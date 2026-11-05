"""Hosted deployments must never silently create an empty, temporary account store."""
import pytest
from app.db import database_url


@pytest.fixture
def clean_database_env(monkeypatch):
    for name in ('SECRET_AI_DATABASE_URL', 'DATABASE_URL', 'SECRET_AI_REQUIRE_POSTGRES', 'RENDER'):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_hosted_deployment_requires_persistent_database(clean_database_env):
    env = clean_database_env
    env.setenv('RENDER', 'true')
    with pytest.raises(RuntimeError, match='persistent PostgreSQL'):
        database_url()
    env.setenv('SECRET_AI_DATABASE_URL', 'sqlite:////srv/data/secretai.db')
    with pytest.raises(RuntimeError, match='persistent PostgreSQL'):
        database_url()


def test_hosted_deployment_accepts_standard_database_url(clean_database_env):
    env = clean_database_env
    env.setenv('RENDER', 'true')
    env.setenv('DATABASE_URL', 'postgresql://test:fixture@db/secretai')
    assert database_url() == 'postgresql+psycopg://test:fixture@db/secretai'
    env.setenv('SECRET_AI_DATABASE_URL', 'postgres://test:fixture@dedicated/secretai')
    assert database_url() == 'postgresql+psycopg://test:fixture@dedicated/secretai'


def test_persistence_requirement_applies_outside_render(clean_database_env):
    clean_database_env.setenv('SECRET_AI_REQUIRE_POSTGRES', '1')
    with pytest.raises(RuntimeError, match='persistent PostgreSQL'):
        database_url()


def test_local_development_can_still_use_sqlite(clean_database_env, tmp_path):
    path = tmp_path / 'local.db'
    clean_database_env.setenv('SECRET_AI_DB', str(path))
    assert database_url() == 'sqlite:///' + str(path)
