from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


_PREFIX = "enc:"


def _fernet() -> Fernet:
    """Cle de chiffrement : TOKEN_ENCRYPTION_KEY (Fernet) si fournie,
    sinon derivee de SESSION_SECRET (stable entre redemarrages)."""
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if key:
        return Fernet(key.encode("utf-8"))
    secret = os.getenv("SESSION_SECRET", "").strip() or "change-me-in-production"
    derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    if plaintext.startswith(_PREFIX):
        return plaintext  # deja chiffre
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return _PREFIX + token


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        return value  # ancien format en clair : renvoye tel quel (migration douce)
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
