"""Pre-session file discovery: identifies relevant excerpts and populates CURRENT_TASK.md."""

from __future__ import annotations
import os
import re
import sys

from cram.utils import call_context_model, get_model_recommendations, find_git_root as _find_git_root
from cram import targets as _targets

MAX_FILES         = int(os.environ.get('AICONTEXT_MAX_FILES',        '5'))
MAX_EXCERPT_LINES = int(os.environ.get('AICONTEXT_MAX_EXCERPT_LINES', '80'))

CONTEXT_DIR = '.cram-ai-context'


def _read_context_file(filename: str) -> str:
    path = os.path.join(CONTEXT_DIR, filename)
    if not os.path.exists(path):
        return ''
    with open(path) as f:
        return f.read()


def _resolve_path(raw: str, root: str = '.') -> str:
    """Resolve a model-returned path to an actual file, handling missing dir prefixes."""
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


def _task_keywords(task: str) -> list[str]:
    """Extract meaningful keywords from a task description."""
    stop = {
        'fix', 'add', 'update', 'change', 'make', 'the', 'a', 'an', 'in',
        'to', 'for', 'of', 'and', 'or', 'with', 'use', 'using', 'from',
        'this', 'that', 'will', 'should', 'need', 'needs', 'get', 'set',
    }
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', task)
    return list({w.lower() for w in words if len(w) >= 3 and w.lower() not in stop})


def _extract_excerpt(fpath: str, keywords: list[str]) -> str:
    """Return a keyword-focused excerpt of a file, or the full file if it's small."""
    with open(fpath, errors='ignore') as f:
        lines = f.readlines()

    total = len(lines)
    if total <= MAX_EXCERPT_LINES:
        return ''.join(lines)

    if not keywords:
        omitted = total - MAX_EXCERPT_LINES
        return ''.join(lines[:MAX_EXCERPT_LINES]) + f'\n... [{omitted} lines omitted]\n'

    kw_lower = [k.lower() for k in keywords]
    window   = 12

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


def find_relevant_files(task: str, arch: str, decisions: str) -> list[str]:
    prompt = (
        f"Repo architecture:\n{arch}\n\n"
        f"Decisions:\n{decisions}\n\n"
        f'Task: "{task}"\n\n'
        f"List ONLY the files DIRECTLY needed to complete this task. Be conservative.\n"
        f"Rules:\n"
        f"- UI/styling/colour tasks → CSS and HTML files only, not Python backend\n"
        f"- Backend/API tasks → Python files only, not UI assets\n"
        f"- Logic/behaviour tasks → JS or relevant backend file\n"
        f"- 1-3 files is almost always enough\n"
        f"Max {MAX_FILES} files. One file path per line. No explanation, no bullets."
    )
    raw_lines = call_context_model(prompt).strip().splitlines()
    paths = [_clean_path(l) for l in raw_lines if l.strip()]
    paths = [p for p in paths if p][:MAX_FILES]
    return [_resolve_path(p) for p in paths]


def populate_current_task(
    task: str,
    files: list[str],
    ctx_model: str = '',
    coding_model: str = '',
) -> list[str]:
    """Write CURRENT_TASK.md with focused excerpts. Returns files actually inlined."""
    found   = [f for f in files if os.path.exists(f)]
    missing = [f for f in files if not os.path.exists(f)]
    keywords = _task_keywords(task)

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
        for fpath in found:
            ext     = os.path.splitext(fpath)[1].lstrip('.')
            excerpt = _extract_excerpt(fpath, keywords)
            out.write(f"\n### {fpath}\n```{ext}\n{excerpt}\n```\n")

    return found


def find_context(task: str, target: str | None = None) -> None:
    if not os.path.isdir(CONTEXT_DIR):
        print(f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.", file=sys.stderr)
        sys.exit(1)

    arch      = _read_context_file('ARCHITECTURE.md')
    decisions = _read_context_file('DECISIONS.md')

    if not arch:
        print(
            f"Warning: {CONTEXT_DIR}/ARCHITECTURE.md is empty or missing. "
            "File suggestions may be less accurate.",
            file=sys.stderr,
        )

    ctx_model, coding_model = get_model_recommendations()
    print(f"Finding relevant files for: {task!r} ...")
    print(f"  Context model : {ctx_model}")
    print(f"  Coding model  : {coding_model}")

    files = find_relevant_files(task, arch, decisions)

    if not files:
        print("No files identified. Check that ARCHITECTURE.md describes the repo structure.")
        return

    inlined = populate_current_task(task, files, ctx_model, coding_model)

    # Report token estimate
    task_path = os.path.join(CONTEXT_DIR, 'CURRENT_TASK.md')
    with open(task_path) as f:
        tokens = len(f.read()) // 4
    print(f"\nWrote {CONTEXT_DIR}/CURRENT_TASK.md (~{tokens:,} tokens) with {len(inlined)} file(s):")
    for f in inlined:
        print(f"  {f}")

    missing = [f for f in files if f not in inlined]
    if missing:
        print("\nSkipped (not found on disk):")
        for f in missing:
            print(f"  {f}")

    if target:
        with open(task_path) as fh:
            content = fh.read()
        root = _find_git_root(os.getcwd())
        print("\nContext auto-loaded into:")
        if target == 'all':
            written = _targets.write_to_all_detected(root, content)
            for p in written:
                print(f"  → {os.path.relpath(p)}")
            if not written:
                print("  (no known tool indicators found — try a specific --target)")
        else:
            path = _targets.write_to_target(root, target, content)
            print(f"  → {os.path.relpath(path)}")

    print(f"\nReady. Switch to {coding_model} and start your session.")


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
