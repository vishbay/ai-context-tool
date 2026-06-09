# Plan: task contract in CURRENT_TASK.md

Add three structured fields to every generated `CURRENT_TASK.md` so the agent starts with
explicit scope rails instead of having to infer them from the file list.

---

## What changes

`populate_current_task()` in `cram/find_context.py` writes three new sections immediately
after `## Task`:

```markdown
## Scope
- cram/
- tests/

## Out of Scope
<!-- Add directories/files the agent should NOT touch -->

## Definition of Done
<!-- Add explicit acceptance criteria before closing this task -->
```

- **Scope** — auto-generated from the directories of the selected files. No user input needed.
- **Out of Scope** — left as a comment placeholder; user fills in before the execution session.
- **Definition of Done** — left as a comment placeholder; user fills in before the execution session.

No new files, no new CLI commands. The contract lives inside the existing `CURRENT_TASK.md`
that `get_context()` already delivers.

---

## Why each field suppresses exploratory reads

**Scope:** The agent sees `- cram/` and stays in `cram/`. Without this, it may wander into
`tests/` or `docs/` to verify things it could infer. Especially effective for refactors and
multi-file tasks.

**Out of Scope:** Explicit exclusions stop the agent before it even checks a file. A model
that reads `Out of Scope: billing/` will not open `billing/models.py` to "just verify it's
not affected." This is the field the user is most likely to fill in on large codebases.

**Definition of Done:** Prevents early stopping ("I've made the change, done") and prevents
over-extension ("while I'm here let me also..."). An explicit list of criteria gives the agent
a checklist, not just a task description.

---

## Implementation

**`cram/find_context.py` — `populate_current_task()`:**

After writing `## Task\n{task}\n\n`, derive scope dirs from `found` (already computed):

```python
scope_dirs = sorted({os.path.dirname(f) or '.' for f, _ in found})
out.write('## Scope\n')
for d in scope_dirs:
    label = (d + '/') if d and d != '.' else '.'
    out.write(f'- {label}\n')
out.write('\n')
out.write('## Out of Scope\n<!-- Add directories/files the agent should NOT touch -->\n\n')
out.write('## Definition of Done\n<!-- Add explicit acceptance criteria before closing this task -->\n\n')
```

No signature change. No callers updated.

---

## Tests

`tests/test_find_context.py` — extend `TestPopulateCurrentTask`:

- `test_scope_section_derived_from_found_files` — verify `## Scope` present and contains
  correct directory
- `test_out_of_scope_placeholder_present` — verify `## Out of Scope` and placeholder comment
- `test_definition_of_done_placeholder_present` — verify `## Definition of Done` present
- `test_scope_empty_when_no_files_found` — missing files only → scope shows `.`
- `test_scope_repo_root_files` — files in repo root → scope shows `.`

---

## What this does NOT do

- Does not auto-generate Out of Scope — cram can't know what's excluded without user input
- Does not auto-generate Definition of Done — criteria are task-specific
- Does not add a new `cram plan` command — that's future work if the fields prove useful
- Does not change `cram task --target` file-based delivery — the contract arrives in whatever
  file the target writes (CLAUDE.md, .cursor/rules/cram-task.md, etc.) unchanged
