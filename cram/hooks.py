"""Git hook installer — wires cram sync into the post-commit and post-checkout hooks."""

from __future__ import annotations
import os
import stat
import sys

HOOK_SCRIPT = """\
#!/bin/sh
# Installed by cram-ai — keeps .cram-ai-context/ARCHITECTURE.md fresh
if command -v cram >/dev/null 2>&1; then
    cram sync
elif command -v python3 >/dev/null 2>&1; then
    python3 -m cram.sync_context
fi
"""

POST_CHECKOUT_HOOK_SCRIPT = """\
#!/bin/sh
# Installed by cram-ai — notifies tray popup on branch switch
prev_head="$1"
new_head="$2"
is_branch_checkout="$3"
if [ "$is_branch_checkout" = "1" ] && [ "$prev_head" != "$new_head" ]; then
    new_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "unknown")
    port=$(cat "$HOME/.config/cram-ai/port" 2>/dev/null || echo "49155")
    curl -sf -X POST "http://127.0.0.1:${port}/notify-branch-switch" \\
        -H "Content-Type: application/json" \\
        --data-raw "{\"branch\": \"${new_branch}\"}" > /dev/null 2>&1 || true
fi
"""


def _git_dir(repo_root: str) -> str | None:
    git_dir = os.path.join(repo_root, '.git')
    return git_dir if os.path.isdir(git_dir) else None


def _write_hook(hook_path: str, script: str, marker: str) -> bool:
    """Write or append a hook script. Returns True if installed, False if skipped."""
    if os.path.exists(hook_path):
        existing = open(hook_path).read()
        if marker in existing:
            print(f"{os.path.basename(hook_path)} hook already contains cram. Skipping.")
            return False
        with open(hook_path, 'a') as f:
            f.write('\n' + script)
        print(f"Appended cram block to existing {hook_path}")
    else:
        with open(hook_path, 'w') as f:
            f.write(script)
        print(f"Installed {os.path.basename(hook_path)} hook at {hook_path}")

    current = os.stat(hook_path).st_mode
    os.chmod(hook_path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def install_hook(repo_root: str = '.') -> bool:
    """Write post-commit hook. Returns True if installed, False if skipped."""
    root = os.path.abspath(repo_root)
    git_dir = _git_dir(root)
    if not git_dir:
        print(f"No .git/ directory found in {root}. Skipping hook install.")
        return False
    hooks_dir = os.path.join(git_dir, 'hooks')
    os.makedirs(hooks_dir, exist_ok=True)
    return _write_hook(os.path.join(hooks_dir, 'post-commit'), HOOK_SCRIPT, 'cram-ai')


def install_checkout_hook(repo_root: str = '.') -> bool:
    """Write post-checkout hook for branch-switch detection. Returns True if installed."""
    root = os.path.abspath(repo_root)
    git_dir = _git_dir(root)
    if not git_dir:
        print(f"No .git/ directory found in {root}. Skipping hook install.")
        return False
    hooks_dir = os.path.join(git_dir, 'hooks')
    os.makedirs(hooks_dir, exist_ok=True)
    return _write_hook(os.path.join(hooks_dir, 'post-checkout'), POST_CHECKOUT_HOOK_SCRIPT, 'cram-ai')


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
        print("Removed cram block from post-commit hook.")
    else:
        os.remove(hook_path)
        print("Removed post-commit hook.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Manage cram git hooks')
    parser.add_argument('action', choices=['install', 'uninstall'], default='install', nargs='?')
    parser.add_argument('path', nargs='?', default='.')
    args = parser.parse_args()

    from cram.utils import find_git_root
    path = find_git_root(args.path)
    if args.action == 'uninstall':
        uninstall_hook(path)
    else:
        install_hook(path)


if __name__ == '__main__':
    main()
