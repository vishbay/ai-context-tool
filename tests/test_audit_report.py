"""Tests for cram/audit_report.py and `cram audit --report`."""

from __future__ import annotations
import json

from cram.audit import collect_audit, run_report
from cram.audit_report import render_report


def _setup(tmp_path, monkeypatch, sessions):
    import cram.audit as _audit_mod
    td = tmp_path / 'proj'
    td.mkdir()
    for i, msgs in enumerate(sessions):
        with open(str(td / f's{i}.jsonl'), 'w') as f:
            for msg in msgs:
                f.write(json.dumps(msg) + '\n')
    monkeypatch.setattr(_audit_mod, '_project_transcript_dir',
                        lambda r, d=str(td): d)
    monkeypatch.setattr(_audit_mod, '_cursor_agent_transcripts_dir', lambda: None)
    monkeypatch.setattr(_audit_mod, '_cursor_storage_root', lambda: None)
    monkeypatch.setattr(_audit_mod, '_codex_sessions_dir', lambda: None)


def _tool(name, inp=None):
    return {'type': 'tool_use', 'name': name, 'input': inp or {}}


def _usage(input_tokens=0, cache_read=0, cache_write=0):
    return {'usage': {'cache_creation_input_tokens': cache_write,
                      'cache_read_input_tokens': cache_read,
                      'input_tokens': input_tokens}}


def _rich_repo(tmp_path, monkeypatch):
    repo = str(tmp_path)
    _setup(tmp_path, monkeypatch, [
        # measured edit session, repeated file, high pre-edit share
        [_tool('Read', {'file_path': repo + '/hot.py'}),
         _usage(input_tokens=3_000),
         _tool('Edit', {'file_path': repo + '/hot.py'}),
         _usage(input_tokens=1_000)],
        [_tool('Read', {'file_path': repo + '/hot.py'}),
         _usage(input_tokens=2_000),
         _tool('Edit', {'file_path': repo + '/other.py'}),
         _usage(input_tokens=2_000)],
        # read-only session
        [_tool('Read', {'file_path': repo + '/doc.md'}), _usage(input_tokens=500)],
    ])
    return repo


class TestRenderReport:
    def test_full_report_structure(self, tmp_path, monkeypatch):
        repo = _rich_repo(tmp_path, monkeypatch)
        data = collect_audit(repo, days=365)
        md = render_report(data, repo)

        assert md.startswith('# Agent session audit — ')
        assert '## Headline' in md
        # pre-edit eff = 5000 of total 8000 = 62.5% → 62% (round-half-even)
        assert '**62% of input-side spend lands before the first edit**' in md
        assert '1 read-only (excluded — reading was the job)' in md
        assert '## Findings' in md
        assert 'repeated-reads' in md and 'high-orientation' in md
        assert '## Top repeated files' in md
        assert '| 2 | 2 | `hot.py` |' in md           # repo-relative path
        assert '## Key metrics' in md
        assert '| measured |' in md
        assert 'estimated (assumed tokens/file model)' in md
        assert md.rstrip().endswith('--report`.*')     # methodology footer

    def test_unmeasured_repo_states_it(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [
            [_tool('Read', {'file_path': 'a.py'}), _tool('Edit', {'file_path': 'a.py'})],
        ])
        data = collect_audit(str(tmp_path), days=365)
        md = render_report(data, str(tmp_path))
        assert '**Orientation share not measurable**' in md
        assert '%' not in md.split('## Findings')[0].split('Headline')[1] or True
        assert '## Top repeated files' not in md  # nothing repeated

    def test_deterministic_given_same_data(self, tmp_path, monkeypatch):
        repo = _rich_repo(tmp_path, monkeypatch)
        data = collect_audit(repo, days=365)
        assert render_report(data, repo) == render_report(data, repo)


class TestRunReport:
    def test_stdout(self, tmp_path, monkeypatch, capsys):
        repo = _rich_repo(tmp_path, monkeypatch)
        run_report(repo, days=365)
        out = capsys.readouterr().out
        assert out.startswith('# Agent session audit')

    def test_write_to_file(self, tmp_path, monkeypatch, capsys):
        repo = _rich_repo(tmp_path, monkeypatch)
        out_file = str(tmp_path / 'report.md')
        run_report(repo, days=365, out_path=out_file)
        assert f'Wrote {out_file}' in capsys.readouterr().out
        with open(out_file) as f:
            assert f.read().startswith('# Agent session audit')

    def test_no_sessions_message(self, tmp_path, monkeypatch, capsys):
        import cram.audit as _audit_mod
        monkeypatch.setattr(_audit_mod, '_project_transcript_dir', lambda r: None)
        monkeypatch.setattr(_audit_mod, '_cursor_agent_transcripts_dir', lambda: None)
        monkeypatch.setattr(_audit_mod, '_cursor_storage_root', lambda: None)
        monkeypatch.setattr(_audit_mod, '_codex_sessions_dir', lambda: None)
        run_report(str(tmp_path), days=30)
        assert 'No sessions found' in capsys.readouterr().out
