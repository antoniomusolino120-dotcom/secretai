import importlib
from fastapi.testclient import TestClient

def test_availability_is_scoped_and_detects_overlap(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "booking.sqlite3"))
    import app.main as main
    importlib.reload(main)
    c = TestClient(main.app)
    token = c.post("/api/auth/register", json={
        "email": "booking@example.com", "password": "very-long-password-123"
    }).json()["access_token"]
    c.headers.update({"Authorization": "Bearer " + token})
    org = c.post("/api/organizations", json={"name": "Studio"}).json()["id"]
    service = c.post("/api/services", json={
        "organization_id": org, "name": "Taglio", "duration_minutes": 30
    }).json()["id"]
    query = {"organization_id": org, "service_id": service,
             "starts_at": "2027-04-02T10:00:00+02:00"}
    assert c.post("/api/booking/availability", json=query).json()["available"] is True
    assert c.post("/api/appointments", json={**query, "customer": "Cliente"}).status_code == 200
    assert c.post("/api/booking/availability", json=query).json()["available"] is False
    assert c.post("/api/booking/availability", json={**query, "starts_at": "2027-04-02T10:30:00+02:00"}).json()["available"] is True
    token2 = c.post("/api/auth/register", json={
        "email": "other@example.com", "password": "very-long-password-123"
    }).json()["access_token"]
    c.headers.update({"Authorization": "Bearer " + token2})
    assert c.post("/api/booking/availability", json=query).status_code == 403
