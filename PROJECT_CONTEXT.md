# PROJECT_CONTEXT.md
# cram-ai — Claude Code Handoff Document

## Problem Statement

Developers using AI coding extensions (Claude Code, Cursor, Copilot, Continue.dev, Windsurf)
are burning expensive cache-write tokens on orientation before a single line of code is written.
AI extensions auto-index entire repos on every session. Cache writes cost 3–4× more than
cache reads. On a large monorepo this can consume $1.57 per session before any coding happens.

## Solution

A lightweight, open source CLI called `cram` (pip package: `cram-ai`) that maintains a set of
curated `.ai-context/` markdown files per repo. These act as a manual RAG system — giving
the AI model a precise map of the codebase instead of letting it index everything.

Key insight: AI coding agents spend most tokens on **orientation, not problem solving**.
A 12,000-token session often only needs 800 tokens of actual work. `.ai-context/`
eliminates orientation cost.

---

## Validated Results (Hoppscotch benchmark)

Repo: hoppscotch/hoppscotch — 12-package monorepo, 2,151 source files, Vue 3 + NestJS + Tauri

| Scenario | Tokens | Cost / session | Reduction |
|---|---|---|---|
| Without cram (full index) | 418,697 | $1.57 | — |
| With cram (first session) | 7,239 | $0.027 | 98.3% |
| With cram (cached) | 7,239 | $0.002 | 99.9% |

Pricing basis: Claude Sonnet cache-write rate ($3.75/1M tokens).

---

## Current Repo Structure

```
cram-ai/                          ← repo root
├── README.md
├── PROJECT_CONTEXT.md
├── setup.py                      ← shim for pip < 21.3
├── pyproject.toml                ← pip installable, entry points
├── pytest.ini
├── cram/                         ← Python package
│   ├── __init__.py               ← __version__ = "0.1.0"
│   ├── cli.py                    ← single `cram` entry point, dispatches subcommands
│   ├── init.py                   ← one-time repo setup
│   ├── find_context.py           ← pre-session file discovery + --target writing
│   ├── sync_context.py           ← post-commit ARCHITECTURE.md update
│   ├── status.py                 ← context freshness + staleness warnings + get_status_dict()
│   ├── hooks.py                  ← git post-commit hook install/uninstall
│   ├── targets.py                ← writes context to cram-owned tool instruction files
│   ├── menubar.py                ← Mac-only (rumps) — superseded by tray.py, kept for reference
│   ├── tray.py                   ← cross-platform tray entry point (pystray + pywebview)
│   ├── tray_server.py            ← local Flask bridge (port 49155) — popup JS ↔ cram CLI
│   ├── tray_ui/
│   │   ├── popup.html            ← popup UI (task + metrics + workflow guide)
│   │   ├── popup.css             ← dark cosmic theme, compact/full modes, help panel
│   │   └── popup.js              ← fetch /status + /metrics, minimize/expand, help toggle
│   └── utils.py                  ← call_model(), strip_code_fence(), routing logic
└── tests/
    ├── test_utils.py             ← 14 tests
    ├── test_init.py              ← 23 tests
    ├── test_find_context.py      ← 23 tests
    └── test_sync.py              ← 11 tests (72 total, all passing)
```

---

## CLI Commands

```bash
cram init [path]                        # one-time repo setup
cram task "<description>" [--target T]  # populate CURRENT_TASK.md + auto-load into tool
cram sync [path]                        # update ARCHITECTURE.md after a commit
cram status [path]                      # show .ai-context/ freshness
cram hook install|uninstall [path]      # manage git post-commit hook
cram menu [path]                        # launch Mac menu bar app
```

`--target` choices: `cursor | claude | copilot | codex | windsurf | all`

Set a permanent default in `.ai-context/config.toml`:
```toml
[task]
default_target = "cursor"
```

---

## Context Directory

`.ai-context/` is created at the repo root by `cram init`.

