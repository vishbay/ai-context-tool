"""Tests for the measured orientation metrics (orientation tax % etc.).

These are the first deliberately *new* metrics since the parity freeze: raw
pre-edit/total token sums per session (cram/audit_events.py) and the
spend-weighted orientation share aggregates (cram/audit.py). Pricing
multipliers are applied at query time from the provider table.
"""

from __future__ import annotations
import json

from cram.audit import _analyze_transcript, _analyze_codex_transcript, collect_audit
from tests.test_audit import (
    _write_codex_jsonl, _exec_cmd, _apply_patch, _token_count,
)


def _write_raw(path, messages):
    with open(path, 'w') as f:
        for msg in messages:
            f.write(json.dumps(msg) + '\n')


def _usage(input_tokens=0, cache_read=0, cache_write=0, output_tokens=0):
    return {'usage': {'cache_creation_input_tokens': cache_write,
                      'cache_read_input_tokens': cache_read,
                      'input_tokens': input_tokens,
                      'output_tokens': output_tokens}}


def _tool(name, inp=None):
    return {'type': 'tool_use', 'name': name, 'input': inp or {}}


class TestPerSessionMeasured:
    def test_requests_before_edit_boundary(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [
            _usage(input_tokens=100),
            _usage(input_tokens=200),
            _tool('Edit', {'file_path': 'a.py'}),
            _usage(input_tokens=400),
        ])
        r = _analyze_transcript(path)
        assert r['requests'] == 3
        assert r['requests_before_edit'] == 2
        assert r['pre_edit_input_tokens'] == 300
        assert r['input_tokens'] == 700

    def test_pre_edit_cache_components(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [
            _usage(input_tokens=10, cache_read=1_000, cache_write=100),
            _tool('Write', {'file_path': 'a.py'}),
            _usage(input_tokens=20, cache_read=2_000, cache_write=200),
        ])
        r = _analyze_transcript(path)
        assert r['pre_edit_input_tokens'] == 10
        assert r['pre_edit_cache_reads'] == 1_000
        assert r['pre_edit_cache_writes'] == 100
        assert r['input_tokens'] == 30
        assert r['cache_reads'] == 3_000
        assert r['cache_writes'] == 300

    def test_no_edit_session_counts_everything_pre_edit(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        _write_raw(path, [_tool('Read'), _usage(input_tokens=50)])
        r = _analyze_transcript(path)
        assert r['edits'] == 0
        assert r['requests_before_edit'] == 1 == r['requests']

    def test_codex_irrelevant_edit_does_not_end_phase(self, tmp_path):
        # An apply_patch outside the repo is not a counted edit, so usage after
        # it is still pre-edit — same boundary as reads_before_edit.
        repo = str(tmp_path / 'repo')
        other = str(tmp_path / 'other')
        path = str(tmp_path / 's.jsonl')
        _write_codex_jsonl(path, repo, [
            _exec_cmd(f'cat {repo}/a.py', repo),
            _token_count(100),
            _apply_patch(f'*** Update File: {other}/x.py\n--- a\n+++ b\n'),
            _token_count(200),
            _apply_patch(f'*** Update File: {repo}/a.py\n--- a\n+++ b\n'),
            _token_count(400),
        ])
        r = _analyze_codex_transcript(path, repo)
        assert r['edits'] == 1
        assert r['requests_before_edit'] == 2
        assert r['pre_edit_input_tokens'] == 300


class TestAggregateMeasured:
    def _setup(self, tmp_path, monkeypatch, sessions):
        import cram.audit as _audit_mod
        td = tmp_path / 'proj'
        td.mkdir()
        for i, msgs in enumerate(sessions):
            _write_raw(str(td / f's{i}.jsonl'), msgs)
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                            lambda r, d=str(td): d)
        monkeypatch.setattr(_audit_mod, '_cursor_agent_transcripts_dir', lambda: None)
        monkeypatch.setattr(_audit_mod, '_cursor_storage_root', lambda: None)
        monkeypatch.setattr(_audit_mod, '_codex_sessions_dir', lambda: None)

    def test_tax_pct_input_only(self, tmp_path, monkeypatch):
        # pre-edit eff = 1000, total eff = 4000 → 25% (no cache → no multipliers)
        self._setup(tmp_path, monkeypatch, [[
            _usage(input_tokens=1_000),
            _tool('Edit', {'file_path': 'a.py'}),
            _usage(input_tokens=3_000),
        ]])
        data = collect_audit(str(tmp_path), days=365)
        assert data['edit_sessions'] == 1
        assert data['orient_measured_sessions'] == 1
        assert abs(data['orient_tax_pct'] - 0.25) < 1e-9
        assert abs(data['orient_spend_eff_tokens'] - 1_000) < 1e-9

    def test_tax_pct_applies_cache_multipliers(self, tmp_path, monkeypatch):
        # anthropic defaults: write 1.25×, read 0.10×.
        # pre-edit: cw=1000, cr=10000 → eff 1250 + 1000 = 2250
        # post-edit: cr=30000 → eff 3000; total eff = 5250
        self._setup(tmp_path, monkeypatch, [[
            _usage(cache_write=1_000, cache_read=10_000),
            _tool('Edit', {'file_path': 'a.py'}),
            _usage(cache_read=30_000),
        ]])
        data = collect_audit(str(tmp_path), days=365)
        assert abs(data['orient_tax_pct'] - 2_250 / 5_250) < 1e-9

    def test_read_only_sessions_segmented_out(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, [
            [_tool('Read'), _usage(input_tokens=9_999)],          # read-only
            [_usage(input_tokens=100),
             _tool('Edit', {'file_path': 'a.py'}),
             _usage(input_tokens=100)],                            # edit session
        ])
        data = collect_audit(str(tmp_path), days=365)
        assert data['sessions'] == 2
        assert data['read_only_sessions'] == 1
        assert data['edit_sessions'] == 1
        # the read-only session's 9,999 tokens must not inflate the tax
        assert abs(data['orient_tax_pct'] - 0.5) < 1e-9

    def test_edit_session_without_usage_is_unmeasured(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, [
            [_tool('Read'), _tool('Edit', {'file_path': 'a.py'})],  # no usage
        ])
        data = collect_audit(str(tmp_path), days=365)
        assert data['edit_sessions'] == 1
        assert data['orient_measured_sessions'] == 0
        assert data['orient_unmeasured_edit_sessions'] == 1
        assert data['orient_tax_pct'] is None
        assert data['orient_spend_eff_tokens'] is None
        assert data['orient_spend_cost'] is None

    def test_all_read_only_yields_none(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, [
            [_tool('Read'), _usage(input_tokens=500)],
        ])
        data = collect_audit(str(tmp_path), days=365)
        assert data['edit_sessions'] == 0
        assert data['read_only_sessions'] == 1
        assert data['orient_tax_pct'] is None

    def test_local_provider_zeroes_cache_weighting(self, tmp_path, monkeypatch):
        # With CRAM_PROVIDER=local the multipliers are 0, so eff = raw input.
        monkeypatch.setenv('CRAM_PROVIDER', 'local')
        import importlib
        import cram.audit as _audit_mod
        importlib.reload(_audit_mod)
        try:
            self._setup(tmp_path, monkeypatch, [[
                _usage(input_tokens=1_000, cache_read=50_000),
                _tool('Edit', {'file_path': 'a.py'}),
                _usage(input_tokens=1_000, cache_read=90_000),
            ]])
            data = _audit_mod.collect_audit(str(tmp_path), days=365)
            assert abs(data['orient_tax_pct'] - 0.5) < 1e-9
        finally:
            monkeypatch.delenv('CRAM_PROVIDER', raising=False)
            importlib.reload(_audit_mod)

    def test_report_prints_measured_block(self, tmp_path, monkeypatch, capsys):
        from cram.audit import run_audit
        self._setup(tmp_path, monkeypatch, [[
            _usage(input_tokens=1_000),
            _tool('Edit', {'file_path': 'a.py'}),
            _usage(input_tokens=3_000),
        ]])
        run_audit(str(tmp_path), days=365)
        out = capsys.readouterr().out
        assert 'Orientation (measured)' in out
        assert '25%' in out
        assert 'Est. orientation' in out  # estimated block keeps its label

    def test_json_includes_new_keys(self, tmp_path, monkeypatch, capsys):
        from cram.audit import run_audit
        self._setup(tmp_path, monkeypatch, [[
            _usage(input_tokens=1_000),
            _tool('Edit', {'file_path': 'a.py'}),
        ]])
        run_audit(str(tmp_path), days=365, as_json=True)
        parsed = json.loads(capsys.readouterr().out)
        assert parsed['orient_tax_pct'] == 1.0
        assert parsed['edit_sessions'] == 1

    def test_compare_renders_dash_for_unmeasured_arm(self, tmp_path, monkeypatch, capsys):
        import cram.audit as _audit_mod
        from cram.audit import run_compare
        td_a = tmp_path / 't-a'
        td_b = tmp_path / 't-b'
        td_a.mkdir()
        td_b.mkdir()
        # A has usage (measured); B has none (unmeasured → '—' row)
        _write_raw(str(td_a / 's.jsonl'), [
            _usage(input_tokens=100),
            _tool('Edit', {'file_path': 'a.py'}),
            _usage(input_tokens=300),
        ])
        _write_raw(str(td_b / 's.jsonl'), [_tool('Read'), _tool('Edit', {'file_path': 'b.py'})])
        repo_a, repo_b = str(tmp_path / 'repo-a'), str(tmp_path / 'repo-b')
        mapping = {repo_a: str(td_a), repo_b: str(td_b)}
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                            lambda root, m=mapping: m.get(root))
        monkeypatch.setattr(_audit_mod, '_cursor_agent_transcripts_dir', lambda: None)
        monkeypatch.setattr(_audit_mod, '_cursor_storage_root', lambda: None)
        monkeypatch.setattr(_audit_mod, '_codex_sessions_dir', lambda: None)
        run_compare(repo_a, repo_b, days=365)
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if 'Orientation tax %' in l)
        assert '—' in line
