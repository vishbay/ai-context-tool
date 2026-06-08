"""Cross-platform system tray app — pystray icon + optional pywebview popup.

Default interaction: click tray icon → native OS dropdown menu.
Optional: choose "Open popup" from the menu for the full HTML window.

Mac:    NSStatusBar via pystray objc backend + WKWebView
Win:    Windows tray icon + MSHTML/Edge WebView2
Linux:  AppIndicator/xorg tray + GTK WebView (requires system tray support)
"""

from __future__ import annotations
import atexit
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_PID_FILE = Path.home() / '.config' / 'cram-ai' / 'cram-menu.pid'


def _acquire_instance_lock() -> bool:
    """Return True if this process should proceed; False if another instance is running."""
    if _PID_FILE.exists():
        try:
            pid = int(_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # signal 0 = existence check only
            return False      # process is alive → another instance is running
        except (ProcessLookupError, PermissionError):
            pass  # stale PID — process is gone, safe to proceed
        except (ValueError, OSError):
            pass  # corrupt file
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: _PID_FILE.unlink(missing_ok=True))
    return True

try:
    import pystray
    from PIL import Image, ImageDraw
    import webview
    from cram import tray_server
    from cram.tray_server import get_active_repo as _get_repo, get_active_port as _get_port
    from cram.status import get_status_dict
    from cram.utils import find_git_root as _find_git_root
except ImportError as exc:
    print(
        f"Missing dependency ({exc}).\n"
        "Install with: pip install 'cram-ai[tray]'",
        file=sys.stderr,
    )
    sys.exit(1)

_PORT = tray_server.DEFAULT_PORT  # updated after server starts via _get_port()

# Mutable refs shared across threads
_win:  list = [None]
_icon: list = [None]


# ── icon ──────────────────────────────────────────────────────────


def _make_icon_image() -> Image.Image:
    """Generate a simple tray icon with Pillow — no image file required."""
    size = 64
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=14,
                            fill=(0, 245, 212, 230))
    draw.arc([13, 13, size - 13, size - 13],
             start=45, end=315,
             fill=(5, 4, 10, 255), width=9)
    return img


# ── pywebview JS API ──────────────────────────────────────────────


