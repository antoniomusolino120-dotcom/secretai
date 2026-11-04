"""Verified Meta webhooks and tenant-scoped inbound message storage."""
import hashlib
import hmac
import json
import os
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

def install(database, current_user, require_org):
    router = APIRouter()

    def ensure_tables(db):
        db.executescript("""
        CREATE TABLE IF NOT EXISTS meta_channels (
          organization_id INTEGER NOT NULL,
          provider TEXT NOT NULL,
          external_id TEXT NOT NULL,
          UNIQUE(provider, external_id));
        CREATE TABLE IF NOT EXISTS meta_messages (
          id INTEGER PRIMARY KEY,
          organization_id INTEGER NOT NULL,
          provider TEXT NOT NULL,
          message_id TEXT NOT NULL,
          sender_id TEXT NOT NULL,
          body TEXT NOT NULL,
          received_at INTEGER NOT NULL,
          UNIQUE(provider, message_id));
        """)

    @router.get("/api/meta/webhook", response_class=PlainTextResponse)
    def verify(mode: str = Query(alias="hub.mode"),
               token: str = Query(alias="hub.verify_token"),
               challenge: str = Query(alias="hub.challenge")):
        secret = os.getenv("META_VERIFY_TOKEN")
        if not secret or mode != "subscribe" or not hmac.compare_digest(secret, token):
            raise HTTPException(403, "Verification failed")
        return challenge

    @router.post("/api/meta/webhook")
    async def receive(request: Request, signature: str | None = Header(None, alias="X-Hub-Signature-256")):
        secret = os.getenv("META_APP_SECRET")
        if not secret:
            raise HTTPException(503, "Meta is not configured")
        raw = await request.body()
        if len(raw) > 1_000_000:
            raise HTTPException(413, "Payload too large")
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise HTTPException(403, "Invalid signature")
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "Invalid payload")
        messages = []
        for entry in payload.get("entry", []):
            if payload.get("object") == "whatsapp_business_account":
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    account = value.get("metadata", {}).get("phone_number_id")
                    for msg in value.get("messages", []):
                        if account and msg.get("type") == "text" and msg.get("id"):
                            messages.append(("whatsapp", str(account), str(msg["id"]),
                                             str(msg.get("from", "")), str(msg.get("text", {}).get("body", ""))))
            elif payload.get("object") == "instagram":
                for event in entry.get("messaging", []):
                    msg = event.get("message", {})
                    if msg.get("mid") and not msg.get("is_echo") and isinstance(msg.get("text"), str):
                        messages.append(("instagram", str(entry.get("id", "")), str(msg["mid"]),
                                         str(event.get("sender", {}).get("id", "")), msg["text"]))
        with database() as db:
            ensure_tables(db)
            for provider, account, mid, sender, body in messages:
                channel = db.execute(
                    "SELECT organization_id FROM meta_channels WHERE provider=? AND external_id=?",
                    (provider, account)).fetchone()
                if channel and sender:
                    db.execute(
                        "INSERT OR IGNORE INTO meta_messages (organization_id,provider,message_id,sender_id,body,received_at) VALUES (?,?,?,?,?,?)",
                        (channel["organization_id"], provider, mid, sender, body, int(time.time())))
        return {"ok": True}

    @router.get("/api/meta/inbox")
    def inbox(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            ensure_tables(db)
            return [dict(row) for row in db.execute(
                "SELECT id,provider,sender_id,body,received_at FROM meta_messages WHERE organization_id=? ORDER BY id DESC LIMIT 100",
                (organization_id,)).fetchall()]
    return router
