# cram-ai: Context Health (staleness score + token budgets)

> **Complete brief for a fresh build session (Sonnet).**
> Read top to bottom before touching code. Two fixes that ship together, plus
> one optional MCP surface. All three are additive — no behavior is removed.
>
> Origin: a side-by-side review of cram-ai against an externally-validated
> "AI Context Strategy" (302K-session ClickHouse data). Most of that strategy
> cram already implements (symbol reads via SYMBOLS.md + `get_symbols()`,
> per-task reset, commit-triggered sync, frozen/volatile split, ignore list).
> Two things cram genuinely lacks: a **graduated staleness score** (cram's is
> binary) and **per-file token budgets** (cram enforces none). This plan adds
> exactly those, in cram's grain.

---

## DO NOT DO (scope guardrails)

- **Do not auto-update DECISIONS.md or GOTCHAS.md from the git diff.** cram
  deliberately keeps these human-curated; `sync()` only refreshes ARCHITECTURE
  + the symbol index. Auto-generating *rationale* invites hallucinated "why".
  Health *reads* these files' sizes — it must never *rewrite* them.
- **Do not remove or shrink SYMBOLS.md / `get_symbols()`.** It is cram's
  implementation of "prefer symbol reads over file reads." It is a feature.
- **Do not add prescriptive model-routing rules** (e.g. "never bootstrap on
  Sonnet"). cram already has `pick_context_model`/`pick_coding_model` + a tray
  selector and is intentionally less dogmatic. Out of scope.
- **Do not add DB_SCHEMA.md or API.md.** Domain-specific, not universal. cram's
  file set is ARCHITECTURE / DECISIONS / GOTCHAS / SYMBOLS / CURRENT_TASK.
- **Do not blindly copy the work-doc's token numbers** (ARCHITECTURE 400 tok,
  etc.). Those target a much tighter context than cram produces — cram's
  ARCHITECTURE is line-budgeted at 300 lines (`AICONTEXT_MAX_LINES`), which is
  several× 400 tokens. Use the cram-calibrated budgets in Fix 2 and make them
  env-overridable. Budgets are **soft warnings**, never hard truncation in v1.
- **Do not invent precision in the score.** Keep the staleness score derived
  from observable git facts (commits since the context last changed), not a
  weighted black box. Auditable beats clever — same ethos as the metrics rework.
- **Do not add new dependencies.** stdlib + existing `subprocess`/`git` only.
- **Do not commit new state files.** Any persisted marker must be gitignored
  (like `session.json`). Prefer the git-native approach in Fix 1 that needs
  *no* new state at all.

---

## 0. Current state (ground truth — verified)

**Staleness today** (`cram/status.py:get_status_dict`, `:76-82`):
```python
if fname == 'ARCHITECTURE.md' and last_commit and last_commit > mtime:
    stale = True
...
'state': 'stale' if stale else 'fresh',
```
Binary. Watches only `ARCHITECTURE.md` mtime vs the latest commit timestamp.
The tray badge consumes `data.state` in `popup.js:fetchStatus` (`~:288-295`):
`'stale'` → `"<age> stale"`, else `"fresh"`.

**Token counts today** (`cram/tray_server.py` `/metrics`, the `files` dict):
```python
files[fname] = {'tokens': tokens, 'lines': content.count('\n')}
```
Per-file tokens are already computed for ARCHITECTURE/SYMBOLS/DECISIONS/GOTCHAS/
CURRENT_TASK. **Nothing is compared against a limit.**

**Persistence:** `session.json` (gitignored, `cram/session.py`) holds per-task
state and is *cleared* on session end — not a durable sync marker. `.gitignore`
in the context dir currently lists `CURRENT_TASK.md` and `session.json`.

**MCP tools** (`cram/mcp_server.py`): `get_context`, `get_architecture`,
`get_symbols`, `get_decisions`, `get_gotchas`, `add_file`, `run_benchmark`.

---

## Fix 1: graduated staleness score (0–10)

Replace the binary `stale/fresh` with a 0–10 score and four bands, matching the
externally-validated scale:

