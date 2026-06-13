"""Shared context health helper — staleness + per-file token + budget status.

Used by the get_health() MCP tool and `cram status`.
"""
from __future__ import annotations
import os

from cram.status import get_status_dict
from cram.context_dir import resolve_context_dir
from cram.cost_model import FILE_BUDGETS, budget_status

_TRACKED = (
    'ARCHITECTURE.md', 'SYMBOLS.md', 'DECISIONS.md',
    'GOTCHAS.md', 'CURRENT_TASK.md',
)


def context_health(root: str) -> dict:
    """Return staleness + per-file token + budget status for root.

    Keys:
        staleness_score   int 0–10
        staleness_band    'fresh' | 'acceptable' | 'stale' | 'critical'
        commits_since_sync  int | None
        state             'fresh' | 'stale' | 'not-init'  (back-compat)
        last_commit_age   str | None
        files             dict[fname -> {tokens, lines, budget, budget_status}]
    """
    root = os.path.abspath(root)
    status = get_status_dict(root)
    context_dir = resolve_context_dir(root)
    files: dict = {}

    for fname in _TRACKED:
        fpath = os.path.join(context_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, errors='ignore') as f:
                content = f.read()
            tokens = len(content) // 4
            files[fname] = {
                'tokens':        tokens,
                'lines':         content.count('\n'),
                'budget':        FILE_BUDGETS.get(fname),
                'budget_status': budget_status(fname, tokens),
            }
        except OSError:
            pass

    return {
        'staleness_score':    status.get('staleness_score', 0),
        'staleness_band':     status.get('staleness_band', 'fresh'),
        'commits_since_sync': status.get('commits_since_sync'),
        'state':              status.get('state', 'fresh'),
        'last_commit_age':    status.get('last_commit_age'),
        'files':              files,
    }
