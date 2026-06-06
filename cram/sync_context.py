"""Post-session context update: refreshes ARCHITECTURE.md after a commit."""

import os
import subprocess
import sys

from cram.init import scan_structure
from cram.utils import call_model, strip_code_fence

MAX_LINES = int(os.environ.get('AICONTEXT_MAX_LINES', '300'))

CONTEXT_DIR = '.ai-context'


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
    return strip_code_fence(call_model(prompt))


def sync(root: str = '.') -> None:
    root = os.path.abspath(root)
    context_dir = os.path.join(root, CONTEXT_DIR)
    arch_path = os.path.join(context_dir, 'ARCHITECTURE.md')

    if not os.path.isdir(context_dir):
        print(
            f"Error: {CONTEXT_DIR}/ not found. Run `aicontext init` first.",
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

    print("Updating ARCHITECTURE.md via Haiku ...")
    updated = update_architecture_md(structure, diff, current)

    with open(arch_path, 'w') as f:
        f.write(updated)

    print(f"Done. {CONTEXT_DIR}/ARCHITECTURE.md updated.")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else '.'
    sync(target)


if __name__ == '__main__':
    main()
