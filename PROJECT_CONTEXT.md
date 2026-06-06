# PROJECT_CONTEXT.md
# ai-context-tool — Claude Code Handoff Document

## Problem Statement

Developers using AI coding extensions in VS Code (with Claude Sonnet/Haiku access via
enterprise GenAI gateways) are hitting monthly token cost limits ($200/month cap).
Root cause: the extension auto-indexes entire repos on every session, generating
massive cache writes (70% of total token usage). Cache writes cost 3-4x more than
cache reads.

## Solution

A lightweight, open source CLI tool that maintains a set of curated `.ai-context/`
markdown files per repo. These files act as a manual RAG system — giving the AI
model a precise map of the codebase instead of letting it index everything.

Key insight: AI coding agents spend most tokens on **orientation, not problem solving**.
A 12,000-token session often only needed 800 tokens of actual work. The `.ai-context/`
system eliminates orientation cost.

---

## Validated Results

- Cache writes dropped drastically per 1k requests after adopting `.ai-context/` files
- Cost reduction confirmed on real Vue.js and Streamlit projects
- Approach maps to established RAG and context compaction patterns

---

## Folder Structure to Build

```
ai-context-tool/                  ← repo root
├── README.md                     ← before/after numbers, quick start
├── setup.py / pyproject.toml     ← pip installable
├── ai_context/
│   ├── __init__.py
│   ├── init.py                   ← scans repo, generates initial .ai-context/ files
│   ├── find_context.py           ← identifies relevant files for a task
│   ├── sync_context.py           ← post-session update script
│   └── utils.py                  ← shared helpers
├── templates/
│   ├── ARCHITECTURE.md           ← repo structure map template
│   ├── DECISIONS.md              ← architectural decisions template
│   ├── CURRENT_TASK.md           ← per-session task context template
│   └── skills/
│       ├── fix-bug.md
│       ├── new-component.md
│       ├── add-api-endpoint.md
│       └── refactor.md
├── .git/hooks/
│   └── post-commit               ← auto-runs sync after every commit
└── tests/
    └── test_find_context.py
```

---

## Core Scripts — Logic Already Designed

### 1. `init.py` — One-time repo setup
- Scans repo structure using `find` or `os.walk`
- Excludes: `node_modules`, `dist`, `build`, `__pycache__`, lock files, `.git`
- Uses a cheap model (Haiku or Gemini Flash) to generate initial `ARCHITECTURE.md`
- Creates all `.ai-context/` template files
- Writes `.ai-context/.gitignore` to exclude `CURRENT_TASK.md` from git

**Key logic:**
```python
EXCLUDE_DIRS = {
    'node_modules', 'dist', 'build', '__pycache__',
    '.git', '.venv', 'venv', 'coverage', '.next'
}
EXCLUDE_FILES = {
    'package-lock.json', 'yarn.lock', 'poetry.lock',
    '*.min.js', '*.min.css'
}
```

### 2. `find_context.py` — Pre-session file discovery (most important script)
- Takes a task description as CLI argument
- Reads `ARCHITECTURE.md` and `DECISIONS.md`
- Calls Haiku/cheap model to identify the 3-5 relevant files for the task
- Inlines those file contents directly into `CURRENT_TASK.md`
- Result: Sonnet session starts with everything it needs, zero hunting

**Usage:**
```bash
python find_context.py "add validation to the login form"
# or after pip install:
aicontext task "add validation to the login form"
```

**Core logic:**
```python
def find_relevant_files(task: str, arch: str, decisions: str) -> list[str]:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"""Given this repo architecture:
{arch}

And these decisions:
{decisions}

For this task: "{task}"

List ONLY the file paths that are directly relevant.
No explanation. One path per line. Maximum 5 files."""
        }]
    )
    return response.content[0].text.strip().split("\n")

def populate_current_task(task: str, files: list[str]):
    with open(".ai-context/CURRENT_TASK.md", "w") as out:
        out.write(f"## Task\n{task}\n\n## Relevant Files\n")
        for fpath in files:
            fpath = fpath.strip()
            if os.path.exists(fpath):
                out.write(f"\n### {fpath}\n```\n")
                with open(fpath) as code:
                    out.write(code.read())
                out.write("\n```\n")
```

### 3. `sync_context.py` — Post-session context update
- Gets git diff from last commit
- Gets current repo structure
- Sends both + existing `ARCHITECTURE.md` to cheap model
- Writes updated `ARCHITECTURE.md`
- Designed to run automatically via git post-commit hook

**Usage:**
```bash
python sync_context.py
# or automatically via git hook
```

**Core logic:**
```python
def get_git_diff() -> str:
    return subprocess.check_output(
        ["git", "diff", "HEAD~1", "--stat", "--unified=2"]
    ).decode()

