<!-- cram-ai: start -->
cram-ai context is served via the MCP server — not this file.

Add cram-ai to your .claude/settings.json:
  {
    "mcpServers": {
      "cram-ai": {
        "command": "cram",
        "args": ["mcp", "--repo", "/Users/vishbay/cram-ai"]
      }
    }
  }

Then call get_context("your task") at the start of each session.
<!-- cram-ai: end -->
