"""cram benchmark — measure token savings for this repo."""

from __future__ import annotations
import os
import sys

CONTEXT_DIR = '.cram-ai-context'

_SKIP_DIRS = {
    '.git', '.venv', 'venv', 'node_modules', '__pycache__',
    'dist', 'build', '.next', 'coverage', CONTEXT_DIR,
    '.pytest_cache', '.github', '.devcontainer',
}
_SRC_EXTS = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.rb',
    '.java', '.md', '.json', '.toml', '.yaml', '.yml', '.html', '.css', '.rst',
}

# Claude pricing per 1M tokens (cache write / cache read)
_PRICING = {
    'Sonnet 4.6': (3.75,  0.30),
    'Opus 4.8':   (18.75, 1.50),
    'Haiku 4.5':  (0.30,  0.03),
}

# Cache minimum tokens by model family
_CACHE_MIN = {
    'opus':   4096,
    'sonnet': 1024,
    'haiku':  1024,
}


def _count_repo_tokens(root: str) -> tuple[int, int]:
    """Return (total_tokens, file_count) for all source files."""
    total, count = 0, 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith('.')
        ]
        for fname in filenames:
            if os.path.splitext(fname)[1] in _SRC_EXTS:
                try:
                    with open(os.path.join(dirpath, fname), errors='ignore') as f:
                        total += len(f.read()) // 4
                    count += 1
                except OSError:
                    pass
    return total, count


def _orientation_tokens(root: str, tree_tokens: int = 2_000) -> int:
    """Estimate tokens for a minimal orientation set.

    = file tree estimate + README + key config + 5 largest source files.
    Represents what an AI tool loads before any user query.
    """
    total = tree_tokens
    for name in ('README.md', 'README.rst', 'pyproject.toml', 'package.json'):
        p = os.path.join(root, name)
        if os.path.exists(p):
            try:
                with open(p, errors='ignore') as f:
                    total += len(f.read()) // 4
            except OSError:
                pass
    candidates: list[tuple[int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith('.')
        ]
        for fname in filenames:
            if os.path.splitext(fname)[1] in {'.py', '.ts', '.js', '.go', '.rs'}:
                p = os.path.join(dirpath, fname)
                try:
                    candidates.append((os.path.getsize(p), p))
                except OSError:
                    pass
    for _, p in sorted(candidates, reverse=True)[:5]:
        try:
            with open(p, errors='ignore') as f:
                total += len(f.read()) // 4
        except OSError:
            pass
    return total


def _context_file_stats(context_dir: str) -> tuple[dict[str, tuple[int, int]], int]:
    """Return ({filename: (lines, tokens)}, total_tokens)."""
    files = ['ARCHITECTURE.md', 'DECISIONS.md', 'CURRENT_TASK.md', 'SYMBOLS.md']
    result: dict[str, tuple[int, int]] = {}
    total = 0
    for fname in files:
        p = os.path.join(context_dir, fname)
        if os.path.exists(p):
            try:
                with open(p, errors='ignore') as f:
                    content = f.read()
                tokens = len(content) // 4
                result[fname] = (content.count('\n'), tokens)
                total += tokens
            except OSError:
                pass
    return result, total


def _bar(ratio: float, width: int = 28) -> str:
    filled = round(ratio * width)
    return '█' * filled + '░' * (width - filled)


def run_benchmark(root: str) -> None:
    repo_name = os.path.basename(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        print(
            f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\nBenchmarking {repo_name} ...", end='', flush=True)
    full_tokens, file_count = _count_repo_tokens(root)
    orient_tokens = _orientation_tokens(root)
    ctx_stats, ctx_tokens = _context_file_stats(context_dir)
    print(" done.\n")

    col = 40
    sep = '─' * 68

    # ── Token summary ─────────────────────────────────────────────
    print(f"  Repo: {repo_name}  ({file_count} source files)\n")
    print(f"  {'':38}  {'Sonnet/session':>14}  {'Opus/session':>12}")
    print(f"  {sep}")

    def cost_row(label: str, tokens: int) -> None:
        s_write = tokens / 1_000_000 * 3.75
        o_write = tokens / 1_000_000 * 18.75
        bar = _bar(min(tokens / max(full_tokens, 1), 1.0))
        print(f"  {label:<38}  ${s_write:>13.3f}  ${o_write:>11.3f}")

    cost_row(f"Without cram — full repo ({full_tokens:,} tokens)", full_tokens)
    cost_row(f"Without cram — orientation ({orient_tokens:,} tokens)", orient_tokens)
    cost_row(f"With cram — context ({ctx_tokens:,} tokens)", ctx_tokens)
    print(f"  {sep}")

    reduction_full   = (1 - ctx_tokens / max(full_tokens, 1)) * 100
    reduction_orient = (1 - ctx_tokens / max(orient_tokens, 1)) * 100
    save_s = (full_tokens - ctx_tokens) / 1_000_000 * 3.75
    save_o = (full_tokens - ctx_tokens) / 1_000_000 * 18.75

    print(f"\n  Token reduction vs full repo:   {reduction_full:.1f}%")
    print(f"  Token reduction vs orientation: {reduction_orient:.1f}%")
    print(f"  Saving per session:   ${save_s:.3f} (Sonnet)  ${save_o:.3f} (Opus)")
    print(f"  Saving over 100 sessions:  ~${save_s*100:.0f} (Sonnet)  ~${save_o*100:.0f} (Opus)")

    # ── Visual bar ────────────────────────────────────────────────
    print()
    w = 50
    full_bar   = '█' * w
    orient_bar = '█' * round(orient_tokens / max(full_tokens, 1) * w)
    ctx_bar    = '█' * max(round(ctx_tokens  / max(full_tokens, 1) * w), 1)
    print(f"  Full repo   {full_bar} {full_tokens:,}")
    print(f"  Orientation {orient_bar:<{w}} {orient_tokens:,}")
    print(f"  Cram        {ctx_bar:<{w}} {ctx_tokens:,}")

    # ── Context file breakdown ────────────────────────────────────
    print(f"\n  Context file breakdown:")
    for fname, (lines, tokens) in ctx_stats.items():
        bar = _bar(tokens / max(ctx_tokens, 1), width=16)
        print(f"    {fname:<26}  {lines:>4} lines  {tokens:>6,} tok  {bar}")

    # ── Cache minimum check ───────────────────────────────────────
    print(f"\n  Cache minimum check:")
    for family, min_tok in _CACHE_MIN.items():
        ok = ctx_tokens >= min_tok
        mark = '✓' if ok else '✗'
        note = '' if ok else f'  ← increase AICONTEXT_MAX_EXCERPT_LINES'
        label = family.capitalize()
        print(f"    {mark} {label:<8} ({min_tok:,} tokens minimum){note}")

    print()


def main() -> None:
    from cram.utils import find_git_root
    start = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    root  = find_git_root(os.path.abspath(start))
    run_benchmark(root)


if __name__ == '__main__':
    main()
