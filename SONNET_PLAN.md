# cram-ai: Correctness Fixes + Surface Cut — Execution Plan (for Sonnet)

> Read top to bottom. Two goals, sequenced so they don't fight:
> **Part A** fixes 6 correctness issues. **Part B** cuts redundant frontends and
> hardens the three surfaces we keep (MCP, `cram ui`, `cram audit`).
> Do A before B — don't harden behavior that's still broken.
>
> **The CLI engine stays fully functional.** `init / task / add / continue / sync /
> decide / decisions / gotcha / status / doctor / hook / mcp / ui / audit` all keep
> working. We only remove duplicate *frontends* (tray, menubar, autostart, vscode)
> and one legacy flag (`--inject`). **`cram benchmark` is KEPT** (its cache-write model
> is honest); **`cram vscode` is CUT** (redundant with the three surfaces).

---

## Phase 0 — Safety net (do first)

1. `git checkout -b refactor/correctness-and-cut`
2. Baseline: `python -m pytest -q` — confirm **259 passed** before changing anything.
3. After every task below, re-run `python -m pytest -q`. Never leave tests red.

---

## PART A — Correctness fixes

### A1. Unify task storage (the big one) — slot vs CURRENT_TASK.md incoherence

**Problem:** MCP `get_context(task)` writes to `.ai-context/tasks/<slug>.md` (mcp_server.py:217),
but `_archive_current_task()` (line 50), no-arg reload (line 161), and `add_file()`
(line 427) all read `CURRENT_TASK.md`. Pure-MCP users therefore get: no task history,
broken no-arg reload, and `add_file` editing the wrong file.

**Fix — make the slot the source of truth, with `CURRENT_TASK.md` as a "last active" pointer:**

- In `mcp_server.py`, introduce a module-level `_last_slot_path: str | None = None`
  (or persist `last_slot` to `.ai-context/session.json` via `cram.session`, preferred —
  survives server restarts).
- After `get_context(task)` writes `slot_path`, also record it as the last active slot
  (write the slug to session.json: `save_session(root, task)` already exists in
  `cram.session` — extend it to also store `slug`, or add `set_last_slot(root, slug)`).
- Rewrite the three readers to resolve the active slot first, falling back to
  `CURRENT_TASK.md` for CLI-only users:
  - `_archive_current_task()` → archive the **active slot** content (or CURRENT_TASK.md
    if no slot). Archive BEFORE overwriting the same slug's slot.
  - no-arg `get_context()` (line 161) → read the active slot; fall back to
    `CURRENT_TASK.md`. This makes "reload last task" work for MCP users.
  - `add_file()` (line 427) → append to and return the **active slot**, not
    `CURRENT_TASK.md`. (Also update `cram.add_context.add_files` if it hardcodes
    CURRENT_TASK.md — check `cram/add_context.py`.)
- Keep CLI `cram task` writing `CURRENT_TASK.md` (it has no slug session) — but also
  call the same `set_last_slot`-style pointer so CLI + MCP share one "active" concept.

**Tests (add to tests/test_mcp_server.py):**
- `get_context("foo")` then `get_context()` (no arg) returns foo's content, not empty.
- `get_context("foo")` then `add_file("some.py")` appends to foo's slot and returns it.
- After two `get_context(task)` calls, `TASK_HISTORY.jsonl` has the first task archived.

### A2. Route the pipeline through `call_context_model` (settings currently ignored)

**Problem:** the cost premise is "cheap model for retrieval," but `find_relevant_files`
calls `call_model` (find_context.py:240) and `sync` calls `call_model`
(sync_context.py:51). The `discover_models()` routing + `settings.context_model`
choice are silently ignored; it only works because `call_model`'s CLI fallback
defaults to `haiku`.

**Fix:**
- find_context.py:240 — change `call_model(prompt)` → `call_context_model(prompt)`.
  (`call_context_model` is already imported at line 9.)
- sync_context.py — `update_architecture_md` should use `call_context_model`
  (ARCHITECTURE regeneration is a retrieval/summarization task, the cheap tier).
  Update the import on line 9 accordingly.
- Leave `call_model` for any genuinely "coding-tier" call (there are none in the
  pipeline today — both pipeline calls are context-tier).

**Tests:** in tests/test_find_context.py, monkeypatch `call_context_model` (not
`call_model`) and assert it's the one invoked by `find_relevant_files`. Update any
existing test that patches `call_model` for these paths.

### A3. Remove the vanity "% less than full repo" metric

**Problem:** find_context.py:488–496 prints `"X% less than full repo"` on every
`cram task`. The project's own design retrospective (Principle 7) calls the full-repo
baseline a strawman. Code contradicts docs.

