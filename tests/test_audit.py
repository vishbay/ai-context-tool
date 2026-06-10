"""Tests for cram/audit.py — transcript analysis and efficiency metrics."""

from __future__ import annotations
import io
import json
import os
import tempfile

import pytest

from cram.audit import (
    _analyze_transcript, _find_all_tool_use, collect_audit, ratio_band,
    AUDIT_TOK_PER_FILE, AUDIT_BASE_PRICE,
)


def _make_transcript(tool_calls: list[tuple[str, dict]], tmp_path) -> str:
    """Write a fake JSONL transcript with the given tool_use blocks."""
    path = str(tmp_path / 'session.jsonl')
    with open(path, 'w') as f:
        for name, inp in tool_calls:
            msg = {'type': 'tool_use', 'name': name, 'input': inp}
            f.write(json.dumps(msg) + '\n')
    return path


class TestAnalyzeTranscript:
    def test_counts_reads(self, tmp_path):
        path = _make_transcript([
            ('Read', {'file_path': 'foo.py'}),
            ('Read', {'file_path': 'bar.py'}),
            ('Edit', {'file_path': 'foo.py'}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r is not None
        assert r['reads'] == 2

    def test_reads_before_edit(self, tmp_path):
        path = _make_transcript([
            ('Read', {}),
            ('Read', {}),
            ('Edit', {}),
            ('Read', {}),  # after edit — not counted in reads_before_edit
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['reads_before_edit'] == 2
        assert r['reads'] == 3

    def test_edits_counted(self, tmp_path):
        path = _make_transcript([
            ('Read', {}),
            ('Edit', {}),
            ('Write', {}),
            ('Edit', {}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['edits'] == 3

    def test_ratio_reads_before_edit_over_edits(self, tmp_path):
        path = _make_transcript([
            ('Read', {}),
            ('Read', {}),
            ('Read', {}),
            ('Read', {}),
            ('Edit', {}),
            ('Edit', {}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['reads_before_edit'] == 4
        assert r['edits'] == 2
        assert abs(r['ratio'] - 2.0) < 0.01

    def test_ratio_with_no_edits_uses_one(self, tmp_path):
        # reads_before_edit / max(edits, 1) — denominator floored at 1
        path = _make_transcript([
            ('Read', {}),
            ('Read', {}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['edits'] == 0
        assert r['ratio'] == 2.0

    def test_bash_read_commands_counted(self, tmp_path):
        path = _make_transcript([
            ('Bash', {'command': 'cat foo.py'}),
            ('Bash', {'command': 'grep -n def foo.py'}),
            ('Edit', {}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['reads_before_edit'] == 2

    def test_bash_write_not_counted_as_read(self, tmp_path):
        path = _make_transcript([
            ('Bash', {'command': 'python run_tests.py'}),
            ('Edit', {}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['reads_before_edit'] == 0

    def test_empty_file_returns_zero_metrics(self, tmp_path):
        path = str(tmp_path / 'empty.jsonl')
        open(path, 'w').close()
        r = _analyze_transcript(path)
        assert r is not None
        assert r['reads'] == 0
        assert r['edits'] == 0
        assert r['ratio'] == 0.0

    def test_returns_none_on_missing_file(self, tmp_path):
        r = _analyze_transcript(str(tmp_path / 'nonexistent.jsonl'))
        assert r is None

    def test_ratio_field_present_in_return(self, tmp_path):
        path = _make_transcript([('Read', {}), ('Edit', {})], tmp_path)
        r = _analyze_transcript(path)
        assert 'ratio' in r
        assert 'edits' in r

    def test_high_ratio_is_flagged(self, tmp_path):
        # 10 reads before 1 edit → ratio 10.0 (above 5× threshold)
        calls = [('Read', {})] * 10 + [('Edit', {})]
        path = _make_transcript(calls, tmp_path)
        r = _analyze_transcript(path)
        assert r['ratio'] > 5.0


class TestRatioBand:
    def test_bands(self):
        assert ratio_band(0.5) == 'good'
        assert ratio_band(1.99) == 'good'
        assert ratio_band(2.0) == 'normal'
        assert ratio_band(4.99) == 'normal'
        assert ratio_band(5.0) == 'high'
        assert ratio_band(12.0) == 'high'


def _write_transcript(path, tool_calls, usage=None):
    """Write a JSONL transcript with tool_use blocks and an optional usage block."""
    with open(path, 'w') as f:
        for name, inp in tool_calls:
            f.write(json.dumps({'type': 'tool_use', 'name': name, 'input': inp}) + '\n')
        if usage is not None:
            f.write(json.dumps({'usage': usage}) + '\n')


class TestCollectAudit:
    def _setup_transcripts(self, tmp_path, monkeypatch, sessions):
        import cram.audit as _audit_mod
        td = tmp_path / 'transcripts' / 'proj'
        td.mkdir(parents=True)
        for i, (calls, usage) in enumerate(sessions):
            _write_transcript(str(td / f's{i}.jsonl'), calls, usage)
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                            lambda repo_root: str(td))
        return td

    def test_returns_none_without_transcripts(self, tmp_path, monkeypatch):
        import cram.audit as _audit_mod
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir', lambda r: None)
        assert collect_audit(str(tmp_path)) is None

    def test_summary_fields(self, tmp_path, monkeypatch):
        self._setup_transcripts(tmp_path, monkeypatch, [
            ([('Read', {}), ('Read', {}), ('Edit', {})], None),
            ([('Read', {}), ('Edit', {}), ('Edit', {})], None),
        ])
        data = collect_audit(str(tmp_path), days=365)
        assert data is not None
        assert data['sessions'] == 2
        assert abs(data['avg_reads_before_edit'] - 1.5) < 0.01
        assert data['ratio_band'] in ('good', 'normal', 'high')
        assert len(data['recent']) == 2
        assert data['weekly']  # at least one weekly bucket

    def test_cache_blind_session_detected(self, tmp_path, monkeypatch):
        # One session reads from cache, one writes but never reads.
        self._setup_transcripts(tmp_path, monkeypatch, [
            ([('Read', {}), ('Edit', {})],
             {'cache_creation_input_tokens': 5000, 'cache_read_input_tokens': 90000}),
            ([('Read', {}), ('Edit', {})],
             {'cache_creation_input_tokens': 5000, 'cache_read_input_tokens': 0}),
        ])
        data = collect_audit(str(tmp_path), days=365)
        assert data['cache_engaged_sessions'] == 1
        assert data['cache_blind_sessions'] == 1

    def test_monthly_cost_not_inflated(self, tmp_path, monkeypatch):
        """Monthly orientation tax = cost/session × sessions/month — no extra ×30."""
        self._setup_transcripts(tmp_path, monkeypatch, [
            ([('Read', {}), ('Read', {}), ('Edit', {})], None),
        ])
        data = collect_audit(str(tmp_path), days=30)
        expected = data['orient_cost_per_session'] * data['sessions_per_month']
        assert abs(data['monthly_orient_cost'] - expected) < 1e-9

    def test_json_output_is_valid(self, tmp_path, monkeypatch, capsys):
        from cram.audit import run_audit
        self._setup_transcripts(tmp_path, monkeypatch, [
            ([('Read', {}), ('Edit', {})], None),
        ])
        run_audit(str(tmp_path), days=365, as_json=True)
        parsed = json.loads(capsys.readouterr().out)
        assert parsed['sessions'] == 1
        assert 'ratio_band' in parsed


class TestContextBloat:
    """Bucket-2 metrics: context growth, oversized tool results, redundant reads."""

    def _write_raw(self, path, messages):
        with open(path, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')

    def _usage(self, cache_read, input_tokens=0):
        return {'usage': {'cache_creation_input_tokens': 0,
                          'cache_read_input_tokens': cache_read,
                          'input_tokens': input_tokens}}

    def test_no_usage_blocks_yields_zero_bloat_fields(self, tmp_path):
        path = _make_transcript([('Read', {}), ('Edit', {})], tmp_path)
        r = _analyze_transcript(path)
        assert r['requests'] == 0
        assert r['avg_context_per_request'] == 0.0
        assert r['peak_context'] == 0
        assert r['tail_share'] is None
        assert r['carried_read_tokens'] == 0

    def test_context_growth_and_tail_share(self, tmp_path):
        # 6 requests with linearly growing context: 10k..60k.
        # Last third = requests 5,6 → (50+60)/210 ≈ 0.524
        path = str(tmp_path / 's.jsonl')
        self._write_raw(path, [self._usage(k * 10_000) for k in range(1, 7)])
        r = _analyze_transcript(path)
        assert r['requests'] == 6
        assert abs(r['avg_context_per_request'] - 35_000) < 1
        assert r['peak_context'] == 60_000
        assert abs(r['tail_share'] - 110 / 210) < 0.01

    def test_tail_share_none_for_short_sessions(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        self._write_raw(path, [self._usage(10_000) for _ in range(5)])
        r = _analyze_transcript(path)
        assert r['tail_share'] is None

    def test_oversized_result_and_carried_tokens(self, tmp_path):
        # Big result lands after 2 requests; 4 more requests follow → carried
        # tokens = est_tokens × 4.
        path = str(tmp_path / 's.jsonl')
        big = {'type': 'tool_result', 'content': 'x' * 30_000}
        msgs = ([self._usage(10_000)] * 2 + [big] + [self._usage(10_000)] * 4)
        self._write_raw(path, msgs)
        r = _analyze_transcript(path)
        assert r['big_results'] == 1
        est_tokens = len(json.dumps('x' * 30_000)) // 4
        assert r['carried_read_tokens'] == est_tokens * 4

    def test_small_result_not_counted(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        self._write_raw(path, [{'type': 'tool_result', 'content': 'small'}])
        r = _analyze_transcript(path)
        assert r['big_results'] == 0

    def test_redundant_reads_counted(self, tmp_path):
        path = _make_transcript([
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'b.py'}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['redundant_reads'] == 2

    def test_collect_audit_aggregates_bloat(self, tmp_path, monkeypatch):
        import cram.audit as _audit_mod
        td = tmp_path / 'transcripts' / 'proj'
        td.mkdir(parents=True)
        msgs = ([self._usage(10_000)] * 2 +
                [{'type': 'tool_result', 'content': 'x' * 30_000}] +
                [self._usage(20_000)] * 4)
        self._write_raw(str(td / 's0.jsonl'), msgs)
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                            lambda repo_root: str(td))
        data = collect_audit(str(tmp_path), days=365)
        assert data['avg_requests'] == 6
        assert data['peak_context'] == 20_000
        assert data['sessions_with_big_results'] == 1
        assert data['carried_cost_per_session'] > 0
        assert data['bloat_sessions_measured'] == 1
        assert 'big_result_bytes' in data


class TestRetryLoops:
    """Bucket-3 metrics: failed tool calls and same-file edit churn."""

    def _write_raw(self, path, messages):
        with open(path, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')

    def test_error_results_counted(self, tmp_path):
        path = str(tmp_path / 's.jsonl')
        self._write_raw(path, [
            {'type': 'tool_result', 'content': 'boom', 'is_error': True},
            {'type': 'tool_result', 'content': 'fine'},
            {'type': 'tool_result', 'content': 'fine', 'is_error': False},
            {'type': 'tool_result', 'content': 'boom again', 'is_error': True},
        ])
        r = _analyze_transcript(path)
        assert r['error_results'] == 2

    def test_no_errors_yields_zero(self, tmp_path):
        path = _make_transcript([('Read', {}), ('Edit', {})], tmp_path)
        r = _analyze_transcript(path)
        assert r['error_results'] == 0
        assert r['edit_churn'] == 0

    def test_edit_churn_counts_repeat_edits(self, tmp_path):
        # 3 edits to a.py (churn 2) + 1 to b.py (churn 0) → 2
        path = _make_transcript([
            ('Edit', {'file_path': 'a.py'}),
            ('Edit', {'file_path': 'a.py'}),
            ('Write', {'file_path': 'a.py'}),
            ('Edit', {'file_path': 'b.py'}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['edit_churn'] == 2

    def test_edits_without_file_path_ignored(self, tmp_path):
        path = _make_transcript([
            ('Edit', {}),
            ('Edit', {}),
            ('Write', {'command': 'no path here'}),
        ], tmp_path)
        r = _analyze_transcript(path)
        assert r['edits'] == 3
        assert r['edit_churn'] == 0

    def test_collect_audit_aggregates_retry_loops(self, tmp_path, monkeypatch):
        import cram.audit as _audit_mod
        td = tmp_path / 'transcripts' / 'proj'
        td.mkdir(parents=True)
        # Session 0: 2 failures + churn 1; session 1: clean.
        self._write_raw(str(td / 's0.jsonl'), [
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'a.py'}},
            {'type': 'tool_result', 'content': 'boom', 'is_error': True},
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'a.py'}},
            {'type': 'tool_result', 'content': 'boom', 'is_error': True},
        ])
        self._write_raw(str(td / 's1.jsonl'), [
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'b.py'}},
            {'type': 'tool_result', 'content': 'fine'},
        ])
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                            lambda repo_root: str(td))
        data = collect_audit(str(tmp_path), days=365)
        assert abs(data['avg_error_results'] - 1.0) < 0.01
        assert abs(data['avg_edit_churn'] - 0.5) < 0.01
        assert data['sessions_with_errors'] == 1


class TestFindAllToolUse:
    def test_finds_top_level(self):
        obj = {'type': 'tool_use', 'name': 'Read', 'input': {}}
        assert _find_all_tool_use(obj) == [obj]

    def test_finds_nested(self):
        obj = {'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {}}]}
        result = _find_all_tool_use(obj)
        assert len(result) == 1
        assert result[0]['name'] == 'Edit'

    def test_empty_object(self):
        assert _find_all_tool_use({}) == []

    def test_depth_limit(self):
        # Build deeply nested structure that exceeds depth limit
        obj = {}
        current = obj
        for _ in range(10):
            current['child'] = {}
            current = current['child']
        current['type'] = 'tool_use'
        # Should not crash or loop; depth limit returns empty
        result = _find_all_tool_use(obj)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# B5: Module constants (AUDIT_TOK_PER_FILE, AUDIT_BASE_PRICE) and caveat output
# ---------------------------------------------------------------------------

class TestAuditConstants:
    def test_constants_have_expected_defaults(self):
        """AUDIT_TOK_PER_FILE defaults to 2500 and AUDIT_BASE_PRICE to Sonnet base."""
        assert AUDIT_TOK_PER_FILE == 2500
        assert abs(AUDIT_BASE_PRICE - 3.0 / 1_000_000) < 1e-12

    def test_constants_are_overridable_via_env(self, monkeypatch):
        """Env vars CRAM_AUDIT_TOK_PER_FILE and CRAM_AUDIT_BASE_PRICE override defaults."""
        monkeypatch.setenv('CRAM_AUDIT_TOK_PER_FILE', '1000')
        monkeypatch.setenv('CRAM_AUDIT_BASE_PRICE', '0.000005')
        # Re-import to pick up env overrides
        import importlib
        import cram.audit as _audit_mod
        importlib.reload(_audit_mod)
        try:
            assert _audit_mod.AUDIT_TOK_PER_FILE == 1000
            assert abs(_audit_mod.AUDIT_BASE_PRICE - 0.000005) < 1e-12
        finally:
            importlib.reload(_audit_mod)  # restore defaults

    def test_provider_wiring_local_zeroes_prices(self, monkeypatch):
        """CRAM_PROVIDER=local zeroes AUDIT_BASE_PRICE and CACHE_READ_MULT on reload."""
        monkeypatch.setenv('CRAM_PROVIDER', 'local')
        monkeypatch.delenv('CRAM_AUDIT_BASE_PRICE', raising=False)
        import importlib
        import cram.audit as _audit_mod
        importlib.reload(_audit_mod)
        try:
            assert _audit_mod.AUDIT_PROVIDER == 'local'
            assert _audit_mod.AUDIT_BASE_PRICE == 0.0
            assert _audit_mod.CACHE_READ_MULT == 0.0
        finally:
            monkeypatch.delenv('CRAM_PROVIDER', raising=False)
            importlib.reload(_audit_mod)  # restore defaults

    def test_run_audit_prints_modelled_caveat(self, tmp_path, monkeypatch):
        """run_audit output contains the modelled-cost caveat line."""
        from cram.audit import run_audit
        import cram.audit as _audit_mod

        # Create a minimal transcript with reads+edits
        td = tmp_path / 'transcripts' / 'cram-ai'
        td.mkdir(parents=True)
        transcript = td / 'session.jsonl'
        calls = [
            ('Read', {'file_path': 'a.py'}),
            ('Read', {'file_path': 'b.py'}),
            ('Edit', {'file_path': 'a.py'}),
        ]
        with open(transcript, 'w') as f:
            for name, inp in calls:
                f.write(json.dumps({'type': 'tool_use', 'name': name, 'input': inp}) + '\n')

        # Patch _project_transcript_dir to return our tmp transcript dir
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                            lambda repo_root: str(td))

        buf = io.StringIO()
        import sys
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            run_audit(str(tmp_path), days=365)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        assert 'modelled' in output or 'Modelled' in output or 'reads_before_edit' in output
        # The caveat note should mention tok/file assumption
        assert 'tok/file' in output or 'AUDIT_TOK_PER_FILE' in output or '2,500' in output

    def test_analyze_transcript_returns_required_fields(self, tmp_path):
        """_analyze_transcript returns reads, reads_before_edit, edits, and ratio."""
        path = str(tmp_path / 'session.jsonl')
        with open(path, 'w') as f:
            for name, inp in [('Read', {}), ('Read', {}), ('Edit', {})]:
                f.write(json.dumps({'type': 'tool_use', 'name': name, 'input': inp}) + '\n')

        r = _analyze_transcript(path)
        assert r is not None
        assert r['reads'] == 2
        assert r['reads_before_edit'] == 2
        assert r['edits'] == 1
        assert abs(r['ratio'] - 2.0) < 0.01
