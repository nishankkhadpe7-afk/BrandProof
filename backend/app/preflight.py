"""ENGINE B (evidence verification) + content checks.

Every finding carries: exact span or image region, rule and/or fact, source
reference, a clear status, a reason, an optional suggestion, confidence and
which engine produced it. Exact rules are deterministic; language/context
checks use the LLM only when configured.
"""
import re
from datetime import date

from . import compiler, llm, ocr, semantic

# ---------------------------------------------------------------- helpers

UNIT_NORM = {
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
    "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
    "day": "days", "days": "days", "week": "weeks", "weeks": "weeks", "month": "months", "months": "months", "year": "years", "years": "years", "yr": "years", "yrs": "years",
    "%": "%", "percent": "%", "x": "x", "times": "x", "mah": "mAh", "mg": "mg", "ml": "ml", "kg": "kg", "kcal": "kcal", "cal": "kcal", "calories": "kcal",
    "litre": "l", "litres": "l", "liter": "l", "liters": "l", "watt": "W", "watts": "W", "w": "W", "gb": "GB", "tb": "TB", "g": "g", "gram": "g", "grams": "g",
    "db": "dB", "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m", "ms": "ms",
    "$": "USD", "usd": "USD", "₹": "INR", "inr": "INR", "rs": "INR", "rs.": "INR", "€": "EUR", "£": "GBP",
}

NUM_CLAIM = re.compile(
    r"(?P<qual>\b(?:up to|over|more than|at least|under|less than|only|just)\s+)?"
    r"(?P<cur>[$₹€£]|\bRs\.?\s?|\bINR\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\b(?:one|two|three|four|five|six|seven|ten|twelve|a)(?=[\s-]+(?:years?|months?|weeks?|days?|hours?)\b))"
    r"(?:(?:\s|-)?(?P<unit>hours?|hrs?|hr|h|percent|%|minutes?|mins?|days?|weeks?|months?|years?|yrs?|mAh|mg|ml|kg|kcal|cal|calories|litres?|liters?|watts?|W|GB|TB|grams?|g|dB|ms|m|metres?|meters?|x|times)(?![A-Za-z]))?",
    re.I)

QUAL_CLAIMS = [r"#\s?1\b", r"\bnumber one\b", r"\bclinically proven\b", r"\baward[- ]winning\b", r"\bbest[- ]selling\b",
               r"\bcarbon[- ]neutral\b", r"\bguaranteed\b", r"\bcertified\b", r"\bdoctor[- ]recommended\b",
               r"\bscientifically proven\b", r"\bindustry[- ]leading\b", r"\bfastest\b", r"\blongest\b", r"\bmost popular\b"]

HYPE_REPLACEMENTS = {"revolutionary": "new", "game-changing": "notable", "game changing": "notable",
                     "best-in-class": "high-quality", "unbeatable": "strong", "insane": "impressive",
                     "mind-blowing": "impressive", "perfect": "great", "ultimate": "complete",
                     "world-class": "high-quality", "groundbreaking": "new", "magical": "effortless"}

WORD_NUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "twelve": 12}
# convertible units: "30 days" or "6 months" can be compared with a warranty stored in years
TO_BASE = {"minutes": ("time", 1 / 60), "hours": ("time", 1), "days": ("span", 1), "weeks": ("span", 7),
           "months": ("span", 30.44), "years": ("span", 365.25)}


def _conv(value: float, unit: str, target: str | None):
    """Convert value from unit to target; None if incompatible."""
    unit, target = (unit or "").lower(), (target or "").lower()
    if unit == target:
        return value
    a, b = TO_BASE.get(unit), TO_BASE.get(target)
    if a and b and a[0] == b[0]:
        return value * a[1] / b[1]
    return None


STATUS_SEVERITY = {"contradicted": "high", "expired": "high", "conflicting": "high", "unverified": "medium", "supported": "info"}


def _today() -> str:
    return date.today().isoformat()


