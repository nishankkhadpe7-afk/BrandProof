"""BrandProof API."""
import os
from collections import Counter

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import compiler, db, extract, llm, preflight

app = FastAPI(title="BrandProof API", version="0.1.0",
              description="Pre-publication gate for brand-safe content. AI suggests; humans decide.")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

conn = db.connect()
db.init(conn)

ROLES = {"creator", "brand_owner", "reviewer", "admin"}


class Actor(BaseModel):
    name: str
    role: str


def actor(x_user: str = Header("demo-user"), x_role: str = Header("creator")) -> Actor:
    if x_role not in ROLES:
        raise HTTPException(400, f"Unknown role {x_role}")
    return Actor(name=x_user, role=x_role)


def need(a: Actor, *roles: str):
    if a.role not in roles:
        raise HTTPException(403, f"Role '{a.role}' cannot do this. Requires: {', '.join(roles)}")


def active_rules() -> list[dict]:
    rs = db.rows(conn.execute(
        "SELECT r.*, s.name AS source_name, s.version AS source_version FROM rules r "
        "LEFT JOIN sources s ON s.id = r.source_id WHERE r.status = 'active'"))
    for r in rs:
        r["source_ref"] = f"{r['source_name']} {r['source_version']}, {r['location']}"
    return rs


def all_facts() -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM facts"))


# ------------------------------------------------------------------ meta

@app.get("/api/health")
def health():
    return {"ok": True, "ai": llm.status()}


# ------------------------------------------------------------------ sources & compiler

@app.get("/api/sources")
def list_sources():
    return db.rows(conn.execute("SELECT id, kind, name, version, filename, owner, uploaded_at, length(text) AS chars FROM sources ORDER BY id DESC"))


@app.get("/api/sources/{sid}")
def get_source(sid: int):
    s = db.row(conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())
    if not s:
        raise HTTPException(404)
    return s


def _store_guideline(name: str, version: str, filename: str | None, text: str, a: Actor) -> dict:
    sid = db.insert(conn, "sources", {"kind": "guideline", "name": name, "version": version, "filename": filename,
                                      "text": text, "owner": a.name, "uploaded_at": db.now()})
    compiled = compiler.compile_guidelines(text)
    # conflicts against rules already active from other sources
    existing = db.rows(conn.execute("SELECT * FROM rules WHERE status='active'"))
    for e in existing:
        e["location"] = f"rule #{e['id']}"
    compiler._conflicts(compiled + existing) if existing else None
    for r in compiled:
        db.insert(conn, "rules", {"source_id": sid, "type": r["type"], "category": r["category"], "params": r["params"],
                                  "severity": r["severity"], "text": r["text"], "location": r["location"],
                                  "status": "proposed", "ambiguity": r["ambiguity"], "engine": r["engine"],
                                  "created_at": db.now()})
    db.audit(conn, a.name, a.role, "source.upload+compile", "source", sid,
             {"rules_proposed": len(compiled), "flagged": sum(1 for r in compiled if r["ambiguity"])})
    return {"source_id": sid, "rules_proposed": len(compiled),
            "flagged_for_review": sum(1 for r in compiled if r["ambiguity"])}


@app.post("/api/sources/guidelines")
async def upload_guidelines(name: str = Form(...), version: str = Form("v1"), text: str = Form(""),
                            file: UploadFile | None = File(None), a: Actor = Depends(actor)):
    need(a, "admin", "brand_owner")
    filename = None
    if file is not None and file.filename:
        filename = file.filename
        text = extract.extract_text(file.filename, await file.read())
    if not text.strip():
        raise HTTPException(400, "Provide guideline text or a PDF/DOCX/TXT file")
    return _store_guideline(name, version, filename, text, a)


@app.get("/api/rules")
def list_rules(status: str | None = None):
    q = "SELECT r.*, s.name AS source_name, s.version AS source_version FROM rules r LEFT JOIN sources s ON s.id=r.source_id"
    args = ()
    if status:
        q += " WHERE r.status=?"
        args = (status,)
    return db.rows(conn.execute(q + " ORDER BY r.id", args))


class RuleUpdate(BaseModel):
    status: str | None = None
    params: dict | None = None
    severity: str | None = None
    type: str | None = None


