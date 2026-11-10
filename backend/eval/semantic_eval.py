"""Semantic evidence evaluation: alias-only (Round 2) vs alias + semantic retrieval (Round 3).

Each case is a marketing sentence about the fictional Aura Earbuds with a hand label:
  expected_key     which ledger fact it is about (blank = none)
  expected_flag    1 if a reviewer should be warned (contradicted / conflicting / expired), else 0

Run from backend/:
  python -m eval.semantic_eval                       # built-in 40 cases
  python -m eval.semantic_eval --csv my_cases.csv    # add your own (e.g. sentences sampled from a Kaggle
                                                     # product-description dataset, labelled by the team)

The built-in set is small and written by the team, so treat the numbers as a smoke test,
not a benchmark. The proposed 150-case benchmark is described in the README.
"""
import csv
import os
import sys
import tempfile

os.environ["BRANDPROOF_DB"] = os.path.join(tempfile.mkdtemp(), "eval.db")
os.environ.setdefault("LLM_PROVIDER", "")
os.environ["DATABASE_URL"] = ""  # always a throwaway SQLite DB

CASES = [
    # battery (max 24 h)
    ("They last all weekend on one charge.", "battery", 1),
    ("A full week of music between charges.", "battery", 1),
    ("You will never need to charge them again.", "battery", 1),
    ("Listen all day without reaching for a cable.", "battery", 0),
    ("Plays overnight on a single charge.", "battery", 0),
    ("Up to 24 hours of battery life with the case.", "battery", 0),
    ("72-hour battery life.", "battery", 1),
    ("Battery that goes for days on end.", "battery", 1),
    ("Juice that lasts the whole weekend.", "battery", 1),
    ("Keeps going from Friday to Sunday.", "battery", 1),
    # noise (max 35 dB)
    ("They silence the world completely.", "anc", 1),
    ("Blocks out every single sound around you.", "anc", 1),
    ("Up to 35 dB of noise cancellation.", "anc", 0),
    ("Total silence on the busiest train.", "anc", 1),
    ("Quieter commutes with active noise cancellation.", "anc", 0),
    ("50 dB noise cancellation.", "anc", 1),
    # water (IPX4 text fact)
    ("Take them swimming without a second thought.", "water", 1),
    ("Fully waterproof design.", "water", 1),
    ("Dive into the pool with them in.", "water", 1),
    ("Sweat and splash resistant for the gym.", "water", 0),
    ("Fine in a light drizzle.", "water", 0),
    ("Wear them in the shower.", "water", 1),
    ("Submersible to two metres.", "water", 1),
    # warranty (two sources disagree -> conflicting)
    ("Backed by a lifetime warranty.", "warranty", 1),
    ("Comes with a 2-year warranty.", "warranty", 1),
    ("Covered for life.", "warranty", 1),
    # price (expired)
    ("Yours for just ₹3,999.", "price_in", 1),
    ("Priced at ₹4,999.", "price_in", 1),
    # no fact: should stay quiet (no claim flag)
    ("Powerful bass and rich, warm sound.", "", 0),
    ("Designed in Bengaluru by music lovers.", "", 0),
    ("Pair once and switch between your phone and laptop.", "", 0),
    ("Soft ear tips in three sizes.", "", 0),
    ("A case that slips into any pocket.", "", 0),
    ("Calls stay clear in a busy café.", "", 0),
    ("Available in navy and paper white.", "", 0),
    ("Gift-ready packaging for the festive season.", "", 0),
    ("The last pair you will ever want.", "", 0),
    ("Charge your phone and earbuds together with the dual dock.", "", 0),
    ("Swim lessons are fun for kids.", "", 0),
    ("Our quietest design yet.", "anc", 0),
]

FLAG = {"contradicted", "conflicting", "expired"}


def load_csv(path):
    with open(path, encoding="utf-8") as fh:
        return [(r["text"], r.get("expected_key", "") or "", int(r.get("expected_flag", 0) or 0)) for r in csv.DictReader(fh)]


def main():
    from app import main as m, preflight, seed, semantic
    if m.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed.seed(m)
    rules, facts = m.active_rules(1), m.all_facts(1)
    by_id = {f["id"]: f for f in facts}

    def run(text, use_semantic):
        fs = preflight.check_claims(text, facts, rules)
        if use_semantic:
            fs += semantic.check_semantic(text, facts, rules, fs, m.conn)
        fs = [f for f in fs if f.get("fact_id")]
        flagged = any(f["status"] in FLAG for f in fs)
        key = by_id[fs[0]["fact_id"]]["key"] if fs else ""
        return flagged, key

    sets = [("built-in (team-written, 40)", list(CASES))]
    if "--csv" in sys.argv:
        sets.append((f"csv: {os.path.basename(sys.argv[sys.argv.index('--csv') + 1])}", load_csv(sys.argv[sys.argv.index("--csv") + 1])))
    show = "--misses" in sys.argv
    print(f"semantic model: {semantic.status()}\n")
    for label, cases in sets:
        print(f"=== {label}: {len(cases)} cases")
        for name, use in (("exact rules only", False), ("exact rules + semantic", True)):
            tp = fp = fn = tn = key_ok = key_n = 0
            misses = []
            for text, key, flag in cases:
                got, gkey = run(text, use)
                tp += got and flag
                fp += got and not flag
                fn += (not got) and flag
                tn += (not got) and not flag
                if key:
                    key_n += 1
                    key_ok += gkey == key
                if bool(got) != bool(flag):
                    misses.append(("missed" if flag else "false alarm", text))
            p = tp / (tp + fp) if tp + fp else 0
            r = tp / (tp + fn) if tp + fn else 0
            f1 = 2 * p * r / (p + r) if p + r else 0
            print(f"{name}\n  flag precision {p:.2f} · recall {r:.2f} · F1 {f1:.2f}  (tp {tp}, fp {fp}, fn {fn}, tn {tn})"
                  f"\n  fact retrieval accuracy {key_ok}/{key_n} = {key_ok / max(key_n, 1):.2f}")
            if show:
                for kind, t in misses:
                    print(f"    {kind}: {t}")
        print()

if __name__ == "__main__":
    main()
