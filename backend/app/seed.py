"""Seed a fictional brand (Lumora / Aura Earbuds). All data is illustrative, not measured.

Run:  python -m app.seed --reset
"""
import os
import sys
from datetime import date, timedelta

from PIL import Image, ImageDraw

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SAMPLES = os.path.join(ROOT, "samples")


def _d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def make_sample_image(path: str) -> None:
    img = Image.new("RGB", (800, 800), "#2ECC71")          # off-palette green, below 1080px
    d = ImageDraw.Draw(img)
    d.rectangle([80, 520, 720, 700], fill="#0B3D91")       # brand navy panel
    d.rectangle([120, 120, 300, 300], fill="#F4F1EA")
    img.save(path)


def seed(main) -> None:
    from . import db
    conn = main.conn
    admin = main.Actor(name="Asha (Admin)", role="admin")
    owner = main.Actor(name="Ravi (Brand owner)", role="brand_owner")

    with open(os.path.join(SAMPLES, "lumora_brand_guidelines_v2.md"), encoding="utf-8") as fh:
        guidelines = fh.read()
    main._store_guideline("Lumora Brand Guidelines", "v2", "lumora_brand_guidelines_v2.md", guidelines, owner)

    # Admin validates every rule the compiler could type cleanly; ambiguous ones stay proposed.
    for r in db.rows(conn.execute("SELECT * FROM rules WHERE status='proposed'")):
        if not r["ambiguity"]:
            main.update_rule(r["id"], main.RuleUpdate(status="active"), admin)

    spec = db.insert(conn, "sources", {"kind": "fact_sheet", "name": "Aura Earbuds Product Spec", "version": "v3",
                                       "filename": "aura_spec_v3.pdf", "text": "(fictional spec sheet)", "owner": "Product team",
                                       "uploaded_at": db.now()})
    facts = [
        dict(key="battery", label="Battery life", value="up to 24 hours", numeric=24, unit="hours",
             comparator="max", aliases=["battery", "playtime", "listening time", "battery life"],
             source_ref="Aura Earbuds Product Spec v3, p.2", owner="Product team", scope="Aura Earbuds incl. case, all markets",
             valid_from=_d(-120), valid_to=_d(400)),
        dict(key="anc", label="Noise cancellation", value="up to 35 dB", numeric=35, unit="dB", comparator="max",
             aliases=["noise cancellation", "anc", "noise cancelling", "noise"],
             source_ref="Aura Earbuds Product Spec v3, p.3", owner="Product team", scope="Aura Earbuds",
             valid_from=_d(-120), valid_to=_d(400)),
        dict(key="water", label="Water resistance", value="IPX4 (sweat and splash resistant)", numeric=None, unit=None,
             comparator="text", aliases=["water", "sweat", "splash"], disallowed=["waterproof", "water-proof", "swim-proof"],
             approved_phrasing="sweat and splash resistant (IPX4)",
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
        f.setdefault("disallowed", [])
        main.add_fact(main.FactIn(**f), owner)
    conn.execute("UPDATE facts SET source_id=?", (spec,))
    conn.commit()

    # A previously reviewed piece, so governance insights and the audit trail are not empty.
    creator = main.Actor(name="Meera (Agency creator)", role="creator")
    reviewer = main.Actor(name="Kabir (Reviewer)", role="reviewer")
    sid = db.insert(conn, "submissions", {"title": "Holiday email — comfort fit", "channel": "email", "author": creator.name,
                                          "kind": "text", "text": "Lumora Aura Earbuds deliver up to 24 hours of battery life. "
                                          "Our game-changing comfort fit stays put on long commutes.", "created_at": db.now()})
    s = main.get_submission(sid)
    main._run_preflight(sid, s["text"], "text")
    db.audit(conn, creator.name, creator.role, "submission.preflight", "submission", sid, {"seed": True})
    for f in main.get_submission(sid)["findings"]:
        if f["decision"] == "pending":
            main.decide(f["id"], main.Decision(decision="overridden",
                                               reason="Approved campaign tagline; legal sign-off LGL-112."), reviewer)
    main.set_status(sid, main.StatusIn(status="approved"), reviewer)

    with open(os.path.join(SAMPLES, "launch_post.txt"), encoding="utf-8") as fh:
        post = fh.read()
    sid2 = db.insert(conn, "submissions", {"title": "Aura Earbuds launch post", "channel": "instagram",
                                           "author": creator.name, "kind": "text", "text": post, "created_at": db.now()})
    main._run_preflight(sid2, post, "text")
    db.audit(conn, creator.name, creator.role, "submission.preflight", "submission", sid2, {"seed": True})

    img_path = os.path.join(SAMPLES, "festive_banner.png")
    if not os.path.exists(img_path):
        make_sample_image(img_path)
    from . import extract, preflight
    img = Image.open(img_path).convert("RGB")
    meta = preflight.image_meta(img)
    sid3 = db.insert(conn, "submissions", {"title": "Festive sale banner", "channel": "instagram", "author": creator.name,
                                           "kind": "image", "filename": "festive_banner.png", "text": "",
                                           "image_meta": meta, "created_at": db.now()})
    os.makedirs(main.UPLOADS, exist_ok=True)
    img.save(os.path.join(main.UPLOADS, f"sub-{sid3}.png"))
    main._run_preflight(sid3, "", "image", img, meta, None)
    db.audit(conn, creator.name, creator.role, "submission.preflight", "submission", sid3, {"seed": True})


def reset() -> None:
    from . import db
    for p in (db.DB_PATH,):
        if os.path.exists(p):
            os.remove(p)


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    from . import main as m
    if m.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0:
        seed(m)
        print("Seeded demo data.")
    else:
        print("Database already has data; use --reset to reseed.")
