"""Tests for canonical .ai-context directory resolution."""

from cram.context_dir import (
    CONTEXT_DIR,
    LEGACY_CONTEXT_DIR,
    context_basename,
    context_path,
    has_context_dir,
    resolve_context_dir,
)


def test_prefers_canonical_context_dir(tmp_path):
    canonical = tmp_path / CONTEXT_DIR
    legacy = tmp_path / LEGACY_CONTEXT_DIR
    canonical.mkdir()
    legacy.mkdir()

    assert resolve_context_dir(str(tmp_path)) == str(canonical)
    assert context_basename(str(tmp_path)) == CONTEXT_DIR


def test_falls_back_to_legacy_context_dir(tmp_path):
    legacy = tmp_path / LEGACY_CONTEXT_DIR
    legacy.mkdir()

    assert has_context_dir(str(tmp_path)) is True
    assert resolve_context_dir(str(tmp_path)) == str(legacy)
    assert context_basename(str(tmp_path)) == LEGACY_CONTEXT_DIR


def test_context_path_uses_resolved_dir(tmp_path):
    legacy = tmp_path / LEGACY_CONTEXT_DIR
    legacy.mkdir()

    assert context_path(str(tmp_path), 'CURRENT_TASK.md') == str(legacy / 'CURRENT_TASK.md')
