import os
import hashlib
import hmac
import secrets
import time
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.getenv("SECRET_AI_DB", str(ROOT / "secretai.db")))
app = FastAPI(title="SecretAI local development API", version="0.1.0")

@contextmanager
def database():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=5000')
    try:
        yield con
        con.commit()
    finally:
        con.close()

with database() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL,
        name TEXT NOT NULL, duration_minutes INTEGER NOT NULL,
        FOREIGN KEY(organization_id) REFERENCES organizations(id)
    );
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL,
        customer TEXT NOT NULL, service_id INTEGER NOT NULL,
        starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
        FOREIGN KEY(organization_id) REFERENCES organizations(id)
    );
    """)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, salt TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memberships (
        user_id INTEGER NOT NULL, organization_id INTEGER NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('owner','member')),
        PRIMARY KEY(user_id, organization_id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(organization_id) REFERENCES organizations(id)
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    # Never seed a publicly readable demo tenant.


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)

def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()

def new_session(db, user_id):
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + 86400))
    return {"access_token": token, "token_type": "bearer", "expires_in": 86400}

@app.post("/api/auth/register", status_code=201)
def register(data: Credentials):
    email = data.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Email non valida")
    salt = secrets.token_hex(16)
    with database() as db:
        try:
            user = db.execute("INSERT INTO users(email,password_hash,salt) VALUES (?,?,?)",
                              (email, hash_password(data.password, salt), salt))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Email già registrata")
        return new_session(db, user.lastrowid)

@app.post("/api/auth/login")
def login(data: Credentials):
    with database() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (data.email.strip().lower(),)).fetchone()
        expected = user["password_hash"] if user else "0" * 64
        salt = user["salt"] if user else "00" * 16
        if not hmac.compare_digest(hash_password(data.password, salt), expected):
            raise HTTPException(401, "Credenziali non valide")
        return new_session(db, user["id"])

def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Autenticazione richiesta")
    token = authorization.removeprefix("Bearer ").strip()
    digest = hashlib.sha256(token.encode()).hexdigest()
    with database() as db:
        row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
                         (digest, int(time.time()))).fetchone()
        if not row:
            raise HTTPException(401, "Sessione scaduta o non valida")
        return row["user_id"]

@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None), user_id: int = Depends(current_user)):
    token = authorization.removeprefix("Bearer ").strip()
    with database() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=? AND user_id=?",
                   (hashlib.sha256(token.encode()).hexdigest(), user_id))
    return {"ok": True}

def require_org(user_id, org_id):
    with database() as db:
        if not db.execute("SELECT 1 FROM memberships WHERE user_id=? AND organization_id=?",
                          (user_id, org_id)).fetchone():
            raise HTTPException(403, "Accesso negato all'azienda")

@app.get("/api/auth/me")
def me(user_id: int = Depends(current_user)):
    with database() as db:
        row = db.execute("SELECT id,email FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row)

class Organization(BaseModel):
    name: str = Field(min_length=1, max_length=120)

class Service(BaseModel):
    organization_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=5, le=480)

class Appointment(BaseModel):
    organization_id: int = Field(gt=0)
    customer: str = Field(min_length=1, max_length=120)
    service_id: int = Field(gt=0)
    starts_at: datetime

class ChatRequest(BaseModel):
    organization_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=4000)

def rows(sql, params=()):
    with database() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]

@app.get("/")
def index():
    return FileResponse(ROOT / "app" / "index.html")

@app.get("/api/organizations")
def organizations(user_id: int = Depends(current_user)):
    return rows("SELECT o.* FROM organizations o JOIN memberships m ON m.organization_id=o.id WHERE m.user_id=? ORDER BY o.id", (user_id,))

@app.post("/api/organizations")
def create_organization(data: Organization, user_id: int = Depends(current_user)):
    with database() as db:
        cur = db.execute("INSERT INTO organizations(name) VALUES (?)", (data.name,))
        db.execute("INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'owner')", (user_id, cur.lastrowid))
        return {"id": cur.lastrowid, "name": data.name}

@app.get("/api/services")
def services(organization_id: int, user_id: int = Depends(current_user)):
    require_org(user_id, organization_id)
    return rows("SELECT * FROM services WHERE organization_id=? ORDER BY id", (organization_id,))

@app.post("/api/services")
def create_service(data: Service, user_id: int = Depends(current_user)):
    require_org(user_id, data.organization_id)
    with database() as db:
        if not db.execute("SELECT 1 FROM organizations WHERE id=?", (data.organization_id,)).fetchone():
            raise HTTPException(404, "Azienda inesistente")
        cur = db.execute("INSERT INTO services(organization_id,name,duration_minutes) VALUES (?,?,?)",
                         (data.organization_id, data.name, data.duration_minutes))
        return {"id": cur.lastrowid, **data.model_dump()}

@app.get("/api/appointments")
def appointments(organization_id: int, user_id: int = Depends(current_user)):
    require_org(user_id, organization_id)
    return rows("SELECT a.*, s.name AS service FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.organization_id=? ORDER BY starts_at",
                (organization_id,))

@app.post("/api/appointments")
def create_appointment(data: Appointment, user_id: int = Depends(current_user)):
    require_org(user_id, data.organization_id)
    from datetime import timedelta
    with database() as db:
        service = db.execute("SELECT * FROM services WHERE id=? AND organization_id=?",
                             (data.service_id, data.organization_id)).fetchone()
        if not service:
            raise HTTPException(404, "Servizio inesistente")
        db.execute('BEGIN IMMEDIATE')
        start = data.starts_at
        if start.tzinfo is None:
            raise HTTPException(422, "Specificare il fuso orario nella data")
        start = start.astimezone(timezone.utc)
        end = start + timedelta(minutes=service["duration_minutes"])
        start_iso, end_iso = start.isoformat(), end.isoformat()
        # UTC timestamps + write transaction avoid local demo conflicts.
        # Production also needs external-calendar verification and idempotency.
        overlaps = db.execute(
            "SELECT 1 FROM appointments WHERE organization_id=? AND starts_at<? AND ends_at>? LIMIT 1",
            (data.organization_id, end_iso, start_iso)
        ).fetchone()
        if overlaps:
            raise HTTPException(409, "Orario occupato")
        cur = db.execute(
            "INSERT INTO appointments(organization_id,customer,service_id,starts_at,ends_at) VALUES (?,?,?,?,?)",
            (data.organization_id, data.customer, data.service_id, start_iso, end_iso))
        return {"id": cur.lastrowid, "starts_at": start_iso, "ends_at": end_iso}

@app.post("/api/chat")
async def chat(data: ChatRequest, user_id: int = Depends(current_user)):
    require_org(user_id, data.organization_id)
    with database() as db:
        org = db.execute("SELECT name FROM organizations WHERE id=?", (data.organization_id,)).fetchone()
        if not org:
            raise HTTPException(404, "Azienda inesistente")
        service_list = [dict(r) for r in db.execute(
            "SELECT name,duration_minutes FROM services WHERE organization_id=?", (data.organization_id,))]
    prompt = (
        "Sei una segretaria AI italiana. Rispondi in modo breve e professionale. "
        "Non dichiarare di aver prenotato, modificato o verificato appuntamenti: "
        "questa chat demo non ha strumenti di scrittura. "
        f"Azienda: {org['name']}. Servizi: {service_list}."
    )
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat",
                json={"model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
                      "stream": False, "messages": [
                          {"role": "system", "content": prompt},
                          {"role": "user", "content": data.message}]})
            response.raise_for_status()
            answer = response.json()["message"]["content"]
            return {"reply": answer, "mode": "ollama"}
    except (httpx.HTTPError, KeyError, ValueError):
        return {"reply": "Il modello AI locale non è disponibile. Avvia Ollama e scarica qwen2.5:3b per attivare la chat.", "mode": "offline"}

# Install local booking routes after all dependencies are defined.
from app.booking_tools import install as install_booking_routes
app.include_router(install_booking_routes(database, current_user, require_org))
