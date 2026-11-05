"""Private service authentication. Never accepted as a customer/tenant token."""
import hmac
import os
from fastapi import Header, HTTPException

def service_auth(authorization: str = Header(default='')):
    expected = os.getenv('SECRET_AI_INTERNAL_TOKEN', '')
    if len(expected) < 32 or not hmac.compare_digest(authorization, 'Bearer '+expected):
        raise HTTPException(403, 'Service authentication required')
