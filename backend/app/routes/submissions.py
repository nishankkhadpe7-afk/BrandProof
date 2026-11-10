"""Submissions, findings, revisions and the approval gate.

Checks run in the background (see jobs.py): the upload is stored, a job is queued, and the
client polls `check_status` (queued -> running -> done | failed). OCR, semantic retrieval and
LLM calls no longer hold the request open.
"""
import io
import os
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db, extract, jobs, llm, ocr, preflight
from ..core import *  # noqa: F401,F403
from ..core import _owned  # noqa: F401

router = APIRouter()
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
MAX_TEXT = int(os.environ.get("MAX_TEXT_CHARS", "50000"))
ALLOWED = {".txt", ".md", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}


# ------------------------------------------------------------------ check pipeline (runs in the worker)

def _run_preflight(sid: int, text: str, wid: int, img=None, meta=None, alt_text=None, ocr_words=None, ocr_engine="n/a") -> list[dict]:
    findings = preflight.run(text, active_rules(wid), all_facts(wid), img=img, meta=meta, alt_text=alt_text,
                             ocr_words=ocr_words, conn=conn, ocr_engine=ocr_engine)
    for f in findings:
        db.insert(conn, "findings", {"submission_id": sid, **f})
    return findings


def _save_pages(sid: int, images) -> int:
    for i, im in enumerate(images):
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        db.put_blob(conn, f"sub-{sid}-p{i}.png", buf.getvalue())
    return len(images)


def _ingest(filename: str, data: bytes, text: str, alt_text: str):
    """Return kind, text, img, meta, page_images, ocr payload."""
    kind = extract.kind_for(filename)
    img, meta, pages, ocr_payload = None, None, [], None
    if kind == "image":
        img = extract.load_image(data)
        meta = preflight.image_meta(img)
        t, words, eng = ocr.ocr_image(img)
        ocr_payload = {"engine": eng, "words": words, "chars": len(t)}
        text, pages = t, [img]
    elif kind == "pdf":
        res = ocr.read_pdf(data)
        text, pages = res["text"], res["images"]
        if res["scanned"]:
            ocr_payload = {"engine": res["engine"], "words": res["words"], "chars": len(text), "scanned": True}
    else:
        text = extract.extract_text(filename, data)
    return kind, text, img, meta, pages, ocr_payload


def _carry_overrides(old: dict, new_id: int):
    overrides = {(f["rule_id"], f["fact_id"], f["excerpt"]): f for f in old["findings"] if f["decision"] == "overridden"}
    for nf in db.rows(conn.execute("SELECT * FROM findings WHERE submission_id=?", (new_id,))):
        o = overrides.get((nf["rule_id"], nf["fact_id"], nf["excerpt"]))
        if o:
            db.update(conn, "findings", nf["id"], {"decision": "overridden", "decided_by": o["decided_by"],
                                                   "decision_reason": f"{o['decision_reason']} (carried from rev {old['revision']})"})


def check_submission(sid: int) -> None:
    """The job. Idempotent: safe to run again after a crash or retry (at-least-once delivery)."""
    s = db.row(conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone())
    if not s or s["check_status"] == "done":
        return
    db.update(conn, "submissions", sid, {"check_status": "running"})
    src = db.get_blob(conn, f"sub-{sid}-src")
    img = None
    if src is not None and not s.get("ingested"):
        kind, text, img, meta, pages, ocr_payload = _ingest(s["filename"], src, s["text"], s.get("alt_text") or "")
        db.update(conn, "submissions", sid, {"kind": kind, "text": text, "image_meta": meta, "ocr": ocr_payload,
                                             "pages": _save_pages(sid, pages), "ingested": 1})
        s = db.row(conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone())
    if s["kind"] == "image" and img is None:
        data = db.get_blob(conn, f"sub-{sid}-p0.png")
        img = extract.load_image(data) if data else None
    o = s.get("ocr") or {}
    conn.execute("DELETE FROM findings WHERE submission_id=?", (sid,))  # idempotency: replace, never duplicate
    conn.commit()
    findings = _run_preflight(sid, s["text"], s["workspace_id"], img, s.get("image_meta"), s.get("alt_text"),
                              o.get("words"), o.get("engine") if s["kind"] == "image" or o.get("scanned") else "n/a")
    if s.get("parent_id"):
        _carry_overrides(_submission(s["parent_id"], s["workspace_id"]), sid)
    db.update(conn, "submissions", sid, {"check_status": "done", "check_error": None})
    db.audit(conn, s["author"], "system", "submission.preflight", "submission", sid,
             {"findings": len(findings), "by_status": dict(Counter(f["status"] for f in findings)),
              "ai": llm.status()["mode"], "ocr": o.get("engine"), "revision_of": s.get("parent_id")},
             workspace_id=s["workspace_id"])


