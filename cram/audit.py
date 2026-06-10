"""cram audit — measure orientation tax from Claude Code session transcripts."""

from __future__ import annotations
import json
import os
import glob
import datetime
import collections


READ_TOOLS  = frozenset({'Read', 'read_file'})
WRITE_TOOLS = frozenset({'Write', 'Edit', 'edit_file', 'write_file', 'NotebookEdit'})
BASH_READ_CMDS = ('cat ', 'head ', 'grep ', 'find ', 'ls ', 'tail ')

CONTEXT_DIR = '.ai-context'

# Cost-model assumptions (overridable via env vars)
# Rough average tokens per file excerpt read during orientation.
# Override with: CRAM_AUDIT_TOK_PER_FILE=2500
AUDIT_TOK_PER_FILE: int = int(os.environ.get('CRAM_AUDIT_TOK_PER_FILE', '2500'))
# Sonnet base input price per token (USD).
# Override with: CRAM_AUDIT_BASE_PRICE=0.000003
AUDIT_BASE_PRICE: float = float(os.environ.get('CRAM_AUDIT_BASE_PRICE', str(3.0 / 1_000_000)))


def _find_all_tool_use(obj: object, depth: int = 0) -> list[dict]:
    if depth > 8:
        return []
    if isinstance(obj, dict):
        if obj.get('type') == 'tool_use':
            return [obj]
        results: list[dict] = []
        for v in obj.values():
            results.extend(_find_all_tool_use(v, depth + 1))
        return results
    if isinstance(obj, list):
        results = []
        for item in obj:
            results.extend(_find_all_tool_use(item, depth + 1))
        return results
    return []


def _find_usage(obj: object, depth: int = 0) -> list[dict]:
    if depth > 8:
        return []
    if isinstance(obj, dict):
        if 'cache_creation_input_tokens' in obj:
            return [obj]
        results: list[dict] = []
        for v in obj.values():
            results.extend(_find_usage(v, depth + 1))
        return results
    if isinstance(obj, list):
        results: list[dict] = []
        for item in obj:
            results.extend(_find_usage(item, depth + 1))
        return results
    return []


def _analyze_transcript(path: str) -> dict | None:
    reads = 0
    reads_before_edit = 0
    edits = 0
    first_edit_seen = False
    cache_writes = 0
    cache_reads = 0

    try:
        with open(path, errors='ignore') as f:
            for line in f:
                try:
                    msg = json.loads(line)
                except Exception:
                    continue

                for block in _find_all_tool_use(msg):
                    name = block.get('name', '')
                    inp  = block.get('input') or {}
                    cmd  = inp.get('command', '') if isinstance(inp, dict) else ''

                    is_read = (
                        name in READ_TOOLS or
                        (name == 'Bash' and any(c in cmd for c in BASH_READ_CMDS))
                    )
                    is_write = name in WRITE_TOOLS

                    if is_read:
                        reads += 1
                        if not first_edit_seen:
                            reads_before_edit += 1
                    if is_write:
                        edits += 1
                        if not first_edit_seen:
                            first_edit_seen = True

                for u in _find_usage(msg):
                    cache_writes += u.get('cache_creation_input_tokens', 0)
                    cache_reads  += u.get('cache_read_input_tokens', 0)

    except Exception:
        return None

    ratio = reads_before_edit / max(edits, 1)
    return {
        'reads':             reads,
        'reads_before_edit': reads_before_edit,
        'edits':             edits,
        'ratio':             ratio,
        'cache_writes':      cache_writes,
        'cache_reads':       cache_reads,
        'mtime':             os.path.getmtime(path),
    }


def _project_transcript_dir(repo_root: str) -> str | None:
    """Return the ~/.claude/projects/ subdirectory for this repo, or None."""
    dashed = repo_root.replace(os.sep, '-').lstrip('-')
    candidate = os.path.join(os.path.expanduser('~'), '.claude', 'projects', '-' + dashed)
    if os.path.isdir(candidate):
        return candidate
    # Also try without leading slash conversion quirk on Windows-style paths
    candidate2 = os.path.join(os.path.expanduser('~'), '.claude', 'projects', dashed)
    if os.path.isdir(candidate2):
        return candidate2
    return None


