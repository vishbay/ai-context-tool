"""Pre-session file discovery: identifies relevant files and populates CURRENT_TASK.md."""

import os
import re
import sys

from cram.utils import call_model

MAX_FILES = int(os.environ.get('AICONTEXT_MAX_FILES', '5'))
MAX_LINES = int(os.environ.get('AICONTEXT_MAX_LINES', '300'))

CONTEXT_DIR = '.ai-context'


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


def find_context(task: str) -> None:
    if not os.path.isdir(CONTEXT_DIR):
        print(
            f"Error: {CONTEXT_DIR}/ not found. Run `aicontext init` first.",
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

    print("\nReady. Start your coding session — CURRENT_TASK.md has everything inlined.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: aicontext task \"<task description>\"", file=sys.stderr)
        sys.exit(1)
    task = ' '.join(sys.argv[1:])
    find_context(task)


if __name__ == '__main__':
    main()
