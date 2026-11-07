"""Idempotent Google event writes, with external conflict checks."""
import hashlib
import json
import time
from zoneinfo import ZoneInfo
from datetime import datetime
from app.booking import enqueue
from urllib.parse import quote

import httpx

from app.google_calendar import access_token, CALENDAR_URL, google_request
from app.jobs import AttentionRequired


def event_id(org_id, appointment_id):
    return hashlib.sha256(f"secretai:{org_id}:{appointment_id}".encode()).hexdigest()


def handlers(database):
    async def sync(job, payload):
        org_id, appointment_id = job["organization_id"], payload["appointment_id"]
        token = await access_token(database, org_id)
        with database(write=True, organization_id=org_id) as db:
            appointment = db.execute("""SELECT a.*,s.name AS service,s.duration_minutes,s.price_cents,c.phone AS customer_phone,c.email AS customer_email FROM appointments a JOIN services s
                ON s.id=a.service_id AND s.organization_id=a.organization_id LEFT JOIN contacts c ON c.id=a.contact_id AND c.organization_id=a.organization_id WHERE a.id=? AND a.organization_id=?""",
                (appointment_id, org_id)).fetchone()
            connection = db.execute("SELECT * FROM google_connections WHERE organization_id=?", (org_id,)).fetchone()
            if not appointment or not connection:
                raise AttentionRequired("Calendar or reservation no longer available")
            if appointment["status"] == "cancelled":
                return
            if job["kind"] == "google_upsert" and appointment["status"] == "cancelling":
                return
            eid = appointment["external_event_id"] or event_id(org_id, appointment_id)
            prefix = "/calendars/" + quote(connection["calendar_id"], safe="") + "/events"
            headers = {"Authorization": "Bearer " + token}
            async with httpx.AsyncClient(timeout=20) as client:
                if job["kind"] == "google_delete":
                    result = await client.delete(CALENDAR_URL+prefix+"/"+eid, headers=headers)
                    if result.status_code not in {200, 204, 404, 410}:
                        result.raise_for_status()
                    db.execute("UPDATE appointments SET status='cancelled',sync_status='synced' WHERE id=? AND organization_id=?", (appointment_id, org_id))
                    db.execute('DELETE FROM appointment_holds WHERE organization_id=? AND appointment_id=?',(org_id,appointment_id))
                    return
                # Google freeBusy includes our own existing event. Use event listing
                # on the write calendar so it can be excluded by deterministic ID.
                page = None
                while True:
                    params = {"timeMin": appointment["starts_at"], "timeMax": appointment["ends_at"],
                              "singleEvents": "true", "maxResults": 2500}
                    if page:
                        params["pageToken"] = page
                    events = await google_request(client, "GET", prefix, token, params=params)
                    if any(e.get("id") != eid and e.get("status") != "cancelled" and e.get("transparency") != "transparent" for e in events.get("items", [])):
                        db.execute("UPDATE appointments SET sync_status='attention' WHERE id=? AND organization_id=?", (appointment_id, org_id))
                        # Commit the diagnostic before reporting to the outbox.
                        break
                    page = events.get("nextPageToken")
                    if not page:
                        break
                conflict = any(e.get("id") != eid and e.get("status") != "cancelled" and e.get("transparency") != "transparent" for e in events.get("items", []))
                read_ids = [i for i in json.loads(connection["read_calendar_ids_json"]) if i != connection["calendar_id"]]
                if read_ids and not conflict:
                    busy = await google_request(client, "POST", "/freeBusy", token, json={"timeMin": appointment["starts_at"], "timeMax": appointment["ends_at"], "items": [{"id": i} for i in read_ids]})
                    calendars = busy.get("calendars", {})
                    if any(i not in calendars or calendars[i].get("errors") for i in read_ids):
                        raise AttentionRequired("Unable to check all selected calendars")
                    conflict = any(calendars[i].get("busy") for i in read_ids)
                if conflict:
                    db.execute("UPDATE appointments SET sync_status='attention' WHERE id=? AND organization_id=?", (appointment_id, org_id))
                else:
                    details = [
                        "Cliente: " + appointment["customer"],
                        "Servizio: " + appointment["service"],
                        "Durata: " + str(appointment["duration_minutes"]) + " minuti",
                    ]
                    if appointment["price_cents"] is not None:
                        details.append("Prezzo: " + f"{appointment['price_cents'] / 100:.2f}" + " EUR")
                    if appointment["customer_phone"]:
                        details.append("Telefono: " + appointment["customer_phone"])
                    if appointment["customer_email"]:
                        details.append("Email: " + appointment["customer_email"])
                    try:
                        intake = json.loads(appointment["intake_json"] or "[]")
                        if isinstance(intake, dict):
                            details.extend(str(k) + ": " + str(v) for k, v in intake.items() if v is not None)
                        elif isinstance(intake, list):
                            for answer in intake:
                                if isinstance(answer, dict):
                                    details.append(str(answer.get("label", answer.get("question", "Nota"))) + ": " + str(answer.get("answer", answer.get("value", ""))))
                    except (ValueError, TypeError):
                        pass
                    details.append("Stato: confermato")
                    body = {"summary": appointment["customer"] + " — " + appointment["service"] + " | SecretAI",
                            "description": "\n".join(details),
                            "start": {"dateTime": appointment["starts_at"]}, "end": {"dateTime": appointment["ends_at"]},
                            "extendedProperties": {"private": {"secretai_org": str(org_id), "secretai_appointment": str(appointment_id)}}}
                    existing = await client.get(CALENDAR_URL+prefix+"/"+eid, headers=headers)
                    if existing.status_code == 200:
                        remote = existing.json()
                        if remote.get("extendedProperties", {}).get("private", {}) != body["extendedProperties"]["private"]:
                            raise AttentionRequired("Calendar event identity does not match reservation")
                        if remote.get("status") == "cancelled":
                            raise AttentionRequired("Event was cancelled outside SecretAI")
                        await google_request(client, "PATCH", prefix+"/"+eid, token, json=body,
                                             headers={"If-Match": remote["etag"]})
                    elif existing.status_code in {404, 410}:
                        # For an already-synced appointment, absence means a human deleted
                        # it externally; do not silently recreate it.
                        if appointment["external_event_id"]:
                            raise AttentionRequired("Event was removed outside SecretAI")
                        response = await client.post(CALENDAR_URL+prefix, headers=headers, json={"id": eid, **body})
                        if response.status_code == 409:
                            raise AttentionRequired("Event already exists; verify its current state")
                        response.raise_for_status()
                    else:
                        existing.raise_for_status()
                    db.execute("UPDATE appointments SET status='confirmed',sync_status='synced',external_event_id=? WHERE id=? AND organization_id=?",
                               (eid, appointment_id, org_id))
                    db.execute('DELETE FROM appointment_holds WHERE organization_id=? AND appointment_id=?',(org_id,appointment_id))
                    # Notify the original WhatsApp contact only after Google confirms the event.
                    conv=db.execute("SELECT c.id FROM conversations c WHERE c.organization_id=? AND c.channel='whatsapp' AND c.contact_id=? AND c.status='ai' ORDER BY c.id DESC LIMIT 1",(org_id,appointment['contact_id'])).fetchone()
                    if conv:
                        from app.channel_controls import policy
                        revision=policy(db,org_id,'whatsapp')['revision']
                        tz=db.execute('SELECT timezone FROM organizations WHERE id=?',(org_id,)).fetchone()['timezone']
                        when=datetime.fromisoformat(appointment['starts_at']).astimezone(ZoneInfo(tz)).strftime('%d/%m/%Y alle %H:%M')
                        content=f"Ti confermo l'appuntamento per {appointment['service']} il {when}, a nome di {appointment['customer']}."
                        external=f"calendar-confirmed:{appointment_id}"
                        existing=db.execute("SELECT id FROM messages WHERE organization_id=? AND external_id=?",(org_id,external)).fetchone()
                        if not existing:
                            mid=db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,delivery_status,external_id) VALUES (?,?,'outbound',?,?,'pending',?)",(org_id,conv['id'],content,int(time.time()),external)).lastrowid
                            enqueue(db,org_id,'meta_send',{'message_id':mid,'automation_revision':revision},external)

        if conflict:
            raise AttentionRequired("External calendar conflict; reservation remains unconfirmed")

    return {"google_upsert": sync, "google_delete": sync}
