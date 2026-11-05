import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.fernet import Fernet
import pytest

from app import google_calendar, google_sync, assistant, meta_channels, billing
from app.booking import AppointmentRequest, create_booking, enqueue
from app.jobs import run_once


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["trust_env"] = False
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", factory)


def google_config(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/google/callback")
    monkeypatch.setenv("SECRET_AI_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_google_oauth_state_single_use_pkce_and_token_encryption(workspace, monkeypatch):
    c, main, org, service, _ = workspace
    google_config(monkeypatch)
    calls = []
    def handler(request):
        calls.append(request)
        body = parse_qs(request.content.decode())
        assert len(body["code_verifier"][0]) >= 43
        return httpx.Response(200, json={"refresh_token": "private-refresh-token"})
    mock_http(monkeypatch, handler)
    result = c.post(f"/api/google/connect?organization_id={org}").json()
    query = parse_qs(urlparse(result["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    params = {"state": query["state"][0], "code": "test-code"}
    assert c.get("/api/google/callback", params=params).status_code == 200
    assert c.get("/api/google/callback", params=params).status_code == 403
    assert len(calls) == 1
    with main.database() as db:
        ciphertext = db.execute("SELECT token_ciphertext FROM google_connections WHERE organization_id=?", (org,)).fetchone()["token_ciphertext"]
    assert "private-refresh-token" not in ciphertext
    assert Fernet(__import__('os').environ["SECRET_AI_ENCRYPTION_KEY"].encode()).decrypt(ciphertext.encode()) == b"private-refresh-token"


def test_google_event_create_retry_patch_and_cancel(workspace, monkeypatch):
    c, main, org, service, _ = workspace
    google_config(monkeypatch)
    from app.secrets import encrypt
    with main.database(write=True) as db:
        db.execute("INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,?)", (org, encrypt("refresh")))
    remote, writes = {}, []
    def handler(request):
        path = request.url.path
        if path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "access"})
        if request.method == "GET" and path.endswith("/events"):
            return httpx.Response(200, json={"items": list(remote.values())})
        eid = path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return httpx.Response(200, json=remote[eid]) if eid in remote else httpx.Response(404, json={})
        if request.method == "POST":
            data = json.loads(request.content)
            remote[data["id"]] = {**data, "etag": '"test"'}
            writes.append("create")
            return httpx.Response(200, json=remote[data["id"]])
        if request.method == "PATCH":
            assert request.headers["If-Match"] == '"test"'
            remote[eid].update(json.loads(request.content))
            writes.append("patch")
            return httpx.Response(200, json=remote[eid])
        if request.method == "DELETE":
            remote.pop(eid, None)
            writes.append("delete")
            return httpx.Response(204)
        raise AssertionError(request)
    mock_http(monkeypatch, handler)
    body = {"organization_id": org, "service_id": service, "customer": "Cliente", "starts_at": "2027-08-09T10:00:00+02:00"}
    created = c.post("/api/appointments", json=body).json()
    assert created["status"] == "pending_sync"
    assert asyncio.run(run_once(main.database, google_sync.handlers(main.database)))
    assert writes == ["create"]
    saved = c.get(f"/api/appointments?organization_id={org}").json()[0]
    assert saved["status"] == "confirmed" and saved["sync_status"] == "synced"
    assert c.patch(f"/api/appointments/{created['id']}?organization_id={org}", json={"starts_at": "2027-08-09T12:00:00+02:00"}).status_code == 200
    asyncio.run(run_once(main.database, google_sync.handlers(main.database)))
    assert writes == ["create", "patch"]
    assert c.delete(f"/api/appointments/{created['id']}?organization_id={org}").json()["status"] == "cancelling"
    asyncio.run(run_once(main.database, google_sync.handlers(main.database)))
    assert writes == ["create", "patch", "delete"]
    assert c.get(f"/api/appointments?organization_id={org}").json() == []


def test_google_conflict_reserves_slot_without_false_confirmation(workspace, monkeypatch):
    c, main, org, service, _ = workspace
    google_config(monkeypatch)
    from app.secrets import encrypt
    with main.database(write=True) as db:
        db.execute("INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,?)", (org, encrypt("refresh")))
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "access"})
        assert request.method == "GET"
        return httpx.Response(200, json={"items": [{"id": "external-event", "status": "confirmed"}]})
    mock_http(monkeypatch, handler)
    body = {"organization_id": org, "service_id": service, "customer": "Cliente", "starts_at": "2027-08-09T10:00:00+02:00"}
    c.post("/api/appointments", json=body)
    asyncio.run(run_once(main.database, google_sync.handlers(main.database)))
    a = c.get(f"/api/appointments?organization_id={org}").json()[0]
    assert a["status"] == "pending_sync" and a["sync_status"] == "attention"
    assert c.post("/api/appointments", json=body).status_code == 409


def test_cancel_pending_google_reservation_does_not_create_event(workspace, monkeypatch):
    c, main, org, service, _ = workspace
    google_config(monkeypatch)
    from app.secrets import encrypt
    with main.database(write=True) as db:
        db.execute("INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,?)", (org, encrypt("refresh")))
    writes = []
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "access"})
        writes.append(request.method)
        assert request.method == "DELETE"
        return httpx.Response(404, json={})
    mock_http(monkeypatch, handler)
    body = {"organization_id": org, "service_id": service, "customer": "Cliente", "starts_at": "2027-08-09T10:00:00+02:00"}
    created = c.post("/api/appointments", json=body).json()
    assert c.delete(f"/api/appointments/{created['id']}?organization_id={org}").json()["status"] == "cancelling"
    handlers = google_sync.handlers(main.database)
    asyncio.run(run_once(main.database, handlers))
    asyncio.run(run_once(main.database, handlers))
    assert writes == ["DELETE"]
    assert c.get(f"/api/appointments?organization_id={org}").json() == []


