"""Post-session context update: refreshes ARCHITECTURE.md after a commit."""

import os
import subprocess
import sys
import time

from cram.init import scan_structure
from cram.utils import call_context_model, strip_code_fence

MAX_LINES = int(os.environ.get('AICONTEXT_MAX_LINES', '300'))
# A commit within this window of setting a task is treated as mid-session.
TASK_GRACE_SECONDS = int(os.environ.get('CRAM_TASK_GRACE_SECONDS', str(10 * 60)))

CONTEXT_DIR = '.cram-ai-context'

SESSION_ENDED_TEMPLATE = """\
# Current Task

## Task
<!-- Session ended on commit. Run `cram task "..."` or use the tray to begin a new task. -->

## Relevant Files
<!-- Populated by `cram task "..."` -->
"""


def get_git_diff() -> str:
    try:
        return subprocess.check_output(
            ['git', 'diff', 'HEAD~1', '--stat', '--unified=2'],
            stderr=subprocess.DEVNULL,
        ).decode()
    except subprocess.CalledProcessError:
        # Only one commit — diff the initial commit itself
        return subprocess.check_output(
            ['git', 'show', '--stat', '--unified=2', 'HEAD'],
            stderr=subprocess.DEVNULL,
        ).decode()


def update_architecture_md(structure: str, diff: str, current: str) -> str:
    prompt = (
        f"Update this ARCHITECTURE.md based on recent changes.\n"
        f"Keep it under {MAX_LINES} lines. Only update what changed.\n\n"
        f"Current ARCHITECTURE.md:\n{current}\n\n"
        f"Repo structure:\n{structure}\n\n"
        f"Recent git diff:\n{diff}\n\n"
        f"Return only the updated markdown, no explanation."
    )
    return strip_code_fence(call_context_model(prompt))


def reset_task(root: str) -> None:
    """Unconditionally reset CURRENT_TASK.md and all target files to the session-ended placeholder."""
    from cram import targets as _targets
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)
    task_path = os.path.join(context_dir, 'CURRENT_TASK.md')
    if not os.path.isdir(context_dir):
        return
    with open(task_path, 'w') as f:
        f.write(SESSION_ENDED_TEMPLATE)
    _targets.write_to_all_detected(root, SESSION_ENDED_TEMPLATE)


def _task_has_real_content(task_path: str) -> bool:
    """Return True if CURRENT_TASK.md has an actual task set (not the blank template)."""
    if not os.path.exists(task_path):
        return False
    with open(task_path) as f:
        content = f.read()
    return '<!-- Replace with your task description -->' not in content \
        and '<!-- Session ended on commit.' not in content


def _reset_task_if_session_ended(root: str, context_dir: str) -> None:
    """Reset CURRENT_TASK.md and all target files after a commit, unless the
    task was set within the grace period (treat as mid-session commit)."""
    from cram import targets as _targets

    task_path = os.path.join(context_dir, 'CURRENT_TASK.md')

    if not _task_has_real_content(task_path):
        return  # nothing to reset

    age = time.time() - os.path.getmtime(task_path)
    if age < TASK_GRACE_SECONDS:
        print(f"Task set {int(age)}s ago — keeping context (within {TASK_GRACE_SECONDS}s grace period).")
        return

    with open(task_path, 'w') as f:
        f.write(SESSION_ENDED_TEMPLATE)

    written = _targets.write_to_all_detected(root, SESSION_ENDED_TEMPLATE)
    for path in written:
        print(f"Session ended — cleared {os.path.relpath(path, root)}")
    print("Set a new task with `cram task \"...\"` or via the tray.")


def sync(root: str = '.') -> None:
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)
    arch_path = os.path.join(context_dir, 'ARCHITECTURE.md')

    if not os.path.isdir(context_dir):
        print(
            f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    current = ''
    if os.path.exists(arch_path):
        with open(arch_path) as f:
            current = f.read()

    print("Getting git diff ...")
    diff = get_git_diff()

    print("Scanning repo structure ...")
    structure = scan_structure(root)

    from cram.utils import get_model_recommendations
    ctx_model, _ = get_model_recommendations()
    print(f"Updating ARCHITECTURE.md via {ctx_model} ...")
    updated = update_architecture_md(structure, diff, current)

    with open(arch_path, 'w') as f:
        f.write(updated)

    print(f"Done. {CONTEXT_DIR}/ARCHITECTURE.md updated.")

    _reset_task_if_session_ended(root, context_dir)


def main() -> None:
    from cram.utils import find_git_root
    target = find_git_root(sys.argv[1] if len(sys.argv) > 1 else '.')
    sync(target)


if __name__ == '__main__':
    main()