| Score | Band         | Meaning                    |
|-------|--------------|----------------------------|
| 0–2   | `fresh`      | up to date                 |
| 3–5   | `acceptable` | drifting, fine to work     |
| 6–7   | `stale`      | update before next session |
| 8–10  | `critical`   | sync now                   |

### 1a. Score input — git-native, no new state file

"Commits since the context last changed" is the primary input. ARCHITECTURE.md
is committed, so derive it from git directly (works after a teammate pull; no
local marker to drift):

**New helper in `cram/status.py`:**
```python
def _commits_since_context_update(root: str) -> int | None:
    """Commits on HEAD since ARCHITECTURE.md was last committed. None if unknown."""
    rel = os.path.join(CONTEXT_DIR, 'ARCHITECTURE.md')
    try:
        sha = subprocess.check_output(
            ['git', 'log', '-1', '--format=%H', '--', rel],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        if not sha:
            return None
        count = subprocess.check_output(
            ['git', 'rev-list', '--count', f'{sha}..HEAD'],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return int(count)
    except (subprocess.CalledProcessError, ValueError):
        return None
```

> All git calls must pass `cwd=root` and swallow errors → degrade to the legacy
> mtime check when git is unavailable or the repo has no commits yet.

### 1b. Score function (auditable, env-tunable threshold)

```python
# Commits-since-update that maps to "critical". Override via env.
STALE_CRITICAL_COMMITS = int(os.environ.get('CRAM_STALE_CRITICAL_COMMITS', '10'))

def staleness_score(commits_since: int | None, arch_behind_commit: bool) -> int:
    """0–10. Primary signal: commits since the context last changed.

    Falls back to the legacy mtime signal (arch_behind_commit) when the commit
    count is unknown: behind → 6 (stale), else 0 (fresh).
    """
    if commits_since is None:
        return 6 if arch_behind_commit else 0
    scaled = round(commits_since / STALE_CRITICAL_COMMITS * 10)
    return max(0, min(10, scaled))

def staleness_band(score: int) -> str:
    if score <= 2: return 'fresh'
    if score <= 5: return 'acceptable'
    if score <= 7: return 'stale'
    return 'critical'
```

### 1c. Wire into `get_status_dict`

Keep the existing `arch_behind_commit` computation (rename the local `stale`
bool), compute the score, and add fields. **Keep `state` backward-compatible**:
map band → the old two-value contract so nothing downstream breaks, *and* add
the richer fields:

```python
commits_since = _commits_since_context_update(root)
score = staleness_score(commits_since, arch_behind_commit)
band  = staleness_band(score)
return {
    'state':            'stale' if band in ('stale', 'critical') else 'fresh',
    'staleness_score':  score,
    'staleness_band':   band,
    'commits_since_sync': commits_since,
    'files':            files,
    'last_commit_age':  _age_label(last_commit) if last_commit else None,
}
```

### 1d. CLI surface (`show_status`)

In `show_status`, print the band + score and commits-since count, e.g.:
```
Context health : stale (6/10) — 6 commits since last sync. Run `cram sync`.
```
Keep the existing per-file age table.

### 1e. Tray badge (`popup.js:fetchStatus`)

Map `staleness_band` → badge text + a CSS class for color. Prefer `band` when
present; fall back to the old `state` logic if absent (older server):
```js
const band = data.staleness_band;
if (band) {
  const score = data.staleness_score;
  setBadge(band === 'fresh' ? 'fresh' : `${band} ${score}/10`);
  // add a class hook for color: app/badge className per band
} else { /* existing stale/fresh logic */ }
```
Add band color classes in `popup.css` (fresh=green, acceptable=neutral,
stale=amber, critical=red). Reuse existing badge color tokens; don't invent a
palette.

### Acceptance / tests (`tests/test_status.py`, new)
- `staleness_score(0, …)=0`, `(5,…)=5`, `(10,…)=10`, `(99,…)` caps at 10.
- `commits_since=None` + behind → 6; + not behind → 0.
- `staleness_band` boundaries: 2→fresh, 3→acceptable, 5→acceptable, 6→stale,
  7→stale, 8→critical.
