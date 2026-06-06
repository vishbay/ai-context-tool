# Architecture

## Overview
ai-context-tool is a utility for discovering, initializing, and synchronizing context information for AI coding assistants. It scans codebases to extract relevant context, manages project configuration, and maintains Claude-specific settings for zero-key integration workflows.

## Directory Structure

### `ai_context/`
Core Python package containing main functionality:
- `cli.py` - Single entry point dispatching `aicontext <subcommand>` to appropriate modules
- `find_context.py` - Scans and extracts relevant context from codebases
- `init.py` - Initializes project configuration and CLAUDE.md files; triggers hook installation
- `sync_context.py` - Synchronizes context with external systems and backends
- `status.py` - Shows .ai-context/ file freshness and repo sync state
- `hooks.py` - Git post-commit hook installer for automated sync
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
- **Configuration Format**: JSON (Claude settings)
- **Package Management**: pip / setuptools
- **Testing**: pytest
- **Packaging**: pyproject.toml with setuptools.build_meta backend and setup.py shim

## Primary Features

- Context extraction from arbitrary codebases
- Project initialization with templated configuration
- Context synchronization across backends with automated git hooks
- Repository status monitoring (file freshness, sync state)
- Claude integration without API key management
- Extensible skill and template system

## Entry Points

CLI commands dispatched through unified `aicontext` entry point:
- `aicontext init [path]` - Bootstrap project configuration and install git hook
- `aicontext task "<description>"` - Populate CURRENT_TASK.md before coding session
- `aicontext sync [path]` - Update ARCHITECTURE.md after commit
- `aicontext status [path]` - Show .ai-context/ freshness and sync state
- `aicontext hook install|uninstall [path]` - Manage git post-commit hook

## Dependencies

All Python dependencies specified in `requirements.txt` and `pyproject.toml`. Install with `pip install -e .` or `pip install -r requirements.txt`.