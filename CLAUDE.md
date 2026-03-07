# Claude Code — Project Instructions

> Full AI agent instructions (including Flaiwheel workflow) are in **AGENTS.md** — read it at the start of every session.

## ⚠️ First-time setup — check MCP connection before anything else

1. Type `/mcp` to see connected servers
2. If `flaiwheel` is **not listed**, tell the user:

   > "Flaiwheel MCP is not connected. Please run this command in your terminal, then restart Claude Code:
   >
   > `claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse`"

3. Do **not** proceed until Flaiwheel is connected — it is the primary knowledge source.

## Session Start Checklist

1. Check MCP connection (see above)
2. Read `AGENTS.md` fully
3. Call `set_project("flaiwheel")` via the Flaiwheel MCP tool
4. Call `get_recent_sessions()` to restore context from the last session

---

## Flaiwheel — Project Knowledge Base (MCP) — YOUR FIRST STOP

> Full AI agent instructions (including Flaiwheel workflow) are in **AGENTS.md** — read it fully before doing anything else.

### ⚠️ First-time setup — check MCP connection before anything else

1. Type `/mcp` to see connected servers
2. If `flaiwheel` is **not listed**, tell the user:

   > "Flaiwheel MCP is not connected. Please run this command in your terminal, then restart Claude Code:
   >
   > `claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse`"

3. Do **not** proceed until Flaiwheel is connected — it is the primary knowledge source for this project.

### Session Start — ALWAYS DO THIS FIRST

1. Check MCP connection (see above)
2. Read `AGENTS.md` in this project root
3. Call `set_project("flaiwheel")` via the Flaiwheel MCP tool
4. Call `get_recent_sessions()` to restore context from the last session
5. **First session only:** Call `analyze_codebase("/src/flaiwheel")` for a zero-token structural overview of the codebase (top files, categories, duplicates). Read it before diving into code.

### Flaiwheel MCP

- **Endpoint:** `http://localhost:8081/sse` (configured in `.mcp.json`)
- **Register once:** `claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse`
- **Verify:** type `/mcp` — `flaiwheel` should appear with 28 tools
- **Rule:** Search Flaiwheel BEFORE reading source code. Always.
- **Rule:** After every bugfix, call `write_bugfix_summary()`. No exceptions.
- **Rule:** End every session with `save_session_summary()`.
