"""Generate .vscode/tasks.json so cram commands are available as VS Code tasks."""

from __future__ import annotations
import json
import os
import sys

_TASKS = [
    {
        'label': 'cram: set task',
        'type': 'shell',
        'command': 'cram',
        'args': ['task', '${input:cramTask}'],
        'presentation': {'reveal': 'always', 'panel': 'shared', 'focus': True},
        'problemMatcher': [],
    },
    {
        'label': 'cram: sync',
        'type': 'shell',
        'command': 'cram',
        'args': ['sync'],
        'presentation': {'reveal': 'always', 'panel': 'shared'},
        'problemMatcher': [],
    },
    {
        'label': 'cram: continue',
        'type': 'shell',
        'command': 'cram',
        'args': ['continue'],
        'presentation': {'reveal': 'always', 'panel': 'shared'},
        'problemMatcher': [],
    },
    {
        'label': 'cram: status',
        'type': 'shell',
        'command': 'cram',
        'args': ['status'],
        'presentation': {'reveal': 'always', 'panel': 'shared'},
        'problemMatcher': [],
    },
    {
        'label': 'cram: benchmark',
        'type': 'shell',
        'command': 'cram',
        'args': ['benchmark'],
        'presentation': {'reveal': 'always', 'panel': 'shared'},
        'problemMatcher': [],
    },
    {
        'label': 'cram: decide',
        'type': 'shell',
        'command': 'cram',
        'args': ['decide', '${input:cramDecision}'],
        'presentation': {'reveal': 'always', 'panel': 'shared', 'focus': True},
        'problemMatcher': [],
    },
]

_INPUTS = [
    {
        'id': 'cramTask',
        'type': 'promptString',
        'description': 'What are you building?',
    },
    {
        'id': 'cramDecision',
        'type': 'promptString',
        'description': 'Architectural decision to log',
    },
]


def generate(repo_root: str, force: bool = False) -> None:
    vscode_dir = os.path.join(repo_root, '.vscode')
    tasks_path = os.path.join(vscode_dir, 'tasks.json')

    if os.path.exists(tasks_path) and not force:
        try:
            with open(tasks_path) as f:
                existing = json.load(f)
        except Exception:
            existing = {}
        existing_labels = {t.get('label') for t in existing.get('tasks', [])}
        existing_inputs = {i.get('id')    for i in existing.get('inputs', [])}
        new_tasks  = [t for t in _TASKS  if t['label'] not in existing_labels]
        new_inputs = [i for i in _INPUTS if i['id']    not in existing_inputs]
        if not new_tasks and not new_inputs:
            print('tasks.json already contains all cram tasks — nothing to do.')
            return
        existing.setdefault('tasks',  []).extend(new_tasks)
        existing.setdefault('inputs', []).extend(new_inputs)
        data = existing
        verb = 'Updated'
    else:
        os.makedirs(vscode_dir, exist_ok=True)
        data = {'version': '2.0.0', 'tasks': _TASKS, 'inputs': _INPUTS}
        verb = 'Created'

    with open(tasks_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

    rel = os.path.relpath(tasks_path, repo_root)
    print(f'{verb} {rel}')
    print()
    print('Run tasks:  Terminal → Run Task → type "cram"')
    print()
    print('Suggested keybindings (File → Preferences → Keyboard Shortcuts → open JSON icon):')
    print('  { "key": "ctrl+shift+t", "command": "workbench.action.tasks.runTask",')
    print('    "args": "cram: set task" },')
    print('  { "key": "ctrl+shift+y", "command": "workbench.action.tasks.runTask",')
    print('    "args": "cram: sync" },')
    print('  { "key": "ctrl+shift+u", "command": "workbench.action.tasks.runTask",')
    print('    "args": "cram: continue" }')


def main() -> None:
    import argparse
    from cram.utils import find_git_root

    parser = argparse.ArgumentParser(
        prog='cram vscode',
        description='Generate .vscode/tasks.json for cram commands',
    )
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing tasks.json instead of merging')
    parser.add_argument('path', nargs='?', default=None)
    args = parser.parse_args()

    root = find_git_root(os.path.abspath(args.path) if args.path else '.')
    generate(root, force=args.force)
