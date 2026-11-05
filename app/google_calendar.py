"""Google OAuth and calendar adapter. Local reservations stay pending until verified."""
import base64
import hashlib
import json
import os
import secrets
import time
from datetime import datetime
from urllib.parse import urlencode, quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth import audit
from app.booking import utc,enqueue
from app.secrets import cipher, encrypt, decrypt

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"


def config():
    values = [os.getenv(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")]
    if not all(values):
        raise HTTPException(503, "Google Calendar non configurato")
    cipher()
    return values


async def access_token(database, org_id):
    client_id, client_secret, _ = config()
    with database() as db:
        row = db.execute("SELECT token_ciphertext FROM google_connections WHERE organization_id=?", (org_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Calendario non collegato")
    refresh = decrypt(row["token_ciphertext"])
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            response = await client.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                "refresh_token": refresh, "grant_type": "refresh_token"})
            response.raise_for_status()
            result = response.json()
            token = result["access_token"]
        except (httpx.HTTPError, ValueError, KeyError):
            raise HTTPException(502, "Aggiornamento token Google non riuscito; verifica il collegamento")
    if result.get("refresh_token"):
        with database(write=True, organization_id=org_id) as db:
            db.execute("UPDATE google_connections SET token_ciphertext=? WHERE organization_id=? AND token_ciphertext=?",
                       (encrypt(result["refresh_token"]), org_id, row["token_ciphertext"]))
    return token


async def google_request(client, method, path, token, **kwargs):
    try:
        response = await client.request(method, CALENDAR_URL + path,
                                        headers={"Authorization": "Bearer " + token, **kwargs.pop("headers", {})}, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Google Calendar non disponibile")


class Availability(BaseModel):
    organization_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime


class CalendarSelection(BaseModel):
    write_calendar_id: str = Field(min_length=1, max_length=500)
    read_calendar_ids: list[str] = Field(min_length=1, max_length=20)


def install(database, current_user, require_org):
    router = APIRouter(tags=["google"])

    @router.post("/api/google/connect")
    def connect(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        client_id, _, redirect = config()
        state, verifier = secrets.token_urlsafe(40), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        with database(write=True, organization_id=organization_id) as db:
            db.execute("DELETE FROM google_oauth_states WHERE expires_at<=? OR (organization_id=? AND user_id=?)", (int(time.time()), organization_id, user_id))
            db.execute("INSERT INTO google_oauth_states(state_hash,organization_id,user_id,expires_at,verifier_ciphertext) VALUES (?,?,?,?,?)",
                       (hashlib.sha256(state.encode()).hexdigest(), organization_id, user_id, int(time.time())+600, encrypt(verifier)))
        query = urlencode({"client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
                           "access_type": "offline", "prompt": "consent", "state": state,
                           "code_challenge": challenge, "code_challenge_method": "S256"})
        return {"authorization_url": AUTH_URL+"?"+query}

    @router.get("/api/google/callback")
    async def callback(request: Request, state: str, code: str):
        client_id, client_secret, redirect = config()
        digest = hashlib.sha256(state.encode()).hexdigest()
        with database(write=True) as db:
            row = db.execute("SELECT * FROM google_oauth_states WHERE state_hash=? AND expires_at>?",
                             (digest, int(time.time()))).fetchone()
            if not row:
                raise HTTPException(403, "OAuth state non valido o scaduto")
            deleted = db.execute("DELETE FROM google_oauth_states WHERE state_hash=?", (digest,))
            if deleted.rowcount != 1:
                raise HTTPException(403, "OAuth state già utilizzato")
            org_id, user_id = row["organization_id"], row["user_id"]
        require_org(user_id, org_id, owner=True)
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(TOKEN_URL, data={"code": code, "client_id": client_id,
                    "client_secret": client_secret, "redirect_uri": redirect, "grant_type": "authorization_code",
                    "code_verifier": decrypt(row["verifier_ciphertext"])})
                response.raise_for_status()
                tokens = response.json()
            except httpx.HTTPStatusError as exc:
                try:
                    error_code = exc.response.json().get("error", "unknown")
                except ValueError:
                    error_code = "non_json_response"
                allowed_codes = {"invalid_client", "invalid_grant", "invalid_request", "unauthorized_client", "unsupported_grant_type", "access_denied"}
                safe_code = error_code if isinstance(error_code, str) and error_code in allowed_codes else "unknown"
                raise HTTPException(502, f"Scambio OAuth non riuscito ({safe_code}); ricollega il calendario")
            except (httpx.HTTPError, ValueError):
                raise HTTPException(502, "Scambio OAuth non riuscito (network_or_response); ricollega il calendario")
        if not tokens.get("refresh_token"):
            raise HTTPException(422, "Google non ha restituito un refresh token; ripeti il consenso")
        with database(write=True, organization_id=org_id) as db:
            db.execute("""INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,?)
                ON CONFLICT(organization_id) DO UPDATE SET token_ciphertext=excluded.token_ciphertext""",
                       (org_id, encrypt(tokens["refresh_token"])))
            enqueue(db,org_id,"google_reconcile",{"calendar_id":"primary"},f"google:connect:{org_id}:{time.time_ns()}")
            audit(db, "google.connected", user_id, org_id, org_id)
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(os.getenv("SECRET_AI_PUBLIC_URL", "https://secretai-iota.vercel.app").rstrip("/") + "/#connections", status_code=303)
        return {"connected": True, "organization_id": org_id}

    @router.get("/api/google/calendars")
    async def calendars(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        token = await access_token(database, organization_id)
        async with httpx.AsyncClient(timeout=20) as client:
            data = await google_request(client, "GET", "/users/me/calendarList", token, params={"maxResults": 250})
        return [{k: item.get(k) for k in ("id", "summary", "timeZone", "accessRole", "primary")} for item in data.get("items", [])]

    @router.put("/api/google/calendars")
    async def select_calendars(organization_id: int, data: CalendarSelection, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        token = await access_token(database, organization_id)
        async with httpx.AsyncClient(timeout=20) as client:
            info = await google_request(client, "GET", "/users/me/calendarList/" + quote(data.write_calendar_id, safe=""), token)
            if info.get("accessRole") not in {"owner", "writer"}:
                raise HTTPException(422, "Seleziona un calendario scrivibile")
        read_ids = list(dict.fromkeys([data.write_calendar_id, *data.read_calendar_ids]))
        with database(write=True, organization_id=organization_id) as db:
            current=db.execute('SELECT calendar_id FROM google_connections WHERE organization_id=?',(organization_id,)).fetchone()
            if current['calendar_id']!=data.write_calendar_id and db.execute("SELECT 1 FROM appointments WHERE organization_id=? AND external_event_id IS NOT NULL AND status<>'cancelled' LIMIT 1", (organization_id,)).fetchone():
                raise HTTPException(409, "Calendario di scrittura bloccato finché ci sono appuntamenti sincronizzati")
            db.execute("UPDATE google_connections SET calendar_id=?,read_calendar_ids_json=? WHERE organization_id=?",
                       (data.write_calendar_id, json.dumps(read_ids), organization_id))
            for row in db.execute('SELECT DISTINCT calendar_id FROM external_busy WHERE organization_id=?',(organization_id,)).fetchall():
                if row['calendar_id'] not in read_ids:db.execute('DELETE FROM external_busy WHERE organization_id=? AND calendar_id=?',(organization_id,row['calendar_id']))
            for cid in read_ids:enqueue(db,organization_id,'google_reconcile',{'calendar_id':cid},f'google:selection:{organization_id}:{cid}:{time.time_ns()}')
            audit(db, "google.calendars_selected", user_id, organization_id, organization_id)
        return {"ok": True}

    @router.post("/api/google/freebusy")
    async def freebusy(data: Availability, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        start, end = utc(data.starts_at), utc(data.ends_at)
        if end <= start:
            raise HTTPException(422, "Intervallo non valido")
        token = await access_token(database, data.organization_id)
        with database() as db:
            row = db.execute("SELECT read_calendar_ids_json FROM google_connections WHERE organization_id=?", (data.organization_id,)).fetchone()
        ids = json.loads(row["read_calendar_ids_json"])
        async with httpx.AsyncClient(timeout=20) as client:
            result = await google_request(client, "POST", "/freeBusy", token, json={"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": i} for i in ids]})
        calendars = result.get("calendars", {})
        if any(i not in calendars or calendars[i].get("errors") for i in ids):
            raise HTTPException(502, "Impossibile verificare tutti i calendari")
        busy = [interval for i in ids for interval in calendars[i].get("busy", [])]
        return {"available": not busy, "busy": busy}

    @router.delete("/api/google/connection")
    def disconnect(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database(write=True, organization_id=organization_id) as db:
            if db.execute("SELECT 1 FROM appointments WHERE organization_id=? AND status<>'cancelled' AND sync_status<>'local' LIMIT 1", (organization_id,)).fetchone():
                raise HTTPException(409, "Gestisci gli appuntamenti collegati prima di scollegare Google")
            db.execute("DELETE FROM google_connections WHERE organization_id=?", (organization_id,))
            db.execute('DELETE FROM google_cursors WHERE organization_id=?',(organization_id,))
            db.execute('DELETE FROM google_watches WHERE organization_id=?',(organization_id,))
            db.execute('DELETE FROM external_busy WHERE organization_id=?',(organization_id,))
            db.execute("DELETE FROM google_oauth_states WHERE organization_id=?", (organization_id,))
            audit(db, "google.disconnected", user_id, organization_id, organization_id)
        return {"ok": True}
    return router
