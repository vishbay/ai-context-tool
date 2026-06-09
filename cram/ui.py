"""cram ui — Textual TUI dashboard for decisions, session efficiency, and context health."""

from __future__ import annotations
import glob
import os
import re
import sys
from datetime import datetime

_TEXTUAL_MISSING = """\
textual is not installed. Run:
  pip install "cram-ai[tui]"
or:
  pip install textual
"""


def _require_textual() -> None:
    try:
        import textual  # noqa: F401
    except ImportError:
        print(_TEXTUAL_MISSING, file=sys.stderr)
        sys.exit(1)


# ── Decision parsing ────────────────────────────────────────────────────────

_ENTRY_RE = re.compile(
    r'^## \[(DECISION-\d+)\](.*?)$',
    re.MULTILINE,
)
_STATUS_RE = re.compile(r'\*\*Status:\*\*\s*(.+)', re.IGNORECASE)
_DATE_RE   = re.compile(r'\*\*Date:\*\*\s*(.+)')
_REASON_RE = re.compile(r'\*\*Reason:\*\*\s*(.+)')


def _parse_decisions(content: str) -> list[dict]:
    """Return list of decision dicts parsed from DECISIONS.md."""
    entries = []
    # Split on entry headings
    splits = list(_ENTRY_RE.finditer(content))
    for i, m in enumerate(splits):
        end = splits[i + 1].start() if i + 1 < len(splits) else len(content)
        block = content[m.start():end]
        decision_id  = m.group(1)
        heading_rest = m.group(2).strip()
        pending      = '[PENDING]' in heading_rest
        title = heading_rest.replace('[PENDING]', '').strip()

        status_m = _STATUS_RE.search(block)
        date_m   = _DATE_RE.search(block)
        reason_m = _REASON_RE.search(block)

        entries.append({
            'id':      decision_id,
            'title':   title,
            'pending': pending,
            'status':  status_m.group(1).strip() if status_m else '',
            'date':    date_m.group(1).strip()   if date_m   else '',
            'reason':  reason_m.group(1).strip() if reason_m else '',
            'block':   block,
        })
    return entries


def _approve_decision(content: str, decision_id: str) -> str:
    """Remove [PENDING] tag and set Status to Accepted in DECISIONS.md content."""
    # Remove [PENDING] from heading
    content = re.sub(
        rf'(## \[{re.escape(decision_id)}\]) \[PENDING\] ',
        r'\1 ',
        content,
    )
    # Replace Status line in that entry's block
    def replace_status(m: re.Match) -> str:
        return f'## [{decision_id}]' + m.group(1).replace(
            'Pending — proposed by agent, awaiting owner review', 'Accepted'
        ).replace('Pending', 'Accepted')

    # Targeted replace: find the entry block and update its Status line
    entry_start = content.find(f'## [{decision_id}]')
    if entry_start == -1:
        return content
    next_entry = content.find('\n## [', entry_start + 1)
    block_end  = next_entry if next_entry != -1 else len(content)
    block = content[entry_start:block_end]
    new_block = _STATUS_RE.sub('**Status:** Accepted', block, count=1)
    return content[:entry_start] + new_block + content[block_end:]


def _delete_decision(content: str, decision_id: str) -> str:
    """Remove a decision entry block from DECISIONS.md content."""
    start = content.find(f'## [{decision_id}]')
    if start == -1:
        return content
    next_entry = content.find('\n## [', start + 1)
    block_end  = next_entry if next_entry != -1 else len(content)
    # Remove trailing blank lines before next entry
    return content[:start].rstrip('\n') + '\n' + content[block_end:]


# ── Textual app ─────────────────────────────────────────────────────────────

