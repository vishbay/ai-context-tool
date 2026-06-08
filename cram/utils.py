"""Shared model backend — provider-agnostic routing with auto-discovery."""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

CLAUDE_BIN = os.environ.get('CLAUDE_CODE_EXECPATH', 'claude')

_SETTINGS_FILE = Path.home() / '.config' / 'cram-ai' / 'settings.json'

# (id, display_name, tier, cost_per_mtok_input, quality_rank)
# tier: 'context' = cheap/fast retrieval; 'coding' = capable implementation
_CATALOGUE: dict[str, list[tuple]] = {
    'claude-cli': [
        ('cli/haiku',  'Claude Haiku (claude CLI)',  'context', 0,    2),
        ('cli/sonnet', 'Claude Sonnet (claude CLI)', 'coding',  0,    6),
        ('cli/opus',   'Claude Opus (claude CLI)',   'coding',  0,    9),
    ],
    'anthropic': [
        ('anthropic/claude-haiku-4-5-20251001', 'Claude Haiku 4.5',  'context', 0.80,  2),
        ('anthropic/claude-sonnet-4-6',         'Claude Sonnet 4.6', 'coding',  3.00,  6),
        ('anthropic/claude-opus-4-8',           'Claude Opus 4.8',   'coding',  15.00, 9),
    ],
    'openai': [
        ('openai/gpt-4o-mini', 'GPT-4o Mini', 'context', 0.15, 2),
        ('openai/gpt-4o',      'GPT-4o',      'coding',  5.00, 6),
    ],
    'gemini': [
        ('gemini/gemini-2.0-flash-lite', 'Gemini 2.0 Flash Lite', 'context', 0.08, 2),
        ('gemini/gemini-2.0-flash',      'Gemini 2.0 Flash',      'context', 0.40, 3),
        ('gemini/gemini-2.5-pro',        'Gemini 2.5 Pro',        'coding',  3.50, 7),
    ],
    'bedrock': [
        ('bedrock/anthropic.claude-3-haiku-20240307-v1:0',           'Claude Haiku (Bedrock)',  'context', 0.25, 2),
        ('bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0',        'Claude Sonnet (Bedrock)', 'coding',  3.00, 6),
    ],
    'vertex_ai': [
        ('vertex_ai/gemini-2.0-flash',            'Gemini Flash (Vertex)',    'context', 0.40, 3),
        ('vertex_ai/gemini-2.5-pro-preview-05-06','Gemini 2.5 Pro (Vertex)', 'coding',  3.50, 7),
    ],
    'azure': [
        ('azure/gpt-4o-mini', 'GPT-4o Mini (Azure)', 'context', 0.15, 2),
        ('azure/gpt-4o',      'GPT-4o (Azure)',       'coding',  5.00, 6),
    ],
}


# ── settings I/O ──────────────────────────────────────────────────

