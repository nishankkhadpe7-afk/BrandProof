"""Accounts, sessions and per-workspace roles (stdlib only).

Passwords: PBKDF2-HMAC-SHA256, 240k iterations, per-user salt.
Sessions: random bearer token; only its SHA-256 is stored; 14-day expiry.
Roles live on the membership, so one person can be a reviewer in one brand
workspace and a creator in another.
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

ROLES = ("creator", "reviewer", "brand_owner", "admin")
ITER = 240_000
SESSION_DAYS = 14
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_failed: dict[str, list[float]] = {}


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITER)
    return f"pbkdf2${ITER}${salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")


def normalise_email(e: str) -> str:
    return (e or "").strip().lower()


def valid_email(e: str) -> bool:
    return bool(EMAIL_RE.match(e))


def throttled(email: str, limit: int = 6, window: float = 300) -> bool:
    """Simple in-memory brute-force guard: max `limit` failed logins per email per window."""
    t = time.time()
    hits = [x for x in _failed.get(email, []) if t - x < window]
    _failed[email] = hits
    return len(hits) >= limit


def record_failure(email: str) -> None:
    _failed.setdefault(email, []).append(time.time())


def clear_failures(email: str) -> None:
    _failed.pop(email, None)


def clean_roles(roles) -> list[str]:
    out = [r for r in (roles or []) if r in ROLES]
    return sorted(set(out), key=ROLES.index)
