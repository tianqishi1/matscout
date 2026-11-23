"""SQLite schema and connection helpers. Stdlib only; all data stays local."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    field TEXT,
    idea TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE,
    title TEXT NOT NULL,
    title_hash TEXT,
    abstract TEXT,
    year INTEGER,
    venue TEXT,
    authors_json TEXT,
    url TEXT,
    source TEXT,
    raw_json TEXT,
    retrieved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    verified INTEGER NOT NULL DEFAULT 0,
    verified_via TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_title_hash ON papers(title_hash);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    query TEXT NOT NULL,
    filters_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS search_results (
    search_id INTEGER NOT NULL REFERENCES searches(id),
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    rank INTEGER NOT NULL,
    PRIMARY KEY (search_id, paper_id)
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    content_json TEXT NOT NULL,
    paper_ids_json TEXT,
    actor TEXT NOT NULL DEFAULT 'matscout',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    verdict TEXT NOT NULL,
    confidence TEXT NOT NULL,
    summary TEXT NOT NULL,
    deltas_json TEXT NOT NULL,
    feasibility_json TEXT,
    risks_json TEXT,
    limitations TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS http_cache (
    key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""


def db_path() -> Path:
    env = os.environ.get("MATSCOUT_DB")
    if env:
        return Path(env)
    return Path.home() / ".matscout" / "matscout.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