def update_architecture_md(structure: str, diff: str, current: str) -> str:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Update this ARCHITECTURE.md based on recent changes.
Keep it under 300 lines. Only update what changed.

Current ARCHITECTURE.md:
{current}

Repo structure:
{structure}

Recent git diff:
{diff}

Return only the updated markdown, no explanation."""
        }]
    )
    return response.content[0].text
```

---

## Model Strategy (Important)

| Task | Model | Reason |
|---|---|---|
| Repo discovery, init | Gemma (free) or Haiku | Cheap orientation work |
| find_context.py calls | Haiku | Cheap, fast file identification |
| sync_context.py calls | Haiku | Simple summarization |
| Actual coding sessions | Sonnet | Quality code generation only |

The tool itself should be model-agnostic via environment variable:
```bash
AICONTEXT_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_API_KEY=your_key
```

---

## Session Discipline Rules (Document in README)

1. **Hard session boundary** — end session the moment a feature works, not when
   the whole task feels done. New code = growing context = snowballing cost.
2. **Same file + same feature** = stay in session. Different file or concern = new session.
3. **$5 per session budget** — confirmed effective in testing.
4. **Always run `find_context.py` before starting a Sonnet session** — never let
   Sonnet hunt for files itself.
5. **Run `sync_context.py` after every commit** — keep ARCHITECTURE.md fresh.

---

## Skills Template Contents

### `skills/fix-bug.md`
```markdown
## Task: Fix Bug

Context files to read first:
- .ai-context/ARCHITECTURE.md
- .ai-context/DECISIONS.md
- .ai-context/CURRENT_TASK.md (contains relevant files already inlined)

Process:
1. Read the error message fully before touching any code
2. State your hypothesis before making changes
3. Change ONE thing at a time
4. Confirm fix before moving to next issue
```

### `skills/new-component.md`
```markdown
## Task: New Component

Context files to read first:
- .ai-context/ARCHITECTURE.md
- .ai-context/DECISIONS.md
- .ai-context/CURRENT_TASK.md

Rules:
- Use Composition API only (no Options API)
- Props must be typed
- Follow existing naming conventions in ARCHITECTURE.md
- Use shared components from the path listed in ARCHITECTURE.md
- Do not read files outside CURRENT_TASK.md without asking first
```

### `skills/refactor.md`
```markdown
## Task: Refactor

Context files to read first:
- .ai-context/ARCHITECTURE.md
- .ai-context/DECISIONS.md
- .ai-context/CURRENT_TASK.md

Rules:
- Explain the refactor plan BEFORE writing any code
- Get confirmation before proceeding
- Do not expand scope beyond files in CURRENT_TASK.md
```

---

## Target Users

- Individual developers using VS Code AI extensions with token cost limits
- Teams on enterprise GenAI gateways (no control over extension behaviour)
- Anyone using Claude Code, Cursor, Continue.dev, Copilot with large repos
- Works with any model: Claude, Gemini, Gemma, GPT

---

## Differentiator vs Existing Tools

- **CLAUDE.md / AGENTS.md** — manual, no tooling
- **Cursor .cursorrules** — extension-specific, no file discovery
- **Continue.dev context providers** — complex setup
- **RAG tools (Pinecone, Weaviate)** — infrastructure-heavy, overkill for one dev

This tool: **local, zero infrastructure, works in 5 minutes, any extension, any model.**

---

## Build Order for v1

1. `init.py` — get the folder structure and templates generating correctly
2. `find_context.py` — the core value, most important to get right
3. `sync_context.py` — post-session update automation
4. `post-commit` git hook — wires sync into normal git workflow
5. `pip install` packaging — `pyproject.toml`, CLI entry points
6. `README.md` — lead with before/after token numbers

---

## CLI Commands to Expose (after pip install)

```bash
aicontext init          # one-time setup for a repo
aicontext task "..."    # populate CURRENT_TASK.md before a session
aicontext sync          # update ARCHITECTURE.md after a session
aicontext status        # show what's in .ai-context/ and when last updated
```

---

## Environment Variables

```bash
ANTHROPIC_API_KEY=...               # required
AICONTEXT_MODEL=claude-haiku-4-5-20251001   # default, overridable
AICONTEXT_MAX_FILES=5               # max files inlined in CURRENT_TASK.md
AICONTEXT_MAX_LINES=300             # max lines per context file
```

---

## GitHub Repo Launch Checklist

- [ ] Before/after token cost numbers in README (real data from Vish's project)
- [ ] Quick start: install + first command under 5 minutes
- [ ] Works with any VS Code AI extension (not tied to one tool)
- [ ] Post on r/ClaudeAI, r/cursor, r/LocalLLaMA on launch
- [ ] Write dev.to post: "How I cut AI coding token costs by X%"
- [ ] VS Code marketplace extension as v2 goal

---

*Generated from conversation on June 5, 2026.*
*Do not give Claude Code this file and then ask it to read the whole repo.*
*Start with: "Read PROJECT_CONTEXT.md, then let's build init.py first."*

---

## V1 Workflow Fixes (Critical — Do Before Launch)

### Fix 1 — Remove CLI friction from daily workflow (CRITICAL)
Current flow requires developer to run `aicontext task "..."` in terminal before
opening VS Code extension. This breaks natural coding flow and won't be adopted.

**Solution: File watcher on CURRENT_TASK.md**
- Developer edits CURRENT_TASK.md directly in VS Code (describe task in plain text)
- File watcher detects save → auto-runs find_context → inlines relevant files
- No terminal context switching required
- Add to `init.py` as a background watcher process:

```python
# watcher.py — runs in background after init
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class TaskFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith("CURRENT_TASK.md"):
            run_find_context()  # auto-populate relevant files on save
```

CURRENT_TASK.md template after fix:
```markdown
## Task
<!-- Describe your task here and save — files will auto-populate below -->

## Relevant Files
<!-- Auto-populated by aicontext watcher — do not edit manually -->
```

---

### Fix 2 — Make API key optional (CRITICAL for enterprise users)
Many target users (enterprise devs on internal gateways) cannot get personal
Anthropic API keys. Tool must work without one.

**Solution: Add --manual flag to init and sync**
```bash
aicontext init --manual
# Creates .ai-context/ folder and all template files
# Skips AI-generated ARCHITECTURE.md
# Prints instructions for populating manually or via Gemma/ChatGPT
```

When --manual flag used, print:
```
✓ Created .ai-context/ folder structure
✓ Templates ready for manual population

To populate ARCHITECTURE.md:
  Option A: Paste your repo structure into Gemma/ChatGPT (free)
            and ask: "Generate an ARCHITECTURE.md from this structure"
  Option B: Fill in manually — see template comments for guidance

No API key required for basic usage.
```

---

### Fix 3 — Init output must be readable and actionable
Current init runs silently. Developer has no confidence it worked correctly.

**Solution: Structured init output**
```
aicontext init output:

✓ Scanned 2,151 files (ignored 1,847 in node_modules/dist/build)
✓ ARCHITECTURE.md — 52 lines, detected: Vue 3, Pinia, Axios
✓ DECISIONS.md — ready for your notes
✓ CURRENT_TASK.md — edit this before each session
✓ Skills generated: new-component.md, fix-bug.md, refactor.md (Vue stack)
✓ Git hook installed — context syncs automatically after commits

Top files identified — does this look right?
  src/components/Auth/LoginForm.vue
  src/store/auth.js
  src/api/client.js
  src/router/index.js
  src/composables/useAuth.js

Review .ai-context/ARCHITECTURE.md before your first session.
Next: Edit CURRENT_TASK.md and describe what you're building.
```

---

### Fix 4 — Stack detection for relevant skills (HIGH)
Generic skills get ignored. Skills must match the developer's actual stack.

**Solution: Detect stack during init**
```python
def detect_stack(repo_path: str) -> list[str]:
    stacks = []
    # Check package.json
    pkg = load_json(f"{repo_path}/package.json")
    if "vue" in pkg.get("dependencies", {}): stacks.append("vue")
    if "react" in pkg.get("dependencies", {}): stacks.append("react")
    if "next" in pkg.get("dependencies", {}): stacks.append("nextjs")
    # Check requirements.txt
    reqs = read_file(f"{repo_path}/requirements.txt")
    if "streamlit" in reqs: stacks.append("streamlit")
    if "fastapi" in reqs: stacks.append("fastapi")
    if "django" in reqs: stacks.append("django")
    return stacks
```

Generate stack-specific skills:
- Vue detected → new-component.md uses Composition API, Pinia conventions
- React detected → new-component.md uses hooks, prop-types/TypeScript
- Streamlit detected → new-page.md uses st.session_state conventions
- FastAPI detected → new-endpoint.md uses Pydantic models, dependency injection

---

### Fix 5 — Surface stale context via status command (MEDIUM)
Git hook only helps disciplined committers. Most devs code for hours before committing.
Stale ARCHITECTURE.md silently causes bad sessions.

**Solution: aicontext status with staleness warning**
```bash
aicontext status

.ai-context health:
  ARCHITECTURE.md  — updated 3 days ago  ⚠️  consider running aicontext sync
  DECISIONS.md     — updated 12 days ago ⚠️
  CURRENT_TASK.md  — updated today       ✓
  Watcher          — running             ✓

Estimated savings (since init, 47 sessions):
  Cache writes avoided: ~18.2M tokens
  Estimated cost saved: ~$54.60
  vs baseline (418k tokens/session on this repo size)
```

The savings counter makes value tangible every time they check status.
This is the most important retention mechanic — shows ROI over time.

---

## V2 Roadmap — VS Code Extension (Post-Launch)

Once v1 CLI gains traction, a VS Code extension removes all remaining friction.
This is the natural evolution and where sustained adoption lives.

### What the extension adds

**Status bar integration**
- Shows `.ai-context` health in VS Code bottom bar at all times
- Green dot = context fresh, yellow = stale, red = not initialised
- Click to run `aicontext sync` or `aicontext status` without leaving VS Code

**CURRENT_TASK.md sidebar panel**
- Dedicated sidebar panel showing current task and inlined files
- Edit task description directly in panel → auto-triggers find_context
- No need to open/edit the .md file manually

**Auto-sync on file save**
- Detects when source files change significantly
- Prompts: "Files changed since last sync — update ARCHITECTURE.md? [Yes/Later]"
- Removes the git hook dependency entirely

**Session cost estimator**
- Before starting a session shows: "Estimated context size: 7,239 tokens (~$0.027)"
- After session shows actual vs estimated — builds trust over time

**One-click init**
- Command palette: `aicontext: Initialize repository`
- Runs init, shows output in VS Code output panel
- No terminal required

### Extension tech stack
```
vscode-aicontext/
  src/
    extension.ts        ← activation, command registration
    statusBar.ts        ← health indicator in bottom bar
    sidebarPanel.ts     ← CURRENT_TASK.md webview panel
    watcher.ts          ← file change detection
    contextEngine.ts    ← wraps Python CLI calls via child_process
  package.json          ← VS Code extension manifest
```

Language: TypeScript (VS Code extension standard)
Calls existing Python CLI under the hood — no logic duplication
Publish to VS Code Marketplace as `aicontext`

---

## Updated Build Order

### V1 — CLI (build now with Claude Code)
1. `init.py` — with stack detection + readable output
2. `find_context.py` — core file discovery logic
3. `watcher.py` — file watcher on CURRENT_TASK.md (replaces CLI task step)
4. `sync_context.py` — post-session update
5. `status.py` — staleness check + savings counter
6. `--manual` flag on init and sync
7. `post-commit` git hook
8. `pyproject.toml` — pip installable, CLI entry points
9. `tests/` — validation test suite + benchmark script
10. `README.md` — benchmark numbers first, then quick start

### V2 — VS Code Extension (after v1 traction)
1. Status bar health indicator
2. CURRENT_TASK.md sidebar panel
3. Auto-sync on file save
4. One-click init from command palette
5. Session cost estimator
6. Publish to VS Code Marketplace

---

## Updated CLI Commands

```bash
aicontext init              # one-time setup, detects stack, generates skills
aicontext init --manual     # setup without API key, manual ARCHITECTURE.md
aicontext sync              # update ARCHITECTURE.md after coding session
aicontext sync --manual     # print diff for manual update via Gemma
aicontext status            # health check + staleness warnings + savings counter
aicontext watch             # start file watcher on CURRENT_TASK.md (auto mode)
```

Note: `aicontext task "..."` kept for power users but no longer the primary flow.
Primary flow is: edit CURRENT_TASK.md → save → watcher auto-populates files.

---

## Context Engineering Positioning (for README and launch posts)

Andrej Karpathy (June 2025, now at Anthropic):
"Context engineering is the delicate art and science of filling the context window
with just the right information for the next step. Too little or of the wrong form
and the LLM doesn't have the right context for optimal performance. Too much or too
irrelevant, and the LLM costs might go up, and performance might come down."

aicontext is a context engineering tool for local codebases.
It implements Karpathy's definition as a practical CLI — automatically selecting
the right 3-5 files from thousands, keeping context lean, sessions focused, costs low.

Benchmark (Hoppscotch — 2,151 files, 12-package monorepo):
  Without aicontext: 418,697 tokens / $1.57 per session (cache write)
  With aicontext:      7,239 tokens / $0.027 per session (cache write)
  Subsequent sessions: 7,239 tokens / $0.002 per session (cache read)
  Reduction: 98.3%

---

*Updated: June 6, 2026*
*Start Claude Code with: "Read PROJECT_CONTEXT.md, then let's build init.py first."*
*Build one script at a time. Commit between scripts. Keep sessions under $5.*
