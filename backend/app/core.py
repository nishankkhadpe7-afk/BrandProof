"""Shared state and dependencies: DB connection, identity, role checks, scoped helpers."""
import os

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from . import auth, db

conn = db.connect()
db.init(conn)
DEMO = os.environ.get("BRANDPROOF_DEMO", "1") == "1"
ROLES = set(auth.ROLES)

# ------------------------------------------------------------------ identity

class Actor(BaseModel):
    user_id: int | None = None
    name: str
    email: str | None = None
    roles: list[str]
    workspace_id: int

    @property
    def role(self) -> str:
        return ",".join(self.roles) or "none"


def current_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required.")
    th = auth.token_hash(authorization.split(" ", 1)[1].strip())
    u = db.row(conn.execute("SELECT u.id, u.email, u.name, u.is_demo FROM sessions s JOIN users u ON u.id=s.user_id "
                            "WHERE s.token_hash=? AND s.expires_at > ?", (th, db.now())).fetchone())
    if not u:
        raise HTTPException(401, "Session expired. Sign in again.")
    return u


def memberships(user_id: int) -> list[dict]:
    return db.rows(conn.execute(
        "SELECT w.id, w.name, w.brand, w.color, m.roles FROM memberships m JOIN workspaces w ON w.id=m.workspace_id "
        "WHERE m.user_id=? ORDER BY w.id", (user_id,)))


def ctx(user: dict = Depends(current_user), x_workspace: str | None = Header(None)) -> Actor:
    ms = memberships(user["id"])
    if not ms:
        raise HTTPException(403, "You are not a member of any workspace yet. Create one or ask an admin to invite you.")
    m = ms[0]
    if x_workspace:
        m = next((x for x in ms if str(x["id"]) == str(x_workspace)), None)
        if not m:
            raise HTTPException(403, "You are not a member of this workspace.")
    return Actor(user_id=user["id"], name=user["name"], email=user["email"], roles=m["roles"], workspace_id=m["id"])


def need(a: Actor, *roles: str):
    if not set(a.roles) & set(roles):
        label = {"creator": "Creator", "reviewer": "Reviewer", "brand_owner": "Brand owner", "admin": "Admin"}
        raise HTTPException(403, f"This needs the {' or '.join(label[r] for r in roles)} role in this workspace.")


def log(a: Actor, action: str, entity: str, entity_id, detail=None):
    db.audit(conn, a.name, a.role, action, entity, entity_id, detail, workspace_id=a.workspace_id)


def _session_for(user_id: int) -> str:
    tok = auth.new_token()
    db.insert(conn, "sessions", {"user_id": user_id, "token_hash": auth.token_hash(tok), "created_at": db.now(),
                                 "expires_at": auth.expiry()})
    return tok


def _me(user_id: int) -> dict:
    u = db.row(conn.execute("SELECT id, email, name, is_demo FROM users WHERE id=?", (user_id,)).fetchone())
    return {"user": u, "workspaces": memberships(user_id)}


def create_user(name: str, email: str, password: str, is_demo: bool = False) -> int:
    uid = db.insert(conn, "users", {"email": email, "name": name, "password_hash": auth.hash_password(password),
                                    "is_demo": int(is_demo), "created_at": db.now()})
    for inv in db.rows(conn.execute("SELECT * FROM invitations WHERE email=? AND accepted_at IS NULL", (email,))):
        conn.execute("INSERT INTO memberships (workspace_id, user_id, roles, created_at) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                     (inv["workspace_id"], uid, db._enc({"roles": inv["roles"]})["roles"], db.now()))
        conn.execute("UPDATE invitations SET accepted_at=? WHERE id=?", (db.now(), inv["id"]))
        db.audit(conn, name, "invitee", "member.joined", "user", uid, {"email": email}, workspace_id=inv["workspace_id"])
    conn.commit()
    return uid


def create_workspace(name: str, brand: str | None, color: str | None, owner_id: int, owner_name: str) -> int:
    wid = db.insert(conn, "workspaces", {"name": name, "brand": brand or name, "color": color or "#0B3D91",
                                         "created_by": owner_id, "created_at": db.now()})
    db.insert(conn, "memberships", {"workspace_id": wid, "user_id": owner_id, "roles": list(auth.ROLES), "created_at": db.now()})
    db.audit(conn, owner_name, "admin", "workspace.create", "workspace", wid, {"name": name}, workspace_id=wid)
    return wid


# ------------------------------------------------------------------ scoped helpers

def active_rules(wid: int) -> list[dict]:
    rs = db.rows(conn.execute(
        "SELECT r.*, s.name AS source_name, s.version AS source_version FROM rules r "
        "LEFT JOIN sources s ON s.id = r.source_id WHERE r.status='active' AND r.workspace_id=?", (wid,)))
    for r in rs:
        r["source_ref"] = f"{r['source_name']} {r['source_version']}, {r['location']}"
    return rs


def all_facts(wid: int) -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM facts WHERE workspace_id=?", (wid,)))


def _owned(table: str, id_: int, wid: int) -> dict:
    r = db.row(conn.execute(f"SELECT * FROM {table} WHERE id=? AND workspace_id=?", (id_, wid)).fetchone())
    if not r:
        raise HTTPException(404, "Not found in this workspace.")
    return r

