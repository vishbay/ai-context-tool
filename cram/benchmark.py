"""cram benchmark — model the cache-write cost of each context-delivery strategy.

cram's job is to minimise *cache writes* — the most expensive token class.
A 5-minute-TTL cache write costs 1.25x base input; a cache read costs 0.1x.
So the win is not "fewer tokens" — it's keeping an expensive shared prefix
written ONCE and read cheaply thereafter, instead of re-writing it on every task.

Two delivery strategies are compared:

  Prefix injection (legacy --target claude)
      The frozen context is rewritten into a prefix-loaded file (CLAUDE.md) on
      every `cram task`. Because caching is a prefix match, each rewrite forces
      a full re-WRITE of that content on the next request → N writes per session.

  Stable prefix + tool result (MCP, recommended)
      The frozen context (ARCHITECTURE/SYMBOLS/DECISIONS) stays byte-identical
      across the session → written once, READ at 0.1x on every later request.
      Per-task context is delivered as a tool result (message content), which
      never invalidates the cached prefix.

Token counts here are the rough len/4 heuristic — fine for relative comparison,
not billing. For exact counts use the Anthropic token-counting endpoint.
"""

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

# Base input price per 1M tokens. Cache write = base x 1.25 (5-min TTL),
# cache read = base x 0.1. (platform.claude.com pricing.)
_MODELS: dict[str, float] = {
    'Opus 4.8':   5.00,
    'Sonnet 4.6': 3.00,
    'Haiku 4.5':  1.00,
}
WRITE_MULT = 1.25   # 5-minute-TTL cache write
READ_MULT  = 0.10   # cache read

# Minimum cacheable prefix per model family. Below this nothing caches —
# no write, but no read savings either, so the frozen layer must clear it.
_CACHE_MIN: dict[str, int] = {
    'Opus 4.8':   4096,
    'Sonnet 4.6': 2048,
    'Haiku 4.5':  4096,
}

# How many `cram task` invocations a developer runs against one warm cache
# before it expires. Override with AICONTEXT_TASKS_PER_SESSION.
TASKS_PER_SESSION = int(os.environ.get('AICONTEXT_TASKS_PER_SESSION', '4'))

# Frozen layer = the stable, cached prefix. Volatile layer = per-task payload.
_FROZEN_FILES   = ('ARCHITECTURE.md', 'SYMBOLS.md', 'DECISIONS.md')
_VOLATILE_FILES = ('CURRENT_TASK.md',)


def _count_repo_tokens(root: str) -> tuple[int, int]:
    """Return (total_tokens, file_count) for all source files. Kept for callers."""
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


def _file_tokens(context_dir: str, names: tuple[str, ...]) -> dict[str, int]:
    """Return {filename: tokens} for the named context files that exist."""
    out: dict[str, int] = {}
    for fname in names:
        p = os.path.join(context_dir, fname)
        if os.path.exists(p):
            try:
                with open(p, errors='ignore') as f:
                    out[fname] = len(f.read()) // 4
            except OSError:
                pass
    return out


def _bar(ratio: float, width: int = 24) -> str:
    filled = max(0, min(width, round(ratio * width)))
    return '█' * filled + '░' * (width - filled)


