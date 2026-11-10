"""Seed two fictional brand workspaces and demo accounts. All data is illustrative, not measured.

Workspaces
  Lumora (Aura Earbuds)   full demo: guidelines, evidence ledger, text / banner / scanned-flyer submissions
  Verdant Oat Co.         second brand, own rules, facts and audit log (shows isolation)

Accounts (password for all: demo-pass-2026)
  asha@lumora.demo    Admin, Lumora
  ravi@lumora.demo    Brand owner, Lumora · Admin + brand owner, Verdant
  meera@agency.demo   Creator in both (an agency working on two brands)
  kabir@lumora.demo   Reviewer, Lumora

Run:  python -m app.seed --reset
"""
import os
import sys
from datetime import date, timedelta

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SAMPLES = os.path.join(ROOT, "samples")
DEMO_PASSWORD = "demo-pass-2026"


def _d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_banner(path: str) -> None:
    """Off-palette green, under 1080px, and claims baked into the pixels (needs OCR to see)."""
    img = Image.new("RGB", (960, 960), "#2ECC71")
    d = ImageDraw.Draw(img)
    d.rectangle([60, 600, 900, 880], fill="#0B3D91")
    d.text((80, 90), "Aura Earbuds", font=_font(84), fill="#0B1F3A")
    d.text((80, 230), "Lasts all weekend.", font=_font(64), fill="#0B1F3A")
    d.text((80, 330), "Waterproof for every swim.", font=_font(52), fill="#0B1F3A")
    d.text((110, 650), "Festive sale: 40% off", font=_font(56), fill="#F4F1EA")
    d.text((110, 750), "Shop now at lumora.example", font=_font(40), fill="#F4F1EA")
    img.save(path)


def make_scanned_flyer(path: str) -> None:
    """A print flyer saved as an image-only PDF, like a scan: no text layer."""
    import pymupdf
    img = Image.new("RGB", (1240, 1754), "#FBFAF6")
    d = ImageDraw.Draw(img)
    d.text((110, 120), "Lumora", font=_font(72), fill="#0B3D91")
    lines = ["Meet Aura Earbuds.", "Take them swimming without a second thought.",
             "They silence the world completely.", "Every pair has a lifetime warranty.",
             "Enjoy up to 24 hours of battery life.", "Visit your nearest Lumora store."]
    y = 330
    for ln in lines:
        d.text((110, y), ln, font=_font(40), fill="#16181D")
        y += 110
    import io
    buf = io.BytesIO()
    img.convert("L").save(buf, "JPEG", quality=80)  # greyscale JPEG keeps the sample small, like a real scan
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


VERDANT_GUIDELINES = """# Verdant Oat Co. Brand Guidelines v1
(Fictional brand for demonstration only.)
Our tone is calm, honest and kind to the planet.
Avoid hype words such as "superfood", "miracle" and "detox".
Use "Verdant Oat Milk" instead of "Verdant milk" or "oat juice".
All nutrition and sustainability claims must be backed by an approved fact sheet.
Sentences must not exceed 22 words.
"""


