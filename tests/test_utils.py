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


class TestProxyHeaders:
    """proxy.base_url and proxy.headers thread through to litellm.completion."""

    def _make_litellm_mock(self):
        mock_litellm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = 'response text'
        mock_litellm.completion.return_value = mock_response
        return mock_litellm

    def test_proxy_base_url_sets_api_base(self, tmp_path):
        from cram.utils import _call_via_litellm
        mock_litellm = self._make_litellm_mock()
        settings = {'proxy': {'base_url': 'https://gateway.corp/v1'}}
        with patch('cram.utils.load_settings', return_value=settings):
            with patch.dict('sys.modules', {'litellm': mock_litellm}):
                _call_via_litellm('hello', 'openai/gpt-4o')
        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs['api_base'] == 'https://gateway.corp/v1'

    def test_proxy_base_url_uses_dummy_key_when_no_api_key(self, tmp_path):
        from cram.utils import _call_via_litellm
        mock_litellm = self._make_litellm_mock()
        settings = {'proxy': {'base_url': 'https://gateway.corp/v1'}}
        with patch('cram.utils.load_settings', return_value=settings):
            with patch.dict('sys.modules', {'litellm': mock_litellm}):
                _call_via_litellm('hello', 'openai/gpt-4o')
        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs['api_key'] == 'no-key'

    def test_proxy_api_key_used_when_provided(self, tmp_path):
        from cram.utils import _call_via_litellm
        mock_litellm = self._make_litellm_mock()
        settings = {'proxy': {'base_url': 'https://gateway.corp/v1', 'api_key': 'mytoken'}}
        with patch('cram.utils.load_settings', return_value=settings):
            with patch.dict('sys.modules', {'litellm': mock_litellm}):
                _call_via_litellm('hello', 'openai/gpt-4o')
        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs['api_key'] == 'mytoken'

    def test_proxy_headers_set_as_extra_headers(self, tmp_path):
        from cram.utils import _call_via_litellm
        mock_litellm = self._make_litellm_mock()
        settings = {'proxy': {
            'base_url': 'https://gateway.corp/v1',
            'headers': {'X-Corp-Token': 'abc123', 'X-Tenant': 'acme'},
        }}
        with patch('cram.utils.load_settings', return_value=settings):
            with patch.dict('sys.modules', {'litellm': mock_litellm}):
                _call_via_litellm('hello', 'openai/gpt-4o')
        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs['extra_headers'] == {'X-Corp-Token': 'abc123', 'X-Tenant': 'acme'}

    def test_no_proxy_config_no_extra_kwargs(self, tmp_path):
        from cram.utils import _call_via_litellm
        mock_litellm = self._make_litellm_mock()
        with patch('cram.utils.load_settings', return_value={}):
            with patch.dict('sys.modules', {'litellm': mock_litellm}):
                _call_via_litellm('hello', 'openai/gpt-4o')
        call_kwargs = mock_litellm.completion.call_args[1]
        assert 'api_base' not in call_kwargs
        assert 'extra_headers' not in call_kwargs
        assert 'api_key' not in call_kwargs

    def test_headers_without_base_url_still_applied(self, tmp_path):
        from cram.utils import _call_via_litellm
        mock_litellm = self._make_litellm_mock()
        settings = {'proxy': {'headers': {'Authorization': 'Bearer tok'}}}
        with patch('cram.utils.load_settings', return_value=settings):
            with patch.dict('sys.modules', {'litellm': mock_litellm}):
                _call_via_litellm('hello', 'openai/gpt-4o')
        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs['extra_headers'] == {'Authorization': 'Bearer tok'}
        assert 'api_base' not in call_kwargs
