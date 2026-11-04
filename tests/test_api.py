import importlib
from fastapi.testclient import TestClient

def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "test.sqlite3"))
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)

def register(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "strong-password-123"})
    assert r.status_code == 201
    client.headers.update({"Authorization": "Bearer " + r.json()["access_token"]})

def test_booking_and_overlap(tmp_path, monkeypatch):
    client = setup(tmp_path, monkeypatch)
    assert client.get("/api/organizations").status_code == 401
    register(client, "one@example.com")
    org = client.post("/api/organizations", json={"name": "Studio uno"}).json()["id"]
    service = client.post("/api/services", json={"organization_id": org, "name": "Consulenza", "duration_minutes": 60})
    assert service.status_code == 200
    payload = {"organization_id": org, "customer": "Cliente test", "service_id": service.json()["id"], "starts_at": "2027-01-10T10:00:00+01:00"}
    first = client.post("/api/appointments", json=payload)
    assert first.status_code == 200
    assert first.json()["starts_at"] == "2027-01-10T09:00:00+00:00"
    assert client.post("/api/appointments", json={**payload, "starts_at": "2027-01-10T09:30:00+00:00"}).status_code == 409
    assert client.post("/api/appointments", json={**payload, "starts_at": "2027-01-10T10:00:00+00:00"}).status_code == 200
    assert client.post("/api/appointments", json={**payload, "starts_at": "2027-01-10T12:00:00"}).status_code == 422

def test_tenant_isolation_and_logout(tmp_path, monkeypatch):
    client = setup(tmp_path, monkeypatch)
    register(client, "one@example.com")
    first = client.post("/api/organizations", json={"name": "Prima"}).json()["id"]
    service = client.post("/api/services", json={"organization_id": first, "name": "Demo", "duration_minutes": 30}).json()["id"]
    register(client, "two@example.com")
    second = client.post("/api/organizations", json={"name": "Seconda"}).json()["id"]
    assert client.get(f"/api/services?organization_id={first}").status_code == 403
    assert client.get(f"/api/appointments?organization_id={first}").status_code == 403
    assert client.post("/api/chat", json={"organization_id": first, "message": "Ciao"}).status_code == 403
    assert client.post("/api/appointments", json={"organization_id": second, "customer": "Test", "service_id": service, "starts_at": "2027-01-10T10:00:00+00:00"}).status_code == 404
    assert len(client.get("/api/organizations").json()) == 1
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/organizations").status_code == 401
