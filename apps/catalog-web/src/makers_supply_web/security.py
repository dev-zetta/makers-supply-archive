from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

PASSWORDS = PasswordHasher()
SESSION_COOKIE = "makers_supply_session"
SESSION_LIFETIME = timedelta(days=14)
REMEMBERED_SESSION_LIFETIME = timedelta(days=30)
INVITE_LIFETIME = timedelta(hours=24)


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(value: str, secret_key: str) -> str:
    return hashlib.sha256(f"{secret_key}:{value}".encode()).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, password)
    except VerifyMismatchError:
        return False
