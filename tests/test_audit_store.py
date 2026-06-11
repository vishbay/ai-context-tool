"""Tests for cram/audit_store.py — the SQLite event-store cache."""

from __future__ import annotations
import json
import os
import sqlite3

from cram import audit_events
from cram.audit_store import AuditStore, SCHEMA_VERSION, resolve_db_path
from tests.test_audit import _make_transcript


def _parse(path):
    parsed = audit_events.parse_claude(path)
    assert parsed is not None
    return parsed


def _ingest_claude(store, path):
    meta, events = _parse(path)
    st = os.stat(path)
    store.replace_file(path, 'claude', st.st_mtime, st.st_size, [(meta, events)])


class TestResolveDbPath:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv('CRAM_AUDIT_DB', '/tmp/custom.db')
        assert resolve_db_path() == '/tmp/custom.db'

    def test_memory_accepted(self, monkeypatch):
        monkeypatch.setenv('CRAM_AUDIT_DB', ':memory:')
        assert resolve_db_path() == ':memory:'

    def test_xdg_data_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv('CRAM_AUDIT_DB', raising=False)
        monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
        assert resolve_db_path() == str(tmp_path / 'cram-ai' / 'audit.db')

    def test_default_under_local_share(self, monkeypatch):
        monkeypatch.delenv('CRAM_AUDIT_DB', raising=False)
        monkeypatch.delenv('XDG_DATA_HOME', raising=False)
        path = resolve_db_path()
        assert path.endswith(os.path.join('cram-ai', 'audit.db'))
        assert '.local' in path


