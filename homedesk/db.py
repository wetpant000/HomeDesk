"""SQLite storage: documents, complaint cases and their history."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    vendor          TEXT,
    item_name       TEXT,
    category        TEXT,
    amount          REAL,
    doc_date        TEXT,
    expiry_date     TEXT,
    warranty_months INTEGER,
    contact_email   TEXT,
    notes           TEXT,
    file_name       TEXT,
    needs_review    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id               INTEGER PRIMARY KEY,
    document_id      INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    issue            TEXT NOT NULL,
    status           TEXT NOT NULL,
    to_email         TEXT,
    subject          TEXT,
    body             TEXT,
    escalation_level INTEGER NOT NULL DEFAULT 0,
    follow_up_on     TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_events (
    id      INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    at      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    note    TEXT
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def row(cursor: sqlite3.Cursor) -> dict | None:
    r = cursor.fetchone()
    return dict(r) if r else None


@contextmanager
def session(path: Path | None = None):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()
