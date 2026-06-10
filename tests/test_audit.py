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
