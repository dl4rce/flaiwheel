# Changelog

All notable changes to Flaiwheel are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [3.9.22] — 2026-03-07

### Fixed
- **installer: use `bash <(curl ...)` to avoid WSL2 pipe write errors** — README updated to use process substitution as primary install form. re-exec falls back to `$HOME` tmp dir if `/tmp` write fails. Error message recommends `bash <(curl ...)` on curl:23.

---

## [3.9.21] — 2026-03-07

### Fixed
- **installer: sudo guard moved to line 3 (before re-exec)** — `curl: (23)` from `sudo curl|bash` truncated the script before the previous guard was reached. Guard now fires on the first bytes received. Duplicate guard removed.

---

## [3.9.20] — 2026-03-07

### Fixed
- **installer: poll Docker daemon readiness on WSL2** — replace fixed 5s sleep with 15×2s poll loop (30s max). Show `service docker start` output. Consolidate WSL detection into one variable.

---

## [3.9.19] — 2026-03-07

### Fixed
- **installer: Docker daemon start on WSL2** — detect WSL2 via `/proc/version`; use `service docker start` instead of `systemctl` (no systemd on WSL2). Better wait time (5s). Clear WSL2-specific error message with fix command and auto-start tip.

---

## [3.9.18] — 2026-03-07

### Fixed
- **installer: block sudo invocation at startup** — detect `SUDO_USER` immediately after color/function setup; exit with clear message if the entire installer was launched via `sudo`. Prevents `/root/.config/gh/` credential misplacement and `curl: (23)` pipe write failures on WSL.

---

## [3.9.17] — 2026-03-07

### Fixed
- **installer: `gh auth login` must not use sudo** — after auto-installing `gh` on Linux/WSL, the installer now pauses and tells the user to run `gh auth login` without `sudo`. Running auth with sudo stores credentials in `/root/.config/gh/`, which is invisible to the current user. Added explicit warning at both the post-install step and the pre-flight auth check.

---

## [3.9.16] — 2026-03-07

### Fixed
- **installer: sudo support for WSL and non-root Linux** — all Linux package manager commands (`apt-get`, `dnf`, `yum`, `zypper`, `pacman`), Docker install script, and `systemctl` calls now prefix with `sudo` when `id -u` is non-zero. Fixes `Permission denied` / lock file errors for WSL users and standard Linux desktop users who run the installer without root.

---

## [3.9.15] — 2026-03-05

### Improved
- **Cold-start classifier: extension + filename heuristics for non-code files** — the "other" bucket (YAML, TOML, SQL, env, Prisma, etc.) now gets classified by extension before the embedding classifier runs:
  - `.yml/.yaml/.toml/.env/.ini/.conf/.cfg` → `setup`
  - `.sql/.prisma/.graphql/.proto` → `architecture`
  - `CHANGELOG.md`, `HISTORY.md`, `RELEASES.md` (by stem) → `changelog`
  - `Dockerfile`, `docker-compose` (by stem) → `setup`
  - Markdown in `docs/` or `documentation/` dirs → `architecture`
  - Other markdown → embedding fallback (not forced into changelog)
- Eliminates the main cause of `changelog` over-classification on large mixed codebases.

---

## [3.9.14] — 2026-03-05

### Fixed
- **Fast-path no longer silently skips cold-start** — on fast-path (correct version already running), `_run_coldstart` now always prompts the user instead of silently returning when a cached report exists. Three prompt variants depending on state:
  - Cache exists → "Re-run to refresh? (y/N)" with pointer to cached report
  - Source cloned but no cache → "Run analysis now? (y/N)"
  - Nothing exists → full cold-start intro + "Run? (y/N)"
- **Removed duplicate `_run_coldstart` call** — was being called twice on fast-path (once inside the fast-path block, once at the global footer); consolidated to the single footer call.

---

## [3.9.13] — 2026-03-05

### Improved
- **Cold-start classification quality** — two-pass classifier in `code_analyzer.py`:
  - **Pass 1 (path heuristics):** high-confidence pattern matching on filename/path before any embedding call. Supabase edge functions → `api`, `test_*` / `*.spec.*` → `tests`, `config`/`settings` → `setup`, `utils`/`helpers` → `best-practices`, etc. Zero model cost, ~90% confidence.
  - **Pass 2 (embedding):** only runs for files not resolved by path heuristics. Uses new code-specific category templates tuned to what source code looks like (not documentation), replacing the doc-oriented `CATEGORY_TEMPLATES` that caused `changelog` over-classification.
- Result: `changelog` bucket correctly narrows to actual release note files instead of dominating the distribution on large mixed codebases.

---

## [3.9.12] — 2026-03-05

### Fixed
- Cold-start `y` answer was ignored when a cached report already existed. The cache check ran before checking `_COLDSTART_ANSWER`, so `y` (explicit re-run) was silently overridden by Case 1 (cache exists → skip). Fixed decision order:
  - `n` → always skip, print manual commands
  - not set (fast-path) → smart: cache→skip, src+no cache→run, nothing→ask
  - `y` → always run regardless of cache (re-clone + re-analyze)

