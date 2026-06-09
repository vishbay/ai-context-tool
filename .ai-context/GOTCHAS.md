# Gotchas

## Context directory resolution has two names
`context_path()` in `context_dir.py` checks `.ai-context/` first, then falls back to `.cram-ai-context/`. If you create a file in the wrong directory it will silently be ignored. Always call `context_path(root, filename)` — never construct the path manually.

## `call_context_model()` lives in `cram.utils`, not the calling module
When patching in tests, use `'cram.utils.call_context_model'` — not `'cram.decisions.call_context_model'` or similar. The function is imported locally inside the function body so it never becomes an attribute of the calling module.

## The MCP server's `_repo_root` is set at startup, not per-call
`_repo_root` is a module-level global set when `main()` parses `--repo`. If you test MCP tools directly (not via the CLI), you must call `mcp_server._repo_root = "/your/path"` before any tool call, or every tool returns `'Error: repo root not configured.'`

## `cram sync` is rate-limited by a grace period
The post-commit hook checks a `.last-sync` timestamp and skips sync if it ran recently (default: 5 minutes). In tests that call `cram sync` back-to-back, the second call will no-op. Force a sync by deleting `.ai-context/.last-sync` or passing `--force`.

## Staleness score falls back silently to mtime
`get_health()` returns a commit-count staleness score, but falls back to mtime if git is unavailable or the repo has no commits. The response dict has a `method` field (`"git"` or `"mtime"`) — don't assume git when writing tests or parsing the output.

## `propose_decision` appends, never deduplicates
Calling `propose_decision` twice with the same text creates two `[PENDING]` entries. There is no dedup check. The agent is expected to call it once per session; the human reviewer removes duplicates via `cram ui` or direct file edit.

## SYMBOLS.md is rebuilt on every `cram sync` — edits are overwritten
SYMBOLS.md is fully regenerated from source on each sync. Manual edits to it will be lost on the next commit. Only edit ARCHITECTURE.md, DECISIONS.md, and GOTCHAS.md by hand.

## litellm swallows provider errors as generic exceptions
When the model backend is misconfigured, litellm raises a generic `Exception` rather than a typed error. Log the full exception message — the provider's error detail is in the string, not a structured field.

## `cram audit` only reads Claude Code transcript files
`cram audit` scans `~/.claude/projects/*/` for `.jsonl` transcript files. It does not read Cursor, Windsurf, or Copilot sessions. Session counts will appear low on multi-tool setups.

## The tray app requires macOS — import guard needed
`cram/tray.py` uses `rumps`, which only works on macOS. Never import it unconditionally. The CLI guards this with `if sys.platform != 'darwin': sys.exit(...)` — follow the same pattern in any new tray code.
