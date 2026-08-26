from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = [
    """
    CREATE TABLE users (
      id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
      password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
      active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
    );
    CREATE TABLE invites (
      token_hash TEXT PRIMARY KEY, created_by TEXT NOT NULL REFERENCES users(id),
      expires_at TEXT NOT NULL, used_at TEXT, used_by TEXT REFERENCES users(id)
    );
    CREATE TABLE sessions (
      token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE login_attempts (
      identity TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_started TEXT NOT NULL,
      blocked_until TEXT
    );
    CREATE TABLE lists (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
      region TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE list_acl (
      list_id TEXT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      role TEXT NOT NULL CHECK(role IN ('viewer', 'editor')),
      PRIMARY KEY(list_id, user_id)
    );
    CREATE TABLE list_items (
      id TEXT PRIMARY KEY, list_id TEXT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
      product_id TEXT NOT NULL, variant_id TEXT, quantity INTEGER NOT NULL CHECK(quantity > 0),
      notes TEXT NOT NULL DEFAULT '', captured_price TEXT, captured_currency TEXT,
      captured_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE(list_id, product_id, variant_id)
    );
    CREATE INDEX sessions_user ON sessions(user_id);
    CREATE INDEX list_items_list ON list_items(list_id);
    """
]


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
    finally:
        connection.close()


def migrate(path: Path) -> int:
    with connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        for index, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            with connection:
                connection.executescript(migration)
                connection.execute(f"PRAGMA user_version = {index}")
        return len(MIGRATIONS)