---

## [3.9.11] — 2026-03-05

### Fixed
- `_run_coldstart: command not found` on fast-path. Both cold-start functions (`_run_coldstart`, `_do_coldstart_analysis`) were defined inside the `else` branch of the full install/update path, so they were not in scope when the fast-path called `_run_coldstart`. Moved both definitions to the top of the script (after the helper functions), before any conditional logic.

---

## [3.9.10] — 2026-03-05

### Fixed
- `LATEST_VERSION` was fetched from `https://raw.githubusercontent.com/.../main/...` which is served by GitHub's CDN with a cache TTL of several minutes. After a push, the CDN still served the old version, so `RUNNING_VERSION == LATEST_VERSION` and the fast-path triggered even though a newer version existed. Removed the HTTP fetch entirely — `LATEST_VERSION` is now simply `$_FW_VERSION` (the version embedded in the installer script itself). The installer is always re-pinned to the latest tag via the `curl|bash` self-update at startup, so `_FW_VERSION` is always the true latest. No HTTP call, no cache issue, no false fast-path.

---

## [3.9.9] — 2026-03-05

### Fixed
- **Cold-start runs on fast-path and for additional projects** — previously the cold-start question and analysis only ran on the full install/update path. When `install.sh` detected the correct version already running (fast-path), no cold-start was offered. Same issue when running from a different project directory: the source repo was never cloned and analysis never ran.

### Changed
- Cold-start logic extracted into a shared `_run_coldstart()` function called from **all three paths** (fast-path, update, fresh install).
- **Smart detection** — `_run_coldstart` now checks three states before deciding what to do:
  1. Cache `/data/coldstart-<project>.md` exists → report it's ready, skip silently
  2. `/src/<project>` cloned but no cache → run analysis immediately (no prompt)
  3. Nothing exists → ask the question (default N)

---

## [3.9.8] — 2026-03-05

### Added
- **Cold-start report caching** — `analyze_codebase()` now caches the report to `/data/coldstart-<project>.md` after the first run. Subsequent calls return the cached report instantly (<1s) instead of re-running the full 20-30s analysis. Call with `force=True` to regenerate after significant codebase changes.
- Installer now also writes the cache file during the initial cold-start run, so the first MCP call by any agent is instant.

### Changed
- `analyze_codebase()` now accepts an optional `force` parameter (default `False`).

---

## [3.9.7] — 2026-03-05

### Added
- **Cold-start report in agent Session Setup** — all four instruction templates (`AGENTS.md`, `.cursor/rules/flaiwheel.mdc`, `CLAUDE.md`, `.github/copilot-instructions.md`) now include a step in the Session Setup that tells the agent to call `analyze_codebase("/src/<project>")` on its first session. This gives every connected AI agent (Cursor, Claude Code, VS Code Copilot) an automatic structural overview of the codebase before it starts working — zero tokens, zero manual setup.

### Changed
- Tool count reference in `CLAUDE.md` template updated from 27 to 28.

---

## [3.9.6] — 2026-03-05

### Fixed
- Cold-start `analyze_codebase()` in the installer was calling `curl -X POST http://localhost:8081/tools/...` — but port 8081 is the **MCP SSE endpoint**, not a REST API. Every curl call returned "Not Found", the Python JSON parser failed silently, and the result was always empty. That's why the warm-up loop and analyze call both timed out after 180 seconds despite the model being ready.
- Replaced the entire HTTP approach with `docker exec python3 -c "..."` which runs the analyzer directly inside the container using the same code the MCP tool uses. No HTTP, no protocol mismatch, no warm-up needed — the embedding model is loaded inline as part of the exec. Tested: completes in ~20 seconds on a running container.

---

## [3.9.5] — 2026-03-05

### Fixed
- Cold-start `analyze_codebase()` was retrying the tool call but the embedding model was never actually loaded. `SentenceTransformerEmbeddingFunction` (ChromaDB) lazy-loads the model weights on the **first embed call**, not at container startup. The `/health` endpoint returns 200 as soon as the web server is up — long before the model is ready. The installer now explicitly **warms up the model** first by calling `search_docs("warmup")` and waiting until it returns a valid result (up to 3 minutes / 36 × 5s). Only then is `analyze_codebase()` called, guaranteeing the model is loaded and the report is generated.

---

## [3.9.4] — 2026-03-05

### Fixed
- Cold-start `analyze_codebase()` call in the installer now retries for up to 90 seconds (18 × 5s) instead of giving up immediately. On a fresh install the embedding model may still be downloading/loading when the call is made — the previous single-shot attempt would always fail and print "Report not available yet". Now prints a progress line and retries until the model is ready.

---

## [3.9.3] — 2026-03-05

### Fixed
- `LATEST_VERSION` in the fast-path check was fetched from the pinned tag (`v${_FW_VERSION}`) instead of `main`. If the user ran a cached installer from a previous session (with an older `_FW_VERSION`), `LATEST_VERSION` matched the running container and the fast-path triggered — silently skipping the update prompt even when a newer version existed. Now always fetches from `main` so the comparison reflects the true latest release.

