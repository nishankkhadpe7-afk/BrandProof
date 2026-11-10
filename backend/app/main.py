"""BrandProof API: app assembly. Routes live in app/routes/*, shared deps in app/core.py,
background checks in app/jobs.py, rate limiting in app/ratelimit.py."""
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from . import db, jobs, llm, mailer, ocr, semantic
from .core import *  # noqa: F401,F403  re-exported for seed, tests and eval
from .core import _me, _owned, _session_for  # noqa: F401
from .ratelimit import RateLimitMiddleware
from .routes import auth as r_auth, facts as r_facts, governance as r_gov, rules as r_rules
from .routes import integrations as r_int, submissions as r_subs, workspaces as r_ws
from .routes.auth import *  # noqa: F401,F403
from .routes.facts import *  # noqa: F401,F403
from .routes.governance import *  # noqa: F401,F403
from .routes.rules import *  # noqa: F401,F403
from .routes.rules import _store_guideline  # noqa: F401
from .routes.submissions import *  # noqa: F401,F403
from .routes.submissions import _carry_overrides, _create_submission, _ingest, _run_preflight, _save_pages, _submission  # noqa: F401
from .routes.workspaces import *  # noqa: F401,F403

app = FastAPI(title="BrandProof API", version="0.4.0",
              description="Pre-publication gate for brand-safe content. AI suggests; humans decide.")
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Retry-After"])
FIELD = {"title": "Title", "email": "Email", "password": "Password", "name": "Name", "key": "Key", "label": "Label",
         "value": "Value", "text": "Text", "file": "File", "decision": "Decision", "roles": "Roles", "nodes": "Selection"}


@app.exception_handler(RequestValidationError)
async def _friendly_422(request: Request, exc: RequestValidationError):
    """Turn framework validation errors into one readable sentence the UI can show as-is."""
    parts = []
    for e in exc.errors():
        loc = [str(x) for x in e.get("loc", []) if x not in ("body", "query", "path")]
        field = FIELD.get(loc[-1], loc[-1]) if loc else "Request"
        if e.get("type") == "missing":
            parts.append(f"{field} is required")
        elif e.get("type") == "json_invalid":
            parts.append("The request wasn't valid JSON")
        else:
            parts.append(f"{field} is not valid")
    return JSONResponse(status_code=422, content={"detail": "; ".join(dict.fromkeys(parts)) + "."})


for r in (r_auth, r_ws, r_rules, r_facts, r_subs, r_gov, r_int):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True, "ai": llm.status(), "ocr": ocr.engine(), "semantic": semantic.status(), "demo": DEMO,
            "db": "postgresql" + (" + pgvector" if db.HAS_VECTOR else "") if db.IS_PG else "sqlite",
            "checks": jobs.stats(), "email": mailer.provider() or "log only"}


@app.on_event("startup")
def _startup():
    if os.environ.get("BRANDPROOF_AUTOSEED", "1") == "1" and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        import sys
        from . import seed
        seed.seed(sys.modules[__name__])
    jobs.start()
