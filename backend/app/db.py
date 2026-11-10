"""Storage, scoped per brand workspace. Every business table carries a workspace_id.

Backends (same code path, same SQL):
  * SQLite                 default, local dev and tests
  * PostgreSQL + pgvector  set DATABASE_URL=postgresql://...  (Neon, Supabase, Render Postgres)
                           fact embeddings go in a pgvector column and are ranked in SQL (<=>).
Uploaded page images live in the `blobs` table, so they persist with the database.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.environ.get("BRANDPROOF_DB", os.path.join(os.path.dirname(__file__), "..", "brandproof.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
HAS_VECTOR = False  # set by init() when the pgvector extension is available

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS password_resets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE IF NOT EXISTS workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  brand TEXT,
  color TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  roles TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE(workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS invitations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  email TEXT NOT NULL,
  roles TEXT NOT NULL DEFAULT '[]',
  invited_by TEXT,
  created_at TEXT NOT NULL,
  accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL,              -- guideline | fact_sheet | asset
  name TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT 'v1',
  filename TEXT,
  text TEXT,
  owner TEXT,
  uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL DEFAULT 1,
  source_id INTEGER REFERENCES sources(id),
  type TEXT NOT NULL,
  category TEXT NOT NULL,
  params TEXT NOT NULL DEFAULT '{}',
  severity TEXT NOT NULL DEFAULT 'medium',
  text TEXT NOT NULL,
  location TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  ambiguity TEXT NOT NULL DEFAULT '[]',
  engine TEXT NOT NULL DEFAULT 'deterministic',
  validated_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL DEFAULT 1,
  key TEXT NOT NULL,
  label TEXT NOT NULL,
  value TEXT NOT NULL,
  numeric REAL,
  unit TEXT,
  comparator TEXT NOT NULL DEFAULT 'exact',
  aliases TEXT NOT NULL DEFAULT '[]',
  disallowed TEXT NOT NULL DEFAULT '[]',
  examples TEXT NOT NULL DEFAULT '[]',       -- paraphrases that should retrieve this fact
  approved_phrasing TEXT,
  source_id INTEGER REFERENCES sources(id),
  source_ref TEXT,
  owner TEXT,
  scope TEXT,
  valid_from TEXT,
  valid_to TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_vectors (
  fact_id INTEGER NOT NULL,
  model TEXT NOT NULL,
  vector TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (fact_id, model)
);
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  channel TEXT,
  author TEXT,
  kind TEXT NOT NULL,
  filename TEXT,
  text TEXT NOT NULL DEFAULT '',
  alt_text TEXT,
  image_meta TEXT,
  ocr TEXT,                        -- {"engine", "words":[{start,end,x,y,w,h,page,img_w,img_h}]}
  pages INTEGER NOT NULL DEFAULT 0, -- stored page/region images
  check_status TEXT NOT NULL DEFAULT 'done',  -- queued | running | done | failed (background job state)
  check_error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  ingested INTEGER NOT NULL DEFAULT 1,       -- 0 = uploaded file not yet extracted/OCR'd
  revision INTEGER NOT NULL DEFAULT 1,
  parent_id INTEGER,
  status TEXT NOT NULL DEFAULT 'in_review',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  category TEXT NOT NULL,
  status TEXT NOT NULL,
  severity TEXT NOT NULL,
  start INTEGER, "end" INTEGER,
  region TEXT,
  excerpt TEXT,
  rule_id INTEGER, fact_id INTEGER,
  reason TEXT NOT NULL,
  suggestion TEXT,
  source_ref TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  engine TEXT NOT NULL DEFAULT 'deterministic',
  match TEXT,                      -- semantic retrieval trace
  decision TEXT NOT NULL DEFAULT 'pending',
  decision_text TEXT,
  decision_reason TEXT,
  decided_by TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  role TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS blobs (
  name TEXT PRIMARY KEY,
  data BLOB NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rules_ws ON rules(workspace_id, status);
CREATE INDEX IF NOT EXISTS ix_facts_ws ON facts(workspace_id);
CREATE INDEX IF NOT EXISTS ix_subs_ws ON submissions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_audit_ws ON audit(workspace_id);
"""

