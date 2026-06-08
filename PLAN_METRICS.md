# cram-ai: Honest Metrics Rework

> **Complete brief for a fresh build session (Sonnet).**
> Read top to bottom before touching code. Three fixes, one shared prerequisite.
> Do them in order — Fix 0 unblocks Fix 1 and 2.

---

## DO NOT DO (scope guardrails)

- **Do not keep the old model behind a flag or env switch.** Replace it. Two
  cost models is exactly the drift problem Fix 0 exists to kill.
- **Do not touch the MCP delivery path, the SessionStart/PostToolUse hooks, or
  `find_context.py`'s selection logic.** This is a metrics-only rework. Context
  generation and delivery are out of scope.
- **Do not change `cram init`, `cram sync`, `cram task`, or `targets.py`.**
- **Do not delete the cache-write teaching table in `benchmark.py`** — only
  correct scenario 1's baseline. It's the most credible artifact in the repo.
- **Do not invent token counts.** Keep the `len/4` heuristic everywhere and keep
  saying so in comments. Do not reach for a real tokenizer for the *modeled*
  numbers — only Fix 3 (measured) uses real counts, and those come from the
  transcript's own `usage` fields, not a tokenizer.
- **Do not widen the model table or the tray selector beyond Anthropic models.**
  The dollar metrics are calibrated to **Anthropic prompt-cache pricing**
  (1.25× write / 0.1× read / 5-min TTL / 2048–4096-tok cacheable floor). See the
  provider-scope note below — do not present these dollar figures as if they
  apply to GPT/Gemini consumers.
- **Do not add new dependencies.** Transcript parsing (Fix 3) is stdlib `json` +
  `pathlib` only.
- **Do not chase true A/B savings.** Once cram is installed there are no no-cram
  sessions to compare. Fix 3 ships as "real consumption," not "what cram saved."

### Provider-scope note (read before Fix 1/3)

cram's context **generation** is genuinely provider-agnostic — `utils.py` routes
through litellm (Anthropic, OpenAI, Gemini, Bedrock, Vertex, Azure, Ollama) plus
a `claude` CLI fallback. Context **consumption** works with any MCP- or
rules-capable agent. **But the savings *metrics* are Anthropic-specific:** the
write/read multipliers and cacheable floor are Anthropic's prompt-cache
mechanics, and Fix 3 reads **Claude Code** transcripts specifically. Keep the
modeled dollars scoped to Claude (the existing tray selector already is). Do not
generalize the dollar claims to other providers in this rework.

---

## 0. Why this plan exists

The tray's savings metrics are directionally right but quantitatively wrong by
1–2 orders of magnitude, and the headline framing oversells what cram actually
does. Live example from this repo (`repo_tokens=80,737`, `frozen_tok≈1,948`):

```
nocram_daily $4.85   cram_daily $0.04   daily_saving $4.81   → claimed 121× reduction
```

### The two modeling errors (in `cram/tray_server.py:227-229`)

```python
nocram_daily = _S * _T * repo_tokens * _WRITE   # ← errors here
cram_daily   = _S * (frozen_tok * _WRITE + (_T - 1) * frozen_tok * _READ)
```

1. **Volume.** `repo_tokens * _T * _S` asserts the agent cache-writes the
   *entire repo* 16×/day. Real agents do targeted retrieval — they read the
   3–6 files a task touches, not 100% of the repo. Inflated ~10–30×.
2. **Price class.** Files read via tool calls are **tool results** = input
   tokens at base (1.0×), incrementally cached and re-read at 0.1×. They are
   **not** cache writes at 1.25×. The no-cram path is billed at the most
   expensive rate for tokens that mostly wouldn't be writes.
3. **Mirror flaw on the cram side.** `cram_daily` counts *only* the frozen
   layer and pretends the agent reads zero source files with cram. But cram
   gives orientation, not the code — the agent still opens the files it edits.
   cram removes the *exploratory orientation* delta, not productive reads.

### The honest claim cram can make

> "cram replaces the cold-start orientation phase — the grep/read sweeps an
> agent does to figure out *where* to work."

This is real and worth showing. It is **not** 121×, and for a small repo like
cram-ai itself it is genuinely small (the whole repo fits in context). The win
scales with repo size. The metric must reflect that honestly.

### Three fixes

