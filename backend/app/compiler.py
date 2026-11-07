"""ENGINE A — Brand policy compiler.

Turns prose guidelines into typed, source-linked rules, and flags vague,
unmeasurable, untyped or conflicting rules for admin validation.
Deterministic patterns first; the LLM (if configured) only types sentences
the patterns could not, and those rules are always marked engine='ai'.
"""
import re

from . import llm

QUOTED = re.compile(r"[\"“”']([^\"“”']{1,60})[\"“”']")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
NUM = re.compile(r"\b(\d+(?:\.\d+)?)\b")

DIRECTIVE = re.compile(r"\b(must|should|never|always|avoid|do not|don't|required?|ensure|keep|use)\b", re.I)

VAGUE = ["appropriate", "where possible", "when possible", "generally", "sometimes", "excessive", "too many",
         "too much", "modern", "as needed", "if needed", "etc", "reasonable", "try to", "minimal", "clean look",
         "where relevant", "on-brand", "feel premium", "feels premium", "sparingly"]

CATEGORY = {
    "banned_term": "term", "preferred_term": "term", "tone_avoid": "tone", "tone_profile": "tone",
    "max_exclamations": "tone", "claim_evidence": "claim", "disclaimer_required": "claim",
    "max_sentence_words": "accessibility", "no_all_caps": "accessibility", "descriptive_links": "accessibility",
    "alt_text_required": "accessibility", "visual_palette": "visual", "visual_min_contrast": "visual",
    "visual_min_resolution": "visual", "unclassified": "other",
}

# Params a rule type cannot work without (absent / null / empty = missing).
REQUIRED_PARAMS = {
    "preferred_term": ["use", "avoid"], "banned_term": ["terms"], "tone_avoid": ["terms"],
    "max_exclamations": ["max"], "max_sentence_words": ["max"], "disclaimer_required": ["trigger", "text"],
    "tone_profile": ["description"], "claim_evidence": ["topics"], "visual_palette": ["colors"],
}


def missing_params(rtype: str, params) -> list[str]:
    if not isinstance(params, dict):
        return ["params (must be a JSON object)"]
    keys = set(REQUIRED_PARAMS.get(rtype, [])) | {k for k, v in params.items() if v is None}
    return sorted(k for k in keys if params.get(k) in (None, "", [], {}))


SEVERITY = {"claim": "high", "term": "medium", "visual": "medium", "tone": "low", "accessibility": "medium", "other": "low"}


def _sentences(text: str):
    """Yield (line_no, sentence) pairs. Bullets and lines are treated as sentences."""
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip().lstrip("-*•0123456789. )").strip()
        if not line or line.startswith(("#", "(")):
            continue
        for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", line):
            if s.strip():
                yield i, s.strip()


def _classify(s: str) -> list[tuple[str, dict]]:
    low = s.lower()
    q = [t.strip() for t in QUOTED.findall(s)]
    out: list[tuple[str, dict]] = []

    # preferred term: Use "A" instead of / not / rather than "B", "C"
    m = re.search(r"\b(?:use|write|say|call it)\b\s*[\"“']([^\"”']+)[\"”']([^\"“]*?)\b(?:not|instead of|rather than|never)\b(.*)", s, re.I)
    if m:
        avoid = [t.strip() for t in QUOTED.findall(m.group(3))]
        if avoid:
            return [("preferred_term", {"use": m.group(1).strip(), "avoid": avoid})]
    m = re.search(r"always (?:write|spell|refer to)\s+(.+?)\s+as\s+[\"“']([^\"”']+)[\"”']", s, re.I)
    if m:
        return [("preferred_term", {"use": m.group(2).strip(), "avoid": [t for t in q if t != m.group(2).strip()]})]

    if "exclamation" in low:
        n = NUM.search(s)
        word_nums = {"one": 1, "two": 2, "zero": 0, "no": 0}
        mx = int(float(n.group(1))) if n else next((v for k, v in word_nums.items() if re.search(rf"\b{k}\b", low)), None)
        return [("max_exclamations", {"max": mx})]

    if re.search(r"\bsentences?\b", low) and re.search(r"\bwords?\b|short", low):
        n = NUM.search(s)
        return [("max_sentence_words", {"max": int(float(n.group(1))) if n else None})]

    if "all caps" in low or "all-caps" in low or "uppercase" in low:
        return [("no_all_caps", {})]

    if "link text" in low or "click here" in low:
        return [("descriptive_links", {"avoid": q or ["click here", "read more", "here"]})]

    if "alt text" in low or "alternative text" in low:
        return [("alt_text_required", {})]

    if "contrast" in low:
        n = NUM.search(s)
        return [("visual_min_contrast", {"ratio": float(n.group(1)) if n else None})]

    hexes = HEX.findall(s)
    if hexes and ("colou" in low or "palette" in low):
        return [("visual_palette", {"colors": [h.upper() for h in hexes], "tolerance": 40})]

    if "resolution" in low or re.search(r"\bpx\b|pixels", low):
        nums = [int(float(x)) for x in NUM.findall(s)]
        return [("visual_min_resolution", {"min_width": nums[0] if nums else None,
                                           "min_height": nums[1] if len(nums) > 1 else (nums[0] if nums else None)})]

    if "disclaimer" in low:
        trig = re.search(r"(?:mention|mentions|mentioning|reference|about|includes?)\s+(?:a\s+|the\s+)?(price|pricing|offer|discount|health|finance|returns?)", low)
        text = q[0] if q else None
        return [("disclaimer_required", {"trigger": trig.group(1) if trig else None, "text": text})]

    if re.search(r"\bclaims?\b", low) and re.search(r"approved|evidence|fact sheet|verified|source|backed", low):
        topics = re.findall(r"\b(battery|price|pricing|performance|speed|health|environment(?:al)?|sustainab\w*|"
                            r"water\w*|warranty|award\w*|ranking|clinical\w*|durab\w*|noise|charging)\b", low)
        return [("claim_evidence", {"topics": sorted(set(topics)) or None})]

    if re.search(r"\b(never use|do not use|don't use|avoid (?:the )?(?:words?|terms?|phrases?)|banned|prohibited|not allowed)\b", low) and q:
        kind = "tone_avoid" if re.search(r"hype|superlative|tone|exaggerat", low) else "banned_term"
        return [(kind, {"terms": q})]
    if re.search(r"\bavoid\b", low) and q:
        kind = "tone_avoid" if re.search(r"hype|superlative|tone|exaggerat|such as", low) else "banned_term"
        return [(kind, {"terms": q})]

    if re.search(r"\b(our )?(tone|voice)\b", low):
        return [("tone_profile", {"description": s})]

    return out


