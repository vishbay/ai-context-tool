"""Parity tests: current audit pipeline vs the frozen legacy implementation.

tests/legacy_audit_reference.py is a verbatim copy of cram/audit.py as it was
before the event-store refactor.

Policy: **legacy metrics are frozen, new metrics are additive.** Every key the
legacy implementation returns must be present in the current output with an
exactly-equal value (including None semantics and the
claude-has-no-'source'-key asymmetry); keys that only exist in the current
output are new, deliberately-added metrics and are tested in their own suites
(e.g. tests/test_audit_measured.py). Delete the reference copy only once the
pre-pivot numbers no longer need pinning.
"""

from __future__ import annotations
import datetime
import json
import math
import sqlite3

import pytest

import cram
import cram.audit as current
import tests.legacy_audit_reference as legacy
from tests.test_audit import (
    _make_transcript, _write_cursor_jsonl, _write_codex_jsonl,
    _exec_cmd, _apply_patch, _token_count,
)


def test_frozen_oracle_removal_trigger():
    """Fails once the oracle's removal trigger passes, so it can't linger.

    tests/legacy_audit_reference.py (1,100+ lines) is scheduled for deletion
    after the P0 analysis completes or v0.5.0 ships, whichever comes first —
    see https://github.com/vishbay/cram-ai/issues/9. The date is a backstop in
    case neither lands.
    """
    version = tuple(int(p) for p in cram.__version__.split('.')[:2])
    backstop = datetime.date(2026, 9, 30)
    if version >= (0, 5) or datetime.date.today() > backstop:
        pytest.fail(
            'Removal trigger for tests/legacy_audit_reference.py has passed: '
            'delete the frozen oracle and this parity suite (issue #9), or '
            'consciously re-pin with a new trigger.')
    pytest.skip('placeholder — fails after v0.5.0 or 2026-09-30 '
                'to force frozen-oracle removal (issue #9)')


def _deep_equal(a, b, path='$'):
    """Frozen-keys equality: every key/value of `a` (legacy) must appear in `b`
    with an equal value; extra keys in `b` are allowed (additive metrics).
    Floats compare with tolerance (guards summation-order drift)."""
    if isinstance(a, float) or isinstance(b, float):
        assert a is not None and b is not None, (path, a, b)
        assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), (path, a, b)
    elif isinstance(a, dict):
        assert isinstance(b, dict) and set(a) <= set(b), (path, a, b)
        for k in a:
            _deep_equal(a[k], b[k], f'{path}.{k}')
    elif isinstance(a, (list, tuple)):
        assert isinstance(b, (list, tuple)) and len(a) == len(b), (path, a, b)
        for i, (x, y) in enumerate(zip(a, b)):
            _deep_equal(x, y, f'{path}[{i}]')
    else:
        assert a == b, (path, a, b)


def _assert_frozen(old, new):
    """Session-dict parity under the frozen-keys policy. Handles None and lists."""
    if old is None or new is None:
        assert old is None and new is None, (old, new)
        return new
    if isinstance(old, list):
        assert isinstance(new, list) and len(old) == len(new), (old, new)
        for o, n in zip(old, new):
            _assert_frozen(o, n)
        return new
    _deep_equal(old, new)
    return new


def _write_raw(path, messages):
    with open(path, 'w') as f:
        for msg in messages:
            f.write(json.dumps(msg) + '\n')


def _usage(cache_read=0, input_tokens=0, cache_write=0, output_tokens=0):
    return {'usage': {'cache_creation_input_tokens': cache_write,
                      'cache_read_input_tokens': cache_read,
                      'input_tokens': input_tokens,
                      'output_tokens': output_tokens}}


def _assert_parity_claude(path):
    old = legacy._analyze_transcript(path)
    new = current._analyze_transcript(path)
    _assert_frozen(old, new)
    if old is not None:
        assert 'source' not in new  # claude dicts must not grow a source key
    return new


