"""Measured token usage from Claude Code transcripts."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

from cram.cost_model import MODEL_BASE, WRITE_MULT, READ_MULT

_DEFAULT_MODEL = 'Sonnet 4.6'


def _dashed_path(repo_root: str) -> str:
    """Convert an absolute path to the Claude Code dashed-directory form."""
    return os.path.abspath(repo_root).replace(os.sep, '-')


def measured_usage(repo_root: str, days: int = 7) -> dict | None:
    """Sum real token usage from Claude Code transcripts for this repo.

    Returns {available, days, sessions, writes, reads, input, output, est_cost}
    or None if no transcript directory is found.
    """
    dashed = _dashed_path(repo_root)
    transcript_dir = Path.home() / '.claude' / 'projects' / dashed
    if not transcript_dir.is_dir():
        return None

    cutoff = time.time() - days * 86400
    writes = reads = input_tok = output_tok = 0
    sessions = 0

    for jsonl_path in sorted(transcript_dir.glob('*.jsonl')):
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        sessions += 1
        try:
            with open(jsonl_path, errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg   = entry.get('message') or {}
                    usage = msg.get('usage') or {}
                    writes     += usage.get('cache_creation_input_tokens', 0)
                    reads      += usage.get('cache_read_input_tokens', 0)
                    input_tok  += usage.get('input_tokens', 0)
                    output_tok += usage.get('output_tokens', 0)
        except OSError:
            continue

    if sessions == 0 and writes == reads == input_tok == output_tok == 0:
        return None

    base        = MODEL_BASE.get(_DEFAULT_MODEL, 3.0) / 1_000_000
    write_price = base * WRITE_MULT
    read_price  = base * READ_MULT
    est_cost    = writes * write_price + reads * read_price + input_tok * base

    return {
        'available': True,
        'days':      days,
        'sessions':  sessions,
        'writes':    writes,
        'reads':     reads,
        'input':     input_tok,
        'output':    output_tok,
        'est_cost':  round(est_cost, 4),
    }