def _ambiguity(rtype: str, params: dict, s: str) -> list[dict]:
    issues = []
    low = s.lower()
    for v in VAGUE:
        if re.search(rf"\b{re.escape(v)}\b", low):
            issues.append({"kind": "vague", "detail": f"Vague qualifier “{v}” — cannot be checked consistently."})
            break
    missing = [k for k, v in params.items() if v is None]
    if missing:
        issues.append({"kind": "unmeasurable", "detail": f"No measurable value for: {', '.join(missing)}."})
    if rtype == "unclassified":
        issues.append({"kind": "untyped", "detail": "Directive could not be mapped to a checkable rule type."})
    return issues


def _conflicts(rules: list[dict]) -> None:
    """Mark conflicts in place: a term required by one rule but banned/avoided by another."""
    required = {}
    for r in rules:
        if r["type"] == "preferred_term" and (r["params"] or {}).get("use"):
            required[r["params"]["use"].lower()] = r
    for r in rules:
        banned = []
        if r["type"] in ("banned_term", "tone_avoid"):
            banned = r["params"].get("terms", [])
        elif r["type"] == "preferred_term":
            banned = r["params"].get("avoid", [])
        for t in banned:
            other = required.get(t.lower())
            if other and other is not r:
                for x, y in ((r, other), (other, r)):
                    x["ambiguity"].append({"kind": "conflict",
                                           "detail": f"Conflicts with guideline at {y['location']}: “{t}” is both required and banned."})


def _llm_type(sentences: list[tuple[int, str]]) -> dict[int, tuple[str, dict]]:
    if not sentences:
        return {}
    types = ", ".join(k for k in CATEGORY if k != "unclassified")
    res = llm.complete_json(
        "You convert brand-guideline sentences into typed rules. Reply with JSON {\"rules\":[{\"i\":int,\"type\":str,\"params\":obj}]}. "
        f"Allowed types: {types}. Param shapes: banned_term/tone_avoid {{terms:[str]}}, preferred_term {{use:str,avoid:[str]}}, "
        "tone_profile {description:str}, max_sentence_words {max:int}, max_exclamations {max:int}, claim_evidence {topics:[str]}, "
        "disclaimer_required {trigger:str,text:str}. Omit sentences that are not checkable rules. Use null for values not stated.",
        "\n".join(f"{i}: {s}" for i, (_, s) in enumerate(sentences)))
    out = {}
    if isinstance(res, dict):
        for r in res.get("rules", []):
            try:
                if r["type"] in CATEGORY and r["type"] != "unclassified":
                    out[int(r["i"])] = (r["type"], r.get("params") or {})
            except (KeyError, ValueError, TypeError):
                continue
    return out


def compile_guidelines(text: str) -> list[dict]:
    rules: list[dict] = []
    untyped: list[tuple[int, str]] = []
    for line_no, s in _sentences(text):
        found = _classify(s)
        if not found:
            if DIRECTIVE.search(s):
                untyped.append((line_no, s))
            continue
        for rtype, params in found:
            rules.append({"type": rtype, "params": params, "text": s, "location": f"line {line_no}", "engine": "deterministic"})

    ai = _llm_type(untyped)
    for idx, (line_no, s) in enumerate(untyped):
        if idx in ai:
            rtype, params = ai[idx]
            rules.append({"type": rtype, "params": params, "text": s, "location": f"line {line_no}", "engine": "ai"})
        else:
            rules.append({"type": "unclassified", "params": {}, "text": s, "location": f"line {line_no}", "engine": "deterministic"})

    for r in rules:
        r["category"] = CATEGORY[r["type"]]
        r["severity"] = SEVERITY[r["category"]]
        r["ambiguity"] = _ambiguity(r["type"], r["params"], r["text"])
        if r["engine"] == "ai":
            r["ambiguity"].append({"kind": "ai_typed", "detail": "Typed by AI — admin must confirm parameters."})
    _conflicts(rules)
    return rules
