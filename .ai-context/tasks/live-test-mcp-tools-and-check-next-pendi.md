# Current Task

## Task
live-test MCP tools and check next pending tasks

## Scope
- cram/
- tests/

## Out of Scope
<!-- Add directories/files the agent should NOT touch -->

## Definition of Done
<!-- Add explicit acceptance criteria before closing this task -->

## Models
- Context loaded by: `Claude Haiku (claude CLI)`
- **Switch to `Claude Opus (claude CLI)` for coding** ←

## Relevant Files

### cram/mcp_server.py
```py
[lines 21–121 of 448]
import sys
import threading
import time

from cram.context_dir import CONTEXT_DIR, context_path, has_context_dir

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "mcp package required. Install with: pip install 'cram-ai[mcp]'",
        file=sys.stderr,
    )
    sys.exit(1)

# Resolved at startup — see main()
_repo_root: str = ''
# Serializes os.chdir() calls across concurrent tool invocations
_chdir_lock = threading.Lock()


def _task_slug(task: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', task.lower())[:40].strip('-')
    return slug or 'unnamed'


def _cleanup_stale_slots(tasks_dir: str, max_age: int = 86400) -> None:
    try:
        cutoff = time.time() - max_age
        for fname in os.listdir(tasks_dir):
            fpath = os.path.join(tasks_dir, fname)
  ··· 21 lines omitted ···
def _ctx_path(filename: str) -> str:
    return context_path(_repo_root, filename, warn=True)


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

    if not has_context_dir(_repo_root):
        return f'Error: {CONTEXT_DIR}/ not found in {_repo_root}. Run `cram init` first.'

    if not task:
  ··· 327 more lines

```

### tests/test_mcp_server.py
```py
[lines 13–92 of 414]
def repo(tmp_path):
    """Minimal initialised repo for MCP tool tests."""
    ctx = tmp_path / CONTEXT_DIR
    ctx.mkdir()
    (ctx / 'ARCHITECTURE.md').write_text('# Arch\n\nKey files: main.py\n')
    (ctx / 'DECISIONS.md').write_text('# Decisions\n\n## [D-001] Use Python\n')
    (ctx / 'SYMBOLS.md').write_text('main.py: main, helper\nutils.py: parse, format\n')
    (tmp_path / 'main.py').write_text('def main(): pass\ndef helper(): pass\n')
    return tmp_path


# ---------------------------------------------------------------------------
# get_architecture determinism
# ---------------------------------------------------------------------------

class TestGetArchitectureDeterminism:
    def test_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_architecture()
        r2 = srv.get_architecture()
        assert r1 == r2

    def test_returns_file_content(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_architecture()
        assert '# Arch' in result


# ---------------------------------------------------------------------------
# get_decisions determinism
# ---------------------------------------------------------------------------

class TestGetDecisionsDeterminism:
    def test_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_decisions()
        r2 = srv.get_decisions()
        assert r1 == r2


# ---------------------------------------------------------------------------
# get_symbols determinism
# ---------------------------------------------------------------------------

class TestGetSymbolsDeterminism:
    def test_full_index_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_symbols()
        r2 = srv.get_symbols()
        assert r1 == r2

    def test_filtered_results_sorted(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        result = srv.get_symbols('py')
        lines = result.split('\n')[2:]  # skip header line
        non_empty = [l for l in lines if l.strip()]
        assert non_empty == sorted(non_empty)

    def test_filtered_identical_on_repeat(self, repo, monkeypatch):
        import cram.mcp_server as srv
        monkeypatch.setattr(srv, '_repo_root', str(repo))

        r1 = srv.get_symbols('main')
        r2 = srv.get_symbols('main')
        assert r1 == r2


# ---------------------------------------------------------------------------
# get_context determinism
# ---------------------------------------------------------------------------
  ··· 322 more lines

```
