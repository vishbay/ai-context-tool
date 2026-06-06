"""Git hook installer — wires aicontext sync into the post-commit hook."""

from __future__ import annotations
import os
import stat
import sys

HOOK_SCRIPT = """\
#!/bin/sh
# Installed by ai-context-tool — keeps .ai-context/ARCHITECTURE.md fresh
if command -v aicontext >/dev/null 2>&1; then
    aicontext sync
elif command -v python3 >/dev/null 2>&1; then
    python3 -m ai_context.sync_context
fi
"""


def _git_dir(repo_root: str) -> str | None:
    git_dir = os.path.join(repo_root, '.git')
    return git_dir if os.path.isdir(git_dir) else None


def install_hook(repo_root: str = '.') -> bool:
    """Write post-commit hook. Returns True if installed, False if skipped."""
    root = os.path.abspath(repo_root)
    git_dir = _git_dir(root)

    if not git_dir:
        print(f"No .git/ directory found in {root}. Skipping hook install.")
        return False

    hooks_dir = os.path.join(git_dir, 'hooks')
    os.makedirs(hooks_dir, exist_ok=True)
    hook_path = os.path.join(hooks_dir, 'post-commit')

    if os.path.exists(hook_path):
        existing = open(hook_path).read()
        if 'ai-context-tool' in existing or 'aicontext' in existing:
            print(f"post-commit hook already contains aicontext. Skipping.")
            return False
        # Append to existing hook rather than overwrite
        with open(hook_path, 'a') as f:
            f.write('\n' + HOOK_SCRIPT)
        print(f"Appended aicontext sync to existing {hook_path}")
    else:
        with open(hook_path, 'w') as f:
            f.write(HOOK_SCRIPT)
        print(f"Installed post-commit hook at {hook_path}")

    # Ensure executable
    current = os.stat(hook_path).st_mode
    os.chmod(hook_path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def uninstall_hook(repo_root: str = '.') -> None:
    root = os.path.abspath(repo_root)
    git_dir = _git_dir(root)
    if not git_dir:
        print("No .git/ directory found.")
        return

    hook_path = os.path.join(git_dir, 'hooks', 'post-commit')
    if not os.path.exists(hook_path):
        print("No post-commit hook found.")
        return

    content = open(hook_path).read()
    # Remove only the block we added
    cleaned = content.replace(HOOK_SCRIPT, '').replace('\n' + HOOK_SCRIPT, '')
    if cleaned.strip():
        with open(hook_path, 'w') as f:
            f.write(cleaned)
        print("Removed aicontext block from post-commit hook.")
    else:
        os.remove(hook_path)
        print("Removed post-commit hook.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Manage aicontext git hooks')
    parser.add_argument('action', choices=['install', 'uninstall'], default='install', nargs='?')
    parser.add_argument('path', nargs='?', default='.')
    args = parser.parse_args()

    if args.action == 'uninstall':
        uninstall_hook(args.path)
    else:
        install_hook(args.path)


if __name__ == '__main__':
    main()
