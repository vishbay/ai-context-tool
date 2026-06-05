"""Shared model backend: uses claude -p (Claude Code session) or Anthropic SDK."""

import os
import subprocess
import sys

CLAUDE_BIN = os.environ.get('CLAUDE_CODE_EXECPATH', 'claude')
DEFAULT_MODEL = os.environ.get('AICONTEXT_MODEL', 'haiku')


def strip_code_fence(text: str) -> str:
    """Remove outer markdown code fences that models sometimes add."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
    # Also strip a prose preamble line before the first heading
    if lines and not lines[0].startswith('#') and lines[0].endswith(':'):
        lines = lines[1:]
    return '\n'.join(lines).strip()


def call_model(prompt: str) -> str:
    """Send a prompt and return the response text.

    Prefers the Anthropic SDK (ANTHROPIC_API_KEY) and falls back to
    the local `claude -p` CLI so the tool works inside Claude Code sessions
    without a separate API key.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')

    if api_key:
        return _call_via_sdk(prompt, api_key)
    return _call_via_cli(prompt)


def _call_via_sdk(prompt: str, api_key: str) -> str:
    import anthropic
    model = os.environ.get('AICONTEXT_MODEL', 'claude-haiku-4-5')
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _call_via_cli(prompt: str) -> str:
    model = DEFAULT_MODEL  # 'haiku' alias works with claude -p --model
    try:
        system = (
            "You are a text generator. Output ONLY the exact content requested. "
            "Never use tools. Never ask for permission. Never describe what you will do. "
            "Never write file paths. Just return the raw text content directly."
        )
        result = subprocess.run(
            [CLAUDE_BIN, '-p', '-', '--model', model,
             '--output-format', 'text', '--input-format', 'text',
             '--allowedTools', '',
             '--append-system-prompt', system],
            input=prompt,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error calling claude CLI: {e.stderr}", file=sys.stderr)
        raise
    except FileNotFoundError:
        raise RuntimeError(
            "No ANTHROPIC_API_KEY set and `claude` CLI not found. "
            "Set ANTHROPIC_API_KEY or run inside a Claude Code session."
        )