def _valid(f: dict, today: str) -> bool:
    return (not f.get("valid_from") or f["valid_from"] <= today) and (not f.get("valid_to") or f["valid_to"] >= today)


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _word_re(term: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", re.I)


def _sentence_of(text: str, pos: int) -> str:
    s = max(text.rfind(c, 0, pos) for c in ".!?\n")
    e = min([i for i in (text.find(c, pos) for c in ".!?\n") if i != -1] or [len(text)])
    return text[s + 1:e]


def _overlaps(spans: list[tuple[int, int]], a: int, b: int) -> bool:
    return any(a < y and x < b for x, y in spans)


def _rule_by_type(rules, *types):
    # skip malformed rules (e.g. activated before params were filled) instead of crashing the preflight
    return [r for r in rules if r["type"] in types and not compiler.missing_params(r["type"], r.get("params"))]


# ---------------------------------------------------------------- claims (Engine B)

def check_claims(text: str, facts: list[dict], rules: list[dict]) -> list[dict]:
    today = _today()
    out: list[dict] = []
    spans: list[tuple[int, int]] = []
    evidence_rules = _rule_by_type(rules, "claim_evidence")

    def rule_for(topic_words: list[str]):
        for r in evidence_rules:
            topics = r["params"].get("topics") or []
            if any(t[:5] in w.lower() for t in topics for w in topic_words):
                return r
        return evidence_rules[0] if evidence_rules else None

    # 1) phrases an approved fact explicitly contradicts (e.g. "waterproof" vs IPX4)
    for f in facts:
        for phrase in f.get("disallowed") or []:
            for m in _word_re(phrase).finditer(text):
                if _overlaps(spans, m.start(), m.end()) or semantic.NEGATED.search(text[max(0, m.start() - 40):m.start()]):
                    continue
                spans.append((m.start(), m.end()))
                r = rule_for([f["key"], *f.get("aliases", [])])
                status = "contradicted" if _valid(f, today) else "expired"
                out.append(dict(category="claim", status=status, severity="high", start=m.start(), end=m.end(),
                                excerpt=m.group(0), fact_id=f["id"], rule_id=r["id"] if r else None,
                                reason=f"“{m.group(0)}” is not supported: approved {f['label'].lower()} is {f['value']}.",
                                suggestion=f.get("approved_phrasing"), source_ref=f.get("source_ref"), confidence=0.95))

    # 2) numeric claims checked against the evidence ledger
    numeric_facts = [f for f in facts if f.get("numeric") is not None]
    for m in NUM_CLAIM.finditer(text):
        unit_raw = (m.group("unit") or "").lower()
        cur = (m.group("cur") or "").strip().lower()
        if not unit_raw and not cur:
            continue
        unit = UNIT_NORM.get(cur or unit_raw, unit_raw)
        a, b = m.start(), m.end()
        if _overlaps(spans, a, b):
            continue
        raw = m.group("num").lower()
        value = float(WORD_NUM[raw]) if raw in WORD_NUM else float(raw.replace(",", ""))
        sent = _sentence_of(text, a).lower()
        cands = [f for f in numeric_facts
                 if _conv(value, unit, f.get("unit")) is not None
                 and any(_word_re(al).search(sent) for al in [f["label"], *f.get("aliases", [])])]
        if cands:
            value = _conv(value, unit, cands[0].get("unit"))
        spans.append((a, b))
        excerpt = m.group(0).strip()
        if not cands:
            r = rule_for([sent])
            out.append(dict(category="claim", status="unverified", severity="medium", start=a, end=b, excerpt=excerpt,
                            rule_id=r["id"] if r else None, fact_id=None,
                            reason="No approved fact in the evidence ledger covers this figure. Missing evidence means unverified, not wrong.",
                            suggestion=None, source_ref=None, confidence=0.8))
            continue
        key = cands[0]["key"]
        same_key = [f for f in cands if f["key"] == key]
        live = [f for f in same_key if _valid(f, today)]
        r = rule_for([key, *cands[0].get("aliases", [])])
        base = dict(category="claim", start=a, end=b, excerpt=excerpt, rule_id=r["id"] if r else None)
        if len({f["numeric"] for f in live}) > 1:
            out.append({**base, "status": "conflicting", "severity": "high", "fact_id": live[0]["id"],
                        "reason": "Two active approved sources disagree: " +
                                  "; ".join(f"{f['value']} ({f['source_ref']})" for f in live) + ". Resolve the ledger before publishing.",
                        "suggestion": None, "source_ref": " | ".join(f["source_ref"] or "" for f in live), "confidence": 1.0})
            continue
        if not live:
            f = max(same_key, key=lambda x: x.get("valid_to") or "")
            out.append({**base, "status": "expired", "severity": "high", "fact_id": f["id"],
                        "reason": f"The only approved figure ({f['value']}) expired on {f['valid_to']}. Request current evidence from {f.get('owner') or 'the fact owner'}.",
                        "suggestion": None, "source_ref": f.get("source_ref"), "confidence": 1.0})
            continue
        f = live[0]
        approved = f["numeric"]
        ok = value <= approved if f["comparator"] == "max" else abs(value - approved) <= max(0.005 * approved, 1e-9)
        qual = (m.group("qual") or "").lower().strip()
        if ok and f["comparator"] == "max" and value == approved and qual not in ("up to", "under", "less than", "only", "just"):
            # matches the figure but drops the "up to" qualifier
            out.append({**base, "status": "supported", "severity": "low", "fact_id": f["id"],
                        "reason": f"Figure matches the approved {f['label'].lower()} ({f['value']}), but the source states it as a maximum. Add “up to”.",
                        "suggestion": "up to " + excerpt, "source_ref": f.get("source_ref"), "confidence": 0.9})
        elif ok:
            out.append({**base, "status": "supported", "severity": "info", "fact_id": f["id"],
                        "reason": f"Matches the approved {f['label'].lower()}: {f['value']}.",
                        "suggestion": None, "source_ref": f.get("source_ref"), "confidence": 1.0})
        else:
            unit_txt = excerpt[len(m.group("qual") or ""):]
            new_num = unit_txt.replace(m.group("num"), _fmt(approved), 1)
            sugg = ("up to " + new_num) if f["comparator"] == "max" else new_num
            verb = "exceeds" if f["comparator"] == "max" else "does not match"
            out.append({**base, "status": "contradicted", "severity": "high", "fact_id": f["id"],
                        "reason": f"The submitted claim {verb} the active approved {f['label'].lower()} ({f['value']}).",
                        "suggestion": sugg, "source_ref": f.get("source_ref"), "confidence": 1.0})

    # 3) qualitative claims that always need evidence
    for pat in QUAL_CLAIMS:
        for m in re.finditer(pat, text, re.I):
            if _overlaps(spans, m.start(), m.end()):
                continue
            spans.append((m.start(), m.end()))
            r = rule_for([m.group(0)])
            out.append(dict(category="claim", status="unverified", severity="medium", start=m.start(), end=m.end(),
                            excerpt=m.group(0), rule_id=r["id"] if r else None, fact_id=None,
                            reason=f"“{m.group(0)}” is a factual claim with no approved evidence in the ledger.",
                            suggestion=None, source_ref=None, confidence=0.85))

    # 4) required disclaimers
    for r in _rule_by_type(rules, "disclaimer_required"):
        trig, disc = r["params"].get("trigger"), r["params"].get("text")
        if not trig or not disc:
            continue
        triggered = re.search(rf"\b{trig[:5]}\w*|[$₹€£]\s?[\d,]+|\d+%\s*off|\bdiscount|\boffer\b", text, re.I) if trig.startswith("pric") or trig in ("offer", "discount") \
            else re.search(rf"\b{re.escape(trig)}", text, re.I)
        if triggered and disc.lower() not in text.lower():
            out.append(dict(category="claim", status="violation", severity=r["severity"], start=len(text), end=len(text),
                            excerpt=triggered.group(0), rule_id=r["id"], fact_id=None,
                            reason=f"Content mentions {trig} but is missing the required disclaimer.",
                            suggestion=(" " if text and not text.endswith((" ", "\n")) else "") + disc,
                            source_ref=r.get("source_ref"), confidence=1.0))
    return out


# ---------------------------------------------------------------- terms & tone

def check_terms_tone(text: str, rules: list[dict]) -> list[dict]:
    out = []
    spans: list[tuple[int, int]] = []
    for r in _rule_by_type(rules, "preferred_term"):
        use = r["params"]["use"]
        for term in r["params"].get("avoid", []):
            # case-only variants (e.g. "LUMORA" vs "Lumora") must match case-sensitively
            pat = re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])") if term.lower() == use.lower() else _word_re(term)
            for m in pat.finditer(text):
                if _overlaps(spans, m.start(), m.end()) or m.group(0) == use:
                    continue
                spans.append((m.start(), m.end()))
                out.append(dict(category="term", status="violation", severity=r["severity"], start=m.start(), end=m.end(),
                                excerpt=m.group(0), rule_id=r["id"], reason=f"Approved term is “{use}”, not “{m.group(0)}”.",
                                suggestion=use, source_ref=r.get("source_ref"), confidence=1.0))
    for r in _rule_by_type(rules, "banned_term", "tone_avoid"):
        cat = "term" if r["type"] == "banned_term" else "tone"
        repl = r["params"].get("replacements") or {}
        for term in r["params"].get("terms", []):
            for m in _word_re(term).finditer(text):
                if _overlaps(spans, m.start(), m.end()):
                    continue
                spans.append((m.start(), m.end()))
                sugg = repl.get(term.lower()) or HYPE_REPLACEMENTS.get(term.lower())
                why = "Banned term" if cat == "term" else "Off-tone hype language"
                out.append(dict(category=cat, status="violation", severity=r["severity"], start=m.start(), end=m.end(),
                                excerpt=m.group(0), rule_id=r["id"],
                                reason=f"{why} per guideline: “{r['text']}”" + ("" if sugg else " Rephrase with a specific, evidenced benefit."),
                                suggestion=sugg, source_ref=r.get("source_ref"), confidence=1.0))
    for r in _rule_by_type(rules, "max_exclamations"):
        mx = r["params"].get("max")
        if mx is None:
            continue
        marks = [m.start() for m in re.finditer("!", text)]
        for p in marks[mx:]:
            out.append(dict(category="tone", status="violation", severity=r["severity"], start=p, end=p + 1, excerpt="!",
                            rule_id=r["id"], reason=f"More than {mx} exclamation mark(s) in one piece.", suggestion=".",
                            source_ref=r.get("source_ref"), confidence=1.0))

    # AI: contextual tone against the tone profile
    profiles = _rule_by_type(rules, "tone_profile")
    if profiles and text.strip():
        res = llm.complete_json(
            "You are a brand tone reviewer. Given the brand tone guideline and content, return JSON "
            "{\"issues\":[{\"quote\":str,\"reason\":str,\"suggestion\":str}]}. quote MUST be an exact substring of the content, "
            "at most 12 words. Only flag clear tone mismatches. Keep the creator's intent in suggestions.",
            "TONE GUIDELINE:\n" + "\n".join(p["text"] for p in profiles) + "\n\nCONTENT:\n" + text)
        for it in (res or {}).get("issues", []) if isinstance(res, dict) else []:
            q = (it.get("quote") or "").strip()
            i = text.find(q) if q else -1
            if i == -1 or _overlaps(spans, i, i + len(q)):
                continue
            spans.append((i, i + len(q)))
            out.append(dict(category="tone", status="violation", severity="low", start=i, end=i + len(q), excerpt=q,
                            rule_id=profiles[0]["id"], reason=str(it.get("reason") or "Tone mismatch."),
                            suggestion=it.get("suggestion"), source_ref=profiles[0].get("source_ref"),
                            confidence=0.7, engine="ai"))
    return out


