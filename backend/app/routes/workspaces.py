"""Brand workspaces, members, invitations."""
import os
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, compiler, db, extract, llm, ocr, preflight, semantic
from ..core import *  # noqa: F401,F403  shared deps: conn, Actor, ctx, need, log, helpers
from ..core import _me, _owned, _session_for  # noqa: F401

router = APIRouter()


# ------------------------------------------------------------------ workspaces & members

class WorkspaceIn(BaseModel):
    name: str
    brand: str | None = None
    color: str | None = None


@router.post("/api/workspaces")
def new_workspace(body: WorkspaceIn, user: dict = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Workspace name is required.")
    wid = create_workspace(body.name.strip(), body.brand, body.color, user["id"], user["name"])
    return {"id": wid, **_me(user["id"])}


@router.get("/api/workspace")
def workspace_detail(a: Actor = Depends(ctx)):
    w = db.row(conn.execute("SELECT * FROM workspaces WHERE id=?", (a.workspace_id,)).fetchone())
    w["members"] = db.rows(conn.execute(
        "SELECT u.id, u.name, u.email, m.roles, m.created_at FROM memberships m JOIN users u ON u.id=m.user_id "
        "WHERE m.workspace_id=? ORDER BY m.id", (a.workspace_id,)))
    w["invitations"] = db.rows(conn.execute("SELECT id, email, roles, invited_by, created_at FROM invitations "
                                            "WHERE workspace_id=? AND accepted_at IS NULL ORDER BY id", (a.workspace_id,)))
    w["my_roles"] = a.roles
    return w


@router.patch("/api/workspace")
def edit_workspace(body: WorkspaceIn, a: Actor = Depends(ctx)):
    need(a, "admin")
    db.update(conn, "workspaces", a.workspace_id, {"name": body.name.strip() or "Workspace", "brand": body.brand, "color": body.color})
    log(a, "workspace.update", "workspace", a.workspace_id, body.model_dump())
    return workspace_detail(a)


class MemberIn(BaseModel):
    email: str
    roles: list[str]


@router.post("/api/workspace/members")
def add_member(body: MemberIn, a: Actor = Depends(ctx)):
    need(a, "admin")
    email, roles = auth.normalise_email(body.email), auth.clean_roles(body.roles)
    if not auth.valid_email(email):
        raise HTTPException(400, "Enter a valid email address.")
    if not roles:
        raise HTTPException(400, "Pick at least one role.")
    u = db.row(conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone())
    if u:
        if conn.execute("SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?", (a.workspace_id, u["id"])).fetchone():
            raise HTTPException(409, "Already a member.")
        db.insert(conn, "memberships", {"workspace_id": a.workspace_id, "user_id": u["id"], "roles": roles, "created_at": db.now()})
        log(a, "member.add", "user", u["id"], {"email": email, "roles": roles})
        sent = _notify(a, email, roles, existing=True)
        return {"status": "added", "email_sent": sent, **workspace_detail(a)}
    db.insert(conn, "invitations", {"workspace_id": a.workspace_id, "email": email, "roles": roles,
                                    "invited_by": a.name, "created_at": db.now()})
    log(a, "member.invite", "invitation", None, {"email": email, "roles": roles})
    sent = _notify(a, email, roles, existing=False)
    return {"status": "invited", "email_sent": sent, **workspace_detail(a)}


def _notify(a: Actor, email: str, roles: list[str], existing: bool) -> bool:
    from .. import mailer
    w = db.row(conn.execute("SELECT name FROM workspaces WHERE id=?", (a.workspace_id,)).fetchone())
    label = {"creator": "Creator", "reviewer": "Reviewer", "brand_owner": "Brand owner", "admin": "Admin"}
    role_txt = ", ".join(label[r] for r in roles)
    if existing:
        return mailer.send(email, f"You've been added to {w['name']} on BrandProof", f"You're in {w['name']}",
                           f"{a.name} added you to the {w['name']} workspace as {role_txt}. Sign in and switch to it from the brand menu.",
                           "Open BrandProof", f"{mailer.app_url()}/login")
    return mailer.send(email, f"{a.name} invited you to {w['name']} on BrandProof", f"Join {w['name']} on BrandProof",
                       f"{a.name} invited you to review brand content in {w['name']} as {role_txt}. "
                       "Create an account with this email address and you'll join automatically.",
                       "Accept invitation", f"{mailer.app_url()}/login?invite={email}")


class RolesIn(BaseModel):
    roles: list[str]


def _admins_left(wid: int, excluding: int) -> int:
    return sum(1 for m in db.rows(conn.execute("SELECT user_id, roles FROM memberships WHERE workspace_id=?", (wid,)))
               if m["user_id"] != excluding and "admin" in m["roles"])


@router.patch("/api/workspace/members/{uid}")
def set_member_roles(uid: int, body: RolesIn, a: Actor = Depends(ctx)):
    need(a, "admin")
    roles = auth.clean_roles(body.roles)
    if not roles:
        raise HTTPException(400, "Pick at least one role, or remove the member.")
    if "admin" not in roles and _admins_left(a.workspace_id, uid) == 0:
        raise HTTPException(400, "A workspace needs at least one admin.")
    cur = conn.execute("UPDATE memberships SET roles=? WHERE workspace_id=? AND user_id=?",
                       (db._enc({"roles": roles})["roles"], a.workspace_id, uid))
    conn.commit()
    if not cur.rowcount:
        raise HTTPException(404)
    log(a, "member.roles", "user", uid, {"roles": roles})
    return workspace_detail(a)


@router.delete("/api/workspace/members/{uid}")
def remove_member(uid: int, a: Actor = Depends(ctx)):
    need(a, "admin")
    if _admins_left(a.workspace_id, uid) == 0:
        raise HTTPException(400, "A workspace needs at least one admin.")
    conn.execute("DELETE FROM memberships WHERE workspace_id=? AND user_id=?", (a.workspace_id, uid))
    conn.commit()
    log(a, "member.remove", "user", uid)
    return workspace_detail(a)


@router.delete("/api/workspace/invitations/{iid}")
def cancel_invite(iid: int, a: Actor = Depends(ctx)):
    need(a, "admin")
    conn.execute("DELETE FROM invitations WHERE id=? AND workspace_id=?", (iid, a.workspace_id))
    conn.commit()
    return workspace_detail(a)
