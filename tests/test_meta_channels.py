import hashlib
import hmac
import importlib
import json
from fastapi.testclient import TestClient

def test_meta_webhook_signature_dedup_and_tenant_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "meta.sqlite3"))
    monkeypatch.setenv("META_APP_SECRET", "unit-test-secret")
    monkeypatch.setenv("META_VERIFY_TOKEN", "verify-test")
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    assert client.get("/api/meta/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "verify-test",
        "hub.challenge": "challenge123"}).text == "challenge123"
    assert client.get("/api/meta/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong",
        "hub.challenge": "x"}).status_code == 403

    token = client.post("/api/auth/register", json={
        "email": "meta@example.com", "password": "very-long-password-123"
    }).json()["access_token"]
    client.headers.update({"Authorization": "Bearer " + token})
    org = client.post("/api/organizations", json={"name": "Meta Studio"}).json()["id"]
    with main.database() as db:
        from app.meta_channels import install
        db.execute("CREATE TABLE IF NOT EXISTS meta_channels (organization_id INTEGER NOT NULL, provider TEXT NOT NULL, external_id TEXT NOT NULL, UNIQUE(provider,external_id))")
        db.execute("INSERT INTO meta_channels VALUES (?,?,?)", (org, "whatsapp", "phone-1"))
    payload = {"object": "whatsapp_business_account", "entry": [
        {"changes": [{"value": {"metadata": {"phone_number_id": "phone-1"},
        "messages": [{"id": "wamid.1", "from": "customer-1", "type": "text",
                      "text": {"body": "Vorrei prenotare"}}]}}]}]}
    raw = json.dumps(payload).encode()
    endpoint = "/api/meta/webhook"
    assert client.post(endpoint, content=raw).status_code == 403
    signature = "sha256=" + hmac.new(b"unit-test-secret", raw, hashlib.sha256).hexdigest()
    for _ in range(2):
        assert client.post(endpoint, content=raw, headers={"X-Hub-Signature-256": signature}).status_code == 200
    inbox = client.get("/api/meta/inbox", params={"organization_id": org})
    assert inbox.status_code == 200
    assert len(inbox.json()) == 1
    assert inbox.json()[0]["body"] == "Vorrei prenotare"
    other_token = client.post("/api/auth/register", json={
        "email": "other-meta@example.com", "password": "very-long-password-123"
    }).json()["access_token"]
    client.headers.update({"Authorization": "Bearer " + other_token})
    assert client.get("/api/meta/inbox", params={"organization_id": org}).status_code == 403
