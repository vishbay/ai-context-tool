"""cram status — show .cram-ai-context/ file freshness and repo sync state."""

from __future__ import annotations
import os
import subprocess
import sys
from datetime import datetime, timezone

CONTEXT_DIR = '.cram-ai-context'
CONTEXT_FILES = ['ARCHITECTURE.md', 'DECISIONS.md', 'GOTCHAS.md', 'CURRENT_TASK.md', '.gitignore']

# Commits-since-update that maps to score 10 (critical). Override via env.
STALE_CRITICAL_COMMITS = int(os.environ.get('CRAM_STALE_CRITICAL_COMMITS', '10'))


def _mtime(path: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except OSError:
        return None


def _last_commit_time() -> datetime | None:
    try:
        ts = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ct'],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def _age_label(dt: datetime) -> str:
    now = datetime.now(tz=timezone.utc)
    secs = int((now - dt).total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _line_count(path: str) -> int:
    try:
        with open(path) as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _commits_since_context_update(root: str) -> int | None:
    """Commits on HEAD since ARCHITECTURE.md was last committed. None if unknown."""
    rel = os.path.join(CONTEXT_DIR, 'ARCHITECTURE.md')
    try:
        sha = subprocess.check_output(
            ['git', 'log', '-1', '--format=%H', '--', rel],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        if not sha:
            return None
        count = subprocess.check_output(
            ['git', 'rev-list', '--count', f'{sha}..HEAD'],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return int(count)
    except (subprocess.CalledProcessError, ValueError):
        return None


def staleness_score(commits_since: int | None, arch_behind_commit: bool) -> int:
    """0–10. Primary: commits since context last changed; fallback: mtime signal.

    Falls back to the legacy mtime signal (arch_behind_commit) when the commit
    count is unknown: behind → 6 (stale), else 0 (fresh).
    """
    if commits_since is None:
        return 6 if arch_behind_commit else 0
    scaled = round(commits_since / STALE_CRITICAL_COMMITS * 10)
    return max(0, min(10, scaled))


def staleness_band(score: int) -> str:
    if score <= 2: return 'fresh'
    if score <= 5: return 'acceptable'
    if score <= 7: return 'stale'
    return 'critical'


def get_status_dict(root: str = '.') -> dict:
    """Return structured status data for programmatic use (tray server, etc.)."""
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        return {'state': 'not-init', 'files': {}, 'last_commit_age': None}

    last_commit = _last_commit_time()
    now = datetime.now(tz=timezone.utc)
    files: dict = {}
    arch_behind_commit = False

    for fname in ('ARCHITECTURE.md', 'DECISIONS.md', 'GOTCHAS.md', 'CURRENT_TASK.md'):
        fpath = os.path.join(context_dir, fname)
        if not os.path.exists(fpath):
            continue
        mtime = _mtime(fpath)
        if mtime:
            age_secs = int((now - mtime).total_seconds())
            files[fname] = {
                'age_secs':  age_secs,
                'age_label': _age_label(mtime),
                'lines':     _line_count(fpath),
            }
            if fname == 'ARCHITECTURE.md' and last_commit and last_commit > mtime:
                arch_behind_commit = True

    commits_since = _commits_since_context_update(root)
    score = staleness_score(commits_since, arch_behind_commit)
    band  = staleness_band(score)

    return {
        'state':              'stale' if band in ('stale', 'critical') else 'fresh',
        'staleness_score':    score,
        'staleness_band':     band,
        'commits_since_sync': commits_since,
        'files':              files,
        'last_commit_age':    _age_label(last_commit) if last_commit else None,
    }


def show_status(root: str = '.') -> None:
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        print(f"No .cram-ai-context/ found in {root}.")
        print("Run `cram init` to set it up.")
        sys.exit(1)

    from cram.cost_model import budget_status as _budget_status

    last_commit = _last_commit_time()

    print(f".cram-ai-context/  ({context_dir})")
    print()

    for fname in CONTEXT_FILES:
        fpath = os.path.join(context_dir, fname)
        if not os.path.exists(fpath):
            print(f"  {'MISSING':10s}  {fname}")
            continue

        mtime = _mtime(fpath)
        age = _age_label(mtime) if mtime else '?'
        lines = _line_count(fpath)

        flag = ''
        if fname == 'ARCHITECTURE.md' and last_commit and mtime and last_commit > mtime:
            flag = '  ← stale (commit after last sync)'

        try:
            with open(fpath, errors='ignore') as f:
                tokens = len(f.read()) // 4
            bstatus = _budget_status(fname, tokens)
            if bstatus == 'over':
                flag += f'  (over budget: {tokens} tok)'
            elif bstatus == 'near':
                flag += f'  (near budget: {tokens} tok)'
        except OSError:
            pass

        print(f"  {age:12s}  {fname}  ({lines} lines){flag}")

    print()
    status = get_status_dict(root)
    score   = status['staleness_score']
    band    = status['staleness_band']
    commits = status['commits_since_sync']

    if last_commit:
        print(f"Last commit : {_age_label(last_commit)}")

    msg = f"Context health : {band} ({score}/10)"
    if commits is not None:
        plural = 's' if commits != 1 else ''
        msg += f" — {commits} commit{plural} since last sync."
        if band in ('stale', 'critical'):
            msg += " Run `cram sync`."
    print(msg)


def main() -> None:
    from cram.utils import find_git_root
    target = find_git_root(sys.argv[1] if len(sys.argv) > 1 else '.')
    show_status(target)


if __name__ == '__main__':
    main()