jobs.register(check_submission)


def _create_submission(a, title, channel, kind, filename, text, alt_text, img, meta, pages, ocr_payload,
                       parent: dict | None = None, source: bytes | None = None, background: bool | None = None) -> int:
    """Store the submission, then check it (in the worker unless background=False or sync mode)."""
    sid = db.insert(conn, "submissions", {
        "workspace_id": a.workspace_id, "title": title, "channel": channel,
        "author": parent["author"] if parent else a.name, "kind": kind, "filename": filename, "text": text or "",
        "alt_text": alt_text or None, "image_meta": meta, "ocr": ocr_payload, "check_status": "queued",
        "ingested": 0 if source is not None else 1,
        "revision": parent["revision"] + 1 if parent else 1, "parent_id": parent["id"] if parent else None,
        "created_at": db.now()})
    if source is not None:
        db.put_blob(conn, f"sub-{sid}-src", source)
    elif pages:
        db.update(conn, "submissions", sid, {"pages": _save_pages(sid, pages)})
    log(a, "submission.queued", "submission", sid, {"file": filename, "revision_of": parent["id"] if parent else None})
    jobs.submit(sid, background)
    return sid


# ------------------------------------------------------------------ endpoints

async def _read(file: UploadFile) -> bytes:
    """Reject bad uploads up front, so a broken file never becomes a failed background job."""
    ext = os.path.splitext((file.filename or "").lower())[1]
    if ext not in ALLOWED:
        raise HTTPException(400, "That file type isn't supported. Upload a PNG, JPG or WEBP image, a PDF, a Word (.docx) file, or TXT/Markdown.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "That file is empty.")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD // (1024 * 1024)} MB.")
    try:
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            extract.load_image(data)
        elif ext == ".pdf":
            import pymupdf
            with pymupdf.open(stream=data, filetype="pdf") as d:
                if d.page_count == 0:
                    raise ValueError
        elif ext == ".docx":
            extract.extract_text(file.filename, data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "That file couldn't be opened. It may be damaged or not really the type its name says.")
    return data


def _check_text(text: str):
    if len(text) > MAX_TEXT:
        raise HTTPException(413, f"That's more than {MAX_TEXT:,} characters. Split it into smaller pieces.")


@router.post("/api/submissions")
async def submit(title: str = Form(...), channel: str = Form("web"), text: str = Form(""), alt_text: str = Form(""),
                 file: UploadFile | None = File(None), a: Actor = Depends(ctx)):
    need(a, "creator", "admin", "brand_owner")
    if file is not None and file.filename:
        data = await _read(file)
        sid = _create_submission(a, title, channel, extract.kind_for(file.filename), file.filename, "", alt_text,
                                 None, None, [], None, source=data)
    else:
        if not text.strip():
            raise HTTPException(400, "Nothing to check. Paste some copy or upload a file.")
        _check_text(text)
        sid = _create_submission(a, title, channel, "text", None, text, alt_text, None, None, [], None)
    return _submission(sid, a.workspace_id)


