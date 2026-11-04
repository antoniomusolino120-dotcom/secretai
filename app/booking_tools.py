"""Safe, deterministic local booking tools. No external calendar side effects."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/booking", tags=["booking"])

class AvailabilityRequest(BaseModel):
    organization_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    starts_at: datetime

def install(database, current_user, require_org):
    @router.post("/availability")
    def availability(data: AvailabilityRequest, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        if data.starts_at.tzinfo is None:
            raise HTTPException(422, "Specificare il fuso orario")
        with database() as db:
            service = db.execute(
                "SELECT duration_minutes FROM services WHERE id=? AND organization_id=?",
                (data.service_id, data.organization_id)).fetchone()
            if not service:
                raise HTTPException(404, "Servizio inesistente")
            start = data.starts_at.astimezone(timezone.utc)
            end = start + timedelta(minutes=service["duration_minutes"])
            busy = db.execute(
                "SELECT 1 FROM appointments WHERE organization_id=? AND starts_at<? AND ends_at>? LIMIT 1",
                (data.organization_id, end.isoformat(), start.isoformat())).fetchone()
            return {"available": not bool(busy), "starts_at": start.isoformat(),
                    "ends_at": end.isoformat(), "source": "local_database"}
    return router