@app.patch("/api/rules/{rid}")
def update_rule(rid: int, body: RuleUpdate, a: Actor = Depends(actor)):
    need(a, "admin", "brand_owner")
    r = db.row(conn.execute("SELECT * FROM rules WHERE id=?", (rid,)).fetchone())
    if not r:
        raise HTTPException(404)
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
        amb = [x for x in r["ambiguity"] if x["kind"] in ("vague", "conflict")]
        data["ambiguity"] = amb
    db.update(conn, "rules", rid, data)
    db.audit(conn, a.name, a.role, "rule.update", "rule", rid, {"before": {k: r.get(k) for k in data}, "after": data})
    return db.row(conn.execute("SELECT * FROM rules WHERE id=?", (rid,)).fetchone())


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
    approved_phrasing: str | None = None
    source_ref: str | None = None
    owner: str | None = None
    scope: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


@app.get("/api/facts")
def list_facts():
    fs = all_facts()
    today = preflight._today()
    for f in fs:
        f["is_valid"] = preflight._valid(f, today)
    return fs


@app.post("/api/facts")
def add_fact(body: FactIn, a: Actor = Depends(actor)):
    need(a, "admin", "brand_owner")
    if body.comparator not in ("max", "exact", "text"):
        raise HTTPException(400, "comparator must be max | exact | text")
    fid = db.insert(conn, "facts", {**body.model_dump(), "created_at": db.now()})
    db.audit(conn, a.name, a.role, "fact.add", "fact", fid, body.model_dump())
    return db.row(conn.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone())


@app.delete("/api/facts/{fid}")
def delete_fact(fid: int, a: Actor = Depends(actor)):
    need(a, "admin", "brand_owner")
    conn.execute("UPDATE findings SET fact_id=NULL WHERE fact_id=?", (fid,))
    conn.execute("DELETE FROM facts WHERE id=?", (fid,))
    conn.commit()
    db.audit(conn, a.name, a.role, "fact.delete", "fact", fid)
    return {"ok": True}


# ------------------------------------------------------------------ submissions / preflight

def _run_preflight(sid: int, text: str, kind: str, img=None, meta=None, alt_text=None) -> list[dict]:
    findings = preflight.run(text, active_rules(), all_facts(), img=img, meta=meta, alt_text=alt_text)
    for f in findings:
        db.insert(conn, "findings", {"submission_id": sid, **f})
    return findings


@app.post("/api/submissions")
async def submit(title: str = Form(...), channel: str = Form("web"), text: str = Form(""), alt_text: str = Form(""),
                 file: UploadFile | None = File(None), a: Actor = Depends(actor)):
    need(a, "creator", "admin", "brand_owner")
    kind, filename, img, meta = "text", None, None, None
    if file is not None and file.filename:
        data = await file.read()
        filename, kind = file.filename, extract.kind_for(file.filename)
        if kind == "image":
            img = extract.load_image(data)
            meta = preflight.image_meta(img)
            text = alt_text or text
        else:
            text = extract.extract_text(file.filename, data)
    if not text.strip() and kind != "image":
        raise HTTPException(400, "Nothing to check")
    sid = db.insert(conn, "submissions", {"title": title, "channel": channel, "author": a.name, "kind": kind,
                                          "filename": filename, "text": text, "alt_text": alt_text or None,
                                          "image_meta": meta, "created_at": db.now()})
    if img is not None:
        os.makedirs(UPLOADS, exist_ok=True)
        img.save(os.path.join(UPLOADS, f"sub-{sid}.png"))
    findings = _run_preflight(sid, text, kind, img, meta, alt_text)
    db.audit(conn, a.name, a.role, "submission.preflight", "submission", sid,
             {"findings": len(findings), "by_status": dict(Counter(f["status"] for f in findings)), "ai": llm.status()["mode"]})
    return get_submission(sid)


UPLOADS = os.path.join(os.path.dirname(__file__), "..", "uploads")


