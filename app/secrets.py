import os
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException


def cipher():
    try:
        return Fernet(os.environ["SECRET_AI_ENCRYPTION_KEY"].encode())
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, "Configura una chiave di cifratura valida")


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(503, "Credenziali non decifrabili: verifica la chiave di cifratura")
