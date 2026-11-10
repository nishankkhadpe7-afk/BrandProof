"""Round 3 · Semantic evidence retrieval.

Alias matching (Round 2) misses paraphrases such as "lasts all weekend". This module
embeds every approved fact and every claim-like sentence, retrieves the nearest fact
from a vector index, then tries to *interpret* the paraphrase into a comparable value
("all weekend" ~ 48 hours) so it can be checked against the fact's comparator.

Two embedders, same interface:
  * local-concept-v1  always on, offline, deterministic: word + char n-gram features plus
                      a small consumer-product concept lexicon (battery, noise, water...).
                      Facts also embed their `examples` (paraphrases a brand owner adds),
                      so retrieval improves from data, not code.
  * gemini-embedding  used in addition when LLM_PROVIDER=gemini and a key is set.
                      Fact vectors are cached in the fact_vectors table.

Every semantic finding carries a `match` trace: model, score, runner-up, top retrieved
facts and the interpretation used, so a reviewer can see *why* that fact was chosen.
Missing or ambiguous evidence stays `unverified`; a semantic match alone never
auto-approves anything.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import defaultdict

import httpx

from . import db, llm

log = logging.getLogger("brandproof.semantic")

LOCAL_MODEL = "local-concept-v1"
REMOTE_MODEL = "gemini-embedding-001"
T_LOCAL = float(os.environ.get("SEMANTIC_T_LOCAL", "0.20"))
T_REMOTE = float(os.environ.get("SEMANTIC_T_REMOTE", "0.78"))

# Concept lexicon: base forms; inflections (s/es/ed/ing) match automatically.
CONCEPTS: dict[str, list[str]] = {
    "battery": ["battery", "batteries", "charge", "recharge", "last", "lasting", "runtime", "run time", "playtime",
                "play time", "listening time", "juice", "power", "between charges", "keep going", "plug in",
                "die", "dies", "dead", "drain"],
    "noise": ["noise", "noisy", "quiet", "silence", "silent", "hush", "drown out", "block out", "tune out",
              "shut out", "cancel", "cancellation", "anc", "every sound", "outside world"],
    "immersion": ["waterproof", "water-proof", "swim", "swimming", "swim-proof", "pool", "underwater", "submerge",
                  "dive", "diving", "dunk", "shower", "ocean", "sea", "lake"],
    "splash": ["splash", "sweat", "sweaty", "rain", "drizzle", "workout", "gym", "resistant", "ipx4"],
    "price": ["price", "priced", "cost", "pay", "rupee", "₹", "rs", "affordable", "cheap", "deal", "bargain"],
    "warranty": ["warranty", "guarantee", "covered", "coverage", "replacement", "replace", "lifetime", "for life"],
}
CLAIM_CUES = re.compile(
    r"\b(last|lasts|lasting|deliver|delivers|give|gives|offer|offers|keep|keeps|block|blocks|silence|silences|"
    r"survive|survives|handle|handles|never|always|all|every|guarantee[sd]?|covered|forever|lifetime|take them|"
    r"go|goes|runs?|cancel|cancels|drowns?)\b", re.I)

NEGATED = re.compile(r"\b(?:not|no|never|didn'?t|don'?t|doesn'?t|isn'?t|wasn'?t|without|need(?:s|ed)? an?|looking for an?)\b[\w\s'-]{0,25}$", re.I)

STOP = set("the a an and or of to for in on with your you our we it its is are be this that these those from at by as "
           "so very just more most can will get enjoy meet".split())

INF = float("inf")
# paraphrase -> implied quantity, keyed by the fact's unit
VAGUE: dict[str, list[tuple[str, float, str]]] = {
    "hours": [
        (r"\b(?:all|whole|entire|full)[- ]day\b|\bday[- ]long\b", 16, "a full day (~16 hours)"),
        (r"\ball[- ]night\b|\bovernight\b", 10, "a night (~10 hours)"),
        (r"\b(?:all|whole|entire)(?: the)?[- ]weekend\b|\bweekend[- ]long\b|\bfrom friday to sunday\b", 48, "a weekend (~48 hours)"),
        (r"\b(?:two|2|a couple of) days\b|\bfor days\b|\bdays on end\b", 48, "multiple days (≥48 hours)"),
        (r"\b(?:a|one|whole|entire|all|full)[- ]week\b|\bseven days\b", 168, "a week (~168 hours)"),
        (r"\b(?:a|whole|entire) month\b", 720, "a month (~720 hours)"),
        (r"\bforever\b|\bnever (?:need to |needs? to |have to )?(?:charge|recharge|run out|runs? out|die)s?\w*\b|\bendless\b|\bunlimited\b",
         INF, "unlimited / never needs charging"),
    ],
    "dB": [
        (r"\b(?:complete|total|absolute|perfect)(?:ly)? silen\w*|\bsilences? (?:everything|the world|it all)\b|"
         r"\bblocks? (?:out )?(?:all|every|100%)\b[\w ]{0,12}(?:noise|sound)|\bevery (?:single )?sound\b|\b100% (?:of )?(?:noise|sound)",
         INF, "complete silence (unbounded)"),
    ],
    "years": [
        (r"\blifetime\b|\bfor life\b|\bforever\b", INF, "lifetime (unbounded)"),
    ],
}


# ---------------------------------------------------------------- local embedder

def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


_concept_res = {c: [re.compile(rf"(?<![a-z]){re.escape(t)}(?:s|es|ed|ing)?(?![a-z])", re.I) for t in terms]
                for c, terms in CONCEPTS.items()}


def concepts_in(text: str) -> dict[str, int]:
    out = {}
    for c, pats in _concept_res.items():
        n = sum(1 for p in pats if p.search(text))
        if n:
            out[c] = n
    return out


def local_vector(text: str) -> dict[str, float]:
    t = text.lower()
    v: dict[str, float] = defaultdict(float)
    for w in re.findall(r"[a-z0-9₹]+(?:-[a-z0-9]+)*", t):
        if w in STOP:
            continue
        s = _stem(w)
        v["w:" + s] += 1.0
        p = f" {s} "
        for i in range(len(p) - 3):
            v["c:" + p[i:i + 4]] += 0.25
    for c, n in concepts_in(t).items():
        v["k:" + c] += 3.0 * min(n, 3)
    return dict(v)


def cosine(a, b) -> float:
    if isinstance(a, dict):
        dot = sum(x * b.get(k, 0.0) for k, x in a.items())
        na = math.sqrt(sum(x * x for x in a.values()))
        nb = math.sqrt(sum(x * x for x in b.values()))
    else:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------- remote embedder (optional)

def remote_enabled() -> bool:
    return llm.provider() == "gemini" and os.environ.get("SEMANTIC_REMOTE", "1") != "0"


def remote_embed(texts: list[str]) -> list[list[float]] | None:
    if not texts or not remote_enabled():
        return None
    key = os.environ["GEMINI_API_KEY"]
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{REMOTE_MODEL}:batchEmbedContents",
                       headers={"x-goog-api-key": key}, timeout=20,
                       json={"requests": [{"model": f"models/{REMOTE_MODEL}", "content": {"parts": [{"text": t}]},
                                           "taskType": "SEMANTIC_SIMILARITY"} for t in texts]})
        r.raise_for_status()
        return [e["values"] for e in r.json()["embeddings"]]
    except Exception as e:
        log.warning("remote embedding failed: %s", str(e).replace(key, "***"))
        return None


def status() -> dict:
    return {"local": LOCAL_MODEL, "remote": REMOTE_MODEL if remote_enabled() else None,
            "index": "pgvector" if (db.IS_PG and db.HAS_VECTOR) else "fact_vectors table (in-process cosine)"}


# ---------------------------------------------------------------- fact documents & index

def fact_document(f: dict) -> str:
    return " ".join(str(x) for x in [f["label"], f["key"].replace("_", " "), *(f.get("aliases") or []), f["value"],
                                     f.get("approved_phrasing") or "", *(f.get("examples") or []),
                                     *(f.get("disallowed") or [])] if x)


def approved_document(f: dict) -> str:
    return " ".join(x for x in [f["label"], f["value"], f.get("approved_phrasing") or ""] if x)


def index_facts(conn, facts: list[dict]) -> dict[int, list[float]]:
    """Return remote vectors for facts, computing and caching any that are missing."""
    if not remote_enabled() or conn is None:
        return {}
    have = {r["fact_id"]: json.loads(r["vector"]) for r in conn.execute(
        f"SELECT fact_id, vector FROM fact_vectors WHERE model=? AND fact_id IN ({','.join('?' * len(facts))})",
        [REMOTE_MODEL, *[f["id"] for f in facts]])} if facts else {}
    missing = [f for f in facts if f["id"] not in have]
    if missing:
        vecs = remote_embed([fact_document(f) for f in missing])
        if vecs:
            for f, v in zip(missing, vecs):
                have[f["id"]] = v
                if getattr(conn, "is_pg", False) and db.HAS_VECTOR:
                    conn.execute("INSERT INTO fact_vectors (fact_id, model, vector, embedding, updated_at) VALUES (?,?,?,?::vector,?) "
                                 "ON CONFLICT (fact_id, model) DO UPDATE SET vector=excluded.vector, embedding=excluded.embedding, "
                                 "updated_at=excluded.updated_at", (f["id"], REMOTE_MODEL, json.dumps(v), json.dumps(v), db.now()))
                else:
                    conn.execute("INSERT INTO fact_vectors (fact_id, model, vector, updated_at) VALUES (?,?,?,?) "
                                 "ON CONFLICT (fact_id, model) DO UPDATE SET vector=excluded.vector, updated_at=excluded.updated_at",
                                 (f["id"], REMOTE_MODEL, json.dumps(v), db.now()))
            conn.commit()
    return have


def invalidate(conn, fact_id: int) -> None:
    conn.execute("DELETE FROM fact_vectors WHERE fact_id=?", (fact_id,))
    conn.commit()


def remote_sims(conn, sent_vec, fact_vecs: dict) -> dict | None:
    """Similarity of one sentence vector to cached fact vectors: ranked in SQL by pgvector when available."""
    if sent_vec is None or not fact_vecs:
        return None
    if getattr(conn, "is_pg", False) and db.HAS_VECTOR:
        ids = list(fact_vecs)
        rows = conn.execute(f"SELECT fact_id, 1 - (embedding <=> ?::vector) AS sim FROM fact_vectors WHERE model=? "
                            f"AND embedding IS NOT NULL AND fact_id IN ({','.join('?' * len(ids))}) ORDER BY embedding <=> ?::vector",
                            [json.dumps(sent_vec), REMOTE_MODEL, *ids, json.dumps(sent_vec)])
        return {r["fact_id"]: float(r["sim"]) for r in rows}
    return {fid: cosine(sent_vec, v) for fid, v in fact_vecs.items()}


def retrieve(sentence: str, facts: list[dict], remote_fact_vecs: dict, remote_sent_vec=None, sims: dict | None = None) -> list[dict]:
    """Rank fact keys by similarity. Returns [{key, fact, local, remote, score}] best first."""
    sv = local_vector(sentence)
    sc = concepts_in(sentence)
    best: dict[str, dict] = {}
    for f in facts:
        fv = local_vector(fact_document(f))
        loc = cosine(sv, fv)
        # local matches must share a concept; char overlap alone is not evidence
        if not (set(sc) & set(concepts_in(fact_document(f)))):
            loc = min(loc, T_LOCAL * 0.5)
        if sims is not None:
            rem = sims.get(f["id"])
        else:
            rem = cosine(remote_sent_vec, remote_fact_vecs[f["id"]]) if remote_sent_vec and f["id"] in remote_fact_vecs else None
        score = max(loc, ((rem - T_REMOTE) / (1 - T_REMOTE)) * (1 - T_LOCAL) + T_LOCAL) if rem is not None and rem >= T_REMOTE else loc
        cur = best.get(f["key"])
        if cur is None or score > cur["score"]:
            best[f["key"]] = {"key": f["key"], "fact": f, "local": round(loc, 3),
                              "remote": round(rem, 3) if rem is not None else None, "score": round(score, 3)}
    return sorted(best.values(), key=lambda d: -d["score"])


# ---------------------------------------------------------------- interpretation

def interpret(sentence: str, unit: str | None):
    for pat, val, label in VAGUE.get(unit or "", []):
        m = re.search(pat, sentence, re.I)
        if m:
            return m, val, label
    return None


def _span(sentence: str, base: int, m: re.Match | None) -> tuple[int, int]:
    if m:
        a, b = m.start(), m.end()
        # pull in an adjacent claim verb or concept word: "lasts all weekend", "silence the world"
        for w in reversed(list(re.finditer(r"[\w-]+", sentence[:a]))[-2:]):
            if sentence[w.end():a].strip(" ") or not (CLAIM_CUES.fullmatch(w.group(0)) or concepts_in(w.group(0))):
                break
            a = w.start()
        return base + a, base + b
    hits = [p.search(sentence) for pats in _concept_res.values() for p in pats]
    hits = [h for h in hits if h]
    if not hits:
        s = len(sentence) - len(sentence.lstrip())
        return base + s, base + len(sentence.rstrip())
    a = min(h.start() for h in hits)
    words = list(re.finditer(r"\S+", sentence[a:]))[:6]
    b = a + (words[-1].end() if words else 0)
    return base + a, base + min(b, len(sentence.rstrip(" .!?")))


def _sentences(text: str):
    for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
        if m.group(0).strip():
            yield m.start(), m.group(0)


# ---------------------------------------------------------------- main check

def check_semantic(text: str, facts: list[dict], rules: list[dict], existing: list[dict], conn=None) -> list[dict]:
    from . import preflight as pf

    if not text.strip() or not facts:
        return []
    today = pf._today()
    taken = [(f["start"], f["end"]) for f in existing if f.get("start") is not None and f["end"] > f["start"]]
    fact_by_id = {f["id"]: f for f in facts}
    handled: list[tuple[int, int, str]] = [(f["start"], f["end"], fact_by_id[f["fact_id"]]["key"])
                                           for f in existing if f.get("fact_id") in fact_by_id and f.get("start") is not None]
    rule = next(iter(pf._rule_by_type(rules, "claim_evidence")), None)

    sents = [(b, s) for b, s in _sentences(text) if concepts_in(s) or remote_enabled()]
    remote_fv = index_facts(conn, facts) if sents else {}
    remote_sv = remote_embed([s for _, s in sents]) if remote_fv else None

    out, ask_ai = [], []
    for i, (base, sent) in enumerate(sents):
        sv = remote_sv[i] if remote_sv else None
        ranked = retrieve(sent, facts, remote_fv, sv, remote_sims(conn, sv, remote_fv))
        if not ranked or ranked[0]["score"] < T_LOCAL:
            continue
        top = ranked[0]
        key = top["key"]
        s_end = base + len(sent)
        if any(a >= base and b <= s_end and k == key for a, b, k in handled):
            continue  # this sentence's claim on this fact was already checked deterministically
        same = [f for f in facts if f["key"] == key]
        live = [f for f in same if pf._valid(f, today)]
        f = live[0] if live else max(same, key=lambda x: x.get("valid_to") or "")
        trace = {"model": LOCAL_MODEL + (f" + {REMOTE_MODEL}" if top["remote"] is not None else ""),
                 "score": top["score"], "runner_up": ranked[1]["score"] if len(ranked) > 1 else None,
                 "retrieved": [{"fact_id": r["fact"]["id"], "label": r["fact"]["label"], "score": r["score"]} for r in ranked[:3]]}
        conf = round(min(0.85, 0.55 + 0.4 * top["score"]), 2)
        base_f = dict(category="claim", rule_id=rule["id"] if rule else None, fact_id=f["id"],
                      source_ref=f.get("source_ref"), engine="semantic", confidence=conf)

        finding, needs_ai = None, False
        if f.get("numeric") is not None and f.get("comparator") in ("max", "exact"):
            it = interpret(sent, f.get("unit"))
            if it:
                m, implied, label = it
                a, b = _span(sent, base, m)
                trace["interpretation"] = f"“{m.group(0)}” ≈ {label}"
                if len({x["numeric"] for x in live}) > 1:
                    finding = {**base_f, "status": "conflicting", "severity": "high",
                               "reason": f"Paraphrased claim about {f['label'].lower()}; approved sources disagree: " +
                                         "; ".join(f"{x['value']} ({x['source_ref']})" for x in live) + "."}
                elif not live:
                    finding = {**base_f, "status": "expired", "severity": "high",
                               "reason": f"Paraphrased claim about {f['label'].lower()}; the only approved figure ({f['value']}) expired on {f['valid_to']}."}
                else:
                    ok = implied <= f["numeric"] if f["comparator"] == "max" else implied == f["numeric"]
                    if ok:
                        finding = {**base_f, "status": "supported", "severity": "info", "suggestion": None,
                                   "reason": f"Paraphrase read as {label}, within the approved {f['label'].lower()} ({f['value']})."}
                    else:
                        verb = re.match(r"[\w-]+", sent[a - base:])
                        verb = verb.group(0) if verb and CLAIM_CUES.fullmatch(verb.group(0)) else ""
                        bounded = implied != INF and f["comparator"] == "max"
                        n = int(f["numeric"]) if float(f["numeric"]).is_integer() else f["numeric"]
                        finding = {**base_f, "status": "contradicted", "severity": "high",
                                   "suggestion": f"{verb} up to {n} {f.get('unit') or ''}".strip() if bounded else None,
                                   "reason": f"Paraphrased claim implies {label}, which exceeds the approved {f['label'].lower()} ({f['value']})."
                                             + ("" if bounded else f" Rephrase using the approved wording: “{f.get('approved_phrasing') or f['value']}”.")}
        elif f.get("disallowed"):
            approved_s = cosine(local_vector(sent), local_vector(approved_document(f)))
            dis_doc = " ".join(f["disallowed"])
            dis_s = cosine(local_vector(sent), local_vector(dis_doc))
            if set(concepts_in(sent)) & set(concepts_in(dis_doc)) and dis_s > approved_s:
                hit = next((p.search(sent) for c in concepts_in(dis_doc) for p in _concept_res[c] if p.search(sent)), None)
                a, b = _span(sent, base, hit)
                trace["interpretation"] = f"closer to disallowed wording ({', '.join(f['disallowed'])}) than to approved wording"
                trace["disallowed_score"], trace["approved_score"] = round(dis_s, 3), round(approved_s, 3)
                finding = {**base_f, "status": "contradicted" if live else "expired", "severity": "high",
                           "suggestion": None,
                           "reason": f"Paraphrase implies something the approved {f['label'].lower()} rules out "
                                     f"({', '.join(f['disallowed'])}). Rephrase using the approved wording: "
                                     f"“{f.get('approved_phrasing') or f['value']}”."}
        if finding is None and f.get("disallowed"):
            continue  # wording-only fact and the sentence sits closer to the approved wording: consistent, nothing to flag
        if finding is None and CLAIM_CUES.search(sent) and top["score"] >= T_LOCAL + 0.05:
            a, b = _span(sent, base, None)
            finding = {**base_f, "status": "unverified", "severity": "medium",
                       "suggestion": f.get("approved_phrasing"),
                       "reason": f"Reads like a claim about {f['label'].lower()} (approved: {f['value']}), but the wording "
                                 f"cannot be checked against the figure. Use the approved phrasing or add evidence."}
            needs_ai = True
        if finding is not None and finding["status"] in ("contradicted", "unverified") and NEGATED.search(text[max(base, a - 40):a]):
            continue  # "didn't go swimming", "need a waterproof case": not a claim about the product
        if finding is None or pf._overlaps(taken, a, b):
            continue
        taken.append((a, b))
        finding.setdefault("suggestion", None)
        out.append({**finding, "start": a, "end": b, "excerpt": text[a:b], "match": trace})
        if needs_ai:
            ask_ai.append((len(out) - 1, sent, f))

    _ai_verify(out, ask_ai)
    return out


def _ai_verify(out: list[dict], items) -> None:
    """Optional: let the LLM upgrade an `unverified` paraphrase to `contradicted` when it clearly overstates."""
    if not items or not llm.provider():
        return
    res = llm.complete_json(
        "You verify marketing claims against approved product facts. For each item, decide if the claim, read naturally, "
        "is SUPPORTED by, CONTRADICTS (overstates or conflicts with), or is UNCLEAR relative to the fact. "
        "Return JSON {\"results\":[{\"i\":int,\"relation\":\"supports|contradicts|unclear\",\"why\":str}]}.",
        json.dumps([{"i": k, "claim": s, "fact": f"{f['label']}: {f['value']} ({f['comparator']})"}
                    for k, (_, s, f) in enumerate(items)]))
    for r in (res or {}).get("results", []) if isinstance(res, dict) else []:
        try:
            idx = items[int(r["i"])][0]
        except Exception:
            continue
        if r.get("relation") == "contradicts" and idx < len(out):
            o = out[idx]
            o.update(status="contradicted", severity="high", engine="ai", confidence=0.65,
                     reason=f"{o['reason']} AI verifier: {r.get('why') or 'claim overstates the approved fact.'}")
