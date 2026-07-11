from __future__ import annotations

import hmac

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings


TOKEN_MAX_AGE_SECONDS = 7 * 24 * 3600
_SALT = "dashboard-session"


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=_SALT)


def verify_credentials(email: str, password: str, settings: Settings) -> bool:
    users = settings.dashboard_users or {}
    # Compat : ancien couple unique si dashboard_users n'est pas peuple.
    if not users and settings.dashboard_email and settings.dashboard_password:
        users = {settings.dashboard_email: settings.dashboard_password}
    stored = users.get(email.strip().lower())
    if not stored:
        return False
    return hmac.compare_digest(password, stored)


def create_token(email: str, settings: Settings) -> str:
    return _serializer(settings).dumps({"email": email})


def verify_token(token: str, settings: Settings) -> str | None:
    try:
        data = _serializer(settings).loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    return data.get("email")