- `get_status_dict` on a temp git repo (init, commit ARCHITECTURE, add N empty
  commits) returns `commits_since_sync == N` and the right band. Use a real
  `tmp_path` git repo (the suite already shells out to git in `test_sync.py` —
  follow that pattern).
- Back-compat: `state` is still `'stale'`/`'fresh'` and matches band mapping.

---

## Fix 2: per-file token budgets (soft warnings)

cram computes per-file tokens but enforces nothing. Add **cram-calibrated** soft
budgets, surfaced in `/metrics`, the tray, and `cram status`. Warn only — never
truncate in v1.

### 2a. Budgets module — put them where the tokens live

Add to `cram/cost_model.py` (already the single source of truth for token
constants), env-overridable, **calibrated to cram's actual output** (not the
work-doc's tighter targets):

```python
# Soft per-file token budgets for the frozen context layer. Warnings only.
# Calibrated to cram's output (ARCHITECTURE is line-budgeted ~300 lines), NOT
# the 400-tok external target. SYMBOLS scales with repo size → no flat cap.
FILE_BUDGETS = {
    'ARCHITECTURE.md': int(os.environ.get('CRAM_BUDGET_ARCHITECTURE', '1500')),
    'DECISIONS.md':    int(os.environ.get('CRAM_BUDGET_DECISIONS',    '600')),
    'GOTCHAS.md':      int(os.environ.get('CRAM_BUDGET_GOTCHAS',      '400')),
    'CURRENT_TASK.md': int(os.environ.get('CRAM_BUDGET_TASK',         '800')),
}

def budget_status(fname: str, tokens: int) -> str:
    """'ok' | 'near' (≥80%) | 'over' (>100%) | 'none' (no budget)."""
    limit = FILE_BUDGETS.get(fname)
    if not limit:
        return 'none'
    if tokens > limit:        return 'over'
    if tokens >= 0.8 * limit: return 'near'
    return 'ok'
```

> SYMBOLS.md is intentionally absent — it grows with the repo and is not a
> hand-written summary. Do not cap it.

### 2b. `/metrics` — attach budget to each file

In `tray_server.py` where `files[fname]` is built, add the limit + status:
```python
from cram.cost_model import FILE_BUDGETS, budget_status
files[fname] = {
    'tokens': tokens,
    'lines':  content.count('\n'),
    'budget': FILE_BUDGETS.get(fname),          # may be None
    'budget_status': budget_status(fname, tokens),
}
```

### 2c. Tray — show over/near-budget files

In `popup.js:fetchMetrics`, if any file is `over` or `near`, surface a compact
line in the metrics block (reuse a `metric-sub` element), e.g.:
```
⚠ GOTCHAS.md 470/400 tok over budget · trim before next sync
```
Only render when something is `near`/`over`; stay silent when all `ok`.

### 2d. `cram sync` + `cram status` — warn in the CLI

- In `sync_context.py:sync`, after writing ARCHITECTURE.md and the symbol index,
  read the frozen files' token counts and print a one-line warning per `over`
  file. Non-fatal. (Reuse `cost_model.budget_status`; count tokens with the
  existing `len(content)//4` heuristic — keep it consistent with everywhere.)
- In `status.py:show_status`, append `(over budget: N tok)` to the relevant
  file rows.

### Acceptance / tests (`tests/test_cost_model.py`, extend)
- `budget_status('GOTCHAS.md', 401)=='over'` when budget 400; `360=='near'`;
  `100=='ok'`.
- Unknown file → `'none'`; SYMBOLS.md → `'none'`.
- Env override changes the threshold (`monkeypatch.setenv` then reimport/patch
  the module constant, mirroring `test_nocram_scales_linearly_with_orient_files`).
- `/metrics` integration: a file written over its budget reports
  `budget_status == 'over'` in the JSON.

---

## Fix 3 (optional): `get_health()` MCP tool

Make staleness **agent-visible**, not just tray-visible — the work-doc's
strongest idea (their committed HEALTH.md). cram's grain says expose it as an
MCP tool, **not** a committed file (avoids repo churn; `CURRENT_TASK.md` is
already gitignored for the same reason).

