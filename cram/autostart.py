"""Install or remove autostart for cram-menu at login.

macOS:   LaunchAgent plist  — ~/Library/LaunchAgents/ai.cram.menu.plist
Windows: Batch file          — %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\cram-menu.bat
Linux:   XDG .desktop file  — ~/.config/autostart/cram-menu.desktop
"""

from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── binary lookup ──────────────────────────────────────────────────

def _cram_menu_bin() -> str:
    candidate = Path(sys.executable).parent / ('cram-menu.exe' if sys.platform == 'win32' else 'cram-menu')
    if candidate.exists():
        return str(candidate)
    found = shutil.which('cram-menu')
    if found:
        return found
    raise RuntimeError(
        "cram-menu binary not found. "
        "Install with: pip install 'cram-ai[tray]'"
    )


# ── macOS ──────────────────────────────────────────────────────────

_MAC_LABEL = 'ai.cram.menu'
_MAC_PLIST = Path.home() / 'Library' / 'LaunchAgents' / f'{_MAC_LABEL}.plist'


def _mac_install(binary: str, repo: str) -> None:
    log = Path.home() / '.config' / 'cram-ai' / 'cram-menu.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    _MAC_PLIST.parent.mkdir(parents=True, exist_ok=True)
    _MAC_PLIST.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>{_MAC_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary}</string>
        <string>{repo}</string>
    </array>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <false/>
    <key>StandardOutPath</key>   <string>{log}</string>
    <key>StandardErrorPath</key> <string>{log}</string>
</dict>
</plist>
""")
    subprocess.run(['launchctl', 'load', str(_MAC_PLIST)], check=False)
    print(f"cram-menu will start automatically at login.")
    print(f"Repo:  {repo}")
    print(f"Plist: {_MAC_PLIST}")
    print(f"\nTo stop: cram autostart off")


def _mac_uninstall() -> None:
    if _MAC_PLIST.exists():
        subprocess.run(['launchctl', 'unload', str(_MAC_PLIST)], check=False)
        _MAC_PLIST.unlink()
        print(f"Removed {_MAC_PLIST}")
        print("cram-menu will no longer start at login.")
    else:
        print("No autostart entry found.")


def _mac_status() -> None:
    if _MAC_PLIST.exists():
        result = subprocess.run(
            ['launchctl', 'list', _MAC_LABEL],
            capture_output=True, text=True,
        )
        running = result.returncode == 0
        print(f"Autostart: installed ({'running' if running else 'not currently running'})")
        print(f"Plist:     {_MAC_PLIST}")
    else:
        print("Autostart: not installed")


# ── Windows ────────────────────────────────────────────────────────

def _win_bat_path() -> Path:
    startup = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    return startup / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup' / 'cram-menu.bat'


def _win_install(binary: str, repo: str) -> None:
    bat = _win_bat_path()
    bat.parent.mkdir(parents=True, exist_ok=True)
    # start /b runs detached so no console window stays open
    bat.write_text(
        f'@echo off\r\n'
        f'start "" /b "{binary}" "{repo}"\r\n',
        encoding='utf-8',
    )
    print(f"cram-menu will start automatically at login.")
    print(f"Repo:    {repo}")
    print(f"Startup: {bat}")
    print(f"\nTo stop: cram autostart off")


def _win_uninstall() -> None:
    bat = _win_bat_path()
    if bat.exists():
        bat.unlink()
        print(f"Removed {bat}")
        print("cram-menu will no longer start at login.")
    else:
        print("No autostart entry found.")


def _win_status() -> None:
    bat = _win_bat_path()
    print(f"Autostart: {'installed' if bat.exists() else 'not installed'}")
    if bat.exists():
        print(f"Startup:   {bat}")


# ── Linux ──────────────────────────────────────────────────────────

def _linux_desktop_path() -> Path:
    xdg = os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')
    return Path(xdg) / 'autostart' / 'cram-menu.desktop'


def _linux_install(binary: str, repo: str) -> None:
    desktop = _linux_desktop_path()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        f'[Desktop Entry]\n'
        f'Type=Application\n'
        f'Name=cram-ai\n'
        f'Comment=AI coding context manager\n'
        f'Exec={binary} {repo}\n'
        f'Hidden=false\n'
        f'NoDisplay=false\n'
        f'X-GNOME-Autostart-enabled=true\n',
        encoding='utf-8',
    )
    print(f"cram-menu will start automatically at login.")
    print(f"Repo:    {repo}")
    print(f"Desktop: {desktop}")
    print(f"\nNote: requires a desktop environment that supports XDG autostart")
    print(f"      (GNOME, KDE, XFCE, etc.). Wayland compositors vary.")
    print(f"\nTo stop: cram autostart off")


def _linux_uninstall() -> None:
    desktop = _linux_desktop_path()
    if desktop.exists():
        desktop.unlink()
        print(f"Removed {desktop}")
        print("cram-menu will no longer start at login.")
    else:
        print("No autostart entry found.")


def _linux_status() -> None:
    desktop = _linux_desktop_path()
    print(f"Autostart: {'installed' if desktop.exists() else 'not installed'}")
    if desktop.exists():
        print(f"Desktop:   {desktop}")


# ── dispatch ───────────────────────────────────────────────────────

def _resolve_repo(path_arg: str | None) -> str:
    from cram.utils import find_git_root
    return find_git_root(path_arg or os.getcwd())


def install(repo_path: str | None = None) -> None:
    binary = _cram_menu_bin()
    repo   = _resolve_repo(repo_path)
    if sys.platform == 'darwin':
        _mac_install(binary, repo)
    elif sys.platform == 'win32':
        _win_install(binary, repo)
    else:
        _linux_install(binary, repo)


def uninstall() -> None:
    if sys.platform == 'darwin':
        _mac_uninstall()
    elif sys.platform == 'win32':
        _win_uninstall()
    else:
        _linux_uninstall()


def status() -> None:
    if sys.platform == 'darwin':
        _mac_status()
    elif sys.platform == 'win32':
        _win_status()
    else:
        _linux_status()


def main() -> None:
    args   = sys.argv[1:]
    action = args[0] if args else 'on'
    path   = args[1] if len(args) > 1 else None

    if action in ('on', 'install', 'enable'):
        install(path)
    elif action in ('off', 'uninstall', 'disable'):
        uninstall()
    elif action == 'status':
        status()
    else:
        print(f"Usage: cram autostart [on|off|status] [repo_path]")
        sys.exit(1)


if __name__ == '__main__':
    main()
