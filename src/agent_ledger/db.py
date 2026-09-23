from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

LANES = ("Backlog", "Ready", "Doing", "Blocked", "Done")
ROLES = ("planner", "consult", "worker")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  lane TEXT NOT NULL DEFAULT 'Backlog',
  status TEXT NOT NULL DEFAULT 'open',
  progress TEXT NOT NULL DEFAULT '',
  owner TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id TEXT,
  session TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id TEXT,
  body TEXT NOT NULL,
  raised_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  checked_at TEXT,
  resolution TEXT,
  closed_by TEXT,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  tag TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT '',
  pid INTEGER,
  started_at TEXT NOT NULL,
  ended_at TEXT
);
CREATE TABLE IF NOT EXISTS changelog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  session TEXT NOT NULL,
  table_name TEXT NOT NULL,
  row_id TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT
);
CREATE TABLE IF NOT EXISTS inbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  to_tag TEXT NOT NULL,
  from_tag TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'message',
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  read_at TEXT
);
CREATE TABLE IF NOT EXISTS day_plan (
  day TEXT NOT NULL,
  card_id TEXT NOT NULL,
  added_by TEXT NOT NULL,
  added_at TEXT NOT NULL,
  removed_at TEXT,
  PRIMARY KEY(day, card_id)
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inbox_unread ON inbox(to_tag, read_at);
CREATE INDEX IF NOT EXISTS idx_changelog_time ON changelog(created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_card ON decisions(card_id, closed_at);
"""


class Connection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return dt.date.today().isoformat()


def project_root(start: str | os.PathLike[str] | None = None) -> Path:
    override = os.environ.get("AGENT_LEDGER_PROJECT")
    current = Path(override or start or os.getcwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".agent-ledger").exists() or (candidate / ".git").exists():
            return candidate
    return current


def db_path(root: Path) -> Path:
    return root / ".agent-ledger" / "ledger.sqlite"


def connect(root: Path, *, create: bool = True, readonly: bool = False) -> sqlite3.Connection:
    path = db_path(root)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5, factory=Connection)
    else:
        con = sqlite3.connect(path, timeout=5, factory=Connection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
    return con


def initialize(root: Path) -> Path:
    with connect(root) as con:
        con.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','1')")
    return db_path(root)


def log_change(
    con: sqlite3.Connection,
    actor: str,
    table: str,
    row_id: str | int,
    field: str,
    old: object,
    new: object,
) -> None:
    con.execute(
        "INSERT INTO changelog(created_at,session,table_name,row_id,field,old_value,new_value) "
        "VALUES(?,?,?,?,?,?,?)",
        (now(), actor, table, str(row_id), field, _text(old), _text(new)),
    )


def _text(value: object) -> str | None:
    return None if value is None else str(value)
