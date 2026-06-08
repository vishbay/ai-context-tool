<!-- cram-ai: start -->
cram-ai context is served via the SessionStart hook and MCP server.

At session start, context is auto-loaded from .cram-ai-context/CURRENT_TASK.md
and you will see a systemMessage: "cram context loaded: <task>". When you see
this, acknowledge it to the user in one line and proceed — do not call
get_context() again.

If no context was auto-loaded (no systemMessage), call get_context() before
answering any question or writing any code. Pass the task description as the
argument (e.g. get_context("fix the rate limiter")), or call with no arguments
to reload the last task's context.

Run `cram doctor` if tools are missing.
<!-- cram-ai: end -->
