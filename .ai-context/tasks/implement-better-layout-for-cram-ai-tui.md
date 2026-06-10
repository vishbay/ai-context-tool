# Current Task

## Task
Implement better layout for cram-ai tui and options to perform cram cli options from tui

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
[lines 275–401 of 401]

            self.query_one('#health-body', Static).update('\n'.join(lines))

            # Task slots
            tasks_dir = os.path.join(root, '.ai-context', 'tasks')
            slots = sorted(glob.glob(os.path.join(tasks_dir, '*.md')))
            slots_text = ''
            for s in slots:
                name = os.path.basename(s).replace('.md', '')
                age  = datetime.fromtimestamp(os.path.getmtime(s)).strftime('%m-%d %H:%M')
                slots_text += f"  {name:<35} [dim]{age}[/dim]\n"
            if not slots_text:
                slots_text = '  [dim]No active task slots.[/dim]\n'
            self.query_one('#slots-body', Static).update(slots_text)

    # ── Main app ─────────────────────────────────────────────────

    class CramApp(App):
        TITLE = 'cram-ai'
        CSS = """
        DecisionsPane, SessionsPane, HealthPane {
            padding: 1 2;
        }
        Label#pending-header, Label#accepted-header, Label#slots-header {
            color: $accent;
            padding: 1 0 0 0;
        }
        DataTable {
            height: auto;
        }
        Footer {
  ··· 56 lines omitted ···
                ('#sessions-pane',  'refresh_sessions'),
                ('#health-pane',    'refresh_health'),
            ]:
                try:
                    w = self.query_one(widget_id)
                    getattr(w, method)()
                except Exception:
                    pass
            self._update_title()

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

### cram/cli.py
```py
[lines 19–89 of 89]
  benchmark   [path]                       Show token savings vs full-repo auto-indexing
  status      [path]                       Show .ai-context/ freshness
  doctor      [path]                       Check setup: models, hooks, git, context files
  vscode      [path] [--force]             Generate .vscode/tasks.json for editor integration
  hook        install|uninstall [path]     Manage the git post-commit hook
  mcp         [--repo PATH]                Start MCP server (stdio) for Claude Code / agents
  ui          [path]                       Launch TUI dashboard (requires cram-ai[tui])
  menu        [path]                       Launch tray app (requires cram-ai[tray])
  autostart   on|off|status [path]         Start cram-menu automatically at login (macOS)

--target choices: cursor | claude | copilot | codex | windsurf | all
  Set a default in .ai-context/config.toml:  [task] default_target = "cursor"
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
    elif cmd == 'decisions':
        from cram.decisions import main as _main
    elif cmd == 'gotcha':
        from cram.gotcha import main as _main
    elif cmd == 'audit':
        from cram.audit import main as _main
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
    elif cmd == 'ui':
        from cram.ui import main as _main
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

```
