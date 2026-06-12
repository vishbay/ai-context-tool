"""Local SQLite cache of normalized audit events (see cram.audit_events).

The store is a cache, never precious data: any schema or parser change drops
and rebuilds it, and any open failure degrades to an ephemeral in-memory
store rather than crashing the audit. Raw transcripts on disk remain the
source of truth.

Invalidation has two triggers:
- SCHEMA_VERSION (PRAGMA user_version) for DDL changes;
- a parser fingerprint (hash of audit_events.py source) stored in the meta
  table, so classification/parsing changes rebuild the cache without anyone
  having to remember a version bump.
"""

from __future__ import annotations
import functools
import hashlib
import json
import os
import sqlite3
import sys
import time

from cram import audit_events
from cram.audit_events import Event, SessionMeta

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE files (
  path        TEXT PRIMARY KEY,
  adapter     TEXT NOT NULL,
  mtime       REAL NOT NULL,
  size        INTEGER NOT NULL,
  ingested_at REAL NOT NULL,
  parse_ok    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE sessions (
  id          INTEGER PRIMARY KEY,
  file_path   TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  adapter     TEXT NOT NULL,
  source      TEXT NOT NULL,
  external_id TEXT NOT NULL DEFAULT '',
  repo_key    TEXT,
  cwd         TEXT,
  mtime       REAL NOT NULL,
  event_mtime REAL,
  UNIQUE (file_path, external_id)
);
CREATE INDEX idx_sessions_file ON sessions(file_path);
CREATE TABLE events (
  session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  kind            TEXT NOT NULL,
  tool            TEXT,
  file_path       TEXT,
  bytes           INTEGER,
  is_error        INTEGER NOT NULL DEFAULT 0,
  tok_input       INTEGER,
  tok_output      INTEGER,
  tok_cache_read  INTEGER,
  tok_cache_write INTEGER,
  extras          TEXT,
  PRIMARY KEY (session_id, seq)
) WITHOUT ROWID;
CREATE INDEX idx_events_filepath ON events(file_path) WHERE file_path IS NOT NULL;
"""


def resolve_db_path() -> str:
    """Audit-cache location: $CRAM_AUDIT_DB > $XDG_DATA_HOME > ~/.local/share.

    ':memory:' is accepted (useful for tests). Config stays under
    ~/.config/cram-ai/; this is regenerable data, so it lives in the data dir.
    """
    env = os.environ.get('CRAM_AUDIT_DB')
    if env:
        return env
    xdg = os.environ.get('XDG_DATA_HOME')
    base = xdg or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, 'cram-ai', 'audit.db')


@functools.cache  # constant for the process; spare re-hashing on every open
def _parser_fingerprint() -> str:
    try:
        with open(audit_events.__file__, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        digest = 'unknown'
    return f'{SCHEMA_VERSION}:{digest}'


class AuditStore:
    """Ingestion ledger + normalized event storage. Never raises on open."""

    def __init__(self, con: sqlite3.Connection, path: str, ephemeral: bool = False):
        self.con = con
        self.path = path
        self.ephemeral = ephemeral
        # Paths whose parse failed during THIS run (mark_failed calls), so the
        # CLI can warn that the numbers may be incomplete. The parse_ok column
        # is the persistent retry ledger; this is just the per-run view.
        self.run_failures: list[str] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    def open(cls, path: str | None = None) -> 'AuditStore':
        path = path or resolve_db_path()
        if path != ':memory:':
            try:
                os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            except Exception:
                pass
        try:
            return cls._open_at(path)
        except Exception as e:
            # A corrupt cache file is safe to delete and rebuild; anything else
            # (locked, unwritable, weird FS) degrades to in-memory for this run.
            if path != ':memory:' and isinstance(e, sqlite3.DatabaseError):
                msg = str(e).lower()
                if 'malformed' in msg or 'not a database' in msg:
                    try:
                        os.remove(path)
                        return cls._open_at(path)
                    except Exception:
                        pass
        store = cls._open_at(':memory:')
        store.ephemeral = True
        print(f'cram audit: cache unavailable at {path}; '
              f'running without a persistent cache this time', file=sys.stderr)
        return store

    @classmethod
    def _open_at(cls, path: str) -> 'AuditStore':
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA busy_timeout = 5000')
        if path != ':memory:':
            con.execute('PRAGMA journal_mode = WAL')
        con.execute('PRAGMA synchronous = NORMAL')
        con.execute('PRAGMA foreign_keys = ON')

        fingerprint = _parser_fingerprint()
        version = con.execute('PRAGMA user_version').fetchone()[0]
        stored_fp = None
        if version == SCHEMA_VERSION:
            try:
                row = con.execute(
                    "SELECT value FROM meta WHERE key = 'parser_fingerprint'"
                ).fetchone()
                stored_fp = row[0] if row else None
            except sqlite3.OperationalError:
                stored_fp = None

        if version != SCHEMA_VERSION or stored_fp != fingerprint:
            con.executescript(
                'DROP TABLE IF EXISTS events;'
                'DROP TABLE IF EXISTS sessions;'
                'DROP TABLE IF EXISTS files;'
                'DROP TABLE IF EXISTS meta;'
            )
            con.executescript(_DDL)
            con.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            con.execute('INSERT INTO meta VALUES (?, ?)',
                        ('parser_fingerprint', fingerprint))
            con.commit()
        return cls(con, path)

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass

    # ── ingestion ledger ──────────────────────────────────────────────────────

    def needs_ingest(self, path: str, mtime: float, size: int) -> bool:
        row = self.con.execute(
            'SELECT mtime, size, parse_ok FROM files WHERE path = ?', (path,)
        ).fetchone()
        if row is None:
            return True
        # parse_ok=0 means the last attempt failed (e.g. locked vscdb): keep
        # retrying every run, exactly like the cacheless legacy behavior.
        return (not row['parse_ok']
                or row['mtime'] != mtime or row['size'] != size)

    def replace_file(self, path: str, adapter: str, mtime: float, size: int,
                     parsed: list[tuple[SessionMeta, list[Event]]]) -> None:
        """Replace a file's snapshot wholesale (transcripts are append-only)."""
        with self.con:
            self.con.execute('DELETE FROM files WHERE path = ?', (path,))
            self.con.execute(
                'INSERT INTO files VALUES (?, ?, ?, ?, ?, 1)',
                (path, adapter, mtime, size, time.time()))
            for meta, events in parsed:
                cur = self.con.execute(
                    'INSERT INTO sessions (file_path, adapter, source, external_id,'
                    ' repo_key, cwd, mtime, event_mtime)'
                    ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (path, meta.adapter, meta.source, meta.external_id or '',
                     None, meta.cwd, meta.mtime, meta.event_mtime))
                sid = cur.lastrowid
                self.con.executemany(
                    'INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    [(sid, ev.seq, ev.kind, ev.tool, ev.file_path, ev.bytes,
                      1 if ev.is_error else 0,
                      ev.tok_input, ev.tok_output,
                      ev.tok_cache_read, ev.tok_cache_write,
                      json.dumps(ev.extras) if ev.extras is not None else None)
                     for ev in events])

    def mark_failed(self, path: str, adapter: str, mtime: float, size: int) -> None:
        """Record a failed parse without discarding any previous good snapshot."""
        self.run_failures.append(path)
        with self.con:
            self.con.execute(
                'INSERT INTO files VALUES (?, ?, ?, ?, ?, 0)'
                ' ON CONFLICT(path) DO UPDATE SET parse_ok = 0',
                (path, adapter, mtime, size, time.time()))

    # ── queries ───────────────────────────────────────────────────────────────

    def sessions_for_file(self, path: str) -> list[tuple[int, SessionMeta]]:
        rows = self.con.execute(
            'SELECT id, adapter, source, external_id, cwd, mtime, event_mtime'
            ' FROM sessions WHERE file_path = ? ORDER BY id', (path,)
        ).fetchall()
        return [
            (r['id'], SessionMeta(
                adapter=r['adapter'], source=r['source'], path=path,
                mtime=r['mtime'], event_mtime=r['event_mtime'],
                external_id=r['external_id'] or None, cwd=r['cwd']))
            for r in rows
        ]

    def events_for_session(self, session_id: int) -> list[Event]:
        rows = self.con.execute(
            'SELECT * FROM events WHERE session_id = ? ORDER BY seq',
            (session_id,)
        ).fetchall()
        return [
            Event(seq=r['seq'], kind=r['kind'], tool=r['tool'],
                  file_path=r['file_path'], bytes=r['bytes'],
                  is_error=bool(r['is_error']),
                  tok_input=r['tok_input'], tok_output=r['tok_output'],
                  tok_cache_read=r['tok_cache_read'],
                  tok_cache_write=r['tok_cache_write'],
                  extras=json.loads(r['extras']) if r['extras'] is not None else None)
            for r in rows
        ]
