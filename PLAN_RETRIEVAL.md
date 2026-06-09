# Plan: retrieval improvements

Three targeted changes to `find_context.py` and `mcp_server.py`.

---

## Fix 1 — Deterministic pre-filter before LLM (worth acting on)

**Problem:** `find_relevant_files()` passes the full SYMBOLS.md, ARCHITECTURE.md, DECISIONS.md,
and GOTCHAS.md to the LLM in a single selection prompt and asks it to name relevant files.
This works, but:
- The LLM can hallucinate filenames not in SYMBOLS.md
- Results vary across runs for the same task
- The prompt is larger than it needs to be (DECISIONS + GOTCHAS don't help select files)

**Change:** Add a deterministic scoring step that runs *before* the LLM call and narrows the
candidate list. The LLM then reranks/selects from a short, grounded list.

**New function** in `find_context.py`:

```python
def _score_files(task: str, symbols_text: str) -> list[tuple[str, float]]:
    """Score files from SYMBOLS.md against task keywords. Returns (path, score) sorted desc."""
    # 1. Extract task keywords: lowercase, split on non-alphanumeric, drop stop words
    # 2. Parse SYMBOLS.md: each line is "file.py: sym1, sym2, ..."
    # 3. Score:
    #    +2.0 per keyword matching the filename stem or path component
    #    +1.0 per keyword matching a symbol name
    # 4. Return all files with score > 0, sorted descending
```

**Modified `find_relevant_files()`:**

```python
def find_relevant_files(task, arch, decisions, symbols, gotchas):
    # 1. Run _score_files(task, symbols) to get scored candidates
    # 2. If any candidates score > 0:
    #    - Build a compact "Candidate files (scored by symbol match):" section
    #      listing only the top min(15, all_scoring) files
    #    - Drop DECISIONS + GOTCHAS from the selection prompt (they don't help pick files)
    # 3. If no candidates score > 0: fall back to current behavior (all symbols to LLM)
    # 4. LLM still does final selection — it can pick from the scored list + ARCHITECTURE context
```

The selection prompt shrinks to: ARCHITECTURE + (scored candidates or full SYMBOLS) + task.
DECISIONS and GOTCHAS are no longer in the selection prompt (they're still delivered via the
frozen context layer — CURRENT_TASK.md does not include them, the agent calls get_decisions()
and get_gotchas() separately via MCP).

**Impact:** Fewer hallucinated filenames, cheaper selection call, stable results for common tasks.

**Files:** `cram/find_context.py`

**Tests:** `tests/test_find_context.py` — test `_score_files()` directly:
- keyword in filename → scores higher than keyword in symbol only
- no keywords → returns empty list
- `find_relevant_files()` smoke test with patched LLM: verify prompt no longer contains DECISIONS

---

## Fix 2 — Surface SYMBOLS.md scoring in CLI output (worth acting on)

**Problem:** Stage 1 in `find_context()` prints "Symbol index ready — N identifiers" but doesn't
tell the user which files the symbol pre-filter found. The user only sees LLM output in Stage 2.

**Change:** After `_score_files()` runs, print the top candidates with their scores:

```
[1/4] Symbol pre-filter → 3 candidates
  → cram/find_context.py  (score 4.0 — keyword 'find_context' in filename + symbols)
  → cram/mcp_server.py    (score 2.0 — keyword 'context' in symbols)
  → cram/utils.py         (score 1.0 — keyword 'find' in symbols)
[2/4] LLM reranking via haiku ...
```

Also: in `get_context()` MCP tool, when `task` is provided, include the pre-filter score table
as a comment block at the top of the returned context so the agent can see why those files
were chosen.

**Files:** `cram/find_context.py`, `cram/mcp_server.py`

**Tests:** CLI output assertions in `tests/test_find_context.py`

---

## Fix 3 — Decouple selection prompt from DECISIONS/GOTCHAS (lower priority)

*This is a subset of Fix 1 and falls out naturally from that implementation. Tracked here
for clarity.*

**Problem:** The selection prompt currently includes DECISIONS.md and GOTCHAS.md:

```python
prompt = (
    f"Repo architecture:\n{arch}\n\n"
    f"{symbols_section}"
    f"Decisions:\n{decisions}\n\n"   # ← not needed to pick files
    f"{gotchas_section}"              # ← not needed to pick files
    f'Task: "{task}"\n\n'
    ...
)
```

These don't help determine which files are relevant. They belong in the context *output*, not
in the *selection* step.

**Change:** Drop `decisions` and `gotchas` parameters from the LLM selection prompt in
`find_relevant_files()`. The selection prompt becomes: ARCHITECTURE + symbol candidates + task.

DECISIONS/GOTCHAS continue to be available via:
- `get_decisions()` and `get_gotchas()` MCP tools (already present)
- `cram task --target all` file-based delivery (writes them to the tool's auto-loaded file)

No change to what the agent ultimately receives — only the intermediate LLM call is leaner.

**Note:** Do NOT remove DECISIONS/GOTCHAS from the cram context delivery altogether. Their value
is that they arrive proactively, before the agent makes a wrong decision. Making them purely
on-demand (the #10 suggestion in its original form) undermines this. The right split is:
selection step = lean; delivery = complete.

**Files:** `cram/find_context.py`

**Tests:** Verify `find_relevant_files()` prompt does not include DECISIONS content when called
with decisions content (patch `call_model` and inspect the captured prompt).

---

## Order of implementation

1. Fix 1 (`_score_files` + compact candidate prompt) — contains Fix 3 as a side effect
2. Fix 2 (surface scores in CLI + MCP output) — built on top of Fix 1
3. Fix 3 is already done by Fix 1

Estimated scope: ~100 lines changed in `find_context.py`, ~20 lines in `mcp_server.py`,
~40 lines of new tests.