| File | Purpose | Managed by |
|---|---|---|
| `ARCHITECTURE.md` | Repo structure, tech stack, key files | `cram init` + `cram sync` |
| `DECISIONS.md` | Architectural rules the AI must respect | Developer (manual) |
| `CURRENT_TASK.md` | Task description + inlined relevant files | `cram task` |
| `.gitignore` | Excludes `CURRENT_TASK.md` from git | `cram init` |
| `config.toml` | Optional: `default_target`, etc. | Developer (manual) |
| `CLAUDE.md` | Claude Code auto-loaded context (if target=claude) | `cram task` |
| `AGENTS.md` | Codex auto-loaded context (if target=codex) | `cram task` |

---

## --target: How Context Auto-Loads Per Tool

Each target writes a **cram-owned file** the tool reads automatically.
No shared developer-managed files (CLAUDE.md, copilot-instructions.md, etc.) are ever modified.

| Target | File written | How it loads |
|---|---|---|
| `cursor` | `.cursor/rules/cram-task.md` | Cursor reads every file in `.cursor/rules/` |
| `claude` | `.ai-context/CLAUDE.md` | Claude Code reads `CLAUDE.md` recursively in subdirs |
| `copilot` | `.github/cram-task.md` | Requires one-time include in `copilot-instructions.md` |
| `codex` | `.ai-context/AGENTS.md` | Codex reads `AGENTS.md` recursively in subdirs |
| `windsurf` | `.windsurf/rules/cram-task.md` | Windsurf reads every file in `.windsurf/rules/` |

---

## Model Routing (utils.py)

`call_model()` routes based on `AICONTEXT_MODEL` env var:

