**v0.2.1 Architecture**

MCP-first delivery with file-based delivery fallback: `get_context()` tool serves stable context via MCP for Claude Code, Cursor, Windsurf, Zed. Other tools use `cram task --target` for file-based delivery.

**Context loading (get_context() PRIMARY, SessionStart hook optional fallback):**
- **get_context() as FIRST action**: Developer calls `get_context("task description")` as the FIRST action in every session to load full context pipeline (symbol pre-filter → keyword scoring → LLM selection → extraction → markdown). With no args, reloads from CURRENT_TASK.md without LLM call. Prepends staleness warning when context is stale (band 6–7) or critical (band 8–10), recommending `cram sync`.
- **SessionStart hook** (`cram_session_start.py`): optional auto-load reads `.cram-ai-context/CURRENT_TASK.md` and injects as AI context with systemMessage. Skips silently if no active task. Fallback when get_context() not called.
- **PostToolUse hook** (`cram_post_context.py`): shows systemMessage with task name after `get_context()` MCP call completes
- **Installation**: `cram init` writes hook scripts to `.claude/hooks/`, registers cram-ai MCP server, and wires both hooks into `.claude/settings.json` automatically

**Per-task context pipeline (four stages):**
1. **Symbol pre-filter** (`_score_files()`): Scores files from SYMBOLS.md by keyword overlap with task description using regex-based keyword extraction (3+ chars, filtered stop-words). Returns top candidates ranked by filename stem match (+2.0), directory component match (+1.5), symbol name match (+1.0). Narrows candidate list before LLM call, avoiding hallucination.
2. **LLM selection**: Cheap model picks relevant files from scored candidates (or full SYMBOLS if no pre-filter hits) and names key identifiers. DECISIONS and GOTCHAS excluded from selection prompt — they don't help pick files. These arrive separately via frozen context layer.
3. **Excerpt extraction**: Pulls identifier-focused excerpts (max 15 lines) from selected files, not full files. Searches for exact symbol matches and related context.
4. **Context write**: Assembles CURRENT_TASK.md with task, contract fields (Scope, Out of Scope, Definition of Done), relevant files + excerpts, model recommendations, and frozen context pointers. Typically 800–1,500 tokens.

**Task contract in CURRENT_TASK.md:**
Three structured fields follow `## Task` to give the agent explicit scope rails:
- **Scope** — auto-derived from directories of selected files. Agent stays within these bounds.
- **Out of Scope** — placeholder for user to fill in explicit exclusions before execution (e.g., "billing/", "legacy/"). Prevents exploratory reads.
- **Definition of Done** — placeholder for user to define acceptance criteria. Prevents early stopping and over-extension.

**Critical workflow:**
- Developer runs `cram init` → installs hooks, registers MCP server, generates frozen files
- Developer calls `cram task "description"` → sets active task in CURRENT_TASK.md
- **Next session: call `get_context()` as FIRST action** before answering any question or writing code. SessionStart hook provides optional auto-load but is not the primary path.
- Git post-commit hook runs `cram sync` automatically → refreshes ARCHITECTURE.md + SYMBOLS.md, warns on over-budget files

**Context layers (frozen):**
- `ARCHITECTURE.md` — repo structure, tech stack, critical invariants (auto-refreshed by post-commit, 2000-tok budget)
- `SYMBOLS.md` — important types, functions, constants; candidate pool for file selection (regex-based, deterministic, no budget)
- `DECISIONS.md` — architectural decisions, conventions (manual, append via `cram decide`, 600-tok budget)
- `GOTCHAS.md` — non-obvious traps, side effects (manual, append via `cram gotcha`, 400-tok budget)

**Cost estimation & measured usage (v0.2.1):**
Orientation-based model: without cram, agents cold-start each session by reading ~ORIENT_FILES (default 8) raw files to understand repo structure. Estimated per-session at base input price (tool-result reads), not cache write.

- **cost_model.py** — single source of truth: MODEL_BASE (Opus/Sonnet/Haiku), cache multipliers (WRITE_MULT=1.25, READ_MULT=0.10), workload defaults
- **FILE_BUDGETS** — soft per-file token limits: ARCHITECTURE (2000), DECISIONS (600), GOTCHAS (400), CURRENT_TASK (800). `budget_status()` returns 'ok' | 'near' | 'over'
- **usage.py** — measures actual usage from Claude Code transcripts. Returns {sessions, writes, reads, est_cost} for last N days
- **audit.py** — measures orientation tax (reads before first edit) from Claude Code session transcripts with per-project breakdown and cost estimates

**Staleness & context health (v0.2.1):**
Graduated 0–10 staleness score via `status.py:staleness_score()`: primary signal is commits since ARCHITECTURE.md was last updated. Score maps to bands: fresh (0–2), acceptable (3–5), stale (6–7), critical (8–10). `health.py:context_health()` unifies staleness, per-file tokens, and budget status. `get_context()` prepends one-line warning when band is stale/critical. Tray badge shows band + score. `get_health()` returns deterministic markdown safe to cache.

**MCP tools:**
- `get_context(task?)` — runs full four-stage pipeline or reloads CURRENT_TASK.md; prepends staleness warning if stale/critical. **Call this FIRST in every session.**
- `get_health()` — returns staleness score (0–10) + band + commits_since_sync + per-file token + budget status
- `get_architecture()`, `get_symbols()`, `get_decisions()`, `get_gotchas()` — read-only access to context layers
- `add_file()` — append file excerpts to CURRENT_TASK.md mid-task
- `run_benchmark()` — cost model for your repo

**CLI commands (key ones):**
- `cram init` — one-time setup
- `cram task "..."` — run pipeline, write CURRENT_TASK.md with contract fields
- `cram sync` — refresh ARCHITECTURE.md + SYMBOLS.md from git diff, warn on over-budget files
- `cram audit [--days N] [--all]` — measure orientation tax from Claude Code transcripts
- `cram status` — show staleness band, score, commits_since_sync, per-file budgets
- `cram doctor` — health check

Repo structure:
cram-ai/
  .claude/
    settings.json
    settings.local.json
    hooks/
      cram_post_context.py
      cram_session_start.py
  cram/
    __init__.py
    __main__.py
    add_context.py
    audit.py
    autostart.py
    benchmark.py
    cli.py
    cost_model.py
    decide.py
    doctor.py
    find_context.py
    gotcha.py
    health.py
    hooks.py
    init.py
    mcp_server.py
    menubar.py
    session.py
    status.py
    suggest.py
    symbols.py
    sync_context.py
    targets.py
    tray.py
    tray_server.py
    usage.py
    utils.py
    vscode.py
    tray_ui/
      popup.css
      popup.html
      popup.js
  scripts/
    build_macos_app.sh
    generate_icns.py
  tests/
    test_cost_model.py
    test_find_context.py
    test_init.py
    test_mcp_server.py
    test_status.py
    test_symbols.py
    test_sync.py
    test_targets.py
    test_usage.py
    test_utils.py