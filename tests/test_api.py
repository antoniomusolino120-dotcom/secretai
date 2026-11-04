import importlib
import os

from fastapi.testclient import TestClient


def test_booking_and_overlap(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "test.sqlite3"))
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    assert client.get("/").status_code == 200
    assert client.get("/api/organizations").json()[0]["name"] == "Azienda demo"

    service = client.post("/api/services", json={
        "organization_id": 1, "name": "Consulenza", "duration_minutes": 60
    })
    assert service.status_code == 200
    service_id = service.json()["id"]

    payload = {
        "organization_id": 1, "customer": "Cliente test",
        "service_id": service_id, "starts_at": "2027-01-10T10:00:00+01:00"
    }
    first = client.post("/api/appointments", json=payload)
    assert first.status_code == 200
    assert first.json()["starts_at"] == "2027-01-10T09:00:00+00:00"

    same_instant = {**payload, "starts_at": "2027-01-10T09:30:00+00:00"}
    assert client.post("/api/appointments", json=same_instant).status_code == 409

    adjacent = {**payload, "starts_at": "2027-01-10T10:00:00+00:00"}
    assert client.post("/api/appointments", json=adjacent).status_code == 200

    naive = {**payload, "starts_at": "2027-01-10T12:00:00"}
    assert client.post("/api/appointments", json=naive).status_code == 422


def test_service_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "other.sqlite3"))
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    second = client.post("/api/organizations", json={"name": "Seconda azienda"}).json()["id"]
    service = client.post("/api/services", json={
        "organization_id": 1, "name": "Demo", "duration_minutes": 30
    }).json()["id"]
    response = client.post("/api/appointments", json={
        "organization_id": second, "customer": "Test",
        "service_id": service, "starts_at": "2027-01-10T10:00:00+00:00"
    })
    assert response.status_code == 404
