"""Mac menu bar app — set tasks, view token metrics, trigger syncs."""

from __future__ import annotations
import os
import subprocess
import sys
import threading
import time

try:
    import rumps
except ImportError:
    print(
        "rumps is required for the menu bar app.\n"
        "Install with: pip install 'cram-ai[mac]'",
        file=sys.stderr,
    )
    sys.exit(1)

CONTEXT_DIR = '.cram-ai-context'
VALID_TARGETS = ["cursor", "claude", "copilot", "codex", "windsurf", "all"]

_EXCLUDE_SCAN = {
    '.git', CONTEXT_DIR, 'node_modules', '__pycache__',
    '.venv', 'venv', 'dist', 'build', '.next', 'coverage',
}
_SCAN_EXTS = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.rb',
    '.java', '.md', '.json', '.toml', '.yaml', '.yml', '.html', '.css',
}


def _estimate_repo_tokens(root: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_SCAN]
        for fname in filenames:
            if os.path.splitext(fname)[1] in _SCAN_EXTS:
                try:
                    with open(os.path.join(dirpath, fname), errors='ignore') as f:
                        total += len(f.read())
                except OSError:
                    pass
    return total // 4


def _age(secs: float) -> str:
    s = int(secs)
    if s < 60:    return f"{s}s ago"
    if s < 3600:  return f"{s // 60}m ago"
    if s < 86400: return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


class CramMenuBar(rumps.App):
    def __init__(self, repo_path: str) -> None:
        self.repo_path = os.path.abspath(repo_path)
        self._current_target = self._load_default_target()

        # Build target submenu with radio-style checkmarks
        target_menu = rumps.MenuItem("Target")
        self._target_items: dict[str, rumps.MenuItem] = {}
        for t in VALID_TARGETS:
            item = rumps.MenuItem(t, callback=self._on_target_select)
            item.state = int(t == self._current_target)
            target_menu.add(item)
            self._target_items[t] = item

        repo_name = os.path.basename(self.repo_path)
        super().__init__(
            "⚡",
            menu=[
                rumps.MenuItem("Set Task…", callback=self._on_set_task),
                None,
                rumps.MenuItem("Token Metrics", callback=self._on_metrics),
                rumps.MenuItem("Sync Now", callback=self._on_sync),
                rumps.MenuItem("Status", callback=self._on_status),
                None,
                target_menu,
                None,
                rumps.MenuItem(f"Repo: {repo_name}"),
            ],
        )

    # ── helpers ───────────────────────────────────────────────────

    def _load_default_target(self) -> str:
        config_path = os.path.join(self.repo_path, CONTEXT_DIR, 'config.toml')
        if os.path.exists(config_path):
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore
                with open(config_path, 'rb') as f:
                    cfg = tomllib.load(f)
                val = cfg.get('task', {}).get('default_target', '')
                if val in VALID_TARGETS:
                    return val
            except Exception:
                pass
        return 'cursor'

    # ── target submenu ────────────────────────────────────────────

    def _on_target_select(self, sender: rumps.MenuItem) -> None:
        for name, item in self._target_items.items():
            item.state = int(name == sender.title)
        self._current_target = sender.title

    # ── set task ──────────────────────────────────────────────────

    def _on_set_task(self, _) -> None:
        w = rumps.Window(
            message="Describe what you're about to work on:",
            title="cram-ai — Set Task",
            default_text="",
            ok="Generate Context",
            cancel="Cancel",
            dimensions=(420, 50),
        )
        resp = w.run()
        if resp.clicked and resp.text.strip():
            threading.Thread(
                target=self._run_task, args=(resp.text.strip(),), daemon=True
            ).start()

    def _run_task(self, task: str) -> None:
        result = subprocess.run(
            ['cram', 'task', task, '--target', self._current_target],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            detail_lines = [
                l for l in result.stdout.splitlines()
                if l.strip().startswith(('  ', '→', 'W'))
            ]
            detail = '\n'.join(detail_lines[:6]) or "Context ready"
            rumps.notification(
                "cram-ai", f"Context ready → {self._current_target}", detail, sound=False
            )
        else:
            rumps.notification(
                "cram-ai", "Error", result.stderr[:120] or "cram task failed", sound=False
            )

    # ── token metrics ─────────────────────────────────────────────

    def _on_metrics(self, _) -> None:
        rumps.alert(title="Token Metrics — cram-ai", message=self._build_metrics(), ok="Close")

    def _build_metrics(self) -> str:
        context_dir = os.path.join(self.repo_path, CONTEXT_DIR)
        if not os.path.isdir(context_dir):
            return f"No {CONTEXT_DIR}/ found.\nRun `cram init` first."

        rows: list[tuple[str, int, int]] = []
        for fname in ('ARCHITECTURE.md', 'DECISIONS.md', 'CURRENT_TASK.md'):
            path = os.path.join(context_dir, fname)
            if os.path.exists(path):
                with open(path, errors='ignore') as f:
                    content = f.read()
                rows.append((fname, content.count('\n'), len(content) // 4))

        cram_tokens = sum(r[2] for r in rows)
        repo_tokens  = _estimate_repo_tokens(self.repo_path)
        savings_pct  = max(0, int((1 - cram_tokens / max(repo_tokens, 1)) * 100))
        cost_saved   = (repo_tokens - cram_tokens) / 1_000_000 * 3.75

        out = "Context files:\n"
        for fname, lines, tokens in rows:
            out += f"  {fname:<26} {lines:>4} lines  ~{tokens:,} tokens\n"
        out += f"  {'Total':<26}        ~{cram_tokens:,} tokens\n"
        out += f"\nFull repo estimate:         ~{repo_tokens:,} tokens\n"
        out += f"Savings this session:       ~{savings_pct}%  (~${cost_saved:.3f} saved)\n"

        task_path = os.path.join(context_dir, 'CURRENT_TASK.md')
        if os.path.exists(task_path):
            out += f"\nLast task set:  {_age(time.time() - os.path.getmtime(task_path))}"

        arch_path = os.path.join(context_dir, 'ARCHITECTURE.md')
        if os.path.exists(arch_path):
            out += f"\nLast sync:      {_age(time.time() - os.path.getmtime(arch_path))}"

        return out

    # ── sync ──────────────────────────────────────────────────────

    def _on_sync(self, _) -> None:
        threading.Thread(target=self._run_sync, daemon=True).start()

    def _run_sync(self) -> None:
        result = subprocess.run(
            ['cram', 'sync'],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        msg = "ARCHITECTURE.md updated" if result.returncode == 0 else result.stderr[:120]
        rumps.notification("cram-ai", "Sync", msg, sound=False)

    # ── status ────────────────────────────────────────────────────

    def _on_status(self, _) -> None:
        result = subprocess.run(
            ['cram', 'status'],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        text = result.stdout or result.stderr or "No output."
        rumps.alert(
            title=f"cram status — {os.path.basename(self.repo_path)}",
            message=text,
            ok="Close",
        )


def main() -> None:
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    CramMenuBar(repo).run()


if __name__ == '__main__':
    main()