# ---------------------------------------------------------------- accessibility

def check_accessibility(text: str, rules: list[dict], is_image: bool, alt_text: str | None) -> list[dict]:
    out = []
    for r in _rule_by_type(rules, "max_sentence_words"):
        mx = r["params"].get("max")
        if not mx:
            continue
        for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
            words = re.findall(r"\b\w[\w'’-]*\b", m.group(0))
            if len(words) > mx:
                a = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
                out.append(dict(category="accessibility", status="violation", severity=r["severity"], start=a, end=m.end(),
                                excerpt=m.group(0).strip()[:80] + ("…" if len(m.group(0).strip()) > 80 else ""),
                                rule_id=r["id"], reason=f"Sentence has {len(words)} words; limit is {mx}. Split it for readability.",
                                suggestion=None, source_ref=r.get("source_ref"), confidence=1.0))
    for r in _rule_by_type(rules, "no_all_caps"):
        for m in re.finditer(r"\b[A-Z]{2,}(?:[\s!.,]+[A-Z]{2,}){2,}\b", text):
            out.append(dict(category="accessibility", status="violation", severity=r["severity"], start=m.start(), end=m.end(),
                            excerpt=m.group(0), rule_id=r["id"], reason="All-caps runs are harder to read and are read letter-by-letter by some screen readers.",
                            suggestion=m.group(0).capitalize(), source_ref=r.get("source_ref"), confidence=1.0))
    for r in _rule_by_type(rules, "descriptive_links"):
        for term in r["params"].get("avoid", []):
            for m in _word_re(term).finditer(text):
                out.append(dict(category="accessibility", status="violation", severity=r["severity"], start=m.start(), end=m.end(),
                                excerpt=m.group(0), rule_id=r["id"], reason="Link text must describe the destination.",
                                suggestion=None, source_ref=r.get("source_ref"), confidence=0.9))
    if is_image:
        for r in _rule_by_type(rules, "alt_text_required"):
            if not (alt_text or "").strip():
                out.append(dict(category="accessibility", status="violation", severity="high", start=None, end=None,
                                excerpt="(image)", rule_id=r["id"], reason="Image has no alt text.",
                                suggestion=None, source_ref=r.get("source_ref"), confidence=1.0))
    return out


