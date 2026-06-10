# cram-ai: MCP-first Delivery Fix

> **This file is the complete brief for a fresh build session.**
> Read it top to bottom before touching code. The problem, fix, and every
> changed file are specified precisely enough to continue without prior context.

---

## 0. Why this plan exists

cram-ai already works — it reduces token usage by generating a stable context layer
(ARCHITECTURE.md, SYMBOLS.md, DECISIONS.md) via cheap models (Haiku/Gemini Flash)
so expensive models (Sonnet) can skip repo auto-indexing.

The owner's real data: **cache writes are 60% of all tokens**. The stable context
layer already cut that 50%. The remaining 50% is caused by a delivery flaw, not a
content flaw.

**The flaw:** cram writes its context into CLAUDE.md (prefix injection). The prefix
gets cache-written on every new session and every 5-minute TTL expiry. Large prefix
= large cache-write = expensive. The MCP server already exists in cram-ai but is
not the primary delivery path.

**The fix:** make MCP the only delivery path for Claude Code. CLAUDE.md becomes a
2-line pointer ("add cram mcp to your settings"). Content moves to MCP tool results
(conversation tail, not prefix). Prefix drops from ~10K tokens to ~1-2K. Cache-write
cost drops proportionally.

**Non-destructive:** all other tools (Cursor, Windsurf, Copilot, Codex) keep prefix
injection — they have no MCP option. Only the Claude Code delivery path changes.

---

## 1. The precise flaw (read this before any code)

### What happens today (Claude Code path)

1. User runs `cram task "fix the rate limiter"`
2. `find_context.py` calls Haiku → gets file list → extracts excerpts → writes `CURRENT_TASK.md`
3. `targets.py: write_to_target(root, 'claude', ...)` → upserts content into `CLAUDE.md`
4. Claude Code reads CLAUDE.md at session start → entire content enters the prefix
5. **Cache-write of ~10K tokens fires on every new session / TTL expiry**
6. Next session: repeat from step 1

### What should happen (the fix)

1. User runs `cram task "fix the rate limiter"` (CLI still works, just stops writing CLAUDE.md)
2. `find_context.py` writes `CURRENT_TASK.md` to disk only (MCP server reads it)
3. Claude Code session starts → prefix is just tool definitions (~1-2K tokens)
4. Model calls `get_context("fix the rate limiter")` → tool result returns the content
5. **Cache-write surface: ~1-2K tokens instead of ~10K**

Tool results are in the conversation tail. They do not expand the prefix. They are
not cache-written on the next session start. This is the correct delivery mechanism.

---

## 2. What changes, what stays

### Changes

| File | Change |
|---|---|
| `cram/targets.py` | Deprecate `claude` target. Writing to CLAUDE.md is now opt-in via `--inject` flag, not the default. |
| `cram/init.py` | `init_repo()` — write a minimal CLAUDE.md pointer instead of calling `install_global_claude_md()`. Stop injecting architecture content at init time. |
| `cram/cli.py` | `cram task` — remove `--target` default of `claude`. Add `--inject` flag for backward compat. |
| `cram/hooks.py` | `install_global_claude_md()` — change to write a pointer-only CLAUDE.md (see §3 below). |
| `cram/mcp_server.py` | Minor: sort results deterministically, remove any volatile fields from served text. |
| `cram/benchmark.py` | Add MCP-delivered scenario. Show prefix-injected vs MCP-delivered cost, not just "with cram vs without cram". |
| `README.md` | Rewrite to lead with MCP path. Show actual savings (prefix size × TTL frequency). Remove "96% token reduction" claim referencing prefix-injected benchmark (that benchmark compared against a strawman). |

### Stays exactly the same

- `cram init` content generation (ARCHITECTURE.md, SYMBOLS.md, DECISIONS.md) — this works, don't touch
- `cram sync` — correct, no changes
- `cram decide` — correct, no changes
- `cram mcp` MCP server tools — already correct, minor stability pass only
- All non-Claude targets in `targets.py` (cursor, windsurf, copilot, codex)
- All 57 existing tests — they must stay green

---

## 3. Precise changes per file

### `cram/targets.py`

**Goal:** make the `claude` target write a pointer-only CLAUDE.md instead of injecting content.

