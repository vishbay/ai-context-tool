"""Write task context to each AI tool's auto-loaded instruction file."""

from __future__ import annotations
import os

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

CONTEXT_DIR = '.cram-ai-context'

# Each entry is a cram-owned file the tool reads automatically.
# cram overwrites it on every `cram task` run — no shared config is ever touched.
TARGET_FILES: dict[str, str] = {
    "cursor":   ".cursor/rules/cram-task.md",      # Cursor reads all files in .cursor/rules/
    "claude":   ".cram-ai-context/CLAUDE.md",       # Claude Code reads CLAUDE.md recursively in subdirs
    "copilot":  ".github/cram-task.md",             # Requires one-time include in copilot-instructions.md
    "codex":    ".cram-ai-context/AGENTS.md",       # Codex reads AGENTS.md recursively in subdirs
    "windsurf": ".windsurf/rules/cram-task.md",     # Windsurf reads all files in .windsurf/rules/
}

# File or directory whose presence indicates the tool is active in the repo
TARGET_INDICATORS: dict[str, str] = {
    "cursor":   ".cursor",
    "claude":   "CLAUDE.md",
    "copilot":  ".github",
    "codex":    "AGENTS.md",
    "windsurf": ".windsurfrules",
}


def load_default_target(root: str) -> str | None:
    """Read default_target from .cram-ai-context/config.toml, if present."""
    config_path = os.path.join(root, CONTEXT_DIR, 'config.toml')
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, 'rb') as f:
            cfg = tomllib.load(f)
        val = cfg.get('task', {}).get('default_target')
        return val if val in {*TARGET_FILES, 'all'} else None
    except Exception:
        return None


def save_default_target(root: str, target: str) -> None:
    """Persist default_target to .cram-ai-context/config.toml.

    Silently no-ops if target is invalid or the file cannot be written.
    Preserves all other content already in config.toml.
    """
    import re
    if target not in {*TARGET_FILES, 'all'}:
        return
    config_path = os.path.join(root, CONTEXT_DIR, 'config.toml')
    content = ''
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                content = f.read()
        except OSError:
            return

    line = f'default_target = "{target}"'
    if re.search(r'^\s*default_target\s*=', content, re.MULTILINE):
        content = re.sub(
            r'^\s*default_target\s*=.*',
            line,
            content,
            flags=re.MULTILINE,
        )
    elif re.search(r'^\[task\]', content, re.MULTILINE):
        content = re.sub(
            r'^(\[task\])',
            lambda m: m.group(0) + f'\n{line}',
            content,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        sep = '\n\n' if content.strip() else ''
        content = content.rstrip('\n') + f'{sep}[task]\n{line}\n'

    try:
        with open(config_path, 'w') as f:
            f.write(content)
    except OSError:
        pass


def detect_targets(root: str) -> list[str]:
    """Return names of tools whose indicator file/dir exists in the repo."""
    return [t for t, ind in TARGET_INDICATORS.items()
            if os.path.exists(os.path.join(root, ind))]


def write_to_target(root: str, target: str, content: str) -> str:
    """Overwrite the cram-owned file for this target. Returns the absolute path written."""
    rel = TARGET_FILES.get(target)
    if not rel:
        raise ValueError(f"Unknown target '{target}'. Valid: {', '.join(TARGET_FILES)}")

    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    return path


def write_to_all_detected(root: str, content: str) -> list[str]:
    """Write to every tool whose indicator is present. Returns paths written."""
    written = []
    for target in detect_targets(root):
        try:
            written.append(write_to_target(root, target, content))
        except Exception:
            pass
    return written
