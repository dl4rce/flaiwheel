# Copilot Instructions

---

## Flaiwheel — Project Knowledge Base (MCP)

> Full AI agent instructions are in **AGENTS.md** in the project root — read it at session start.

### MCP Connection

Flaiwheel is configured in `.vscode/mcp.json`. Verify the connection:
- Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
- Run **MCP: List Servers** — `flaiwheel` should appear as running

If it is not running:
1. Open `.vscode/mcp.json` and confirm the server entry is present
2. Run **MCP: List Servers** → select `flaiwheel` → click **Start**
3. Requires VS Code 1.99+ with GitHub Copilot

### Session Start — ALWAYS DO THIS FIRST

1. Verify MCP connection (see above)
2. Read `AGENTS.md` in this project root
3. Call `set_project("flaiwheel")` via Flaiwheel MCP
4. Call `get_recent_sessions()` to restore context from the last session
5. **First session only:** Call `analyze_codebase("/src/flaiwheel")` for a zero-token structural overview of the codebase before diving into code.

### Rules

- Search Flaiwheel BEFORE reading source code. Always.
- After every bugfix: `write_bugfix_summary()`. No exceptions.
- End every session with `save_session_summary()`.