# ---------------------------------------------------------------- visuals

def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(int(x) for x in c[:3])


def _rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _dist(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _lum(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def image_meta(img) -> dict:
    small = img.copy()
    small.thumbnail((200, 200))
    q = small.quantize(colors=6, method=2)
    pal = q.getpalette()[:18]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    colors = [{"hex": _hex(pal[i * 3:i * 3 + 3]), "share": round(c / total, 3)} for c, i in counts]
    return {"width": img.width, "height": img.height, "colors": colors}


def _region(img, target, tol=30) -> dict | None:
    small = img.copy()
    small.thumbnail((200, 200))
    sx, sy = img.width / small.width, img.height / small.height
    px = small.load()
    xs, ys = [], []
    for y in range(small.height):
        for x in range(small.width):
            if _dist(px[x, y], target) <= tol:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return {"x": int(min(xs) * sx), "y": int(min(ys) * sy), "w": int((max(xs) - min(xs) + 1) * sx),
            "h": int((max(ys) - min(ys) + 1) * sy), "img_w": img.width, "img_h": img.height, "page": 0}


def check_visual(img, meta: dict, rules: list[dict]) -> list[dict]:
    out = []
    for r in _rule_by_type(rules, "visual_palette"):
        pal = [_rgb(h) for h in r["params"].get("colors", [])]
        tol = r["params"].get("tolerance", 40)
        if not pal:
            continue
        for c in meta["colors"]:
            rgb = _rgb(c["hex"])
            neutral = max(rgb) - min(rgb) < 25
            if c["share"] < 0.08 or neutral:
                continue
            nearest = min(pal, key=lambda p: _dist(p, rgb))
            if _dist(nearest, rgb) > tol:
                out.append(dict(category="visual", status="violation", severity=r["severity"], start=None, end=None,
                                region=_region(img, rgb), excerpt=f"{c['hex']} ({int(c['share'] * 100)}% of image)",
                                rule_id=r["id"], reason=f"Off-palette colour {c['hex']} covers {int(c['share'] * 100)}% of the image.",
                                suggestion=f"Use nearest brand colour {_hex(nearest)}", source_ref=r.get("source_ref"), confidence=0.85))
    for r in _rule_by_type(rules, "visual_min_contrast"):
        ratio = r["params"].get("ratio")
        if not ratio or len(meta["colors"]) < 2:
            continue
        a, b = _rgb(meta["colors"][0]["hex"]), _rgb(meta["colors"][1]["hex"])
        cr = contrast(a, b)
        if cr < ratio:
            out.append(dict(category="visual", status="violation", severity=r["severity"], start=None, end=None,
                            region=_region(img, b), excerpt=f"{_hex(a)} vs {_hex(b)}", rule_id=r["id"],
                            reason=f"Dominant colours have contrast {cr:.2f}:1, below the required {ratio}:1 (heuristic: assumes they are background and foreground).",
                            suggestion=None, source_ref=r.get("source_ref"), confidence=0.6))
    for r in _rule_by_type(rules, "visual_min_resolution"):
        mw, mh = r["params"].get("min_width"), r["params"].get("min_height")
        if mw and mh and (meta["width"] < mw or meta["height"] < mh):
            out.append(dict(category="visual", status="violation", severity=r["severity"], start=None, end=None,
                            excerpt=f"{meta['width']}×{meta['height']}px", rule_id=r["id"],
                            reason=f"Image is {meta['width']}×{meta['height']}px; minimum is {mw}×{mh}px.",
                            suggestion=None, source_ref=r.get("source_ref"), confidence=1.0))
    return out


# ---------------------------------------------------------------- AI claim extraction (optional)

def ai_extra_claims(text: str, existing: list[dict]) -> list[dict]:
    if not text.strip():
        return []
    res = llm.complete_json(
        "Extract verifiable factual marketing claims (performance, comparisons, awards, health, environment, rankings) "
        "from the content. Return JSON {\"claims\":[{\"quote\":str}]} where quote is an exact substring, at most 12 words.",
        text)
    out = []
    spans = [(f["start"], f["end"]) for f in existing if f.get("start") is not None]
    for c in (res or {}).get("claims", []) if isinstance(res, dict) else []:
        q = (c.get("quote") or "").strip()
        i = text.find(q) if q else -1
        if i == -1 or _overlaps(spans, i, i + len(q)):
            continue
        spans.append((i, i + len(q)))
        out.append(dict(category="claim", status="unverified", severity="medium", start=i, end=i + len(q), excerpt=q,
                        reason="AI identified a factual claim that no approved fact covers. Missing evidence means unverified, not wrong.",
                        suggestion=None, source_ref=None, confidence=0.6, engine="ai"))
    return out


# ---------------------------------------------------------------- orchestrator

def run(text: str, rules: list[dict], facts: list[dict], *, img=None, meta=None, alt_text=None,
        ocr_words=None, conn=None, ocr_engine="n/a") -> list[dict]:
    findings = []
    findings += check_claims(text, facts, rules)
    findings += check_terms_tone(text, rules)
    findings += check_accessibility(text, rules, img is not None, alt_text)
    if img is not None and meta:
        findings += check_visual(img, meta, rules)
    findings += semantic.check_semantic(text, facts, rules, findings, conn)
    findings += ai_extra_claims(text, findings)
    if img is not None and ocr_engine is None:
        findings.append(dict(category="visual", status="unverified", severity="low", start=None, end=None, excerpt="(text in image)",
                             reason="Text inside this creative could not be read: no OCR engine is available on the server. "
                                    "Install Tesseract (or set a Gemini key) to check claims and terms inside images.",
                             suggestion=None, source_ref=None, confidence=1.0))
    for f in findings:
        if ocr_words and f.get("start") is not None and not f.get("region"):
            f["region"] = ocr.region_for(f["start"], f["end"], ocr_words)
        f.setdefault("engine", "deterministic")
        f.setdefault("rule_id", None)
        f.setdefault("fact_id", None)
        f.setdefault("region", None)
        f.setdefault("match", None)
        f["decision"] = "n/a" if f["status"] == "supported" and f.get("suggestion") is None else "pending"
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: (order.get(f["severity"], 4), f["start"] if f["start"] is not None else 1e9))
    return findings


def apply_fixes(text: str, findings: list[dict]) -> str:
    """Apply accepted/edited replacements from end to start, skipping overlaps."""
    edits = []
    for f in findings:
        if f.get("start") is None:
            continue
        if f["decision"] == "accepted" and f.get("suggestion") is not None:
            edits.append((f["start"], f["end"], f["suggestion"]))
        elif f["decision"] == "edited" and f.get("decision_text") is not None:
            edits.append((f["start"], f["end"], f["decision_text"]))
    edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
    last = len(text) + 1
    for a, b, rep in edits:
        if b > last:
            continue
        text = text[:a] + rep + text[b:]
        last = a
    return text
