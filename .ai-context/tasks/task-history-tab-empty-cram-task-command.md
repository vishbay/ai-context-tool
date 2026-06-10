# Current Task

## Task
task history tab empty, cram task command output without quotes

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
[lines 396–614 of 614]

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
  ··· 148 lines omitted ···
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

### cram/find_context.py
```py
[lines 256–410 of 507]

# ── context assembly ──────────────────────────────────────────────


def _arch_summary(arch: str, max_lines: int = 25) -> str:
    """Extract the first max_lines non-blank lines of ARCHITECTURE.md."""
    collected = []
    for line in arch.splitlines():
        if line.strip():
            collected.append(line)
        if len(collected) >= max_lines:
            break
    return '\n'.join(collected)


def populate_current_task(
    task: str,
    file_entries,  # list[str] or list[tuple[str, list[str]]]
    ctx_model: str = '',
    coding_model: str = '',
    output_path: str | None = None,
) -> list[str]:
    """Write CURRENT_TASK.md (or output_path) with identifier-focused excerpts. Returns files inlined."""
    # Normalize: accept both plain string paths and (path, identifiers) tuples
    normalized = [
        (e, []) if isinstance(e, str) else e
        for e in file_entries
    ]
    found   = [(f, ids) for f, ids in normalized if os.path.exists(f)]
    missing = [f for f, _ in normalized if not os.path.exists(f)]

  ··· 28 lines omitted ···
        if missing:
            out.write("## Notes\n")
            for m in missing:
                out.write(f"- `{m}` suggested but not found on disk\n")
            out.write('\n')

        out.write("## Relevant Files\n")
        for fpath, ids in found:
            ext     = os.path.splitext(fpath)[1].lstrip('.')
            excerpt = _extract_excerpt(fpath, ids)
            out.write(f"\n### {fpath}\n```{ext}\n{excerpt}\n```\n")

    return [f for f, _ in found]


# ── main entry ────────────────────────────────────────────────────


def find_context(task: str, target: str | None = None, inject: bool = False, root: str = '.') -> None:
    if not has_context_dir('.'):
        print(f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.", file=sys.stderr)
        sys.exit(1)

    arch      = _read_context_file('ARCHITECTURE.md')
    decisions = _read_context_file('DECISIONS.md')
    gotchas   = _read_context_file('GOTCHAS.md')
    symbols   = _read_context_file('SYMBOLS.md')

    if not arch:
        print(
            f"Warning: {CONTEXT_DIR}/ARCHITECTURE.md is empty. "
  ··· 47 lines omitted ···

    # ── Stage 3: excerpt extraction ───────────────────────────────
    print(f"[3/4] Extracting focused excerpts from {len(found_entries)} file(s) ...")
    sys.stdout.flush()

    for fpath, ids in found_entries:
        excerpt = _extract_excerpt(fpath, ids)
        tok = len(excerpt) // 4
        id_note = f" ({', '.join(ids[:2])}{'…' if len(ids) > 2 else ''})" if ids else ''
        print(f"  → {fpath}{id_note}  ~{tok:,} tokens")

    # ── Stage 4: write context ───────────────────────────────────
    print(f"[4/4] Writing context ...")
    sys.stdout.flush()

    inlined = populate_current_task(task, file_entries, ctx_model, coding_model)

    task_path = context_path('.', 'CURRENT_TASK.md', warn=True)
  ··· 97 more lines

```
