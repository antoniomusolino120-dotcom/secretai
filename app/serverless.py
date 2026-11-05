"""Lazy database startup keeps static routes alive on a misconfigured host.

There is no ephemeral/in-memory database fallback. API operations remain closed
until the dedicated PostgreSQL connection and schema are usable.
"""
import logging
import threading
import time
from contextlib import contextmanager

from fastapi import HTTPException

from app.config import validate
from app.db import build_engine, initialize, make_database

log = logging.getLogger('secretai.startup')


class ServerlessDatabase:
    def __init__(self):
        self.engine = None
        self._database = None
        self._lock = threading.Lock()
        self._retry_at = 0
        self._detail = 'Servizio temporaneamente non disponibile. Riprova tra poco.'

    def ensure_ready(self):
        if self._database is not None:
            return
        with self._lock:
            if self._database is not None:
                return
            if time.monotonic() < self._retry_at:
                raise HTTPException(503, self._detail, headers={'Retry-After': '5'})
            engine = None
            try:
                validate()
                engine = build_engine()
                initialize(engine)
                self.engine = engine
                self._database = make_database(engine)
            except Exception as error:
                if engine is not None:
                    engine.dispose()
                self._retry_at = time.monotonic() + 5
                self._detail = ('Configurazione del servizio incompleta. Collega il database persistente e completa la configurazione del progetto.'
                                if isinstance(error, RuntimeError) else 'Database temporaneamente non disponibile. Riprova tra poco.')
                # Driver exceptions may embed credentials or SQL; never log their text.
                log.error('serverless_startup_failed error_type=%s', type(error).__name__)
                raise HTTPException(503, self._detail, headers={'Retry-After': '5'}) from None

    @contextmanager
    def database(self, write=False, organization_id=None):
        self.ensure_ready()
        with self._database(write=write, organization_id=organization_id) as db:
            yield db
