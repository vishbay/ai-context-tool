"""Single entry point: dispatches `cram <subcommand>` to the right module."""

import sys


USAGE = """\
Usage: cram <command> [args]

Commands:
  init        [path] [--team]              One-time repo setup (--team adds GitHub Actions CI)
  task        "<description>" [--target T] Populate CURRENT_TASK.md and auto-load into tool
  add         <file> [file ...] [--replace] Append files to the current session context
  continue    [path]                       Extend grace period — keep context on next commit
  sync        [path]                       Update ARCHITECTURE.md after a commit
  decide      "<decision>" [path]          Append an architectural decision to DECISIONS.md
  gotcha      "<trap>" [path]             Append a non-obvious trap to GOTCHAS.md
  benchmark   [path]                       Show token savings vs full-repo auto-indexing
  status      [path]                       Show .cram-ai-context/ freshness
  doctor      [path]                       Check setup: models, hooks, git, context files
  vscode      [path] [--force]             Generate .vscode/tasks.json for editor integration
  hook        install|uninstall [path]     Manage the git post-commit hook
  mcp         [--repo PATH]                Start MCP server (stdio) for Claude Code / agents
  menu        [path]                       Launch tray app (requires cram-ai[tray])
  autostart   on|off|status [path]         Start cram-menu automatically at login (macOS)

--target choices: cursor | claude | copilot | codex | windsurf | all
  Set a default in .cram-ai-context/config.toml:  [task] default_target = "cursor"
"""


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ('-h', '--help'):
        print(USAGE)
        sys.exit(0)

    cmd, rest = args[0], args[1:]
    sys.argv = [f'cram {cmd}'] + rest  # rewrite for submodule arg parsers

    if cmd == 'init':
        from cram.init import main as _main
    elif cmd == 'task':
        from cram.find_context import main as _main
    elif cmd == 'add':
        from cram.add_context import main as _main
    elif cmd == 'continue':
        from cram.session import _continue_main as _main
    elif cmd == 'sync':
        from cram.sync_context import main as _main
    elif cmd == 'decide':
        from cram.decide import main as _main
    elif cmd == 'gotcha':
        from cram.gotcha import main as _main
    elif cmd == 'benchmark':
        from cram.benchmark import main as _main
    elif cmd == 'status':
        from cram.status import main as _main
    elif cmd == 'doctor':
        from cram.doctor import main as _main
    elif cmd == 'vscode':
        from cram.vscode import main as _main
    elif cmd == 'hook':
        from cram.hooks import main as _main
    elif cmd == 'mcp':
        from cram.mcp_server import main as _main
    elif cmd == 'menu':
        from cram.tray import main as _main
    elif cmd == 'autostart':
        from cram.autostart import main as _main
    else:
        print(f"Unknown command: {cmd!r}\n")
        print(USAGE)
        sys.exit(1)

    _main()


if __name__ == '__main__':
    main()