class _PopupAPI:
    """Methods callable from popup JS via window.pywebview.api.*"""

    def __init__(self, repo_path: str) -> None:
        self._repo = repo_path

    def hide(self) -> None:
        if _win[0]:
            _win[0].hide()

    def quit(self) -> None:
        import threading
        threading.Timer(0.05, lambda: os._exit(0)).start()

    def set_size(self, height: int, width: int = 320) -> None:
        if _win[0]:
            w = max(280, min(800, int(width)))
            h = max(52, min(1400, int(height)))
            _win[0].resize(w, h)
            x, y = _popup_position(w, h)
            if x is not None:
                try:
                    _win[0].move(x, y)
                except Exception:
                    pass

    def browse_repo(self) -> str | None:
        """Open a native folder picker and return the chosen path (or None)."""
        if not _win[0]:
            return None
        result = _win[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def open_folder(self) -> None:
        context_dir = os.path.join(self._repo, '.cram-ai-context')
        target = context_dir if os.path.isdir(context_dir) else self._repo
        if sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', target])
        else:
            subprocess.Popen(['xdg-open', target])


# ── repo and window position helpers ─────────────────────────────


def _pick_repo_native() -> str | None:
    """Show a native folder picker so the user can choose a git repo.
    Returns the git root of the chosen folder, or None if cancelled.
    """
    if sys.platform == 'darwin':
        result = subprocess.run(
            ['osascript', '-e',
             'POSIX path of (choose folder with prompt '
             '"Select a git repository for cram-ai:")'],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _find_git_root(result.stdout.strip())

    elif sys.platform == 'win32':
        ps = (
            'Add-Type -AssemblyName System.Windows.Forms;'
            '$d = New-Object System.Windows.Forms.FolderBrowserDialog;'
            '$d.Description = "Select a git repository for cram-ai";'
            'if ($d.ShowDialog() -eq "OK") { $d.SelectedPath }'
        )
        result = subprocess.run(
            ['powershell', '-Command', ps],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _find_git_root(result.stdout.strip())

    return None


_POPUP_W = 320   # default width
_POPUP_H = 528   # initial height (JS auto-adjusts via set_size)


def _popup_position(w: int = _POPUP_W, h: int = _POPUP_H) -> tuple[int | None, int | None]:
    """Return (x, y) to anchor the popup near the system tray, keeping the right
    edge fixed and the top edge just below the menu bar.

    pywebview on macOS passes x/y to NSWindow.setFrameOrigin_ (AppKit bottom-left
    origin; y=0 is the bottom of the screen).  Windows uses top-left origin.
    """
    try:
        if sys.platform == 'darwin':
            from AppKit import NSScreen, NSStatusBar
            frame = NSScreen.mainScreen().frame()
            sw = int(frame.size.width)
            sh = int(frame.size.height)
            try:
                mb = int(NSStatusBar.systemStatusBar().thickness())
            except Exception:
                mb = 24
            return (sw - w - 10, sh - mb - h)
        elif sys.platform == 'win32':
            import ctypes
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            return (sw - w - 10, sh - h - 48)  # 48px = typical taskbar height
    except Exception:
        pass
    return (None, None)


# ── native task dialog ────────────────────────────────────────────


def _ask_task_native() -> str | None:
    """Prompt for a task description using a native OS dialog. Returns None on cancel."""
    if sys.platform == 'darwin':
        result = subprocess.run(
            ['osascript', '-e',
             'set r to display dialog "What are you building?" default answer "" '
             'with title "cram-ai" buttons {"Cancel", "Cram it"} default button "Cram it"\n'
             'return text returned of r'],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None

    elif sys.platform == 'win32':
        # PowerShell InputBox via Windows Forms
        ps = (
            'Add-Type -AssemblyName Microsoft.VisualBasic;'
            '[Microsoft.VisualBasic.Interaction]::InputBox('
            '"What are you building?","cram-ai","")'
        )
        result = subprocess.run(
            ['powershell', '-Command', ps],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None

    else:
        # Linux: try zenity, fallback to popup
        result = subprocess.run(
            ['zenity', '--entry', '--title=cram-ai',
             '--text=What are you building?'],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None


# ── tray menu ─────────────────────────────────────────────────────


def _status_label(repo_path: str) -> str:
    """Live status line — evaluated each time the menu opens."""
    try:
        s = get_status_dict(repo_path)
        state = s.get('state', '?')
        return {'fresh': '● fresh', 'stale': '◐ stale', 'not-init': '○ not initialised'}.get(state, '?')
    except Exception:
        return '...'


def _build_menu(repo_path: str) -> pystray.Menu:

    def on_set_task(icon, item):
        task = _ask_task_native()
        if task:
            subprocess.Popen([str(Path(sys.executable).parent / 'cram'), 'task', task], cwd=_get_repo())

    def on_show_popup(icon, item):
        if _win[0]:
            _win[0].show()
            # Re-anchor to tray corner each time it's opened
            x, y = _popup_position()
            if x is not None:
                try:
                    _win[0].move(x, y)
                except Exception:
                    pass
        else:
            import webbrowser
            webbrowser.open(f'http://127.0.0.1:{_get_port()}/popup')

    def on_sync(icon, item):
        subprocess.Popen([str(Path(sys.executable).parent / 'cram'), 'sync'], cwd=_get_repo())

    def on_open_folder(icon, item):
        repo   = _get_repo()
        cd     = os.path.join(repo, '.cram-ai-context')
        target = cd if os.path.isdir(cd) else repo
        if sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', target])
        else:
            subprocess.Popen(['xdg-open', target])

    def on_quit(icon, item):
        if _win[0]:
            _win[0].destroy()
        icon.stop()

    return pystray.Menu(
        pystray.MenuItem(
            lambda item: _status_label(_get_repo()),
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Set task…', on_set_task, default=True),
        pystray.MenuItem('Sync context', on_sync),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Open popup', on_show_popup),
        pystray.MenuItem('Open folder', on_open_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Quit', on_quit),
    )


# ── entry point ───────────────────────────────────────────────────


def main() -> None:
    if not _acquire_instance_lock():
        print("cram menu is already running.", file=sys.stderr)
        sys.exit(0)

    start = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    repo  = _find_git_root(start)

    # If launched outside any git repo, ask the user to pick one
    if not os.path.isdir(os.path.join(repo, '.git')):
        chosen = _pick_repo_native()
        if chosen:
            repo = chosen
        # If cancelled, proceed with cwd — popup will show the repo selector

    # 1. Start Flask server in background thread
    threading.Thread(
        target=tray_server.run, args=(repo,), daemon=True,
    ).start()

    # Give Flask a moment to bind before webview tries to load
    time.sleep(0.6)

    # 2. Build pystray icon — run_detached() creates the status bar item
    #    without entering the run loop, so pywebview can own the main thread.
    img = _make_icon_image()
    _icon[0] = pystray.Icon(
        'cram-ai', img, 'cram-ai',
        menu=_build_menu(repo),
    )
    _icon[0].run_detached()

    # 3. Create the webview popup window — hidden by default, anchored to tray.
    x, y = _popup_position()
    pos_kwargs: dict = {'x': x, 'y': y} if x is not None else {}
    _win[0] = webview.create_window(
        'cram-ai',
        url=f'http://127.0.0.1:{_get_port()}/popup',
        width=_POPUP_W,
        height=_POPUP_H,
        frameless=True,
        on_top=True,
        hidden=True,
        js_api=_PopupAPI(repo),
        min_size=(280, 52),
        background_color='#111115',
        **pos_kwargs,
    )

    # 4. Register show callback so the tray server can open the popup from a hook
    def _show_popup_from_hook():
        if _win[0]:
            _win[0].show()
            x, y = _popup_position()
            if x is not None:
                try:
                    _win[0].move(x, y)
                except Exception:
                    pass
    tray_server.register_show_callback(_show_popup_from_hook)

    # 5. webview.start() owns the main thread (required on macOS/Win)
    webview.start(debug=False)

    # 5. Webview exited — stop tray icon
    if _icon[0]:
        _icon[0].stop()


if __name__ == '__main__':
    main()
