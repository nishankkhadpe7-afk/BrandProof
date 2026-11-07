"""Run: .venv\Scripts\python.exe check_ai.py  -> verifies the API key in .env works."""
import app  # loads .env
from app import llm
print("config:", llm.status())
r = llm.complete_json("Reply only with JSON.", 'Return {"ok": true}')
print("LIVE CALL OK:", r) if r else print("LIVE CALL FAILED - see warning above (bad key/model/quota)")
