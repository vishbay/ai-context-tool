"""One-time setup: scans a repo, generates initial .ai-context/ files via Haiku."""

import os
import sys
import fnmatch

from cram.utils import call_model, strip_code_fence
from cram.hooks import install_hook

EXCLUDE_DIRS = {
    'node_modules', 'dist', 'build', '__pycache__',
    '.git', '.venv', 'venv', 'coverage', '.next',
    '.ai-context',
}

EXCLUDE_FILES = {
    'package-lock.json', 'yarn.lock', 'poetry.lock',
}

EXCLUDE_PATTERNS = {'*.min.js', '*.min.css'}

MAX_LINES = int(os.environ.get('AICONTEXT_MAX_LINES', '300'))


def _is_excluded_file(filename: str) -> bool:
    if filename in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(filename, pat) for pat in EXCLUDE_PATTERNS)


def scan_structure(root: str) -> str:
    """Return a compact directory tree as a string, excluding noise dirs."""
    lines = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded dirs in-place so os.walk skips them
        dirnames[:] = [d for d in sorted(dirnames) if d not in EXCLUDE_DIRS]

        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        indent = '  ' * depth
        folder = os.path.basename(dirpath) if rel != '.' else os.path.basename(root)
        lines.append(f"{indent}{folder}/")

        file_indent = '  ' * (depth + 1)
        for fname in sorted(filenames):
            if not _is_excluded_file(fname):
                lines.append(f"{file_indent}{fname}")

    return '\n'.join(lines)


def generate_architecture_md(structure: str) -> str:
    """Call Haiku to produce an initial ARCHITECTURE.md from the repo tree."""
    prompt = (
        f"You are a technical writer creating a concise ARCHITECTURE.md "
        f"for an AI coding assistant.\n\n"
        f"Repo structure:\n```\n{structure}\n```\n\n"
        f"Write a markdown document under {MAX_LINES} lines that covers:\n"
        f"1. What this repo does (inferred from file names)\n"
        f"2. Key directories and their purpose\n"
        f"3. Important files an AI should know about\n"
        f"4. Tech stack (inferred from file extensions and config files)\n\n"
        f"Be concise. No filler. Return only the markdown, no explanation."
    )
    return strip_code_fence(call_model(prompt))


def write_gitignore(context_dir: str) -> None:
    path = os.path.join(context_dir, '.gitignore')
    with open(path, 'w') as f:
        f.write("CURRENT_TASK.md\n")


DECISIONS_TEMPLATE = """\
# Architectural Decisions

## [DECISION-001] Example decision
- **Date:** YYYY-MM-DD
- **Status:** Accepted
- **Decision:** What was decided
- **Reason:** Why
- **Alternatives considered:** What else was weighed
"""

CURRENT_TASK_TEMPLATE = """\
# Current Task

## Task
<!-- Replace with your task description -->

## Relevant Files
<!-- Populated by `aicontext task "..."` -->
"""


def init_repo(target: str = '.') -> None:
    root = os.path.abspath(target)
    context_dir = os.path.join(root, '.ai-context')

    if os.path.exists(context_dir):
        print(f".ai-context/ already exists at {context_dir}. Skipping.")
        return

    print(f"Scanning {root} ...")
    structure = scan_structure(root)

    print("Generating ARCHITECTURE.md via Haiku ...")
    architecture = generate_architecture_md(structure)

    os.makedirs(context_dir, exist_ok=True)

    with open(os.path.join(context_dir, 'ARCHITECTURE.md'), 'w') as f:
        f.write(architecture)

    with open(os.path.join(context_dir, 'DECISIONS.md'), 'w') as f:
        f.write(DECISIONS_TEMPLATE)

    with open(os.path.join(context_dir, 'CURRENT_TASK.md'), 'w') as f:
        f.write(CURRENT_TASK_TEMPLATE)

    write_gitignore(context_dir)

    install_hook(root)

    print(f"\nDone. Created .ai-context/ with:")
    for fname in ['ARCHITECTURE.md', 'DECISIONS.md', 'CURRENT_TASK.md', '.gitignore']:
        print(f"  .ai-context/{fname}")
    print("\nNext: review ARCHITECTURE.md and run `aicontext task \"<your task>\"` before a coding session.")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else '.'
    init_repo(target)


if __name__ == '__main__':
    main()
