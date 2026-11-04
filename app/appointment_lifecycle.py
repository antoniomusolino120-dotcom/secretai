"""Tenant-scoped appointment lifecycle, with atomic rescheduling and cancellation."""
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

class ChangeAppointment(BaseModel):
    starts_at: datetime

def install(database, current_user, require_org):
    router = APIRouter()

    @router.delete("/api/appointments/{appointment_id}")
    def cancel(appointment_id: int, organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            appointment = db.execute("SELECT id FROM appointments WHERE id=? AND organization_id=?",
                                     (appointment_id, organization_id)).fetchone()
            if not appointment:
                raise HTTPException(404, "Appuntamento non trovato")
            db.execute("DELETE FROM appointments WHERE id=? AND organization_id=?",
                       (appointment_id, organization_id))
        return {"ok": True, "id": appointment_id}

    @router.patch("/api/appointments/{appointment_id}")
    def reschedule(appointment_id: int, organization_id: int, data: ChangeAppointment,
                   user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        if data.starts_at.tzinfo is None:
            raise HTTPException(422, "Specificare il fuso orario")
        start = data.starts_at.astimezone(timezone.utc)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            appointment = db.execute(
                """SELECT a.id,s.duration_minutes FROM appointments a
                JOIN services s ON s.id=a.service_id AND s.organization_id=a.organization_id
                WHERE a.id=? AND a.organization_id=?""",
                (appointment_id, organization_id)).fetchone()
            if not appointment:
                raise HTTPException(404, "Appuntamento non trovato")
            end = start + timedelta(minutes=appointment["duration_minutes"])
            start_iso, end_iso = start.isoformat(), end.isoformat()
            conflict = db.execute(
                """SELECT id FROM appointments WHERE organization_id=? AND id<>?
                AND starts_at<? AND ends_at>? LIMIT 1""",
                (organization_id, appointment_id, end_iso, start_iso)).fetchone()
            if conflict:
                raise HTTPException(409, "Orario occupato")
            db.execute("UPDATE appointments SET starts_at=?,ends_at=? WHERE id=? AND organization_id=?",
                       (start_iso, end_iso, appointment_id, organization_id))
        return {"id": appointment_id, "starts_at": start_iso, "ends_at": end_iso}
    return router
