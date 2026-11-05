import os
from urllib.parse import urlparse
from app.secrets import cipher


def on_vercel():
    return os.getenv('VERCEL') == '1'


def public_origin():
    explicit = os.getenv('SECRET_AI_PUBLIC_URL')
    if explicit:
        return explicit.rstrip('/')
    if on_vercel():
        # Use only Vercel-provided configuration, never request/forwarded headers.
        host = (os.getenv('VERCEL_PROJECT_PRODUCTION_URL') if os.getenv('VERCEL_ENV') == 'production'
                else os.getenv('VERCEL_URL'))
        if host:
            parsed = urlparse('https://' + host)
            if parsed.hostname and not parsed.username and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment:
                return 'https://' + parsed.netloc
        raise RuntimeError('Configure SECRET_AI_PUBLIC_URL for this deployment')
    return 'http://localhost:8000'


def validate():
    if os.getenv("SECRET_AI_ENV","development") not in {"development","test","production"}:
        raise RuntimeError("Unknown SecretAI environment")
    if os.getenv("SECRET_AI_ENV", "development") != "production":
        return
    public = urlparse(public_origin())
    if public.scheme != "https" or not public.hostname or public.path not in {"", "/"} or public.query or public.fragment or public.username:
        raise RuntimeError("Production requires an HTTPS public origin")
    cipher()
    if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
        raise RuntimeError("Production requires verified email delivery configuration")
