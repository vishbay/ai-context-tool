"""Repo-local context directory helpers.

The public contract is `.ai-context/`.  `.cram-ai-context/` is kept as a
temporary legacy fallback so older repos keep working while they migrate.
"""

from __future__ import annotations

import os
import sys

CONTEXT_DIR = '.ai-context'
LEGACY_CONTEXT_DIR = '.cram-ai-context'


def canonical_context_dir(root: str = '.') -> str:
    return os.path.join(os.path.abspath(root), CONTEXT_DIR)


def legacy_context_dir(root: str = '.') -> str:
    return os.path.join(os.path.abspath(root), LEGACY_CONTEXT_DIR)


def resolve_context_dir(root: str = '.', *, warn: bool = False) -> str:
    """Return the context dir to use for this repo, preferring `.ai-context/`."""
    canonical = canonical_context_dir(root)
    if os.path.isdir(canonical):
        return canonical

    legacy = legacy_context_dir(root)
    if os.path.isdir(legacy):
        if warn:
            print(
                f"Warning: using legacy {LEGACY_CONTEXT_DIR}/. "
                f"Run `cram init` or migrate it to {CONTEXT_DIR}/.",
                file=sys.stderr,
            )
        return legacy

    return canonical


def has_context_dir(root: str = '.') -> bool:
    return os.path.isdir(canonical_context_dir(root)) or os.path.isdir(legacy_context_dir(root))


def context_path(root: str, filename: str, *, warn: bool = False) -> str:
    return os.path.join(resolve_context_dir(root, warn=warn), filename)


def context_basename(root: str = '.') -> str:
    return os.path.basename(resolve_context_dir(root))
