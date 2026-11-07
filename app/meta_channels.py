"""Official Meta webhooks, verified account binding and unified inbox ingestion."""
import hashlib
import hmac
import json
import os
import re
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.auth import audit
from app.booking import enqueue
from app.secrets import encrypt, decrypt
from app.jobs import AttentionRequired


def graph_base(provider):
    version = os.getenv("META_GRAPH_VERSION", "")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
        raise HTTPException(503, "Configura la versione API Meta approvata per la tua app")
    host = "graph.facebook.com" if provider == "whatsapp" else "graph.instagram.com"
    return "https://" + host + "/" + version


def objects(value):
    return [i for i in value if isinstance(i, dict)] if isinstance(value, list) else []


def incoming(payload):
    for entry in objects(payload.get("entry")):
        if payload.get("object") == "whatsapp_business_account":
            for change in objects(entry.get("changes")):
                value = change.get("value")
                if not isinstance(value, dict):
                    continue
                metadata = value.get("metadata", {})
                account = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
                for msg in objects(value.get("messages")):
                    text = msg.get("text", {})
                    if account and msg.get("id") and msg.get("from"):
                        body = text.get("body") if isinstance(text, dict) else None
                        yield "whatsapp", str(account), str(msg["id"]), str(msg["from"]), body if isinstance(body, str) else "[Messaggio non testuale: intervento operatore]", msg.get("timestamp")
        elif payload.get("object") == "instagram":
            for event in objects(entry.get("messaging")):
                msg, sender = event.get("message", {}), event.get("sender", {})
                if not isinstance(msg, dict) or not isinstance(sender, dict):
                    continue
                if msg.get("mid") and not msg.get("is_echo") and sender.get("id") and entry.get("id"):
                    body = msg.get("text")
                    yield "instagram", str(entry["id"]), str(msg["mid"]), str(sender["id"]), body if isinstance(body, str) else "[Messaggio non testuale: intervento operatore]", event.get("timestamp")


class Channel(BaseModel):
    organization_id: int = Field(gt=0)
    provider: str = Field(pattern="^(whatsapp|instagram)$")
    external_id: str = Field(pattern="^[0-9]{1,40}$")
    access_token: str = Field(min_length=10, max_length=4000)
    expires_at: int | None = None