def run_audit(repo_root: str, days: int = 30, all_projects: bool = False) -> None:
    """Print an orientation-tax audit for the repo (or all projects)."""

    if all_projects:
        projects_root = os.path.join(os.path.expanduser('~'), '.claude', 'projects')
        dirs = sorted(glob.glob(projects_root + '/*/'))
    else:
        td = _project_transcript_dir(repo_root)
        if not td:
            print("No Claude Code transcripts found for this repo.")
            print("  (Expected: ~/.claude/projects/" +
                  repo_root.replace(os.sep, '-').lstrip('-') + "/)")
            return
        dirs = [td + '/']

    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)

    all_sessions = []
    project_summaries = []

    for proj_dir in dirs:
        name = os.path.basename(proj_dir.rstrip('/'))
        # Skip test/tmp dirs
        if 'pytest' in name or 'private-tmp' in name or 'private-var' in name:
            continue

        files = glob.glob(proj_dir + '*.jsonl')
        sessions = []
        for f in files:
            mtime = os.path.getmtime(f)
            if datetime.datetime.fromtimestamp(mtime) < cutoff:
                continue
            r = _analyze_transcript(f)
            if r:
                sessions.append(r)
                all_sessions.append(r)

        if not sessions:
            continue

        avg_reads = sum(s['reads'] for s in sessions) / len(sessions)
        avg_rbe   = sum(s['reads_before_edit'] for s in sessions) / len(sessions)
        avg_cw    = sum(s['cache_writes'] for s in sessions) / len(sessions)
        project_summaries.append((name, len(sessions), avg_reads, avg_rbe, avg_cw))

    if not all_sessions:
        print(f"No sessions found in the last {days} days.")
        return

    # ── Summary ──────────────────────────────────────────────────
    total     = len(all_sessions)
    avg_reads = sum(s['reads'] for s in all_sessions) / total
    avg_rbe   = sum(s['reads_before_edit'] for s in all_sessions) / total
    avg_edits = sum(s['edits'] for s in all_sessions) / total
    avg_ratio = sum(s['ratio'] for s in all_sessions) / total
    avg_cw    = sum(s['cache_writes'] for s in all_sessions) / total

    # Orientation cost estimate: reads_before_edit × avg file size × Sonnet price
    # Assumptions: AUDIT_TOK_PER_FILE tokens per file read, AUDIT_BASE_PRICE per token.
    orient_tok_per_session = avg_rbe * AUDIT_TOK_PER_FILE
    orient_cost_per_session = orient_tok_per_session * AUDIT_BASE_PRICE
    sessions_per_month = total / (days / 30)
    monthly_orient_cost = orient_cost_per_session * sessions_per_month * 30

    # Read-to-edit ratio benchmark
    if avg_ratio < 2.0:
        ratio_label = '✓ good'
    elif avg_ratio < 5.0:
        ratio_label = '~ normal'
    else:
        ratio_label = '⚠ high — context may not be landing'

    print(f"\nOrientation tax audit — last {days} days\n")
    print(f"  Sessions analysed:              {total}")
    print(f"  Avg reads/session:              {avg_reads:.1f}")
    print(f"  Avg reads before first edit:    {avg_rbe:.1f}  ← primary metric")
    print(f"  Avg edits/session:              {avg_edits:.1f}")
    print(f"  Avg read-to-edit ratio:         {avg_ratio:.1f}×  {ratio_label}")
    print(f"  Avg cache writes/session:       {avg_cw:,.0f} tokens")
    print()
    print(f"  Est. orientation tokens/session: ~{orient_tok_per_session:,.0f}")
    print(f"  Est. orientation cost/session:   ~${orient_cost_per_session:.4f}  (Sonnet, base input)")
    print(f"  Est. monthly orientation tax:    ~${monthly_orient_cost:.2f}  ({sessions_per_month:.0f} sessions/month)")
    print(f"  Note: cost is modelled from reads_before_edit ({AUDIT_TOK_PER_FILE:,} tok/file assumed); "
          f"the ratio is the measured signal.")
    print()
    print(f"  Ratio guide: < 2× good · 2–5× normal · > 5× context isn't landing")

    if all_projects and len(project_summaries) > 1:
        print(f"\n  Per-project breakdown:")
        print(f"  {'Project':<45} {'Sessions':>8} {'Reads/s':>8} {'RBE':>6} {'CW/s':>12}")
        print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*6} {'-'*12}")
        for name, n, reads, rbe, cw in sorted(project_summaries, key=lambda x: -x[3]):
            short = name[-43:] if len(name) > 43 else name
            print(f"  {short:<45} {n:>8} {reads:>8.1f} {rbe:>6.1f} {cw:>12,.0f}")

    print()
    print("  To reduce orientation tax: cram task \"your task\" before each session")
    print("  Then compare: run this command again next week.")


def main() -> None:
    import argparse
    from cram.utils import find_git_root

    parser = argparse.ArgumentParser(
        prog='cram audit',
        description='Measure orientation tax from Claude Code session transcripts',
    )
    parser.add_argument('--days', type=int, default=30,
                        help='Look back N days (default: 30)')
    parser.add_argument('--all', action='store_true', dest='all_projects',
                        help='Show all projects, not just this repo')
    parser.add_argument('--path', default=None, metavar='REPO_PATH')
    args = parser.parse_args()

    start = os.path.abspath(args.path) if args.path else os.getcwd()
    try:
        root = find_git_root(start)
    except Exception:
        root = start

    run_audit(root, days=args.days, all_projects=args.all_projects)


if __name__ == '__main__':
    main()