| Condition | Route |
|---|---|
| `AICONTEXT_MODEL` contains `/` | litellm (`provider/model` string) |
| `ANTHROPIC_API_KEY` set | Anthropic SDK directly |
| Neither | `claude -p` subprocess (uses Claude Code's active session) |

The third path means **no API key is required** when running inside a Claude Code session.

```bash
# Examples
export AICONTEXT_MODEL="gemini/gemini-2.5-flash"   # litellm → Google
export AICONTEXT_MODEL="openai/gpt-4o-mini"         # litellm → OpenAI
export AICONTEXT_MODEL="ollama/mistral"              # litellm → local Ollama
export AICONTEXT_MODEL="claude-haiku-4-5"            # Anthropic SDK
# (unset) → claude -p subprocess, zero config
```

---

## Two-Tier Model Strategy

Use cheap models for all cram maintenance. Reserve expensive models for actual coding.

| Task | Recommended model | Cost |
|---|---|---|
| `cram init`, `cram task`, `cram sync` | Gemini Flash / Haiku | ~$0.001/call |
| Actual coding sessions | Sonnet / GPT-4o | Pay only for real work |

---

## Cross-Platform Tray App

Replaces the Mac-only `menubar.py` (rumps). Works on macOS, Windows, and Linux.

### Framework decision

| Framework | Mac | Windows | Linux | Notes |
|---|---|---|---|---|
| **pystray + pywebview** | ✓ | ✓ | ✓ | **Pick this** — pure Python, pip install, HTML popup UI |
| rumps | ✓ | ✗ | ✗ | Current impl — Mac only, replace |
| toga | ✓ | ✓ | partial | Heavier dependency |
| tauri | ✓ | ✓ | ✓ | Best quality but requires Rust + JS — overkill for v1 |

### Install

```bash
pip install 'cram-ai[tray]'   # installs pystray pillow pywebview
cram-menu                      # or: cram menu
```

### Architecture

```
cram/
  tray.py          ← replaces menubar.py
    pystray         → system tray icon + right-click menu (all 3 platforms)
    pywebview       → floating HTML popup window (identical UI on all platforms)
  tray_ui/
    popup.html      ← popup UI (task input + metrics + actions)
    popup.css       ← styling using CSS variables
    popup.js        ← calls cram CLI via fetch() to local Flask/http server
  tray_server.py   ← tiny local HTTP server (Flask or http.server)
                      bridges pywebview JS ↔ cram CLI subprocesses
```

### Popup UI — three states

**State 1 — Fresh (green)**
```
┌─────────────────────────────┐
│ 🧠 cram-ai      ● fresh     │
│ ─────────────────────────── │
│  2.1M tokens saved  $6.30   │
│ ─────────────────────────── │
│ Current task                │
│ [what are you building?  ]  │
│ [         Cram it         ] │
│ ─────────────────────────── │
│ ↺ Sync context              │
│ 📁 Open .ai-context/   │
│ ⏻  Quit                     │
└─────────────────────────────┘
```

**State 2 — Stale (amber)**
- Status badge shows "3d old" in amber
- Metrics still visible
- Sync context action highlighted

**State 3 — Not initialised (red)**
- Status badge shows "not init" in red
- Task input disabled, placeholder: "run cram init first"
- Primary action becomes "Run cram init"
- Metrics show "—"

### How pywebview bridges to CLI

```python
# tray_server.py — tiny local server
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route('/task', methods=['POST'])
def run_task():
    description = request.json['description']
    target = request.json.get('target', 'all')
    result = subprocess.run(
        ['cram', 'task', description, '--target', target],
        capture_output=True, text=True
    )
    return jsonify({'success': result.returncode == 0, 'output': result.stdout})

@app.route('/sync', methods=['POST'])
def run_sync():
    result = subprocess.run(['cram', 'sync'], capture_output=True, text=True)
    return jsonify({'success': result.returncode == 0})

@app.route('/status', methods=['GET'])
def get_status():
    result = subprocess.run(
        ['cram', 'status', '--json'],
        capture_output=True, text=True
    )
    return jsonify({'status': result.stdout})
```

```python
# tray.py — pystray entry point
import pystray
from PIL import Image
import threading
import webview
from cram.tray_server import app as flask_app

def start_server():
    flask_app.run(port=49155, debug=False)

def open_popup(icon, item):
    webview.create_window(
        'cram-ai',
        url='http://localhost:49155/popup',
        width=260, height=380,
        frameless=True,
        on_top=True
    )
    webview.start()

def build_tray():
    icon_img = Image.open('cram/tray_ui/icon.png')
    menu = pystray.Menu(
        pystray.MenuItem('Open', open_popup, default=True),
        pystray.MenuItem('Sync context', lambda: subprocess.run(['cram', 'sync'])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Quit', lambda: icon.stop())
    )
    icon = pystray.Icon('cram-ai', icon_img, 'cram-ai', menu)
    threading.Thread(target=start_server, daemon=True).start()
    icon.run()
```

### Linux caveat

Linux tray support varies by desktop environment:
- GNOME: requires AppIndicator extension (common on Ubuntu)
- KDE, XFCE, i3: works natively
- Document in README: "Linux tray requires a system tray — see setup notes"

### Packaging as standalone app

```bash
# Mac → .app
pip install py2app
py2app setup.py       # dist/cram-ai.app

# Windows → .exe
pip install pyinstaller
pyinstaller --onefile --windowed cram/tray.py

# Linux → AppImage (optional, v2)
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AICONTEXT_MODEL` | `''` (uses claude -p) | Model to use for cram's own calls |
| `ANTHROPIC_API_KEY` | — | Optional when inside Claude Code session |
| `AICONTEXT_MAX_FILES` | `5` | Max files inlined into CURRENT_TASK.md |
| `AICONTEXT_MAX_LINES` | `300` | Max lines per file when inlining |

---

## Session Protocol (Document in README)

1. Run `cram task "..." --target <tool>` before opening your AI extension
2. The tool auto-loads `.ai-context/CURRENT_TASK.md` context — no hunting
3. Hard session boundary: end session when the feature works, not when everything feels done
4. Same file + same concern = stay in session. Different file or concern = new session
5. `cram sync` fires automatically via git hook after every commit

---

## Documentation

HTML docs page: `/Users/vishbay/SideQuests/cram-ai.html`
- Dark cosmic theme (pink/purple/cyan gradient)
- Sections: overview, how it works, install, CLI commands, daily workflow,
  saving cache writes (token flow viz + two-tier strategy + 6-step protocol),
  model providers, session rules, env vars, benchmark, extensions
- Pure HTML/CSS, no dependencies

---

## Context Engineering Positioning

Andrej Karpathy (June 2025):
> "Context engineering is the delicate art and science of filling the context window
> with just the right information for the next step."

cram is a context engineering tool for local codebases. It implements this as a practical
CLI — automatically selecting the right 3–5 files from thousands, keeping context lean,
sessions focused, costs low.

---

## Agentic Workflow Integration

In single developer sessions, orientation cost is a one-time hit per session.
In agentic workflows it multiplies — every agent call starts a fresh context window,
paying the orientation tax independently. A 10-step agentic task = 10 separate
orientation costs. cram as agent infrastructure reduces this to a flat ~7,000 token
cost per call regardless of repo size.

### Why agentic workflows make the problem worse

66% of developers cite AI solutions that are "close but not quite right" as their biggest frustration. The best agents minimise that gap through better codebase context. cram solves context quality before the agent starts — not after.

Code duplication has risen 4x with AI adoption. Dev teams juggling six or more tools report shipping confidence of just 28%. This is not a tools problem — it's a context problem. cram addresses this directly by maintaining accurate, shared architectural context.

### Three integration patterns

**Pattern 1 — Pre-flight context injection**
Run cram before spawning any coding agent. The agent reads `.ai-context/CURRENT_TASK.md`
instead of indexing the repo itself:

```python
import subprocess
from cram import prepare_context  # Python SDK (v2)

# Before any agent call
subprocess.run(['cram', 'task', agent_task, '--target', 'all'])
# or with SDK:
context = prepare_context(task=agent_task, repo_path='.')
agent.run(system_context=context)
```

Works with: LangChain, AutoGen, CrewAI, Claude Code SDK, any framework.

**Pattern 2 — Multi-agent context routing**
Each sub-agent receives only the context relevant to its role.
cram acts as a context router between the orchestrator and sub-agents:

```
Orchestrator: "add rate limiting to the REST API"
       ↓ cram identifies: routes/api.js, middleware/auth.js, config/limits.js
       ↓
  Agent A (code writer)  → routes/api.js + middleware only
  Agent B (test writer)  → existing test files only
  Agent C (doc updater)  → README + API docs only
```

Token cost stays flat regardless of how many agents run in parallel.

**Pattern 3 — Context compaction between steps**
Long agentic runs accumulate context fast (turn 10 costs ~7x turn 1).
cram sync after each step resets context to a compact baseline:

```python
def on_agent_step_complete(step_output):
    subprocess.run(['cram', 'sync', '--from-output', step_output])
    # next step reads fresh compact ARCHITECTURE.md
    # instead of full accumulated history
```

### Agentic savings at scale

| Scenario | Without cram | With cram |
|---|---|---|
| Single dev session | $1.57 | $0.027 |
| 10-step agentic task | $15.70 | $0.27 |
| 100-step autonomous run | $157.00 | $2.70 |
| Team of 5, 100 sessions/month | $785.00 | $13.50 |

---

## MCP Server (V2)

The Model Context Protocol, introduced by Anthropic in late 2024, has become a standard for agent communication. MCP tools for planning, memorialising conversations, and ingesting user files mitigate context limitations and hallucination risks.

Exposing cram as an MCP server means any MCP-compatible agent (Claude, Cursor, Windsurf,
Codex) can call cram's context engineering natively — zero integration code required.

```json
{
  "name": "cram_prepare_context",
  "description": "Find and prepare relevant files for a coding task. Returns CURRENT_TASK.md content with inlined file contents.",
  "parameters": {
    "task": { "type": "string", "description": "What the agent is trying to build or fix" },
    "repo_path": { "type": "string", "description": "Path to the repo root" },
    "max_files": { "type": "integer", "default": 5 }
  }
}
```

```json
{
  "name": "cram_sync",
  "description": "Update ARCHITECTURE.md after code changes. Call after completing a task.",
  "parameters": {
    "repo_path": { "type": "string" }
  }
}
```

### MCP server architecture

```python
# cram/mcp_server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from cram.find_context import find_relevant_files, populate_current_task
from cram.sync_context import update_architecture_md

server = Server("cram-ai")

@server.call_tool()
async def prepare_context(task: str, repo_path: str = ".") -> str:
    files = find_relevant_files(task, repo_path)
    return populate_current_task(task, files, repo_path)

@server.call_tool()
async def sync_context(repo_path: str = ".") -> str:
    return update_architecture_md(repo_path)

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write)
```

Add to Claude Code, Cursor, or any MCP client config:
```json
{
  "mcpServers": {
    "cram-ai": {
      "command": "cram-mcp",
      "args": []
    }
  }
}
```

---

## Python SDK (V2)

Allows cram to be imported directly into agent orchestration code
without subprocess calls. Cleaner integration for LangChain, AutoGen, CrewAI.

```python
# Public SDK surface
from cram import prepare_context, sync_context, get_status

# Prepare context for a task
context = prepare_context(
    task="add rate limiting to the API",
    repo_path=".",
    max_files=5,
    model="gemini/gemini-2.5-flash"  # optional override
)
# Returns: { "task": str, "files": list[str], "content": str }

# Sync after changes
sync_context(repo_path=".")

# Check context health
status = get_status(repo_path=".")
# Returns: { "fresh": bool, "days_old": int, "tokens_saved": int }
```

```python
# LangChain integration example
from cram import prepare_context
from langchain.agents import AgentExecutor

def run_coding_agent(task: str):
    ctx = prepare_context(task=task)
    agent = build_agent(system_prompt=ctx['content'])
    return AgentExecutor(agent=agent).invoke({"input": task})
```

---

## Additional Features (Research-Backed)

### 1. Incremental context updates (not full regeneration)
The ACE paper (Stanford/SambaNova, October 2025) demonstrates that incremental updates reduce drift and latency by up to 86% compared to context regeneration strategies. Incremental updates preserve accumulated accuracy and keep the change set reviewable.

Current `cram sync` regenerates ARCHITECTURE.md from scratch. V2 should diff and patch:
```bash
cram sync --incremental   # only update sections that changed, not full regen
```

### 2. Context coverage gaps detection
Finding gaps requires a structured walk through the technology stack — "does our context file cover how we use X?" for each significant dependency. A context-evaluator tool can automate this by scanning the repository and surfacing coverage gaps.

```bash
cram audit   # scans repo vs ARCHITECTURE.md, reports what's missing or stale
             # output: "12 new files not in ARCHITECTURE.md, 3 deleted files still referenced"
```

### 3. Team shared context (`.ai-context/` in git)
Currently CURRENT_TASK.md is gitignored (per-developer). ARCHITECTURE.md and
DECISIONS.md should be committed and shared — the orientation cost is paid once
and benefits the whole team. Add a `cram team` command:

```bash
cram team init    # marks ARCHITECTURE.md + DECISIONS.md for git tracking
cram team sync    # pulls latest shared context before starting work
```

Enterprise value: a team of 5 sharing context = 5x the savings with 1x the maintenance.

### 4. Session cost tracking (per repo, persistent)
Currently `cram status` shows staleness only. Add a persistent SQLite log of
estimated savings per session, surfaced in the tray app and status command:

```bash
cram status
# Context: fresh ✓
# Sessions logged: 47
# Tokens saved (estimated): 18.2M
# Cost saved (estimated): $54.60 @ Sonnet rates
# vs baseline: 418k tokens/session on this repo
```

SQLite schema:
```sql
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY,
  repo_path TEXT,
  task TEXT,
  context_tokens INTEGER,
  baseline_tokens INTEGER,
  model TEXT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5. `--manual` flag for enterprise users (no API key)
Many enterprise developers cannot use personal API keys (internal gateway only).
cram must work without one for the largest segment of the target market.

```bash
cram init --manual   # creates folder structure + empty templates
                     # prints: "Populate ARCHITECTURE.md manually or paste into Gemma/ChatGPT"
cram sync --manual   # prints git diff formatted for manual paste into any AI chat
```

### 6. Stack-aware skill generation
Detect tech stack during init, generate specific DECISIONS.md and skills:

```python
STACK_DETECTORS = {
    'vue':       lambda pkg: 'vue' in pkg.get('dependencies', {}),
    'react':     lambda pkg: 'react' in pkg.get('dependencies', {}),
    'nextjs':    lambda pkg: 'next' in pkg.get('dependencies', {}),
    'streamlit': lambda reqs: 'streamlit' in reqs,
    'fastapi':   lambda reqs: 'fastapi' in reqs,
    'django':    lambda reqs: 'django' in reqs,
    'nestjs':    lambda pkg: '@nestjs/core' in pkg.get('dependencies', {}),
}
```

Output: stack-specific `skills/new-component.md`, `skills/fix-bug.md`, etc.
Vue gets Composition API rules. FastAPI gets Pydantic model conventions. etc.

### 7. File watcher — zero-friction task prep
`watchdog` monitors CURRENT_TASK.md for saves. Developer edits the task description
and saves — cram auto-populates relevant files without running any command.

```bash
cram watch   # starts background watcher, exits cleanly on Ctrl+C
             # or runs automatically when tray app is open
```

```python
# watcher.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from cram.find_context import auto_populate_on_save

class TaskFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if 'CURRENT_TASK.md' in event.src_path:
            auto_populate_on_save(event.src_path)
```

---

## What's Built (V1 — Shipped)

- [x] `cram init` — repo scan, ARCHITECTURE.md generation, hook install
- [x] `cram task` — file discovery, CURRENT_TASK.md population, `--target` flag
- [x] `cram sync` — git diff → ARCHITECTURE.md update
- [x] `cram status` — freshness display, staleness warning, `get_status_dict()`
- [x] `cram hook` — install/uninstall git post-commit hook
- [x] `targets.py` — cram-owned instruction files for cursor/claude/copilot/codex/windsurf
- [x] `tray.py` — cross-platform tray app (pystray + pywebview)
  - Native OS dropdown as default (live status, Set task… native dialog, Sync)
  - "Open popup" opt-in → full 280px HTML window
  - Popup: minimize to header strip / expand, ? workflow guide panel, task input, metrics
- [x] `find_git_root()` in utils.py — all commands auto-detect git root by walking up from cwd; works from any subdirectory
- [x] `tray_server.py` — local Flask bridge on port 49155
- [x] `tray_ui/` — popup.html + popup.css + popup.js
- [x] `pip install 'cram-ai[tray]'` extra — pystray + pillow + pywebview + flask
- [x] Model routing: litellm / Anthropic SDK / claude -p subprocess
- [x] `pyproject.toml` — pip installable as `cram-ai`, CLI entry `cram` + `cram-menu`
- [x] 72 tests, all passing
- [x] README with benchmark numbers
- [x] HTML docs page (dark cosmic theme)

---

## What's Next

### Next sprint — highest friction, highest value

| Priority | Item | Why now |
|---|---|---|
| 1 | **pipx install** | Current venv story is too complex; pipx is one line, handles PATH automatically |
| 2 | **Session cost tracking** (SQLite) | Shows users the value cram is delivering; drives retention |
| 3 | **MCP server** | Unlocks every agentic workflow without any integration code |
| 4 | **cram audit** | Context quality degrades silently; audit surfaces drift before it causes bad codegen |
| 5 | **`--manual` flag** | Largest enterprise segment can't use API keys; this unblocks them |

---

### V1.5 — Install & packaging (highest friction point right now)
- [ ] **`pipx` as canonical install path** — `brew install pipx && pipx install 'cram-ai[tray]'`; document in README + HTML docs; `cram-menu` on PATH with no venv management
- [ ] **Homebrew tap** (`homebrew-cram-ai`) — `brew install vishbay/cram-ai/cram-ai`; write Formula/cram-ai.rb; requires PyPI publish first
- [ ] **PyPI publish** — `twine upload`; set version to 0.1.0; prerequisite for Homebrew
- [ ] **Mac .app bundle** — `py2app` wrapping `cram-menu`; drag-to-Applications; auto-launch on login option
- [ ] **Windows .exe** — `PyInstaller --onefile --windowed cram/tray.py`

### V1.5 — Tray app polish
- [ ] **Popup position** — anchor popup below tray icon (not center-screen); requires getting icon position from pystray
- [ ] **Auto-start on login** — macOS LaunchAgent plist; Windows registry run key
- [ ] **Repo picker** — if launched outside a git repo, show a folder-chooser dialog
- [ ] **Target remembered** — persist last-used `--target` selection in config.toml; restore on popup open

### V1.5 — CLI improvements
- [ ] **Session cost tracking** — SQLite log per repo; `cram status` shows cumulative savings ("18.2M tokens saved, $54.60"); surfaced in popup metrics
- [ ] **`cram audit`** — scan repo vs ARCHITECTURE.md; report new files not indexed, deleted files still referenced
- [ ] **`--manual` flag** — `cram init --manual` creates empty templates; `cram sync --manual` prints formatted git diff for paste into any AI chat (no API key required)
- [ ] **Stack detection** — detect Vue/React/FastAPI/Django/NestJS during init; generate stack-specific DECISIONS.md + skills templates
- [ ] **`cram watch`** — `watchdog` monitors CURRENT_TASK.md; auto-populates relevant files on save; runs in background when tray app is open
- [ ] **`cram sync --incremental`** — diff-patch ARCHITECTURE.md instead of full regen (86% less drift per ACE paper)
- [ ] **`cram team init/sync`** — commit ARCHITECTURE.md + DECISIONS.md to git; `cram team sync` pulls shared context before starting work

### V2 — MCP server (highest leverage for agentic workflows)
- [ ] **`cram-mcp`** entry point — exposes `cram_prepare_context` and `cram_sync` as MCP tools
- [ ] Works with Claude Code, Cursor, Windsurf, Codex — zero integration code
- [ ] `pip install 'cram-ai[mcp]'` extra

### V2 — Python SDK
- [ ] `from cram import prepare_context, sync_context, get_status`
- [ ] LangChain / AutoGen / CrewAI integration examples
- [ ] `cram sync --from-output` for context compaction between agentic steps

### V2 — VS Code extension
- [ ] Status bar dot (green/amber/red)
- [ ] CURRENT_TASK.md sidebar panel with inline edit
- [ ] Auto-sync on file save; one-click init from command palette
- [ ] Publish to VS Code Marketplace

---

## Differentiator

- **CLAUDE.md / AGENTS.md** — manual, no tooling
- **Cursor .cursorrules** — extension-specific, no file discovery
- **Continue.dev context providers** — complex setup
- **RAG tools (Pinecone, Weaviate)** — infrastructure-heavy, overkill for one dev

cram: **local, zero infrastructure, works in 30 seconds, any extension, any model.**

---

*Updated: June 6, 2026 — added agentic workflow integration (3 patterns), MCP server spec, Python SDK, 7 additional features (incremental sync, audit, team context, session tracking, manual flag, stack detection, file watcher), cross-platform tray app spec, and expanded roadmap.*
*Start a new session with: "Read PROJECT_CONTEXT.md" — gives full current state.*
