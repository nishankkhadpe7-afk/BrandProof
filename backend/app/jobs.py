"""Background check queue.

Design (outbox + worker, at-least-once):
  * The submission row is the durable job record (check_status: queued | running | done | failed).
  * An in-process queue feeds one worker thread. On startup, rows left queued/running by a
    crash or restart are re-queued, so no submission is lost.
  * Jobs are idempotent (findings are replaced, never appended), so a retry or duplicate run is safe.
  * Failures retry with exponential backoff (2s, 4s, 8s); after MAX_ATTEMPTS the row is marked failed
    with the error, and the UI offers "Check again".
  * BRANDPROOF_SYNC_CHECKS=1 runs jobs inline (tests, seeding, debugging).

Single-instance by design (one Render web service). For several instances, swap the in-process
queue for Redis/RQ or a Postgres SKIP LOCKED poller; the job function stays the same.
"""
import logging
import os
import queue
import threading
import time

from . import db

log = logging.getLogger("brandproof.jobs")
MAX_ATTEMPTS = 3
_q: "queue.Queue[int]" = queue.Queue()
_fn = None
_started = False
_lock = threading.Lock()


def sync_mode() -> bool:
    return os.environ.get("BRANDPROOF_SYNC_CHECKS", "0") == "1"


def register(fn) -> None:
    global _fn
    _fn = fn


def _conn():
    from .core import conn
    return conn


def _attempt(sid: int) -> bool:
    try:
        _fn(sid)
        return True
    except Exception as e:  # recorded on the row, retried with backoff
        conn = _conn()
        r = conn.execute("SELECT attempts FROM submissions WHERE id=?", (sid,)).fetchone()
        n = int((r["attempts"] if r else 0) or 0) + 1
        failed = n >= MAX_ATTEMPTS
        db.update(conn, "submissions", sid, {"attempts": n, "check_status": "failed" if failed else "queued",
                                             "check_error": f"{type(e).__name__}: {e}"[:500]})
        log.warning("check %s failed (attempt %s/%s): %s", sid, n, MAX_ATTEMPTS, e)
        if not failed:
            time.sleep(2 ** n)
        return failed


def _worker():
    while True:
        sid = _q.get()
        try:
            while not _attempt(sid):
                pass
        finally:
            _q.task_done()


def start() -> None:
    """Start the worker and re-queue unfinished jobs (crash recovery)."""
    global _started
    with _lock:
        if _started or sync_mode():
            return
        _started = True
    threading.Thread(target=_worker, name="brandproof-checks", daemon=True).start()
    for r in _conn().execute("SELECT id FROM submissions WHERE check_status IN ('queued','running') ORDER BY id"):
        _q.put(r["id"])


def submit(sid: int, background: bool | None = None) -> None:
    if background is False or (background is None and (sync_mode() or not _started)):
        while not _attempt(sid):
            pass
        return
    _q.put(sid)


def wait_idle(timeout: float = 30) -> None:
    """Block until the queue drains (tests)."""
    end = time.time() + timeout
    while _q.unfinished_tasks and time.time() < end:
        time.sleep(0.05)


def stats() -> dict:
    return {"queued": _q.qsize(), "mode": "inline" if sync_mode() or not _started else "background worker"}
