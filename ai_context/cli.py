"""Single entry point: dispatches `aicontext <subcommand>` to the right module."""

import sys


USAGE = """\
Usage: aicontext <command> [args]

Commands:
  init   [path]       One-time repo setup — generates .ai-context/ files
  task   "<description>"  Populate CURRENT_TASK.md before a coding session
  sync   [path]       Update ARCHITECTURE.md after a commit
  status [path]       Show .ai-context/ freshness and sync state
  hook   install|uninstall [path]  Manage the git post-commit hook
"""


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ('-h', '--help'):
        print(USAGE)
        sys.exit(0)

    cmd, rest = args[0], args[1:]
    sys.argv = [f'aicontext {cmd}'] + rest  # rewrite for submodule arg parsers

    if cmd == 'init':
        from ai_context.init import main as _main
    elif cmd == 'task':
        from ai_context.find_context import main as _main
    elif cmd == 'sync':
        from ai_context.sync_context import main as _main
    elif cmd == 'status':
        from ai_context.status import main as _main
    elif cmd == 'hook':
        from ai_context.hooks import main as _main
    else:
        print(f"Unknown command: {cmd!r}\n")
        print(USAGE)
        sys.exit(1)

    _main()


if __name__ == '__main__':
    main()
