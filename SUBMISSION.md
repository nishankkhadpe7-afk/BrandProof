# BrandProof · Round 3 submission

Team false 9s · SIES Graduate School of Technology

| Item | Link / location |
| --- | --- |
| Final working project | https://brand-proof-three.vercel.app (one-click demo accounts; password `demo-pass-2026`) |
| Source code | https://github.com/nishankkhadpe7-afk/BrandProof |
| Final product PDF | `BrandProof_Round3.pdf` (in this repository) |
| API docs | https://brandproof-api-h2pc.onrender.com/docs |
| Run it locally | [README → Quick start](README.md#quick-start) |

---

## 1. Complete list of features

**Guidelines → rules (Engine A)**
- Paste guidelines or upload PDF (including scanned PDFs, via OCR), DOCX, TXT or Markdown
- 14 typed rule kinds (banned and preferred terms, tone, exclamations, claims needing evidence, disclaimers, sentence length, all caps, link text, alt text, palette, contrast, resolution), each linked to its source document and line
- Vague, untyped, incomplete and conflicting guidelines stay off until a person checks them; incomplete rules can't be switched on
- Claim topics extracted for any domain ("All caffeine claims…", "claims about protein, sugar or fibre…")
- Edit rule type and values; switch rules on or off

**Evidence ledger**
- Approved facts with value, unit, comparator (max / exact / wording), aliases, example paraphrases, ruled-out phrases, approved wording, source, owner and validity dates
- Expired facts and disagreeing sources detected automatically
- Add, edit, remove; "Test a claim" shows which fact a sentence matches and how it would be judged

**Checking content (Engine B)**
- Text, PDF, DOCX, PNG / JPG / WEBP
- Claim statuses: supported, contradicted, expired, conflicting, unverified (missing evidence is never "wrong")
- Exact numeric claims with unit conversion (days / weeks / months / years; mg, ml, kg, kcal, W, GB…), number words and negation handling
- Semantic evidence: paraphrased claims matched to facts and interpreted ("lasts all weekend" ≈ 48 h vs "up to 24 h")
- OCR: text in banners and scanned PDF pages checked with the same rules, problems boxed on the image
- Terms, tone, disclaimers, accessibility and visual checks (off-palette colours with nearest brand colour, contrast, resolution)
- Optional AI tone and claim checks (Gemini) with automatic model fallback; everything works without it
- Checks run in the background with retries; live "Checking…" status

**Review and governance**
- Accept a suggested fix, write your own, or override with a reason
- Apply fixes → new revision, re-checked automatically; overrides carry forward
- Upload a corrected creative as the next revision
- Approval blocked while any high or medium finding is open; decisions lock after approval
- Decision trail per item and an append-only activity log per workspace
- Insights: repeated mistakes, unclear guidelines (often overridden), missing evidence

**Accounts and platform**
- Email and password accounts, "keep me signed in", password reset by email
- Brand workspaces with roles per workspace (Creator, Reviewer, Brand owner, Admin), email invitations, last-admin protection, full isolation
- Figma plugin: check selected frames or text layers, show the layer, apply the fix in place, send to the review queue
- Rate limiting, upload validation, friendly error messages
- SQLite locally or PostgreSQL + pgvector in production
- Landing, privacy and terms pages; light and dark theme with animated logo; works on phones

## 2. Technical architecture and implementation summary

- **Frontend:** Next.js 15 / React 19 / TypeScript, deployed on Vercel. Session token in browser storage, workspace sent as `X-Workspace`.
- **Backend:** FastAPI (Python 3.12) in Docker on Render, with Tesseract installed. Routers per area (`routes/auth, workspaces, rules, facts, submissions, governance, integrations`); `core.py` handles identity, role checks and workspace scoping.
- **Engine A (`compiler.py`):** sentence → typed rule with parameters; ambiguity and conflict detection; required-parameter validation.
- **Engine B (`preflight.py`):** claim, term, tone, accessibility and visual checks; span overlap resolution; region mapping for OCR.
- **Semantic evidence (`semantic.py`):** offline embedder (word and character n-grams + concept lexicon + per-fact example paraphrases) always on; Gemini embeddings added when configured, cached and ranked by pgvector (`<=>`) in PostgreSQL. Paraphrases interpreted into the fact's unit, then compared with the same comparator, validity and conflict logic. Each finding carries a retrieval trace.
- **OCR (`ocr.py`):** Tesseract word boxes (two page-segmentation modes, confidence filter, upscaling); scanned PDF pages rendered and read; Gemini vision fallback.
- **Jobs (`jobs.py`):** durable job state on the submission row; worker thread; idempotent jobs; exponential-backoff retries; crash recovery on start.
- **Security:** PBKDF2 passwords; hashed session tokens with expiry; per-workspace roles on every write; per-client rate limits (429 + Retry-After); upload type, size and integrity checks; secrets only in environment variables.
- **Data:** SQLite or PostgreSQL (+ pgvector); every business row scoped by `workspace_id`; page images stored in the database (`blobs`) so they survive restarts.
- **Email (`mailer.py`):** Gmail API over HTTPS (Render's free tier blocks SMTP) or Resend; logs instead when unconfigured.

## 3. Improvements completed after Round 2

**The three we committed to, all delivered**
1. **Semantic evidence:** embedding retrieval (pgvector in PostgreSQL) plus paraphrase interpretation. Recall on paraphrased false claims rose from 0.33 to 0.90 on our 40-case set.
2. **OCR for creatives:** text in banners and scanned PDFs read with word boxes, checked with the same rules, and the region marked on the image.
3. **Accounts + workspaces:** email login, password reset, real users with roles per workspace, invitations, and isolated brand workspaces with their own activity logs.

**Round 2 open items closed:** PostgreSQL + pgvector support (was SQLite only) · background job queue (was synchronous) · real authentication (was a header role switcher) · OCR (was deferred) · tenant isolation (was planned) · benchmark run on real data (was proposed only) · creative revisions by upload (previously needed a new submission).

**Also added:** Figma plugin · email invitations · rate limiting · upload validation and readable errors · redesigned interface with dark mode and landing page · unit conversion, number words and negation · AI model fallback · rule topics for any domain.

**Changes to the plan:** pgvector is used when PostgreSQL is configured, with an in-process index on SQLite so the project runs with no database server; the queue is in-process on the submission row instead of Redis (one free Render service); email goes through the Gmail API because SMTP is blocked on Render's free tier. None of the three improvements was impossible.

## 4. Testing details

- **27 automated API tests** (`cd backend && pytest -q`), passing on SQLite and PostgreSQL + pgvector: accounts and isolation, invites, last-admin protection, password reset, evidence statuses, ambiguity gate, roles, approval gate, revise and re-check, semantic matching (including no false flags on approved wording), OCR on banners, scanned PDFs and uploads, corrected-file revisions, job idempotency and retry, background queue, rate limiting, upload limits and bad files, mailer, Figma endpoint, AI path (mocked).
- **Benchmark** (`python -m eval.semantic_eval --csv eval/kaggle_benchmark.csv`): 325 real sentences from public Kaggle datasets plus 40 paraphrases, hand-labelled with a written rule. Exact rules + semantic: F1 0.93 on paraphrases (exact rules alone: 0.50); on real copy F1 0.89 vs 0.92 for exact rules alone, with fact retrieval up from 0.50 to 0.65. Treated as a development set.
- **Scripted end-to-end journeys** in a browser: sign-up → empty workspace → guidelines → rules → fact → check (double-clicked) → refresh → fixes and overrides → approve; demo roles; banner, scanned PDF and paraphrase pages; theme switch; phone width.
- **Robustness run:** empty input, unsupported / corrupt / empty / oversized files, missing fields, malformed requests, unknown and other-workspace IDs, fake sessions, approving twice, deciding after approval, revising a superseded revision, repeated wrong passwords. All return a clear message; zero server errors.
- **Bugs found by testing and fixed:** mg / kcal units ignored; false flag on approved water-resistance wording; corrupt files accepted then failing later; raw validation errors shown; rule topics limited to the demo domain; retired AI model.

## 5. Product roadmap and future development plan

- **Next 3 months:** held-out benchmark (150+ new cases); pilots with 2–3 D2C brands and an agency (review time, claims caught); fact extraction from spec-sheet PDFs; Google Docs and Canva add-ons; publish the Figma plugin.
- **3–6 months:** industry rule packs (ASCI, FSSAI health claims, SEBI ads, green claims); Hindi, Tamil and Hinglish; video and audio (transcripts, on-screen text); publishing-gate API and webhooks.
- **6–12 months:** learning loop from overrides; cross-encoder reranker and fine-tuned verifier; SSO, SOC 2 groundwork, regional hosting; multi-instance queue and scaling.
- **Business model:** free solo plan; Team ₹3–5k per brand per month; Agency per seat; Enterprise (SSO, rule packs, API). First customers: Indian D2C brands and their agencies, starting with a free claim audit of their last 50 posts.
