import importlib
from fastapi.testclient import TestClient

def test_reschedule_cancel_and_tenant_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "lifecycle.sqlite3"))
    import app.main as main
    importlib.reload(main)
    c = TestClient(main.app)
    token = c.post("/api/auth/register", json={
        "email": "owner@example.com", "password": "very-long-password-123"}).json()["access_token"]
    c.headers.update({"Authorization": "Bearer " + token})
    org = c.post("/api/organizations", json={"name": "Studio"}).json()["id"]
    service = c.post("/api/services", json={
        "organization_id": org, "name": "Sessione", "duration_minutes": 60}).json()["id"]
    base = {"organization_id": org, "service_id": service, "customer": "Cliente"}
    first = c.post("/api/appointments", json={
        **base, "starts_at": "2027-04-02T10:00:00+02:00"}).json()["id"]
    second = c.post("/api/appointments", json={
        **base, "starts_at": "2027-04-02T12:00:00+02:00"}).json()["id"]
    url = f"/api/appointments/{first}"
    assert c.patch(url, params={"organization_id": org}, json={
        "starts_at": "2027-04-02T12:30:00+02:00"}).status_code == 409
    assert c.patch(url, params={"organization_id": org}, json={
        "starts_at": "2027-04-02T14:00:00+02:00"}).status_code == 200
    outsider = c.post("/api/auth/register", json={
        "email": "outsider@example.com", "password": "very-long-password-123"}).json()["access_token"]
    c.headers.update({"Authorization": "Bearer " + outsider})
    assert c.delete(url, params={"organization_id": org}).status_code == 403
    c.headers.update({"Authorization": "Bearer " + token})
    assert c.delete(url, params={"organization_id": org}).status_code == 200
    assert c.delete(url, params={"organization_id": org}).status_code == 404
    assert len(c.get("/api/appointments", params={"organization_id": org}).json()) == 1
