# Changelog

All notable changes to Flaiwheel are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [3.13.0] — 2026-08-19 — Observability

**Closes the 2026-08-19 incident entirely.** The last and largest gap: Flaiwheel could not tell whether its knowledge repository was still connected to its remote.

Everything shipped in 3.12.x reports on *pushes that were attempted*. The failure that hid 325 documents inside a Docker volume for 2.5 months attempted nothing at all — the clone had drifted from its remote, so there was never anything to commit, so no push could fail, so no metric could go red. "Nothing to push (already in sync)" and genuinely being in sync were rendered identically. This release makes the local↔remote relationship itself a first-class, monitored fact.

### Added
- **Divergence detection — `GitWatcher.check_divergence()`.** Compares `HEAD` against `@{u}` with `git rev-list --left-right --count` and classifies the result as `synced`, `ahead`, `behind`, `diverged`, `no-upstream`, or `unknown`. The states are deliberately distinct rather than a boolean: `behind` is the *normal* state between two pulls and must not raise an alarm, whereas `ahead` (commits that exist only locally), `diverged` (histories split — pushes will be rejected) and `no-upstream` (writes landing in a repo that pushes nowhere) each mean knowledge is not being backed up, for different reasons and with different fixes.
- **Divergence is checked on the `noop` path.** This is the entire point. A repository with nothing to commit is precisely where a disconnected clone hides, so that path — the one that used to return an unconditional "already in sync" — now establishes whether that claim is *true*. It is also checked after every successful push (confirming the commit actually landed), after a rejected push (a rejection is the classic symptom of divergence — now named instead of leaving the caller to parse a git error), and on every pull, including a failed `--ff-only` pull, which refuses in exactly the diverged case.
- **`HealthTracker` records divergence and escalates on it.** New `divergence_status`, `commits_ahead`, `commits_behind`, and `last_divergence_at`. `is_healthy` returns `False` for `diverged`, `ahead`, and `no-upstream`. A repository that indexes perfectly and pushes nothing can no longer report itself healthy. `unknown` is never persisted as a state — a transient fetch failure must not erase a real `diverged` verdict.
- **`/health` exposes the divergence fields** on both the per-project and aggregate endpoints, alongside the push metrics added in 3.12.3.
- **Agents are told directly.** Every `write_*` tool result now appends an explicit warning when the repository has diverged, is ahead, or tracks no upstream — including on `noop`. A warning that lives only in an endpoint nobody polls does not exist; the agent writing the document is the one that needs to know it did not leave the machine.

### Notes
- 19 new tests (**335 total**), exercising real temp repositories: a force-pushed rewritten upstream (the real-world trigger — a secret purge or a squash silently desynchronises every clone), a repo with no upstream, `behind` treated as healthy, and `unknown` not clearing a prior verdict.
- **The incident is now fully remediated.** Items A, B, C, D and E shipped across v3.12.0 → v3.13.0. Item F — "watcher path scoping" — was **retracted as a misdiagnosis**, verified against the running container: `/docs` is not a git repo, every project owns its `.git`, so `_find_git_dir()` cannot escape upward past its own project, and no commit in any repo contains another project's path. The evidence that produced item F was the log line `knowledge: update flaiwheel/telemetry.json`, read as one project's file appearing in all 11 repos. The real file is `.flaiwheel/telemetry.json` — **with a leading dot**. That missing dot is the exact signature of the porcelain off-by-one fixed in v3.12.2, which truncated the first character of the first worktree-modified filename. Every project owns an identically-named `.flaiwheel/telemetry.json` rewritten on each sync tick, so all 11 watchers emitted the same mangled string simultaneously — uniformity caused by shared *code*, misread as shared *state*. A log line is evidence of a symptom, not of a cause.

## [3.12.3] — 2026-08-19

Preventive hardening. No user-visible behaviour changes; all three items close gaps that the 2026-08-19 incident exposed but did not fix.

### Changed
- **Every dependency is now capped below the next major.** Eleven requirements were unbounded `>=X`. That is a promise no upstream makes, and it fails silently: the breaking release lands, existing environments keep working off a stale resolve, and the failure only appears on the next fresh install — CI, a Docker rebuild, or a new contributor's checkout. This is exactly how `mcp` 2.0.0 took out CI and the Docker build together in v3.12.0, three weeks after release, while every developer machine stayed green. Verified that a clean install resolves to byte-identical versions as before (`chromadb` 1.5.9, `fastapi` 0.141.1, `pypdf` 6.16.1, …), so the caps constrain the future without moving anything today. Raise a cap deliberately, with the suite green against the new major.

