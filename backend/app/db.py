"""SQLite storage. Swap for PostgreSQL + pgvector in production (see README)."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.environ.get("BRANDPROOF_DB", os.path.join(os.path.dirname(__file__), "..", "brandproof.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
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
  source_id INTEGER REFERENCES sources(id),
  type TEXT NOT NULL,
  category TEXT NOT NULL,          -- claim | tone | term | visual | accessibility | other
  params TEXT NOT NULL DEFAULT '{}',
  severity TEXT NOT NULL DEFAULT 'medium',
  text TEXT NOT NULL,              -- original guideline sentence
  location TEXT,                   -- e.g. "line 12"
  status TEXT NOT NULL DEFAULT 'proposed',  -- proposed | active | rejected
  ambiguity TEXT NOT NULL DEFAULT '[]',
  engine TEXT NOT NULL DEFAULT 'deterministic',
  validated_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL,
  label TEXT NOT NULL,
  value TEXT NOT NULL,
  numeric REAL,
  unit TEXT,
  comparator TEXT NOT NULL DEFAULT 'exact',  -- max | min | exact | text
  aliases TEXT NOT NULL DEFAULT '[]',
  disallowed TEXT NOT NULL DEFAULT '[]',     -- phrases this fact contradicts
  approved_phrasing TEXT,
  source_id INTEGER REFERENCES sources(id),
  source_ref TEXT,
  owner TEXT,
  scope TEXT,
  valid_from TEXT,
  valid_to TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  channel TEXT,
  author TEXT,
  kind TEXT NOT NULL,              -- text | pdf | docx | image
  filename TEXT,
  text TEXT NOT NULL DEFAULT '',
  alt_text TEXT,
  image_meta TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  parent_id INTEGER,
  status TEXT NOT NULL DEFAULT 'in_review',  -- in_review | approved | rejected | changes_requested | superseded
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  category TEXT NOT NULL,
  status TEXT NOT NULL,            -- supported | contradicted | expired | conflicting | unverified | violation
  severity TEXT NOT NULL,
  start INTEGER, "end" INTEGER,
  region TEXT,                     -- image bbox json
  excerpt TEXT,
  rule_id INTEGER, fact_id INTEGER,
  reason TEXT NOT NULL,
  suggestion TEXT,
  source_ref TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  engine TEXT NOT NULL DEFAULT 'deterministic',
  decision TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | edited | overridden
  decision_text TEXT,
  decision_reason TEXT,
  decided_by TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  role TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  detail TEXT NOT NULL DEFAULT '{}'
);
"""

JSON_COLS = {"params", "ambiguity", "aliases", "disallowed", "detail", "region", "image_meta"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


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


def insert(conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> int:
    data = {k: (json.dumps(v) if k in JSON_COLS and not isinstance(v, str) and v is not None else v) for k, v in data.items()}
    cols = ", ".join(f'"{c}"' for c in data)
    qs = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(data.values()))
    conn.commit()
    return cur.lastrowid


def update(conn: sqlite3.Connection, table: str, id_: int, data: dict[str, Any]) -> None:
    data = {k: (json.dumps(v) if k in JSON_COLS and not isinstance(v, str) and v is not None else v) for k, v in data.items()}
    sets = ", ".join(f'"{c}" = ?' for c in data)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), id_])
    conn.commit()


def audit(conn: sqlite3.Connection, actor: str, role: str, action: str, entity: str, entity_id: int | None, detail: dict | None = None) -> None:
    insert(conn, "audit", {"ts": now(), "actor": actor, "role": role, "action": action,
                           "entity": entity, "entity_id": entity_id, "detail": detail or {}})