- **Fix 1** — re-baseline the no-cram model to an orientation estimate.
- **Fix 2** — reframe presentation: size-reduction is the headline; dollars are
  clearly-labeled, low-precision *orientation-overhead-avoided* estimates.
- **Fix 3** — add a *measured* panel from Claude Code transcripts (real tokens),
  so modeled numbers stop being the only story.

---

## Fix 0 (prerequisite): single cost model module

**Problem:** the cost model is duplicated in two places that will drift —
`tray_server.py:222-229` and `benchmark.py:151-178`. Extract one source of truth.

**New file: `cram/cost_model.py`**

```python
"""Single source of truth for cram's token-cost model.

Used by the tray /metrics endpoint and `cram benchmark` so the numbers never
diverge. Token counts are the len/4 heuristic — fine for relative comparison,
not billing.
"""
from __future__ import annotations
import os
from dataclasses import dataclass

# Base input price per 1M tokens (platform.claude.com).
MODEL_BASE = {
    'Opus 4.8':   5.00,
    'Sonnet 4.6': 3.00,
    'Haiku 4.5':  1.00,
}
WRITE_MULT = 1.25   # 5-min-TTL cache write
READ_MULT  = 0.10   # cache read

# Workload assumptions (overridable via env).
SESSIONS_PER_DAY  = int(os.environ.get('AICONTEXT_SESSIONS_PER_DAY',  '4'))
TASKS_PER_SESSION = int(os.environ.get('AICONTEXT_TASKS_PER_SESSION', '4'))

# Orientation model: without cram, the agent cold-starts each SESSION by reading
# ~N raw files to orient. This is the cost cram removes — NOT a full-repo
# rewrite, and billed at base input (tool-result reads), not cache write.
ORIENT_FILES = int(os.environ.get('AICONTEXT_ORIENT_FILES', '8'))


@dataclass
class CostInputs:
    repo_tokens: int
    repo_files:  int
    frozen_tok:  int


def orientation_tokens(repo_tokens: int, repo_files: int) -> int:
    """Tokens read to cold-start orient, per session, without cram."""
    if repo_files <= 0 or repo_tokens <= 0:
        return 0
    avg_file = repo_tokens / repo_files
    return int(min(repo_tokens, ORIENT_FILES * avg_file))


def daily_costs(inp: CostInputs, base_price: float) -> dict:
    """Return modeled daily costs for one model's base input price."""
    base  = base_price / 1_000_000
    write = base * WRITE_MULT
    read  = base * READ_MULT
    S, T  = SESSIONS_PER_DAY, TASKS_PER_SESSION

    orient = orientation_tokens(inp.repo_tokens, inp.repo_files)
    # Without cram: re-orient once per session at base input price.
    nocram = S * orient * base
    # With cram: frozen layer write-once/session + read (T-1)×; orientation gone.
    cram   = S * (inp.frozen_tok * write + (T - 1) * inp.frozen_tok * read)
    return {
        'orient_tokens': orient,
        'nocram_daily':  nocram,
        'cram_daily':    cram,
        'daily_saving':  max(0.0, nocram - cram),
    }
```

**Design notes for the implementer:**
- Orientation is **per session**, not per task — within a warm session the
  agent keeps context; it doesn't re-explore from scratch each task. (This alone
  divides the old number by `_T`.)
- Priced at **base input (1.0×)**, deliberately conservative: real cold starts
  include *some* cache writes at 1.25×, so we slightly *understate* the no-cram
  cost. Understating protects credibility.
- `ORIENT_FILES=8` is the one debatable assumption. Keep it env-configurable and
  surface it in the UI (Fix 2) so it's auditable, not hidden.