def install(database, current_user, require_org):
    router = APIRouter(tags=["meta"])

    @router.get("/api/meta/webhook", response_class=PlainTextResponse)
    def verify(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"), challenge: str = Query(alias="hub.challenge")):
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
        for provider, account, mid, sender, body, timestamp in incoming(payload):
            now = int(time.time())
            try:
                received = int(timestamp)
                if provider == "instagram":
                    received //= 1000
                received = min(received, now)
            except (ValueError, TypeError):
                received = now
            with database() as db:
                channel = db.execute("SELECT organization_id FROM meta_channels WHERE provider=? AND external_id=?", (provider, account)).fetchone()
            if not channel:
                continue
            org_id = channel["organization_id"]
            with database(write=True, organization_id=org_id) as db:
                # Recheck binding after taking the tenant lock, then deduplicate.
                if not db.execute("SELECT 1 FROM meta_channels WHERE provider=? AND external_id=? AND organization_id=?", (provider, account, org_id)).fetchone():
                    continue
                if db.execute("SELECT 1 FROM meta_messages WHERE provider=? AND message_id=?", (provider, mid)).fetchone():
                    continue
                db.execute("INSERT INTO meta_messages(organization_id,provider,message_id,sender_id,body,received_at) VALUES (?,?,?,?,?,?)", (org_id, provider, mid, sender, body[:4000], received))
                conversation = db.execute("SELECT * FROM conversations WHERE organization_id=? AND channel=? AND external_id=?", (org_id, provider, sender)).fetchone()
                if not conversation:
                    contact = db.execute("INSERT INTO contacts(organization_id,name,phone,created_at) VALUES (?,?,?,?)", (org_id, sender, sender if provider == "whatsapp" else "", now))
                    cid = db.execute("INSERT INTO conversations(organization_id,contact_id,channel,external_id,updated_at) VALUES (?,?,?,?,?)", (org_id, contact.lastrowid, provider, sender, now)).lastrowid
                else:
                    cid = conversation["id"]
                message_id = db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,external_id) VALUES (?,?,'inbound',?,?,?)", (org_id, cid, body[:4000], received, provider+":"+mid)).lastrowid
                unsupported = body.startswith("[Messaggio non testuale")
                if unsupported or (conversation and conversation["status"] == "closed"):
                    db.execute("UPDATE conversations SET status='human' WHERE id=? AND organization_id=?", (cid, org_id))
                db.execute("UPDATE conversations SET updated_at=?,identity_verified=1 WHERE id=? AND organization_id=?", (now, cid, org_id))
                from app.channel_controls import permitted, policy
                revision = policy(db, org_id, provider)['revision']
                enabled = permitted(db, org_id, provider)
                if enabled and not unsupported and received > now-86400 and (not conversation or conversation["status"] == "ai"):
                    enqueue(db, org_id, "ai_reply", {"message_id": message_id, "conversation_id": cid, "automation_revision": revision}, "ai:"+provider+":"+mid)
        # Delivery updates are authenticated by the same raw-body HMAC.
        for entry in objects(payload.get('entry')):
            for change in objects(entry.get('changes')):
                value=change.get('value',{})
                if not isinstance(value,dict): continue
                for receipt in objects(value.get('statuses')):
                    remote=receipt.get('id');status=receipt.get('status')
                    if not remote or status not in {'sent','delivered','read','failed'}:continue
                    with database(write=True) as db:
                        row=db.execute("SELECT id,organization_id,delivery_status FROM messages WHERE external_id=? AND direction='outbound'",('whatsapp:'+str(remote),)).fetchone()
                        if not row:continue
                        ranks={'pending':0,'sending':0,'sent':1,'delivered':2,'read':3,'failed':1}
                        if ranks.get(status,0)>=ranks.get(row['delivery_status'],0):
                            db.execute('UPDATE messages SET delivery_status=? WHERE id=? AND organization_id=?',(status,row['id'],row['organization_id']))
        return {"ok": True}

    @router.post("/api/meta/test-whatsapp/connect")
    async def connect_test_whatsapp(organization_id: int, user_id: int = Depends(current_user)):
        """Bind the dedicated Meta test number, without Embedded Signup or browser tokens."""
        require_org(user_id, organization_id, owner=True)
        allowed = os.getenv("WHATSAPP_TEST_ORG_ID", "")
        if not allowed or str(organization_id) != allowed:
            raise HTTPException(403, "Test WhatsApp non abilitato per questa azienda")
        phone_id = os.getenv("WHATSAPP_TEST_PHONE_NUMBER_ID", "")
        waba_id = os.getenv("WHATSAPP_TEST_WABA_ID", "")
        token = os.getenv("WHATSAPP_TEST_ACCESS_TOKEN", "")
        if not (phone_id.isdecimal() and waba_id.isdecimal() and token):
            raise HTTPException(503, "Credenziali WhatsApp di prova incomplete")
        base = graph_base("whatsapp")
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                result = await client.get(base + "/" + waba_id + "/phone_numbers",
                    headers={"Authorization": "Bearer " + token}, params={"fields": "id", "limit": 100})
                result.raise_for_status()
                numbers = result.json().get("data", [])
                if not any(str(item.get("id")) == phone_id for item in numbers):
                    raise HTTPException(422, "Il numero di prova non appartiene al WABA indicato")
                subscription = await client.post(base + "/" + waba_id + "/subscribed_apps",
                    headers={"Authorization": "Bearer " + token})
                if subscription.status_code >= 400:
                    raise HTTPException(422, "Meta non ha accettato l'iscrizione dell'app ai webhook WhatsApp (HTTP " + str(subscription.status_code) + ")")
            except httpx.HTTPError:
                raise HTTPException(422, "Meta non ha autorizzato la verifica del numero di prova")
        with database(write=True, organization_id=organization_id) as db:
            existing = db.execute("SELECT organization_id FROM meta_channels WHERE provider='whatsapp' AND external_id=?", (phone_id,)).fetchone()
            if existing and existing["organization_id"] != organization_id:
                raise HTTPException(409, "Numero di prova già associato a un'altra azienda")
            other = db.execute("SELECT external_id FROM meta_channels WHERE organization_id=? AND provider='whatsapp' AND external_id<>?", (organization_id, phone_id)).fetchone()
            if other:
                raise HTTPException(409, "Scollega prima il numero WhatsApp esistente")
            db.execute("INSERT INTO meta_channels(organization_id,provider,external_id) VALUES (?,'whatsapp',?) ON CONFLICT(provider,external_id) DO NOTHING", (organization_id, phone_id))
            db.execute("""INSERT INTO channel_credentials(organization_id,provider,token_ciphertext,expires_at)
                VALUES (?,'whatsapp',?,NULL)
                ON CONFLICT(organization_id,provider) DO UPDATE SET token_ciphertext=excluded.token_ciphertext,expires_at=NULL""",
                (organization_id, encrypt(token)))
            audit(db, "meta.test_connected", user_id, organization_id, "whatsapp")
        return {"connected": True, "provider": "whatsapp", "test": True}

    @router.post("/api/meta/channels")
    async def connect(data: Channel, user_id: int = Depends(current_user)):
        require_org(user_id, data.organization_id, owner=True)
        if data.expires_at is not None and data.expires_at <= int(time.time()):
            raise HTTPException(422, "Token già scaduto")
        base = graph_base(data.provider)
        # Never accept an account ID without proving that the token can access it.
        path = "/"+data.external_id if data.provider == "whatsapp" else "/me"
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                result = await client.get(base+path, headers={"Authorization": "Bearer "+data.access_token}, params={"fields": "id"})
                result.raise_for_status()
                if str(result.json()["id"]) != data.external_id:
                    raise ValueError()
            except (httpx.HTTPError, ValueError, KeyError):
                raise HTTPException(422, "Impossibile verificare l'account e le autorizzazioni Meta")
        try:
            with database(write=True, organization_id=data.organization_id) as db:
                existing = db.execute("SELECT * FROM meta_channels WHERE provider=? AND external_id=?", (data.provider, data.external_id)).fetchone()
                if existing and existing["organization_id"] != data.organization_id:
                    raise HTTPException(409, "Canale già associato a un'azienda")
                if db.execute("SELECT 1 FROM meta_channels WHERE organization_id=? AND provider=? AND external_id<>?", (data.organization_id, data.provider, data.external_id)).fetchone():
                    raise HTTPException(409, "Scollega prima il canale esistente")
                db.execute("INSERT INTO meta_channels(organization_id,provider,external_id) VALUES (?,?,?) ON CONFLICT(provider,external_id) DO NOTHING", (data.organization_id, data.provider, data.external_id))
                bound = db.execute("SELECT organization_id FROM meta_channels WHERE provider=? AND external_id=?", (data.provider, data.external_id)).fetchone()
                if bound["organization_id"] != data.organization_id:
                    raise HTTPException(409, "Canale già associato a un'azienda")
                db.execute("""INSERT INTO channel_credentials(organization_id,provider,token_ciphertext,expires_at) VALUES (?,?,?,?)
                    ON CONFLICT(organization_id,provider) DO UPDATE SET token_ciphertext=excluded.token_ciphertext,expires_at=excluded.expires_at""", (data.organization_id, data.provider, encrypt(data.access_token), data.expires_at))
                audit(db, "meta.connected", user_id, data.organization_id, data.provider)
        except IntegrityError:
            raise HTTPException(409, "Canale già associato")
        return {"connected": True, "provider": data.provider}

    @router.delete("/api/meta/channels/{provider}")
    def disconnect(provider: str, organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database(write=True, organization_id=organization_id) as db:
            db.execute("DELETE FROM meta_channels WHERE organization_id=? AND provider=?", (organization_id, provider))
            db.execute("DELETE FROM channel_credentials WHERE organization_id=? AND provider=?", (organization_id, provider))
            db.execute("UPDATE conversations SET status='human' WHERE organization_id=? AND channel=?", (organization_id, provider))
            audit(db, "meta.disconnected", user_id, organization_id, provider)
        return {"ok": True}

    @router.get("/api/meta/inbox")
    def inbox(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            return [dict(row) for row in db.execute("SELECT id,provider,sender_id,body,received_at FROM meta_messages WHERE organization_id=? ORDER BY id DESC LIMIT 100", (organization_id,))]
    return router


def handlers(database):
    async def send(job, payload):
        org_id = job["organization_id"]
        with database(write=True, organization_id=org_id) as db:
            row = db.execute("""SELECT m.*,c.channel,c.external_id AS recipient FROM messages m JOIN conversations c
                ON c.id=m.conversation_id AND c.organization_id=m.organization_id WHERE m.id=? AND m.organization_id=?""", (payload["message_id"], org_id)).fetchone()
            if not row or row["delivery_status"] == "sent":
                return
            from app.channel_controls import permitted
            if (row['external_id'] or '').startswith('ai:') and not permitted(db, org_id, row['channel'], payload.get('automation_revision', 0)):
                db.execute("UPDATE messages SET delivery_status='suppressed' WHERE id=? AND organization_id=?", (row['id'], org_id))
                return
            credentials = db.execute("SELECT * FROM channel_credentials WHERE organization_id=? AND provider=?", (org_id, row["channel"])).fetchone()
            channel = db.execute("SELECT external_id FROM meta_channels WHERE organization_id=? AND provider=?", (org_id, row["channel"])).fetchone()
            if not credentials or not channel or (credentials["expires_at"] and credentials["expires_at"] <= int(time.time())):
                raise AttentionRequired("Reconnect channel credentials")
            inbound = db.execute("SELECT MAX(created_at) AS last FROM messages WHERE organization_id=? AND conversation_id=? AND direction='inbound'", (org_id, row["conversation_id"])).fetchone()["last"]
            if not inbound or inbound < int(time.time())-86400:
                raise AttentionRequired("Messaging reply window expired")
            if row["delivery_status"] == "sending":
                raise AttentionRequired("Previous delivery outcome unknown")
            db.execute("UPDATE messages SET delivery_status='sending' WHERE id=? AND organization_id=?", (row["id"], org_id))
        base = graph_base(row["channel"])
        body = ({"messaging_product": "whatsapp", "recipient_type": "individual", "to": row["recipient"], "type": "text", "text": {"body": row["body"]}}
                if row["channel"] == "whatsapp" else {"recipient": {"id": row["recipient"]}, "message": {"text": row["body"]}})
        async with httpx.AsyncClient(timeout=20) as client:
            result = await client.post(base+"/"+channel["external_id"]+"/messages", headers={"Authorization": "Bearer "+decrypt(credentials["token_ciphertext"])}, json=body)
            result.raise_for_status()
            data = result.json()
            remote_id = data["messages"][0]["id"] if row["channel"] == "whatsapp" else data["message_id"]
        with database(write=True, organization_id=org_id) as db:
            db.execute("UPDATE messages SET delivery_status='sent',external_id=? WHERE id=? AND organization_id=?", (row["channel"]+":"+remote_id, row["id"], org_id))
    return {"meta_send": send}
