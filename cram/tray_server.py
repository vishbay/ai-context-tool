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

def _find_cram() -> str:
    """Locate the cram CLI binary.

    In a frozen .app bundle sys.executable is inside Contents/MacOS/ and has
    no sibling cram script, so fall back to PATH.  In a normal venv the sibling
    approach is fast and reliable.
    """
    import shutil
    if not getattr(sys, 'frozen', False):
        candidate = Path(sys.executable).parent / 'cram'
        if candidate.exists():
            return str(candidate)
    found = shutil.which('cram')
    if found:
        return found
    return 'cram'  # will surface a clear FileNotFoundError at call time

_CRAM = _find_cram()

from flask import Flask, jsonify, request, send_from_directory

from cram.status import get_status_dict

CONTEXT_DIR  = '.cram-ai-context'
DEFAULT_PORT = 49155

_UI_DIR = Path(__file__).parent / 'tray_ui'

# Mutable active repo — updated by /set-repo, read by tray menu callbacks
_active_repo: list[str] = ['']
_active_port: list[int] = [DEFAULT_PORT]

# Branch-switch alert — set by POST /notify-branch-switch, cleared on task set or dismiss
_branch_alert: list[str | None] = [None]

# Callback registered by tray.py to show the popup window from a background thread
_show_window_cb: list = [None]


def get_active_repo() -> str:
    return _active_repo[0]

def get_active_port() -> int:
    return _active_port[0]

def register_show_callback(cb) -> None:
    """Register a callable that opens and positions the popup window."""
    _show_window_cb[0] = cb

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
# Lockfiles inflate repo_tokens without reflecting real orientation cost.
_SKIP_FILES = {'package-lock.json', 'yarn.lock', 'poetry.lock', 'Cargo.lock', 'pnpm-lock.yaml'}


