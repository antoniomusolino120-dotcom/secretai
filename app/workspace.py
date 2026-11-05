"""Company configuration, service catalogue, CRM and unified conversations."""
import json
import re
import secrets
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth import audit
from app.booking import enqueue, replay, remember


class Organization(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class Settings(Organization):
    timezone: str = "Europe/Rome"
    instructions: str = Field(default="", max_length=8000)
    knowledge: str = Field(default="", max_length=40000)
    hours: dict[str, list[tuple[str, str]]] = Field(default_factory=dict)
    assistant_enabled: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Fuso orario non valido")
        return value

    @field_validator("hours")
    @classmethod
    def valid_hours(cls, value):
        for day, intervals in value.items():
            if day not in {str(i) for i in range(7)} or len(intervals) > 6:
                raise ValueError("Giorno o numero di intervalli non valido")
            previous = "00:00"
            for opening, closing in sorted(intervals):
                if not all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", x) for x in (opening, closing)):
                    raise ValueError("Usa orari HH:MM")
                if opening >= closing or opening < previous:
                    raise ValueError("Intervalli sovrapposti o non validi")
                previous = closing
        return value


class Service(BaseModel):
    organization_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=5, le=480)
    price_cents: int = Field(default=0, ge=0, le=10_000_000)
    active: bool = True


class Contact(BaseModel):
    organization_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=8000)


class Conversation(BaseModel):
    organization_id: int = Field(gt=0)
    contact_id: int | None = Field(default=None, gt=0)