@router.get("/api/submissions")
def list_submissions(a: Actor = Depends(ctx)):
    subs = db.rows(conn.execute("SELECT id, title, channel, author, kind, revision, parent_id, status, check_status, created_at "
                                "FROM submissions WHERE workspace_id=? ORDER BY id DESC", (a.workspace_id,)))
    for s in subs:
        c = conn.execute("SELECT COUNT(*) n, SUM(CASE WHEN severity='high' AND decision='pending' THEN 1 ELSE 0 END) hp, "
                         "SUM(CASE WHEN decision='pending' THEN 1 ELSE 0 END) p "
                         "FROM findings WHERE submission_id=? AND status!='supported'", (s["id"],)).fetchone()
        s.update({"findings": int(c["n"]), "high_pending": int(c["hp"] or 0), "pending": int(c["p"] or 0)})
    return subs


def _submission(sid: int, wid: int) -> dict:
    s = _owned("submissions", sid, wid)
    s["findings"] = db.rows(conn.execute(
        "SELECT f.*, r.text AS rule_text, r.type AS rule_type, fa.label AS fact_label, fa.value AS fact_value "
        "FROM findings f LEFT JOIN rules r ON r.id=f.rule_id LEFT JOIN facts fa ON fa.id=f.fact_id "
        "WHERE f.submission_id=? ORDER BY f.id", (sid,)))
    if s.get("ocr"):
        s["ocr_engine"] = s["ocr"].get("engine")
        s["ocr_words"] = len(s["ocr"].get("words") or [])
    s.pop("ocr", None)
    chain, cur = [], s
    while cur and cur.get("parent_id"):
        cur = db.row(conn.execute("SELECT id, revision, status, created_at, parent_id FROM submissions WHERE id=?", (cur["parent_id"],)).fetchone())
        if cur:
            chain.append(cur)
    s["history"] = chain
    s["next_revision"] = db.row(conn.execute("SELECT id, revision FROM submissions WHERE parent_id=?", (sid,)).fetchone())
    s["audit"] = db.rows(conn.execute("SELECT * FROM audit WHERE workspace_id=? AND ((entity='submission' AND entity_id=?) OR "
                                      "(entity='finding' AND entity_id IN (SELECT id FROM findings WHERE submission_id=?))) ORDER BY id",
                                      (wid, sid, sid)))
    return s


@router.get("/api/submissions/{sid}")
def get_submission(sid: int, a: Actor = Depends(ctx)):
    return _submission(sid, a.workspace_id)


@router.post("/api/submissions/{sid}/recheck")
def recheck(sid: int, a: Actor = Depends(ctx)):
    """Re-run a failed or stale check (idempotent)."""
    need(a, "creator", "reviewer", "brand_owner", "admin")
    s = _owned("submissions", sid, a.workspace_id)
    if s["status"] not in ("in_review", "changes_requested"):
        raise HTTPException(409, f"Submission is {s['status']}")
    if s["check_status"] in ("queued", "running"):
        raise HTTPException(409, "A check is already in progress.")
    db.update(conn, "submissions", sid, {"check_status": "queued", "attempts": 0})
    log(a, "submission.recheck", "submission", sid)
    jobs.submit(sid)
    return _submission(sid, a.workspace_id)


@router.get("/api/submissions/{sid}/image")
def submission_image(sid: int, page: int = 0, a: Actor = Depends(ctx)):
    _owned("submissions", sid, a.workspace_id)
    data = db.get_blob(conn, f"sub-{sid}-p{page}.png")
    if data is None:
        raise HTTPException(404)
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


class Decision(BaseModel):
    decision: str
    text: str | None = None
    reason: str | None = None


def _open(s: dict):
    if s["status"] not in ("in_review", "changes_requested"):
        raise HTTPException(409, f"Submission is {s['status']}; decisions are locked.")
    if s.get("check_status") not in (None, "done"):
        raise HTTPException(409, "The check is still running. Wait for it to finish.")


