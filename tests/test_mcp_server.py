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

    def test_no_task_returns_current_task_md(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        (repo / CONTEXT_DIR / 'CURRENT_TASK.md').write_text('# Task: previous task\n\nsome context\n')
        result = srv.get_context()

        assert '# Task: previous task' in result
        assert 'some context' in result

    def test_no_task_no_file_returns_guidance(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_context()

        assert 'No context loaded yet' in result

    def test_stale_header_prepended_when_stale(self, repo, monkeypatch):
        import cram.mcp_server as srv
        import cram.health as health_mod
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        (repo / CONTEXT_DIR / 'CURRENT_TASK.md').write_text('# Task: fix\n\nsome context\n')

        fake_health = {
            'staleness_band': 'stale', 'staleness_score': 6,
            'commits_since_sync': 6, 'state': 'stale', 'last_commit_age': '1h ago',
            'files': {},
        }
        monkeypatch.setattr(health_mod, 'context_health', lambda root: fake_health)

        result = srv.get_context()
        assert result.startswith('> staleness: stale')
        assert 'run `cram sync`' in result

    def test_no_stale_header_when_fresh(self, repo, monkeypatch):
        import cram.mcp_server as srv
        import cram.health as health_mod
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        (repo / CONTEXT_DIR / 'CURRENT_TASK.md').write_text('# Task: fix\n\nsome context\n')

        fake_health = {
            'staleness_band': 'fresh', 'staleness_score': 1,
            'commits_since_sync': 0, 'state': 'fresh', 'last_commit_age': None,
            'files': {},
        }
        monkeypatch.setattr(health_mod, 'context_health', lambda root: fake_health)

        result = srv.get_context()
        assert not result.startswith('> staleness:')


# ---------------------------------------------------------------------------
# get_health determinism + content
# ---------------------------------------------------------------------------

class TestGetHealthDeterminism:
    def test_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_health()
        r2 = srv.get_health()
        assert r1 == r2

    def test_contains_health_header(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_health()
        assert '# Context health' in result
        assert 'staleness:' in result

    def test_no_wall_clock_in_output(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_health()
        # Determinism check: no "ago" timestamps in the health body
        assert ' ago' not in result

    def test_over_budget_file_flagged(self, repo, monkeypatch):
        import cram.mcp_server as srv
        import cram.health as health_mod
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        fake_health = {
            'staleness_band': 'stale', 'staleness_score': 6,
            'commits_since_sync': 6, 'state': 'stale', 'last_commit_age': None,
            'files': {
                'GOTCHAS.md': {'tokens': 470, 'lines': 30, 'budget': 400, 'budget_status': 'over'},
            },
        }
        monkeypatch.setattr(health_mod, 'context_health', lambda root: fake_health)

        result = srv.get_health()
        assert 'over' in result
        assert 'trim before next sync' in result
        assert 'GOTCHAS.md' in result
        assert 'recommendation' in result
