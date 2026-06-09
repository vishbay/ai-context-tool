# Architecture

## Overview
cram-ai is a utility for discovering, initializing, and synchronizing context information for AI coding assistants. It scans codebases to extract relevant context, manages project configuration, and maintains Claude-specific settings for zero-key integration workflows.

## Directory Structure

### `cram/`
Core Python package containing main functionality:
- `cli.py` - Single entry point dispatching `cram <subcommand>` to appropriate modules
- `context_dir.py` - Context directory resolution (`.ai-context/` preferred, `.cram-ai-context/` legacy fallback)
- `find_context.py` - Scans and extracts relevant context from codebases; populates CURRENT_TASK.md
- `init.py` - Initializes project configuration and CLAUDE.md files; triggers hook installation
- `sync_context.py` - Synchronizes context with external systems and backends
- `status.py` - Shows .ai-context/ file freshness and repo sync state
- `hooks.py` - Git post-commit and commit-msg hook installer for automated sync and decision recording
- `mcp_server.py` - MCP server for Claude Code integration with task slot namespacing, usage logging, and decision proposals
- `targets.py` - Target-specific output generation with byte-cap command protection rules
- `symbols.py` - Public identifier extraction for SYMBOLS.md
- `audit.py` - Measures orientation tax (reads vs. edits) from Claude Code transcripts
- `decisions.py` - Mine architectural decisions from git history; show DECISIONS.md
- `decide.py` - Decision recording and management; append to DECISIONS.md
- `gotcha.py` - Non-obvious trap documentation; append to GOTCHAS.md
- `ui.py` - Textual TUI dashboard for decisions, session efficiency, and context health
- `utils.py` - Shared utility functions for context operations
- `__init__.py` - Package initialization

### `.claude/`
Claude-specific configuration and settings:
- `settings.local.json` - Local settings for Claude integration and behavior

### `templates/`
Template files for project initialization:
- `skills/` - Reusable skill templates for Claude extensibility

### `tests/`
Test suite for the package functionality

## Key Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python package metadata and build configuration |
| `setup.py` | setuptools shim for pip compatibility |
| `requirements.txt` | Python dependencies |
| `PROJECT_CONTEXT.md` | Project goals and context documentation |
| `.gitignore` | Git exclusion rules |

## Tech Stack

- **Language**: Python 3.10+
- **Configuration Format**: JSON (Claude settings), TOML (cram config)
- **Package Management**: pip / setuptools
- **Testing**: pytest
- **Packaging**: pyproject.toml with setuptools.build_meta backend and setup.py shim
- **TUI**: Textual (optional, cram[tui])

## Primary Features

- Context extraction from arbitrary codebases with identifier-focused excerpts
- Project initialization with templated configuration and ARCHITECTURE.md generation
- Context synchronization across backends with automated git hooks
- **Output protection by default**: Command outputs byte-capped to prevent token waste
- Repository status monitoring (file freshness, sync state, token budgets)
- Claude integration without API key management via MCP server
- Task slot namespacing for concurrent agent invocations
- Extensible skill and template system
- **Architectural decision tracking**: Record and mine decisions from git history; auto-suggest via commit-msg hook
- **Gotcha documentation**: Maintain repository-specific non-obvious traps and workarounds
- **Orientation tax audit**: Measure reads-vs-edits efficiency from transcripts
- **TUI dashboard**: Visualize decisions, session metrics, and context health
- Usage logging (task, tokens, timestamp) in JSONL format
- Suggested decisions (from agents) logged to suggestions.jsonl
- Custom targets via config.toml with marker-based upsert support

## Entry Points

CLI commands dispatched through unified `cram` entry point:
- `cram init [path]` - Bootstrap project configuration (.ai-context/) and install git hooks
- `cram task "<description>"` - Populate CURRENT_TASK.md before coding session with relevant file excerpts
- `cram sync [path]` - Update ARCHITECTURE.md and SYMBOLS.md after a commit
- `cram status [path]` - Show .ai-context/ freshness and output protection status
- `cram decide "<statement>"` - Append architectural decision to DECISIONS.md (auto-suggested by commit-msg hook)
- `cram decisions [--mine] [--days N]` - Show or mine decisions from git history
- `cram gotcha "<trap>"` - Append non-obvious trap to GOTCHAS.md
- `cram audit [--days N] [--all]` - Measure orientation tax from Claude Code transcripts
- `cram benchmark` - Token/cost comparison across delivery strategies
- `cram doctor [path]` - Check setup: models, hooks, git, context files
- `cram hook install|uninstall [path]` - Manage git post-commit and commit-msg hooks
- `cram mcp [--repo PATH]` - Start MCP server (stdio) for Claude Code / agents
- `cram ui [path]` - Launch TUI dashboard (requires cram-ai[tui])
- `cram menu [path]` - Launch tray app (requires cram-ai[tray])

## Context Directory

`.ai-context/` (canonical) is created at repo root by `cram init`. Older repos using `.cram-ai-context/` continue to work via fallback resolution in `context_dir.py`.

| File | Purpose | Managed by |
|------|---------|-----------|
| `ARCHITECTURE.md` | Repo structure, tech stack, key files | `cram sync` |
| `SYMBOLS.md` | Public identifiers per source file | `cram init` / `cram sync` |
| `DECISIONS.md` | Architectural invariants and decisions | Manual + `cram decide` / `cram decisions --mine` |
| `GOTCHAS.md` | Non-obvious traps and workarounds | Manual + `cram gotcha` |
| `CURRENT_TASK.md` | Active task context (per-session) | `cram task` |
| `config.toml` | Output protection, task defaults, custom targets | Manual |
| `tasks/` | Per-task slot files for concurrent agents | MCP server |
| `usage.jsonl` | Usage log (task, tokens, timestamp) | MCP server |
| `suggestions.jsonl` | Proposed decisions from agents | MCP server (propose_decision) |
| `.gitignore` | Excludes CURRENT_TASK.md (per-developer) | `cram init` |

## Dependencies

All Python dependencies specified in `requirements.txt` and `pyproject.toml`. Install with `pip install -e .` or `pip install cram-ai`.

Optional extras:
- `cram[tui]` - Textual dashboard (depends on textual>=0.80)
- `cram[tray]` - macOS menu bar app (depends on pystray, pillow, pywebview, flask)
- `cram[mcp]` - MCP server support (depends on mcp>=1.0.0)