import os
from urllib.parse import urlparse
from app.secrets import cipher


def validate():
    if os.getenv("SECRET_AI_ENV", "development") != "production":
        return
    public = urlparse(os.getenv("SECRET_AI_PUBLIC_URL", ""))
    if public.scheme != "https" or not public.hostname or public.path not in {"", "/"} or public.query or public.fragment or public.username:
        raise RuntimeError("Production requires an HTTPS public origin")
    cipher()
    if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
        raise RuntimeError("Production requires verified email delivery configuration")
