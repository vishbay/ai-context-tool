"""aicontext status — show .ai-context/ file freshness and repo sync state."""

from __future__ import annotations
import os
import subprocess
import sys
from datetime import datetime, timezone

CONTEXT_DIR = '.ai-context'
CONTEXT_FILES = ['ARCHITECTURE.md', 'DECISIONS.md', 'CURRENT_TASK.md', '.gitignore']


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


def show_status(root: str = '.') -> None:
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)

    if not os.path.isdir(context_dir):
        print(f"No .ai-context/ found in {root}.")
        print("Run `aicontext init` to set it up.")
        sys.exit(1)

    last_commit = _last_commit_time()

    print(f".ai-context/  ({context_dir})")
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
        print("ARCHITECTURE.md is behind the latest commit. Run `aicontext sync` to update.")
    else:
        print("Context is up to date.")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else '.'
    show_status(target)


if __name__ == '__main__':
    main()
