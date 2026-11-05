import importlib
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setenv("SECRET_AI_ENV", "development")
    monkeypatch.setenv("SECRET_AI_BILLING_REQUIRED", "0")
    test_url = os.getenv("SECRET_AI_TEST_DATABASE_URL")
    if not test_url:
        monkeypatch.delenv("SECRET_AI_DATABASE_URL", raising=False)
        yield
        return
    root_engine = create_engine(test_url)
    schema = "test_" + uuid.uuid4().hex
    with root_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(test_url).update_query_dict({"options": "-csearch_path="+schema})
    monkeypatch.setenv("SECRET_AI_DATABASE_URL", url.render_as_string(hide_password=False))
    try:
        yield
    finally:
        with root_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root_engine.dispose()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_DB", str(tmp_path / "workspace.sqlite3"))
    import app.main as main
    importlib.reload(main)
    c = TestClient(main.app)
    login = c.post("/api/auth/register", json={"email": "owner@example.com", "password": "very-long-password-123"}).json()
    c.headers["Authorization"] = "Bearer "+login["access_token"]
    org = c.post("/api/organizations", json={"name": "Studio SecretAI"}).json()["id"]
    service = c.post("/api/services", json={"organization_id": org, "name": "Consulenza", "duration_minutes": 60, "price_cents": 3900}).json()["id"]
    yield c, main, org, service, login
    c.close()


def outsider(c):
    r = c.post("/api/auth/register", json={"email": "outsider@example.com", "password": "another-long-password-123"}).json()
    c.headers["Authorization"] = "Bearer "+r["access_token"]
