"""One booking implementation for dashboard, AI and channel workers."""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.auth import audit


class AvailabilityRequest(BaseModel):
    organization_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    starts_at: datetime


class AppointmentRequest(AvailabilityRequest):
    customer: str = Field(min_length=1, max_length=120)
    contact_id: int | None = Field(default=None, gt=0)


class ChangeAppointment(BaseModel):
    starts_at: datetime


def utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(422, "Specificare il fuso orario nella data")
    return value.astimezone(timezone.utc)


def check_hours(org, start, end):
    hours = json.loads(org["hours_json"])
    if not hours:
        return
    zone = ZoneInfo(org["timezone"])
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    windows = hours.get(str(local_start.weekday()), [])
    # Opening intervals cannot cross midnight. Configure each day explicitly.
    if local_start.date() == local_end.date():
        for opening, closing in windows:
            if opening <= local_start.strftime("%H:%M") and local_end.strftime("%H:%M:%S") <= closing + ":00":
                return
    raise HTTPException(409, "Fuori dagli orari di apertura")


def slot(db, org_id, service_id, starts_at, exclude_id=0):
    org = db.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    service = db.execute("SELECT * FROM services WHERE id=? AND organization_id=? AND active=1",
                         (service_id, org_id)).fetchone()
    if not org or not service:
        raise HTTPException(404, "Servizio inesistente")
    start = utc(starts_at)
    end = start + timedelta(minutes=service["duration_minutes"])
    check_hours(org, start, end)
    busy = db.execute("""SELECT id FROM appointments WHERE organization_id=? AND id<>?
        AND status<>'cancelled' AND starts_at<? AND ends_at>? LIMIT 1""",
        (org_id, exclude_id, end.isoformat(), start.isoformat())).fetchone()
    return start, end, busy


def replay(db, org_id, key, payload):
    if not key:
        return None
    if not 8 <= len(key) <= 150:
        raise HTTPException(422, "Idempotency-Key deve avere tra 8 e 150 caratteri")
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    row = db.execute("SELECT * FROM idempotency_keys WHERE organization_id=? AND key=?", (org_id, key)).fetchone()
    if row:
        if row["request_hash"] != request_hash:
            raise HTTPException(409, "Idempotency-Key già usata per un'altra operazione")
        return json.loads(row["response_json"])
    return None


def remember(db, org_id, key, payload, response):
    if key:
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        db.execute("INSERT INTO idempotency_keys VALUES (?,?,?,?,?)",
                   (org_id, key, request_hash, json.dumps(response), int(time.time())))


def enqueue(db, org_id, kind, payload, dedupe_key):
    db.execute("""INSERT INTO jobs(organization_id,kind,payload_json,dedupe_key,available_at)
        VALUES (?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING""",
               (org_id, kind, json.dumps(payload), dedupe_key, int(time.time())))


def create_booking(database, data, user_id=None, key=None, conversation_id=None):
    payload = {"operation": "create", **data.model_dump(mode="json")}
    with database(write=True, organization_id=data.organization_id) as db:
        if conversation_id is not None:
            conversation = db.execute("SELECT status,contact_id FROM conversations WHERE id=? AND organization_id=?",
                                      (conversation_id, data.organization_id)).fetchone()
            if not conversation or conversation["status"] != "ai" or conversation["contact_id"] != data.contact_id:
                raise HTTPException(409, "Conversazione passata a un operatore")
        previous = replay(db, data.organization_id, key, payload)
        if previous:
            return previous
        start, end, busy = slot(db, data.organization_id, data.service_id, data.starts_at)
        if busy:
            raise HTTPException(409, "Orario occupato")
        if data.contact_id and not db.execute("SELECT id FROM contacts WHERE id=? AND organization_id=?",
                                             (data.contact_id, data.organization_id)).fetchone():
            raise HTTPException(404, "Cliente inesistente")
        google = db.execute("SELECT calendar_id FROM google_connections WHERE organization_id=?", (data.organization_id,)).fetchone()
        sync = "pending" if google else "local"
        status = "pending_sync" if google else "confirmed"
        cur = db.execute("""INSERT INTO appointments(organization_id,customer,service_id,starts_at,ends_at,contact_id,status,sync_status)
            VALUES (?,?,?,?,?,?,?,?)""", (data.organization_id, data.customer, data.service_id,
            start.isoformat(), end.isoformat(), data.contact_id, status, sync))
        result = {"id": cur.lastrowid, "starts_at": start.isoformat(), "ends_at": end.isoformat(),
                  "status": status, "sync_status": sync}
        audit(db, "appointment.created", user_id, data.organization_id, cur.lastrowid)
        if google:
            enqueue(db, data.organization_id, "google_upsert", {"appointment_id": cur.lastrowid}, f"google:create:{cur.lastrowid}")
        remember(db, data.organization_id, key, payload, result)
        return result


