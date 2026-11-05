"""SecretAI API, independent of every other application and database."""
import logging
import os
from pathlib import Path

import stripe
from fastapi import FastAPI, Depends, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.db import build_engine, initialize, make_database
from app.auth import install as install_auth
from app.http_security import SecurityMiddleware
from app.config import validate, on_vercel

ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
if on_vercel():
    from app.serverless import ServerlessDatabase
    runtime = ServerlessDatabase()
    engine = None
    database = runtime.database
else:
    validate()
    engine = build_engine()
    initialize(engine)
    database = make_database(engine)
app = FastAPI(title="SecretAI", version="0.2.0",
              docs_url=None if os.getenv("SECRET_AI_ENV") == "production" else "/docs",
              redoc_url=None,
              openapi_url=None if os.getenv("SECRET_AI_ENV") == "production" else "/openapi.json")
auth_router, current_user, require_org = install_auth(database)
app.include_router(auth_router)
app.add_middleware(SecurityMiddleware, database=database)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")

@app.exception_handler(stripe.StripeError)
async def stripe_error(request: Request, error):
    return JSONResponse({"detail": "Servizio pagamenti temporaneamente non disponibile"}, status_code=502)

@app.get("/")
def index():
    return FileResponse(ROOT / "app" / "index.html")

@app.get("/health/live")
def live():
    return {"status": "ok"}

@app.get("/health/ready")
def ready():
    with database() as db:
        db.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": db.dialect}

from app.assistant import install as install_assistant
from app.billing import install as install_billing
from app.workspace import install as install_workspace
from app.booking import install as install_booking
from app.meta_channels import install as install_meta
from app.google_calendar import install as install_google
app.include_router(install_assistant(database, current_user, require_org))
app.include_router(install_billing(database, current_user, require_org))
app.include_router(install_workspace(database, current_user, require_org))
app.include_router(install_booking(database, current_user, require_org))
app.include_router(install_meta(database, current_user, require_org))
app.include_router(install_google(database, current_user, require_org))
from app.voice import install as install_voice
from app.browser_automation import install as install_browser
from app.google_reconcile import install as install_reconcile
from app.meta_oauth import install as install_oauth
from app.operations import install as install_operations
for install in (install_voice,install_browser,install_reconcile,install_oauth,install_operations):
    app.include_router(install(database,current_user,require_org))


@app.get("/api/integrations")
def integrations(organization_id: int, user_id: int = Depends(current_user)):
    require_org(user_id, organization_id)
    with database() as db:
        google = bool(db.execute("SELECT 1 FROM google_connections WHERE organization_id=?", (organization_id,)).fetchone())
        meta = [dict(row) for row in db.execute("SELECT provider,external_id FROM meta_channels WHERE organization_id=?", (organization_id,))]
    return {"google": {"configured": all(os.getenv(k) for k in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "SECRET_AI_ENCRYPTION_KEY"]), "connected": google},
            "meta": {"configured": bool(os.getenv("META_APP_SECRET") and os.getenv("META_VERIFY_TOKEN")), "channels": meta},
            "ai": {"provider": "ollama", "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"), "live_verified": False},
            "telephony": {"configured": bool(os.getenv("SECRET_AI_INTERNAL_TOKEN") and os.getenv("PIPER_MODEL")), "implemented": True},
            "billing": {"configured": bool(os.getenv("STRIPE_SECRET_KEY") and os.getenv("STRIPE_WEBHOOK_SECRET") and os.getenv("SECRET_AI_PLANS_JSON"))},
            "computer_use": {"configured": bool(os.getenv("BROWSER_WORKER_URL") and os.getenv("BROWSER_ALLOWED_ORIGINS")), "implemented": True}}

from app.channel_controls import install as install_controls
app.include_router(install_controls(database, current_user, require_org))
