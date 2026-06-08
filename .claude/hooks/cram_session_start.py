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

    # Extract task name — two formats:
    #   MCP format:  "# Task: <description>" (first line)
    #   CLI format:  "# Current Task\n\n## Task\n<description>"
    #   Reset state: "# Current Task\n\n## Task\n<!-- Session ended... -->"
    task = ''
    lines = content.split('\n')
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('# Task:'):
            task = s[len('# Task:'):].strip()
            break
        if s == '## Task':
            # Next non-empty, non-comment, non-heading line is the task description
            for next_line in lines[i + 1:]:
                ns = next_line.strip()
                if ns.startswith('#'):
                    break  # hit next section — no task set
                if ns and not ns.startswith('<!--'):
                    task = ns
                    break
            break

    # Skip injection when no active task (placeholder-only content)
    if not task:
        sys.exit(0)

    note = f'cram context loaded: {task}'
    print(json.dumps({
        'additionalContext': content,
        'systemMessage': note,
    }))


main()
