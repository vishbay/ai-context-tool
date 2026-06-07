"""Tests for cram/targets.py — save/load default_target, detect, write."""

import os
import pytest

from cram.targets import (
    load_default_target,
    save_default_target,
    detect_targets,
    write_to_target,
    TARGET_FILES,
)

CONTEXT_DIR = '.cram-ai-context'


# ---------------------------------------------------------------------------
# save_default_target / load_default_target round-trip
# ---------------------------------------------------------------------------

class TestSaveLoadDefaultTarget:
    def test_round_trip(self, tmp_path):
        os.makedirs(tmp_path / CONTEXT_DIR)
        save_default_target(str(tmp_path), 'cursor')
        assert load_default_target(str(tmp_path)) == 'cursor'

    def test_overwrites_previous_value(self, tmp_path):
        os.makedirs(tmp_path / CONTEXT_DIR)
        save_default_target(str(tmp_path), 'claude')
        save_default_target(str(tmp_path), 'windsurf')
        assert load_default_target(str(tmp_path)) == 'windsurf'

    def test_all_is_valid(self, tmp_path):
        os.makedirs(tmp_path / CONTEXT_DIR)
        save_default_target(str(tmp_path), 'all')
        assert load_default_target(str(tmp_path)) == 'all'

    def test_all_known_targets_round_trip(self, tmp_path):
        os.makedirs(tmp_path / CONTEXT_DIR)
        for t in TARGET_FILES:
            save_default_target(str(tmp_path), t)
            assert load_default_target(str(tmp_path)) == t

    def test_invalid_target_not_saved(self, tmp_path):
        os.makedirs(tmp_path / CONTEXT_DIR)
        save_default_target(str(tmp_path), 'unknown-tool')
        assert load_default_target(str(tmp_path)) is None

    def test_preserves_existing_toml_content(self, tmp_path):
        config = tmp_path / CONTEXT_DIR / 'config.toml'
        os.makedirs(tmp_path / CONTEXT_DIR)
        config.write_text('[model]\nname = "claude"\n')
        save_default_target(str(tmp_path), 'cursor')
        content = config.read_text()
        assert 'name = "claude"' in content
        assert 'default_target = "cursor"' in content

    def test_appends_to_existing_task_section(self, tmp_path):
        config = tmp_path / CONTEXT_DIR / 'config.toml'
        os.makedirs(tmp_path / CONTEXT_DIR)
        config.write_text('[task]\nsome_other = "value"\n')
        save_default_target(str(tmp_path), 'copilot')
        content = config.read_text()
        assert 'some_other = "value"' in content
        assert 'default_target = "copilot"' in content

    def test_no_context_dir_returns_none(self, tmp_path):
        assert load_default_target(str(tmp_path)) is None

    def test_empty_config_dir_returns_none(self, tmp_path):
        os.makedirs(tmp_path / CONTEXT_DIR)
        assert load_default_target(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# detect_targets
# ---------------------------------------------------------------------------

class TestDetectTargets:
    def test_detects_cursor(self, tmp_path):
        (tmp_path / '.cursor').mkdir()
        assert 'cursor' in detect_targets(str(tmp_path))

    def test_detects_github(self, tmp_path):
        (tmp_path / '.github').mkdir()
        assert 'copilot' in detect_targets(str(tmp_path))

    def test_detects_none_when_empty(self, tmp_path):
        assert detect_targets(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# write_to_target
# ---------------------------------------------------------------------------

class TestWriteToTarget:
    def test_creates_file_for_cursor(self, tmp_path):
        path = write_to_target(str(tmp_path), 'cursor', '# Task\n')
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == '# Task\n'

    def test_creates_parent_dirs(self, tmp_path):
        path = write_to_target(str(tmp_path), 'windsurf', 'content')
        assert os.path.isfile(path)

    def test_raises_on_unknown_target(self, tmp_path):
        with pytest.raises(ValueError, match='Unknown target'):
            write_to_target(str(tmp_path), 'nonexistent', '')