class TestClaudeParity:
    def test_basic_reads_edits(self, tmp_path):
        path = _make_transcript([
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'b.py'}),
            ('Bash', {'command': 'grep -n def a.py'}),
            ('Bash', {'command': 'python run.py'}),       # not a read
            ('Edit', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'a.py'}),              # after first edit
            ('Edit', {'file_path': 'a.py'}),
            ('Write', {'file_path': 'c.py'}),
            ('Edit', {}),                                  # no file_path
        ], tmp_path)
        r = _assert_parity_claude(path)
        assert r['reads'] == 5 and r['edits'] == 4

    def test_usage_and_big_results_interleaved(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        big = {'type': 'tool_result', 'content': 'x' * 30_000}
        msgs = ([_usage(cache_read=10_000, cache_write=500)] * 2
                + [big]
                + [_usage(cache_read=20_000, input_tokens=100)] * 4
                + [{'type': 'tool_result', 'content': 'small'}]
                + [{'type': 'tool_result', 'content': 'boom', 'is_error': True}]
                + [_usage(cache_read=30_000)])
        _write_raw(path, msgs)
        r = _assert_parity_claude(path)
        assert r['big_results'] == 1 and r['error_results'] == 1
        assert r['requests'] == 7 and r['carried_read_tokens'] > 0

    def test_tool_use_and_result_same_line(self, tmp_path):
        # usage + tool_use + tool_result nested inside one message: per-line
        # processing order (tool_use, usage, results) must be preserved.
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [
            {'message': {
                'content': [
                    {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}},
                    {'type': 'tool_result', 'content': 'y' * 25_000},
                ],
                'usage': {'cache_creation_input_tokens': 100,
                          'cache_read_input_tokens': 5_000,
                          'input_tokens': 10},
            }},
            _usage(cache_read=6_000),
            _usage(cache_read=7_000),
        ])
        _assert_parity_claude(path)

    def test_tail_share_and_growth(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [_usage(cache_read=k * 10_000) for k in range(1, 7)])
        r = _assert_parity_claude(path)
        assert r['tail_share'] is not None
        assert r['context_growth_factor'] is not None

    def test_context_mode_key_is_additive(self, tmp_path):
        # The new context_mode flag must be a pure addition: absent from the
        # frozen oracle, present in current, and perturbing no frozen value.
        path = _make_transcript([
            ('Read', {'file_path': 'a.py'}),
            ('ctx_search', {'query': 'x'}),
            ('Edit', {'file_path': 'a.py'}),
        ], tmp_path)
        old = legacy._analyze_transcript(path)
        new = current._analyze_transcript(path)
        _assert_frozen(old, new)                 # every legacy value unchanged
        assert 'context_mode' not in old
        assert new['context_mode'] is True

    def test_short_session_none_fields(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [_usage(cache_read=10_000)])
        r = _assert_parity_claude(path)
        assert r['tail_share'] is None
        assert r['context_growth_factor'] is None

    def test_malformed_lines_and_unknown_tools(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        with open(path, 'w') as f:
            f.write('{not json\n')
            f.write(json.dumps({'type': 'tool_use', 'name': 'Glob', 'input': {}}) + '\n')
            f.write(json.dumps([1, 2, 3]) + '\n')
            f.write(json.dumps({'type': 'tool_use', 'name': 'Read',
                                'input': 'not-a-dict'}) + '\n')
            f.write(json.dumps({'type': 'tool_use', 'name': 'Read',
                                'input': {'file_path': 'a.py'}}) + '\n')
        _assert_parity_claude(path)

    def test_empty_file(self, tmp_path):
        path = str(tmp_path / 'empty.jsonl')
        open(path, 'w').close()
        _assert_parity_claude(path)

    def test_missing_file(self, tmp_path):
        path = str(tmp_path / 'nope.jsonl')
        assert legacy._analyze_transcript(path) is None
        assert current._analyze_transcript(path) is None

    def test_deeply_nested_tool_use_depth_limit(self, tmp_path):
        obj = {}
        cur = obj
        for _ in range(10):
            cur['child'] = {}
            cur = cur['child']
        cur['type'] = 'tool_use'
        cur['name'] = 'Read'
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [obj, {'type': 'tool_use', 'name': 'Read', 'input': {}}])
        _assert_parity_claude(path)