class TestRoundtrip:
    def test_events_survive_storage(self, tmp_path):
        transcript = _make_transcript([
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'a.py'}),
            ('Bash', {'command': 'grep -n def a.py'}),
            ('Edit', {'file_path': 'a.py'}),
        ], tmp_path)
        meta, events = _parse(transcript)
        direct = audit_events.derive_session(meta, events, big_result_bytes=20_000)

        store = AuditStore.open(str(tmp_path / 'cache.db'))
        _ingest_claude(store, transcript)
        sessions = store.sessions_for_file(transcript)
        assert len(sessions) == 1
        sid, stored_meta = sessions[0]
        replayed = audit_events.derive_session(
            stored_meta, store.events_for_session(sid), big_result_bytes=20_000)
        assert replayed == direct
        store.close()

    def test_extras_and_token_fields_roundtrip(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        with open(path, 'w') as f:
            f.write(json.dumps({'usage': {'cache_creation_input_tokens': 5,
                                          'cache_read_input_tokens': 7,
                                          'input_tokens': 3,
                                          'output_tokens': 11}}) + '\n')
            f.write(json.dumps({'type': 'tool_result', 'content': 'x' * 30_000,
                                'is_error': True}) + '\n')
        meta, events = _parse(path)
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        _ingest_claude(store, path)
        sid, _ = store.sessions_for_file(path)[0]
        assert store.events_for_session(sid) == events
        store.close()

    def test_replace_is_idempotent(self, tmp_path):
        transcript = _make_transcript([('Read', {})], tmp_path)
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        _ingest_claude(store, transcript)
        _ingest_claude(store, transcript)
        assert len(store.sessions_for_file(transcript)) == 1
        store.close()


class TestLedger:
    def test_new_file_needs_ingest(self, tmp_path):
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        assert store.needs_ingest('/nope.jsonl', 1.0, 10)
        store.close()

    def test_ingested_file_is_cached(self, tmp_path):
        transcript = _make_transcript([('Read', {})], tmp_path)
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        _ingest_claude(store, transcript)
        st = os.stat(transcript)
        assert not store.needs_ingest(transcript, st.st_mtime, st.st_size)
        store.close()

    def test_changed_file_needs_reingest(self, tmp_path):
        transcript = _make_transcript([('Read', {})], tmp_path)
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        _ingest_claude(store, transcript)
        st = os.stat(transcript)
        assert store.needs_ingest(transcript, st.st_mtime + 5, st.st_size)
        assert store.needs_ingest(transcript, st.st_mtime, st.st_size + 100)
        store.close()

    def test_failed_parse_retried_and_keeps_old_snapshot(self, tmp_path):
        transcript = _make_transcript([('Read', {})], tmp_path)
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        _ingest_claude(store, transcript)
        st = os.stat(transcript)
        store.mark_failed(transcript, 'claude', st.st_mtime, st.st_size)
        # previous good sessions remain queryable…
        assert len(store.sessions_for_file(transcript)) == 1
        # …and the file is retried on the next run
        assert store.needs_ingest(transcript, st.st_mtime, st.st_size)
        store.close()

    def test_persists_across_reopen(self, tmp_path):
        transcript = _make_transcript([('Read', {})], tmp_path)
        db = str(tmp_path / 'cache.db')
        store = AuditStore.open(db)
        _ingest_claude(store, transcript)
        store.close()
        store2 = AuditStore.open(db)
        st = os.stat(transcript)
        assert not store2.needs_ingest(transcript, st.st_mtime, st.st_size)
        assert len(store2.sessions_for_file(transcript)) == 1
        store2.close()


class TestInvalidation:
    def test_corrupt_db_rebuilt_never_raises(self, tmp_path):
        db = str(tmp_path / 'cache.db')
        with open(db, 'w') as f:
            f.write('this is not a sqlite database, not even close — padding ' * 50)
        store = AuditStore.open(db)
        assert not store.ephemeral  # corrupt file was deleted and rebuilt
        transcript = _make_transcript([('Read', {})], tmp_path)
        _ingest_claude(store, transcript)
        assert len(store.sessions_for_file(transcript)) == 1
        store.close()

    def test_unopenable_path_falls_back_to_memory(self, tmp_path, capsys):
        store = AuditStore.open(str(tmp_path))  # a directory, not a file
        assert store.ephemeral
        transcript = _make_transcript([('Read', {})], tmp_path)
        _ingest_claude(store, transcript)
        assert len(store.sessions_for_file(transcript)) == 1
        assert 'cache unavailable' in capsys.readouterr().err
        store.close()

    def test_schema_version_bump_rebuilds(self, tmp_path):
        db = str(tmp_path / 'cache.db')
        transcript = _make_transcript([('Read', {})], tmp_path)
        store = AuditStore.open(db)
        _ingest_claude(store, transcript)
        store.close()
        con = sqlite3.connect(db)
        con.execute('PRAGMA user_version = 999')
        con.commit()
        con.close()
        store2 = AuditStore.open(db)
        assert store2.sessions_for_file(transcript) == []
        st = os.stat(transcript)
        assert store2.needs_ingest(transcript, st.st_mtime, st.st_size)
        store2.close()

    def test_parser_fingerprint_change_rebuilds(self, tmp_path):
        db = str(tmp_path / 'cache.db')
        transcript = _make_transcript([('Read', {})], tmp_path)
        store = AuditStore.open(db)
        _ingest_claude(store, transcript)
        store.close()
        con = sqlite3.connect(db)
        con.execute("UPDATE meta SET value = 'stale' WHERE key = 'parser_fingerprint'")
        con.commit()
        con.close()
        store2 = AuditStore.open(db)
        assert store2.sessions_for_file(transcript) == []
        store2.close()


class TestCursorDbSessions:
    def test_multiple_sessions_per_file_no_duplicates(self, tmp_path):
        from cram.audit_events import SessionMeta
        store = AuditStore.open(str(tmp_path / 'cache.db'))
        vscdb = str(tmp_path / 'state.vscdb')
        open(vscdb, 'w').close()
        metas = [
            (SessionMeta('cursor-db', 'cursor', vscdb, 100.0,
                         event_mtime=100.0, external_id='c1'), []),
            (SessionMeta('cursor-db', 'cursor', vscdb, 200.0,
                         event_mtime=200.0, external_id='c2'), []),
        ]
        store.replace_file(vscdb, 'cursor-db', 1.0, 0, metas)
        store.replace_file(vscdb, 'cursor-db', 2.0, 0, metas)  # wholesale replace
        sessions = store.sessions_for_file(vscdb)
        assert len(sessions) == 2
        assert {m.external_id for _, m in sessions} == {'c1', 'c2'}
        store.close()
