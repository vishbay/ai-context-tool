"""cram-ai MCP server — exposes repo context as tools for Claude Code and other agents.

Start with: cram mcp [--repo /path/to/repo]

Configure in .claude/settings.json:
  {
    "mcpServers": {
      "cram-ai": {
        "command": "cram",
        "args": ["mcp", "--repo", "/absolute/path/to/your/repo"]
      }
    }
  }
"""

from __future__ import annotations
import os
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "mcp package required. Install with: pip install 'cram-ai[mcp]'",
        file=sys.stderr,
    )
    sys.exit(1)

CONTEXT_DIR = '.cram-ai-context'

# Resolved at startup — see main()
_repo_root: str = ''


def _ctx_path(filename: str) -> str:
    return os.path.join(_repo_root, CONTEXT_DIR, filename)


def _read(filename: str) -> str:
    p = _ctx_path(filename)
    if not os.path.exists(p):
        return ''
    with open(p, errors='ignore') as f:
        return f.read()


mcp = FastMCP(
    'cram-ai',
    instructions=(
        "IMPORTANT: Call get_context() as your FIRST action in every session, before "
        "answering any question or writing any code. Pass the task description as the "
        "argument (e.g. get_context('fix the rate limiter')), or call with no arguments "
        "to reload the last task's context. Skipping this means you have no focused "
        "context and will miss key files."
    ),
)


@mcp.tool()
def get_context(task: str = '') -> str:
    """Load focused file excerpts for a coding task.

    Call this as your FIRST action in every session before writing any code.

    With a task argument: runs the full pipeline — reads the symbol index, asks
    the context model to identify relevant files, extracts identifier-focused
    excerpts, and returns everything assembled as a markdown document.

    With no argument: returns the last context loaded by `cram task`, skipping
    the LLM pipeline. Use this at session start when the developer already ran
    `cram task "..."` from the CLI before opening the editor.

    Args:
        task: What you're about to work on, e.g. "add OAuth login to the API".
              Omit to reload the existing context from the last `cram task` run.
    """
    if not _repo_root:
        return 'Error: repo root not configured.'

    if not os.path.isdir(os.path.join(_repo_root, CONTEXT_DIR)):
        return f'Error: {CONTEXT_DIR}/ not found in {_repo_root}. Run `cram init` first.'

    if not task:
        content = _read('CURRENT_TASK.md')
        if not content:
            return (
                'No context loaded yet. Call get_context("your task description") '
                'to generate context for a specific task, or run `cram task "..."` '
                'from the terminal first.'
            )
        return content

    # Run find_context in the repo directory
    orig_dir = os.getcwd()
    try:
        os.chdir(_repo_root)
        from cram.find_context import find_relevant_files, populate_current_task
        from cram.utils import get_model_recommendations

        arch      = _read('ARCHITECTURE.md')
        decisions = _read('DECISIONS.md')
        gotchas   = _read('GOTCHAS.md')
        symbols   = _read('SYMBOLS.md')

        ctx_model, coding_model = get_model_recommendations()
        file_entries = find_relevant_files(task, arch, decisions, symbols, gotchas)

        if not file_entries:
            return (
                f"# Task: {task}\n\n"
                "No relevant files identified. "
                "Check that ARCHITECTURE.md and SYMBOLS.md describe the repo structure.\n\n"
                f"## Architecture\n{arch}"
            )

        populate_current_task(task, file_entries, ctx_model, coding_model)

        with open(_ctx_path('CURRENT_TASK.md')) as f:
            return f.read()

    finally:
        os.chdir(orig_dir)


@mcp.tool()
def get_architecture() -> str:
    """Get this repo's ARCHITECTURE.md — structure, tech stack, and key files.

    Use this for general orientation questions about the codebase before diving
    into a specific task.
    """
    content = _read('ARCHITECTURE.md')
    if not content:
        return 'ARCHITECTURE.md not found. Run `cram init` to generate it.'
    return content