@router.post("/api/findings/{fid}/decision")
def decide(fid: int, body: Decision, a: Actor = Depends(ctx)):
    f = db.row(conn.execute("SELECT f.* FROM findings f JOIN submissions s ON s.id=f.submission_id "
                            "WHERE f.id=? AND s.workspace_id=?", (fid, a.workspace_id)).fetchone())
    if not f:
        raise HTTPException(404)
    _open(db.row(conn.execute("SELECT status, check_status FROM submissions WHERE id=?", (f["submission_id"],)).fetchone()))
    if body.decision == "overridden":
        need(a, "reviewer", "brand_owner")
        if not (body.reason or "").strip():
            raise HTTPException(400, "An override requires a reason.")
    elif body.decision in ("accepted", "edited", "pending"):
        need(a, "creator", "reviewer", "brand_owner")
        if body.decision == "accepted" and f["suggestion"] is None:
            raise HTTPException(400, "No suggestion to accept; use edit.")
        if body.decision == "edited" and body.text is None:
            raise HTTPException(400, "Edited decision needs replacement text.")
    else:
        raise HTTPException(400, "decision must be accepted | edited | overridden | pending")
    db.update(conn, "findings", fid, {"decision": body.decision, "decision_text": body.text,
                                      "decision_reason": body.reason, "decided_by": a.name})
    log(a, f"finding.{body.decision}", "finding", fid,
        {"excerpt": f["excerpt"], "suggestion": f["suggestion"], "text": body.text, "reason": body.reason})
    return db.row(conn.execute("SELECT * FROM findings WHERE id=?", (fid,)).fetchone())


@router.post("/api/submissions/{sid}/revise")
def revise(sid: int, a: Actor = Depends(ctx)):
    """Apply accepted/edited fixes, create a new revision and re-check it."""
    need(a, "creator", "reviewer", "brand_owner")
    s = _submission(sid, a.workspace_id)
    _open(s)
    if s["kind"] == "image" or s.get("pages"):
        raise HTTPException(400, "Creatives are revised by uploading a corrected file.")
    new_text = preflight.apply_fixes(s["text"], s["findings"])
    nid = _create_submission(a, s["title"], s["channel"], "text", s["filename"], new_text, None, None, None, [], None, parent=s)
    db.update(conn, "submissions", sid, {"status": "superseded"})
    log(a, "submission.revise", "submission", sid, {"new_revision": nid})
    return _submission(nid, a.workspace_id)


@router.post("/api/submissions/{sid}/revise-upload")
async def revise_upload(sid: int, file: UploadFile = File(...), alt_text: str = Form(""), a: Actor = Depends(ctx)):
    """Upload a corrected creative as the next revision; overrides carry forward."""
    need(a, "creator", "reviewer", "brand_owner")
    s = _submission(sid, a.workspace_id)
    _open(s)
    data = await _read(file)
    nid = _create_submission(a, s["title"], s["channel"], extract.kind_for(file.filename), file.filename, "",
                             alt_text or s.get("alt_text") or "", None, None, [], None, parent=s, source=data)
    db.update(conn, "submissions", sid, {"status": "superseded"})
    log(a, "submission.revise", "submission", sid, {"new_revision": nid, "upload": file.filename})
    return _submission(nid, a.workspace_id)


class StatusIn(BaseModel):
    status: str
    reason: str | None = None


@router.post("/api/submissions/{sid}/status")
def set_status(sid: int, body: StatusIn, a: Actor = Depends(ctx)):
    need(a, "reviewer", "brand_owner")
    s = _submission(sid, a.workspace_id)
    _open(s)
    if body.status == "approved":
        blocking = [f for f in s["findings"] if f["decision"] == "pending" and f["severity"] in ("high", "medium")]
        if blocking:
            raise HTTPException(409, f"{len(blocking)} high/medium finding(s) still pending. Accept, edit or override each first.")
    elif body.status in ("rejected", "changes_requested"):
        if not (body.reason or "").strip():
            raise HTTPException(400, "A reason is required.")
    else:
        raise HTTPException(400, "Invalid status")
    db.update(conn, "submissions", sid, {"status": body.status})
    log(a, f"submission.{body.status}", "submission", sid, {"reason": body.reason})
    return _submission(sid, a.workspace_id)
