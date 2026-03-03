# Claude Code — Project Instructions

> Full AI agent instructions (including Flaiwheel workflow) are in **AGENTS.md** — read it at the start of every session.

## Session Start Checklist

1. Read `AGENTS.md` fully before doing anything else
2. Call `set_project("flaiwheel")` via the Flaiwheel MCP tool
3. Call `get_recent_sessions()` to restore context from the last session

## Flaiwheel MCP

- **Endpoint:** `http://localhost:8081/sse` (configured in `.mcp.json`)
- **First-time trust:** run once → `claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse`
- **Verify connected:** type `/mcp` inside Claude Code — `flaiwheel` should appear with 27 tools
- **Rule:** Search Flaiwheel BEFORE reading source code. Always.
- **Rule:** After every bugfix, call `write_bugfix_summary()`. No exceptions.
- **Rule:** End every session with `save_session_summary()`.
