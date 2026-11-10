"""Evidence ledger and the claim probe."""
import os
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, compiler, db, extract, llm, ocr, preflight, semantic
from ..core import *  # noqa: F401,F403  shared deps: conn, Actor, ctx, need, log, helpers
from ..core import _me, _owned, _session_for  # noqa: F401

router = APIRouter()


# ------------------------------------------------------------------ evidence ledger

class FactIn(BaseModel):
    key: str
    label: str
    value: str
    numeric: float | None = None
    unit: str | None = None
    comparator: str = "exact"
    aliases: list[str] = []
    disallowed: list[str] = []
    examples: list[str] = []
    approved_phrasing: str | None = None
    source_ref: str | None = None
    owner: str | None = None
    scope: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


@router.get("/api/facts")
def list_facts(a: Actor = Depends(ctx)):
    fs = all_facts(a.workspace_id)
    today = preflight._today()
    for f in fs:
        f["is_valid"] = preflight._valid(f, today)
    return fs


@router.post("/api/facts")
def add_fact(body: FactIn, a: Actor = Depends(ctx)):
    need(a, "admin", "brand_owner")
    if body.comparator not in ("max", "exact", "text"):
        raise HTTPException(400, "comparator must be max | exact | text")
    fid = db.insert(conn, "facts", {**body.model_dump(), "workspace_id": a.workspace_id, "created_at": db.now()})
    log(a, "fact.add", "fact", fid, body.model_dump())
    return db.row(conn.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone())


@router.patch("/api/facts/{fid}")
def edit_fact(fid: int, body: FactIn, a: Actor = Depends(ctx)):
    need(a, "admin", "brand_owner")
    before = _owned("facts", fid, a.workspace_id)
    db.update(conn, "facts", fid, body.model_dump())
    semantic.invalidate(conn, fid)
    log(a, "fact.update", "fact", fid, {"before": {k: before.get(k) for k in body.model_dump()}, "after": body.model_dump()})
    return db.row(conn.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone())


@router.delete("/api/facts/{fid}")
def delete_fact(fid: int, a: Actor = Depends(ctx)):
    need(a, "admin", "brand_owner")
    _owned("facts", fid, a.workspace_id)
    conn.execute("UPDATE findings SET fact_id=NULL WHERE fact_id=?", (fid,))
    conn.execute("DELETE FROM facts WHERE id=?", (fid,))
    conn.commit()
    semantic.invalidate(conn, fid)
    log(a, "fact.delete", "fact", fid)
    return {"ok": True}


class ProbeIn(BaseModel):
    text: str


@router.post("/api/facts/probe")
def probe(body: ProbeIn, a: Actor = Depends(ctx)):
    """Show which approved fact a sentence retrieves, and how it would be judged. Helps brand owners tune examples."""
    facts = all_facts(a.workspace_id)
    ranked = semantic.retrieve(body.text, facts, semantic.index_facts(conn, facts),
                               (semantic.remote_embed([body.text]) or [None])[0] if semantic.remote_enabled() else None)
    findings = semantic.check_semantic(body.text, facts, active_rules(a.workspace_id), [], conn)
    return {"ranked": [{"fact_id": r["fact"]["id"], "label": r["fact"]["label"], "value": r["fact"]["value"],
                        "score": r["score"], "local": r["local"], "remote": r["remote"]} for r in ranked[:5]],
            "threshold": semantic.T_LOCAL, "findings": findings}
