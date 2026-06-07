"""Pre-session file discovery: identifies relevant files and populates CURRENT_TASK.md."""

from __future__ import annotations
import os
import re
import sys

from cram.utils import call_model, find_git_root as _find_git_root
from cram import targets as _targets

MAX_FILES = int(os.environ.get('AICONTEXT_MAX_FILES', '5'))
MAX_LINES = int(os.environ.get('AICONTEXT_MAX_LINES', '300'))

CONTEXT_DIR = '.cram-ai-context'


def _read_context_file(filename: str) -> str:
    path = os.path.join(CONTEXT_DIR, filename)
    if not os.path.exists(path):
        return ''
    with open(path) as f:
        return f.read()


def _clean_path(line: str) -> str:
    """Strip markdown bullets, backticks, and whitespace from a line.

    Returns empty string for lines that look like prose rather than file paths.
    """
    line = line.strip()
    line = re.sub(r'^[-*\d.]+\s*', '', line)   # leading bullets / numbered list
    line = line.strip('`').strip()
    # Discard lines that contain spaces (prose) or no path separator / extension
    if ' ' in line:
        return ''
    if '/' not in line and '.' not in line:
        return ''
    return line


def find_relevant_files(task: str, arch: str, decisions: str) -> list[str]:
    prompt = (
        f"Given this repo architecture:\n{arch}\n\n"
        f"And these decisions:\n{decisions}\n\n"
        f'For this task: "{task}"\n\n'
        f"List ONLY the file paths that are directly relevant.\n"
        f"No explanation. One path per line. Maximum {MAX_FILES} files."
    )
    raw_lines = call_model(prompt).strip().splitlines()
    paths = [_clean_path(l) for l in raw_lines if l.strip()]
    return [p for p in paths if p][:MAX_FILES]


def _read_truncated(fpath: str) -> str:
    with open(fpath) as f:
        lines = f.readlines()
    if len(lines) <= MAX_LINES:
        return ''.join(lines)
    kept = lines[:MAX_LINES]
    omitted = len(lines) - MAX_LINES
    return ''.join(kept) + f'\n... [{omitted} lines omitted — increase AICONTEXT_MAX_LINES to see more]\n'


def populate_current_task(task: str, files: list[str]) -> list[str]:
    """Write CURRENT_TASK.md and return the list of files that were actually inlined."""
    found = [f for f in files if os.path.exists(f)]
    missing = [f for f in files if not os.path.exists(f)]

    with open(os.path.join(CONTEXT_DIR, 'CURRENT_TASK.md'), 'w') as out:
        out.write(f"# Current Task\n\n## Task\n{task}\n\n")

        if missing:
            out.write("## Notes\n")
            for m in missing:
                out.write(f"- `{m}` was suggested but not found on disk\n")
            out.write('\n')

        out.write("## Relevant Files\n")
        for fpath in found:
            ext = os.path.splitext(fpath)[1].lstrip('.')
            out.write(f"\n### {fpath}\n```{ext}\n")
            out.write(_read_truncated(fpath))
            out.write("\n```\n")

    return found


def find_context(task: str, target: str | None = None) -> None:
    if not os.path.isdir(CONTEXT_DIR):
        print(
            f"Error: {CONTEXT_DIR}/ not found. Run `cram init` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    arch = _read_context_file('ARCHITECTURE.md')
    decisions = _read_context_file('DECISIONS.md')

    if not arch:
        print(
            f"Warning: {CONTEXT_DIR}/ARCHITECTURE.md is empty or missing. "
            "File suggestions may be less accurate.",
            file=sys.stderr,
        )

    print(f"Finding relevant files for: {task!r} ...")
    files = find_relevant_files(task, arch, decisions)

    if not files:
        print("No files identified. Check that ARCHITECTURE.md describes the repo structure.")
        return

    inlined = populate_current_task(task, files)

    print(f"\nWrote {CONTEXT_DIR}/CURRENT_TASK.md with {len(inlined)} file(s):")
    for f in inlined:
        print(f"  {f}")

    missing = [f for f in files if f not in inlined]
    if missing:
        print("\nSkipped (not found on disk):")
        for f in missing:
            print(f"  {f}")

    # Write to target tool's auto-loaded instruction file
    if target:
        with open(os.path.join(CONTEXT_DIR, 'CURRENT_TASK.md')) as fh:
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

    print("\nReady. Start your coding session — CURRENT_TASK.md has everything inlined.")


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
    parser.add_argument(
        '--path',
        default=None,
        metavar='REPO_PATH',
        help='Path to the repo root (default: auto-detected from cwd)',
    )
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
