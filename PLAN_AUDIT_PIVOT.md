# PLAN — Pivot to cram audit (agent token-waste observability)

Status: **executed through P2; shipped as v0.4.0** (June 2026). The headline metric
is now the measured **pre-edit context share** ("orientation tax" survives only as
finding language); the audit runs on a parity-gated SQLite event store with per-file
drilldown, a findings engine, and `--report`. First real reading: 13.4% share across
183 sessions, 84% no-edit sessions excluded.
Companion docs: `orientation-tax-idea-assessment.html`, `cram-ai-external-review-editorial.html`,
`cram-ai-design-retrospective-v2.html` (SideQuests)

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

### P0 — The attribution experiment ~~(validates everything else)~~
**Demoted (2026-06-11) to optional internal evidence.** The product claim became
"cram diagnoses where agent-session spend goes, with evidence" — which needs
measurement credibility, not P0. P0 remains the right protocol for the narrower
claim that context loading reduces pre-edit share; tooling stays ready
(`cram audit --compare`, control checkout, auto-logged task log), and a faster
paired-probe variant is documented in the runbook. Passive collection continues.

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

### P2 — Audit-first `cram ui` — **done** (v0.4.0)
- ~~New **Audit** tab as the default landing tab~~ done — pre-edit context share,
  no-edit split, cache engagement, bloat metrics, top repeated files, weekly trend;
  Sessions tab reads through the event-store cache.
- Beyond the original scope, also shipped: SQLite event store with parity gate,
  measured pre-edit share + segmentation, per-file drilldown, deterministic findings
  engine, `cram audit --report` (markdown), Apache-2.0 + test CI, v0.4.0 on PyPI.

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