class TestCursorJsonlParity:
    def test_relevant_and_irrelevant_mix(self, tmp_path):
        repo, other = '/repo/mine', '/repo/other'
        path = str(tmp_path / 's.jsonl')
        with open(path, 'w') as f:
            f.write(json.dumps({'tool': 'read_file', 'vcs': {'root': other},
                                'files': [other + '/x.py']}) + '\n')
            f.write(json.dumps({'tool': 'read_file', 'vcs': {'root': repo},
                                'files': [repo + '/a.py', repo + '/b.py']}) + '\n')
            f.write(json.dumps({'tool': 'run_terminal_command', 'vcs': {'root': repo},
                                'files': [repo + '/a.py'],
                                'input': {'command': 'grep -n def a.py'}}) + '\n')
            f.write(json.dumps({'tool': 'run_terminal_command', 'vcs': {'root': repo},
                                'files': [], 'input': {'command': 'npm test'}}) + '\n')
            f.write(json.dumps({'tool': 'edit_file', 'vcs': {'root': repo},
                                'files': [repo + '/a.py']}) + '\n')
            f.write(json.dumps({'tool': 'edit_file', 'vcs': {'root': repo},
                                'files': [repo + '/a.py']}) + '\n')
        old = legacy._analyze_cursor_transcript(path, repo)
        new = current._analyze_cursor_transcript(path, repo)
        _assert_frozen(old, new)
        assert new['source'] == 'cursor'

    def test_multifile_redundant_reads(self, tmp_path):
        repo = '/repo/p'
        path = str(tmp_path / 's.jsonl')
        _write_cursor_jsonl(path, repo, [
            ('read_file', [repo + '/a.py', repo + '/b.py']),
            ('read_file', [repo + '/a.py']),
            ('edit_file', [repo + '/a.py']),
        ])
        old = legacy._analyze_cursor_transcript(path, repo)
        new = current._analyze_cursor_transcript(path, repo)
        _assert_frozen(old, new)

    def test_no_relevant_activity_returns_none(self, tmp_path):
        repo, other = '/repo/mine', '/repo/other'
        path = str(tmp_path / 's.jsonl')
        _write_cursor_jsonl(path, other, [('read_file', [other + '/x.py'])])
        assert legacy._analyze_cursor_transcript(path, repo) is None
        assert current._analyze_cursor_transcript(path, repo) is None

    def test_empty_and_missing(self, tmp_path):
        empty = str(tmp_path / 'empty.jsonl')
        open(empty, 'w').close()
        assert legacy._analyze_cursor_transcript(empty, '/r') is None
        assert current._analyze_cursor_transcript(empty, '/r') is None
        missing = str(tmp_path / 'nope.jsonl')
        assert legacy._analyze_cursor_transcript(missing, '/r') is None
        assert current._analyze_cursor_transcript(missing, '/r') is None


def _make_cursor_db(path: str, bubbles: list[dict]) -> None:
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE cursorDiskKV (key TEXT, value TEXT)')
    for i, bubble in enumerate(bubbles):
        composer_id = bubble.pop('_composerId', 'comp1')
        bubble_id   = bubble.pop('_bubbleId', f'bub{i}')
        con.execute('INSERT INTO cursorDiskKV VALUES (?, ?)',
                    (f'bubbleId:{composer_id}:{bubble_id}', json.dumps(bubble)))
    con.commit()
    con.close()