def install(database, current_user, require_org):
    router = APIRouter(tags=["booking"])

    @router.get("/api/appointments")
    def appointments(organization_id: int, include_cancelled: bool = False, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            return [dict(row) for row in db.execute("""SELECT a.*,s.name AS service FROM appointments a
                JOIN services s ON s.id=a.service_id AND s.organization_id=a.organization_id
                WHERE a.organization_id=? AND (?=1 OR a.status<>'cancelled') ORDER BY starts_at""",
                (organization_id, int(include_cancelled)))]

    @router.post("/api/appointments")
    def create(data: AppointmentRequest, user_id: int = Depends(current_user),
               key: str | None = Header(None, alias="Idempotency-Key")):
        require_org(user_id, data.organization_id)
        return create_booking(database, data, user_id, key)

    @router.post("/api/booking/availability")
    def availability(data: AvailabilityRequest, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        with database() as db:
            start, end, busy = slot(db, data.organization_id, data.service_id, data.starts_at)
            google = db.execute("SELECT 1 FROM google_connections WHERE organization_id=?", (data.organization_id,)).fetchone()
        return {"available": not bool(busy) if not google else None,
                "local_available": not bool(busy), "requires_external_check": bool(google),
                "starts_at": start.isoformat(), "ends_at": end.isoformat(), "source": "local_database"}

    @router.patch("/api/appointments/{appointment_id}")
    def reschedule(appointment_id: int, organization_id: int, data: ChangeAppointment,
                   key: str | None = Header(None, alias="Idempotency-Key"), user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        payload = {"operation": "reschedule", "id": appointment_id, **data.model_dump(mode="json")}
        with database(write=True, organization_id=organization_id) as db:
            previous = replay(db, organization_id, key, payload)
            if previous:
                return previous
            appointment = db.execute("SELECT * FROM appointments WHERE id=? AND organization_id=? AND status<>'cancelled'",
                                     (appointment_id, organization_id)).fetchone()
            if not appointment:
                raise HTTPException(404, "Appuntamento non trovato")
            if appointment["sync_status"] not in {"local", "synced"}:
                raise HTTPException(409, "Attendi la sincronizzazione del calendario")
            start, end, busy = slot(db, organization_id, appointment["service_id"], data.starts_at, appointment_id)
            if busy:
                raise HTTPException(409, "Orario occupato")
            google = db.execute("SELECT 1 FROM google_connections WHERE organization_id=?", (organization_id,)).fetchone()
            status, sync = ("pending_sync", "pending") if google else ("confirmed", "local")
            db.execute("UPDATE appointments SET starts_at=?,ends_at=?,status=?,sync_status=? WHERE id=? AND organization_id=?",
                       (start.isoformat(), end.isoformat(), status, sync, appointment_id, organization_id))
            result = {"id": appointment_id, "starts_at": start.isoformat(), "ends_at": end.isoformat(), "status": status, "sync_status": sync}
            if google:
                enqueue(db, organization_id, "google_upsert", {"appointment_id": appointment_id},
                        f"google:reschedule:{appointment_id}:{start.isoformat()}:{time.time_ns()}")
            audit(db, "appointment.rescheduled", user_id, organization_id, appointment_id)
            remember(db, organization_id, key, payload, result)
            return result

    @router.delete("/api/appointments/{appointment_id}")
    def cancel(appointment_id: int, organization_id: int, user_id: int = Depends(current_user),
               key: str | None = Header(None, alias="Idempotency-Key")):
        require_org(user_id, organization_id)
        payload = {"operation": "cancel", "id": appointment_id}
        with database(write=True, organization_id=organization_id) as db:
            previous = replay(db, organization_id, key, payload)
            if previous:
                return previous
            appointment = db.execute("SELECT * FROM appointments WHERE id=? AND organization_id=? AND status<>'cancelled'",
                                     (appointment_id, organization_id)).fetchone()
            if not appointment:
                raise HTTPException(404, "Appuntamento non trovato")
            # Pending external reservations can be cancelled safely by deleting
            # their deterministic Google event ID, even after an ambiguous write.
            google = bool(appointment["external_event_id"]) or bool(db.execute(
                "SELECT 1 FROM google_connections WHERE organization_id=?", (organization_id,)).fetchone())
            # Keep the slot reserved until an external cancellation is acknowledged.
            status, sync = ("cancelling", "pending") if google else ("cancelled", "local")
            db.execute("UPDATE appointments SET status=?,sync_status=? WHERE id=? AND organization_id=?",
                       (status, sync, appointment_id, organization_id))
            if google:
                enqueue(db, organization_id, "google_delete", {"appointment_id": appointment_id}, f"google:delete:{appointment_id}")
            audit(db, "appointment.cancelled", user_id, organization_id, appointment_id)
            result = {"ok": True, "id": appointment_id, "status": status, "sync_status": sync}
            remember(db, organization_id, key, payload, result)
            return result

    return router
