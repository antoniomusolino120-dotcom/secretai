"""Revocable opaque sessions, cookie CSRF, email verification and password reset."""
import hashlib
import hmac
import os
import secrets
import smtplib
import time
from email.message import EmailMessage
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

COOKIE = "secretai_session"
SESSION_TTL = 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()


def audit(db, action, user_id=None, organization_id=None, entity_id=""):
    db.execute("INSERT INTO audit_events(organization_id,user_id,action,entity_id,created_at) VALUES (?,?,?,?,?)",
               (organization_id, user_id, action, str(entity_id), int(time.time())))


def production():
    return os.getenv("SECRET_AI_ENV", "development") == "production"


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class ExistingAccountLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class EmailRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class PasswordReset(TokenRequest):
    password: str = Field(min_length=12, max_length=256)


def install(database):
    router = APIRouter(prefix="/api/auth", tags=["identity"])

    def current_user(request: Request):
        authorization = request.headers.get("authorization", "")
        bearer = authorization.startswith("Bearer ")
        token = authorization[7:].strip() if bearer else request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Autenticazione richiesta")
        with database() as db:
            row = db.execute("SELECT user_id,csrf_hash FROM sessions WHERE token_hash=? AND expires_at>?",
                             (digest(token), int(time.time()))).fetchone()
        if not row:
            raise HTTPException(401, "Sessione scaduta o non valida")
        if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token", "")
            if not row["csrf_hash"] or not hmac.compare_digest(row["csrf_hash"], digest(csrf)):
                raise HTTPException(403, "Token CSRF non valido")
        return row["user_id"]

    def require_org(user_id, org_id, owner=False):
        with database() as db:
            row = db.execute("SELECT role FROM memberships WHERE user_id=? AND organization_id=?",
                             (user_id, org_id)).fetchone()
        if not row or (owner and row["role"] != "owner"):
            raise HTTPException(403, "Accesso negato all'azienda")

    def new_session(db, user_id, response):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at,csrf_hash) VALUES (?,?,?,?)",
                   (digest(token), user_id, int(time.time()) + SESSION_TTL, digest(csrf)))
        response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True,
                            secure=production(), samesite="lax", path="/")
        return {"access_token": token, "csrf_token": csrf, "token_type": "bearer", "expires_in": SESSION_TTL}

    def mail_ready():
        return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM") and os.getenv("SECRET_AI_PUBLIC_URL"))

    def send_challenge(db, user, purpose):
        token = secrets.token_urlsafe(40)
        db.execute("DELETE FROM auth_challenges WHERE user_id=? AND purpose=?", (user["id"], purpose))
        db.execute("INSERT INTO auth_challenges VALUES (?,?,?,?)",
                   (digest(token), user["id"], purpose, int(time.time()) + 1800))
        # The token belongs to the browser fragment: HTTP logs never receive it.
        base = os.environ["SECRET_AI_PUBLIC_URL"].rstrip("/")
        message = EmailMessage()
        message["From"], message["To"] = os.environ["SMTP_FROM"], user["email"]
        message["Subject"] = "SecretAI — " + ("conferma email" if purpose == "verify" else "recupera password")
        message.set_content(f"Apri questo link entro 30 minuti: {base}/#{purpose}={token}\nSe non hai richiesto l'operazione, ignora questa email.")
        try:
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
                smtp.starttls()
                if os.getenv("SMTP_USERNAME"):
                    smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise HTTPException(503, "Invio email non disponibile; riprova")

    @router.post("/register", status_code=201)
    def register(data: Credentials, response: Response):
        email, salt = str(data.email).lower(), secrets.token_hex(16)
        if production() and not mail_ready():
            raise HTTPException(503, "Registrazione temporaneamente non disponibile")
        try:
            with database(write=True) as db:
                user = db.execute("INSERT INTO users(email,password_hash,salt) VALUES (?,?,?)",
                                  (email, hash_password(data.password, salt), salt))
                audit(db, "auth.register", user_id=user.lastrowid)
                if production():
                    send_challenge(db, {"id": user.lastrowid, "email": email}, "verify")
                    return {"verification_required": True}
                return new_session(db, user.lastrowid, response)
        except IntegrityError:
            raise HTTPException(409, "Email già registrata")

    @router.post("/login")
    def login(data: ExistingAccountLogin, response: Response):
        with database(write=True) as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (str(data.email).lower(),)).fetchone()
            expected, salt = (user["password_hash"], user["salt"]) if user else ("0" * 64, "00" * 16)
            if not hmac.compare_digest(hash_password(data.password, salt), expected):
                raise HTTPException(401, "Credenziali non valide")
            if production() and not user["email_verified"]:
                raise HTTPException(403, "Conferma prima il tuo indirizzo email")
            audit(db, "auth.login", user_id=user["id"])
            return new_session(db, user["id"], response)

    @router.get("/me")
    def me(user_id: int = Depends(current_user)):
        with database() as db:
            return dict(db.execute("SELECT id,email,email_verified FROM users WHERE id=?", (user_id,)).fetchone())

    @router.get("/csrf")
    def csrf(request: Request, user_id: int = Depends(current_user)):
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Sessione browser richiesta")
        csrf_token = secrets.token_urlsafe(32)
        with database(write=True) as db:
            # Bind to both the cookie and authenticated user, even with a bearer header.
            result = db.execute("UPDATE sessions SET csrf_hash=? WHERE token_hash=? AND user_id=?",
                                (digest(csrf_token), digest(token), user_id))
            if result.rowcount != 1:
                raise HTTPException(401, "Sessione browser non valida")
        return {"csrf_token": csrf_token}

    @router.post("/logout")
    def logout(request: Request, response: Response, user_id: int = Depends(current_user)):
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else request.cookies.get(COOKIE)
        with database(write=True) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=? AND user_id=?", (digest(token), user_id))
            audit(db, "auth.logout", user_id=user_id)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.post("/logout-all")
    def logout_all(response: Response, user_id: int = Depends(current_user)):
        with database(write=True) as db:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            audit(db, "auth.logout_all", user_id=user_id)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.post("/forgot-password")
    @router.post("/resend-verification")
    def email_challenge(data: EmailRequest, request: Request):
        if not mail_ready():
            raise HTTPException(503, "Invio email non configurato")
        purpose = "reset" if request.url.path.endswith("forgot-password") else "verify"
        with database(write=True) as db:
            user = db.execute("SELECT id,email,email_verified FROM users WHERE email=?", (str(data.email).lower(),)).fetchone()
            if user and (purpose != "verify" or not user["email_verified"]):
                send_challenge(db, user, purpose)
        return {"ok": True, "message": "Se l'indirizzo è registrato, riceverai un'email"}

    def consume(db, token, purpose):
        row = db.execute("SELECT user_id FROM auth_challenges WHERE token_hash=? AND purpose=? AND expires_at>?",
                         (digest(token), purpose, int(time.time()))).fetchone()
        if not row:
            raise HTTPException(400, "Link non valido o scaduto")
        # DELETE RETURNING would also work; rowcount protects concurrent consumption.
        deleted = db.execute("DELETE FROM auth_challenges WHERE token_hash=?", (digest(token),))
        if deleted.rowcount != 1:
            raise HTTPException(400, "Link già utilizzato")
        return row["user_id"]

    @router.post("/verify-email")
    def verify_email(data: TokenRequest):
        with database(write=True) as db:
            user_id = consume(db, data.token, "verify")
            db.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
            audit(db, "auth.email_verified", user_id=user_id)
        return {"ok": True}

    @router.post("/reset-password")
    def reset_password(data: PasswordReset, response: Response):
        salt = secrets.token_hex(16)
        with database(write=True) as db:
            user_id = consume(db, data.token, "reset")
            db.execute("UPDATE users SET password_hash=?,salt=? WHERE id=?", (hash_password(data.password, salt), salt, user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM auth_challenges WHERE user_id=?", (user_id,))
            audit(db, "auth.password_reset", user_id=user_id)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    return router, current_user, require_org
