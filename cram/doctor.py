"""cram doctor — check your setup and print a health report."""

from __future__ import annotations
import os
import subprocess
import sys

CONTEXT_DIR = '.cram-ai-context'


def _row(ok: bool | None, label: str, detail: str = '') -> None:
    """Print one check row.  True=✓  False=✗ (error)  None=! (advisory)"""
    icon = '✓' if ok is True else ('!' if ok is None else '✗')
    tail = f'  — {detail}' if detail else ''
    print(f'  {icon}  {label}{tail}')


def main() -> None:
    from cram.utils import find_git_root, discover_models, pick_context_model, pick_coding_model

    print('\ncram doctor')
    print('─' * 44)

    errors = 0

    # ── Python ────────────────────────────────────────────────────
    v = sys.version_info
    ok = v >= (3, 8)
    _row(ok, f'Python {v.major}.{v.minor}.{v.micro}')
    if not ok:
        errors += 1

    # ── git ───────────────────────────────────────────────────────
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
        _row(True, 'git')
    except Exception:
        _row(False, 'git not found', 'install from https://git-scm.com')
        errors += 1

    # ── repo ──────────────────────────────────────────────────────
    try:
        repo = find_git_root()
        _row(True, 'git repo', os.path.basename(repo))
    except Exception:
        _row(False, 'not in a git repo', 'run from inside a git repository')
        errors += 1
        repo = None

    # ── context dir ───────────────────────────────────────────────
    if repo:
        ctx = os.path.join(repo, CONTEXT_DIR)
        if os.path.isdir(ctx):
            _row(True, f'{CONTEXT_DIR}/')

            for fname in ('ARCHITECTURE.md', 'DECISIONS.md', 'GOTCHAS.md', 'SYMBOLS.md'):
                p = os.path.join(ctx, fname)
                if os.path.exists(p) and os.path.getsize(p) > 0:
                    _row(True, f'  {fname}')
                else:
                    _row(None, f'  {fname} missing', 'run `cram sync` to rebuild')

            task_p = os.path.join(ctx, 'CURRENT_TASK.md')
            if os.path.exists(task_p) and os.path.getsize(task_p) > 100:
                _row(True, '  CURRENT_TASK.md', 'task set')
            else:
                _row(None, '  CURRENT_TASK.md not set', 'run `cram task "..."` before your session')

            # committed to git?
            try:
                r = subprocess.run(
                    ['git', 'ls-files', '--error-unmatch',
                     os.path.join(ctx, 'ARCHITECTURE.md')],
                    cwd=repo, capture_output=True,
                )
                if r.returncode == 0:
                    _row(True, 'context committed', 'teammates get context automatically')
                else:
                    _row(None, 'context not committed',
                         f'git add {CONTEXT_DIR}/ && git commit -m "chore: init cram-ai"')
            except Exception:
                pass
        else:
            _row(False, f'{CONTEXT_DIR}/ not found', 'run `cram init` first')
            errors += 1

    # ── git hooks ─────────────────────────────────────────────────
    if repo:
        hooks = os.path.join(repo, '.git', 'hooks')
        pc  = os.path.exists(os.path.join(hooks, 'post-commit'))
        pco = os.path.exists(os.path.join(hooks, 'post-checkout'))
        if pc and pco:
            _row(True, 'git hooks', 'post-commit + post-checkout')
        elif pc:
            _row(None, 'git hooks', 'post-commit only — re-run `cram init` to add post-checkout')
        else:
            _row(None, 'git hooks not installed', 'run `cram hook install` to enable auto-sync on commit')

    # ── models ────────────────────────────────────────────────────
    print()
    print('  Models:')
    try:
        available = discover_models()
        if not available:
            _row(False, 'no models found')
            errors += 1
            print()
            print('  Set one of these environment variables:')
            print('    export ANTHROPIC_API_KEY=sk-ant-...    # Claude Haiku + Sonnet')
            print('    export OPENAI_API_KEY=sk-...           # GPT-4o Mini + GPT-4o')
            print('    export GEMINI_API_KEY=...              # Gemini 2.0 Flash + 2.5 Pro')
            print('    # or install Ollama for free local inference (auto-detected)')
            print('    # or install the `claude` CLI (auto-detected, no key needed)')
        else:
            ctx_m  = pick_context_model(available)
            code_m = pick_coding_model(available)
            _row(True, 'context model', ctx_m['name']  if ctx_m  else '—')
            _row(True, 'coding model',  code_m['name'] if code_m else '—')
            other_providers = sorted({
                m['provider'] for m in available
                if m not in (ctx_m, code_m)
            })
            if other_providers:
                _row(True, 'also available', ', '.join(other_providers))
    except Exception as exc:
        _row(None, f'model discovery error: {exc}')

    # ── tray deps (optional) ──────────────────────────────────────
    print()
    try:
        import pystray, webview  # noqa: F401
        _row(True, 'tray deps', 'pystray + webview')
    except ImportError:
        _row(None, 'tray app not installed',
             "optional — pip install 'cram-ai[tray]' for the menu bar app")

    # ── summary ───────────────────────────────────────────────────
    print()
    if errors == 0:
        print('  All checks passed.\n')
    else:
        print(f'  {errors} error(s) found — see above for fixes.\n')

    sys.exit(0 if errors == 0 else 1)
