import asyncio
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.assistant import Proposal, propose, confirm
from app.billing import consume
from app.booking import AppointmentRequest, create_booking, enqueue
from app.jobs import claim, run_once
from conftest import outsider


def payload(org, service, start="2027-08-09T10:00:00+02:00"):
    return {"organization_id": org, "service_id": service, "customer": "Cliente test", "starts_at": start}


def test_cookie_csrf_and_revocation(workspace):
    c, main, org, service, login = workspace
    c.headers.pop("Authorization")
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/organizations", json={"name": "CSRF"}).status_code == 403
    c.headers["X-CSRF-Token"] = login["csrf_token"]
    assert c.post("/api/organizations", json={"name": "Authorized"}).status_code == 200
    assert c.post("/api/organizations", json={"name": "Attack"}, headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert c.post("/api/auth/logout-all").status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    c.headers["Authorization"] = "Bearer "+login["access_token"]
    assert c.get("/api/auth/me").status_code == 401


def test_rate_limit_is_persistent(workspace, monkeypatch):
    c, main, *_ = workspace
    monkeypatch.setenv("SECRET_AI_AUTH_RATE_LIMIT", "2")
    body = {"email": "absent@example.com", "password": "wrong-password-long"}
    assert c.post("/api/auth/login", json=body).status_code == 401
    assert c.post("/api/auth/login", json=body).status_code == 401
    response = c.post("/api/auth/login", json=body)
    assert response.status_code == 429
    assert 0 < int(response.headers["Retry-After"]) <= 300


def test_idempotency_reuses_result_but_rejects_changed_payload(workspace):
    c, main, org, service, _ = workspace
    headers = {"Idempotency-Key": "booking-request-0001"}
    first = c.post("/api/appointments", json=payload(org, service), headers=headers)
    assert first.status_code == 200
    repeat = c.post("/api/appointments", json=payload(org, service), headers=headers)
    assert repeat.json() == first.json()
    changed = c.post("/api/appointments", json=payload(org, service, "2027-08-09T12:00:00+02:00"), headers=headers)
    assert changed.status_code == 409
    assert len(c.get(f"/api/appointments?organization_id={org}").json()) == 1


def test_simultaneous_requests_have_one_winner(workspace):
    _, main, org, service, _ = workspace
    data = AppointmentRequest(**payload(org, service))
    def attempt(i):
        try:
            return create_booking(main.database, data, key=f"parallel-request-{i}")["id"]
        except HTTPException as error:
            assert error.status_code == 409
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = list(pool.map(attempt, range(8)))
    assert len([w for w in winners if w is not None]) == 1


def test_hours_dst_and_service_changes_do_not_move_existing_bookings(workspace):
    c, main, org, service, _ = workspace
    settings = {"name": "Studio", "timezone": "Europe/Rome", "hours": {"0": [["09:00", "18:00"]]}, "assistant_enabled": True}
    assert c.put(f"/api/organizations/{org}/settings", json=settings).status_code == 200
    assert c.post("/api/appointments", json=payload(org, service, "2027-08-09T17:30:00+02:00")).status_code == 409
    booking = c.post("/api/appointments", json=payload(org, service, "2027-08-09T10:00:00+02:00")).json()
    assert booking["starts_at"] == "2027-08-09T08:00:00+00:00"
    assert c.put(f"/api/services/{service}", json={"organization_id": org, "name": "Consulenza", "duration_minutes": 90}).status_code == 200
    saved = c.get(f"/api/appointments?organization_id={org}").json()[0]
    assert saved["ends_at"] == booking["ends_at"]
    invalid = {**settings, "hours": {"0": [["09:00", "13:00"], ["12:00", "17:00"]]}}
    assert c.put(f"/api/organizations/{org}/settings", json=invalid).status_code == 422


def test_crm_inbox_and_audit_are_tenant_scoped(workspace):
    c, main, org, service, _ = workspace
    contact = c.post("/api/contacts", json={"organization_id": org, "name": "Cliente"}).json()["id"]
    conversation = c.post("/api/conversations", json={"organization_id": org, "contact_id": contact}).json()["id"]
    assert c.post(f"/api/conversations/{conversation}/reply?organization_id={org}", json={"body": "Ciao"}).status_code == 409
    assert c.put(f"/api/conversations/{conversation}/handoff?organization_id={org}", json={"status": "human"}).status_code == 200
    assert c.post(f"/api/conversations/{conversation}/reply?organization_id={org}", json={"body": "Ciao"}).json()["delivery_status"] == "sent"
    outsider(c)
    for endpoint in [f"contacts?organization_id={org}", f"conversations?organization_id={org}",
                     f"conversations/{conversation}/messages?organization_id={org}",
                     f"organizations/{org}/settings", f"organizations/{org}/audit", f"organizations/{org}/jobs", f"billing?organization_id={org}"]:
        assert c.get("/api/"+endpoint).status_code == 403
    other_org = c.post("/api/organizations", json={"name": "Other"}).json()["id"]
    assert c.post("/api/conversations", json={"organization_id": other_org, "contact_id": contact}).status_code == 404
    with pytest.raises(IntegrityError):
        with main.database(write=True) as db:
            db.execute("INSERT INTO appointments(organization_id,service_id,customer,starts_at,ends_at) VALUES (?,?,?,'2027-01-01','2027-01-02')", (other_org, service, "Invalid tenant"))


def test_member_cannot_change_settings_or_integrations(workspace):
    c, main, org, service, _ = workspace
    outsider(c)
    uid = c.get("/api/auth/me").json()["id"]
    with main.database(write=True) as db:
        db.execute("INSERT INTO memberships VALUES (?,?,'member')", (uid, org))
    assert c.get(f"/api/contacts?organization_id={org}").status_code == 200
    assert c.post("/api/services", json={"organization_id": org, "name": "Forbidden", "duration_minutes": 30}).status_code == 403
    assert c.post(f"/api/google/connect?organization_id={org}").status_code == 403
    assert c.get(f"/api/billing?organization_id={org}").status_code == 403


def test_ai_proposal_requires_confirmation_and_is_idempotent(workspace):
    c, main, org, service, _ = workspace
    uid = c.get("/api/auth/me").json()["id"]
    proposed = propose(main.database, org, Proposal(service_id=service, customer="Cliente", starts_at=datetime.fromisoformat("2027-09-01T10:00:00+02:00")), user_id=uid)
    assert c.get(f"/api/appointments?organization_id={org}").json() == []
    result = confirm(main.database, org, proposed["proposal_id"], user_id=uid)
    assert result["appointment"]["status"] == "confirmed"
    assert confirm(main.database, org, proposed["proposal_id"], user_id=uid) == result
    with pytest.raises(HTTPException) as error:
        confirm(main.database, org, proposed["proposal_id"], user_id=uid+1)
    assert error.value.status_code == 404


def test_ai_handoff_cancels_inflight_booking_authority(workspace):
    c, main, org, service, _ = workspace
    cid = c.post("/api/conversations", json={"organization_id": org}).json()["id"]
    proposed = propose(main.database, org, Proposal(service_id=service, customer="Cliente", starts_at=datetime.fromisoformat("2027-09-01T10:00:00+02:00")), conversation_id=cid)
    c.put(f"/api/conversations/{cid}/handoff?organization_id={org}", json={"status": "human"})
    with pytest.raises(HTTPException) as error:
        confirm(main.database, org, proposed["proposal_id"], conversation_id=cid)
    assert error.value.status_code == 409
    assert c.get(f"/api/appointments?organization_id={org}").json() == []


def test_google_booking_is_never_confirmed_before_external_write(workspace):
    c, main, org, service, _ = workspace
    with main.database(write=True) as db:
        db.execute("INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,'encrypted-test-token')", (org,))
    result = c.post("/api/appointments", json=payload(org, service)).json()
    assert result["status"] == "pending_sync"
    availability = c.post("/api/booking/availability", json={"organization_id": org, "service_id": service, "starts_at": "2027-08-09T14:00:00+02:00"}).json()
    assert availability["available"] is None and availability["requires_external_check"]
    with main.database() as db:
        assert db.execute("SELECT kind FROM jobs WHERE organization_id=?", (org,)).fetchone()["kind"] == "google_upsert"


def test_queue_retry_and_non_replayable_delivery_crash(workspace):
    _, main, org, *_ = workspace
    with main.database(write=True) as db:
        enqueue(db, org, "google_upsert", {}, "queue-google-1")
        enqueue(db, org, "google_upsert", {}, "queue-google-1")
    async def fail(*args):
        raise RuntimeError("secret-provider-data-must-not-be-stored")
    assert asyncio.run(run_once(main.database, {"google_upsert": fail}))
    with main.database(write=True) as db:
        row = db.execute("SELECT * FROM jobs").fetchone()
        assert row["status"] == "pending" and "secret-provider" not in row["last_error"]
        enqueue(db, org, "meta_send", {}, "queue-meta-1")
    job = claim(main.database)
    assert job["kind"] == "meta_send"
    with main.database(write=True) as db:
        db.execute("UPDATE jobs SET locked_until=0 WHERE id=?", (job["id"],))
    assert claim(main.database) is None
    with main.database() as db:
        assert db.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()["status"] == "attention"


def test_atomic_usage_limit_and_deduplication(workspace, monkeypatch):
    _, main, org, *_ = workspace
    monkeypatch.setenv("SECRET_AI_BILLING_REQUIRED", "1")
    monkeypatch.setenv("SECRET_AI_PLANS_JSON", json.dumps({"test": {"price_id": "price_test", "message_limit": 2, "voice_seconds_limit": 30}}))
    with pytest.raises(HTTPException) as error:
        consume(main.database, org, "messages", 1, "not-paid")
    assert error.value.status_code == 402
    with main.database(write=True) as db:
        db.execute("INSERT INTO billing_accounts(organization_id,stripe_customer_id,plan,status,period_start,period_end) VALUES (?,'cus_test','test','active',?,?)", (org, int(time.time())-100, int(time.time())+1000))
    consume(main.database, org, "messages", 1, "one")
    consume(main.database, org, "messages", 1, "one")
    consume(main.database, org, "messages", 1, "two")
    with pytest.raises(HTTPException) as error:
        consume(main.database, org, "messages", 1, "three")
    assert error.value.status_code == 402


def test_password_reset_consumes_token_and_revokes_sessions(workspace):
    c, main, org, service, login = workspace
    uid = c.get("/api/auth/me").json()["id"]
    token = "test-password-reset-token-long-enough"
    with main.database(write=True) as db:
        db.execute("INSERT INTO auth_challenges VALUES (?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), uid, "reset", int(time.time())+100))
    body = {"token": token, "password": "a-new-secure-password-123"}
    assert c.post("/api/auth/reset-password", json=body).status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/reset-password", json=body).status_code == 400


def test_security_headers_and_no_secret_fields(workspace):
    c, main, org, *_ = workspace
    r = c.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    r = c.get(f"/api/integrations?organization_id={org}")
    assert r.headers["Cache-Control"] == "no-store"
    assert "token_ciphertext" not in r.text
