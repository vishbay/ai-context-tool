#!/usr/bin/env python3
"""PostToolUse hook: show a user note after get_context() is called via MCP."""
import json
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Handle both possible tool_response shapes
    result = ''
    tool_response = data.get('tool_response', data.get('tool_result', ''))
    if isinstance(tool_response, dict):
        for block in tool_response.get('content', []):
            if isinstance(block, dict) and block.get('type') == 'text':
                result = block.get('text', '')
                break
    elif isinstance(tool_response, str):
        result = tool_response

    task = ''
    for line in result.split('\n'):
        s = line.strip()
        if s.startswith('# Task:'):
            task = s[len('# Task:'):].strip()
            break

    note = 'cram context loaded'
    if task:
        note += f': {task}'

    print(json.dumps({'systemMessage': note}))


main()
