"""Accounts: register, login, sessions, demo accounts."""
import os
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, compiler, db, extract, llm, ocr, preflight, semantic
from ..core import *  # noqa: F401,F403  shared deps: conn, Actor, ctx, need, log, helpers
from ..core import _me, _owned, _session_for  # noqa: F401

router = APIRouter()


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    workspace_name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/api/auth/register")
def register(body: RegisterIn):
    email = auth.normalise_email(body.email)
    if not auth.valid_email(email):
        raise HTTPException(400, "Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if not body.name.strip():
        raise HTTPException(400, "Enter your name.")
    if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    uid = create_user(body.name.strip(), email, body.password)
    if body.workspace_name and body.workspace_name.strip() or not memberships(uid):
        create_workspace((body.workspace_name or "").strip() or f"{body.name.strip()}'s brand", None, None, uid, body.name.strip())
    return {"token": _session_for(uid), **_me(uid)}


@router.post("/api/auth/login")
def login(body: LoginIn):
    email = auth.normalise_email(body.email)
    if auth.throttled(email):
        raise HTTPException(429, "Too many failed attempts. Wait a few minutes and try again.")
    u = db.row(conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
    if not u or not auth.verify_password(body.password, u["password_hash"]):
        auth.record_failure(email)
        raise HTTPException(401, "Email or password is incorrect.")
    auth.clear_failures(email)
    return {"token": _session_for(u["id"]), **_me(u["id"])}


@router.post("/api/auth/logout")
def logout(authorization: str | None = Header(None)):
    if authorization and authorization.lower().startswith("bearer "):
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (auth.token_hash(authorization.split(" ", 1)[1].strip()),))
        conn.commit()
    return {"ok": True}


@router.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return _me(user["id"])


@router.get("/api/auth/demo")
def demo_accounts():
    if not DEMO:
        return []
    out = []
    for u in db.rows(conn.execute("SELECT id, email, name FROM users WHERE is_demo=1 ORDER BY id")):
        u["workspaces"] = [{"name": m["name"], "roles": m["roles"]} for m in memberships(u["id"])]
        out.append(u)
    return out


class DemoIn(BaseModel):
    email: str


@router.post("/api/auth/demo")
def demo_login(body: DemoIn):
    if not DEMO:
        raise HTTPException(404)
    u = db.row(conn.execute("SELECT id FROM users WHERE email=? AND is_demo=1", (auth.normalise_email(body.email),)).fetchone())
    if not u:
        raise HTTPException(404, "Unknown demo account")
    return {"token": _session_for(u["id"]), **_me(u["id"])}



# ------------------------------------------------------------------ password reset

class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/api/auth/forgot")
def forgot_password(body: ForgotIn):
    """Always answers the same way, so it can't be used to find out who has an account."""
    from datetime import datetime, timedelta, timezone
    from .. import mailer
    email = auth.normalise_email(body.email)
    u = db.row(conn.execute("SELECT id, name, is_demo FROM users WHERE email=?", (email,)).fetchone())
    if u and not u["is_demo"]:  # demo accounts are shared, so their passwords can't be changed
        tok = auth.new_token()
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        db.insert(conn, "password_resets", {"user_id": u["id"], "token_hash": auth.token_hash(tok), "created_at": db.now(), "expires_at": exp})
        mailer.send(email, "Reset your BrandProof password", "Reset your password",
                    f"Hi {u['name']}, someone asked to reset the password for this account. The link works once and expires in 1 hour. "
                    "If it wasn't you, ignore this email.", "Choose a new password", f"{mailer.app_url()}/reset?token={tok}")
    return {"ok": True, "message": "If an account exists for that email, a reset link is on its way."}


@router.post("/api/auth/reset")
def reset_password(body: ResetIn):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    r = db.row(conn.execute("SELECT * FROM password_resets WHERE token_hash=?", (auth.token_hash(body.token.strip()),)).fetchone())
    if not r or r["used_at"] or r["expires_at"] < db.now():
        raise HTTPException(400, "This reset link is invalid or has expired. Ask for a new one.")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(body.password), r["user_id"]))
    conn.execute("UPDATE password_resets SET used_at=? WHERE id=?", (db.now(), r["id"]))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (r["user_id"],))  # sign out everywhere
    conn.commit()
    u = db.row(conn.execute("SELECT name FROM users WHERE id=?", (r["user_id"],)).fetchone())
    db.audit(conn, u["name"], "user", "user.password_reset", "user", r["user_id"])
    return {"token": _session_for(r["user_id"]), **_me(r["user_id"])}
