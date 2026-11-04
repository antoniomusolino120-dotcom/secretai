"""Deployment safety guardrails for the development-only app."""
import os
from fastapi import HTTPException

def enforce_local_only():
    # Default is local-only. To expose remotely, an explicit opt-in is required.
    if os.getenv("SECRET_AI_ALLOW_REMOTE") == "1":
        raise RuntimeError(
            "Remote deployment is disabled until production auth, CSRF, rate limits, "
            "audit logging and secrets management have been implemented."
        )