def run_benchmark(root: str) -> None:
    repo_name   = os.path.basename(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        print(f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.", file=sys.stderr)
        sys.exit(1)

    print(f"\nBenchmarking {repo_name} ...", end='', flush=True)
    repo_tokens, file_count = _count_repo_tokens(root)
    frozen   = _file_tokens(context_dir, _FROZEN_FILES)
    volatile = _file_tokens(context_dir, _VOLATILE_FILES)
    print(" done.\n")

    frozen_tok   = sum(frozen.values())
    volatile_tok = sum(volatile.values())
    n            = TASKS_PER_SESSION
    sep          = '─' * 70

    # ── Layers ────────────────────────────────────────────────────
    print(f"  Repo: {repo_name}  ({file_count} source files, ~{repo_tokens:,} tokens)\n")
    print("  Context layers")
    print(f"  {sep}")
    print(f"  Frozen prefix  (cached once, read thereafter)")
    for fname in _FROZEN_FILES:
        if fname in frozen:
            print(f"    {fname:<18} ~{frozen[fname]:>7,} tok")
    print(f"    {'= prefix total':<18} ~{frozen_tok:>7,} tok  "
          f"{_bar(frozen_tok / max(repo_tokens, 1))} {frozen_tok / max(repo_tokens, 1) * 100:.1f}% of repo")
    print(f"\n  Volatile context  (per task, delivered as a tool result)")
    for fname in _VOLATILE_FILES:
        if fname in volatile:
            print(f"    {fname:<18} ~{volatile[fname]:>7,} tok")
    print(f"  {sep}\n")

    # ── Cache-write model ─────────────────────────────────────────
    # Three scenarios, N tasks per warm-cache session:
    #
    #   1. No cram       → N writes of full repo  (model re-reads everything)
    #   2. Prefix inject → N writes of frozen_tok (CLAUDE.md rewritten each task)
    #   3. MCP delivery  → 1 write + (N-1) reads  (frozen prefix cached)
    #
    # The volatile per-task payload (CURRENT_TASK.md) rides as a tool result
    # on path 3 — it never invalidates the cached prefix.

    nocram_writes = n * repo_tokens
    inj_writes    = n * frozen_tok
    stable_writes = frozen_tok
    stable_reads  = (n - 1) * frozen_tok

    print(f"  Cache-write model  ·  {n} tasks per warm cache  ·  5-min TTL\n")
    print(f"  {'':<28}{'cache writes':>16}{'$/session':>13}{'$/100 sessions':>17}")
    print(f"  {sep}")

    for model, base in _MODELS.items():
        write_price  = base * WRITE_MULT / 1_000_000
        read_price   = base * READ_MULT  / 1_000_000
        nocram_cost  = nocram_writes  * write_price
        inj_cost     = inj_writes     * write_price
        stable_cost  = stable_writes  * write_price + stable_reads * read_price
        print(f"  {model}")
        print(f"    {'1. no cram (auto-index)':<26}{nocram_writes:>16,}{nocram_cost:>12.3f} "
              f"{nocram_cost * 100:>16.2f}")
        print(f"    {'2. cram prefix-injected':<26}{inj_writes:>16,}{inj_cost:>12.3f} "
              f"{inj_cost * 100:>16.2f}")
        print(f"    {'3. cram MCP-delivered':<26}{stable_writes:>16,}{stable_cost:>12.3f} "
              f"{stable_cost * 100:>16.2f}")
        mcp_vs_nocram = nocram_cost - stable_cost
        mcp_vs_inj    = inj_cost    - stable_cost
        print(f"    {'→ MCP vs no-cram':<26}{'':>16}{mcp_vs_nocram:>12.3f} "
              f"{mcp_vs_nocram * 100:>16.2f}  saved")
        print(f"    {'→ MCP vs injected':<26}{'':>16}{mcp_vs_inj:>12.3f} "
              f"{mcp_vs_inj * 100:>16.2f}  saved")
        print()

    print(f"  {sep}")
    print(f"  Frozen prefix:  {frozen_tok:,} tok  ({frozen_tok / max(repo_tokens,1) * 100:.1f}% of repo)")
    print(f"  Per-task payload (tool result, never cache-written): ~{volatile_tok:,} tok\n")

    # ── Cache-minimum check (frozen layer must be cacheable) ──────
    print("  Cacheable-prefix check  (frozen layer must clear the minimum)")
    for model, _ in _MODELS.items():
        floor = _CACHE_MIN[model]
        ok    = frozen_tok >= floor
        mark  = '✓' if ok else '✗'
        note  = '' if ok else '  ← below minimum: prefix will NOT cache (sync more context)'
        print(f"    {mark} {model:<12} needs ≥ {floor:,} tok{note}")
    print()


def main() -> None:
    from cram.utils import find_git_root
    start = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    root  = find_git_root(os.path.abspath(start))
    run_benchmark(root)


if __name__ == '__main__':
    main()
