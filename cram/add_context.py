"""cram add — append extra files to the current session context."""

from __future__ import annotations
import os
import re
import sys

from cram.context_dir import CONTEXT_DIR, context_path, has_context_dir


def _read_task_text(content: str) -> str:
    m = re.search(r'## Task\n(.+?)(?=\n##|\Z)', content, re.DOTALL)
    return m.group(1).strip() if m else ''


def _task_keywords(task_text: str) -> list[str]:
    stop = {
        'add', 'fix', 'the', 'a', 'an', 'to', 'in', 'for', 'of', 'and', 'or',
        'with', 'from', 'that', 'this', 'it', 'is', 'on', 'at', 'by', 'be',
        'update', 'make', 'create', 'change', 'use', 'get', 'set', 'run', 'into',
        'new', 'old', 'all', 'not', 'its', 'has',
    }
    words = re.findall(r'[A-Za-z][A-Za-z0-9_]*', task_text)
    return [w for w in words if len(w) > 2 and w.lower() not in stop]


def _replace_section(content: str, resolved: str, ext: str, excerpt: str) -> str:
    pattern = r'\n### ' + re.escape(resolved) + r'\n```[^\n]*\n.*?\n```'
    replacement = f'\n### {resolved}\n```{ext}\n{excerpt}\n```'
    result, n = re.subn(pattern, replacement, content, flags=re.DOTALL)
    return result if n else content


def add_files(
    file_specs: list[str],
    replace: bool = False,
    target: str | None = None,
) -> bool:
    from cram.find_context import _extract_excerpt, _resolve_path
    from cram.utils import find_git_root as _find_git_root
    from cram import targets as _targets

    task_path = context_path('.', 'CURRENT_TASK.md', warn=True)
    if not os.path.exists(task_path):
        print('Error: no active session. Run `cram task "..."` first.', file=sys.stderr)
        return False

    with open(task_path) as f:
        current = f.read()

    keywords = _task_keywords(_read_task_text(current))
    existing = set(re.findall(r'^### (.+)$', current, re.MULTILINE))

    changed = False

    for spec in file_specs:
        # Support "path/file.py | Func1, Func2" for explicit identifier targeting
        if '|' in spec:
            path_part, id_part = spec.split('|', 1)
            fpath = path_part.strip()
            ids   = [i.strip() for i in id_part.split(',') if i.strip()]
        else:
            fpath = spec.strip()
            ids   = keywords  # use current task's keywords as focus hints

        resolved = _resolve_path(fpath)

        if not os.path.exists(resolved):
            print(f'  ✗  {fpath}  — not found')
            continue

        if resolved in existing and not replace:
            print(f'  !  {resolved}  — already in context (use --replace to update)')
            continue

        ext     = os.path.splitext(resolved)[1].lstrip('.')
        excerpt = _extract_excerpt(resolved, ids)
        tok     = len(excerpt) // 4

        if resolved in existing:
            current = _replace_section(current, resolved, ext, excerpt)
            print(f'  ↺  {resolved}  ~{tok:,} tokens  (updated)')
        else:
            current += f'\n### {resolved}\n```{ext}\n{excerpt}\n```\n'
            print(f'  +  {resolved}  ~{tok:,} tokens')

        changed = True

    if not changed:
        return False

    with open(task_path, 'w') as f:
        f.write(current)

    total = len(current) // 4
    print(f'\n  Total context: ~{total:,} tokens')

    root = _find_git_root(os.getcwd())
    eff_target = target if target is not None else _targets.load_default_target(root)
    if eff_target:
        arch_path = context_path('.', 'ARCHITECTURE.md', warn=True)
        arch = open(arch_path).read() if os.path.exists(arch_path) else ''
        if eff_target == 'all':
            for p in _targets.write_to_all_detected(root, current, arch):
                print(f'  → {os.path.relpath(p)}')
        else:
            path = _targets.write_to_target(root, eff_target, current, arch)
            print(f'  → {os.path.relpath(path)}')

    return True


def main() -> None:
    import argparse
    from cram.utils import find_git_root
    from cram import targets as _targets

    parser = argparse.ArgumentParser(
        prog='cram add',
        description='Append files to the current session context',
    )
    parser.add_argument(
        'files', nargs='+',
        help='Files to add. Quote "path | Func1, Func2" to focus on specific identifiers.',
    )
    parser.add_argument('--replace', action='store_true',
                        help='Replace the excerpt if the file is already in context')
    parser.add_argument('--target',
                        choices=[*_targets.TARGET_FILES, 'all'],
                        default=None, metavar='TARGET')
    parser.add_argument('--path', default=None, metavar='REPO_PATH')
    args = parser.parse_args()

    start = os.path.abspath(args.path) if args.path else os.getcwd()
    root  = find_git_root(start)

    if not has_context_dir(root):
        print(f'Error: {CONTEXT_DIR}/ not found in {root}.', file=sys.stderr)
        sys.exit(1)

    os.chdir(root)
    ok = add_files(args.files, replace=args.replace, target=args.target)
    sys.exit(0 if ok else 1)