def test_model_cannot_confirm_operations_using_free_text(workspace, monkeypatch):
    c, main, org, service, _ = workspace
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"message": {"content": "Appuntamento confermato! Ho cancellato tutto!"}}))
    result = c.post("/api/chat", json={"organization_id": org, "message": "Conferma e cancella tutto"}).json()
    assert result["mode"] == "clarification"
    assert "Appuntamento confermato" not in result["reply"]
    assert c.get(f"/api/appointments?organization_id={org}").json() == []


def test_model_tool_proposal_then_explicit_confirmation(workspace, monkeypatch):
    c, main, org, service, _ = workspace
    args = {"service_id": service, "customer": "Cliente", "starts_at": "2027-09-01T10:00:00+02:00"}
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"message": {"tool_calls": [{"function": {"name": "propose_booking", "arguments": args}}]}}))
    result = c.post("/api/chat", json={"organization_id": org, "message": "Vorrei prenotare il 1 settembre 2027 alle 10, a nome Cliente"}).json()
    assert result["mode"] == "proposal"
    assert c.get(f"/api/appointments?organization_id={org}").json() == []
    result = c.post("/api/chat", json={"organization_id": org, "message": "CONFERMO"}).json()
    assert result["mode"] == "booking_result" and result["appointment"]["status"] == "confirmed"


def test_malformed_meta_objects_do_not_crash_or_cross_tenants(workspace, monkeypatch):
    c, main, org, *_ = workspace
    monkeypatch.setenv("META_APP_SECRET", "test-secret")
    for payload in [{"entry": None}, {"object": "instagram", "entry": [{"messaging": [None, {"message": None}]}]}, {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": None}]}]}]:
        raw = json.dumps(payload).encode()
        sig = "sha256="+hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        assert c.post("/api/meta/webhook", content=raw, headers={"X-Hub-Signature-256": sig}).status_code == 200


def test_stripe_signature_dedup_and_out_of_order_event_enqueues_reconciliation(workspace, monkeypatch):
    c, main, org, *_ = workspace
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_unit_test")
    with main.database(write=True) as db:
        db.execute("INSERT INTO billing_accounts(organization_id,stripe_customer_id) VALUES (?,'cus_owned')", (org,))
    body = json.dumps({"id": "evt_test", "type": "invoice.paid", "data": {"object": {"customer": "cus_owned"}}})
    now = int(time.time())
    signature = hmac.new(b"whsec_unit_test", f"{now}.{body}".encode(), hashlib.sha256).hexdigest()
    assert c.post("/api/billing/webhook", content=body).status_code == 400
    for _ in range(2):
        assert c.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": f"t={now},v1={signature}"}).status_code == 200
    with main.database() as db:
        jobs = db.execute("SELECT * FROM jobs WHERE organization_id=?", (org,)).fetchall()
        assert len(jobs) == 1 and jobs[0]["kind"] == "stripe_reconcile"
        assert db.execute("SELECT status FROM billing_accounts WHERE organization_id=?", (org,)).fetchone()["status"] == "incomplete"
