"""Single source of truth for cram's token-cost model.

Used by the tray /metrics endpoint and `cram benchmark` so the numbers never
diverge. Token counts are the len/4 heuristic — fine for relative comparison,
not billing.
"""
from __future__ import annotations
import os
from dataclasses import dataclass

# Base input price per 1M tokens (platform.claude.com).
MODEL_BASE = {
    'Opus 4.8':   5.00,
    'Sonnet 4.6': 3.00,
    'Haiku 4.5':  1.00,
}
WRITE_MULT = 1.25   # 5-min-TTL cache write
READ_MULT  = 0.10   # cache read

# Workload assumptions (overridable via env).
SESSIONS_PER_DAY  = int(os.environ.get('AICONTEXT_SESSIONS_PER_DAY',  '4'))
TASKS_PER_SESSION = int(os.environ.get('AICONTEXT_TASKS_PER_SESSION', '4'))

# Orientation model: without cram, the agent cold-starts each SESSION by reading
# ~N raw files to orient. This is the cost cram removes — NOT a full-repo
# rewrite, and billed at base input (tool-result reads), not cache write.
ORIENT_FILES = int(os.environ.get('AICONTEXT_ORIENT_FILES', '8'))


@dataclass
class CostInputs:
    repo_tokens: int
    repo_files:  int
    frozen_tok:  int


def orientation_tokens(repo_tokens: int, repo_files: int) -> int:
    """Tokens read to cold-start orient, per session, without cram."""
    if repo_files <= 0 or repo_tokens <= 0:
        return 0
    avg_file = repo_tokens / repo_files
    return int(min(repo_tokens, ORIENT_FILES * avg_file))


# Soft per-file token budgets for the frozen context layer. Warnings only.
# Calibrated to cram's output (ARCHITECTURE is line-budgeted ~300 lines), NOT
# the 400-tok external target. SYMBOLS scales with repo size → no flat cap.
FILE_BUDGETS = {
    'ARCHITECTURE.md': int(os.environ.get('CRAM_BUDGET_ARCHITECTURE', '3000')),
    'DECISIONS.md':    int(os.environ.get('CRAM_BUDGET_DECISIONS',    '1500')),
    'GOTCHAS.md':      int(os.environ.get('CRAM_BUDGET_GOTCHAS',      '800')),
    'CURRENT_TASK.md': int(os.environ.get('CRAM_BUDGET_TASK',         '2000')),
}


def budget_status(fname: str, tokens: int) -> str:
    """'ok' | 'near' (≥80%) | 'over' (>100%) | 'none' (no budget for this file)."""
    limit = FILE_BUDGETS.get(fname)
    if not limit:
        return 'none'
    if tokens > limit:
        return 'over'
    if tokens >= 0.8 * limit:
        return 'near'
    return 'ok'


def daily_costs(inp: CostInputs, base_price: float) -> dict:
    """Return modeled daily costs for one model's base input price."""
    base  = base_price / 1_000_000
    write = base * WRITE_MULT
    read  = base * READ_MULT
    S, T  = SESSIONS_PER_DAY, TASKS_PER_SESSION

    orient = orientation_tokens(inp.repo_tokens, inp.repo_files)
    # Without cram: re-orient once per session at base input price.
    nocram = S * orient * base
    # With cram: frozen layer write-once/session + read (T-1)×; orientation gone.
    cram   = S * (inp.frozen_tok * write + (T - 1) * inp.frozen_tok * read)
    return {
        'orient_tokens': orient,
        'nocram_daily':  nocram,
        'cram_daily':    cram,
        'daily_saving':  max(0.0, nocram - cram),
    }
