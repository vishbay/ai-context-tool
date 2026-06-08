"""Tests for cram/mcp_server.py — deterministic output from each tool."""

import os
from unittest.mock import patch

import pytest


CONTEXT_DIR = '.cram-ai-context'


@pytest.fixture()
def repo(tmp_path):
    """Minimal initialised repo for MCP tool tests."""
    ctx = tmp_path / CONTEXT_DIR
    ctx.mkdir()
    (ctx / 'ARCHITECTURE.md').write_text('# Arch\n\nKey files: main.py\n')
    (ctx / 'DECISIONS.md').write_text('# Decisions\n\n## [D-001] Use Python\n')
    (ctx / 'SYMBOLS.md').write_text('main.py: main, helper\nutils.py: parse, format\n')
    (tmp_path / 'main.py').write_text('def main(): pass\ndef helper(): pass\n')
    return tmp_path


# ---------------------------------------------------------------------------
# get_architecture determinism
# ---------------------------------------------------------------------------

class TestGetArchitectureDeterminism:
    def test_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_architecture()
        r2 = srv.get_architecture()
        assert r1 == r2

    def test_returns_file_content(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_architecture()
        assert '# Arch' in result


# ---------------------------------------------------------------------------
# get_decisions determinism
# ---------------------------------------------------------------------------

class TestGetDecisionsDeterminism:
    def test_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_decisions()
        r2 = srv.get_decisions()
        assert r1 == r2


# ---------------------------------------------------------------------------
# get_symbols determinism
# ---------------------------------------------------------------------------

class TestGetSymbolsDeterminism:
    def test_full_index_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_symbols()
        r2 = srv.get_symbols()
        assert r1 == r2

    def test_filtered_results_sorted(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_symbols('py')
        lines = result.split('\n')[2:]  # skip header line
        non_empty = [l for l in lines if l.strip()]
        assert non_empty == sorted(non_empty)

    def test_filtered_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_symbols('main')
        r2 = srv.get_symbols('main')
        assert r1 == r2


# ---------------------------------------------------------------------------
# get_context determinism
# ---------------------------------------------------------------------------

class TestGetContextDeterminism:
    def test_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))
        monkeypatch.chdir(repo)

        mock_entries = [('main.py', ['main', 'helper'])]
        with patch('cram.find_context.find_relevant_files', return_value=mock_entries):
            r1 = srv.get_context('fix the helper function')
            r2 = srv.get_context('fix the helper function')

        assert r1 == r2

    def test_no_volatile_token_header(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))
        monkeypatch.chdir(repo)

        mock_entries = [('main.py', ['main'])]
        with patch('cram.find_context.find_relevant_files', return_value=mock_entries):
            result = srv.get_context('some task')

        assert '<!-- cram-ai context' not in result
        assert 'tokens -->' not in result