@app.get("/api/submissions")
def list_submissions():
    subs = db.rows(conn.execute("SELECT id, title, channel, author, kind, revision, parent_id, status, created_at FROM submissions ORDER BY id DESC"))
    for s in subs:
        c = conn.execute("SELECT COUNT(*) n, SUM(severity='high' AND decision='pending') hp, SUM(decision='pending') p "
                         "FROM findings WHERE submission_id=? AND status!='supported'", (s["id"],)).fetchone()
        s.update({"findings": c["n"], "high_pending": c["hp"] or 0, "pending": c["p"] or 0})
    return subs


@app.get("/api/submissions/{sid}")
def get_submission(sid: int):
    s = db.row(conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone())
    if not s:
        raise HTTPException(404)
    s["findings"] = db.rows(conn.execute(
        "SELECT f.*, r.text AS rule_text, r.type AS rule_type, fa.label AS fact_label, fa.value AS fact_value "
        "FROM findings f LEFT JOIN rules r ON r.id=f.rule_id LEFT JOIN facts fa ON fa.id=f.fact_id "
        "WHERE f.submission_id=? ORDER BY f.id", (sid,)))
    s["has_image"] = os.path.exists(os.path.join(UPLOADS, f"sub-{sid}.png"))
    chain, cur = [], s
    while cur and cur.get("parent_id"):
        cur = db.row(conn.execute("SELECT id, revision, status, created_at FROM submissions WHERE id=?", (cur["parent_id"],)).fetchone())
        if cur:
            chain.append(cur)
            cur = db.row(conn.execute("SELECT * FROM submissions WHERE id=?", (cur["id"],)).fetchone())
    child = db.row(conn.execute("SELECT id, revision FROM submissions WHERE parent_id=?", (sid,)).fetchone())
    s["history"] = chain
    s["next_revision"] = child
    s["audit"] = db.rows(conn.execute("SELECT * FROM audit WHERE (entity='submission' AND entity_id=?) OR "
                                      "(entity='finding' AND entity_id IN (SELECT id FROM findings WHERE submission_id=?)) ORDER BY id",
                                      (sid, sid)))
    return s


@app.get("/api/submissions/{sid}/image")
def submission_image(sid: int):
    from fastapi.responses import FileResponse
    p = os.path.join(UPLOADS, f"sub-{sid}.png")
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


class Decision(BaseModel):
    decision: str  # accepted | edited | overridden | pending
    text: str | None = None
    reason: str | None = None


@app.post("/api/findings/{fid}/decision")
def decide(fid: int, body: Decision, a: Actor = Depends(actor)):
    f = db.row(conn.execute("SELECT * FROM findings WHERE id=?", (fid,)).fetchone())
    if not f:
        raise HTTPException(404)
    s = db.row(conn.execute("SELECT status FROM submissions WHERE id=?", (f["submission_id"],)).fetchone())
    if s["status"] not in ("in_review", "changes_requested"):
        raise HTTPException(409, f"Submission is {s['status']}; decisions are locked.")
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
    db.audit(conn, a.name, a.role, f"finding.{body.decision}", "finding", fid,
             {"excerpt": f["excerpt"], "suggestion": f["suggestion"], "text": body.text, "reason": body.reason})
    return db.row(conn.execute("SELECT * FROM findings WHERE id=?", (fid,)).fetchone())


@app.post("/api/submissions/{sid}/revise")
def revise(sid: int, a: Actor = Depends(actor)):
    """Apply accepted/edited fixes, create a new revision and re-run the preflight."""
    need(a, "creator", "reviewer", "brand_owner")
    s = get_submission(sid)
    if s["status"] not in ("in_review", "changes_requested"):
        raise HTTPException(409, f"Submission is {s['status']}")
    if s["kind"] == "image":
        raise HTTPException(400, "Image revisions require a new upload.")
    new_text = preflight.apply_fixes(s["text"], s["findings"])
    nid = db.insert(conn, "submissions", {"title": s["title"], "channel": s["channel"], "author": s["author"],
                                          "kind": "text", "filename": s["filename"], "text": new_text,
                                          "revision": s["revision"] + 1, "parent_id": sid, "created_at": db.now()})
    # carry overrides forward so reviewers are not asked twice for the same justified exception
    overrides = {(f["rule_id"], f["fact_id"], f["excerpt"]): f for f in s["findings"] if f["decision"] == "overridden"}
    findings = _run_preflight(nid, new_text, "text")
    for nf in db.rows(conn.execute("SELECT * FROM findings WHERE submission_id=?", (nid,))):
        o = overrides.get((nf["rule_id"], nf["fact_id"], nf["excerpt"]))
        if o:
            db.update(conn, "findings", nf["id"], {"decision": "overridden", "decision_reason": o["decision_reason"] + " (carried from rev " + str(s["revision"]) + ")",
                                                   "decided_by": o["decided_by"]})
    db.update(conn, "submissions", sid, {"status": "superseded"})
    db.audit(conn, a.name, a.role, "submission.revise", "submission", sid, {"new_revision": nid})
    db.audit(conn, a.name, a.role, "submission.preflight", "submission", nid, {"findings": len(findings), "revision_of": sid})
    return get_submission(nid)