### Added
- **Consecutive-push-failure tracking.** `HealthTracker` recorded only `last_push_ok`, a single boolean that the next attempt overwrites — so one transient blip and a repository that had been failing for weeks were indistinguishable. `push_failures_consecutive` now increments on failure and resets on success. Past `PUSH_FAILURE_THRESHOLD` (3) `/health` reports `degraded`, so sustained failure escalates instead of staying invisible. A single failure deliberately does **not** degrade — crying wolf on transients is how alerts get ignored.
- **`/health` now reports the push state and names the failing projects.** Added `last_push_ok`, `last_push_error`, `push_failures_consecutive`, and `degraded_projects`. Previously the aggregate endpoint could report `degraded` while showing only the default project's metrics, leaving no way to tell *which* of the repositories was broken.
- **Documented the pre-deploy image smoke test.** An image can build cleanly and still fail every import at runtime when a transitive dependency breaks on a fresh resolve — the v3.12.0 rollback in full. The README manual-install path now runs `from flaiwheel.server import create_mcp_server` inside the image before any container is started, and documents renaming rather than removing the previous container so rollback is instant.

### Notes
- 6 new tests (**316 total**). The escalation test was verified to fail against the previous code.
- Still open from the same incident: divergence detection (no `HEAD..@{u}` comparison exists yet — the actual gap that hid 325 documents for 2.5 months) and watcher path scoping.

## [3.12.2] — 2026-08-19

### Fixed
- **Auto-commit silently dropped the first changed file when it was modified in the worktree.** `_push_local_changes()` called `status.stdout.strip()` before splitting into lines. Porcelain lines are `XY <path>` where `X` or `Y` may be a space — a file modified in the worktree but not staged is reported as `" M path"`. Stripping the whole output removes the leading space of the **first line only**, so the subsequent `line[3:]` truncated that filename's first character: `.flaiwheel/telemetry.json` became `flaiwheel/telemetry.json` and `git add` failed with `pathspec did not match any files`. The commit then aborted with "no changes added to commit". Now iterates the raw stdout.
- **Renamed and copied files were never staged.** Porcelain reports these as `old -> new`; the whole string was passed to `git add`. The new path is now extracted for `R`/`C` status codes.

### Notes
- Both bugs are older than v3.12.0 and were **invisible until v3.12.0 made push failures visible** — they were found within minutes of deploying it, on the very first real push. This is the intended payoff of that release.
- 2 new regression tests (310 total), each verified to fail against the previous code.

## [3.12.1] — 2026-08-19