**Fix:**
- Delete the `savings_note` block (find_context.py ~488–496) and the `savings_note`
  interpolation in the final print (~498).
- Replace the closing line with a pointer to the honest metric:
  `print("  Run `cram audit` to measure orientation tax on your real sessions.")`
- Grep for other emitters of the same phrasing: `grep -rn "less than full repo\|% of repo\|full-repo" cram/` and neutralize any in user-facing CLI output. (Leave `benchmark.py`'s cache-write model intact — that one is honest; just don't headline "% of repo".)

### A4. De-duplicate archive logic

**Problem:** `_archive_current_task_to_history` (find_context.py:260) and
`_archive_current_task` (mcp_server.py:47) are near-identical and have drifted
(one adds `slug`, one doesn't).

**Fix:**
- Move one canonical implementation to `cram/session.py` (or a new
  `cram/task_history.py`): `archive_task(root, source_path) -> None` that extracts
  the task line, writes `{ts, task, slug}` to `TASK_HISTORY.jsonl`.
- Replace both call sites to use it. Always include `slug` (use `_task_slug`).
- Keep behavior identical for the `<!-- Session ended` skip guard.

**Tests:** one test in a shared location asserting archive writes a well-formed
JSONL line with ts/task/slug and skips session-ended placeholders.

### A5. chdir concurrency — low-risk hybrid (drop lock, no chdir, join paths)

**Problem:** the `_chdir_lock` (mcp_server.py:191) serializes the whole LLM call, so
"parallel agents" are sequential for the slow part. Slot files isolate output, not
execution. The only real reason chdir exists: `_resolve_path` returns a **relative**
path, and `_extract_excerpt` / `populate_current_task` then open it relative to cwd.

**Risk note:** removing chdir is MODERATE risk, concentrated entirely in the path
contract. Do NOT change `_resolve_path` to return absolute paths — that breaks CLI
tests and makes `CURRENT_TASK.md` headers ugly. Instead use the hybrid below.

**Fix (chosen — low-risk hybrid):**
- In the MCP `get_context` / `add_file` paths, remove `os.chdir(_repo_root)` and the
  `_chdir_lock`.
- Make the file-opening sites root-aware without changing `_resolve_path`'s relative
  return value: in `_extract_excerpt` and `populate_current_task`, open via
  `os.path.join(root, relpath)` when `root` is provided (thread a `root` kwarg through;
  default `root='.'` preserves current CLI behavior and test expectations).
- `_read_context_file` hardcodes `context_path('.', ...)` — in the MCP path this is
  already avoided (MCP uses its own `_read` with absolute `_repo_root`), so no change
  needed there. Leave the CLI `find_context.main()` chdir as-is (it's process-global
  and harmless for a one-shot CLI invocation).
- Keep display paths relative (headers in CURRENT_TASK.md stay `### path/to/file.py`).

**Fallback if the hybrid proves invasive:** keep the lock, but fix the docstring/comment
and any doc claiming concurrent execution — state "output is isolated per slot;
pipeline execution is serialized." (Owner chose the hybrid; only fall back if blocked.)

**Tests:** add an MCP test that runs `get_context(task)` from a cwd OTHER than the repo
root (e.g. `os.chdir(tmp_path)` before calling) and asserts excerpts are still extracted
correctly — this proves the chdir removal didn't break path resolution.

### A6. `_resolve_path` basename ambiguity

**Problem:** find_context.py:72 walks the tree and returns the **first** basename
match — wrong-file risk when multiple files share a name (e.g. several `utils.py`).

**Fix:**
- When the model returns a path that doesn't resolve directly, and the basename walk
  finds **more than one** match, prefer the one whose directory components overlap the
  model's original path string; if still ambiguous, return the raw path unresolved
  (so it surfaces as "suggested but not found" rather than silently wrong).
- Add a test in tests/test_find_context.py with two `utils.py` files asserting the
  closer-path match wins and a fully-ambiguous case stays unresolved.

---

## PART B — Cut to MCP + `cram ui` + `cram audit`, harden the three

### B1. Remove redundant frontends (1,577 LOC, imported only by cli.py)

Delete files: `cram/tray.py`, `cram/tray_server.py`, `cram/menubar.py`,
`cram/autostart.py`, `cram/vscode.py`, and the `cram/tray_ui/` directory.

**KEEP `cram/benchmark.py`** and the `benchmark` CLI command — its cache-write model
is the honest one; leave it untouched (A3 already removed the vanity line, which lived
in find_context.py, not benchmark.py).

Then:
- `cli.py` — remove the `menu`, `autostart`, `vscode` dispatch branches and their
  USAGE lines. Leave the `benchmark` branch and USAGE line in place.
- `pyproject.toml`:
  - remove the `tray` optional-dependency group (`pystray`, `pillow`, `pywebview`, `flask`).
  - remove `cram-menu` and `cram-autostart` from `[project.scripts]`.
  - remove the `tray_ui/*` package-data line.
- Grep for stragglers: `grep -rn "tray\|menubar\|autostart\|vscode\|pystray\|pywebview\|flask" cram/ tests/ docs/ README.md`.
- Delete `tests/test_*` for removed modules if any exist (none currently, but recheck).

### B2. Deprecate the `--inject` / prefix-injection path

`--inject` writes task content into CLAUDE.md — the exact anti-pattern v2 exists to
avoid.

- In `find_context.py` argparse, keep the flag but mark it deprecated in help text and
  print a one-line stderr warning when used: "--inject is deprecated; MCP delivery is
  the supported path. See README."
- Do **not** remove it this pass (some non-MCP tool users may rely on it); just steer
  away. Revisit removal in a later release.

### B3. Harden MCP (`cram/mcp_server.py`)

- Land the A1 slot-coherence fix (above) — this is the core hardening.
- Add explicit error returns (not silent `except Exception: pass`) for the user-facing
  read failures in `get_task_history` and `get_health` — return a short diagnostic
  string so the agent knows something's wrong.
- Add a guard test: calling any tool before `cram init` returns the actionable
  "Run `cram init`" message (several already do — assert it for all of them).

### B4. Harden `cram ui` (`cram/ui.py`)

- Wrap each tab's `refresh_*` in defensive try/except that renders an in-pane error
  string instead of letting a Textual worker crash the app (some already do — make it
  uniform across all five panes).
- Guard empty-state for every tab (no sessions, no history, no decisions) — show a
  friendly "nothing yet" line, never a traceback.
- Add a lightweight smoke test: import `cram.ui`, build the app object, and call each
  `refresh_*` against a temp repo with empty `.ai-context/` — assert no exception.
  (Full Textual interaction tests are out of scope; the smoke test catches the common
  breakage.)

### B5. Harden `cram audit` (`cram/audit.py`)

- Make the magic numbers explicit + overridable: `2_500` tok/file (line 181) and the
  `3.0/1M` Sonnet base (line 182) should be module constants with env overrides
  (`CRAM_AUDIT_TOK_PER_FILE`, `CRAM_AUDIT_BASE_PRICE`), and the output should label them
  as assumptions.
- The cost figure is modelled — print a one-line caveat: "cost is modelled from
  reads_before_edit; the ratio is the measured signal."
- Add tests in a new `tests/test_audit.py` (exists — extend it): feed a synthetic
  transcript (Read/Edit tool_use blocks) and assert `reads`, `reads_before_edit`,
  `edits`, and `ratio` are computed correctly, including the bash-read heuristic.

### B6. Docs sync

- `README.md` — remove tray/menubar/autostart/vscode sections; reframe around the
  three surfaces; note `--inject` deprecation; remove the "% vs full repo" claim.
- `/Users/vishbay/SideQuests/*.html` — already partly updated this session; after the
  cut, drop tray/menubar mentions and the vanity metric there too.
- `.ai-context/` docs — `cram sync` will refresh ARCHITECTURE.md; run it at the end.

---

## Definition of done

- `python -m pytest -q` green, with new tests for A1, A2, A4, A6, B3, B5.
- `cram task "x"` runs, archives prior task, no "% of repo" line, uses context model.
- `get_context("x")` then `get_context()` returns x; `add_file` targets x's slot.
- `cram menu` / `cram autostart` / `cram vscode` no longer exist; `cram --help` clean.
- `cram ui` opens and every tab renders against an empty repo without crashing.
- `cram audit` prints the ratio with a modelled-cost caveat.
- Removed ~1,577 LOC of frontends; no dangling imports (`python -c "import cram.cli"`).
- Final: `cram sync` to refresh ARCHITECTURE.md, then commit.

## Suggested commit sequence
1. `fix: unify task slot storage so MCP reload/archive/add_file are coherent` (A1, A4)
2. `fix: route retrieval pipeline through call_context_model` (A2)
3. `fix: drop vanity full-repo savings metric; point to cram audit` (A3)
4. `fix: resolve basename ambiguity + honest concurrency semantics` (A5, A6)
5. `refactor: remove tray/menubar/autostart/vscode frontends` (B1, B2)
6. `harden: mcp/ui/audit robustness + tests` (B3, B4, B5)
7. `docs: reframe around MCP + cram ui + cram audit` (B6)
