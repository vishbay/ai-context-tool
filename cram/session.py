"""Session metadata — tracks when the current task was set and the grace period."""

from __future__ import annotations
import json
import os
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
