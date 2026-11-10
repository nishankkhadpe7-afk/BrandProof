"""Guideline sources and the policy compiler (Engine A)."""
import os
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, compiler, db, extract, llm, ocr, preflight, semantic
from ..core import *  # noqa: F401,F403  shared deps: conn, Actor, ctx, need, log, helpers
from ..core import _me, _owned, _session_for  # noqa: F401

router = APIRouter()


# ------------------------------------------------------------------ sources & compiler

@router.get("/api/sources")
def list_sources(a: Actor = Depends(ctx)):
    return db.rows(conn.execute("SELECT id, kind, name, version, filename, owner, uploaded_at, length(text) AS chars "
                                "FROM sources WHERE workspace_id=? ORDER BY id DESC", (a.workspace_id,)))


@router.get("/api/sources/{sid}")
def get_source(sid: int, a: Actor = Depends(ctx)):
    return _owned("sources", sid, a.workspace_id)


def _store_guideline(name: str, version: str, filename: str | None, text: str, a: Actor) -> dict:
    sid = db.insert(conn, "sources", {"workspace_id": a.workspace_id, "kind": "guideline", "name": name, "version": version,
                                      "filename": filename, "text": text, "owner": a.name, "uploaded_at": db.now()})
    compiled = compiler.compile_guidelines(text)
    existing = db.rows(conn.execute("SELECT * FROM rules WHERE status='active' AND workspace_id=?", (a.workspace_id,)))
    for e in existing:
        e["location"] = f"rule #{e['id']}"
    if existing:
        compiler._conflicts(compiled + existing)
    for r in compiled:
        db.insert(conn, "rules", {"workspace_id": a.workspace_id, "source_id": sid, "type": r["type"], "category": r["category"],
                                  "params": r["params"], "severity": r["severity"], "text": r["text"], "location": r["location"],
                                  "status": "proposed", "ambiguity": r["ambiguity"], "engine": r["engine"], "created_at": db.now()})
    flagged = sum(1 for r in compiled if r["ambiguity"])
    log(a, "source.upload+compile", "source", sid, {"rules_proposed": len(compiled), "flagged": flagged})
    return {"source_id": sid, "rules_proposed": len(compiled), "flagged_for_review": flagged}


@router.post("/api/sources/guidelines")
async def upload_guidelines(name: str = Form(...), version: str = Form("v1"), text: str = Form(""),
                            file: UploadFile | None = File(None), a: Actor = Depends(ctx)):
    need(a, "admin", "brand_owner")
    filename = None
    if file is not None and file.filename:
        filename = file.filename
        if os.path.splitext(filename.lower())[1] not in (".pdf", ".docx", ".txt", ".md"):
            raise HTTPException(400, "Guidelines must be a PDF, Word (.docx), TXT or Markdown file.")
        data = await file.read()
        if not data:
            raise HTTPException(400, "That file is empty.")
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(413, "File is larger than 15 MB.")
        if extract.kind_for(filename) == "pdf":
            try:
                text = ocr.read_pdf(data)["text"]  # scanned guideline PDFs work too
            except Exception:
                raise HTTPException(400, "That PDF couldn't be opened. It may be damaged.")
        else:
            try:
                text = extract.extract_text(filename, data)
            except Exception:
                raise HTTPException(400, "That file couldn't be opened. It may be damaged.")
    if not text.strip():
        raise HTTPException(400, "No text found. Paste the guidelines or upload a PDF, Word or TXT file that contains text.")
    return _store_guideline(name, version, filename, text, a)


@router.get("/api/rules")
def list_rules(status: str | None = None, a: Actor = Depends(ctx)):
    q = ("SELECT r.*, s.name AS source_name, s.version AS source_version FROM rules r "
         "LEFT JOIN sources s ON s.id=r.source_id WHERE r.workspace_id=?")
    args: list = [a.workspace_id]
    if status:
        q += " AND r.status=?"
        args.append(status)
    return db.rows(conn.execute(q + " ORDER BY r.id", args))


class RuleUpdate(BaseModel):
    status: str | None = None
    params: dict | None = None
    severity: str | None = None
    type: str | None = None


@router.patch("/api/rules/{rid}")
def update_rule(rid: int, body: RuleUpdate, a: Actor = Depends(ctx)):
    need(a, "admin", "brand_owner")
    r = _owned("rules", rid, a.workspace_id)
    data = body.model_dump(exclude_none=True)
    if "type" in data:
        if data["type"] not in compiler.CATEGORY:
            raise HTTPException(400, "Unknown rule type")
        data["category"] = compiler.CATEGORY[data["type"]]
    if data.get("status") == "active":
        rtype = data.get("type", r["type"])
        params = data.get("params", r["params"])
        if rtype == "unclassified":
            raise HTTPException(400, "Assign a rule type before activating.")
        missing = compiler.missing_params(rtype, params)
        if missing:
            raise HTTPException(400, f"Fill measurable values before activating: {', '.join(missing)}")
        data["validated_by"] = a.name
    if "params" in data or "type" in data:
        data["ambiguity"] = [x for x in r["ambiguity"] if x["kind"] in ("vague", "conflict")]
    db.update(conn, "rules", rid, data)
    log(a, "rule.update", "rule", rid, {"before": {k: r.get(k) for k in data}, "after": data})
    return db.row(conn.execute("SELECT * FROM rules WHERE id=?", (rid,)).fetchone())
