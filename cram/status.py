"""cram status — show .cram-ai-context/ file freshness and repo sync state."""

from __future__ import annotations
import os
import subprocess
import sys
from datetime import datetime, timezone

CONTEXT_DIR = '.cram-ai-context'
CONTEXT_FILES = ['ARCHITECTURE.md', 'DECISIONS.md', 'GOTCHAS.md', 'CURRENT_TASK.md', '.gitignore']


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


def get_status_dict(root: str = '.') -> dict:
    """Return structured status data for programmatic use (tray server, etc.)."""
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        return {'state': 'not-init', 'files': {}, 'last_commit_age': None}

    last_commit = _last_commit_time()
    now = datetime.now(tz=timezone.utc)
    files: dict = {}
    stale = False

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
                stale = True

    return {
        'state':            'stale' if stale else 'fresh',
        'files':            files,
        'last_commit_age':  _age_label(last_commit) if last_commit else None,
    }


def show_status(root: str = '.') -> None:
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        print(f"No .cram-ai-context/ found in {root}.")
        print("Run `cram init` to set it up.")
        sys.exit(1)

    last_commit = _last_commit_time()

    print(f".cram-ai-context/  ({context_dir})")
    print()

    stale = False
    for fname in CONTEXT_FILES:
        fpath = os.path.join(context_dir, fname)
        if not os.path.exists(fpath):
            print(f"  {'MISSING':10s}  {fname}")
            continue

        mtime = _mtime(fpath)
        age = _age_label(mtime) if mtime else '?'
        lines = _line_count(fpath)

        if fname == 'ARCHITECTURE.md' and last_commit and mtime and last_commit > mtime:
            flag = '  ← stale (commit after last sync)'
            stale = True
        else:
            flag = ''

        print(f"  {age:12s}  {fname}  ({lines} lines){flag}")

    print()
    if last_commit:
        print(f"Last commit : {_age_label(last_commit)}")
    if stale:
        print("ARCHITECTURE.md is behind the latest commit. Run `cram sync` to update.")
    else:
        print("Context is up to date.")


def main() -> None:
    from cram.utils import find_git_root
    target = find_git_root(sys.argv[1] if len(sys.argv) > 1 else '.')
    show_status(target)


if __name__ == '__main__':
    main()
