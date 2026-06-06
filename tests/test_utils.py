"""Tests for cram/utils.py — strip_code_fence and call_model routing."""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from cram.utils import strip_code_fence, call_model


# ---------------------------------------------------------------------------
# strip_code_fence
# ---------------------------------------------------------------------------

class TestStripCodeFence:
    def test_removes_plain_fence(self):
        assert strip_code_fence("```\nfoo\n```") == "foo"

    def test_removes_language_fence(self):
        assert strip_code_fence("```markdown\n# Arch\n```") == "# Arch"

    def test_removes_prose_preamble_before_heading(self):
        assert strip_code_fence("Here's the doc:\n# Arch") == "# Arch"

    def test_leaves_clean_markdown_unchanged(self):
        md = "# Arch\n\n## Section\nContent"
        assert strip_code_fence(md) == md

    def test_handles_empty_string(self):
        assert strip_code_fence("") == ""

    def test_strips_surrounding_whitespace(self):
        assert strip_code_fence("  \n# Heading\n  ") == "# Heading"

    def test_does_not_strip_mid_document_fences(self):
        md = "# Arch\n```python\ncode\n```\nmore"
        result = strip_code_fence(md)
        assert "```python" in result

    def test_preamble_not_stripped_if_no_colon(self):
        # Only strip preamble when it ends with ':'
        md = "Some intro line\n# Heading"
        result = strip_code_fence(md)
        assert "Some intro line" in result


# ---------------------------------------------------------------------------
# call_model routing
# ---------------------------------------------------------------------------

class TestCallModelRouting:
    def test_routes_to_litellm_when_model_has_slash(self):
        with patch.dict('os.environ', {'AICONTEXT_MODEL': 'openai/gpt-4o-mini'}, clear=False):
            with patch('cram.utils._call_via_litellm', return_value='ok') as mock_litellm:
                result = call_model("hello")
        mock_litellm.assert_called_once_with("hello", "openai/gpt-4o-mini")
        assert result == "ok"

    def test_routes_to_anthropic_sdk_when_key_set(self):
        env = {'AICONTEXT_MODEL': '', 'ANTHROPIC_API_KEY': 'sk-test'}
        with patch.dict('os.environ', env, clear=False):
            with patch('cram.utils._call_via_anthropic_sdk', return_value='ok') as mock_sdk:
                result = call_model("hello")
        mock_sdk.assert_called_once_with("hello", "")
        assert result == "ok"

    def test_routes_to_cli_when_no_key(self):
        env = {'AICONTEXT_MODEL': ''}
        with patch.dict('os.environ', env, clear=False):
            # Remove ANTHROPIC_API_KEY if present
            with patch('os.environ.get') as mock_get:
                mock_get.side_effect = lambda k, d='': {
                    'AICONTEXT_MODEL': '',
                    'ANTHROPIC_API_KEY': '',
                }.get(k, d)
                with patch('cram.utils._call_via_cli', return_value='ok') as mock_cli:
                    result = call_model("hello")
        mock_cli.assert_called_once()

    def test_litellm_takes_priority_over_api_key(self):
        env = {'AICONTEXT_MODEL': 'google/gemini-2.5-flash', 'ANTHROPIC_API_KEY': 'sk-test'}
        with patch.dict('os.environ', env, clear=False):
            with patch('cram.utils._call_via_litellm', return_value='ok') as mock_litellm:
                with patch('cram.utils._call_via_anthropic_sdk') as mock_sdk:
                    call_model("hello")
        mock_litellm.assert_called_once()
        mock_sdk.assert_not_called()

    def test_bare_model_alias_goes_to_cli_without_api_key(self):
        with patch.dict('os.environ', {'AICONTEXT_MODEL': 'haiku'}, clear=False):
            with patch('os.environ.get') as mock_get:
                mock_get.side_effect = lambda k, d='': {
                    'AICONTEXT_MODEL': 'haiku',
                    'ANTHROPIC_API_KEY': '',
                }.get(k, d)
                with patch('cram.utils._call_via_cli', return_value='ok') as mock_cli:
                    call_model("hello")
        mock_cli.assert_called_once()


class TestCallViaLitellmMissing:
    def test_exits_when_litellm_not_installed(self):
        with patch.dict('sys.modules', {'litellm': None}):
            with pytest.raises(SystemExit):
                from cram.utils import _call_via_litellm
                _call_via_litellm("hi", "openai/gpt-4o-mini")