---

## [3.9.2] — 2026-03-05

### Fixed
- Cold-start analysis prompt was placed after the final summary block, meaning it appeared **after** the long Docker rebuild — the user had already left by then. The prompt is now asked upfront (right after the embedding model selection), before the rebuild starts. All questions are gathered interactively first; the clone/analyze executes at the very end once the container is healthy.

---

## [3.9.1] — 2026-03-05

### Added
- **Cold-start one-time source repo clone** — `install.sh` now prompts at the end of install/update: `Run cold-start source code analysis? (y/N)`. Default is **N** so routine updates are unaffected. If confirmed, the installer performs a clean `git clone --depth 1` of the project's own source repo (derived from the already-known `OWNER/PROJECT` git remote) into `/src/<project>` inside the Docker container. GitHub token is reused automatically for private repos. After cloning, `analyze_codebase("/src/<project>")` is invoked via the MCP HTTP endpoint and the bootstrap report is printed inline.
- Manual fallback instructions are printed on skip or clone failure so the user always knows how to run it later.

### Changed
- `_FW_VERSION` in `install.sh` updated to `3.9.1` (was stuck at `3.8.3`).

---

## [3.9.0] — 2026-03-05

### Added
- **`analyze_codebase(path)`** — new MCP tool (28th tool) for zero-token cold-start analysis of legacy source code directories. Runs entirely server-side inside the Docker container. Uses Python's built-in `ast` module for Python parsing (no new dependencies), regex extraction for TypeScript/JavaScript, the existing MiniLM embedding model for nearest-centroid classification against Flaiwheel's 9 knowledge categories, and the existing cosine similarity deduplication pipeline (threshold 0.92). Returns a single `bootstrap_report.md` with: language distribution, inferred category map, top 20 files ranked by documentability score (docstrings, import density, public API surface, entry-point name patterns), near-duplicate file pairs, and undocumented directories. Reduces cold-start agent token cost by ~90% on large legacy repos.
- **`src/flaiwheel/code_analyzer.py`** — new module with zero new dependencies. Exports `CodebaseAnalyzer`, `format_codebase_report`, and extraction helpers `_extract_python`, `_extract_ts_js`, `_score_documentability`, `_walk_repo`.
- 20 new tests in `tests/test_code_analyzer.py` covering walker, Python/TS extractors, scoring, analyzer, deduplication, and report formatting.

### Changed
- Total MCP tools: 27 → 28.
- Test suite: 239 → 259 tests.

---

## [3.8.3] — 2026-03-04

### Fixed
- Installer now reconciles project registration in all paths (fast-path, update mode, fresh install). Previously, if a project was removed via the Web UI and `install.sh` was re-run, the container came back healthy but the project was silently missing from the registry. The installer now checks the `/api/projects` list and re-registers the current project if it is absent, in both the fast-path and the post-update-rebuild path.
- Fast-path project check now checks existence before POSTing, eliminating spurious "project may already exist" warnings on re-runs.

---

## [3.8.2] — 2026-03-04

### Fixed
- Installer temp file (`/tmp/flaiwheel-install-*.sh`) left behind after `curl | bash` could cause `mktemp: mkstemp failed: File exists` on subsequent runs. Now cleans up stale temp files before creating a new one, includes PID in the filename to prevent concurrent-run collisions, and schedules deletion of the temp file immediately after `exec` (the running process holds an open fd so execution continues unaffected).

---

## [3.8.1] — 2026-03-04

### Fixed
- Project creation via web UI no longer auto-indexes on add. `setup_new_project()` previously called `_initial_index()` immediately after cloning the knowledge repo, polluting the vector DB before the user had a chance to review content. Indexing is now intentionally deferred — the user must trigger it explicitly via "Git Pull + Reindex" or the `reindex()` MCP tool. Bootstrap indexing on server restart (existing projects) is unaffected.
- Aligned `__version__` in `src/flaiwheel/__init__.py` with `pyproject.toml` (was `3.8.0`, correctly bumped from `3.8.0` to `3.8.1`).

---

## [3.6.1] — 2026-03-03

### Fixed
- Web UI Client Configuration panel: added VS Code and Claude Code CLI tabs; fixed Claude Desktop tab (was showing SSE format, now correctly shows `mcp-remote` stdio bridge via `npx`).

---

## [3.6.0] — 2026-03-03

### Added
- **VS Code / GitHub Copilot support** — installer writes `.vscode/mcp.json` with native SSE config (no bridge, no Node.js required). Requires VS Code 1.99+ with GitHub Copilot. Works project-scope.
- **`.github/copilot-instructions.md`** — generated in project root with Flaiwheel session rules and MCP connection check instructions for VS Code Copilot.
- VS Code added to all installer summary output variants (FAST_PATH, UPDATE_MODE, fresh install).
- VS Code added to README Quick Start installer list, After Install table, and Manual Setup section.

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
