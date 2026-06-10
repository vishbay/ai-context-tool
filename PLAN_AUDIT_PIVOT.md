# PLAN — Pivot to cram audit (agent token-waste observability)

Status: **in progress** (June 2026)
Companion docs: `orientation-tax-idea-assessment.html`, `cram-ai-external-review-*.html` (SideQuests)

## The goal we are attacking

> Teams and individuals using AI coding agents cannot see **where their token spend
> goes as behavior**. Billing data says "spend doubled"; nobody can say *why* —
> longer sessions? caching silently not engaging? agents reading 40 files before
> every edit? cram becomes the tool that answers that question from data that
> already exists (local transcripts, gateway usage logs).

This inverts the product: **measurement is the headline, the context layer is one
remediation among several.** The pivot is mostly deletion and re-framing, not a rewrite.

## Why this and not more context delivery

- Context delivery races the host (agentic search, memory, AGENTS.md) and a falling
  price curve. Observability races nobody — no harness vendor profits from making
  waste visible.
- An audit needs zero workflow change, zero discipline, zero agent cooperation.
  It produces a number that creates its own demand for remediation.
- The orientation tax is real but bounded (~10–30% of session cost, shrinking).
  The audit must therefore report the full waste ledger, not one bucket.

## The five waste buckets the audit must report

| # | Bucket | Signal source |
|---|--------|---------------|
| 1 | Orientation (reads before first edit, read-to-edit ratio) | transcripts — **already built** |
| 2 | Context bloat (cache-read growth vs session length) | transcript `usage` blocks |
| 3 | Retry/clarification loops (re-edits of same file, user corrections) | transcript tool-call sequences |
| 4 | Uncapped tool output (single tool results > N KB) | transcript tool_result sizes |
| 5 | Cache misconfiguration (cache_creation high + cache_read ~0 across requests) | usage blocks — **the silent killer; likely the biggest single finding on gateways** |

## Phases

### P0 — The attribution experiment (validates everything else)
Two weeks of real work. Alternate tasks with/without `get_context()`, session
discipline held constant. `cram audit` before/after per cohort. This is the number
the pivot stands on. **Do this before building more.**

### P1 — Deepen the audit (buckets 2–5)
- ~~Extend `cram/audit.py`: context-per-request, read-cost tail share, carried cost of
  oversized tool results, redundant re-reads (bucket 2 + 4), cache-engagement ratio
  (bucket 5)~~ **done** — surfaced in CLI report, `--json`, and the TUI Audit tab.
- ~~Add `--json` output so other surfaces consume data, not text~~ **done**.
- ~~Retry-loop detection (bucket 3): failed tool calls (`is_error` results) +
  same-file edit churn~~ **done** — CLI report, `--json`, TUI.
- ~~Per-provider cost model table (Anthropic / OpenAI / Gemini / local) in
  `cost_model.py`~~ **done** — `CRAM_PROVIDER` selects, field-level env overrides,
  audit dollar attribution wired through it. **P1 complete.**

### P2 — Audit-first `cram ui`
- New **Audit** tab as the default landing tab: headline metrics (reads-before-first-edit,
  read-to-edit ratio with band, cache writes/session, cache-engagement check),
  per-session table, ratio trend.
- Sessions tab stays (drill-down); Decisions/Health/Actions remain but move after Audit.
- This is what developers and platform teams expect to see first: *the number*, not the knobs.

### P3 — Team/gateway story (after P0–P2 validate)
- Ingest adapter for gateway usage exports (CSV/JSON) alongside local transcripts.
- Aggregate per-developer/per-repo rollups. Deploy target: an internal marketplace
  app (Streamlit/Vue) backed by the same `--json` audit core.
- Only build this with a real platform-team design partner. No partner → stop here.

## What gets demoted (not deleted)
- `cram task` / file-based delivery targets: kept as remediation, removed from headline docs.
- Context pipeline polish: frozen — no new selection/excerpt features.
- DECISIONS/GOTCHAS + `propose_decision` approval queue: kept; future direction is
  writing approved entries into AGENTS.md/CLAUDE.md rather than a proprietary folder.

## Success metrics (each can embarrass us)
- P0: measurable delta in reads-before-first-edit attributable to context loading
  alone — or an honest finding that there isn't one.
- P1: audit run on ≥3 distinct repos surfaces at least one non-orientation finding
  (bucket 2–5) per repo.
- P2: `cram ui` opens to the audit tab and answers "where did the spend go" in <10s
  with no configuration.
- P3: one platform team uses a rollup to change something (policy, config, caching fix).

## Kill criteria
- P0 shows no attributable orientation savings **and** buckets 2–5 show nothing
  actionable on real repos → the observability thesis is also wrong; write the
  retrospective and move on.
- No design partner materializes for P3 within a quarter of P2 shipping → stay a
  personal/local tool, stop investing in team features.
