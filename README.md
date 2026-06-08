# cram-ai

Stable context layer for AI coding tools — generated once by a cheap model, delivered cheaply on every session.

## Install

```bash
# pip (MCP support required for Claude Code)
pip install 'cram-ai[mcp]'

# Homebrew (macOS)
brew tap vishbay/cram-ai
brew install cram-ai
```

---

## What it does

cram-ai generates three files from your repo (via Haiku or equivalent cheap model):

```
.cram-ai-context/
├── ARCHITECTURE.md   — repo structure, tech stack, key files
├── DECISIONS.md      — architectural decisions the AI should respect
└── SYMBOLS.md        — every source file mapped to its public functions and classes
```

At session start you call `get_context("your task")` via the MCP server. cram picks the relevant files using the symbol index, extracts focused excerpts, and returns them as a tool result. The model gets exactly what it needs — no repo auto-indexing, no hunting.

---

## Why MCP, not CLAUDE.md

Anthropic's prompt cache has a 5-minute TTL. Any content in the conversation prefix gets **cache-written** on every new session and on every TTL expiry. Cache writes cost 1.25× the base input price. Injecting 10K tokens of context into CLAUDE.md means 10K tokens of cache writes fire every time you open a new session — even if the content hasn't changed.

MCP tool results land in the **conversation tail**, not the prefix. They don't expand what gets cache-written on session start. The prefix stays tiny (tool definitions only, ~1–2K tokens), written once, read cheaply thereafter.

Run `cram benchmark` to see the exact cost difference for your repo.

---

## Quick start

```bash
pip install 'cram-ai[mcp]'

cd your-repo
cram init                  # one-time: scans repo, generates context files, installs git hook
```

Add cram-ai to your `.claude/settings.json` (or see `CLAUDE.md` for the snippet after init):

```json
{
  "mcpServers": {
    "cram-ai": {
      "command": "cram",
      "args": ["mcp", "--repo", "/absolute/path/to/your-repo"]
    }
  }
}
```

Then at the start of each Claude Code session:

```
get_context("your task description")
```

That's it. The tool runs the full pipeline — symbol lookup, file selection, excerpt extraction — and returns the context as a tool result.

---

## CLI commands

| Command | When to run | What it does |
|---|---|---|
| `cram init` | Once per repo | Scans structure, generates `ARCHITECTURE.md` + `SYMBOLS.md` via Haiku |
| `cram mcp` | On session start | Starts the MCP server (stdio) — wire this into your editor settings |
| `cram sync` | After every commit | Updates `ARCHITECTURE.md` + `SYMBOLS.md` from git diff |
| `cram decide "..."` | When making arch choices | Appends a dated decision entry to `DECISIONS.md` |
| `cram task "..."` | Optional CLI path | Runs the context pipeline and writes `CURRENT_TASK.md` without MCP |
| `cram benchmark` | Anytime | Shows three-scenario cache-write cost model for your repo |

`cram task --inject "..."` writes task content into `CLAUDE.md` directly (backward compat for tools without MCP support).

---

## Provider support

The context generation (init, sync) is model-agnostic. Set `AICONTEXT_MODEL` to any provider:

```bash
# Claude CLI (default — works inside Claude Code with no API key)
cram init

# Anthropic SDK
export ANTHROPIC_API_KEY=sk-...
export AICONTEXT_MODEL=anthropic/claude-haiku-4-5-20251001
cram init

# OpenAI
export OPENAI_API_KEY=sk-...
export AICONTEXT_MODEL=openai/gpt-4o-mini
cram init

# Google Gemini
export GEMINI_API_KEY=...
export AICONTEXT_MODEL=gemini/gemini-2.0-flash
cram init

# Local (Ollama — free, no key needed)
export AICONTEXT_MODEL=ollama/mistral
cram init
```

Also supports: AWS Bedrock, GCP Vertex AI, Azure OpenAI, custom LiteLLM proxies.

---

## Tool support

| Tool | Context delivery |
|---|---|
| **Claude Code** | MCP server — `get_context()` tool result, prefix stays tiny |
| **Cursor** | Prefix injection — writes to `.cursor/rules/cram-task.md` |
| **Windsurf** | Prefix injection — writes to `.windsurf/rules/cram-task.md` |
| **Codex** | Prefix injection — writes to `.cram-ai-context/AGENTS.md` |
| **GitHub Copilot** | Prefix injection — writes to `.github/cram-task.md` |

Cursor, Windsurf, Codex, and Copilot have no MCP option — they use prefix injection via `cram task`. The cache-write cost savings only apply to the MCP (Claude Code) path.

---

## Benchmarks

Run `cram benchmark` in your repo for exact numbers. Three scenarios are modelled:

| Scenario | What gets cache-written per session |
|---|---|
| **No cram** — model auto-indexes repo | N × full repo tokens |
| **cram prefix-injected** — content in CLAUDE.md | N × frozen context tokens |
| **cram MCP-delivered** — content as tool result | 1 × frozen context tokens + (N−1) reads |

At Sonnet 4.6 pricing for a medium repo (~50K tokens, 4 tasks/session):

| Scenario | Cache writes | $/session | $/100 sessions |
|---|---|---|---|
| No cram | ~200,000 tok | ~$0.94 | ~$94 |
| Prefix-injected | ~40,000 tok | ~$0.19 | ~$19 |
| **MCP-delivered** | **~10,000 tok** | **~$0.05** | **~$5** |

The MCP path reduces cache-write cost ~20× vs no cram and ~4× vs prefix injection. Savings scale with repo size and session frequency. Run `cram benchmark` against your actual repo to get numbers grounded in your file sizes.

**Note:** the frozen prefix must exceed the model's cache minimum (2,048 tokens for Sonnet 4.6, 4,096 for Opus and Haiku) to cache at all. If `cram benchmark` flags this, run `cram sync` to rebuild the context files with more detail.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `AICONTEXT_MODEL` | auto-detected | Model for context tasks — bare alias or `provider/model` |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (optional inside Claude Code) |
| `AICONTEXT_MAX_FILES` | `5` | Max files inlined per task |
| `AICONTEXT_MAX_LINES` | `300` | Max lines per ARCHITECTURE.md |
| `AICONTEXT_MAX_EXCERPT_LINES` | `80` | Max lines excerpted per file |
| `CRAM_TASK_GRACE_SECONDS` | `600` | Seconds after `cram task` before a commit resets context |

---

## Upgrading from v0.1.0

v0.2.0 changes the Claude Code delivery path from CLAUDE.md prefix injection to MCP tool results. This is the main behavioral change:

| | v0.1.0 | v0.2.0 |
|---|---|---|
| Claude Code delivery | `cram task` writes context into `CLAUDE.md` | `get_context()` MCP tool, CLAUDE.md is a config pointer |
| `cram task` | Writes to CLAUDE.md | Writes `CURRENT_TASK.md` only, prints MCP reminder |
| `cram task --inject` | n/a | Restores old CLAUDE.md injection behavior |
| Other tools (Cursor, Windsurf, etc.) | Unchanged | Unchanged |

If you had `cram task` wired into a pre-session script:
- **For Claude Code:** remove it. Use the MCP `get_context()` tool instead.
- **For other tools:** keep it as-is, or add `--inject` if you want CLAUDE.md injection preserved.

---

## Running tests

```bash
pip install pytest
pytest
```

99 passing tests, no API key required. All model calls are mocked.

---

## License

MIT
