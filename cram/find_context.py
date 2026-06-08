"""Pre-session file discovery: identifies relevant excerpts and populates CURRENT_TASK.md."""

from __future__ import annotations
import os
import re
import sys

from cram.utils import (
    call_model,
    call_context_model,
    cache_min_tokens,
    get_model_recommendations,
    find_git_root as _find_git_root,
)
from cram import targets as _targets

MAX_FILES         = int(os.environ.get('AICONTEXT_MAX_FILES',        '5'))
MAX_EXCERPT_LINES = int(os.environ.get('AICONTEXT_MAX_EXCERPT_LINES', '80'))
MAX_LINES         = MAX_EXCERPT_LINES  # alias kept for test compatibility

CONTEXT_DIR = '.cram-ai-context'


# ── file helpers ──────────────────────────────────────────────────


def _read_context_file(filename: str) -> str:
    path = os.path.join(CONTEXT_DIR, filename)
    if not os.path.exists(path):
        return ''
    with open(path) as f:
        return f.read()


def _read_truncated(path: str) -> str:
    """Read a file, truncating to MAX_LINES lines if needed."""
    with open(path, errors='ignore') as f:
        lines = f.readlines()
    if len(lines) > MAX_LINES:
        omitted = len(lines) - MAX_LINES
        return ''.join(lines[:MAX_LINES]) + f'\n... [{omitted} lines omitted]\n'
    return ''.join(lines)


def _resolve_path(raw: str, root: str = '.') -> str:
    if os.path.exists(raw):
        return raw
    _skip = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'dist', 'build'}
    basename = os.path.basename(raw)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _skip and not d.startswith('.')]
        if basename in filenames:
            return os.path.relpath(os.path.join(dirpath, basename), root)
    return raw


def _clean_path(line: str) -> str:
    line = line.strip()
    line = re.sub(r'^[-*\d.]+\s*', '', line)
    line = line.strip('`').strip()
    if ' ' in line:
        return ''
    if '/' not in line and '.' not in line:
        return ''
    return line


# ── excerpt extraction ────────────────────────────────────────────


def _extract_excerpt(fpath: str, identifiers: list[str]) -> str:
    """Return an identifier-focused excerpt of a file, or the full file if small."""
    with open(fpath, errors='ignore') as f:
        lines = f.readlines()

    total = len(lines)
    if total <= MAX_EXCERPT_LINES:
        return ''.join(lines)

    if not identifiers:
        omitted = total - MAX_EXCERPT_LINES
        return ''.join(lines[:MAX_EXCERPT_LINES]) + f'\n... [{omitted} lines omitted]\n'

    kw_lower = [k.lower() for k in identifiers]
    window   = 15

    matched: set[int] = set()
    for i, line in enumerate(lines):
        ll = line.lower()
        if any(kw in ll for kw in kw_lower):
            for j in range(max(0, i - window), min(total, i + window + 1)):
                matched.add(j)

    if not matched:
        omitted = total - MAX_EXCERPT_LINES
        return ''.join(lines[:MAX_EXCERPT_LINES]) + f'\n... [{omitted} lines omitted]\n'

    sorted_idx = sorted(matched)[:MAX_EXCERPT_LINES]

    parts: list[str] = [f'[lines {sorted_idx[0]+1}–{sorted_idx[-1]+1} of {total}]\n']
    prev = -2
    for i in sorted_idx:
        if i > prev + 1:
            if prev >= 0:
                parts.append(f'  ··· {i - prev - 1} lines omitted ···\n')
        parts.append(lines[i])
        prev = i
    if sorted_idx[-1] < total - 1:
        parts.append(f'  ··· {total - sorted_idx[-1] - 1} more lines\n')

    return ''.join(parts)


# ── file selection ────────────────────────────────────────────────


def _parse_file_line(raw: str) -> tuple[str, list[str]]:
    """Parse 'path/to/file.py | id1, id2' into (path, [id1, id2])."""
    if '|' in raw:
        path_part, id_part = raw.split('|', 1)
        path = _clean_path(path_part)
        ids  = [i.strip() for i in id_part.split(',') if i.strip()]
    else:
        path = _clean_path(raw)
        ids  = []
    return path, ids


