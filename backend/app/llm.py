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

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-haiku-5-5",
}


def provider() -> str | None:
    p = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if p in DEFAULT_MODELS and os.environ.get(f"{p.upper()}_API_KEY"):
        return p
    return None


def status() -> dict:
    p = provider()
    return {"provider": p, "model": (os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(p)) if p else None,
            "mode": "ai+deterministic" if p else "deterministic+heuristic"}


def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        return None
    return json.loads(text[start:])


def complete_json(system: str, user: str, timeout: float = 30.0):
    p = provider()
    if not p:
        return None
    key = os.environ[f"{p.upper()}_API_KEY"]
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS[p]
    try:
        if p == "openai":
            r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=timeout,
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "temperature": 0,
                                 "response_format": {"type": "json_object"},
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": user}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        elif p == "gemini":
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                           headers={"x-goog-api-key": key}, timeout=timeout,
                           json={"systemInstruction": {"parts": [{"text": system}]},
                                 "contents": [{"role": "user", "parts": [{"text": user}]}],
                                 "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=timeout,
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                           json={"model": model, "max_tokens": 2000, "temperature": 0, "system": system,
                                 "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            text = r.json()["content"][0]["text"]
        return _extract_json(text)
    except Exception as e:  # never break the audit because of the AI layer
        log.warning("LLM call failed (%s): %s", p, str(e).replace(key, "***"))
        return None