### 3a. New tool in `cram/mcp_server.py`
```python
@mcp.tool()
def get_health() -> str:
    """Report context staleness + per-file token budgets so the agent knows
    whether to trust the loaded context or recommend `cram sync` first."""
```
- Call `get_status_dict(root)` for `staleness_score`/`band`/`commits_since_sync`.
- Call the same per-file token + `budget_status` logic used by `/metrics`
  (factor that into a small shared helper if it would otherwise be copy-paste —
  e.g. `cram/health.py:context_health(root) -> dict`, consumed by both the tray
  `/metrics` route and this tool, so they never diverge — same anti-drift
  principle as `cost_model.py`).
- Return a short, deterministic markdown block (bullets, no prose), e.g.:
  ```
  # Context health
  - staleness: stale (6/10) — 6 commits since last sync
  - ARCHITECTURE.md  1,180 tok (budget 1,500) ok
  - GOTCHAS.md         470 tok (budget 400) OVER — trim before next sync
  - recommendation: run `cram sync` before relying on this context
  ```
- Deterministic output (no timestamps in the body) so it caches cleanly, mirror
  the determinism tests in `test_mcp_server.py`.

### 3b. Optional: fold a one-line health header into `get_context()`
Low-risk add: prepend a single `staleness: <band> (<score>/10)` line to
`get_context()` output **only when band is `stale`/`critical`**, so the agent is
warned exactly when it matters without bloating the happy path. Keep it one line;
do not embed token tables in `get_context`.

### Acceptance / tests (`tests/test_mcp_server.py`, extend)
- `get_health()` is deterministic across repeat calls (no wall-clock in body).
- Reflects an over-budget file and a non-zero commit count on a temp repo.
- `get_context()` header line appears only for stale/critical, absent for fresh.

---

## Suggested shared helper (prevents drift)

If Fix 3 is in scope, create `cram/health.py`:
```python
def context_health(root: str) -> dict:
    """Single source for staleness + per-file budget status.
    Used by tray /metrics and the get_health() MCP tool."""
```
…and have both surfaces call it. If Fix 3 is deferred, skip this — don't
pre-abstract for a single caller.

---

## Sequencing & risks

1. **Fix 1** (staleness score) — self-contained in `status.py` + `popup.js`.
   Land first; it's the highest-signal change and unblocks the badge color work.
2. **Fix 2** (token budgets) — touches `cost_model.py`, `/metrics`, tray, CLI.
   Independent of Fix 1; can land in parallel.
3. **Fix 3** (get_health) — depends on 1 and 2's outputs. Optional; land last.
   If included, route 1+2's data through `cram/health.py` so tray and MCP agree.

**Risks**
- Git calls must `cwd=root` and never raise into the request path — always
  degrade to the legacy mtime check. A repo with zero/one commit must not crash
  `get_status_dict`.
- `state` must stay `'stale'`/`'fresh'` for back-compat; only *add* fields.
- Budgets are opinions — keep every threshold env-overridable and labeled, and
  ship them as warnings. No truncation in v1 (that's a separate, riskier change).
- Token counts use the `len/4` heuristic everywhere; do not introduce a real
  tokenizer just for budgets — consistency over precision.

---

## Definition of done

- `get_status_dict` returns `staleness_score` (0–10), `staleness_band`, and
  `commits_since_sync`; `state` remains back-compatible. Tray badge shows the
  band + score with band-appropriate color; `cram status` prints it.
- `/metrics` reports a per-file `budget`/`budget_status`; the tray surfaces
  over/near-budget files; `cram sync` and `cram status` warn on over-budget
  frozen files. Nothing is truncated.
- (If included) `get_health()` MCP tool returns a deterministic health block and
  `get_context()` warns inline only when stale/critical.
- `pytest tests/` green, including new `tests/test_status.py` and extended
  `test_cost_model.py` (+ `test_mcp_server.py` if Fix 3 lands).
- No new dependencies; no new committed state files; DECISIONS.md / GOTCHAS.md
  remain human-curated (never auto-rewritten).
```
