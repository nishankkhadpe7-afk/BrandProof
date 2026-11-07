import io
import os
import tempfile

os.environ["BRANDPROOF_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["LLM_PROVIDER"] = ""  # keep tests deterministic; .env loader won't override

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import main  # noqa: E402

H = lambda role, user="tester": {"X-Role": role, "X-User": user}  # noqa: E731

with TestClient(main.app) as c:  # triggers autoseed
    pass
client = TestClient(main.app)


def _launch():
    return next(s for s in client.get("/api/submissions").json() if s["title"] == "Aura Earbuds launch post")


def test_seeded_findings_have_evidence():
    s = client.get(f"/api/submissions/{_launch()['id']}").json()
    by = {f["excerpt"]: f for f in s["findings"]}
    f = by["72-hour"]
    assert f["status"] == "contradicted" and f["suggestion"] == "up to 24-hour"
    assert "Product Spec v3" in f["source_ref"] and f["rule_id"]
    assert by["2-year"]["status"] == "conflicting"
    assert by["just ₹3,999"]["status"] == "expired"
    assert by["#1"]["status"] == "unverified"
    assert by["LUMORA"]["suggestion"] == "Lumora"
    assert by["up to 35 dB"]["status"] == "supported"


def test_ambiguous_rules_stay_proposed_and_cannot_activate_untyped():
    proposed = client.get("/api/rules?status=proposed").json()
    kinds = {a["kind"] for r in proposed for a in r["ambiguity"]}
    assert {"vague", "conflict", "untyped"} <= kinds
    untyped = next(r for r in proposed if r["type"] == "unclassified")
    assert client.patch(f"/api/rules/{untyped['id']}", json={"status": "active"}, headers=H("admin")).status_code == 400
    assert client.patch(f"/api/rules/{untyped['id']}", json={"status": "active"}, headers=H("creator")).status_code == 403


def test_override_needs_reason_and_reviewer():
    fid = next(f for f in client.get(f"/api/submissions/{_launch()['id']}").json()["findings"] if f["excerpt"] == "#1")["id"]
    assert client.post(f"/api/findings/{fid}/decision", json={"decision": "overridden"}, headers=H("reviewer")).status_code == 400
    assert client.post(f"/api/findings/{fid}/decision", json={"decision": "overridden", "reason": "x"}, headers=H("creator")).status_code == 403


def test_full_workflow_gate_revise_approve():
    sid = client.post("/api/submissions", data={"title": "t", "text": "Aura buds from LUMORA give 72-hour battery life."},
                      headers=H("creator")).json()["id"]
    assert client.post(f"/api/submissions/{sid}/status", json={"status": "approved"}, headers=H("reviewer")).status_code == 409
    for f in client.get(f"/api/submissions/{sid}").json()["findings"]:
        if f["decision"] == "pending":
            assert client.post(f"/api/findings/{f['id']}/decision", json={"decision": "accepted"}, headers=H("creator")).status_code == 200
    rev = client.post(f"/api/submissions/{sid}/revise", headers=H("creator")).json()
    assert rev["text"] == "Aura Earbuds from Lumora give up to 24-hour battery life."
    assert rev["revision"] == 2 and all(f["status"] == "supported" for f in rev["findings"])
    assert client.post(f"/api/submissions/{rev['id']}/status", json={"status": "approved"}, headers=H("reviewer")).json()["status"] == "approved"
    acts = [a["action"] for a in client.get("/api/audit").json()]
    assert "submission.approved" in acts and "finding.accepted" in acts


def test_disclaimer_insertion():
    sid = client.post("/api/submissions", data={"title": "p", "text": "Now at a new price of ₹4,999."}, headers=H("creator")).json()["id"]
    f = next(f for f in client.get(f"/api/submissions/{sid}").json()["findings"] if f["rule_type"] == "disclaimer_required")
    client.post(f"/api/findings/{f['id']}/decision", json={"decision": "accepted"}, headers=H("creator"))
    rev = client.post(f"/api/submissions/{sid}/revise", headers=H("creator")).json()
    assert rev["text"].endswith("Prices include GST; offer valid while stocks last.")


def test_image_checks():
    img = Image.new("RGB", (600, 600), "#2ECC71")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    s = client.post("/api/submissions", data={"title": "img"}, files={"file": ("b.png", buf.getvalue(), "image/png")},
                    headers=H("creator")).json()
    types = {f["rule_type"] for f in s["findings"]}
    assert {"visual_palette", "visual_min_resolution", "alt_text_required"} <= types
    pal = next(f for f in s["findings"] if f["rule_type"] == "visual_palette")
    assert pal["region"]["w"] > 0
    assert client.get(f"/api/submissions/{s['id']}/image").status_code == 200


def test_docx_guideline_upload_compiles():
    import docx
    d = docx.Document()
    d.add_paragraph('Never use "cheapest" in headlines.')
    d.add_paragraph("Sentences must not exceed 20 words.")
    buf = io.BytesIO()
    d.save(buf)
    r = client.post("/api/sources/guidelines", data={"name": "Social addendum"},
                    files={"file": ("g.docx", buf.getvalue())}, headers=H("brand_owner")).json()
    assert r["rules_proposed"] == 2


def test_insights():
    i = client.get("/api/insights").json()
    assert i["totals"]["rules_active"] > 10 and i["rules_awaiting_validation"]
    assert i["ai"]["mode"] == "deterministic+heuristic"


def test_llm_layer_is_pluggable(monkeypatch):
    from app import llm, preflight
    def fake(system, user, timeout=30):
        if "tone reviewer" in system:
            return {"issues": [{"quote": "you NEED these", "reason": "Pushy", "suggestion": "you may like these"}]}
        if "Extract verifiable" in system:
            return {"claims": [{"quote": "loved by audiophiles"}, {"quote": "not in text"}]}
        return None
    monkeypatch.setattr(llm, "complete_json", fake)
    rules = main.active_rules()
    fs = preflight.run("Honestly you NEED these, loved by audiophiles.", rules, main.all_facts())
    ai = [f for f in fs if f["engine"] == "ai"]
    assert {f["excerpt"] for f in ai} == {"you NEED these", "loved by audiophiles"}


def test_rule_without_required_params_cannot_activate_or_crash_preflight():
    rid = client.get("/api/rules").json()[0]["id"]
    r = client.patch(f"/api/rules/{rid}", headers=H("admin"),
                     json={"type": "preferred_term", "params": {}, "status": "active"})
    assert r.status_code == 400 and "use" in r.json()["detail"]
    # a malformed rule already active in the DB must not break submissions
    main.conn.execute("UPDATE rules SET type='preferred_term', params='{}', status='active' WHERE id=?", (rid,))
    main.conn.commit()
    s = client.post("/api/submissions", headers=H("creator"),
                    data={"title": "t", "channel": "instagram", "text": "Hello LUMORA world"})
    assert s.status_code == 200, s.text