class TestCursorDbParity:
    CUTOFF = datetime.datetime(2020, 1, 1)

    def _compare(self, db, repo):
        old = legacy._analyze_cursor_workspace_db(db, repo, self.CUTOFF)
        new = current._analyze_cursor_workspace_db(db, repo, self.CUTOFF)
        return _assert_frozen(old, new)

    def test_reads_edits_two_composers(self, tmp_path):
        repo = '/repo/p'
        db = str(tmp_path / 'state.vscdb')
        _make_cursor_db(db, [
            {'_composerId': 'c1', '_bubbleId': 'b1', 'createdAt': 1_700_000_001_000,
             'toolFormerData': [
                 {'toolName': 'read_file', 'params': {'target_file': repo + '/a.py'}},
                 {'toolName': 'read_file', 'params': {'target_file': repo + '/a.py'}},
             ]},
            {'_composerId': 'c1', '_bubbleId': 'b2', 'createdAt': 1_700_000_002_000,
             'toolFormerData': [
                 {'toolName': 'edit_file', 'params': {'target_file': repo + '/a.py'}},
             ]},
            {'_composerId': 'c2', '_bubbleId': 'b3', 'createdAt': 1_700_000_003_000,
             'toolFormerData': [
                 {'toolName': 'edit_file', 'params': {'target_file': repo + '/b.py'}},
             ]},
        ])
        sessions = self._compare(db, repo)
        assert len(sessions) == 2

    def test_irrelevant_repo_filtered(self, tmp_path):
        db = str(tmp_path / 'state.vscdb')
        _make_cursor_db(db, [
            {'_composerId': 'c1', '_bubbleId': 'b1', 'createdAt': 1_700_000_001_000,
             'toolFormerData': [
                 {'toolName': 'read_file', 'params': {'target_file': '/other/x.py'}},
             ]},
        ])
        assert self._compare(db, '/repo/mine') == []

    def test_mixed_repo_bubbles_counted_wholesale(self, tmp_path):
        # Legacy counts ALL events once any one event is under the repo —
        # the relevance gate is per-session, not per-event.
        repo = '/repo/p'
        db = str(tmp_path / 'state.vscdb')
        _make_cursor_db(db, [
            {'_composerId': 'c1', '_bubbleId': 'b1', 'createdAt': 1_700_000_001_000,
             'toolFormerData': [
                 {'toolName': 'read_file', 'params': {'target_file': '/other/x.py'}},
                 {'toolName': 'read_file', 'params': {'target_file': repo + '/a.py'}},
                 {'toolName': 'edit_file', 'params': {'target_file': '/other/y.py'}},
             ]},
        ])
        sessions = self._compare(db, repo)
        assert sessions and sessions[0]['reads'] == 2 and sessions[0]['edits'] == 1

    def test_missing_table_and_missing_file(self, tmp_path):
        db = str(tmp_path / 'state.vscdb')
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE unrelated (k TEXT)')
        con.commit()
        con.close()
        assert self._compare(db, '/repo/p') == []
        missing = str(tmp_path / 'nope.vscdb')
        assert self._compare(missing, '/repo/p') == []

    def test_no_created_at_uses_file_mtime(self, tmp_path):
        repo = '/repo/p'
        db = str(tmp_path / 'state.vscdb')
        _make_cursor_db(db, [
            {'_composerId': 'c1', '_bubbleId': 'b1',
             'toolFormerData': [
                 {'toolName': 'read_file', 'params': {'target_file': repo + '/a.py'}},
             ]},
        ])
        self._compare(db, repo)


def _codex_error_output(code: int = 2) -> dict:
    return {
        'type': 'response_item',
        'payload': {
            'type': 'function_call_output',
            'output': f'Process exited with code {code}',
        },
    }