The pointer CLAUDE.md content (write this instead of the full context block):

```markdown
<!-- cram-ai: start -->
cram-ai context is served via the MCP server — not this file.

Add cram-ai to your .claude/settings.json:
  {
    "mcpServers": {
      "cram-ai": {
        "command": "cram",
        "args": ["mcp", "--repo", "/absolute/path/to/this/repo"]
      }
    }
  }

Then call get_context("your task") at the start of each session.
<!-- cram-ai: end -->
```

Change `_render()` for `target == 'claude'` to return this pointer instead of `task_content`.

Add a new export `CLAUDE_MCP_POINTER` constant with the above string so `init.py` and
`hooks.py` can use the same text.

Keep the `--inject` escape hatch: if the caller explicitly passes `inject=True` to
`write_to_target()`, use the old content-injection behavior (for users who can't use MCP).

### `cram/init.py`

**Goal:** `cram init` should not inject content into CLAUDE.md.

In `init_repo()`:
- Replace `install_global_claude_md()` call with a call that writes the pointer-only CLAUDE.md
  to the repo root (not the global user file).
- The pointer CLAUDE.md is committed with the repo so teammates get it automatically.
- Remove or guard the code that inlines architecture content into any prefix file.

Also: update the "Next steps" print output to say:
```
  3. Add cram-ai to your .claude/settings.json (see CLAUDE.md for the snippet)
  4. Call get_context("your task") at the start of each session
```
(Remove "Run `cram task` before each coding session" from the Claude Code path.)

### `cram/cli.py`

**Goal:** `cram task` stops writing to CLAUDE.md by default.

Find where `cram task` dispatches to `write_to_target` (or `write_to_all_detected`).
- Remove the automatic write to `claude` target.
- Add `--inject` flag: if passed, write to CLAUDE.md using the old content (backward compat).
- Default behavior: write CURRENT_TASK.md to disk only. Print:
  ```
  Context ready. Call get_context("<task>") via the cram-ai MCP server to load it.
  ```

### `cram/hooks.py`

**Goal:** `install_global_claude_md()` — check what this writes to the global `~/.claude/CLAUDE.md`
and change it to write the pointer text instead of injected content.

Read this file first (not read yet — do it at build time). Apply the same pointer-only
change as targets.py.

### `cram/mcp_server.py`

**Goal:** byte-stable output, no volatile fields in served text.

Minor changes only:
- `get_symbols()`: when returning filtered results, sort the matching lines before joining.
- `get_context()`: remove the `<!-- cram-ai context · N files · ~X tokens -->` header comment
  from the returned string. That comment contains a token count that varies and prevents
  deterministic output. Move it to a separate line the model can ignore, or drop it.
- `get_architecture()`, `get_decisions()`: already return file content as-is — correct, no change.

### `cram/benchmark.py`

**Goal:** add the MCP-delivered scenario so the benchmark shows the real savings.

Add a third scenario: "With cram MCP — prefix is 1-2K tokens (tool definitions only),
content delivered as tool results." This is the correct comparison for the fixed tool.

The three scenarios:
1. No cram — full repo auto-indexed (baseline)
2. cram prefix-injected — current (broken) delivery
3. cram MCP-delivered — new (correct) delivery ← add this

Show: prefix tokens, cache-write cost per session, cache-read cost per session,
and break-even sessions (how many sessions until the stable layer pays for itself).

### `README.md`

**Goal:** honest, accurate description of what the tool now does.

Structure:
1. **What it does** — stable context layer (Haiku-generated) delivered via MCP. Keeps prefix tiny.
2. **Why MCP, not CLAUDE.md** — one paragraph: prefix cache-writes fire on every TTL expiry;
   MCP tool results don't expand the prefix. Link to benchmark.
3. **Quick start** — `cram init` → add MCP config → `cram mcp` → call `get_context("task")`
4. **CLI reference** — keep existing table, update `cram task` description
5. **Provider support** — keep as-is
6. **Non-Claude tools** — note that Cursor/Windsurf still use prefix injection (no MCP option)
7. **Benchmarks** — replace current table with the three-scenario benchmark from benchmark.py

Remove: the "96% token reduction" claim until the new benchmark is in place.
The old benchmark compared prefix-injected cram vs full-repo auto-indexing — both
inject into the prefix, so the comparison was valid for token count but didn't
account for cache-write frequency correctly.

---

## 4. Build phases

Each phase ends with all existing tests green plus any new tests for the phase.

### Phase 1 — Fix the CLAUDE.md pointer (lowest risk, immediate value)
**Files:** `targets.py`, `hooks.py`, `init.py`

1. Add `CLAUDE_MCP_POINTER` constant to `targets.py`.
2. Change `_render(target='claude', ...)` to return the pointer text.
3. Add `inject=False` param to `write_to_target()` — if True, use old behavior.
4. Update `init_repo()` in `init.py` to write the pointer CLAUDE.md.
5. Read `hooks.py` and apply the same pointer change to `install_global_claude_md()`.

**Acceptance:** `cram init` on a fresh repo writes a CLAUDE.md containing only the MCP
config snippet, not injected content. `cram task "..."` no longer overwrites CLAUDE.md.
All 57 existing tests pass.

### Phase 2 — `cram task` default behavior
**Files:** `cli.py`

1. Remove automatic `write_to_target(root, 'claude', ...)` from `cram task` dispatch.
2. Add `--inject` flag.
3. Update the success print message.

**Acceptance:** `cram task "fix auth"` writes CURRENT_TASK.md, prints the MCP reminder,
does NOT modify CLAUDE.md. `cram task --inject "fix auth"` writes CLAUDE.md (old behavior).

### Phase 3 — MCP stability pass
**Files:** `mcp_server.py`

1. Remove volatile token-count header from `get_context()` return value.
2. Sort `get_symbols()` filtered results.
3. Add a test: call each tool twice with identical store state, assert output is identical.

**Acceptance:** new determinism test passes. All 57 existing tests pass.

### Phase 4 — Benchmark + README
**Files:** `benchmark.py`, `README.md`

1. Add MCP-delivered scenario to `benchmark.py`.
2. Rewrite `README.md` as described in §3.

**Acceptance:** `cram mcp` then `run_benchmark()` tool returns a table with all three
scenarios. README accurately describes the fixed tool.

---

## 5. Non-goals

- Do not change the content generation (init, sync, decide) — it works.
- Do not remove Cursor/Windsurf/Copilot/Codex prefix injection — they have no alternative.
- Do not add new MCP tools — the existing five are sufficient.
- Do not change the CURRENT_TASK.md format — `get_context()` already reads it correctly.
- Do not touch the 57 existing tests except to fix any that test the old CLAUDE.md injection behavior.
- Do not rename the project or change pyproject.toml entry points.
- Do not add auth, packaging, or distribution features.

---

## 6. File reference (read before editing)

```
cram/
  cli.py              — arg dispatch; find the `task` subcommand handler
  init.py             — init_repo(); calls install_global_claude_md() — change this
  targets.py          — write_to_target(), _render() — the main change lives here
  hooks.py            — install_global_claude_md() — read first, then apply pointer change
  find_context.py     — find_relevant_files(), populate_current_task() — no changes needed
  sync_context.py     — post-commit sync — no changes needed
  mcp_server.py       — MCP tools — minor stability pass only
  benchmark.py        — add MCP scenario
  symbols.py          — regex extraction — no changes needed
  session.py          — session timing — no changes needed
  utils.py            — helpers — no changes needed

tests/               — 57 tests, all must stay green
README.md            — rewrite last
```

---

## 7. Definition of done

- [ ] `cram init` writes a pointer-only CLAUDE.md (MCP config snippet), not injected content.
- [ ] `cram task "..."` writes CURRENT_TASK.md and prints the MCP reminder. Does not touch CLAUDE.md.
- [ ] `cram task --inject "..."` still writes CLAUDE.md (backward compat).
- [ ] All 57 existing tests pass.
- [ ] New determinism test: each MCP tool called twice → identical output.
- [ ] `run_benchmark()` shows three-scenario table including MCP-delivered path.
- [ ] README leads with MCP path and accurately describes cache-write savings.
- [ ] Owner has wired `cram mcp` into Claude Code settings and confirmed `get_context()` works.
