"""Per-client rate limiting (token bucket), applied as ASGI middleware.

Limits per client per minute (client = bearer token if present, else IP from X-Forwarded-For):
  auth        login / register / demo     10   (plus the per-email failed-login throttle in auth.py)
  upload      new checks and revisions    20
  write       other POST / PATCH / DELETE 90
  read        GET                         300
Exceeding a limit returns 429 with Retry-After. Set RATE_LIMIT=0 to disable, or RATE_LIMIT_SCALE to
loosen/tighten all limits. In-memory, so it is per instance (fine for a single Render service).
"""
import hashlib
import os
import threading
import time

from starlette.responses import JSONResponse

LIMITS = {"auth": 10, "upload": 20, "write": 90, "read": 300}
_buckets: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()


def _enabled() -> bool:
    return os.environ.get("RATE_LIMIT", "1") != "0"


def _scale() -> float:
    try:
        return max(0.01, float(os.environ.get("RATE_LIMIT_SCALE", "1")))
    except ValueError:
        return 1.0


def classify(method: str, path: str) -> str | None:
    if method == "OPTIONS" or path in ("/api/health", "/docs", "/openapi.json"):
        return None
    if path.startswith("/api/auth/") and method == "POST" and not path.endswith("/logout"):
        return "auth"
    if method == "POST" and (path == "/api/submissions" or path.endswith(("/revise", "/revise-upload", "/recheck"))
                             or path in ("/api/sources/guidelines", "/api/integrations/figma/check")):
        return "upload"
    return "read" if method == "GET" else "write"


def client_key(headers: dict, client_host: str | None) -> str:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return "t:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
    fwd = headers.get("x-forwarded-for", "")
    return "ip:" + (fwd.split(",")[0].strip() or client_host or "?")


def take(key: str, kind: str, now: float | None = None) -> float:
    """Consume one token. Returns 0 if allowed, else seconds until a token is free."""
    cap = max(1, int(LIMITS[kind] * _scale()))
    rate = cap / 60.0
    now = now or time.monotonic()
    with _lock:
        tokens, last = _buckets.get((key, kind), [cap, now])
        tokens = min(cap, tokens + (now - last) * rate)
        if tokens >= 1:
            _buckets[(key, kind)] = [tokens - 1, now]
            return 0.0
        _buckets[(key, kind)] = [tokens, now]
        return (1 - tokens) / rate


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not _enabled():
            return await self.app(scope, receive, send)
        kind = classify(scope["method"], scope["path"])
        if kind:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            wait = take(client_key(headers, (scope.get("client") or [None])[0]), kind)
            if wait:
                resp = JSONResponse({"detail": f"Too many requests. Try again in {int(wait) + 1} s."}, status_code=429,
                                    headers={"Retry-After": str(int(wait) + 1)})
                return await resp(scope, receive, send)
        return await self.app(scope, receive, send)
