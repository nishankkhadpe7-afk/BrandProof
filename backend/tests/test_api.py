import io
import os
import tempfile

os.environ["BRANDPROOF_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.setdefault("DATABASE_URL", "")  # never touch a real Postgres from .env; set TEST_PG to test it
if os.environ.get("TEST_PG"):
    os.environ["DATABASE_URL"] = os.environ["TEST_PG"]
os.environ["LLM_PROVIDER"] = ""
os.environ["BRANDPROOF_SYNC_CHECKS"] = "1"  # run checks inline so responses carry findings
os.environ["RATE_LIMIT"] = "0"  # deterministic tests; the .env loader won't override

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app import main, ocr  # noqa: E402
from app.seed import DEMO_PASSWORD, _font  # noqa: E402

with TestClient(main.app) as c:  # triggers autoseed
    pass
client = TestClient(main.app)
_tokens: dict[str, str] = {}


def login(email: str) -> str:
    if email not in _tokens:
        r = client.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
        assert r.status_code == 200, r.text
        _tokens[email] = r.json()["token"]
    return _tokens[email]


def H(who: str = "meera@agency.demo", ws: int | None = None) -> dict:
    h = {"Authorization": f"Bearer {login(who)}"}
    if ws:
        h["X-Workspace"] = str(ws)
    return h


ADMIN, OWNER, CREATOR, REVIEWER = "asha@lumora.demo", "ravi@lumora.demo", "meera@agency.demo", "kabir@lumora.demo"
LUM, VER = 1, 2


def sub(title: str, who=CREATOR, ws=LUM):
    return next(s for s in client.get("/api/submissions", headers=H(who, ws)).json() if s["title"] == title)


def full(title: str, who=CREATOR, ws=LUM):
    return client.get(f"/api/submissions/{sub(title, who, ws)['id']}", headers=H(who, ws)).json()


# ------------------------------------------------------------------ accounts & workspaces

def test_auth_required_and_bad_password():
    assert client.get("/api/rules").status_code == 401
    r = client.post("/api/auth/login", json={"email": ADMIN, "password": "wrong-password"})
    assert r.status_code == 401


def test_register_creates_private_workspace_and_isolation():
    r = client.post("/api/auth/register", json={"name": "New Person", "email": "New@Example.com", "password": "longenough1"})
    assert r.status_code == 200
    tok, ws = r.json()["token"], r.json()["workspaces"]
    assert len(ws) == 1 and set(ws[0]["roles"]) == {"creator", "reviewer", "brand_owner", "admin"}
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/submissions", headers=h).json() == []           # sees nothing from Lumora
    assert client.get("/api/facts", headers=h).json() == []
    lumora_sub = sub("Aura Earbuds launch post")["id"]
    assert client.get(f"/api/submissions/{lumora_sub}", headers=h).status_code == 404
    assert client.get("/api/rules", headers={**h, "X-Workspace": str(LUM)}).status_code == 403
    assert client.post("/api/auth/register", json={"name": "x", "email": "new@example.com", "password": "longenough1"}).status_code == 409
    assert client.post("/api/auth/register", json={"name": "x", "email": "short@example.com", "password": "short"}).status_code == 400


def test_agency_member_sees_two_brands_with_separate_audit():
    me = client.get("/api/auth/me", headers=H(CREATOR)).json()
    assert {w["name"] for w in me["workspaces"]} == {"Lumora", "Verdant Oat Co."}
    lum_titles = {s["title"] for s in client.get("/api/submissions", headers=H(CREATOR, LUM)).json()}
    ver_titles = {s["title"] for s in client.get("/api/submissions", headers=H(CREATOR, VER)).json()}
    assert "Oat milk shelf talker" in ver_titles and "Oat milk shelf talker" not in lum_titles
    ver_audit = client.get("/api/audit", headers=H(OWNER, VER)).json()
    assert ver_audit and all(a["workspace_id"] == VER for a in ver_audit)


def test_invite_then_register_joins_with_role():
    r = client.post("/api/workspace/members", headers=H(ADMIN, LUM), json={"email": "legal@lumora.demo", "roles": ["reviewer"]})
    assert r.json()["status"] == "invited"
    assert client.post("/api/workspace/members", headers=H(CREATOR, LUM), json={"email": "a@b.co", "roles": ["admin"]}).status_code == 403
    t = client.post("/api/auth/register", json={"name": "Legal", "email": "legal@lumora.demo", "password": "longenough1"}).json()
    lum = next(w for w in t["workspaces"] if w["id"] == LUM)
    assert lum["roles"] == ["reviewer"]


def test_last_admin_cannot_be_removed():
    asha = next(m for m in client.get("/api/workspace", headers=H(ADMIN, LUM)).json()["members"] if m["email"] == ADMIN)
    r = client.patch(f"/api/workspace/members/{asha['id']}", headers=H(ADMIN, LUM), json={"roles": ["reviewer"]})
    assert r.status_code == 400


# ------------------------------------------------------------------ Round 2 behaviour still holds

def test_seeded_findings_have_evidence():
    by = {f["excerpt"]: f for f in full("Aura Earbuds launch post")["findings"]}
    f = by["72-hour"]
    assert f["status"] == "contradicted" and f["suggestion"] == "up to 24-hour"
    assert "Product Spec v3" in f["source_ref"] and f["rule_id"]
    assert by["2-year"]["status"] == "conflicting"
    assert by["just ₹3,999"]["status"] == "expired"
    assert by["#1"]["status"] == "unverified"
    assert by["LUMORA"]["suggestion"] == "Lumora"
    assert by["up to 35 dB"]["status"] == "supported"


def test_ambiguity_gate_rbac_and_approval_gate():
    proposed = client.get("/api/rules?status=proposed", headers=H(ADMIN)).json()
    assert {"vague", "conflict", "untyped"} <= {a["kind"] for r in proposed for a in r["ambiguity"]}
    untyped = next(r for r in proposed if r["type"] == "unclassified")
    assert client.patch(f"/api/rules/{untyped['id']}", headers=H(ADMIN), json={"status": "active"}).status_code == 400
    assert client.patch(f"/api/rules/{untyped['id']}", headers=H(CREATOR), json={"status": "active"}).status_code == 403
    s = full("Aura Earbuds launch post")
    assert client.post(f"/api/submissions/{s['id']}/status", headers=H(REVIEWER), json={"status": "approved"}).status_code == 409
    f = next(x for x in s["findings"] if x["decision"] == "pending")
    assert client.post(f"/api/findings/{f['id']}/decision", headers=H(CREATOR), json={"decision": "overridden", "reason": "x"}).status_code == 403
    assert client.post(f"/api/findings/{f['id']}/decision", headers=H(REVIEWER), json={"decision": "overridden"}).status_code == 400


def test_revise_applies_fixes_and_reruns():
    s = client.post("/api/submissions", headers=H(CREATOR), data={"title": "rev test", "text": "Enjoy 72-hour battery life."}).json()
    sid = s["id"]
    f = next(x for x in s["findings"] if x["excerpt"] == "72-hour")
    client.post(f"/api/findings/{f['id']}/decision", headers=H(CREATOR), json={"decision": "accepted"})
    n = client.post(f"/api/submissions/{sid}/revise", headers=H(CREATOR)).json()
    assert "up to 24-hour" in n["text"] and n["revision"] == 2
    assert all(x["status"] != "contradicted" for x in n["findings"])


# ------------------------------------------------------------------ Round 3 · semantic evidence

def test_semantic_paraphrases_are_matched_to_facts():
    by = {f["excerpt"]: f for f in full("Weekend campaign (paraphrased claims)")["findings"]}
    w = by["last all weekend"]
    assert w["status"] == "contradicted" and w["engine"] == "semantic" and w["fact_label"] == "Battery life"
    assert "48 hours" in w["match"]["interpretation"] and w["match"]["retrieved"][0]["label"] == "Battery life"
    assert by["swimming"]["status"] == "contradicted" and by["swimming"]["fact_label"] == "Water resistance"
    assert by["silence the world"]["status"] == "contradicted"
    assert by["lifetime"]["status"] == "conflicting"  # warranty sources disagree


def test_semantic_supported_and_no_false_positive():
    r = client.post("/api/facts/probe", headers=H(OWNER), json={"text": "Charge once and listen all day."}).json()
    assert r["ranked"][0]["label"] == "Battery life"
    assert [f["status"] for f in r["findings"]] == ["supported"]
    r = client.post("/api/facts/probe", headers=H(OWNER), json={"text": "Powerful bass and rich, warm sound."}).json()
    assert r["findings"] == []


def test_semantic_does_not_double_report_deterministic_claims():
    s = full("Aura Earbuds launch post")
    assert not [f for f in s["findings"] if f["engine"] == "semantic" and f["fact_label"] == "Battery life"]


# ------------------------------------------------------------------ Round 3 · OCR

needs_ocr = pytest.mark.skipif(ocr.engine() != "tesseract", reason="tesseract not installed")


@needs_ocr
def test_banner_text_is_read_and_regions_marked():
    s = full("Festive sale banner")
    assert s["ocr_engine"] == "tesseract" and "weekend" in s["text"].lower()
    by = {f["excerpt"].lower(): f for f in s["findings"]}
    w = by["lasts all weekend"]
    assert w["status"] == "contradicted" and w["region"]["source"] == "ocr" and w["region"]["w"] > 50
    assert by["waterproof"]["region"]["source"] == "ocr"
    img = client.get(f"/api/submissions/{s['id']}/image?page=0", headers=H(CREATOR))
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"


@needs_ocr
def test_scanned_pdf_is_ocrd():
    s = full("Store flyer (scanned PDF)")
    assert s["pages"] == 1 and "swimming" in s["text"]
    assert any(f["region"] and f["region"]["page"] == 0 for f in s["findings"])


@needs_ocr
def test_uploaded_creative_and_revision_upload():
    img = Image.new("RGB", (1200, 1200), "#0B3D91")
    ImageDraw.Draw(img).text((80, 500), "Now with 72-hour battery", font=_font(70), fill="#F4F1EA")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = client.post("/api/submissions", headers=H(CREATOR), data={"title": "ocr upload", "alt_text": "Earbuds"},
                    files={"file": ("ad.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    s = r.json()
    sid = s["id"]
    f = next(x for x in s["findings"] if x["excerpt"] == "72-hour")
    assert f["status"] == "contradicted" and f["region"]
    img2 = Image.new("RGB", (1200, 1200), "#0B3D91")
    ImageDraw.Draw(img2).text((80, 500), "Up to 24 hours of battery", font=_font(70), fill="#F4F1EA")
    buf2 = io.BytesIO()
    img2.save(buf2, "PNG")
    n = client.post(f"/api/submissions/{sid}/revise-upload", headers=H(CREATOR),
                    files={"file": ("ad2.png", buf2.getvalue(), "image/png")}).json()
    assert n["revision"] == 2 and not [x for x in n["findings"] if x["status"] == "contradicted"]


def test_image_without_ocr_engine_says_so(monkeypatch):
    monkeypatch.setenv("OCR_DISABLED", "1")
    buf = io.BytesIO()
    Image.new("RGB", (1200, 1200), "#0B3D91").save(buf, "PNG")
    r = client.post("/api/submissions", headers=H(CREATOR), data={"title": "no ocr", "alt_text": "x"},
                    files={"file": ("a.png", buf.getvalue(), "image/png")})
    s = r.json()
    sid = s["id"]
    assert any("no OCR engine" in f["reason"] for f in s["findings"])


def test_ai_layer_mocked(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "provider", lambda: "openai")
    monkeypatch.setattr(llm, "complete_json", lambda system, user, timeout=30.0:
                        {"issues": [{"quote": "very cool", "reason": "too casual", "suggestion": "well designed"}]}
                        if "tone" in system.lower() else {"claims": []})
    r = client.post("/api/submissions", headers=H(CREATOR), data={"title": "ai", "text": "These are very cool earbuds."})
    s = r.json()
    sid = s["id"]
    assert any(f["engine"] == "ai" and f["excerpt"] == "very cool" for f in s["findings"])


# ------------------------------------------------------------------ jobs and rate limiting

def test_check_job_is_idempotent_and_retries(monkeypatch):
    from app import jobs
    from app.routes import submissions as rs
    sid = client.post("/api/submissions", headers=H(CREATOR), data={"title": "job", "text": "Enjoy 72-hour battery life."}).json()["id"]
    n = len(client.get(f"/api/submissions/{sid}", headers=H(CREATOR)).json()["findings"])
    main.conn.execute("UPDATE submissions SET check_status='queued' WHERE id=?", (sid,))
    rs.check_submission(sid)  # duplicate delivery must not duplicate findings
    s = client.get(f"/api/submissions/{sid}", headers=H(CREATOR)).json()
    assert len(s["findings"]) == n and s["check_status"] == "done"
    calls = {"n": 0}

    def flaky(x):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        rs.check_submission(x)
    monkeypatch.setattr(jobs, "_fn", flaky)
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    main.conn.execute("UPDATE submissions SET check_status='queued', attempts=0 WHERE id=?", (sid,))
    jobs.submit(sid, background=False)
    s = client.get(f"/api/submissions/{sid}", headers=H(CREATOR)).json()
    assert calls["n"] == 2 and s["check_status"] == "done" and s["attempts"] == 1


def test_background_upload_is_queued_then_done(monkeypatch):
    from app import jobs
    monkeypatch.setenv("BRANDPROOF_SYNC_CHECKS", "0")
    monkeypatch.setattr(jobs, "_started", False)
    jobs.start()
    r = client.post("/api/submissions", headers=H(CREATOR), data={"title": "bg", "text": "Grab it for just ₹3,999."}).json()
    assert r["check_status"] in ("queued", "running", "done")
    jobs.wait_idle()
    s = client.get(f"/api/submissions/{r['id']}", headers=H(CREATOR)).json()
    assert s["check_status"] == "done" and any(f["status"] == "expired" for f in s["findings"])
    assert client.post(f"/api/findings/{s['findings'][0]['id']}/decision", headers=H(CREATOR), json={"decision": "pending"}).status_code == 200


def test_rate_limit_returns_429(monkeypatch):
    from app import ratelimit
    monkeypatch.setenv("RATE_LIMIT", "1")
    monkeypatch.setenv("RATE_LIMIT_SCALE", "0.3")  # auth limit 3/min
    ratelimit._buckets.clear()
    codes = [client.post("/api/auth/login", json={"email": "x@y.zz", "password": "nope-nope"},
                         headers={"X-Forwarded-For": "203.0.113.9"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[-1] == 429
    r = client.post("/api/auth/login", json={"email": "x@y.zz", "password": "nope"}, headers={"X-Forwarded-For": "203.0.113.9"})
    assert int(r.headers["Retry-After"]) >= 1
    assert client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200  # health is exempt
    ratelimit._buckets.clear()


def test_upload_size_limit(monkeypatch):
    from app.routes import submissions as rs
    monkeypatch.setattr(rs, "MAX_UPLOAD", 10)
    r = client.post("/api/submissions", headers=H(CREATOR), data={"title": "big"}, files={"file": ("a.txt", b"x" * 50, "text/plain")})
    assert r.status_code == 413


# ------------------------------------------------------------------ password reset, invite emails, Figma

def test_password_reset_flow(monkeypatch):
    from app import mailer
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, title, body, cta, link: sent.append((to, link)) or True)
    client.post("/api/auth/register", json={"name": "Reset Me", "email": "reset@example.com", "password": "first-pass-1"})
    r = client.post("/api/auth/forgot", json={"email": "RESET@example.com"})
    assert r.status_code == 200 and sent and sent[0][0] == "reset@example.com"
    assert client.post("/api/auth/forgot", json={"email": "nobody@example.com"}).json() == r.json()  # no account enumeration
    client.post("/api/auth/forgot", json={"email": ADMIN})
    assert len(sent) == 1  # demo accounts can't be reset
    token = sent[0][1].split("token=")[1]
    assert client.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code == 400
    assert client.post("/api/auth/reset", json={"token": token, "password": "second-pass-2"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": token, "password": "third-pass-3"}).status_code == 400  # single use
    assert client.post("/api/auth/login", json={"email": "reset@example.com", "password": "second-pass-2"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "reset@example.com", "password": "first-pass-1"}).status_code == 401


def test_invite_sends_email(monkeypatch):
    from app import mailer
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, *a: sent.append((to, subject)) or True)
    r = client.post("/api/workspace/members", headers=H(ADMIN, LUM), json={"email": "newperson@lumora.demo", "roles": ["creator"]}).json()
    assert r["status"] == "invited" and r["email_sent"] and sent[0][0] == "newperson@lumora.demo" and "invited you" in sent[0][1]


def test_figma_check_maps_findings_to_layers():
    nodes = [{"id": "1:2", "name": "Headline", "text": "Aura Earbuds last all weekend."},
             {"id": "1:3", "name": "Body", "text": "Enjoy 72-hour battery life from LUMORA."}]
    r = client.post("/api/integrations/figma/check", headers=H(CREATOR), json={"nodes": nodes, "save": True, "title": "Figma test"}).json()
    by = {f["excerpt"]: f for f in r["findings"]}
    assert by["72-hour"]["node_id"] == "1:3" and nodes[1]["text"][by["72-hour"]["start"]:by["72-hour"]["end"]] == "72-hour"
    assert by["72-hour"]["fixable"] and by["last all weekend"]["node_id"] == "1:2" and r["blocking"] >= 2
    s = client.get(f"/api/submissions/{r['submission_id']}", headers=H(CREATOR)).json()
    assert s["channel"] == "figma" and s["findings"]
    assert client.post("/api/integrations/figma/check", headers=H(REVIEWER), json={"nodes": nodes}).status_code == 403


def test_gmail_api_mailer(monkeypatch):
    import base64 as b64
    from app import mailer
    for k in ("RESEND_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("MAIL_FROM", "BrandProof <me@gmail.com>")
    calls = []

    class R:
        def __init__(self, j): self.j = j
        def raise_for_status(self): pass
        def json(self): return self.j

    def fake_post(url, **kw):
        calls.append((url, kw))
        return R({"access_token": "at"}) if "oauth2" in url else R({"id": "1"})
    monkeypatch.setattr(mailer.httpx, "post", fake_post)
    assert mailer.provider() == "gmail-api"
    assert mailer.send("a@b.co", "Subj", "Title", "Body", "Go", "https://x/y")
    assert calls[0][1]["data"]["refresh_token"] == "refresh" and calls[1][1]["headers"]["Authorization"] == "Bearer at"
    raw = b64.urlsafe_b64decode(calls[1][1]["json"]["raw"]).decode()
    assert "To: a@b.co" in raw and "From: BrandProof <me@gmail.com>" in raw and "https://x/y" in raw


def test_more_units_are_checked():
    h = {"Authorization": f"Bearer {client.post('/api/auth/register', json={'name': 'U', 'email': 'units@test.dev', 'password': 'units-pass-1'}).json()['token']}"}
    client.post("/api/facts", headers=h, json={"key": "caffeine", "label": "Caffeine per cup", "value": "up to 95 mg", "numeric": 95,
                                               "unit": "mg", "comparator": "max", "aliases": ["caffeine"]})
    s = client.post("/api/submissions", headers=h, data={"title": "u", "text": "Only 200 mg caffeine per cup. Up to 90 mg caffeine."}).json()
    by = {f["excerpt"]: f["status"] for f in s["findings"]}
    assert by["Only 200 mg"] == "contradicted" and by["Up to 90 mg"] == "supported"


def test_approved_wording_is_not_flagged():
    r = client.post("/api/facts/probe", headers=H(OWNER), json={
        "text": "Lumora Aura Earbuds give you up to 24 hours of battery life with the case, and they're sweat and splash resistant (IPX4) for the gym."}).json()
    assert [f for f in r["findings"] if f["status"] != "supported"] == []


def test_bad_uploads_are_rejected_up_front():
    for name, data, code in [("a.exe", b"MZ", 400), ("a.png", b"notapng", 400), ("a.pdf", b"%PDF-broken", 400), ("a.txt", b"", 400)]:
        r = client.post("/api/submissions", headers=H(CREATOR), data={"title": "x"}, files={"file": (name, data, "application/octet-stream")})
        assert r.status_code == code, (name, r.text)
    r = client.post("/api/submissions", headers=H(CREATOR), data={"text": "hello"})
    assert r.status_code == 422 and r.json()["detail"] == "Title is required."
    assert client.post("/api/submissions", headers=H(CREATOR), data={"title": "big", "text": "x" * 60000}).status_code == 413