- Alternative model considered and rejected: `ORIENT_MULT * frozen_tok`. The
  file-count model is more defensible to a skeptic ("the agent reads ~8 files to
  orient") than a multiple of the summary. Use file-count.

**Acceptance:** `from cram.cost_model import daily_costs, CostInputs` works;
`pytest tests/` still green.

---

## Fix 1: re-baseline the no-cram model

### 1a. `cram/tray_server.py` — make `_estimate_repo_tokens` return a count

Current (`:98-109`) returns only tokens. Change to return `(tokens, files)`:

```python
def _estimate_repo_tokens(root: str) -> tuple[int, int]:
    total = files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_SCAN]
        for fname in filenames:
            if os.path.splitext(fname)[1] in _SCAN_EXTS:
                try:
                    with open(os.path.join(dirpath, fname), errors='ignore') as f:
                        total += len(f.read())
                    files += 1
                except OSError:
                    pass
    return total // 4, files
```

> ⚠️ Consider excluding lockfiles (`package-lock.json`, `yarn.lock`, `*.lock`,
> `poetry.lock`) from `_SCAN_EXTS`/scan — they inflate `repo_tokens` and thus
> savings. Add a `_SKIP_FILES` set. Apply the same exclusion in
> `benchmark.py:_count_repo_tokens` for consistency.

### 1b. `cram/tray_server.py` — rewrite the `/metrics` cost block

Replace lines `218-229` (`_BASE` … `daily_saving`) with:

```python
from cram.cost_model import CostInputs, daily_costs, MODEL_BASE, orientation_tokens

repo_tokens, repo_files = _estimate_repo_tokens(root())
savings_pct = max(0, int((1 - total_cram / max(repo_tokens, 1)) * 100))

inp   = CostInputs(repo_tokens=repo_tokens, repo_files=repo_files, frozen_tok=frozen_tok)
costs = daily_costs(inp, MODEL_BASE['Sonnet 4.6'])   # tray scales client-side per model
```

Then in the JSON response (`:248-260`) replace the cost fields with
`costs['nocram_daily']`, `costs['cram_daily']`, `costs['daily_saving']`, and add
`'orient_tokens': costs['orient_tokens']`, `'repo_files': repo_files`. Keep the
existing client-side per-model scaling in `popup.js` (it scales both cost fields
by `base/3.0`, still valid since orientation is also linear in base price).

### 1c. `cram/benchmark.py` — consume the shared model

Replace the inline math (`:151-178`) with calls into `cost_model.daily_costs`
per model so the CLI benchmark and tray agree. Keep the per-task cache-write
*table* (it's a legitimate, separate teaching view) but relabel scenario 1 from
"no cram (auto-index reads full repo)" to "no cram (cold-start orientation,
~N files)" and feed it `orientation_tokens(...)` instead of `repo_tokens`.

### Expected numbers after Fix 1 (this repo)

`avg_file ≈ 80,737/51 ≈ 1,583`; `orient = 8 × 1,583 ≈ 12,664`/session.
```
nocram_daily = 4 × 12,664 × 3e-6   ≈ $0.15/day
cram_daily   ≈ $0.036/day
daily_saving ≈ $0.11/day
```
Small for an 80k repo — **correct and honest**. Verify it scales: a 1M-token
repo with 200 files yields ~$1.50/day no-cram, a believable headline.

### Acceptance / tests
- New `tests/test_cost_model.py`: orientation caps at `repo_tokens`; zero files →
  zero; `daily_saving` never negative; nocram scales linearly with `ORIENT_FILES`.
- `curl /metrics` returns the new fields; `daily_saving` is in cents, not dollars,
  for this repo.

---

## Fix 2: reframe the presentation

Goal: **size reduction is the headline (a true claim); dollars are secondary,
low-precision, clearly labeled as orientation overhead avoided, with assumptions
visible.**

### 2a. `cram/tray_ui/popup.html` (metrics section, `:119-144`)

- Keep `context reduction` (the % size claim) as the **primary** big number.
- Relabel the dollar blocks so they don't read as total agent spend:
  - `without cram / day` → `orientation / day`
  - `with cram / day`    → `cram layer / day`
  - `saved / day`        → keep, but see precision rule below.
- Add a one-line caption under the heading making the size claim explicit:
  `frozen layer is {100 - savings_pct}% the size of the repo`.

### 2b. `cram/tray_ui/popup.js`

- **Precision:** stop showing 2-decimal dollars when the value implies false
  precision. Rule: `>= $1` → `~$X.XX`; `< $1` → `~$0.XX`; `< $0.01` → `<$0.01`.
  Always prefix `~` and never show 3 decimals. (Update `_applyModelPricing`.)
- **Surface assumptions** in `daily-est-line`: append the orientation assumption,
  e.g. `repo: ~81k tok · 4 sessions × 4 tasks/day · ~8 files to orient · Sonnet 4.6`.
  Pull `orient_tokens`/`repo_files` from the new `/metrics` fields.
- Keep the existing model-selector scaling; just route through the new labels.

### 2c. `README.md` (`:283-333`)

- Replace the "~$1.20/day, 120–200K orientation overhead" table framing with the
  orientation model and its stated assumptions (sessions/day, tasks/session,
  files-to-orient). State plainly: **savings scale with repo size; small repos
  see small savings.**
- Relabel the metrics table rows to match the new UI labels.
- Keep the cache-economics `<details>` block — it's the strongest, most credible
  content. Make sure its numbers use the shared model.

### Acceptance
- Tray headline leads with the size-reduction %; dollar figures carry `~` and ≤2
  decimals; the orientation assumption is visible in the popup without opening
  help. README no longer implies total-spend savings.

---

## Fix 3: measured usage from Claude Code transcripts

Modeled numbers will always be arguable. Add a **measured** view from real data.

### Source of truth
Claude Code writes per-session JSONL transcripts at
`~/.claude/projects/<dashed-project-path>/*.jsonl`. Assistant turns carry a
`message.usage` object with `input_tokens`, `output_tokens`,
`cache_creation_input_tokens` (writes), and `cache_read_input_tokens` (reads).
The dashed path for this repo is `-Users-vishbay-cram-ai` (replace `/` with `-`).

### 3a. New module `cram/usage.py`

```python
def measured_usage(repo_root: str, days: int = 7) -> dict | None:
    """Sum real token usage from Claude Code transcripts for this repo.

    Returns {writes, reads, input, output, sessions, est_cost} or None if no
    transcripts are found. est_cost uses Sonnet 4.6 base unless a model is read
    from the transcript.
    """
```
- Map `repo_root` → `~/.claude/projects/<dashed>/`. If absent, return `None`
  (tray simply hides the measured panel — no error).
- Parse the last `days` of `*.jsonl`, summing the four usage fields; count
  distinct session files as `sessions`.
- Compute `est_cost` from the shared `MODEL_BASE` with WRITE/READ mults; read the
  per-turn `message.model` when present, else default Sonnet 4.6.

### 3b. `tray_server.py` — `/measured` endpoint
Add `GET /measured` returning `measured_usage(root())` (or `{available: false}`).
Cache for ~60s (parsing JSONL on every poll is wasteful).

### 3c. `popup.html` / `popup.js` — measured panel
A small, collapsible "measured (last 7d)" block under the modeled metrics:
real writes vs reads and est. spend. Label it clearly as **actual**, distinct
from the **estimated** model above. Hide entirely when `/measured` is unavailable
(non-Claude-Code users).

### Scope honesty
True A/B (with-cram vs without) is impossible once cram is installed — there are
no no-cram sessions to compare. So Fix 3 ships as **"here is your real token
consumption"**, not "here is what cram saved you." That's the honest version and
still valuable: it shows the write/read split cram is designed to shift.

### Acceptance
- `tests/test_usage.py` with a fixture JSONL: sums match; missing dir → `None`;
  malformed lines skipped, not fatal.
- `/measured` returns real numbers on a machine with transcripts; panel hidden
  when absent.

---

## Sequencing & risks

1. **Fix 0** (cost_model.py) — unblocks 1 and 2. Land + tests first.
2. **Fix 1** (re-baseline) — depends on 0. Verify cents-scale output here.
3. **Fix 2** (reframe) — depends on 1's new fields.
4. **Fix 3** (measured) — independent; can land last or in parallel.

**Risks:**
- `benchmark.py` and `tray_server.py` *must* both move to `cost_model.py` in the
  same change, or the CLI and tray will print different numbers. Don't do one.
- Don't delete the cache-write teaching table in `benchmark.py` — it's the most
  credible artifact; just correct scenario 1's baseline.
- Transcript schema (Fix 3) can change across Claude Code versions — guard every
  field access with `.get(...)` and treat absence as "measured unavailable."

**Out of scope:** the Anthropic org-level usage/cost API (needs an admin key,
not per-repo) — transcripts are the right granularity for a per-repo tray.

---

## Definition of done
- One cost model, imported by both surfaces; `pytest tests/` green.
- Tray headline leads with size reduction; dollars are `~`, ≤2 decimals, labeled
  as orientation overhead, with assumptions visible.
- No-cram baseline is orientation-based; this repo shows cents/day, scaling
  sensibly with repo size.
- A measured panel shows real transcript usage when available, hidden otherwise.
- README reframed to match; cache-economics section preserved.