class StatusIn(BaseModel):
    status: str  # approved | rejected | changes_requested
    reason: str | None = None


@app.post("/api/submissions/{sid}/status")
def set_status(sid: int, body: StatusIn, a: Actor = Depends(actor)):
    need(a, "reviewer", "brand_owner")
    s = get_submission(sid)
    if s["status"] not in ("in_review", "changes_requested"):
        raise HTTPException(409, f"Submission is {s['status']}")
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
    db.audit(conn, a.name, a.role, f"submission.{body.status}", "submission", sid, {"reason": body.reason})
    return get_submission(sid)


# ------------------------------------------------------------------ governance

@app.get("/api/audit")
def audit_log(limit: int = 200):
    return db.rows(conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)))


@app.get("/api/insights")
def insights():
    fs = db.rows(conn.execute(
        "SELECT f.*, r.text AS rule_text, r.type AS rule_type FROM findings f LEFT JOIN rules r ON r.id=f.rule_id "
        "JOIN submissions s ON s.id=f.submission_id WHERE f.status!='supported'"))
    by_cat = Counter(f["category"] for f in fs)
    by_status = Counter(f["status"] for f in fs)
    per_rule: dict[int, dict] = {}
    for f in fs:
        if f["rule_id"] is None:
            continue
        d = per_rule.setdefault(f["rule_id"], {"rule_id": f["rule_id"], "rule_text": f["rule_text"], "hits": 0, "overrides": 0, "decided": 0})
        d["hits"] += 1
        if f["decision"] in ("accepted", "edited", "overridden"):
            d["decided"] += 1
        if f["decision"] == "overridden":
            d["overrides"] += 1
    for d in per_rule.values():
        d["override_rate"] = round(d["overrides"] / d["decided"], 2) if d["decided"] else 0
    repeated = sorted(per_rule.values(), key=lambda d: -d["hits"])[:6]
    unclear = [d for d in per_rule.values() if d["decided"] >= 2 and d["override_rate"] >= 0.5]
    pending_rules = db.rows(conn.execute("SELECT id, type, text, ambiguity FROM rules WHERE status='proposed'"))
    unverified = Counter(f["excerpt"] for f in fs if f["status"] == "unverified").most_common(6)
    subs = conn.execute("SELECT status, COUNT(*) n FROM submissions GROUP BY status").fetchall()
    decided = [f for f in fs if f["decision"] in ("accepted", "edited", "overridden")]
    return {
        "totals": {"findings": len(fs), "submissions": {r["status"]: r["n"] for r in subs},
                   "override_rate": round(sum(f["decision"] == "overridden" for f in decided) / len(decided), 2) if decided else 0,
                   "rules_active": conn.execute("SELECT COUNT(*) FROM rules WHERE status='active'").fetchone()[0],
                   "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]},
        "by_category": dict(by_cat), "by_status": dict(by_status),
        "repeated_issues": repeated, "unclear_rules": unclear,
        "rules_awaiting_validation": pending_rules,
        "missing_evidence": [{"excerpt": e, "count": c} for e, c in unverified],
        "ai": llm.status(),
    }


@app.on_event("startup")
def _autoseed():
    if os.environ.get("BRANDPROOF_AUTOSEED", "1") == "1" and conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0:
        import sys
        from . import seed
        seed.seed(sys.modules[__name__])
