# Current Task

## Task
tui history tab: new task not showing up, clean up session ended comment task, add loading indicator for check results

## Scope
- cram/

## Out of Scope
<!-- Add directories/files the agent should NOT touch -->

## Definition of Done
<!-- Add explicit acceptance criteria before closing this task -->

## Models
- Context loaded by: `Claude Haiku (claude CLI)`
- **Switch to `Claude Opus (claude CLI)` for coding** ←

## Relevant Files

### cram/ui.py
```py
[lines 399–621 of 621]

    class ActionsPane(VerticalScroll):
        def compose(self) -> ComposeResult:
            yield Static(_ACTIONS_MENU, id='actions-menu')
            yield Label('[b]Output[/b]', id='output-header')
            yield RichLog(id='output-log', highlight=True, markup=True, wrap=True)

        def start_command(self, cmd_str: str) -> None:
            log = self.query_one('#output-log', RichLog)
            log.clear()
            log.write(f'[dim]$ {cmd_str}[/dim]\n')

        def append_output(self, text: str) -> None:
            self.query_one('#output-log', RichLog).write(text)

    # ── Main app ─────────────────────────────────────────────────

    class CramApp(App):
        TITLE = 'cram-ai'
        CSS = """
        DecisionsPane, SessionsPane, HealthPane, ActionsPane {
            padding: 1 2;
        }
        Label#pending-header, Label#accepted-header, Label#slots-header,
        Label#output-header {
            color: $accent;
            padding: 1 0 0 0;
        }
        DataTable {
            height: auto;
        }
  ··· 152 lines omitted ···
            self._run_cli(['cram', 'doctor'])
            self.notify('Running cram doctor…')

        @work
        async def action_task(self) -> None:
            description = await self.push_screen_wait(TaskInputModal())
            if description:
                self._run_cli(['cram', 'task', description])
                self.notify(f'Running cram task "{description}"…')

    return CramApp


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    from cram.utils import find_git_root

    _require_textual()

    parser = argparse.ArgumentParser(
        prog='cram ui',
        description='TUI dashboard — decisions, session efficiency, context health',
    )
    parser.add_argument('--path', default=None, metavar='REPO_PATH')
    args = parser.parse_args()

    start = os.path.abspath(args.path) if args.path else os.getcwd()
    try:
        root = find_git_root(start)
    except Exception:
        root = start

    AppClass = _build_app(root)
    AppClass().run()


if __name__ == '__main__':
    main()

```

### cram/session.py
```py
[lines 3–82 of 94]
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
  ··· 12 more lines

```