def seed(main) -> None:
    from . import db
    conn = main.conn
    for t in ("findings", "submissions", "facts", "fact_vectors", "rules", "sources", "audit"):
        conn.execute(f"DELETE FROM {t}")  # legacy single-workspace rows (pre Round 3) belong to no account
    conn.commit()

    users = {}
    for key, name, email in [("asha", "Asha Iyer", "asha@lumora.demo"), ("ravi", "Ravi Menon", "ravi@lumora.demo"),
                             ("meera", "Meera Shah", "meera@agency.demo"), ("kabir", "Kabir Rao", "kabir@lumora.demo")]:
        users[key] = main.create_user(name, email, DEMO_PASSWORD, is_demo=True)

    lum = main.create_workspace("Lumora", "Lumora · Aura Earbuds", "#0B3D91", users["asha"], "Asha Iyer")
    for k, roles in (("ravi", ["brand_owner"]), ("meera", ["creator"]), ("kabir", ["reviewer"])):
        db.insert(conn, "memberships", {"workspace_id": lum, "user_id": users[k], "roles": roles, "created_at": db.now()})
    conn.execute("UPDATE memberships SET roles=? WHERE workspace_id=? AND user_id=?", ('["admin"]', lum, users["asha"]))
    ver = main.create_workspace("Verdant Oat Co.", "Verdant Oat Milk", "#3E7B4F", users["ravi"], "Ravi Menon")
    conn.execute("UPDATE memberships SET roles=? WHERE workspace_id=? AND user_id=?", ('["brand_owner","admin"]', ver, users["ravi"]))
    db.insert(conn, "memberships", {"workspace_id": ver, "user_id": users["meera"], "roles": ["creator"], "created_at": db.now()})
    conn.commit()

    A = lambda k, wid, roles: main.Actor(user_id=users[k], name={"asha": "Asha Iyer", "ravi": "Ravi Menon", "meera": "Meera Shah",  # noqa: E731
                                                                  "kabir": "Kabir Rao"}[k], roles=roles, workspace_id=wid)
    admin, owner = A("asha", lum, ["admin"]), A("ravi", lum, ["brand_owner"])
    creator, reviewer = A("meera", lum, ["creator"]), A("kabir", lum, ["reviewer"])

    # ---------------- Lumora
    with open(os.path.join(SAMPLES, "lumora_brand_guidelines_v2.md"), encoding="utf-8") as fh:
        main._store_guideline("Lumora Brand Guidelines", "v2", "lumora_brand_guidelines_v2.md", fh.read(), owner)
    for r in db.rows(conn.execute("SELECT * FROM rules WHERE status='proposed' AND workspace_id=?", (lum,))):
        if not r["ambiguity"]:
            main.update_rule(r["id"], main.RuleUpdate(status="active"), admin)

    spec = db.insert(conn, "sources", {"workspace_id": lum, "kind": "fact_sheet", "name": "Aura Earbuds Product Spec", "version": "v3",
                                       "filename": "aura_spec_v3.pdf", "text": "(fictional spec sheet)", "owner": "Product team",
                                       "uploaded_at": db.now()})
    facts = [
        dict(key="battery", label="Battery life", value="up to 24 hours", numeric=24, unit="hours", comparator="max",
             aliases=["battery", "playtime", "listening time", "battery life"],
             examples=["how long they last on one charge", "keeps going between charges"],
             approved_phrasing="up to 24 hours of battery life (with case)",
             source_ref="Aura Earbuds Product Spec v3, p.2", owner="Product team", scope="Aura Earbuds incl. case, all markets",
             valid_from=_d(-120), valid_to=_d(400)),
        dict(key="anc", label="Noise cancellation", value="up to 35 dB", numeric=35, unit="dB", comparator="max",
             aliases=["noise cancellation", "anc", "noise cancelling", "noise"],
             examples=["blocks outside noise", "quiet on a busy commute"],
             approved_phrasing="active noise cancellation up to 35 dB",
             source_ref="Aura Earbuds Product Spec v3, p.3", owner="Product team", scope="Aura Earbuds",
             valid_from=_d(-120), valid_to=_d(400)),
        dict(key="water", label="Water resistance", value="IPX4 (sweat and splash resistant)", numeric=None, unit=None,
             comparator="text", aliases=["water", "sweat", "splash"], disallowed=["waterproof", "water-proof", "swim-proof", "submersible"],
             examples=["fine in the rain", "handles a sweaty workout"], approved_phrasing="sweat and splash resistant (IPX4)",
             source_ref="Aura Earbuds Product Spec v3, p.3", owner="Product team", scope="Aura Earbuds",
             valid_from=_d(-120), valid_to=_d(400)),
        dict(key="price_in", label="Launch price (India)", value="₹4,999", numeric=4999, unit="INR", comparator="exact",
             aliases=["price", "priced", "cost", "for just", "for only", "at just"],
             source_ref="Pricing Memo 2026-Q3", owner="Revenue team", scope="India, launch window",
             valid_from=_d(-90), valid_to=_d(-7)),
        dict(key="warranty", label="Warranty", value="1 year", numeric=1, unit="years", comparator="exact",
             aliases=["warranty", "guarantee"], source_ref="Warranty Policy 2025, s.2", owner="Legal",
             scope="All products", valid_from=_d(-400), valid_to=_d(200)),
        dict(key="warranty", label="Warranty", value="2 years", numeric=2, unit="years", comparator="exact",
             aliases=["warranty", "guarantee"], source_ref="Aura Earbuds Product Spec v3, p.6", owner="Product team",
             scope="Aura Earbuds", valid_from=_d(-120), valid_to=_d(400)),
    ]
    for f in facts:
        main.add_fact(main.FactIn(**f), owner)
    conn.execute("UPDATE facts SET source_id=? WHERE workspace_id=?", (spec, lum))
    conn.commit()

    # previously reviewed piece, so insights and the audit trail are not empty
    sid = main._create_submission(creator, "Holiday email — comfort fit", "email", "text", None,
                                  "Lumora Aura Earbuds deliver up to 24 hours of battery life. "
                                  "Our game-changing comfort fit stays put on long commutes.", "", None, None, [], None)
    for f in main._submission(sid, lum)["findings"]:
        if f["decision"] == "pending":
            main.decide(f["id"], main.Decision(decision="overridden", reason="Approved campaign tagline; legal sign-off LGL-112."), reviewer)
    main.set_status(sid, main.StatusIn(status="approved"), reviewer)

    with open(os.path.join(SAMPLES, "launch_post.txt"), encoding="utf-8") as fh:
        main._create_submission(creator, "Aura Earbuds launch post", "instagram", "text", None, fh.read(), "", None, None, [], None)

    weekend = os.path.join(SAMPLES, "weekend_campaign.txt")
    if os.path.exists(weekend):
        with open(weekend, encoding="utf-8") as fh:
            main._create_submission(creator, "Weekend campaign (paraphrased claims)", "web", "text", None, fh.read(), "", None, None, [], None)

    banner = os.path.join(SAMPLES, "festive_banner.png")
    if not os.path.exists(banner) or os.path.getsize(banner) < 15000:
        make_banner(banner)
    with open(banner, "rb") as fh:
        kind, text, img, meta, pages, o = main._ingest("festive_banner.png", fh.read(), "", "")
    main._create_submission(creator, "Festive sale banner", "instagram", kind, "festive_banner.png", text, "", img, meta, pages, o)

    flyer = os.path.join(SAMPLES, "scanned_flyer.pdf")
    if not os.path.exists(flyer):
        make_scanned_flyer(flyer)
    with open(flyer, "rb") as fh:
        kind, text, img, meta, pages, o = main._ingest("scanned_flyer.pdf", fh.read(), "", "")
    main._create_submission(creator, "Store flyer (scanned PDF)", "print", kind, "scanned_flyer.pdf", text, "", img, meta, pages, o)

    # ---------------- Verdant (second brand: separate rules, facts, audit)
    vowner, vcreator = A("ravi", ver, ["brand_owner", "admin"]), A("meera", ver, ["creator"])
    main._store_guideline("Verdant Brand Guidelines", "v1", None, VERDANT_GUIDELINES, vowner)
    for r in db.rows(conn.execute("SELECT * FROM rules WHERE status='proposed' AND workspace_id=?", (ver,))):
        if not r["ambiguity"]:
            main.update_rule(r["id"], main.RuleUpdate(status="active"), vowner)
    for f in [
        dict(key="protein", label="Protein per 250 ml", value="3 g", numeric=3, unit="g", comparator="exact",
             aliases=["protein"], source_ref="Verdant Nutrition Panel 2026", owner="Nutrition", valid_from=_d(-60), valid_to=_d(300)),
        dict(key="carbon", label="Carbon footprint vs dairy", value="up to 70% lower", numeric=70, unit="%", comparator="max",
             aliases=["carbon", "emissions", "footprint", "lower carbon"], examples=["better for the planet than dairy"],
             approved_phrasing="up to 70% lower carbon footprint than dairy milk",
             source_ref="LCA Report 2025 (third-party)", owner="Sustainability", valid_from=_d(-200), valid_to=_d(300)),
    ]:
        main.add_fact(main.FactIn(**f), vowner)
    main._create_submission(vcreator, "Oat milk shelf talker", "print", "text", None,
                            "Verdant milk is the miracle superfood your mornings need. 5 g of protein per glass and 90% lower emissions than dairy.",
                            "", None, None, [], None)


def reset() -> None:
    from . import db
    if db.IS_PG:
        db.drop_all(db.connect())
    elif os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    from . import main as m
    if m.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(m)
        print(f"Seeded demo data. Demo password: {DEMO_PASSWORD}")
    else:
        print("Database already has data; use --reset to reseed.")