class Reply(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class Handoff(BaseModel):
    status: str = Field(pattern="^(ai|human|closed)$")


def install(database, current_user, require_org):
    router = APIRouter(tags=["workspace"])

    @router.get("/api/organizations")
    def organizations(user_id: int = Depends(current_user)):
        with database() as db:
            return [dict(row) for row in db.execute("""SELECT o.id,o.name,o.timezone,m.role FROM organizations o
                JOIN memberships m ON m.organization_id=o.id WHERE m.user_id=? ORDER BY o.id""", (user_id,))]

    @router.post("/api/organizations")
    def create_organization(data: Organization, user_id: int = Depends(current_user)):
        if not data.name.strip():
            raise HTTPException(422, "Inserisci un nome")
        with database(write=True) as db:
            cur = db.execute("INSERT INTO organizations(name) VALUES (?)", (data.name.strip(),))
            db.execute("INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'owner')", (user_id, cur.lastrowid))
            audit(db, "organization.created", user_id, cur.lastrowid, cur.lastrowid)
            return {"id": cur.lastrowid, "name": data.name.strip()}

    @router.get("/api/organizations/{organization_id}/settings")
    def settings(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            result = dict(db.execute("SELECT * FROM organizations WHERE id=?", (organization_id,)).fetchone())
        result["hours"] = json.loads(result.pop("hours_json"))
        result["assistant_enabled"] = bool(result["assistant_enabled"])
        return result

    @router.put("/api/organizations/{organization_id}/settings")
    def save_settings(organization_id: int, data: Settings, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        if not data.name.strip():
            raise HTTPException(422, "Inserisci un nome")
        if data.assistant_enabled and not any(data.hours.values()):
            raise HTTPException(422, "Configura gli orari prima di attivare la segretaria")
        with database(write=True, organization_id=organization_id) as db:
            if data.assistant_enabled and not db.execute("SELECT 1 FROM services WHERE organization_id=? AND active=1", (organization_id,)).fetchone():
                raise HTTPException(422, "Aggiungi almeno un servizio attivo")
            db.execute("""UPDATE organizations SET name=?,timezone=?,instructions=?,knowledge=?,hours_json=?,assistant_enabled=? WHERE id=?""",
                       (data.name.strip(), data.timezone, data.instructions, data.knowledge,
                        json.dumps(data.hours), int(data.assistant_enabled), organization_id))
            audit(db, "organization.settings_updated", user_id, organization_id, organization_id)
        return {"ok": True}

    @router.get("/api/services")
    def services(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            return [dict(row) for row in db.execute("SELECT * FROM services WHERE organization_id=? ORDER BY id", (organization_id,))]

    @router.post("/api/services")
    def create_service(data: Service, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id, owner=True)
        with database(write=True, organization_id=data.organization_id) as db:
            cur = db.execute("INSERT INTO services(organization_id,name,duration_minutes,price_cents,active) VALUES (?,?,?,?,?)",
                             (data.organization_id, data.name, data.duration_minutes, data.price_cents, int(data.active)))
            audit(db, "service.created", user_id, data.organization_id, cur.lastrowid)
            return {"id": cur.lastrowid, **data.model_dump()}

    @router.put("/api/services/{service_id}")
    def update_service(service_id: int, data: Service, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id, owner=True)
        with database(write=True, organization_id=data.organization_id) as db:
            result = db.execute("UPDATE services SET name=?,duration_minutes=?,price_cents=?,active=? WHERE id=? AND organization_id=?",
                                (data.name, data.duration_minutes, data.price_cents, int(data.active), service_id, data.organization_id))
            if result.rowcount != 1:
                raise HTTPException(404, "Servizio inesistente")
            audit(db, "service.updated", user_id, data.organization_id, service_id)
        return {"ok": True}

    @router.get("/api/contacts")
    def contacts(organization_id: int, q: str = "", limit: int = 100, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            return [dict(row) for row in db.execute("SELECT * FROM contacts WHERE organization_id=? AND LOWER(name) LIKE ? ORDER BY id DESC LIMIT ?",
                        (organization_id, "%" + q[:120].lower() + "%", min(max(limit, 1), 500)))]

    @router.post("/api/contacts")
    def create_contact(data: Contact, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        with database(write=True, organization_id=data.organization_id) as db:
            cur = db.execute("INSERT INTO contacts(organization_id,name,email,phone,notes,created_at) VALUES (?,?,?,?,?,?)",
                             (data.organization_id, data.name, data.email, data.phone, data.notes, int(time.time())))
            audit(db, "contact.created", user_id, data.organization_id, cur.lastrowid)
            return {"id": cur.lastrowid, **data.model_dump()}

    @router.put("/api/contacts/{contact_id}")
    def update_contact(contact_id: int, data: Contact, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        with database(write=True, organization_id=data.organization_id) as db:
            changed = db.execute("UPDATE contacts SET name=?,email=?,phone=?,notes=? WHERE id=? AND organization_id=?",
                                 (data.name, data.email, data.phone, data.notes, contact_id, data.organization_id))
            if changed.rowcount != 1:
                raise HTTPException(404, "Cliente inesistente")
            audit(db, "contact.updated", user_id, data.organization_id, contact_id)
        return {"ok": True}

    @router.get("/api/conversations")
    def conversations(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            return [dict(row) for row in db.execute("""SELECT c.*,p.name AS customer,
                (SELECT body FROM messages m WHERE m.conversation_id=c.id AND m.organization_id=c.organization_id ORDER BY m.id DESC LIMIT 1) AS last_message
                FROM conversations c LEFT JOIN contacts p ON p.id=c.contact_id AND p.organization_id=c.organization_id
                WHERE c.organization_id=? ORDER BY c.updated_at DESC,c.id DESC LIMIT 100""", (organization_id,))]

    @router.post("/api/conversations")
    def create_conversation(data: Conversation, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        with database(write=True, organization_id=data.organization_id) as db:
            if data.contact_id and not db.execute("SELECT 1 FROM contacts WHERE id=? AND organization_id=?", (data.contact_id, data.organization_id)).fetchone():
                raise HTTPException(404, "Cliente inesistente")
            cur = db.execute("INSERT INTO conversations(organization_id,contact_id,channel,external_id,updated_at) VALUES (?,?,'web',?,?)",
                             (data.organization_id, data.contact_id, secrets.token_urlsafe(20), int(time.time())))
            return {"id": cur.lastrowid, "channel": "web"}

    def scoped_conversation(db, conversation_id, organization_id):
        row = db.execute("SELECT * FROM conversations WHERE id=? AND organization_id=?", (conversation_id, organization_id)).fetchone()
        if not row:
            raise HTTPException(404, "Conversazione inesistente")
        return row

    @router.get("/api/conversations/{conversation_id}/messages")
    def messages(conversation_id: int, organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            scoped_conversation(db, conversation_id, organization_id)
            return [dict(row) for row in db.execute("SELECT * FROM messages WHERE conversation_id=? AND organization_id=? ORDER BY id LIMIT 500",
                                                  (conversation_id, organization_id))]

    @router.put("/api/conversations/{conversation_id}/handoff")
    def handoff(conversation_id: int, organization_id: int, data: Handoff, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database(write=True, organization_id=organization_id) as db:
            scoped_conversation(db, conversation_id, organization_id)
            db.execute("UPDATE conversations SET status=?,updated_at=? WHERE id=? AND organization_id=?",
                       (data.status, int(time.time()), conversation_id, organization_id))
            audit(db, "conversation." + data.status, user_id, organization_id, conversation_id)
        return {"ok": True}

    @router.post("/api/conversations/{conversation_id}/reply")
    def reply(conversation_id: int, organization_id: int, data: Reply, user_id: int = Depends(current_user),
              key: str | None = Header(None, alias="Idempotency-Key")):
        require_org(user_id, organization_id)
        with database(write=True, organization_id=organization_id) as db:
            payload = {"operation": "reply", "conversation_id": conversation_id, "body": data.body}
            previous = replay(db, organization_id, key, payload)
            if previous:
                return previous
            row = scoped_conversation(db, conversation_id, organization_id)
            if row["status"] != "human":
                raise HTTPException(409, "Prendi in carico la conversazione prima di rispondere")
            status = "sent" if row["channel"] == "web" else "pending"
            cur = db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,delivery_status) VALUES (?,?,'outbound',?,?,?)",
                             (organization_id, conversation_id, data.body, int(time.time()), status))
            if status == "pending":
                enqueue(db, organization_id, "meta_send", {"message_id": cur.lastrowid}, f"meta:reply:{cur.lastrowid}")
            db.execute("UPDATE conversations SET updated_at=? WHERE id=? AND organization_id=?", (int(time.time()), conversation_id, organization_id))
            audit(db, "conversation.reply", user_id, organization_id, cur.lastrowid)
            result = {"id": cur.lastrowid, "delivery_status": status}
            remember(db, organization_id, key, payload, result)
        return result

    @router.get("/api/organizations/{organization_id}/statistics")
    def statistics(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            result = {}
            for key, table in [("customers", "contacts"), ("conversations", "conversations"), ("messages", "messages")]:
                result[key] = db.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE organization_id=?", (organization_id,)).fetchone()["n"]
            result["appointments"] = db.execute("SELECT COUNT(*) AS n FROM appointments WHERE organization_id=? AND status<>'cancelled'", (organization_id,)).fetchone()["n"]
            result["human_queue"] = db.execute("SELECT COUNT(*) AS n FROM conversations WHERE organization_id=? AND status='human'", (organization_id,)).fetchone()["n"]
            result["failed_jobs"] = db.execute("SELECT COUNT(*) AS n FROM jobs WHERE organization_id=? AND status IN ('failed','attention')", (organization_id,)).fetchone()["n"]
            return result

    @router.get("/api/organizations/{organization_id}/audit")
    def audit_log(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database() as db:
            return [dict(row) for row in db.execute("SELECT * FROM audit_events WHERE organization_id=? ORDER BY id DESC LIMIT 100", (organization_id,))]

    @router.get("/api/organizations/{organization_id}/jobs")
    def jobs(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database() as db:
            return [dict(row) for row in db.execute("SELECT id,kind,status,attempts,last_error,available_at FROM jobs WHERE organization_id=? ORDER BY id DESC LIMIT 100", (organization_id,))]

    @router.post("/api/organizations/{organization_id}/jobs/{job_id}/retry")
    def retry_job(organization_id: int, job_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database(write=True, organization_id=organization_id) as db:
            job = db.execute("SELECT kind,status FROM jobs WHERE id=? AND organization_id=?", (job_id, organization_id)).fetchone()
            if not job:
                raise HTTPException(404, "Operazione inesistente")
            if job["kind"] not in {"google_upsert", "google_delete", "stripe_reconcile", "ai_reply"} or job["status"] not in {"failed", "attention"}:
                raise HTTPException(409, "Operazione non ripetibile automaticamente")
            db.execute("UPDATE jobs SET status='pending',attempts=0,available_at=?,last_error='' WHERE id=? AND organization_id=?", (int(time.time()), job_id, organization_id))
            audit(db, "job.retry_requested", user_id, organization_id, job_id)
        return {"ok": True}

    return router
