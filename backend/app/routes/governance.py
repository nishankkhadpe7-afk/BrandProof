"""Audit log and governance insights."""
import os
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, compiler, db, extract, llm, ocr, preflight, semantic
from ..core import *  # noqa: F401,F403  shared deps: conn, Actor, ctx, need, log, helpers
from ..core import _me, _owned, _session_for  # noqa: F401

router = APIRouter()


# ------------------------------------------------------------------ governance

@router.get("/api/audit")
def audit_log(limit: int = 300, a: Actor = Depends(ctx)):
    return db.rows(conn.execute("SELECT * FROM audit WHERE workspace_id=? ORDER BY id DESC LIMIT ?", (a.workspace_id, limit)))


@router.get("/api/insights")
def insights(a: Actor = Depends(ctx)):
    wid = a.workspace_id
    fs = db.rows(conn.execute(
        "SELECT f.*, r.text AS rule_text, r.type AS rule_type FROM findings f LEFT JOIN rules r ON r.id=f.rule_id "
        "JOIN submissions s ON s.id=f.submission_id WHERE f.status!='supported' AND s.workspace_id=?", (wid,)))
    by_cat = Counter(f["category"] for f in fs)
    by_status = Counter(f["status"] for f in fs)
    by_engine = Counter(f["engine"] for f in fs)
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
    pending_rules = db.rows(conn.execute("SELECT id, type, text, ambiguity FROM rules WHERE status='proposed' AND workspace_id=?", (wid,)))
    unverified = Counter(f["excerpt"] for f in fs if f["status"] == "unverified").most_common(6)
    subs = conn.execute("SELECT status, COUNT(*) n FROM submissions WHERE workspace_id=? GROUP BY status", (wid,)).fetchall()
    decided = [f for f in fs if f["decision"] in ("accepted", "edited", "overridden")]
    return {
        "totals": {"findings": len(fs), "submissions": {r["status"]: r["n"] for r in subs},
                   "override_rate": round(sum(f["decision"] == "overridden" for f in decided) / len(decided), 2) if decided else 0,
                   "rules_active": conn.execute("SELECT COUNT(*) FROM rules WHERE status='active' AND workspace_id=?", (wid,)).fetchone()[0],
                   "facts": conn.execute("SELECT COUNT(*) FROM facts WHERE workspace_id=?", (wid,)).fetchone()[0],
                   "sources": conn.execute("SELECT COUNT(*) FROM sources WHERE workspace_id=?", (wid,)).fetchone()[0]},
        "by_category": dict(by_cat), "by_status": dict(by_status), "by_engine": dict(by_engine),
        "repeated_issues": repeated, "unclear_rules": unclear,
        "rules_awaiting_validation": pending_rules,
        "missing_evidence": [{"excerpt": e, "count": c} for e, c in unverified],
        "ai": llm.status(),
    }
