"""Design-tool integrations. The Figma plugin sends the text layers of a selection; findings come
back mapped to each layer, so the plugin can highlight a layer and apply a fix in place."""
import base64
import io

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import extract, preflight
from ..core import *  # noqa: F401,F403
from .submissions import _create_submission, _submission

router = APIRouter()
MAX_NODES = 300
MAX_CHARS = 20000
SEP = "\n\n"


class Node(BaseModel):
    id: str
    name: str = ""
    text: str


class FigmaCheckIn(BaseModel):
    title: str = "Figma selection"
    file_name: str | None = None
    nodes: list[Node]
    save: bool = False                 # also create a submission in the review queue
    image_png_b64: str | None = None   # optional frame export, shown to reviewers


@router.post("/api/integrations/figma/check")
def figma_check(body: FigmaCheckIn, a: Actor = Depends(ctx)):
    need(a, "creator", "admin", "brand_owner")
    nodes = [n for n in body.nodes if n.text.strip()][:MAX_NODES]
    if not nodes:
        raise HTTPException(400, "Select at least one frame or text layer that contains text.")
    text, spans, pos = "", [], 0
    for n in nodes:
        if text:
            text += SEP
            pos += len(SEP)
        spans.append((pos, pos + len(n.text), n))
        text += n.text
        pos += len(n.text)
    if len(text) > MAX_CHARS:
        raise HTTPException(413, f"Selection has more than {MAX_CHARS} characters of text. Select fewer layers.")

    findings = preflight.run(text, active_rules(a.workspace_id), all_facts(a.workspace_id), conn=conn)
    out = []
    for f in findings:
        item = {k: f.get(k) for k in ("category", "status", "severity", "excerpt", "reason", "suggestion",
                                       "source_ref", "confidence", "engine", "match")}
        if f.get("start") is not None:
            hit = next(((s, e, n) for s, e, n in spans if s <= f["start"] <= e), None)
            if hit:
                s, e, n = hit
                item.update(node_id=n.id, node_name=n.name, start=f["start"] - s, end=min(f["end"], e) - s,
                            fixable=f.get("suggestion") is not None and f["end"] <= e and f["end"] > f["start"])
        out.append(item)

    sid = None
    if body.save:
        pages = []
        if body.image_png_b64:
            try:
                pages = [extract.load_image(base64.b64decode(body.image_png_b64))]
            except Exception:
                raise HTTPException(400, "The frame image could not be read.")
        sid = _create_submission(a, body.title, "figma", "text", body.file_name, text, "", None, None, pages, None)
    log(a, "integration.figma.check", "submission" if sid else "integration", sid,
        {"nodes": len(nodes), "findings": len(out), "saved": bool(sid)})
    blocking = sum(1 for f in out if f["severity"] in ("high", "medium") and f["status"] != "supported")
    return {"findings": out, "blocking": blocking, "submission_id": sid,
            "submission_url_path": f"/submissions/{sid}" if sid else None}