def _build_app(root: str):  # noqa: ANN202
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import ScrollableContainer, VerticalScroll
    from textual.widgets import (
        DataTable, Footer, Header, Label, Static,
        TabbedContent, TabPane,
    )
    from textual.reactive import reactive

    from cram.context_dir import context_path
    from cram.audit import _analyze_transcript, _project_transcript_dir
    from cram.health import context_health

    DECISIONS_FILE = 'DECISIONS.md'

    # ── Decisions pane ───────────────────────────────────────────

    class DecisionsPane(VerticalScroll):
        focused_id: reactive[str | None] = reactive(None)

        def _decisions_path(self) -> str:
            return context_path(root, DECISIONS_FILE, warn=True)

        def _load(self) -> tuple[str, list[dict]]:
            path = self._decisions_path()
            if not os.path.exists(path):
                return '', []
            with open(path) as f:
                content = f.read()
            return content, _parse_decisions(content)

        def compose(self) -> ComposeResult:
            yield Label('[b]Pending review[/b]', id='pending-header')
            yield Static('', id='pending-list')
            yield Label('[b]Accepted[/b]', id='accepted-header')
            yield Static('', id='accepted-list')

        def on_mount(self) -> None:
            self.refresh_decisions()

        def refresh_decisions(self) -> None:
            _, entries = self._load()
            pending  = [e for e in entries if e['pending']]
            accepted = [e for e in entries if not e['pending']]

            pending_text = ''
            for e in pending:
                pending_text += (
                    f"  [{e['id']}] [yellow]{e['title']}[/yellow]\n"
                    f"  {'Reason: ' + e['reason'] if e['reason'] else ''}\n"
                    f"  [dim]{e['date']}[/dim]\n\n"
                )
            if not pending_text:
                pending_text = '  [dim]No pending decisions.[/dim]\n'

            accepted_text = ''
            for e in accepted:
                accepted_text += (
                    f"  [{e['id']}] {e['title']}"
                    f"{'  [dim]' + e['date'] + '[/dim]' if e['date'] else ''}\n"
                )
            if not accepted_text:
                accepted_text = '  [dim]None yet.[/dim]\n'

            self.query_one('#pending-list', Static).update(pending_text)
            self.query_one('#accepted-list', Static).update(accepted_text)

            # Track first pending for keybinding target
            self.focused_id = pending[0]['id'] if pending else None

        def approve_focused(self) -> str | None:
            path = self._decisions_path()
            if not self.focused_id or not os.path.exists(path):
                return None
            with open(path) as f:
                content = f.read()
            new_content = _approve_decision(content, self.focused_id)
            with open(path, 'w') as f:
                f.write(new_content)
            approved_id = self.focused_id
            self.refresh_decisions()
            return approved_id

        def delete_focused(self) -> str | None:
            path = self._decisions_path()
            if not self.focused_id or not os.path.exists(path):
                return None
            with open(path) as f:
                content = f.read()
            new_content = _delete_decision(content, self.focused_id)
            with open(path, 'w') as f:
                f.write(new_content)
            deleted_id = self.focused_id
            self.refresh_decisions()
            return deleted_id

        def pending_count(self) -> int:
            _, entries = self._load()
            return sum(1 for e in entries if e['pending'])

    # ── Sessions pane ────────────────────────────────────────────

    class SessionsPane(ScrollableContainer):
        def compose(self) -> ComposeResult:
            yield DataTable(id='sessions-table')

        def on_mount(self) -> None:
            table = self.query_one('#sessions-table', DataTable)
            table.add_columns('Date', 'Reads', 'Edits', 'Ratio', 'Signal')
            self.refresh_sessions()

        def refresh_sessions(self) -> None:
            import glob as _glob
            table = self.query_one('#sessions-table', DataTable)
            table.clear()

            td = _project_transcript_dir(root)
            if not td:
                table.add_row('No transcripts found', '', '', '', '')
                return

            files = sorted(_glob.glob(td + '/*.jsonl'), key=os.path.getmtime, reverse=True)[:20]
            if not files:
                table.add_row('No sessions found', '', '', '', '')
                return

            for fpath in files:
                r = _analyze_transcript(fpath)
                if not r:
                    continue
                mtime    = datetime.fromtimestamp(r['mtime'])
                date_str = mtime.strftime('%m-%d %H:%M')
                ratio    = r['ratio']
                signal   = '✓' if ratio < 2 else ('⚠' if ratio > 5 else '~')
                table.add_row(
                    date_str,
                    str(r['reads']),
                    str(r['edits']),
                    f"{ratio:.1f}×",
                    signal,
                )

    # ── Health pane ──────────────────────────────────────────────

    class HealthPane(ScrollableContainer):
        def compose(self) -> ComposeResult:
            yield Static('', id='health-body')
            yield Label('\n[b]Task Slots[/b]', id='slots-header')
            yield Static('', id='slots-body')

        def on_mount(self) -> None:
            self.refresh_health()

        def refresh_health(self) -> None:
            h = context_health(root)
            score = h['staleness_score']
            band  = h['staleness_band']
            color = {'fresh': 'green', 'acceptable': 'yellow',
                     'stale': 'orange1', 'critical': 'red'}.get(band, 'white')

            lines = [f"[b]Score:[/b] [{color}]{score}/10 ({band})[/{color}]"]
            if h.get('commits_since_sync') is not None:
                lines.append(f"[b]Commits since sync:[/b] {h['commits_since_sync']}")
            if h.get('last_commit_age'):
                lines.append(f"[b]Last commit:[/b] {h['last_commit_age']}")
            lines.append('')
            for fname, info in h.get('files', {}).items():
                bs = info.get('budget_status', 'ok')
                fc = 'green' if bs == 'ok' else ('yellow' if bs == 'warn' else 'red')
                lines.append(f"  [{fc}]{fname:<22}[/{fc}] {info['tokens']:>5} tok  {bs}")

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
            background: $surface;
        }
        """
        BINDINGS = [
            Binding('a', 'approve', 'Approve'),
            Binding('d', 'delete',  'Delete'),
            Binding('r', 'refresh', 'Refresh'),
            Binding('q', 'quit',    'Quit'),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            with TabbedContent(initial='decisions'):
                with TabPane('Decisions', id='decisions'):
                    yield DecisionsPane(id='decisions-pane')
                with TabPane('Sessions', id='sessions'):
                    yield SessionsPane(id='sessions-pane')
                with TabPane('Health', id='health'):
                    yield HealthPane(id='health-pane')
            yield Footer()

        def on_mount(self) -> None:
            self._update_title()
            self.set_interval(30, self._auto_refresh)

        def _update_title(self) -> None:
            pane = self.query_one('#decisions-pane', DecisionsPane)
            n = pane.pending_count()
            repo_name = os.path.basename(root)
            self.title = f'cram-ai  •  {repo_name}{"  •  " + str(n) + " pending" if n else ""}'

        def _auto_refresh(self) -> None:
            self.action_refresh()

        def action_approve(self) -> None:
            pane = self.query_one('#decisions-pane', DecisionsPane)
            approved = pane.approve_focused()
            if approved:
                self.notify(f'Approved {approved}', severity='information')
                self._update_title()
            else:
                self.notify('No pending decision selected', severity='warning')

        def action_delete(self) -> None:
            pane = self.query_one('#decisions-pane', DecisionsPane)
            deleted = pane.delete_focused()
            if deleted:
                self.notify(f'Deleted {deleted}', severity='warning')
                self._update_title()
            else:
                self.notify('No pending decision selected', severity='warning')

        def action_refresh(self) -> None:
            for widget_id, method in [
                ('#decisions-pane', 'refresh_decisions'),
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
