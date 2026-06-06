"""Shared model backend — routes to any provider via litellm or claude -p CLI."""

import os
import subprocess
import sys

CLAUDE_BIN = os.environ.get('CLAUDE_CODE_EXECPATH', 'claude')

# AICONTEXT_MODEL accepts:
#   provider/model  → routed via litellm (openai/gpt-4o-mini, google/gemini-2.0-flash-lite,
#                     anthropic/claude-haiku-4-5, ollama/mistral, …)
#   bare alias      → passed to claude -p (haiku, sonnet, opus)
#   unset           → falls back to claude -p with 'haiku'


def strip_code_fence(text: str) -> str:
    """Remove outer markdown code fences that models sometimes add."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
    # Strip a prose preamble line before the first heading
    if lines and not lines[0].startswith('#') and lines[0].endswith(':'):
        lines = lines[1:]
    return '\n'.join(lines).strip()


def call_model(prompt: str) -> str:
    """Send a prompt and return the response text.

    Routing priority:
    1. AICONTEXT_MODEL contains '/'  → litellm (any provider)
    2. ANTHROPIC_API_KEY is set      → Anthropic SDK directly
    3. Fallback                      → claude -p (Claude Code session, no key needed)
    """
    model = os.environ.get('AICONTEXT_MODEL', '')

    if '/' in model:
        return _call_via_litellm(prompt, model)

    if os.environ.get('ANTHROPIC_API_KEY'):
        return _call_via_anthropic_sdk(prompt, model)

    return _call_via_cli(prompt, model)


def _call_via_litellm(prompt: str, model: str) -> str:
    try:
        import litellm
    except ImportError:
        print(
            "litellm not installed. Run: pip install litellm\n"
            "Or set AICONTEXT_MODEL to a bare alias (haiku) to use the claude CLI.",
            file=sys.stderr,
        )
        sys.exit(1)

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
    )
    return response.choices[0].message.content.strip()


def _call_via_anthropic_sdk(prompt: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model or 'claude-haiku-4-5',
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _call_via_cli(prompt: str, model: str) -> str:
    system = (
        "You are a text generator. Output ONLY the exact content requested. "
        "Never use tools. Never ask for permission. Never describe what you will do. "
        "Never write file paths. Just return the raw text content directly."
    )
    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', '-', '--model', model or 'haiku',
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
            "Set ANTHROPIC_API_KEY or AICONTEXT_MODEL=provider/model and the matching API key."
        )