# columns added in Round 3, applied to older databases in place
MIGRATIONS = [
    ("sources", "workspace_id", "INTEGER NOT NULL DEFAULT 1"),
    ("rules", "workspace_id", "INTEGER NOT NULL DEFAULT 1"),
    ("facts", "workspace_id", "INTEGER NOT NULL DEFAULT 1"),
    ("facts", "examples", "TEXT NOT NULL DEFAULT '[]'"),
    ("submissions", "workspace_id", "INTEGER NOT NULL DEFAULT 1"),
    ("submissions", "ocr", "TEXT"),
    ("submissions", "pages", "INTEGER NOT NULL DEFAULT 0"),
    ("findings", "match", "TEXT"),
    ("submissions", "check_status", "TEXT NOT NULL DEFAULT 'done'"),
    ("submissions", "check_error", "TEXT"),
    ("submissions", "attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("submissions", "ingested", "INTEGER NOT NULL DEFAULT 1"),
    ("audit", "workspace_id", "INTEGER"),
]

JSON_COLS = {"params", "ambiguity", "aliases", "disallowed", "examples", "detail", "region", "image_meta",
             "ocr", "roles", "match"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Row(dict):
    """dict row that also supports positional access, like sqlite3.Row."""
    def __getitem__(self, k):
        return list(self.values())[k] if isinstance(k, int) else super().__getitem__(k)


def _row_factory(cursor):
    names = [d.name for d in cursor.description] if cursor.description else []
    return lambda values: _Row(zip(names, values))


class PgConn:
    """Minimal sqlite3-compatible wrapper over psycopg 3 (thread-safe, auto-reconnect)."""
    is_pg = True

    def __init__(self, url: str):
        self.url = url
        self.lock = threading.RLock()
        self._open()

    def _open(self):
        import psycopg
        self.c = psycopg.connect(self.url, autocommit=True, row_factory=_row_factory)

    def execute(self, sql: str, params=()):
        import psycopg
        sql = sql.replace("?", "%s")
        with self.lock:
            for attempt in (0, 1):
                try:
                    cur = self.c.cursor()
                    cur.execute(sql, list(params) if params else None)
                    return cur
                except psycopg.OperationalError:
                    if attempt:
                        raise
                    self._open()  # managed Postgres drops idle connections

    def commit(self):
        pass

    def executescript(self, script: str):
        with self.lock:
            self.c.execute(script)


def connect():
    if IS_PG:
        return PgConn(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _pg_schema() -> str:
    return (SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            .replace(" REAL", " DOUBLE PRECISION").replace("data BLOB", "data BYTEA"))


def init(conn) -> None:
    global HAS_VECTOR
    if getattr(conn, "is_pg", False):
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            pass
        HAS_VECTOR = bool(conn.execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone())
        conn.executescript(_pg_schema())
        for table, col, decl in MIGRATIONS:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {decl.replace(' REAL', ' DOUBLE PRECISION')}")
        if HAS_VECTOR:
            conn.execute("ALTER TABLE fact_vectors ADD COLUMN IF NOT EXISTS embedding vector")
        return
    for table, col, decl in MIGRATIONS:
        exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists and col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.executescript(SCHEMA)
    conn.commit()


TABLES = ["password_resets", "findings", "submissions", "facts", "fact_vectors", "rules", "sources", "audit", "blobs",
          "invitations", "memberships", "sessions", "workspaces", "users"]


def drop_all(conn) -> None:
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t}" + (" CASCADE" if getattr(conn, "is_pg", False) else ""))
    conn.commit()


def put_blob(conn, name: str, data: bytes) -> None:
    conn.execute("INSERT INTO blobs (name, data, created_at) VALUES (?,?,?) "
                 "ON CONFLICT (name) DO UPDATE SET data=excluded.data", (name, data, now()))
    conn.commit()


def get_blob(conn, name: str) -> bytes | None:
    r = conn.execute("SELECT data FROM blobs WHERE name=?", (name,)).fetchone()
    return bytes(r["data"]) if r else None


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def _enc(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (json.dumps(v) if k in JSON_COLS and not isinstance(v, str) and v is not None else v) for k, v in data.items()}


def insert(conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> int:
    data = _enc(data)
    cols = ", ".join(f'"{c}"' for c in data)
    qs = ", ".join("?" for _ in data)
    if getattr(conn, "is_pg", False):
        return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs}) RETURNING id", list(data.values())).fetchone()["id"]
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(data.values()))
    conn.commit()
    return cur.lastrowid


def update(conn: sqlite3.Connection, table: str, id_: int, data: dict[str, Any]) -> None:
    data = _enc(data)
    sets = ", ".join(f'"{c}" = ?' for c in data)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), id_])
    conn.commit()


def audit(conn: sqlite3.Connection, actor: str, role: str, action: str, entity: str, entity_id: int | None,
          detail: dict | None = None, workspace_id: int | None = None) -> None:
    insert(conn, "audit", {"workspace_id": workspace_id, "ts": now(), "actor": actor, "role": role, "action": action,
                           "entity": entity, "entity_id": entity_id, "detail": detail or {}})
