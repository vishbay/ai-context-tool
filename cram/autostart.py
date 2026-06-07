"""Install or remove a macOS LaunchAgent that starts cram-menu at login."""

from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

_LABEL    = 'ai.cram.menu'
_PLIST    = Path.home() / 'Library' / 'LaunchAgents' / f'{_LABEL}.plist'


def _cram_menu_bin() -> str:
    """Return the absolute path to the cram-menu binary."""
    # Prefer the binary in the same venv as this interpreter
    candidate = Path(sys.executable).parent / 'cram-menu'
    if candidate.exists():
        return str(candidate)
    found = shutil.which('cram-menu')
    if found:
        return found
    raise RuntimeError(
        "cram-menu binary not found. "
        "Install with: pip install 'cram-ai[tray]'"
    )


def install(repo_path: str | None = None) -> None:
    from cram.utils import find_git_root
    repo = find_git_root(repo_path or os.getcwd())

    binary = _cram_menu_bin()

    plist = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>{_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary}</string>
        <string>{repo}</string>
    </array>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <false/>
    <key>StandardOutPath</key>   <string>{Path.home()}/.config/cram-ai/cram-menu.log</string>
    <key>StandardErrorPath</key> <string>{Path.home()}/.config/cram-ai/cram-menu.log</string>
</dict>
</plist>
"""
    Path.home().joinpath('.config', 'cram-ai').mkdir(parents=True, exist_ok=True)
    _PLIST.parent.mkdir(parents=True, exist_ok=True)
    _PLIST.write_text(plist)

    # Load immediately (also activates on next login)
    subprocess.run(['launchctl', 'load', str(_PLIST)], check=False)

    print(f"cram-menu will now start automatically at login.")
    print(f"Repo: {repo}")
    print(f"Plist: {_PLIST}")
    print(f"\nTo stop: cram autostart off")


def uninstall() -> None:
    if _PLIST.exists():
        subprocess.run(['launchctl', 'unload', str(_PLIST)], check=False)
        _PLIST.unlink()
        print(f"Removed {_PLIST}")
        print("cram-menu will no longer start at login.")
    else:
        print("No autostart entry found.")


def status() -> None:
    if _PLIST.exists():
        result = subprocess.run(
            ['launchctl', 'list', _LABEL],
            capture_output=True, text=True,
        )
        running = result.returncode == 0
        print(f"Autostart: installed ({'running' if running else 'not currently running'})")
        print(f"Plist:     {_PLIST}")
    else:
        print("Autostart: not installed")


def main() -> None:
    if sys.platform != 'darwin':
        print(
            "cram autostart is currently macOS-only.\n"
            "Windows: add cram-menu to the Startup folder.\n"
            "Linux:   add to ~/.config/autostart/ or your WM's autostart.",
            file=sys.stderr,
        )
        sys.exit(1)

    action = sys.argv[1] if len(sys.argv) > 1 else 'on'
    path   = sys.argv[2] if len(sys.argv) > 2 else None

    if action in ('on', 'install', 'enable'):
        install(path)
    elif action in ('off', 'uninstall', 'disable'):
        uninstall()
    elif action in ('status',):
        status()
    else:
        print(f"Usage: cram autostart [on|off|status] [repo_path]")
        sys.exit(1)


if __name__ == '__main__':
    main()