class TestCodexParity:
    def _compare(self, path, repo):
        old = legacy._analyze_codex_transcript(path, repo)
        new = current._analyze_codex_transcript(path, repo)
        return _assert_frozen(old, new)

    def test_full_session(self, tmp_path):
        repo = str(tmp_path / 'repo')
        other = str(tmp_path / 'other')
        path = str(tmp_path / 's.jsonl')
        _write_codex_jsonl(path, repo, [
            _exec_cmd(f'cat {repo}/a.py', repo),
            _token_count(500, cached_input_tokens=100, output_tokens=20),
            _exec_cmd(f'cat {other}/x.py', other),          # irrelevant workdir
            _exec_cmd(f'ls {repo}', ''),                    # falls back to session cwd
            _exec_cmd('npm test', repo),                    # not a read
            _codex_error_output(2),
            _codex_error_output(1),                         # code 1 — not an error
            _apply_patch(f'*** Update File: {repo}/a.py\n--- a\n+++ b\n'),
            _token_count(2_000),
            _exec_cmd(f'cat {repo}/b.py', repo),            # after first edit
            _apply_patch(f'*** Update File: {repo}/a.py\n--- a\n+++ c\n'),
            _apply_patch(f'*** Update File: {other}/z.py\n--- a\n+++ b\n'),  # irrelevant
            _apply_patch('garbage patch with no file headers'),  # falls back to cwd
        ])
        r = self._compare(path, repo)
        assert r['source'] == 'codex'
        assert r['error_results'] == 1
        assert r['requests'] == 2

    def test_no_relevant_activity(self, tmp_path):
        repo = str(tmp_path / 'repo')
        other = str(tmp_path / 'other')
        path = str(tmp_path / 's.jsonl')
        _write_codex_jsonl(path, repo, [
            _exec_cmd(f'cat {other}/a.py', other),
        ])
        assert self._compare(path, repo) is None

    def test_dict_arguments(self, tmp_path):
        repo = str(tmp_path / 'repo')
        path = str(tmp_path / 's.jsonl')
        with open(path, 'w') as f:
            f.write(json.dumps({'type': 'session_meta', 'payload': {'cwd': repo}}) + '\n')
            f.write(json.dumps({
                'type': 'response_item',
                'payload': {'type': 'function_call', 'name': 'exec_command',
                            'arguments': {'cmd': f'cat {repo}/a.py', 'workdir': repo}},
            }) + '\n')
            f.write(json.dumps({
                'type': 'response_item',
                'payload': {'type': 'custom_tool_call', 'name': 'apply_patch',
                            'input': f'*** Add File: {repo}/n.py\n+++ x\n'},
            }) + '\n')
        self._compare(path, repo)

    def test_empty_and_missing(self, tmp_path):
        repo = str(tmp_path / 'repo')
        empty = str(tmp_path / 'empty.jsonl')
        _write_codex_jsonl(empty, repo, [])
        assert self._compare(empty, repo) is None
        missing = str(tmp_path / 'nope.jsonl')
        assert legacy._analyze_codex_transcript(missing, repo) is None
        assert current._analyze_codex_transcript(missing, repo) is None


