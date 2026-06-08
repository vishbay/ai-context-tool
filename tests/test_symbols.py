"""Tests for cram/symbols.py — byte-stability of the cached symbol index.

The symbol index is part of the frozen prefix. If its bytes change when the
source hasn't, the agent's cached prefix silently invalidates and the next
request pays a cache WRITE instead of a read. These tests pin determinism.
"""

import os

from cram.symbols import extract_symbols


def _write(root: str, rel: str, content: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _make_repo(tmp_path) -> str:
    root = str(tmp_path)
    _write(root, 'pkg/alpha.py', 'def foo():\n    pass\n\nclass Bar:\n    pass\n')
    _write(root, 'pkg/beta.py', 'async def baz():\n    pass\n')
    _write(root, 'web/app.ts', 'export function handler() {}\nexport class Widget {}\n')
    _write(root, 'README.md', '# not a source file\n')
    return root


class TestByteStability:
    def test_identical_across_runs(self, tmp_path):
        """Same source → byte-identical index. A diff here is a silent cache write."""
        root = _make_repo(tmp_path)
        first  = extract_symbols(root)
        second = extract_symbols(root)
        assert first == second

    def test_deterministic_sorted_order(self, tmp_path):
        """File lines are emitted in sorted path order regardless of FS walk order."""
        root = _make_repo(tmp_path)
        lines = [ln for ln in extract_symbols(root).splitlines() if ln]
        paths = [ln.split(':', 1)[0] for ln in lines]
        assert paths == sorted(paths)

    def test_symbols_within_file_preserve_source_order(self, tmp_path):
        """Identifier order within a line follows source order, not hash order."""
        root = str(tmp_path)
        _write(root, 'a.py', 'def first():\n    pass\n\ndef second():\n    pass\n')
        line = next(
            ln for ln in extract_symbols(root).splitlines() if ln.startswith('a.py:')
        )
        assert line == 'a.py: first, second'

    def test_excludes_non_source_and_noise_dirs(self, tmp_path):
        root = _make_repo(tmp_path)
        _write(root, 'node_modules/dep/index.js', 'export function leak() {}\n')
        out = extract_symbols(root)
        assert 'README.md' not in out
        assert 'node_modules' not in out