def load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(updates: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = load_settings()
    existing.update(updates)
    with open(_SETTINGS_FILE, 'w') as f:
        json.dump(existing, f, indent=2)


# ── credential probes ─────────────────────────────────────────────

def _check_claude_cli() -> bool:
    try:
        r = subprocess.run([CLAUDE_BIN, '--version'], capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


_OLLAMA_EMBED_PATTERNS = ('embed', 'clip', 'rerank', 'nomic-embed', 'bge-', 'e5-')


def _probe_ollama(base_url: str = 'http://localhost:11434') -> list[dict]:
    try:
        with urllib.request.urlopen(f'{base_url}/api/tags', timeout=2) as r:
            data = json.loads(r.read())
        result = []
        for m in data.get('models', []):
            name = m['name']
            name_lower = name.lower()
            # Skip embedding / reranking models — not text generators
            if any(p in name_lower for p in _OLLAMA_EMBED_PATTERNS):
                continue
            size_match = re.search(r'(\d+)b', name_lower)
            size = int(size_match.group(1)) if size_match else 7
            result.append({
                'id':       f'ollama/{name}',
                'name':     f'{name} (local Ollama)',
                'provider': 'ollama',
                'tier':     'context' if size <= 8 else 'coding',
                'cost':     0,
                'quality':  min(2 + size // 4, 8),
                'base_url': base_url,
            })
        return result
    except Exception:
        return []


def _check_aws_credentials() -> bool:
    if os.environ.get('AWS_ACCESS_KEY_ID') or os.environ.get('AWS_PROFILE'):
        return True
    return (Path.home() / '.aws' / 'credentials').exists() or \
           (Path.home() / '.aws' / 'config').exists()


def _check_gcp_credentials() -> bool:
    if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        return True
    return (Path.home() / '.config' / 'gcloud' / 'application_default_credentials.json').exists()


def _check_azure_credentials() -> bool:
    return bool(os.environ.get('AZURE_OPENAI_ENDPOINT'))


# ── discovery ─────────────────────────────────────────────────────

def discover_models() -> list[dict]:
    """Discover available models across all providers, sorted cheapest first."""
    available: list[dict] = []

    def _add(provider: str) -> None:
        for mid, name, tier, cost, quality in _CATALOGUE[provider]:
            available.append({'id': mid, 'name': name, 'provider': provider,
                               'tier': tier, 'cost': cost, 'quality': quality})

    # 1. Claude CLI — free, works inside Claude Code with no API key
    if _check_claude_cli():
        _add('claude-cli')

    # 2. Ollama — local, free
    settings = load_settings()
    available.extend(_probe_ollama(settings.get('ollama_url', 'http://localhost:11434')))

    # 3. Enterprise: AWS Bedrock (IAM / instance role, no API key needed)
    if _check_aws_credentials():
        _add('bedrock')

    # 4. Enterprise: GCP Vertex AI (ADC / service account, no API key needed)
    if _check_gcp_credentials():
        _add('vertex_ai')

    # 5. Enterprise: Azure OpenAI (managed identity / AZURE_OPENAI_ENDPOINT)
    if _check_azure_credentials():
        _add('azure')

    # 6. Direct API keys
    if os.environ.get('ANTHROPIC_API_KEY'):
        _add('anthropic')
    if os.environ.get('OPENAI_API_KEY'):
        _add('openai')
    if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
        _add('gemini')

    # 7. Custom proxy (corporate gateway, LiteLLM proxy, etc.)
    proxy = settings.get('proxy', {})
    if proxy.get('base_url'):
        available.append({
            'id':       'proxy/custom',
            'name':     f"Custom proxy ({proxy['base_url']})",
            'provider': 'proxy',
            'tier':     'both',
            'cost':     0,
            'quality':  5,
        })

    # Sort: free first, then cheapest, then highest quality within same cost
    return sorted(available, key=lambda m: (m['cost'], -m['quality']))


def pick_context_model(available: list[dict]) -> dict | None:
    """Cheapest model suitable for context/retrieval tasks."""
    candidates = [m for m in available if m['tier'] in ('context', 'both')]
    return candidates[0] if candidates else (available[0] if available else None)


def pick_coding_model(available: list[dict]) -> dict | None:
    """Highest quality model for coding tasks."""
    candidates = [m for m in available if m['tier'] in ('coding', 'both')]
    if not candidates:
        candidates = available
    return max(candidates, key=lambda m: m['quality']) if candidates else None


def cache_min_tokens(model_name: str) -> int:
    """Minimum prefix tokens required for prompt caching to activate for this model."""
    return 4096 if 'opus' in model_name.lower() else 1024


def get_model_recommendations() -> tuple[str, str]:
    """Return (context_model_name, coding_model_name) for display."""
    settings = load_settings()
    available = discover_models()

    ctx_id = settings.get('context_model', 'auto')
    cod_id = settings.get('coding_model',  'auto')

    def _name(model_id: str, picker) -> str:
        if model_id == 'auto':
            m = picker(available)
            return m['name'] if m else 'none found'
        m = next((x for x in available if x['id'] == model_id), None)
        return m['name'] if m else model_id

    return _name(ctx_id, pick_context_model), _name(cod_id, pick_coding_model)


# ── call_context_model ────────────────────────────────────────────

def call_context_model(prompt: str) -> str:
    """Route to the cheapest available model for context/retrieval tasks.

    Priority:
    1. settings.json context_model (explicit user choice)
    2. Auto-discover cheapest available provider
    3. Fall back to call_model()
    """
    settings = load_settings()
    model_id = settings.get('context_model', 'auto')

    if model_id == 'auto':
        available = discover_models()
        best = pick_context_model(available)
        model_id = best['id'] if best else ''

    if not model_id or model_id == 'auto':
        return call_model(prompt)

    if model_id.startswith('cli/'):
        return _call_via_cli(prompt, model_id.split('/', 1)[1])
    if model_id.startswith('ollama/'):
        settings = load_settings()
        base_url = settings.get('ollama_url', 'http://localhost:11434')
        return _call_via_ollama(prompt, model_id[len('ollama/'):], base_url)
    if '/' in model_id:
        return _call_via_litellm(prompt, model_id)
    return _call_via_cli(prompt, model_id)


# ── existing call_model (kept for backwards compat) ───────────────

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


# ── shared helpers ────────────────────────────────────────────────

def find_git_root(path: str = '.') -> str:
    current = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(path)
        current = parent


def strip_code_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
    if lines and not lines[0].startswith('#') and lines[0].endswith(':'):
        lines = lines[1:]
    return '\n'.join(lines).strip()


def _call_via_ollama(prompt: str, model: str, base_url: str = 'http://localhost:11434') -> str:
    payload = json.dumps({'model': model, 'prompt': prompt, 'stream': False}).encode()
    req = urllib.request.Request(
        f'{base_url}/api/generate',
        data=payload,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())['response'].strip()


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
        model=model or 'claude-haiku-4-5-20251001',
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
