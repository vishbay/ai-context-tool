"""Tests for cram/find_context.py — path cleaning, file inlining, CLI flow."""

import os
from unittest.mock import patch

import pytest

from cram.find_context import (
    _clean_path,
    _read_truncated,
    find_relevant_files,
    populate_current_task,
    find_context,
)


# ---------------------------------------------------------------------------
# _clean_path
# ---------------------------------------------------------------------------

class TestCleanPath:
    def test_strips_dash_bullet(self):
        assert _clean_path('- src/main.py') == 'src/main.py'

    def test_strips_asterisk_bullet(self):
        assert _clean_path('* src/main.py') == 'src/main.py'

    def test_strips_numbered_list(self):
        assert _clean_path('1. src/main.py') == 'src/main.py'

    def test_strips_backticks(self):
        assert _clean_path('`src/main.py`') == 'src/main.py'

    def test_strips_whitespace(self):
        assert _clean_path('  src/main.py  ') == 'src/main.py'

    def test_rejects_prose_with_spaces(self):
        assert _clean_path('Based on the architecture:') == ''
        assert _clean_path('Here are the relevant files') == ''

    def test_rejects_bare_word_without_separator(self):
        # 'README' has no '/' or '.' — ambiguous, rejected
        assert _clean_path('README') == ''

    def test_accepts_path_with_dot_only(self):
        assert _clean_path('README.md') == 'README.md'

    def test_accepts_path_with_slash_only(self):
        assert _clean_path('src/file') == 'src/file'

    def test_accepts_nested_path(self):
        assert _clean_path('cram/utils.py') == 'cram/utils.py'


# ---------------------------------------------------------------------------
# _read_truncated
# ---------------------------------------------------------------------------

class TestReadTruncated:
    def test_returns_full_content_under_limit(self, tmp_path):
        f = tmp_path / 'small.py'
        f.write_text('line1\nline2\nline3\n')
        result = _read_truncated(str(f))
        assert 'line1' in result
        assert 'line3' in result
        assert 'omitted' not in result

    def test_truncates_and_adds_marker(self, tmp_path, monkeypatch):
        import cram.find_context as fc
        monkeypatch.setattr(fc, 'MAX_LINES', 2)
        f = tmp_path / 'big.py'
        f.write_text('\n'.join(f'line{i}' for i in range(10)))
        result = _read_truncated(str(f))
        assert 'line0' in result
        assert 'line1' in result
        assert 'line9' not in result
        assert 'omitted' in result


# ---------------------------------------------------------------------------
# find_relevant_files
# ---------------------------------------------------------------------------

class TestFindRelevantFiles:
    def test_returns_cleaned_file_paths(self):
        mock_response = 'src/main.py\ncram/utils.py\n'
        with patch('cram.find_context.call_model', return_value=mock_response):
            result = find_relevant_files('add feature', '# Arch', '# Decisions')
        assert 'src/main.py' in result
        assert 'cram/utils.py' in result

    def test_strips_prose_from_response(self):
        mock_response = (
            'Here are the relevant files:\n'
            'src/main.py\n'
            '- cram/utils.py\n'
        )
        with patch('cram.find_context.call_model', return_value=mock_response):
            result = find_relevant_files('add feature', '', '')
        assert 'src/main.py' in result
        assert 'cram/utils.py' in result
        assert any('Here' in p for p in result) is False

    def test_respects_max_files_limit(self, monkeypatch):
        import cram.find_context as fc
        monkeypatch.setattr(fc, 'MAX_FILES', 2)
        mock_response = 'a/b.py\nc/d.py\ne/f.py\ng/h.py'
        with patch('cram.find_context.call_model', return_value=mock_response):
            result = find_relevant_files('task', '', '')
        assert len(result) <= 2

    def test_passes_task_and_context_to_model(self):
        with patch('cram.find_context.call_model', return_value='src/a.py') as mock_call:
            find_relevant_files('my task', '# Arch content', '# Dec content')
        prompt = mock_call.call_args[0][0]
        assert 'my task' in prompt
        assert '# Arch content' in prompt
        assert '# Dec content' in prompt


# ---------------------------------------------------------------------------
# populate_current_task
# ---------------------------------------------------------------------------

class TestPopulateCurrentTask:
    def test_inlines_existing_file_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = tmp_path / '.ai-context'
        ctx.mkdir()
        src = tmp_path / 'utils.py'
        src.write_text('def helper(): pass\n')

        found = populate_current_task('fix bug', ['utils.py'])

        assert found == ['utils.py']
        content = (ctx / 'CURRENT_TASK.md').read_text()
        assert 'fix bug' in content
        assert 'def helper(): pass' in content

    def test_notes_missing_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / '.ai-context').mkdir()

        found = populate_current_task('task', ['ghost.py'])

        assert found == []
        content = (tmp_path / '.ai-context' / 'CURRENT_TASK.md').read_text()
        assert 'ghost.py' in content
        assert 'not found' in content

    def test_uses_correct_code_fence_for_extension(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / '.ai-context').mkdir()
        (tmp_path / 'app.ts').write_text('const x = 1;\n')

        populate_current_task('task', ['app.ts'])

        content = (tmp_path / '.ai-context' / 'CURRENT_TASK.md').read_text()
        assert '```ts' in content

    def test_handles_mixed_existing_and_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / '.ai-context').mkdir()
        (tmp_path / 'real.py').write_text('# real\n')

        found = populate_current_task('task', ['real.py', 'fake.py'])

        assert 'real.py' in found
        assert 'fake.py' not in found


# ---------------------------------------------------------------------------
# find_context (integration)
# ---------------------------------------------------------------------------

class TestFindContext:
    def test_exits_if_no_context_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            find_context('some task')

    def test_warns_if_architecture_missing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / '.ai-context').mkdir()
        # No ARCHITECTURE.md created — should warn but not crash

        with patch('cram.find_context.call_model', return_value=''):
            find_context('some task')

        assert 'Warning' in capsys.readouterr().err

    def test_full_flow_with_mocked_model(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = tmp_path / '.ai-context'
        ctx.mkdir()
        (ctx / 'ARCHITECTURE.md').write_text('# Arch')
        (ctx / 'DECISIONS.md').write_text('# Dec')
        (tmp_path / 'main.py').write_text('print("hello")\n')

        with patch('cram.find_context.call_model', return_value='main.py'):
            find_context('fix the print')

        content = (ctx / 'CURRENT_TASK.md').read_text()
        assert 'fix the print' in content
        assert 'print("hello")' in content
