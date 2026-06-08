"""Branch-name → task description heuristic for the auto-suggest feature."""

from __future__ import annotations
import re
import subprocess

_PREFIX_VERBS: dict[str, str] = {
    'feature':  'Add',
    'feat':     'Add',
    'fix':      'Fix',
    'bugfix':   'Fix',
    'hotfix':   'Fix',
    'chore':    'Update',
    'refactor': 'Refactor',
    'docs':     'Update docs for',
    'doc':      'Update docs for',
    'test':     'Add tests for',
    'tests':    'Add tests for',
}

_SKIP_BRANCHES = frozenset({
    'main', 'master', 'develop', 'development', 'dev',
    'staging', 'release', 'HEAD', '',
})


def _current_branch(repo_root: str) -> str:
    try:
        r = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=repo_root, capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip()
    except Exception:
        return ''


def _parse_branch(branch: str) -> str | None:
    if branch in _SKIP_BRANCHES:
        return None

    verb = ''
    name = branch

    if '/' in name:
        prefix, rest = name.split('/', 1)
        verb = _PREFIX_VERBS.get(prefix.lower(), '')
        name = rest

    # Strip leading issue numbers: PROJ-123, #456, 1234- at start
    name = re.sub(r'^([A-Z]+-\d+[-_]?|#\d+[-_]?|\d{1,6}[-_])', '', name)

    # Replace separators with spaces and strip
    name = re.sub(r'[-_/]+', ' ', name).strip()

    if not name or len(name) < 3:
        return None

    # If branch body starts with the same word as the verb, drop it to avoid
    # "Add add payment gateway" → "Add payment gateway"
    if verb:
        verb_word = verb.split()[0].lower()
        words = name.split()
        if words and words[0].lower() == verb_word:
            name = ' '.join(words[1:]).strip()
            if not name:
                return None

    # Capitalise only the very first letter
    suggestion = f'{verb} {name}' if verb else name
    return suggestion[0].upper() + suggestion[1:]


def suggest_task(repo_root: str) -> str | None:
    """Return a task description inferred from the current git branch, or None."""
    branch = _current_branch(repo_root)
    return _parse_branch(branch)
