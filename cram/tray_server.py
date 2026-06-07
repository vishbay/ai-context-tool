"""Local HTTP server — bridges the popup UI to the cram CLI.

Runs on 127.0.0.1:49155 in a daemon thread started by tray.py.
All subprocess calls use the active repo path, which can be changed
at runtime via POST /set-repo.
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Always use the cram binary from the same venv as this interpreter
_CRAM = str(Path(sys.executable).parent / 'cram')

from flask import Flask, jsonify, request, send_from_directory

from cram.status import get_status_dict

CONTEXT_DIR  = '.cram-ai-context'
DEFAULT_PORT = 49155

_UI_DIR = Path(__file__).parent / 'tray_ui'

# Mutable active repo — updated by /set-repo, read by tray menu callbacks
_active_repo: list[str] = ['']
_active_port: list[int] = [DEFAULT_PORT]

def get_active_repo() -> str:
    return _active_repo[0]

def get_active_port() -> int:
    return _active_port[0]

# ── recent repos ──────────────────────────────────────────────────

_CONFIG_DIR  = Path.home() / '.config' / 'cram-ai'
_RECENT_FILE = _CONFIG_DIR / 'recent_repos.json'
_MAX_RECENT  = 5

def _load_recent_repos() -> list[str]:
    try:
        paths = json.loads(_RECENT_FILE.read_text())
        return [p for p in paths if os.path.isdir(p)][:_MAX_RECENT]
    except Exception:
        return []

def _save_recent_repo(path: str) -> None:
    try:
        existing = _load_recent_repos()
        deduped  = [path] + [p for p in existing if p != path]
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(json.dumps(deduped[:_MAX_RECENT]))
    except Exception:
        pass

# ── token helpers ─────────────────────────────────────────────────

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

def _age_short(secs: float) -> str:
    s = int(secs)
    if s < 60:    return f"{s}s"
    if s < 3600:  return f"{s // 60}m"
    if s < 86400: return f"{s // 3600}h"
    return f"{s // 86400}d"

# ── app factory ───────────────────────────────────────────────────

def create_app(repo_path: str) -> Flask:
    """Build and return the Flask app. repo_path sets the initial active repo."""
    _active_repo[0] = os.path.abspath(repo_path)
    _save_recent_repo(_active_repo[0])

    app = Flask(__name__, static_folder=None)

    # helpers that always read the current active repo
    def root() -> str:
        return _active_repo[0]
    def context_dir() -> str:
        return os.path.join(root(), CONTEXT_DIR)

    # ── UI static files ───────────────────────────────────────────

    @app.get('/')
    @app.get('/popup')
    def popup():
        return send_from_directory(str(_UI_DIR), 'popup.html')

    @app.get('/static/<path:filename>')
    def static_file(filename):
        return send_from_directory(str(_UI_DIR), filename)

    # ── repo ──────────────────────────────────────────────────────

    @app.get('/repo')
    def get_repo():
        from cram.targets import load_default_target
        r = root()
        return jsonify({
            'path':           r,
            'name':           os.path.basename(r),
            'default_target': load_default_target(r),
        })

    @app.get('/recent-repos')
    def get_recent_repos():
        recent = _load_recent_repos()
        cur    = root()
        return jsonify([
            {'path': p, 'name': os.path.basename(p), 'active': p == cur}
            for p in recent
        ])

    @app.post('/set-repo')
    def set_repo():
        data = request.get_json(silent=True) or {}
        path = os.path.abspath(data.get('path', '').strip())
        if not path or not os.path.isdir(path):
            return jsonify({'success': False, 'error': 'Path does not exist'}), 400
        _active_repo[0] = path
        _save_recent_repo(path)
        return jsonify({
            'success': True,
            'path':    path,
            'name':    os.path.basename(path),
        })

    # ── status ────────────────────────────────────────────────────

    @app.get('/status')
    def get_status():
        return jsonify(get_status_dict(root()))

    # ── metrics ───────────────────────────────────────────────────

    @app.get('/metrics')
    def get_metrics():
        cd = context_dir()
        if not os.path.isdir(cd):
            return jsonify({'initialized': False})

        now = time.time()
        files: dict = {}
        total_cram  = 0

        for fname in ('ARCHITECTURE.md', 'DECISIONS.md', 'CURRENT_TASK.md'):
            path = os.path.join(cd, fname)
            if os.path.exists(path):
                with open(path, errors='ignore') as f:
                    content = f.read()
                tokens = len(content) // 4
                total_cram += tokens
                files[fname] = {'tokens': tokens, 'lines': content.count('\n')}

        repo_tokens = _estimate_repo_tokens(root())
        savings_pct = max(0, int((1 - total_cram / max(repo_tokens, 1)) * 100))
        cost_saved  = (repo_tokens - total_cram) / 1_000_000 * 3.75

        task_path = os.path.join(cd, 'CURRENT_TASK.md')
        last_task_age = (
            _age_short(now - os.path.getmtime(task_path))
            if os.path.exists(task_path) else None
        )

        arch_path = os.path.join(cd, 'ARCHITECTURE.md')
        last_sync_age = (
            _age_short(now - os.path.getmtime(arch_path))
            if os.path.exists(arch_path) else None
        )

        return jsonify({
            'initialized':   True,
            'cram_tokens':   total_cram,
            'repo_tokens':   repo_tokens,
            'savings_pct':   savings_pct,
            'cost_saved':    round(cost_saved, 3),
            'files':         files,
            'last_task_age': last_task_age,
            'last_sync_age': last_sync_age,
        })

    # ── actions ───────────────────────────────────────────────────

    @app.post('/task')
    def run_task():
        data        = request.get_json(silent=True) or {}
        description = (data.get('description') or '').strip()
        target      = (data.get('target') or 'all').strip()

        if not description:
            return jsonify({'success': False, 'error': 'description is required'}), 400

        result = subprocess.run(
            [_CRAM,'task', description, '--target', target],
            cwd=root(), capture_output=True, text=True,
        )
        if result.returncode == 0:
            from cram.targets import save_default_target
            save_default_target(root(), target)
        return jsonify({
            'success': result.returncode == 0,
            'output':  result.stdout,
            'error':   result.stderr,
        })

    @app.post('/sync')
    def run_sync():
        result = subprocess.run(
            [_CRAM,'sync'],
            cwd=root(), capture_output=True, text=True,
        )
        return jsonify({
            'success': result.returncode == 0,
            'output':  result.stdout,
            'error':   result.stderr,
        })

    @app.post('/init')
    def run_init():
        result = subprocess.run(
            [_CRAM,'init'],
            cwd=root(), capture_output=True, text=True,
        )
        return jsonify({
            'success': result.returncode == 0,
            'output':  result.stdout,
            'error':   result.stderr,
        })

    @app.post('/open-folder')
    def open_folder():
        import sys as _sys
        cd = context_dir()
        target = cd if os.path.isdir(cd) else root()
        if _sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif _sys.platform == 'win32':
            subprocess.Popen(['explorer', target])
        else:
            subprocess.Popen(['xdg-open', target])
        return jsonify({'success': True})

    @app.post('/quit')
    def quit_app():
        func = request.environ.get('werkzeug.server.shutdown')
        if func:
            func()
        return jsonify({'success': True})

    # ── model discovery & settings ────────────────────────────────

    @app.get('/models')
    def get_models():
        from cram.utils import discover_models, load_settings, pick_context_model, pick_coding_model
        available = discover_models()
        settings  = load_settings()
        return jsonify({
            'available':     available,
            'context_model': settings.get('context_model', 'auto'),
            'coding_model':  settings.get('coding_model',  'auto'),
            'auto_context':  (pick_context_model(available) or {}).get('name', ''),
            'auto_coding':   (pick_coding_model(available)  or {}).get('name', ''),
        })

    @app.get('/settings')
    def get_settings():
        from cram.utils import load_settings
        return jsonify(load_settings())

    @app.post('/settings')
    def post_settings():
        from cram.utils import save_settings
        data = request.get_json(silent=True) or {}
        allowed = {'context_model', 'coding_model', 'ollama_url', 'proxy'}
        save_settings({k: v for k, v in data.items() if k in allowed})
        return jsonify({'success': True})

    return app


def find_free_port(start: int = DEFAULT_PORT, attempts: int = 20) -> int:
    """Return the first free TCP port starting from start."""
    import socket
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}–{start + attempts}")


def run(repo_path: str, port: int = DEFAULT_PORT) -> None:
    """Start the server (blocking). Call from a daemon thread in tray.py."""
    free_port = find_free_port(port)
    _active_port[0] = free_port
    flask_app = create_app(repo_path)
    flask_app.run(
        host='127.0.0.1',
        port=free_port,
        debug=False,
        use_reloader=False,
    )