def _estimate_repo_tokens(root: str) -> tuple[int, int]:
    total = files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_SCAN]
        for fname in filenames:
            if fname in _SKIP_FILES:
                continue
            if os.path.splitext(fname)[1] in _SCAN_EXTS:
                try:
                    with open(os.path.join(dirpath, fname), errors='ignore') as f:
                        total += len(f.read())
                    files += 1
                except OSError:
                    pass
    return total // 4, files

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
        result = get_status_dict(root())
        result['branch_alert'] = _branch_alert[0]
        return jsonify(result)

    # ── metrics ───────────────────────────────────────────────────

    @app.get('/metrics')
    def get_metrics():
        cd = context_dir()
        if not os.path.isdir(cd):
            return jsonify({'initialized': False})

        now = time.time()

        from cram.health import context_health
        health = context_health(root())
        files  = health['files']  # tokens, lines, budget, budget_status per file

        _FROZEN = {'ARCHITECTURE.md', 'SYMBOLS.md', 'DECISIONS.md', 'GOTCHAS.md'}
        total_cram = sum(f['tokens'] for f in files.values())
        frozen_tok = sum(f['tokens'] for n, f in files.items() if n in _FROZEN)

        from cram.cost_model import (
            CostInputs, daily_costs, MODEL_BASE, orientation_tokens, ORIENT_FILES,
        )

        repo_tokens, repo_files = _estimate_repo_tokens(root())
        savings_pct = max(0, int((1 - total_cram / max(repo_tokens, 1)) * 100))

        inp   = CostInputs(repo_tokens=repo_tokens, repo_files=repo_files, frozen_tok=frozen_tok)
        costs = daily_costs(inp, MODEL_BASE['Sonnet 4.6'])

        task_path = os.path.join(cd, 'CURRENT_TASK.md')
        try:
            from cram.session import load_session
            sess = load_session(root())
            set_at = sess.get('set_at') if sess else None
        except Exception:
            set_at = None
        if set_at is None and os.path.exists(task_path):
            set_at = os.path.getmtime(task_path)
        last_task_age = _age_short(now - set_at) if set_at else None

        arch_path = os.path.join(cd, 'ARCHITECTURE.md')
        last_sync_age = (
            _age_short(now - os.path.getmtime(arch_path))
            if os.path.exists(arch_path) else None
        )

        return jsonify({
            'initialized':   True,
            'cram_tokens':   total_cram,
            'repo_tokens':   repo_tokens,
            'repo_files':    repo_files,
            'savings_pct':   savings_pct,
            'orient_tokens': costs['orient_tokens'],
            'orient_files':  ORIENT_FILES,
            'nocram_daily':  round(costs['nocram_daily'], 4),
            'cram_daily':    round(costs['cram_daily'],   4),
            'daily_saving':  round(costs['daily_saving'], 4),
            'files':         files,
            'last_task_age': last_task_age,
            'last_sync_age': last_sync_age,
        })

    # ── measured usage ────────────────────────────────────────────

    _measured_cache: list = [None, 0.0]  # [data, timestamp]

    @app.get('/measured')
    def get_measured():
        now = time.time()
        if _measured_cache[0] is not None and now - _measured_cache[1] < 60:
            return jsonify(_measured_cache[0])
        from cram.usage import measured_usage
        data = measured_usage(root()) or {'available': False}
        _measured_cache[0] = data
        _measured_cache[1] = now
        return jsonify(data)

    # ── actions ───────────────────────────────────────────────────

    @app.post('/task')
    def run_task():
        data        = request.get_json(silent=True) or {}
        description = (data.get('description') or '').strip()
        target      = (data.get('target') or 'all').strip()

        if not description:
            return jsonify({'success': False, 'error': 'description is required'}), 400

        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'task', description, '--target', target],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            if success:
                _branch_alert[0] = None
                from cram.targets import save_default_target
                save_default_target(root(), target)
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/notify-branch-switch')
    def notify_branch_switch():
        data   = request.get_json(silent=True) or {}
        branch = (data.get('branch') or 'unknown').strip()
        from cram.sync_context import reset_task
        reset_task(root())
        _branch_alert[0] = branch
        if _show_window_cb[0]:
            try:
                _show_window_cb[0]()
            except Exception:
                pass
        return jsonify({'success': True})

    @app.post('/dismiss-branch-alert')
    def dismiss_branch_alert():
        _branch_alert[0] = None
        return jsonify({'success': True})

    @app.post('/sync')
    def run_sync():
        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'sync'],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/init')
    def run_init():
        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'init'],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/continue')
    def run_continue():
        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'continue'],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/decide')
    def run_decide():
        data     = request.get_json(silent=True) or {}
        decision = (data.get('decision') or '').strip()
        if not decision:
            return jsonify({'success': False, 'error': 'decision is required'}), 400

        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'decide', decision],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/benchmark')
    def run_benchmark():
        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'benchmark'],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/status-run')
    def run_status_cmd():
        def _stream():
            import subprocess as _sp
            proc = _sp.Popen(
                [_CRAM, 'status'],
                cwd=root(),
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    yield f"data: {json.dumps({'line': stripped})}\n\n"
            proc.wait()
            success = proc.returncode == 0
            yield f"data: {json.dumps({'done': True, 'success': success})}\n\n"

        from flask import Response, stream_with_context
        return Response(
            stream_with_context(_stream()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

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
        import threading
        threading.Timer(0.15, lambda: os._exit(0)).start()
        return jsonify({'success': True})

    # ── model discovery & settings ────────────────────────────────

    @app.get('/suggest')
    def get_suggest():
        from cram.utils import load_settings
        if load_settings().get('auto_suggest', True) is False:
            return jsonify({'suggestion': None})
        from cram.suggest import suggest_task
        return jsonify({'suggestion': suggest_task(root())})

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
        allowed = {'context_model', 'coding_model', 'ollama_url', 'proxy', 'auto_suggest'}
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
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (_CONFIG_DIR / 'port').write_text(str(free_port))
    except Exception:
        pass
    flask_app = create_app(repo_path)
    flask_app.run(
        host='127.0.0.1',
        port=free_port,
        debug=False,
        use_reloader=False,
    )