@mcp.tool()
def get_symbols(query: str = '') -> str:
    """Get the repo's public symbol index — files mapped to their top-level functions and classes.

    Use this to find which file defines a specific function or class without
    reading every source file.

    Args:
        query: Optional filter — returns only lines containing this string (case-insensitive).
               Leave empty to get the full index.
    """
    content = _read('SYMBOLS.md')
    if not content:
        return 'SYMBOLS.md not found. Run `cram init` or `cram sync` to generate it.'

    if not query:
        return content

    q = query.lower()
    matching = sorted(line for line in content.splitlines() if q in line.lower())
    if not matching:
        return f'No symbols matching "{query}" found.\n\nFull index:\n{content}'
    return f'Symbols matching "{query}":\n\n' + '\n'.join(matching)


@mcp.tool()
def get_decisions() -> str:
    """Get architectural decisions recorded for this repo.

    These are choices the team has committed to — use them to ensure your
    implementation aligns with existing conventions and constraints.
    """
    content = _read('DECISIONS.md')
    if not content:
        return 'DECISIONS.md not found. Run `cram init` to create it.'
    return content


@mcp.tool()
def get_gotchas() -> str:
    """Get known non-obvious traps and foot-guns in this repo.

    These are things that aren't visible from the code alone: silent side
    effects, endpoints that bypass middleware, columns with surprising nullability,
    patterns that look correct but break in production. Read before touching
    unfamiliar areas.
    """
    content = _read('GOTCHAS.md')
    if not content:
        return 'GOTCHAS.md not found. Run `cram init` to create it, then add entries as you find them.'
    return content


@mcp.tool()
def add_file(path: str, identifiers: str = '') -> str:
    """Add a file's excerpts to the current session context.

    Use this when you discover mid-task that a file not in the initial context
    is needed. The file is appended to CURRENT_TASK.md with excerpts focused on
    the current task's keywords, or on the identifiers you specify.

    Args:
        path: Relative path to the file, e.g. "auth/middleware.py"
        identifiers: Optional comma-separated function/class names to focus on,
                     e.g. "handle_request, check_token". Leave empty to use the
                     current task's keywords automatically.
    """
    if not _repo_root:
        return 'Error: repo root not configured.'

    orig_dir = os.getcwd()
    try:
        os.chdir(_repo_root)
        import io
        from contextlib import redirect_stdout
        from cram.add_context import add_files

        spec = f'{path} | {identifiers}' if identifiers.strip() else path
        buf  = io.StringIO()
        with redirect_stdout(buf):
            ok = add_files([spec], replace=False)

        output = buf.getvalue()
        if ok:
            with open(_ctx_path('CURRENT_TASK.md')) as f:
                content = f.read()
            return output.rstrip() + '\n\n' + content
        return output or f'Could not add {path} — check the file exists and a session is active.'
    finally:
        os.chdir(orig_dir)


@mcp.tool()
def run_benchmark() -> str:
    """Show token savings for this repo — full repo vs cram context, with cost breakdown.

    Returns a summary of how many tokens cram-ai saves per session and the
    estimated cost reduction at Sonnet and Opus rates.
    """
    if not _repo_root:
        return 'Error: repo root not configured.'
    import io
    from contextlib import redirect_stdout
    from cram.benchmark import run_benchmark as _bench

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            _bench(_repo_root)
        return buf.getvalue()
    except SystemExit:
        return buf.getvalue() or 'Benchmark failed — run `cram init` first.'


def main() -> None:
    global _repo_root

    import argparse
    from cram.utils import find_git_root

    parser = argparse.ArgumentParser(
        prog='cram mcp',
        description='Start the cram-ai MCP server on stdio',
    )
    parser.add_argument(
        '--repo', default=None,
        help='Path to the git repo (defaults to cwd)',
    )
    args = parser.parse_args()

    start = os.path.abspath(args.repo) if args.repo else os.getcwd()
    _repo_root = find_git_root(start)

    # Validate the repo has been initialised
    if not os.path.isdir(os.path.join(_repo_root, CONTEXT_DIR)):
        print(
            f"Warning: {CONTEXT_DIR}/ not found in {_repo_root}. "
            "Run `cram init` before using the MCP server.",
            file=sys.stderr,
        )

    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
