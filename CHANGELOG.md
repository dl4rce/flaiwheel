# Changelog

All notable changes to Flaiwheel are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [3.5.0] — 2026-03-03

### Added
- **Claude Desktop (macOS app)** — installer auto-configures `~/Library/Application Support/Claude/claude_desktop_config.json` using `mcp-remote` as a stdio→SSE bridge. Requires Node.js/npx. Falls back with manual instructions if npx is absent.
- **Claude Code CLI** — installer auto-runs `claude mcp add --transport sse --scope project flaiwheel ...` if the `claude` CLI is on PATH. Falls back with a boxed `ACTION REQUIRED` prompt if not.
- **`CLAUDE.md`** — generated in project root with a first-session `/mcp` connection check; the AI agent proactively prompts the user with the registration command if Flaiwheel is not connected.
- **`.mcp.json`** — generated in project root for Claude Code CLI project-scope MCP config.
- **`AGENTS.md`** — generated in project root for all other agents.

### Fixed
- `mcp-proxy` replaced by `mcp-remote` for Claude Desktop bridge — `mcp-proxy` treated the SSE URL as a process to spawn (`ENOENT`); `mcp-remote` correctly acts as a stdio client connecting to a remote SSE endpoint.
- Test `test_execute_move_stages_targeted_paths` — filter used tuple comparison against list (`[:2] == ("git","add")`), always returning empty.
- Test `test_setup_keyword_path` — corrected expected value from `"docs"` to `"setup"` for `ops/install-guide.md`.

---

## [3.4.7] — 2026-03-03

### Fixed
- **Claude Desktop**: switched from `mcp-proxy` to `mcp-remote` as the stdio→SSE bridge. `mcp-proxy` treated the URL as a command to spawn (`ENOENT`). `mcp-remote` correctly connects to a remote SSE endpoint and exposes it as a local stdio server — which is what Claude Desktop requires.

---

## [3.4.6] — 2026-03-03

### Fixed
- **Claude Desktop crash on launch** — the previous release used `{"type":"sse","url":"..."}` which is not a valid format for Claude Desktop's `claude_desktop_config.json`. Claude Desktop only supports `stdio` servers. The installer now uses `mcp-proxy` as a stdio→SSE bridge: `{"command":"npx","args":["-y","mcp-proxy","http://localhost:8081/sse"]}`. Requires Node.js/npx; gracefully skipped with instructions if not available.

---

## [3.4.5] — 2026-03-03

### Improved
- `install.sh`: when `claude` CLI is not on PATH, print a prominent boxed `ACTION REQUIRED` prompt with the exact command to run — no longer a quiet `info` line that is easy to miss.
- `CLAUDE.md` template (written to user projects) and this repo's own `CLAUDE.md`: added a `⚠️ First-time setup` section that instructs the AI agent to check `/mcp` at session start and proactively tell the user to run the registration command if Flaiwheel is not connected.

---

## [3.4.4] — 2026-03-03

### Added
- `install.sh` now auto-registers Flaiwheel with the Claude Code CLI if `claude` is available on `$PATH`. Zero manual steps needed — the installer calls `claude mcp add --transport sse --scope project flaiwheel ...` automatically and prints `✓` in the summary. Falls back gracefully with the manual command if the CLI is not installed.

---

## [3.4.3] — 2026-03-03

### Fixed
- `install.sh` and `CLAUDE.md` now include the one-time Claude Code trust command (`claude mcp add --transport sse --scope project flaiwheel ...`) in the post-install instructions. Without this step the `.mcp.json` is silently ignored by Claude Code due to its project-scope security approval requirement.

---

## [3.4.2] — 2026-03-03

### Added
- `install.sh` now generates `.mcp.json` and `CLAUDE.md` in the project root so Claude Code connects to Flaiwheel and follows the same behavioral workflow as Cursor — both agents share one knowledge base out of the box.

### Fixed
- Test `test_execute_move_stages_targeted_paths`: filter used tuple comparison against a list (`[:2] == ("git", "add")`), always returning empty — corrected to list comparison.
- Test `test_setup_keyword_path`: expected `"docs"` for `ops/install-guide.md` which contains the `install` token; corrected expectation to `"setup"` to match actual classifier behaviour.

---

## [3.4.1] — 2026-03-03

### Fixed
- Search miss rate in the telemetry dashboard could exceed 100% because `search_bugfixes` calls were counted in the miss numerator but excluded from the denominator (`t.searches` only). Denominator now uses `t.searches + t.bugfix_searches`, consistent with the "Searches" stat box display.

---

## [3.4.0] — 2026-03-02

### Fixed
- `_path_category_hint` bugfix branch now uses the same token-based approach as all other categories — removes inconsistent regex-first detection path.

### Notes
- `install.sh` reads version dynamically from `__init__.py` — no stale hardcodes.
- `CHANGELOG.md` added to repo root for GitHub browsing.

---

## [3.3.0] — 2026-03-02

### Changed
- Path-based document classification now uses token-based signal extraction with confidence scores, avoiding substring false positives (e.g. `apiary` no longer maps to `api`).
- Bootstrap execution stages only touched files (`git add -- <paths>`) — no more global `git add -A` or hard-reset rollback patterns.
- `quality._detect_category` and `bootstrap._consensus` now share the same signal model via `_path_category_hint`.

### Added
- `FileInfo.category_by_path_confidence` field carries path confidence through the classification pipeline.
- Regression tests for false-positive path detection and scoped git staging behavior.

---

## [3.2.0] — 2026-03-01

### Added
- **Persistent telemetry** — MCP tool telemetry survives container restarts and updates.
- **Impact metrics API** — `GET /api/impact-metrics` tracks estimated time saved and regressions avoided.
- **CI guardrail ingestion** — CI can post PR outcomes to `POST /api/telemetry/ci-guardrail-report`.
- **Web UI impact card** — 30-day dashboard for time saved, regressions avoided, guardrail findings.

---

## [3.0.0] — 2026-02-28

### Added
- **Behavioral Directives** — Four machine-level directives (`SILENT_BACKGROUND_SEARCH`, `AUTO_CLOSE_THE_LOOP`, `REUSE_BEFORE_RECREATE`, `FILE_CONTEXT_PRELOAD`) force AI agents to use Flaiwheel silently without being asked.
- **post-commit git hook** — Every `fix:`, `feat:`, `refactor:`, `perf:`, `docs:` commit is captured as a structured knowledge doc automatically. Works from any editor, no credentials required.
- **`get_file_context(filename)`** — New MCP tool (#27) pre-loads spatial knowledge for any source file before editing. Complements `get_recent_sessions()` for full temporal + spatial context.
- REST endpoints: `POST /api/capture-commit`, `GET /api/search/by-file`.

### Stats
- 230 tests, 27 MCP tools, 2 new REST endpoints.

---

## [2.x] — Earlier

For 2.x release notes see the [GitHub Releases page](https://github.com/dl4rce/flaiwheel/releases).
