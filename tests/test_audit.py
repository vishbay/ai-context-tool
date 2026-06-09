"""Tests for cram/audit.py — transcript analysis and efficiency metrics."""

from __future__ import annotations
import json
import os
import tempfile

import pytest

from cram.audit import _analyze_transcript, _find_all_tool_use


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
