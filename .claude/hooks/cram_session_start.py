#!/usr/bin/env python3
"""SessionStart hook: auto-inject cram-ai context and notify the user.

Reads .cram-ai-context/CURRENT_TASK.md from the project root and injects it
as AI context, with a systemMessage shown to the user. Silent no-op if no
cram context exists in the current repo.
"""
import json
import sys
from pathlib import Path


def main():
    task_file = Path.cwd() / '.cram-ai-context' / 'CURRENT_TASK.md'
    if not task_file.exists():
        sys.exit(0)

    try:
        content = task_file.read_text()
    except Exception:
        sys.exit(0)

    task = ''
    for line in content.split('\n'):
        s = line.strip()
        if s.startswith('# Task:'):
            task = s[len('# Task:'):].strip()
            break

    note = 'cram context loaded'
    if task:
        note += f': {task}'

    print(json.dumps({
        'additionalContext': content,
        'systemMessage': note,
    }))


main()
