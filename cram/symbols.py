"""Regex-based symbol index: maps each source file to its top-level public identifiers."""

from __future__ import annotations
import os
import re

CONTEXT_DIR = '.cram-ai-context'

_SKIP_DIRS = {
    '.git', '.venv', 'venv', 'node_modules', '__pycache__',
    'dist', 'build', '.next', 'coverage', CONTEXT_DIR,
}

# (extensions, compiled pattern) — groups capture identifier names
_PATTERNS: list[tuple[tuple[str, ...], re.Pattern]] = [
    (
        ('.py',),
        re.compile(r'^(?:async\s+)?def\s+([A-Za-z]\w*)|^class\s+([A-Za-z]\w*)', re.MULTILINE),
    ),
    (
        ('.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs'),
        re.compile(
            r'(?:^export\s+)?(?:async\s+)?function\s+([A-Za-z]\w*)'
            r'|^(?:export\s+)?class\s+([A-Za-z]\w*)'
            r'|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z]\w*)\s*=\s*(?:async\s*)?\(',
            re.MULTILINE,
        ),
    ),
    (
        ('.go',),
        re.compile(r'^func\s+(?:\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)', re.MULTILINE),
    ),
    (
        ('.rb',),
        re.compile(r'^\s*def\s+([A-Za-z]\w*)|^class\s+([A-Z]\w*)', re.MULTILINE),
    ),
    (
        ('.rs',),
        re.compile(
            r'^(?:pub(?:\(\w+\))?\s+)?fn\s+([A-Za-z]\w*)'
            r'|^(?:pub(?:\(\w+\))?\s+)?struct\s+([A-Z]\w*)'
            r'|^(?:pub(?:\(\w+\))?\s+)?enum\s+([A-Z]\w*)',
            re.MULTILINE,
        ),
    ),
    (
        ('.java', '.kt'),
        re.compile(
            r'(?:public|private|protected|internal)?\s*(?:static\s+)?'
            r'(?:class|interface|enum|fun|object)\s+([A-Za-z]\w*)',
            re.MULTILINE,
        ),
    ),
]

MAX_SYMBOLS_PER_FILE = 25


def _symbols_for_file(fpath: str) -> list[str]:
    ext = os.path.splitext(fpath)[1].lower()
    pattern = next((p for exts, p in _PATTERNS if ext in exts), None)
    if pattern is None:
        return []
    try:
        with open(fpath, errors='ignore') as f:
            content = f.read()
    except OSError:
        return []

    seen: list[str] = []
    for m in pattern.finditer(content):
        name = next((g for g in m.groups() if g), None)
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= MAX_SYMBOLS_PER_FILE:
            break
    return seen


def extract_symbols(root: str) -> str:
    """Walk root and return a compact symbol-index string."""
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith('.')
        )
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            symbols = _symbols_for_file(fpath)
            if symbols:
                rel = os.path.relpath(fpath, root)
                lines.append(f"{rel}: {', '.join(symbols)}")
    return '\n'.join(lines)


def write_symbols_md(root: str) -> tuple[str, int]:
    """Generate SYMBOLS.md in the context dir. Returns (content, identifier_count)."""
    content = extract_symbols(root)
    path = os.path.join(root, CONTEXT_DIR, 'SYMBOLS.md')
    with open(path, 'w') as f:
        f.write(content)
    count = sum(1 for line in content.splitlines() if ': ' in line
                for _ in line.split(': ', 1)[1].split(','))
    return content, count