class TestCollectParity:
    """collect_audit / run_compare: store-backed pipeline vs frozen legacy,
    cold cache and warm cache."""

    def _build_tree(self, tmp_path, monkeypatch, with_vscdb=False):
        repo = str(tmp_path / 'repo')
        other = str(tmp_path / 'other')

        claude_dir = tmp_path / 'claude-proj'
        claude_dir.mkdir()
        _write_raw(str(claude_dir / 's1.jsonl'), [
            {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}},
            {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}},
            _usage(cache_read=10_000, cache_write=500),
            {'type': 'tool_result', 'content': 'x' * 30_000},
            _usage(cache_read=20_000, input_tokens=50, output_tokens=5),
            {'type': 'tool_result', 'content': 'boom', 'is_error': True},
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'a.py'}},
            _usage(cache_read=25_000),
        ])
        _write_raw(str(claude_dir / 's2.jsonl'), [
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'grep -rn x .'}},
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'b.py'}},
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'b.py'}},
        ])

        at_dir = None
        if not with_vscdb:
            at_dir = tmp_path / 'agent-transcripts'
            at_dir.mkdir()
            _write_cursor_jsonl(str(at_dir / 'c.jsonl'), repo, [
                ('read_file', [repo + '/a.py']),
                ('read_file', [repo + '/a.py']),
                ('edit_file', [repo + '/a.py']),
            ])
            _write_cursor_jsonl(str(at_dir / 'irrelevant.jsonl'), other, [
                ('read_file', [other + '/z.py']),
            ])

        storage_root = None
        if with_vscdb:
            storage_root = tmp_path / 'cursor-user'
            ws = storage_root / 'workspaceStorage' / 'h1'
            ws.mkdir(parents=True)
            _make_cursor_db(str(ws / 'state.vscdb'), [
                {'_composerId': 'c1', '_bubbleId': 'b1',
                 'createdAt': 1_900_000_000_000,
                 'toolFormerData': [
                     {'toolName': 'read_file', 'params': {'target_file': repo + '/a.py'}},
                     {'toolName': 'edit_file', 'params': {'target_file': repo + '/a.py'}},
                 ]},
            ])

        codex_root = tmp_path / 'codex-sessions'
        (codex_root / 'sub').mkdir(parents=True)
        _write_codex_jsonl(str(codex_root / 'sub' / 'x.jsonl'), repo, [
            _exec_cmd(f'cat {repo}/a.py', repo),
            _token_count(500, cached_input_tokens=100, output_tokens=20),
            _apply_patch(f'*** Update File: {repo}/a.py\n--- a\n+++ b\n'),
            _token_count(2_000),
        ])

        cd = str(claude_dir)
        at = str(at_dir) if at_dir else None
        sr = str(storage_root) if storage_root else None
        cx = str(codex_root)
        for mod in (legacy, current):
            monkeypatch.setattr(mod, '_project_transcript_dir', lambda r, d=cd: d)
            monkeypatch.setattr(mod, '_cursor_agent_transcripts_dir', lambda d=at: d)
            monkeypatch.setattr(mod, '_cursor_storage_root', lambda d=sr: d)
            monkeypatch.setattr(mod, '_codex_sessions_dir', lambda d=cx: d)
        return repo

    def test_cold_warm_and_reingest_equal_legacy(self, tmp_path, monkeypatch):
        repo = self._build_tree(tmp_path, monkeypatch)
        old = legacy.collect_audit(repo, days=365)
        assert old is not None and old['sessions'] == 4
        cold = current.collect_audit(repo, days=365)
        warm = current.collect_audit(repo, days=365)
        forced = current.collect_audit(repo, days=365, reingest=True)
        _deep_equal(old, cold)
        _deep_equal(old, warm)
        _deep_equal(old, forced)

    def test_vscdb_branch_parity(self, tmp_path, monkeypatch):
        repo = self._build_tree(tmp_path, monkeypatch, with_vscdb=True)
        old = legacy.collect_audit(repo, days=365)
        cold = current.collect_audit(repo, days=365)
        warm = current.collect_audit(repo, days=365)
        _deep_equal(old, cold)
        _deep_equal(old, warm)
        assert any(p[0] == 'cursor' for p in cold['projects'])

    def test_none_when_no_transcripts(self, tmp_path, monkeypatch):
        for mod in (legacy, current):
            monkeypatch.setattr(mod, '_project_transcript_dir', lambda r: None)
            monkeypatch.setattr(mod, '_cursor_agent_transcripts_dir', lambda: None)
            monkeypatch.setattr(mod, '_cursor_storage_root', lambda: None)
            monkeypatch.setattr(mod, '_codex_sessions_dir', lambda: None)
        assert legacy.collect_audit(str(tmp_path)) is None
        assert current.collect_audit(str(tmp_path)) is None

    def test_run_compare_json_parity(self, tmp_path, monkeypatch, capsys):
        td_a = tmp_path / 't-a'
        td_b = tmp_path / 't-b'
        td_a.mkdir()
        td_b.mkdir()
        _write_raw(str(td_a / 's.jsonl'),
                   [{'type': 'tool_use', 'name': 'Read', 'input': {}}] * 4
                   + [{'type': 'tool_use', 'name': 'Edit', 'input': {}}])
        _write_raw(str(td_b / 's.jsonl'),
                   [{'type': 'tool_use', 'name': 'Read', 'input': {}},
                    {'type': 'tool_use', 'name': 'Edit', 'input': {}}])
        repo_a, repo_b = str(tmp_path / 'repo-a'), str(tmp_path / 'repo-b')
        mapping = {repo_a: str(td_a), repo_b: str(td_b)}
        for mod in (legacy, current):
            monkeypatch.setattr(mod, '_project_transcript_dir',
                                lambda root, m=mapping: m.get(root))
            monkeypatch.setattr(mod, '_cursor_agent_transcripts_dir', lambda: None)
            monkeypatch.setattr(mod, '_cursor_storage_root', lambda: None)
            monkeypatch.setattr(mod, '_codex_sessions_dir', lambda: None)

        legacy.run_compare(repo_a, repo_b, days=365, as_json=True)
        old = json.loads(capsys.readouterr().out)
        current.run_compare(repo_a, repo_b, days=365, as_json=True)
        new = json.loads(capsys.readouterr().out)
        _deep_equal(old, new)
