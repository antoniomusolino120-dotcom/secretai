"""Database-backed throttling and HTTP hardening; safe across API workers."""
import hashlib
import json
import logging
import os
import time
import uuid

from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("secretai.http")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, database):
        super().__init__(app)
        self.database = database

    async def dispatch(self, request, call_next):
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        response = None
        production = os.getenv("SECRET_AI_ENV") == "production"
        try:
            origin = request.headers.get("origin")
            allowed = os.getenv("SECRET_AI_PUBLIC_URL", "http://localhost:8000").rstrip("/")
            # Canonical Vercel frontend proxies API requests to Render; trust only its exact origin.
            trusted_origins = {allowed, "https://secretai-iota.vercel.app"}
            if origin and request.method not in {"GET", "HEAD", "OPTIONS"} and origin not in trusted_origins:
                response = JSONResponse({"detail": "Origine non autorizzata"}, status_code=403)
            if response is None and int(request.headers.get("content-length", "0")) > 1_000_000:
                response = JSONResponse({"detail": "Payload troppo grande"}, status_code=413)
            if response is None and request.url.path.startswith("/api/auth/") and request.method == "POST":
                # No proxy headers: deployment must use the explicitly trusted proxy configuration.
                ip = request.client.host if request.client else "unknown"
                key = hashlib.sha256((ip + ":" + request.url.path).encode()).hexdigest()
                now, window = int(time.time()), int(time.time()) // 300
                with self.database(write=True) as db:
                    db.execute("DELETE FROM rate_limits WHERE window_start<?", (window - 2,))
                    db.execute("""INSERT INTO rate_limits(bucket,window_start,count) VALUES (?,?,1)
                        ON CONFLICT(bucket) DO UPDATE SET
                        count=CASE WHEN rate_limits.window_start=excluded.window_start THEN rate_limits.count+1 ELSE 1 END,
                        window_start=excluded.window_start""", (key, window))
                    count = db.execute("SELECT count FROM rate_limits WHERE bucket=?", (key,)).fetchone()["count"]
                if count > int(os.getenv("SECRET_AI_AUTH_RATE_LIMIT", "30")):
                    response = JSONResponse({"detail": "Troppi tentativi; riprova tra qualche minuto"},
                                            status_code=429, headers={"Retry-After": str(300 - now % 300)})
            if response is None:
                response = await call_next(request)
        except ValueError:
            response = JSONResponse({"detail": "Richiesta non valida"}, status_code=400)
        except SQLAlchemyError as error:
            log.error(json.dumps({"event": "database_error", "request_id": request_id,
                                  "error_type": type(error).__name__,
                                  "sqlstate": getattr(getattr(error, "orig", None), "sqlstate", None)}))
            response = JSONResponse({"detail": "Servizio temporaneamente non disponibile", "request_id": request_id}, status_code=503)
        response.headers.update({"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self' https://connect.facebook.net; frame-src https://www.facebook.com https://web.facebook.com; style-src 'self'; img-src 'self' data:; connect-src 'self' https://graph.facebook.com https://www.facebook.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if request.url.path.startswith(("/api/","/internal/")):
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        # Never log request URLs, query strings, auth headers, prompts or PII.
        log.info(json.dumps({"event": "request", "request_id": request_id,
                             "method": request.method, "status": response.status_code,
                             "duration_ms": round((time.monotonic() - started) * 1000)}))
        return response