### Fixed
- **Pinned `mcp[cli]` to `<2.0.0`.** The dependency was declared as `mcp[cli]>=1.0.0` with no upper bound. `mcp` 2.0.0 (released 2026-07-28) removed `mcp.server.fastmcp` entirely — `FastMCP` is replaced by a new `mcp.server.mcpserver` API — so `from mcp.server.fastmcp import FastMCP, Context` at `server.py:18` raises `ModuleNotFoundError` and every import of the server fails. Any environment that resolved dependencies fresh after that date (CI, a Docker rebuild, a new contributor's checkout) got a completely broken install, while existing environments with a stale lock kept working. Now bounded to the 1.x line, which resolves to 1.29.0.

### Notes
- Migrating to the `mcp` 2.x `mcpserver` API is separate, deliberate work — not something to absorb accidentally through an unbounded version range.
- Nothing else changed; `3.12.0` and `3.12.1` are functionally identical apart from the dependency bound. Use `3.12.1`.

## [3.12.0] — 2026-08-19

### Fixed
- **Auto-push reported success from configuration instead of outcome.** `_write_knowledge_doc()` rendered `Auto-pushed to remote: {cfg.git_auto_push and bool(cfg.git_repo_url)}` — an expression that evaluates whether auto-push is *enabled*, never whether the push *worked*. With both settings present it was permanently `True`. In one deployment this masked 2.5 months of rejected non-fast-forward pushes while 325 knowledge documents lived only inside the Docker volume. `push_pending()` now returns `{"status": "ok"|"noop"|"disabled"|"failed"|"blocked", "files": int, "error": str|None}` and the MCP layer renders that status. A failure reads **"Auto-push: FAILED — this doc is NOT on the remote"** with the git stderr attached.
- **Push failures were swallowed.** `push_pending()` caught every exception in a bare `except` that only called `diag()`, so no error could reach the MCP tool result — the correct value sat in `health.last_push_error` the whole time, one lookup away from the reporting code. Exceptions are now recorded to `HealthTracker` *and* returned to the caller.
- **A failing `git commit` aborted the push path via an unchecked `check=True`.** The commit result is now inspected and reported like any other failure.
- **`web.py` bootstrap-execute discarded the push result in a `try/except: pass`.** Both `web.py` write paths now include a `push` object in their JSON response.

### Added
- **Secret scanning on the write path (`MCP_GITLEAKS_MODE`).** Flaiwheel's commits are machine-generated and never human-reviewed, so gitleaks now runs against the *staged* changes in `_push_local_changes()` before the commit is created. This is deliberately not a git hook: hooks are per-clone, invisible, and lost on re-clone, whereas the knowledge repo is cloned by the container at runtime.
  - `block` (default) — refuse to commit, return `status: "blocked"` plus the findings (file, line, rule, description) through the same channel as every other result, so the calling agent can redact and retry.
  - `warn` — commit and push, surface findings in the result.
  - `off` — disable scanning.
  - Honours a `.gitleaks.toml` in the knowledge repo for allowlisting false positives.
  - Implemented by materialising the staged blobs to a temp dir and running `gitleaks dir`, **not** `gitleaks git --staged` — the latter reports "0 commits scanned" and finds nothing on freshly-staged files, which would have made this gate a permanent silent pass. That is precisely the failure mode this release exists to eliminate, so it is called out in the code.
  - **A missing or malfunctioning scanner is reported as `unavailable`, never treated as a pass.** The prior arrangement had gitleaks installed on the *host* while commits were created inside the container — genuinely installed and genuinely useless.
- **gitleaks 8.30.0 is installed in the runtime image** (amd64 + arm64), pinned via the `GITLEAKS_VERSION` build arg.
- **Secret scanning selector in the Web UI** under Git configuration.
- **`tests/test_watcher_push.py`** — 8 integration tests against real temp git repos: push ok/noop/disabled, a rejected push surfacing as `failed` with health recorded, gitleaks block (asserting nothing was committed), warn, clean, and unavailable-scanner visibility. The gitleaks cases skip when the binary is absent.

### Notes
- Backwards-compatible for anyone reading the human-readable tool output. If you *parse* the `Auto-pushed to remote: True` line, it is now `Auto-push: ok (N file(s) pushed to remote)`.
- Existing installs get `block` mode by default. If your knowledge repo contains content that trips gitleaks, either allowlist it in `.gitleaks.toml` or set `MCP_GITLEAKS_MODE=warn`.
- Still open from the same incident and **not** addressed here: explicit divergence detection (`git rev-list --count @{u}..HEAD`), a consecutive-push-failure counter with escalation, and watcher path scoping across multiple project repos.

## [3.11.0] — 2026-05-22

### Added
- **Two-tier telemetry persistence with cold-start recovery** — per-project summary counters are now mirrored from the Docker volume into each knowledge repo at `<docs_path>/.flaiwheel/telemetry.json`. After `docker volume rm flaiwheel-data` (or a brand-new Docker host), `hydrate_from_mirrors()` reconstructs the in-memory summary from these per-project files on the next start, so dashboards do not reset to zero. The hot tier remains authoritative when both exist; mirrors only fill gaps. Mirror writes are rate-limited (60s/project) so we don't churn one Git commit per tool call. Events (`events.jsonl`) intentionally stay in the volume only — too noisy for the knowledge repo.
- **Reset Telemetry button on each per-project tile** — zeroes a single project's summary counters across both storage tiers (hot tier + mirror). Wired to a new `POST /api/telemetry/reset?project=<name>` endpoint and a `mcp.reset_project_telemetry()` server hook. Event history is preserved so the rolling 30-day impact metrics remain reproducible after a reset.
- **"Structured Relations Workflow" section** added to `AGENTS.md` and to both install.sh agent-instruction templates. Three concrete rules teach agents how to populate `fixes` / `replaces` / `depends_on` and when to flip `status: superseded` — without this, agents would never know the v3.10.x graph-edge mechanics exist.
- **9 new tests in `tests/test_telemetry.py`** covering mirror writes, rate limiting, cold-start hydration, hot-tier authority, reset semantics, and edge cases (unknown project, empty name).

### Changed
- **Client Configuration → "VS Code" tab renamed to "VS Code + Copilot"** with explicit help text mentioning GitHub Copilot agent mode and the `MCP: List Servers` Command Palette verification. The `.vscode/mcp.json` config file Flaiwheel emits is the same file Copilot reads — no separate snippet needed. (No tab added; the existing one was just under-labelled.)
- **`indexer._iter_docs`, `quality._check_*`, `bootstrap._scan_files`** now skip any path component starting with `.flaiwheel`, so the new mirror file (and any future internal metadata) never pollutes the index, quality report, or codebase-bootstrap output.

### Notes
- The mirror file lives **inside** the knowledge repo by design — that repo is the part the user already version-controls and (typically) backs up off-host, so persistence comes for free. If you don't want telemetry committed, add `.flaiwheel/` to your knowledge repo's `.gitignore`; Flaiwheel will still read/write the local file but `push_pending` will skip it.
- Fully backwards-compatible. Existing installs continue to work; mirror files materialise organically on the next save and hydrate on the next cold start.

## [3.10.1] — 2026-05-22

### Added
- **Auto-emit frontmatter from every structured writer** — `write_bugfix_summary`, `write_architecture_doc`, `write_api_doc`, `write_best_practice`, `write_setup_doc`, `write_changelog_entry`, and `write_test_case` now prepend a canonical YAML frontmatter block (id, type, status=active, empty relation lists) to every new doc. Every newly written knowledge doc becomes a graph node automatically — no manual edits, no agent ceremony.
- **`flaiwheel.frontmatter.emit()`** — deterministic, ordered renderer used by all writers. Stable diffs when a same-day doc is overwritten.
- **8 new tests in `TestFrontmatterAutoEmission`** — one per writer plus an end-to-end `relations()` round-trip that confirms inbound-edge resolution between two writer-created docs.

### Notes
- Entity IDs are derived from the existing filename slug (`adr-YYYY-MM-DD-<slug>`, `bugfix-YYYY-MM-DD-<slug>`, `api-<slug>`, `best-practice-<slug>`, `setup-<slug>`, `changelog-<version-slug>`, `test-YYYY-MM-DD-<slug>`). Stable, predictable, never reused.
- Writers still don't accept explicit `replaces` / `depends_on` arguments — that is a separate, opt-in API and intentionally not part of this minor. To declare a relation today, edit the emitted frontmatter directly or write the doc manually.
- Fully backwards-compatible. Existing docs without frontmatter continue to work; they just don't become graph nodes until they're rewritten.

## [3.10.0] — 2026-05-22

### Added

- **Structured relations (v1)** — two new MCP tools, `relations(entity_id)` and `timeline(entity_id)`, derive a project-scoped knowledge graph from YAML frontmatter on existing markdown docs. No new persistent store, no `graph_add`/`invalidate` writes — markdown stays the single source of truth and Git history is the validity window. Recognised relation keys: `replaces`, `depends_on`, `fixes`, `implements`; scalar keys: `id`, `type`, `status`, `superseded_at`. See `.project/ROADMAP.md` → "Structured relations via frontmatter" for rationale.
- **`GitWatcher.log_for_file(rel_path, limit)`** — read-only helper returning newest-first commits for a file (`hash`, `author`, ISO `date`, `subject`). Backs the `timeline()` tool.
- **`flaiwheel.frontmatter`** — stdlib-only YAML subset parser for the small set of frontmatter keys Flaiwheel needs (scalars, flow lists, block lists). No new pip dependency.
- **`validate_doc()` frontmatter checks** — warns on unknown relation keys (info severity) and invalid `status` values (warning severity).

### Changed

- **Quality checks now strip frontmatter** before the heading-structure regex, so a leading `---`-fenced block does not confuse the "first heading is h1" check.

### Deferred

- The previously planned SQLite ER store (`graph_add` / `graph_invalidate` / `valid_from` / `valid_to` columns) is parked as v2, gated on a real query becoming measurably too slow on v1. AST-driven code↔symbol edges (v3) remain merged with backlog #13.

---

## [3.9.40] — 2026-05-13

### Fixed

- **Installer parallel job `claude-md`** — `claude mcp add` was invoked inside command substitution with `set -e`, so any non-zero exit aborted `_phase7c_claude` before the “already registered” handling. Output is now captured with `if OUT=$(claude …); then … else … fi` (errexit-safe), with broader “already registered” matching.
- **Installer `_FW_VERSION` vs GitHub CDN** — when online, the installer reads `version` from `main` `pyproject.toml` so Docker rebuild and fast-path version checks match the published release even when raw `install.sh` on `main` is briefly stale at the edge.

---

## [3.9.33] — 2026-03-25

### Fixed
- **Glama "Try in Browser" crash loop** — `entrypoint.sh` was printing banner text and downloading embedding models to stdout before launching Python. In stdio mode stdout is reserved for JSON-RPC; those prints corrupted the MCP stream causing Glama to crash and retrigger rebuilds. `entrypoint.sh` now detects `MCP_TRANSPORT=stdio` and immediately `exec`s `python -m flaiwheel`, skipping all stdout output and model downloads.

---

## [3.9.30] — 2026-03-25

### Fixed
- Internal tag (same fix as 3.9.33, superseded).

---

## [3.9.29] — 2026-03-23

### Fixed
- **Glama stdio crash** — `AuthManager` tried to write `/data/config.json` on first startup, crashing with `OSError: Read-only file system` before the MCP server could start. In `stdio_cold_start` mode, `AuthManager` is now skipped entirely (no Web-UI auth needed for stdio).
- **`config.save()` resilient to read-only `/data`** — wrapped in try/except so a read-only filesystem logs a warning instead of crashing.
- **Remaining 36 `print()` calls → `diag()`** — `watcher.py`, `indexer.py`, `readers.py`, and `bootstrap.py` still had `print()` on stdout. All diagnostics now go to stderr via `logutil.diag()`. Zero `print()` calls remain outside of `logutil.py`.

---

## [3.9.28] — 2026-03-22

### Fixed
- **MCP stdio / Glama "no tools detected"** — MCP over stdio uses **stdout exclusively for JSON-RPC**. All startup/bootstrap diagnostics now write to **stderr** via new `logutil.diag()`. Previously every `print()` on stdout corrupted the JSON-RPC stream so MCP clients (Glama Inspector, Claude) could not parse `tools/list` and reported zero tools.
- **stdio cold-start with empty Docker volume** — cold-start logic now also triggers when `/data` exists as an empty Docker volume with no `projects.json` and no docs (previously only skipped when `/data` was absent, so the full bootstrap always ran under Glama).

---

## [3.9.27] — 2026-03-21

### Changed
- **License file layout** — single canonical `LICENSE` (BSL 1.1) with full Additional Use Grant inline; removed `LICENSE.md` so GitHub Licensee no longer reports “Unknown, Unknown licenses” from dual files.
- **References** — all `LICENSE.md` pointers updated to `LICENSE` across README, `pyproject.toml`, Dockerfile, scripts, and source headers.

### Added
- **`[inspect]` optional dependency group** — lightweight deps for Glama MCP directory builds (no torch/CUDA pull); stdio cold-start skips heavy init when `/data` is absent.
- **`glama.json`**, **`SECURITY.md`**, root **`LICENSE`** — Glama listing and security disclosure.

### Fixed
- **stdio / Glama** — cold-start path for `MCP_TRANSPORT=stdio` without embedding bootstrap; lazy `chromadb` import in `__main__.py`.

---

## [3.9.26] — 2026-03-16

### Added
- **Claude Cowork skill** — installer now writes `.skills/skills/flaiwheel/SKILL.md` to the project directory. When the project is opened in Claude (Cowork), the Flaiwheel workflow skill is available automatically: session-start context restore, pre-coding knowledge search, mandatory post-bugfix documentation, and session-end summarisation — all without manual configuration.
- `skills/flaiwheel/SKILL.md` committed to the repo as the canonical skill source for reference and manual install.

---

## [3.9.25] — 2026-03-07

### Added
- **WSL2 pre-flight block** — automatic WSL2 detection + iptables-legacy switch + docker group membership + daemon start + ~/.bashrc auto-start. All WSL2 setup is now zero-touch.

---

## [3.9.24] — 2026-03-07

### Fixed
- **installer: auto-install python3 as prerequisite #0** — minimal WSL2/Linux systems may not have python3. Added pre-flight check with auto-install via apt/dnf/yum/pacman/brew before any python3 calls are made.

---

## [3.9.23] — 2026-03-07

### Fixed
- **installer: iptables-legacy + docker group on WSL2** — run `update-alternatives --set iptables /usr/sbin/iptables-legacy` before starting Docker. Add user to docker group via `usermod -aG docker`. Applied in both post-install and daemon-start blocks.
- **All displayed install commands use `bash <(curl ...)`** — error messages, generated AGENTS.md, Cursor rules, and Claude instructions all updated.

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
