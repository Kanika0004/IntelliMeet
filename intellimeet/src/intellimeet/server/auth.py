"""User accounts for a hosted IntelliMeet: password hashing and cookie sessions (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Optional

COOKIE = "im_session"
SESSION_DAYS = 30
ITERATIONS = 240_000

# The signed-in user for the current request (set by the auth middleware in app.py).
current_user: ContextVar[Optional[dict]] = ContextVar("current_user", default=None)


def enabled() -> bool:
    """Accounts are on when AUTH_ENABLED=true (the hosted server); a local single-user install keeps them off."""
    return os.environ.get("AUTH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def signup_allowed() -> bool:
    return os.environ.get("ALLOW_SIGNUP", "true").strip().lower() in {"1", "true", "yes", "on"}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def new_token() -> tuple[str, str, str]:
    """Return (token for the cookie, sha256 of it for the database, expiry ISO time)."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    return token, token_hash(token), expires


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"])}


def uid() -> Optional[int]:
    u = current_user.get()
    return u["id"] if u else None