def find_relevant_files(
    task: str, arch: str, decisions: str, symbols: str = '',
) -> list[tuple[str, list[str]]]:
    """Ask the context model to identify relevant files + their key identifiers.

    Returns a list of (resolved_path, [identifier, ...]) tuples.
    """
    symbols_section = (
        f"Symbol index (file → public identifiers):\n{symbols}\n\n"
        if symbols else ''
    )
    prompt = (
        f"Repo architecture:\n{arch}\n\n"
        f"{symbols_section}"
        f"Decisions:\n{decisions}\n\n"
        f'Task: "{task}"\n\n'
        f"List ONLY the files DIRECTLY needed to complete this task.\n"
        f"For each file, include the specific identifiers (functions/classes) most relevant to the task.\n"
        f"Rules:\n"
        f"- UI/styling tasks → CSS and HTML files only\n"
        f"- Backend/API tasks → Python/Go/etc files only\n"
        f"- 1–3 files is almost always enough\n"
        f"- Max {MAX_FILES} files\n\n"
        f"Output format — one file per line:\n"
        f"  relative/path/to/file.ext | RelevantFunc, AnotherClass\n"
        f"If no specific identifiers match, output path only. No explanation."
    )
    raw_lines = call_model(prompt).strip().splitlines()

    results: list[tuple[str, list[str]]] = []
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        path, ids = _parse_file_line(raw)
        if not path:
            continue
        resolved = _resolve_path(path)
        results.append((resolved, ids))
        if len(results) >= MAX_FILES:
            break
    return results


# ── context assembly ──────────────────────────────────────────────


def _arch_summary(arch: str, max_lines: int = 25) -> str:
    """Extract the first max_lines non-blank lines of ARCHITECTURE.md."""
    collected = []
    for line in arch.splitlines():
        if line.strip():
            collected.append(line)
        if len(collected) >= max_lines:
            break
    return '\n'.join(collected)


def populate_current_task(
    task: str,
    file_entries,  # list[str] or list[tuple[str, list[str]]]
    ctx_model: str = '',
    coding_model: str = '',
) -> list[str]:
    """Write CURRENT_TASK.md with identifier-focused excerpts. Returns files inlined."""
    # Normalize: accept both plain string paths and (path, identifiers) tuples
    normalized = [
        (e, []) if isinstance(e, str) else e
        for e in file_entries
    ]
    found   = [(f, ids) for f, ids in normalized if os.path.exists(f)]
    missing = [f for f, _ in normalized if not os.path.exists(f)]

    with open(os.path.join(CONTEXT_DIR, 'CURRENT_TASK.md'), 'w') as out:
        out.write(f"# Current Task\n\n## Task\n{task}\n\n")

        if ctx_model or coding_model:
            out.write("## Models\n")
            if ctx_model:
                out.write(f"- Context loaded by: `{ctx_model}`\n")
            if coding_model:
                out.write(f"- **Switch to `{coding_model}` for coding** ←\n")
            out.write('\n')

        if missing:
            out.write("## Notes\n")
            for m in missing:
                out.write(f"- `{m}` suggested but not found on disk\n")
            out.write('\n')

        out.write("## Relevant Files\n")
        for fpath, ids in found:
            ext     = os.path.splitext(fpath)[1].lstrip('.')
            excerpt = _extract_excerpt(fpath, ids)
            out.write(f"\n### {fpath}\n```{ext}\n{excerpt}\n```\n")

    return [f for f, _ in found]


# ── main entry ────────────────────────────────────────────────────


