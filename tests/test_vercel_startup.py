import importlib
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import public_origin
from app.db import database_url


def vercel(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_ENV', 'production')
    monkeypatch.setenv('VERCEL_PROJECT_PRODUCTION_URL', 'secretai.example.test')
    monkeypatch.setenv('VERCEL_URL', 'secretai-preview.example.test')
    monkeypatch.delenv('SECRET_AI_PUBLIC_URL', raising=False)


def test_vercel_never_falls_back_to_local_or_ephemeral_sqlite(monkeypatch):
    vercel(monkeypatch)
    for name in ('SECRET_AI_DATABASE_URL', 'DATABASE_URL', 'POSTGRES_URL'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match='dedicated PostgreSQL'):
        database_url()
    monkeypatch.setenv('SECRET_AI_DATABASE_URL', 'sqlite:////tmp/secretai.db')
    with pytest.raises(RuntimeError, match='local SQLite'):
        database_url()


def test_standard_vercel_database_variables_and_explicit_precedence(monkeypatch):
    vercel(monkeypatch)
    monkeypatch.delenv('SECRET_AI_DATABASE_URL', raising=False)
    monkeypatch.setenv('POSTGRES_URL', 'postgres://test:local@db.invalid/legacy')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert database_url() == 'postgresql+psycopg://test:local@db.invalid/legacy'
    monkeypatch.setenv('DATABASE_URL', 'postgresql://test:local@db.invalid/standard')
    assert database_url().endswith('/standard')
    monkeypatch.setenv('SECRET_AI_DATABASE_URL', 'postgresql+psycopg://test:local@db.invalid/dedicated')
    assert database_url().endswith('/dedicated')


def test_origin_comes_from_trusted_vercel_metadata_or_explicit_configuration(monkeypatch):
    vercel(monkeypatch)
    assert public_origin() == 'https://secretai.example.test'
    monkeypatch.setenv('VERCEL_ENV', 'preview')
    assert public_origin() == 'https://secretai-preview.example.test'
    monkeypatch.setenv('SECRET_AI_PUBLIC_URL', 'https://dedicated.example.test/')
    assert public_origin() == 'https://dedicated.example.test'


def test_unconfigured_vercel_serves_ui_but_api_and_readiness_stay_closed(monkeypatch, tmp_path):
    vercel(monkeypatch)
    for name in ('SECRET_AI_DATABASE_URL', 'DATABASE_URL', 'POSTGRES_URL'):
        monkeypatch.delenv(name, raising=False)
    forbidden_path = tmp_path / 'read-only-deployment' / 'secretai.db'
    monkeypatch.setenv('SECRET_AI_DB', str(forbidden_path))
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app, base_url='https://secretai.example.test') as c:
        assert c.get('/').status_code == 200
        assert c.get('/static/app.css').status_code == 200
        assert c.get('/health/live').status_code == 200
        ready = c.get('/health/ready')
        assert ready.status_code == 503
        assert 'Configurazione' in ready.json()['detail']
        assert c.get('/api/auth/me').status_code == 401
        blocked = c.post('/api/auth/register', json={'email': 'test@example.test', 'password': 'test-password-long-123'}, headers={'Origin': 'https://secretai.example.test'})
        assert blocked.status_code == 503
        assert blocked.headers['Retry-After'] == '5'
        assert c.post('/api/auth/register', json={}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert not forbidden_path.exists()
    assert main.runtime.engine is None


def test_serverless_bootstrap_with_real_postgres_persists_across_cold_starts(monkeypatch):
    if not os.getenv('SECRET_AI_TEST_DATABASE_URL'):
        pytest.skip('Requires isolated PostgreSQL; exercised by the PostgreSQL workflow')
    # conftest has created a dedicated empty schema for this exact test.
    url = os.environ['SECRET_AI_DATABASE_URL']
    vercel(monkeypatch)
    monkeypatch.delenv('SECRET_AI_DATABASE_URL')
    monkeypatch.setenv('DATABASE_URL', url)
    from app.serverless import ServerlessDatabase
    runtimes = [ServerlessDatabase(), ServerlessDatabase()]
    def start(runtime):
        with runtime.database() as db:
            return db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(start, runtimes)) == ['0008_channel_controls'] * 2
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app, base_url='https://secretai.example.test') as c:
        assert c.get('/health/ready').json() == {'status': 'ok', 'database': 'postgresql'}
        registration = c.post('/api/auth/register', json={'email': 'owner@example.com', 'password': 'test-password-long-123'}, headers={'Origin': 'https://secretai.example.test'})
        assert registration.status_code == 201
        assert 'Secure' in registration.headers['set-cookie']
        csrf = registration.json()['csrf_token']
        created = c.post('/api/organizations', json={'name': 'Persistent test activity'}, headers={'X-CSRF-Token': csrf, 'Origin': 'https://secretai.example.test'})
        assert created.status_code == 200
        cookies = dict(c.cookies)
    # The second function starts from zero and must read the same durable session/data.
    importlib.reload(main)
    with TestClient(main.app, base_url='https://secretai.example.test') as c:
        c.cookies.update(cookies)
        assert c.get('/api/auth/me').json()['email'] == 'owner@example.com'
        assert c.get('/api/organizations').json()[0]['name'] == 'Persistent test activity'
    for runtime in runtimes:
        runtime.engine.dispose()
