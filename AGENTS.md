<!-- cram-ai: start -->
cram-ai context is served via the MCP server — not this file.

IMPORTANT: Call get_context() as your FIRST action in every session,
before answering any question or writing any code. Pass the task description
as the argument (e.g. get_context("fix the rate limiter")), or call with no
arguments to reload the last task's context.

Add cram-ai to your .Codex/settings.json:
  {
    "mcpServers": {
      "cram-ai": {
        "command": "cram",
        "args": ["mcp", "--repo", "/Users/vishbay/cram-ai"]
      }
    }
  }
<!-- cram-ai: end -->