def find_context(task: str, target: str | None = None) -> None:
    if not os.path.isdir(CONTEXT_DIR):
        print(f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.", file=sys.stderr)
        sys.exit(1)

    arch      = _read_context_file('ARCHITECTURE.md')
    decisions = _read_context_file('DECISIONS.md')
    symbols   = _read_context_file('SYMBOLS.md')

    if not arch:
        print(
            f"Warning: {CONTEXT_DIR}/ARCHITECTURE.md is empty. "
            "Run `cram sync` to rebuild it.",
            file=sys.stderr,
        )

    ctx_model, coding_model = get_model_recommendations()

    # ── Stage 1: symbol index ─────────────────────────────────────
    if symbols:
        sym_count = sum(
            len(line.split(': ', 1)[1].split(','))
            for line in symbols.splitlines() if ': ' in line
        )
        print(f"[1/4] Symbol index ready — {sym_count} identifiers across "
              f"{symbols.count(chr(10)) + 1} files")
    else:
        print("[1/4] Symbol index not found — run `cram sync` for better file selection")

    # ── Stage 2: file selection (LLM call) ───────────────────────
    print(f"[2/4] Identifying relevant files via {ctx_model} ...")
    sys.stdout.flush()

    file_entries = find_relevant_files(task, arch, decisions, symbols)
    found_entries = [(f, ids) for f, ids in file_entries if os.path.exists(f)]
    missing       = [f for f, _ in file_entries if not os.path.exists(f)]

    if not file_entries:
        print("No files identified. Check that ARCHITECTURE.md describes the repo structure.")
        return

    for fpath, ids in found_entries:
        id_note = f" ({', '.join(ids[:3])}{'…' if len(ids) > 3 else ''})" if ids else ''
        print(f"  → {fpath}{id_note}")
    if missing:
        print(f"  (skipped {len(missing)} not found on disk)")

    # Warn about truncation (Gap 6)
    total_suggested = len(file_entries)
    if total_suggested >= MAX_FILES:
        print(f"  Note: capped at {MAX_FILES} files — set AICONTEXT_MAX_FILES to raise limit")

    # ── Stage 3: excerpt extraction ───────────────────────────────
    print(f"[3/4] Extracting focused excerpts from {len(found_entries)} file(s) ...")
    sys.stdout.flush()

    for fpath, ids in found_entries:
        excerpt = _extract_excerpt(fpath, ids)
        tok = len(excerpt) // 4
        id_note = f" ({', '.join(ids[:2])}{'…' if len(ids) > 2 else ''})" if ids else ''
        print(f"  → {fpath}{id_note}  ~{tok:,} tokens")

    # ── Stage 4: write context ───────────────────────────────────
    print(f"[4/4] Writing context ...")
    sys.stdout.flush()

    inlined = populate_current_task(task, file_entries, ctx_model, coding_model)

    task_path = os.path.join(CONTEXT_DIR, 'CURRENT_TASK.md')
    with open(task_path) as f:
        tokens = len(f.read()) // 4

    min_tokens = cache_min_tokens(coding_model)
    if tokens < min_tokens:
        print(
            f"  Warning: ~{tokens:,} tokens is below the {min_tokens:,}-token cache minimum "
            f"for {coding_model}.\n"
            f"  Increase AICONTEXT_MAX_LINES or AICONTEXT_MAX_EXCERPT_LINES to pad context."
        )

    if target:
        arch_content = _read_context_file('ARCHITECTURE.md')
        with open(task_path) as fh:
            task_content = fh.read()
        root = _find_git_root(os.getcwd())
        if target == 'all':
            written = _targets.write_to_all_detected(root, task_content, arch_content)
            for p in written:
                print(f"  → {os.path.relpath(p)}")
            if not written:
                print("  (no known tool indicators found — try a specific --target)")
        else:
            path = _targets.write_to_target(root, target, task_content, arch_content)
            print(f"  → {os.path.relpath(path)}")

    # ── Save session metadata ─────────────────────────────────────
    try:
        from cram.session import save_session
        root = _find_git_root(os.getcwd())
        expiry = save_session(root, task)
    except Exception:
        root = _find_git_root(os.getcwd())
        expiry = None

    savings_note = ''
    try:
        from cram.benchmark import _count_repo_tokens
        repo_tokens, _ = _count_repo_tokens(root)
        if repo_tokens > tokens:
            pct = int((1 - tokens / repo_tokens) * 100)
            savings_note = f' · {pct}% less than full repo'
    except Exception:
        pass

    print(f"\n✓ Ready — ~{tokens:,} tokens{savings_note} · switch to {coding_model}")
    if expiry:
        print(f"  Context resets on commit after {expiry} "
              f"(run `cram continue` to extend)")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog='cram task',
        description='Populate CURRENT_TASK.md before a coding session',
    )
    parser.add_argument('task', nargs='+', help='Task description')
    parser.add_argument(
        '--target',
        choices=[*_targets.TARGET_FILES, 'all'],
        default=None,
        metavar='TARGET',
        help=(
            'Auto-load context into the tool\'s instruction file. '
            f"Choices: {', '.join(_targets.TARGET_FILES)} | all. "
            'Falls back to default_target in .cram-ai-context/config.toml.'
        ),
    )
    parser.add_argument('--path', default=None, metavar='REPO_PATH')
    args = parser.parse_args()

    start = os.path.abspath(args.path) if args.path else os.getcwd()
    root  = _find_git_root(start)

    if not os.path.isdir(os.path.join(root, CONTEXT_DIR)):
        print(
            f"Error: {CONTEXT_DIR}/ not found in {root}.\n"
            "  Run `cram init` first, or use --path to point at your repo:\n"
            f"  cram task \"{' '.join(args.task)}\" --path /path/to/repo",
            file=sys.stderr,
        )
        sys.exit(1)

    os.chdir(root)
    task = ' '.join(args.task)
    effective_target = args.target or _targets.load_default_target(root)
    find_context(task, effective_target)


if __name__ == '__main__':
    main()
