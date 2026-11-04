import importlib
from urllib.parse import parse_qs, urlparse
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

def test_google_oauth_connect_requires_tenant_and_generates_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "google.sqlite3"))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/google/callback")
    monkeypatch.setenv("SECRET_AI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    token = client.post("/api/auth/register", json={
        "email": "google@example.com", "password": "very-long-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": "Bearer " + token})
    org = client.post("/api/organizations", json={"name": "Calendar Studio"}).json()["id"]
    result = client.post("/api/google/connect", params={"organization_id": org})
    assert result.status_code == 200
    query = parse_qs(urlparse(result.json()["authorization_url"]).query)
    assert query["client_id"] == ["test-client"]
    assert query["access_type"] == ["offline"]
    assert len(query["state"][0]) > 20
    assert client.get("/api/google/callback", params={"state": "invalid", "code": "x"}).status_code == 403
    other = client.post("/api/auth/register", json={
        "email": "other-google@example.com", "password": "very-long-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": "Bearer " + other})
    assert client.post("/api/google/connect", params={"organization_id": org}).status_code == 403
    assert client.post("/api/google/freebusy", json={
        "organization_id": org,
        "starts_at": "2027-05-01T10:00:00+02:00",
        "ends_at": "2027-05-01T11:00:00+02:00"}).status_code == 403
