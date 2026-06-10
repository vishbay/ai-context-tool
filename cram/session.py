"""Session metadata — tracks when the current task was set and the grace period."""

from __future__ import annotations
import datetime as _dt
import json
import os
import re
import time
from datetime import datetime

from cram.context_dir import resolve_context_dir

SESSION_FILE = 'session.json'


def _session_path(root: str) -> str:
    return os.path.join(resolve_context_dir(root), SESSION_FILE)


def save_session(root: str, task: str, grace_seconds: int | None = None) -> str:
    """Write session.json and return a human-readable expiry time string."""
    if grace_seconds is None:
        grace_seconds = int(os.environ.get('CRAM_TASK_GRACE_SECONDS', str(10 * 60)))
    data = {
        'task':          task,
        'set_at':        time.time(),
        'grace_seconds': grace_seconds,
    }
    path = _session_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

    expiry_ts  = data['set_at'] + grace_seconds
    expiry_str = datetime.fromtimestamp(expiry_ts).strftime('%H:%M')
    return expiry_str


def set_last_slot(root: str, slug: str) -> None:
    """Record the most recently active task slot slug in session.json."""
    path = _session_path(root)
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
    data['last_slot'] = slug
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def get_last_slot(root: str) -> str | None:
    """Return the slug of the most recently active task slot, or None."""
    path = _session_path(root)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get('last_slot') or None
    except Exception:
        return None


def _task_slug(task: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', task.lower())[:40].strip('-')
    return slug or 'unnamed'


def archive_task(root: str, source_path: str) -> None:
    """Canonical archive implementation: append the task in source_path to TASK_HISTORY.jsonl.

    Skips if the file doesn't exist, is empty, or contains the session-ended placeholder.
    Always writes slug + ts + task fields.
    """
    try:
        if not source_path or not os.path.exists(source_path):
            return
        content = open(source_path, errors='ignore').read().strip()
        if not content or '<!-- Session ended' in content:
            return
        task = ''
        lines = content.splitlines()
        for i, line in enumerate(lines):
            s = line.strip()
            if s == '## Task':
                for j in range(i + 1, len(lines)):
                    candidate = lines[j].strip()
                    if candidate and not candidate.startswith('#') and '<!--' not in candidate:
                        task = candidate
                        break
                break
            if s.startswith('# Task:'):
                task = s[len('# Task:'):].strip()
                break
        if not task:
            return
        entry = {
            'ts':   _dt.datetime.now(_dt.timezone.utc).isoformat(),
            'task': task,
            'slug': _task_slug(task),
        }
        from cram.context_dir import resolve_context_dir
        history_path = os.path.join(resolve_context_dir(root), 'TASK_HISTORY.jsonl')
        with open(history_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass


def load_session(root: str) -> dict | None:
    path = _session_path(root)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def touch_session(root: str) -> str:
    """Refresh set_at to now (extend grace period). Returns new expiry time string."""
    session = load_session(root)
    if session is None:
        return '(no active session)'
    grace   = session.get('grace_seconds', 600)
    task    = session.get('task', '')
    return save_session(root, task, grace)


def session_age(root: str) -> float | None:
    """Seconds since the session was set, or None if no session exists."""
    session = load_session(root)
    if session is None:
        return None
    return time.time() - session.get('set_at', 0.0)


def session_within_grace(root: str) -> bool:
    """True if the current session is still within its grace period."""
    session = load_session(root)
    if session is None:
        return False
    age   = time.time() - session.get('set_at', 0.0)
    grace = session.get('grace_seconds', 600)
    return age < grace


def clear_session(root: str) -> None:
    path = _session_path(root)
    if os.path.exists(path):
        os.remove(path)


def _continue_main() -> None:
    import sys
    from cram.utils import find_git_root
    start = sys.argv[1] if len(sys.argv) > 1 else '.'
    root  = find_git_root(start)
    session = load_session(root)
    if session is None:
        print("No active session — set one with `cram task \"...\"`.")
        sys.exit(1)
    expiry = touch_session(root)
    grace  = session.get('grace_seconds', 600)
    print(f"Session extended — context will reset on commit after {expiry} "
          f"({int(grace)}s grace).")
