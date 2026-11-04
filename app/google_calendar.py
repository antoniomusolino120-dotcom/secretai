"""Google Calendar OAuth and free/busy integration.

Credentials are supplied by the deployment operator. Tokens are encrypted at rest.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"

class Availability(BaseModel):
    organization_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime

def install(database, current_user, require_org):
    router = APIRouter()

    def setup(db):
        db.executescript("""
        CREATE TABLE IF NOT EXISTS google_connections (
          organization_id INTEGER PRIMARY KEY,
          token_ciphertext TEXT NOT NULL,
          calendar_id TEXT NOT NULL DEFAULT 'primary');
        CREATE TABLE IF NOT EXISTS google_oauth_states (
          state_hash TEXT PRIMARY KEY,
          organization_id INTEGER NOT NULL,
          user_id INTEGER NOT NULL,
          expires_at INTEGER NOT NULL);
        """)

    def config():
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect = os.getenv("GOOGLE_REDIRECT_URI")
        key = os.getenv("SECRET_AI_ENCRYPTION_KEY")
        if not all((client_id, client_secret, redirect, key)):
            raise HTTPException(503, "Google Calendar non configurato")
        try:
            cipher = Fernet(key.encode())
        except (ValueError, TypeError):
            raise HTTPException(503, "Chiave cifratura non valida")
        return client_id, client_secret, redirect, cipher

    @router.post("/api/google/connect")
    def connect(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        client_id, _, redirect, _ = config()
        state = secrets.token_urlsafe(40)
        with database() as db:
            setup(db)
            db.execute("DELETE FROM google_oauth_states WHERE expires_at<?", (int(time.time()),))
            db.execute("INSERT INTO google_oauth_states VALUES (?,?,?,?)",
                       (hashlib.sha256(state.encode()).hexdigest(), organization_id, user_id, int(time.time())+600))
        query = urlencode({"client_id": client_id, "redirect_uri": redirect,
                           "response_type": "code", "scope": SCOPES,
                           "access_type": "offline", "prompt": "consent",
                           "state": state})
        return {"authorization_url": AUTH_URL+"?"+query}

    @router.get("/api/google/callback")
    async def callback(state: str, code: str):
        client_id, client_secret, redirect, cipher = config()
        digest = hashlib.sha256(state.encode()).hexdigest()
        with database() as db:
            setup(db)
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM google_oauth_states WHERE state_hash=? AND expires_at>?",
                             (digest, int(time.time()))).fetchone()
            if not row:
                raise HTTPException(403, "OAuth state non valido o scaduto")
            db.execute("DELETE FROM google_oauth_states WHERE state_hash=?", (digest,))
            organization_id = row["organization_id"]
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(TOKEN_URL, data={
                    "code": code, "client_id": client_id, "client_secret": client_secret,
                    "redirect_uri": redirect, "grant_type": "authorization_code"})
                response.raise_for_status()
                tokens = response.json()
            except (httpx.HTTPError, ValueError):
                raise HTTPException(502, "Scambio OAuth non riuscito")
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise HTTPException(422, "Google non ha restituito un refresh token")
        encrypted = cipher.encrypt(refresh.encode()).decode()
        with database() as db:
            setup(db)
            db.execute("""INSERT INTO google_connections(organization_id,token_ciphertext)
                VALUES (?,?) ON CONFLICT(organization_id) DO UPDATE SET token_ciphertext=excluded.token_ciphertext""",
                (organization_id, encrypted))
        return {"connected": True, "organization_id": organization_id}

    async def access_token(org_id):
        client_id, client_secret, _, cipher = config()
        with database() as db:
            setup(db)
            row = db.execute("SELECT token_ciphertext FROM google_connections WHERE organization_id=?",
                             (org_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Calendario non collegato")
        try:
            refresh = cipher.decrypt(row["token_ciphertext"].encode()).decode()
        except InvalidToken:
            raise HTTPException(503, "Credenziali Google non decifrabili")
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(TOKEN_URL, data={
                    "client_id": client_id, "client_secret": client_secret,
                    "refresh_token": refresh, "grant_type": "refresh_token"})
                response.raise_for_status()
                return response.json()["access_token"]
            except (httpx.HTTPError, ValueError, KeyError):
                raise HTTPException(502, "Aggiornamento token Google non riuscito")

    @router.post("/api/google/freebusy")
    async def freebusy(data: Availability, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id)
        if data.starts_at.tzinfo is None or data.ends_at.tzinfo is None or data.ends_at <= data.starts_at:
            raise HTTPException(422, "Intervallo o fuso orario non valido")
        token = await access_token(data.organization_id)
        with database() as db:
            row = db.execute("SELECT calendar_id FROM google_connections WHERE organization_id=?",
                             (data.organization_id,)).fetchone()
        calendar_id = row["calendar_id"]
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(CALENDAR_URL+"/freeBusy",
                    headers={"Authorization": "Bearer "+token},
                    json={"timeMin": data.starts_at.isoformat(), "timeMax": data.ends_at.isoformat(),
                          "items": [{"id": calendar_id}]})
                response.raise_for_status()
                calendar = response.json()["calendars"][calendar_id]
                if calendar.get("errors"):
                    raise HTTPException(502, "Errore disponibilità Google")
                return {"available": not bool(calendar.get("busy")), "busy": calendar.get("busy", [])}
            except (httpx.HTTPError, KeyError, ValueError):
                raise HTTPException(502, "Google Calendar non disponibile")

    @router.delete("/api/google/connection")
    def disconnect(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            setup(db)
            db.execute("DELETE FROM google_connections WHERE organization_id=?", (organization_id,))
        return {"ok": True}
    return router
