"""Pluggable LLM layer. Returns None whenever no provider is configured or a call fails,
so every caller must have a deterministic fallback.

Env:
  LLM_PROVIDER = openai | gemini | anthropic   (unset = heuristics only)
  OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY
  LLM_MODEL (optional override)
"""
import json
import logging
import os
import re

import httpx

log = logging.getLogger("brandproof.llm")

# models get retired; when the configured one returns 404 we try these in order
FALLBACKS = {
    "gemini": ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-2.5-flash-lite"],
    "openai": ["gpt-4.1-mini", "gpt-4o-mini"],
    "anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5"],
}
_working: dict[str, str] = {}  # provider -> model that last worked

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-flash-lite-latest",
    "anthropic": "claude-haiku-5-5",
}


def provider() -> str | None:
    p = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if p in DEFAULT_MODELS and os.environ.get(f"{p.upper()}_API_KEY"):
        return p
    return None


def status() -> dict:
    p = provider()
    return {"provider": p, "model": (_working.get(p) or os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(p)) if p else None,
            "mode": "ai+deterministic" if p else "deterministic+heuristic"}


def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        return None
    return json.loads(text[start:])


def _candidates(p: str) -> list[str]:
    first = os.environ.get("LLM_MODEL") or DEFAULT_MODELS[p]
    extra = [m.strip() for m in (os.environ.get("LLM_FALLBACK_MODELS") or "").split(",") if m.strip()]
    out = []
    for m in [_working.get(p), first, *extra, *FALLBACKS.get(p, [])]:
        if m and m not in out:
            out.append(m)
    return out


def _call(p: str, key: str, model: str, system: str, user: str, timeout: float) -> str:
    if p == "openai":
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=timeout,
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if p == "gemini":
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                       headers={"x-goog-api-key": key}, timeout=timeout,
                       json={"systemInstruction": {"parts": [{"text": system}]},
                             "contents": [{"role": "user", "parts": [{"text": user}]}],
                             "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=timeout,
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                   json={"model": model, "max_tokens": 2000, "temperature": 0, "system": system,
                         "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def complete_json(system: str, user: str, timeout: float = 30.0):
    p = provider()
    if not p:
        return None
    key = os.environ[f"{p.upper()}_API_KEY"]
    for model in _candidates(p):
        try:
            text = _call(p, key, model, system, user, timeout)
            if _working.get(p) != model:
                log.info("LLM using %s/%s", p, model)
            _working[p] = model
            return _extract_json(text)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 400) and "model" in e.response.text.lower() or e.response.status_code == 404:
                log.warning("LLM model %s unavailable (%s), trying next", model, e.response.status_code)
                continue  # retired or unknown model: try the next one
            log.warning("LLM call failed (%s/%s): %s", p, model, str(e).replace(key, "***"))
            return None
        except httpx.TimeoutException:
            log.warning("LLM model %s timed out, trying next", model)
            continue
        except Exception as e:  # never break a check because of the AI layer
            log.warning("LLM call failed (%s/%s): %s", p, model, str(e).replace(key, "***"))
            return None
    log.warning("LLM: no available model for %s; set LLM_MODEL to one your key can use", p)
    return None
