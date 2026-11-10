"""Run: .venv\\Scripts\\python.exe check_ai.py  -> checks the AI key in .env and finds a model it can use."""
import logging
import os

import httpx

import app  # loads .env
from app import llm

logging.basicConfig(level=logging.INFO, format="%(message)s")
print("config:", llm.status())
if llm.provider() == "gemini":
    key = os.environ["GEMINI_API_KEY"]
    try:
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key}, timeout=20)
        r.raise_for_status()
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]]
        print("flash models this key can use:", ", ".join(names) or "none")
    except Exception as e:
        print("could not list models:", str(e).replace(key, "***"))
r = llm.complete_json("Reply only with JSON.", 'Return {"ok": true}', timeout=20)
if r:
    print("LIVE CALL OK with model:", llm.status()["model"], r)
    print("Tip: set LLM_MODEL to that model in backend/.env and on Render to skip the fallback search.")
else:
    print("LIVE CALL FAILED - see the messages above (bad key, no available model, or quota)")
