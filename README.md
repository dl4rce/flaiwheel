# Flaiwheel

> Self-hosted memory & governance layer for AI coding agents.
> Turn every bug fix into permanent knowledge. Zero cloud. Zero lock-in.

## 🚀 Why Flaiwheel Exists

AI coding agents forget everything between sessions.
That leads to repeated bugs, lost architectural decisions, and knowledge decay.

Flaiwheel ensures:
- Agents search before coding
- Agents document after fixing
- Commits automatically capture knowledge
- Memory compounds over time

**Every bug fixed makes the next bug cheaper.**

## 🧠 How Flaiwheel Is Different

- **Persistent AI Memory That Compounds** — knowledge doesn't reset between sessions.
- **Git-Native Automation** — commits automatically become structured knowledge.
- **Governance, Not Just Storage** — quality gates + enforced documentation.
- **Hybrid Search + Reranking** — high-precision context for real codebases.
- **Fully Self-Hosted** — single Docker container, no external infrastructure.
- **Zero Lock-In** — all knowledge stored as structured flat files in Git.

## ✅ Who Flaiwheel Is For

- Engineering teams using AI coding assistants in real projects
- Codebases where repeated bugs are expensive
- Teams requiring full data control
- AI-native development environments

## ❌ Not For

- Small hobby projects under a few thousand lines
- Developers who just want better autocomplete
- Pure SaaS workflows with no interest in self-hosting

## 🆚 Where Flaiwheel Fits

- AI coding tools generate code.
- RAG tools retrieve documents.
- **Flaiwheel governs and compounds structured engineering knowledge inside your own infrastructure.**

It does not replace your AI assistant. **It makes it reliable at scale.**

---

## ⚙️ Key Technical Features

Flaiwheel is a self-contained Docker service that operates on three levels:
**Pull** — agents search before they code (`search_docs`, `get_file_context`)  
**Push** — agents document as they work (`write_bugfix_summary`, `write_architecture_doc`, …)  
**Capture** — git commits auto-capture knowledge via a post-commit hook, even without an AI agent

- **Indexes** your project documentation (`.md`, `.pdf`, `.html`, `.docx`, `.rst`, `.txt`, `.json`, `.yaml`, `.csv`) into a vector database
- **Provides an MCP server** that AI agents (Cursor, Claude Code, VS Code Copilot) connect to
- **Hybrid search** — combines semantic vector search with BM25 keyword search via Reciprocal Rank Fusion (RRF) for best-of-both-worlds retrieval
- **Cross-encoder reranker** — optional reranking step that rescores candidates with a cross-encoder model for significantly higher precision on vocabulary-mismatch queries
- **Behavioral Directives** — AI agents silently search Flaiwheel before every response, auto-document after every task, and reuse before recreating — all without being asked
- **`get_file_context(filename)`** — pre-loads spatial knowledge for any file the agent is about to edit (complements `get_recent_sessions` for full temporal + spatial context)
- **post-commit git hook** — captures every `fix:`, `feat:`, `refactor:`, `perf:`, `docs:` commit as a structured knowledge doc automatically
- **Living Architecture** — AI agents are instructed to maintain self-updating Mermaid.js diagrams for system components and flows
- **Executable Test Flows** — test scenarios are documented in machine-readable BDD/Gherkin format (`Given`, `When`, `Then`) for QA automation
- **Learns from bugfixes** — agents write bugfix summaries that are instantly indexed
- **Structured write tools** — 7 category-specific tools (bugfix, architecture, API, best-practice, setup, changelog, test case) that enforce quality at the source
- **Pre-commit validation** — `validate_doc()` checks freeform markdown before it enters the knowledge base
- **Ingest quality gate** — files with critical issues are automatically skipped during indexing (never deleted — you own your files)
- **Auto-syncs via Git** — pulls AND pushes to a dedicated knowledge repo
- **Tool telemetry (persistent)** — tracks every MCP call per project (searches, writes, misses, patterns), detects knowledge gaps, and nudges agents to document — persisted across restarts and visible in the Web UI
- **Impact metrics API** — `/api/impact-metrics` computes estimated time saved + regressions avoided; CI pipelines can post guardrail outcomes to `/api/telemetry/ci-guardrail-report`
- **Proactive quality checks** — automatically validates knowledge base after every reindex
- **Knowledge Bootstrap** — "This is the Way": analyse messy repos, classify files, detect duplicates, propose a cleanup plan, execute with user approval (never deletes files)
- **Multi-project support** — one container manages multiple knowledge repos with per-project isolation
- **Includes a Web UI** for configuration, monitoring, and testing

---

## What’s New in v3.5.0

- **Claude Desktop support** — the installer auto-configures `~/Library/Application Support/Claude/claude_desktop_config.json` using `mcp-remote` as a stdio→SSE bridge. Claude for Mac connects to Flaiwheel out of the box — just restart the app after install.
- **Claude Code CLI support** — the installer auto-registers Flaiwheel via `claude mcp add` if the `claude` CLI is on PATH. Falls back with a prominent `ACTION REQUIRED` prompt if not.
- **`CLAUDE.md` + `.mcp.json`** — generated in the project root for Claude Code CLI. Includes a first-session MCP connection check that the agent enforces automatically.
- **`AGENTS.md`** — written to the project root for all other agents (GitHub Copilot, etc.).
- **One installer, all agents** — Cursor, Claude Desktop, Claude Code CLI all connected in a single `curl | bash`.

### Previous: v3.4.x
- Search miss rate fix — `search_bugfixes` calls no longer inflate miss rate above 100%.
- Classification consistency — `_path_category_hint` unified token-based approach across all categories.
- `CHANGELOG.md` added to repo root.
---

## Quick Start — One Command (recommended)

**Prerequisites:** [GitHub CLI](https://cli.github.com) authenticated (`gh auth login`), [Docker](https://docs.docker.com/get-docker/) running.

**Platform support:** macOS and Linux work out of the box. On **Windows**, run the installer from [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) or [Git Bash](https://gitforwindows.org/) (Docker Desktop must be running with WSL 2 backend enabled).

Run this from inside your project directory:

```bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
```

**That's it.** The installer automatically:

1. Detects your project name and GitHub org from the git remote
2. Creates a private `<project>-knowledge` repo with the standard folder structure
3. Starts the Flaiwheel Docker container pointed at that repo
4. Configures **Cursor** — writes `.cursor/mcp.json` and `.cursor/rules/flaiwheel.mdc`
5. Configures **Claude Desktop** (macOS app) — writes `claude_desktop_config.json` via `mcp-remote` bridge (requires Node.js)
6. Configures **Claude Code CLI** — writes `.mcp.json` + `CLAUDE.md` and runs `claude mcp add` automatically if the CLI is on PATH
7. Writes `AGENTS.md` for all other agents (GitHub Copilot, etc.)
8. If existing `.md` docs are found, creates a migration guide — the AI will offer to organize them into the knowledge repo

1. Agent scans the project directory for documentation files (`.md`, `.txt`, `.pdf`, `.html`, `.rst`, `.docx`)
2. Agent reads the first ~2000 chars of each file
3. **`classify_documents(files=JSON)`** — Flaiwheel classifies each file, detects duplicates, suggests target directories and write tools
4. **Review** — the agent presents the migration plan; you decide what to approve
5. Agent reads each approved file, restructures if needed, uses the suggested `write_*` tool
6. **`reindex()`** — finalize the knowledge base

### For EXISTING knowledge repos (files already inside, but messy):

1. **`analyze_knowledge_repo()`** — read-only scan of the knowledge repo
2. **Review** — the agent presents the report; you decide what to approve
3. **`execute_cleanup(actions)`** — executes only the actions you approved (creates directories, moves files via `git mv`)
4. **`reindex()`** — finalize

### How it works under the hood

The AI agent does the heavy lifting (local I/O, creative rewriting). Flaiwheel provides the **classification engine** — it embeds document content against category templates using cosine similarity, runs keyword-based classification as a second signal, and combines both with a three-way consensus (path hint + keywords + embedding). No LLM needed for classification.

**Hard rule:** Flaiwheel never deletes files. It classifies, moves, and suggests — you decide.

---

## Knowledge Repo Structure

```
yourproject-knowledge/
├── README.md              ← overview / index
├── architecture/          ← system design, decisions, diagrams
├── api/                   ← endpoint docs, contracts, schemas
├── bugfix-log/            ← auto-generated bugfix summaries
│   └── 2026-02-25-fix-payment-retry.md
├── best-practices/        ← coding standards, patterns
├── setup/                 ← deployment, environment setup
├── changelog/             ← release notes
└── tests/                 ← test cases, scenarios, regression patterns
```

---

## Supported Input Formats

Flaiwheel indexes 9 file formats. All non-markdown files are converted to markdown-like text in memory at index time — no generated files on disk, no repo clutter.

| Format | Extension(s) | How it works |
|--------|-------------|--------------|
| **Markdown** | `.md` | Native (pass-through) |
| **Plain text** | `.txt` | Wrapped in `# filename` heading |
| **PDF** | `.pdf` | Text extracted per page via `pypdf` |
| **HTML** | `.html`, `.htm` | Headings/lists/code converted to markdown, scripts stripped |
| **reStructuredText** | `.rst` | Heading underlines converted to `#` levels, code blocks preserved |
| **Word** | `.docx` | Paragraphs + heading styles mapped to markdown |
| **JSON** | `.json` | Pretty-printed in fenced `json` code block |
| **YAML** | `.yaml`, `.yml` | Wrapped in fenced `yaml` code block |
| **CSV** | `.csv` | Converted to markdown table |

Quality checks (structure, completeness, bugfix format) apply only to `.md` files. Other formats are indexed as-is.

---

## Configuration

All config via environment variables (`MCP_` prefix), Web UI (http://localhost:8080), or `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DOCS_PATH` | `/docs` | Path to .md files inside container |
| `MCP_EMBEDDING_PROVIDER` | `local` | `local` (free, private) or `openai` |
| `MCP_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model name |
| `MCP_CHUNK_STRATEGY` | `heading` | `heading`, `fixed`, or `hybrid` |
| `MCP_RERANKER_ENABLED` | `false` | Enable cross-encoder reranker for higher precision |
| `MCP_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker model name |
| `MCP_RRF_K` | `60` | RRF k parameter (lower = more weight on top ranks) |
| `MCP_RRF_VECTOR_WEIGHT` | `1.0` | Vector search weight in RRF fusion |
| `MCP_RRF_BM25_WEIGHT` | `1.0` | BM25 keyword search weight in RRF fusion |
| `MCP_MIN_RELEVANCE` | `0` | Minimum relevance % to return (0 = no filter) |
| `MCP_GIT_REPO_URL` | | Knowledge repo URL (enables git sync) |
| `MCP_GIT_BRANCH` | `main` | Branch to sync |
| `MCP_GIT_TOKEN` | | GitHub token for private repos |
| `MCP_GIT_SYNC_INTERVAL` | `300` | Pull interval in seconds (0 = disabled) |
| `MCP_GIT_AUTO_PUSH` | `true` | Auto-commit + push bugfix summaries |
| `MCP_WEBHOOK_SECRET` | | GitHub webhook secret (enables `/webhook/github` HMAC verification) |
| `MCP_TRANSPORT` | `sse` | MCP transport: `sse` or `stdio` |
| `MCP_SSE_PORT` | `8081` | MCP SSE endpoint port |
| `MCP_WEB_PORT` | `8080` | Web UI port |

### Multi-Repo Support

A single Flaiwheel container can manage multiple knowledge repositories — one per project. Each project gets its own ChromaDB collection, git watcher, index lock, health tracker, and quality checker, while sharing one embedding model in RAM and one MCP/Web endpoint.

**How it works:**
- The first `install.sh` run creates the Flaiwheel container with project A
- Subsequent `install.sh` runs from other project directories detect the running container and register the new project via the API — no additional containers
- All MCP tools accept an optional `project` parameter (e.g., `search_docs("query", project="my-app")`)
- Call `set_project("my-app")` at the start of every conversation to bind all subsequent calls to that project (sticky session)
- Without an explicit `project` parameter, the active project (set via `set_project`) is used; if none is set, the first project is used
- The Web UI has a project selector dropdown to switch between projects
- Use `list_projects()` via MCP to see all registered projects (shows active marker)

**Adding/removing projects:**
- **Via AI agent:** call `setup_project(name="my-app", git_repo_url="...")` — registers, clones, indexes, and auto-binds
- **Via install script:** run `install.sh` from a new project directory (auto-registers)
- **Via Web UI:** click "Add Project" in the project selector bar
- **Via API:** `POST /api/projects` with `{name, git_repo_url, git_branch, git_token}`
- **Remove:** `DELETE /api/projects/{name}` or the "Remove" button in the Web UI

**Backward compatibility:** existing single-project setups continue to work without changes. If no `projects.json` exists but `MCP_GIT_REPO_URL` is set, Flaiwheel auto-creates a single project from the env vars.

### Embedding Model Hot-Swap

When you change the embedding model via the Web UI, Flaiwheel re-embeds all documents in the background using a shadow collection. Search remains fully available on the old model while the migration runs. Once complete, the new index atomically replaces the old one — zero downtime.

The Web UI shows a live progress bar with file count and percentage. You can cancel at any time.

### Embedding Models (local, free)

| Model | RAM | Quality | Best for |
|-------|-----|---------|----------|
| `all-MiniLM-L6-v2` | 90MB | 78% | Large repos, low RAM |
| `nomic-ai/nomic-embed-text-v1.5` | 520MB | 87% | Best English quality |
| `BAAI/bge-m3` | 2.2GB | 86% | Multilingual (DE/EN) |

Select via Web UI or `MCP_EMBEDDING_MODEL` env var. Full list in the Web UI.

### Cross-Encoder Reranker (optional)

The reranker is a second-stage model that rescores the top candidates from hybrid search. It reads the full `(query, document)` pair together, which produces much more accurate relevance scores than independent embeddings — especially for vocabulary-mismatch queries where the user and the document use different words for the same concept.

**How it works:**
1. Hybrid search (vector + BM25) retrieves a wider candidate pool (`top_k × 5`)
2. RRF merges and ranks the candidates
3. The cross-encoder rescores the top candidates and returns only the best `top_k`

**Enable via Web UI** (Search & Retrieval card) or environment variable:
```bash
docker run -d \
  -e MCP_RERANKER_ENABLED=true \
  -e MCP_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 \
  ...
```

| Reranker Model | RAM | Speed | Quality |
|----------------|-----|-------|---------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 90MB | Fast | Good — best speed/quality balance |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | 130MB | Medium | Better — higher precision |
| `BAAI/bge-reranker-base` | 420MB | Slower | Best — state-of-the-art accuracy |

The reranker is **off by default** (zero overhead). When enabled, it adds ~50ms latency per search but typically improves precision by 10-25% on vocabulary-mismatch queries.

### GitHub Webhook (instant reindex)

Instead of waiting for the 300s polling interval, configure a GitHub webhook for instant reindex on push:

1. In your knowledge repo on GitHub: **Settings → Webhooks → Add webhook**
2. **Payload URL:** `http://your-server:8080/webhook/github`
3. **Content type:** `application/json`
4. **Secret:** set the same value as `MCP_WEBHOOK_SECRET`
5. **Events:** select "Just the push event"

The webhook endpoint verifies the HMAC signature if `MCP_WEBHOOK_SECRET` is set. Without a secret, any POST triggers a pull + reindex.

### CI Guardrail Telemetry (ROI tracking)

Track non-vanity engineering impact directly in Flaiwheel:

- **POST** `/api/telemetry/ci-guardrail-report` — CI reports guardrail findings/fixes per PR
- **GET** `/api/impact-metrics?project=<name>&days=30` — returns estimated time saved + regressions avoided

Example payload:

```json
{
  "project": "my-app",
  "violations_found": 4,
  "violations_blocking": 1,
  "violations_fixed_before_merge": 2,
  "cycle_time_baseline_minutes": 58,
  "cycle_time_actual_minutes": 43,
  "pr_number": 127,
  "branch": "feature/payment-fix",
  "commit_sha": "abc1234",
  "source": "github-actions"
}
```

Flaiwheel persists telemetry on disk (`<vectorstore>/telemetry`) so metrics survive container restarts and updates.

### Diff-aware Reindexing

Reindexing is incremental by default — only files whose content changed since the last run are re-embedded. On a 500-file repo, this means a typical reindex after a single-file push takes <1s instead of re-embedding everything.

Use `reindex(force=True)` via MCP or the Web UI "Reindex" button to force a full rebuild (e.g. after changing the embedding model).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Container (single process, N projects)               │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Web-UI (FastAPI)                        Port 8080    │  │
│  │  Project CRUD, config, monitoring, search, health     │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                         │ shared state (ProjectRegistry)     │
│  ┌─────────────────────┴─────────────────────────────────┐  │
│  │  MCP Server (FastMCP)                    Port 8081    │  │
│  │  27 tools (search, write, classify, manage, projects) │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                         │                                    │
│  ┌─────────────────────┴─────────────────────────────────┐  │
│  │  Shared Embedding Model (1× in RAM)                   │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                         │                                    │
│  ┌──────────────────────┴────────────────────────────────┐  │
│  │  Per-Project Contexts (isolated)                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │  Project A  │  │  Project B  │  │  Project C  │   │  │
│  │  │  collection │  │  collection │  │  collection │   │  │
│  │  │  watcher    │  │  watcher    │  │  watcher    │   │  │
│  │  │  lock       │  │  lock       │  │  lock       │   │  │
│  │  │  health     │  │  health     │  │  health     │   │  │
│  │  │  quality    │  │  quality    │  │  quality    │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  /docs/{project}/  ← per-project knowledge repos             │
│  /data/            ← shared vectorstore + config + projects  │
└─────────────────────────────────────────────────────────────┘
```

### Search Pipeline

```
query
  │
  ├──► Vector Search (ChromaDB/HNSW, cosine similarity)
  │         fetch top_k (or top_k×5 if reranker enabled)
  │
  ├──► BM25 Keyword Search (bm25s, English stopwords)
  │         fetch top_k (or top_k×5 if reranker enabled)
  │
  ├──► RRF Fusion (configurable k, vector/BM25 weights)
  │         merge + rank candidates
  │
  ├──► [optional] Cross-Encoder Reranker
  │         rescore (query, doc) pairs for higher precision
  │
  ├──► Min Relevance Filter (configurable threshold)
  │
  └──► Return top_k results with relevance scores
```

---

## Web UI

Access at **http://localhost:8080** (HTTP Basic Auth — credentials shown on first start).

Features:
- System health panel: last index, last git pull, git commit, version, search metrics, quality score, skipped files count
- Index status and statistics (including reranker status)
- Embedding model selection (visual picker)
- **Search & Retrieval tuning**: cross-encoder reranker toggle + model picker, RRF weights, minimum relevance threshold
- Chunking strategy configuration
- Git sync settings (URL, branch, auto-push toggle)
- Test search interface
- Knowledge quality checker (also runs automatically after every reindex)
- Search metrics (hits/total, miss rate, per-tool breakdown)
- Skipped files indicator (files excluded from indexing due to critical quality issues)
- **"This is the Way" — Knowledge Bootstrap**: agent-driven project classification + in-repo cleanup (Web UI shows guidance + advanced scan)
- Multi-project switcher (manage multiple repos from one instance)
- Client configuration snippets (Cursor, Claude Desktop, Docker)
- Password management

---

## Development

```bash
# Clone
git clone https://github.com/dl4rce/flaiwheel.git
cd flaiwheel

# Install
pip install -e ".[dev]"

# Run tests (230 tests covering readers, quality checker, indexer, reranker, health tracker, MCP tools, model migration, multi-project, bootstrap, classification, file-context)
pytest

# Run locally (needs /docs and /data directories)
mkdir -p /tmp/flaiwheel-docs /tmp/flaiwheel-data
MCP_DOCS_PATH=/tmp/flaiwheel-docs MCP_VECTORSTORE_PATH=/tmp/flaiwheel-data python -m flaiwheel
```

---

## License

**Business Source License 1.1 (BSL 1.1)**

Flaiwheel is source-available under the [Business Source License 1.1](https://mariadb.com/bsl11/).

**You may use Flaiwheel for free** if:
- Your use is **non-commercial** (personal, educational, no revenue), or
- Your organization has **no more than 10 individuals** using it

**Commercial use beyond these limits** (e.g., teams of 11+ or commercial deployment) requires a paid license.

- Effective **2030-02-25**, this version converts to **Apache License 2.0** (fully open source)
- Commercial licenses: [info@4rce.com](mailto:info@4rce.com) | [https://4rce.com](https://4rce.com)

See [LICENSE.md](LICENSE.md) for full terms.**After install:**

| Agent | What to do |
|-------|-----------|
| **Cursor** | Restart Cursor → Settings → MCP → enable `flaiwheel` toggle |
| **Claude Desktop** (macOS app) | Quit and reopen Claude for Mac — hammer icon appears when connected |
| **Claude Code CLI** | Already registered automatically — run `/mcp` inside Claude Code to verify |### 3. Connect your AI agent

**Cursor** — add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "flaiwheel": {
      "type": "sse",
      "url": "http://localhost:8081/sse"
    }
  }
}
```

**Claude Desktop** (macOS app) — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "flaiwheel": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8081/sse"]
    }
  }
}
```
Requires Node.js. Restart Claude for Mac after editing.

**Claude Code CLI** — run once in your project directory:
```bash
claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse
```

### 4. Done. Start coding. with AI, for AI.** A self-improving knowledge base that makes AI coding agents smarter with every bug fixed and every decision documented.

---

## What is Flaiwheel?

Flaiwheel is a self-contained Docker service that turns AI coding agents from amnesiac assistants into an always-learning engineering platform. It operates on three levels:

**Pull** — agents search before they code (`search_docs`, `get_file_context`)  
**Push** — agents document as they work (`write_bugfix_summary`, `write_architecture_doc`, …)  
**Capture** — git commits auto-capture knowledge via a post-commit hook, even without an AI agent

Features:
- **Indexes** your project documentation (`.md`, `.pdf`, `.html`, `.docx`, `.rst`, `.txt`, `.json`, `.yaml`, `.csv`) into a vector database
- **Provides an MCP server** that AI agents (Cursor, Claude Code, VS Code Copilot) connect to
- **Hybrid search** — combines semantic vector search with BM25 keyword search via Reciprocal Rank Fusion (RRF) for best-of-both-worlds retrieval
- **Cross-encoder reranker** — optional reranking step that rescores candidates with a cross-encoder model for significantly higher precision on vocabulary-mismatch queries (e.g. "auth bypass" finds "client-side auth flag")
- **Behavioral Directives** — AI agents silently search Flaiwheel before every response, auto-document after every task, and reuse before recreating — all without being asked
- **`get_file_context(filename)`** — pre-loads spatial knowledge for any file the agent is about to edit (complements `get_recent_sessions` for full temporal + spatial context)
- **post-commit git hook** — captures every `fix:`, `feat:`, `refactor:`, `perf:`, `docs:` commit as a structured knowledge doc automatically — no agent needed, IDE-agnostic, no credentials required (localhost trust)
- **Living Architecture** — AI agents are instructed to maintain self-updating Mermaid.js diagrams for system components and flows
- **Executable Test Flows** — test scenarios are documented in machine-readable BDD/Gherkin format (`Given`, `When`, `Then`) for QA automation
- **Learns from bugfixes** — agents write bugfix summaries that are instantly indexed
- **Structured write tools** — 7 category-specific tools (bugfix, architecture, API, best-practice, setup, changelog, test case) that enforce quality at the source
- **Pre-commit validation** — `validate_doc()` checks freeform markdown before it enters the knowledge base
- **Ingest quality gate** — files with critical issues are automatically skipped during indexing (never deleted — you own your files)
- **Auto-syncs via Git** — pulls AND pushes to a dedicated knowledge repo
- **Tool telemetry (persistent)** — tracks every MCP call per project (searches, writes, misses, patterns), detects knowledge gaps, and nudges agents to document — persisted across restarts and visible in the Web UI
- **Impact metrics API** — `/api/impact-metrics` computes estimated time saved + regressions avoided; CI pipelines can post guardrail outcomes to `/api/telemetry/ci-guardrail-report`
- **Proactive quality checks** — automatically validates knowledge base after every reindex
- **Knowledge Bootstrap** — "This is the Way": analyse messy repos, classify files, detect duplicates, propose a cleanup plan, execute with user approval (never deletes files)
- **Multi-project support** — one container manages multiple knowledge repos with per-project isolation
- **Includes a Web UI** for configuration, monitoring, and testing

The flywheel effect: **every bug fixed makes the next bug cheaper to fix**. Knowledge compounds.

---

## What’s New in v3.5.0

- **Claude Desktop support** — the installer auto-configures `~/Library/Application Support/Claude/claude_desktop_config.json` using `mcp-remote` as a stdio→SSE bridge. Claude for Mac connects to Flaiwheel out of the box — just restart the app after install.
- **Claude Code CLI support** — the installer auto-registers Flaiwheel via `claude mcp add` if the `claude` CLI is on PATH. Falls back with a prominent `ACTION REQUIRED` prompt if not.
- **`CLAUDE.md` + `.mcp.json`** — generated in the project root for Claude Code CLI. Includes a first-session MCP connection check that the agent enforces automatically.
- **`AGENTS.md`** — written to the project root for all other agents (GitHub Copilot, etc.).
- **One installer, all agents** — Cursor, Claude Desktop, Claude Code CLI all connected in a single `curl | bash`.

### Previous: v3.4.x
- Search miss rate fix — `search_bugfixes` calls no longer inflate miss rate above 100%.
- Classification consistency — `_path_category_hint` unified token-based approach across all categories.
- `CHANGELOG.md` added to repo root.
---

## Quick Start — One Command (recommended)

**Prerequisites:** [GitHub CLI](https://cli.github.com) authenticated (`gh auth login`), [Docker](https://docs.docker.com/get-docker/) running.

**Platform support:** macOS and Linux work out of the box. On **Windows**, run the installer from [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) or [Git Bash](https://gitforwindows.org/) (Docker Desktop must be running with WSL 2 backend enabled).

Run this from inside your project directory:

```bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
```

**That's it.** The installer automatically:

1. Detects your project name and GitHub org from the git remote
2. Creates a private `<project>-knowledge` repo with the standard folder structure
3. Starts the Flaiwheel Docker container pointed at that repo
4. Configures **Cursor** — writes `.cursor/mcp.json` and `.cursor/rules/flaiwheel.mdc`
5. Configures **Claude Desktop** (macOS app) — writes `claude_desktop_config.json` via `mcp-remote` bridge (requires Node.js)
6. Configures **Claude Code CLI** — writes `.mcp.json` + `CLAUDE.md` and runs `claude mcp add` automatically if the CLI is on PATH
7. Writes `AGENTS.md` for all other agents (GitHub Copilot, etc.)
8. If existing `.md` docs are found, creates a migration guide — the AI will offer to organize them into the knowledge repo

1. Agent scans the project directory for documentation files (`.md`, `.txt`, `.pdf`, `.html`, `.rst`, `.docx`)
2. Agent reads the first ~2000 chars of each file
3. **`classify_documents(files=JSON)`** — Flaiwheel classifies each file, detects duplicates, suggests target directories and write tools
4. **Review** — the agent presents the migration plan; you decide what to approve
5. Agent reads each approved file, restructures if needed, uses the suggested `write_*` tool
6. **`reindex()`** — finalize the knowledge base

### For EXISTING knowledge repos (files already inside, but messy):

1. **`analyze_knowledge_repo()`** — read-only scan of the knowledge repo
2. **Review** — the agent presents the report; you decide what to approve
3. **`execute_cleanup(actions)`** — executes only the actions you approved (creates directories, moves files via `git mv`)
4. **`reindex()`** — finalize

### How it works under the hood

The AI agent does the heavy lifting (local I/O, creative rewriting). Flaiwheel provides the **classification engine** — it embeds document content against category templates using cosine similarity, runs keyword-based classification as a second signal, and combines both with a three-way consensus (path hint + keywords + embedding). No LLM needed for classification.

**Hard rule:** Flaiwheel never deletes files. It classifies, moves, and suggests — you decide.

---

## Knowledge Repo Structure

```
yourproject-knowledge/
├── README.md              ← overview / index
├── architecture/          ← system design, decisions, diagrams
├── api/                   ← endpoint docs, contracts, schemas
├── bugfix-log/            ← auto-generated bugfix summaries
│   └── 2026-02-25-fix-payment-retry.md
├── best-practices/        ← coding standards, patterns
├── setup/                 ← deployment, environment setup
├── changelog/             ← release notes
└── tests/                 ← test cases, scenarios, regression patterns
```

---

## Supported Input Formats

Flaiwheel indexes 9 file formats. All non-markdown files are converted to markdown-like text in memory at index time — no generated files on disk, no repo clutter.

| Format | Extension(s) | How it works |
|--------|-------------|--------------|
| **Markdown** | `.md` | Native (pass-through) |
| **Plain text** | `.txt` | Wrapped in `# filename` heading |
| **PDF** | `.pdf` | Text extracted per page via `pypdf` |
| **HTML** | `.html`, `.htm` | Headings/lists/code converted to markdown, scripts stripped |
| **reStructuredText** | `.rst` | Heading underlines converted to `#` levels, code blocks preserved |
| **Word** | `.docx` | Paragraphs + heading styles mapped to markdown |
| **JSON** | `.json` | Pretty-printed in fenced `json` code block |
| **YAML** | `.yaml`, `.yml` | Wrapped in fenced `yaml` code block |
| **CSV** | `.csv` | Converted to markdown table |

Quality checks (structure, completeness, bugfix format) apply only to `.md` files. Other formats are indexed as-is.

---

## Configuration

All config via environment variables (`MCP_` prefix), Web UI (http://localhost:8080), or `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DOCS_PATH` | `/docs` | Path to .md files inside container |
| `MCP_EMBEDDING_PROVIDER` | `local` | `local` (free, private) or `openai` |
| `MCP_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model name |
| `MCP_CHUNK_STRATEGY` | `heading` | `heading`, `fixed`, or `hybrid` |
| `MCP_RERANKER_ENABLED` | `false` | Enable cross-encoder reranker for higher precision |
| `MCP_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker model name |
| `MCP_RRF_K` | `60` | RRF k parameter (lower = more weight on top ranks) |
| `MCP_RRF_VECTOR_WEIGHT` | `1.0` | Vector search weight in RRF fusion |
| `MCP_RRF_BM25_WEIGHT` | `1.0` | BM25 keyword search weight in RRF fusion |
| `MCP_MIN_RELEVANCE` | `0` | Minimum relevance % to return (0 = no filter) |
| `MCP_GIT_REPO_URL` | | Knowledge repo URL (enables git sync) |
| `MCP_GIT_BRANCH` | `main` | Branch to sync |
| `MCP_GIT_TOKEN` | | GitHub token for private repos |
| `MCP_GIT_SYNC_INTERVAL` | `300` | Pull interval in seconds (0 = disabled) |
| `MCP_GIT_AUTO_PUSH` | `true` | Auto-commit + push bugfix summaries |
| `MCP_WEBHOOK_SECRET` | | GitHub webhook secret (enables `/webhook/github` HMAC verification) |
| `MCP_TRANSPORT` | `sse` | MCP transport: `sse` or `stdio` |
| `MCP_SSE_PORT` | `8081` | MCP SSE endpoint port |
| `MCP_WEB_PORT` | `8080` | Web UI port |

### Multi-Repo Support

A single Flaiwheel container can manage multiple knowledge repositories — one per project. Each project gets its own ChromaDB collection, git watcher, index lock, health tracker, and quality checker, while sharing one embedding model in RAM and one MCP/Web endpoint.

**How it works:**
- The first `install.sh` run creates the Flaiwheel container with project A
- Subsequent `install.sh` runs from other project directories detect the running container and register the new project via the API — no additional containers
- All MCP tools accept an optional `project` parameter (e.g., `search_docs("query", project="my-app")`)
- Call `set_project("my-app")` at the start of every conversation to bind all subsequent calls to that project (sticky session)
- Without an explicit `project` parameter, the active project (set via `set_project`) is used; if none is set, the first project is used
- The Web UI has a project selector dropdown to switch between projects
- Use `list_projects()` via MCP to see all registered projects (shows active marker)

**Adding/removing projects:**
- **Via AI agent:** call `setup_project(name="my-app", git_repo_url="...")` — registers, clones, indexes, and auto-binds
- **Via install script:** run `install.sh` from a new project directory (auto-registers)
- **Via Web UI:** click "Add Project" in the project selector bar
- **Via API:** `POST /api/projects` with `{name, git_repo_url, git_branch, git_token}`
- **Remove:** `DELETE /api/projects/{name}` or the "Remove" button in the Web UI

**Backward compatibility:** existing single-project setups continue to work without changes. If no `projects.json` exists but `MCP_GIT_REPO_URL` is set, Flaiwheel auto-creates a single project from the env vars.

### Embedding Model Hot-Swap

When you change the embedding model via the Web UI, Flaiwheel re-embeds all documents in the background using a shadow collection. Search remains fully available on the old model while the migration runs. Once complete, the new index atomically replaces the old one — zero downtime.

The Web UI shows a live progress bar with file count and percentage. You can cancel at any time.

### Embedding Models (local, free)

| Model | RAM | Quality | Best for |
|-------|-----|---------|----------|
| `all-MiniLM-L6-v2` | 90MB | 78% | Large repos, low RAM |
| `nomic-ai/nomic-embed-text-v1.5` | 520MB | 87% | Best English quality |
| `BAAI/bge-m3` | 2.2GB | 86% | Multilingual (DE/EN) |

Select via Web UI or `MCP_EMBEDDING_MODEL` env var. Full list in the Web UI.

### Cross-Encoder Reranker (optional)

The reranker is a second-stage model that rescores the top candidates from hybrid search. It reads the full `(query, document)` pair together, which produces much more accurate relevance scores than independent embeddings — especially for vocabulary-mismatch queries where the user and the document use different words for the same concept.

**How it works:**
1. Hybrid search (vector + BM25) retrieves a wider candidate pool (`top_k × 5`)
2. RRF merges and ranks the candidates
3. The cross-encoder rescores the top candidates and returns only the best `top_k`

**Enable via Web UI** (Search & Retrieval card) or environment variable:
```bash
docker run -d \
  -e MCP_RERANKER_ENABLED=true \
  -e MCP_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 \
  ...
```

| Reranker Model | RAM | Speed | Quality |
|----------------|-----|-------|---------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 90MB | Fast | Good — best speed/quality balance |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | 130MB | Medium | Better — higher precision |
| `BAAI/bge-reranker-base` | 420MB | Slower | Best — state-of-the-art accuracy |

The reranker is **off by default** (zero overhead). When enabled, it adds ~50ms latency per search but typically improves precision by 10-25% on vocabulary-mismatch queries.

### GitHub Webhook (instant reindex)

Instead of waiting for the 300s polling interval, configure a GitHub webhook for instant reindex on push:

1. In your knowledge repo on GitHub: **Settings → Webhooks → Add webhook**
2. **Payload URL:** `http://your-server:8080/webhook/github`
3. **Content type:** `application/json`
4. **Secret:** set the same value as `MCP_WEBHOOK_SECRET`
5. **Events:** select "Just the push event"

The webhook endpoint verifies the HMAC signature if `MCP_WEBHOOK_SECRET` is set. Without a secret, any POST triggers a pull + reindex.

### CI Guardrail Telemetry (ROI tracking)

Track non-vanity engineering impact directly in Flaiwheel:

- **POST** `/api/telemetry/ci-guardrail-report` — CI reports guardrail findings/fixes per PR
- **GET** `/api/impact-metrics?project=<name>&days=30` — returns estimated time saved + regressions avoided

Example payload:

```json
{
  "project": "my-app",
  "violations_found": 4,
  "violations_blocking": 1,
  "violations_fixed_before_merge": 2,
  "cycle_time_baseline_minutes": 58,
  "cycle_time_actual_minutes": 43,
  "pr_number": 127,
  "branch": "feature/payment-fix",
  "commit_sha": "abc1234",
  "source": "github-actions"
}
```

Flaiwheel persists telemetry on disk (`<vectorstore>/telemetry`) so metrics survive container restarts and updates.

### Diff-aware Reindexing

Reindexing is incremental by default — only files whose content changed since the last run are re-embedded. On a 500-file repo, this means a typical reindex after a single-file push takes <1s instead of re-embedding everything.

Use `reindex(force=True)` via MCP or the Web UI "Reindex" button to force a full rebuild (e.g. after changing the embedding model).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Container (single process, N projects)               │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Web-UI (FastAPI)                        Port 8080    │  │
│  │  Project CRUD, config, monitoring, search, health     │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                         │ shared state (ProjectRegistry)     │
│  ┌─────────────────────┴─────────────────────────────────┐  │
│  │  MCP Server (FastMCP)                    Port 8081    │  │
│  │  27 tools (search, write, classify, manage, projects) │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                         │                                    │
│  ┌─────────────────────┴─────────────────────────────────┐  │
│  │  Shared Embedding Model (1× in RAM)                   │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                         │                                    │
│  ┌──────────────────────┴────────────────────────────────┐  │
│  │  Per-Project Contexts (isolated)                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │  Project A  │  │  Project B  │  │  Project C  │   │  │
│  │  │  collection │  │  collection │  │  collection │   │  │
│  │  │  watcher    │  │  watcher    │  │  watcher    │   │  │
│  │  │  lock       │  │  lock       │  │  lock       │   │  │
│  │  │  health     │  │  health     │  │  health     │   │  │
│  │  │  quality    │  │  quality    │  │  quality    │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  /docs/{project}/  ← per-project knowledge repos             │
│  /data/            ← shared vectorstore + config + projects  │
└─────────────────────────────────────────────────────────────┘
```

### Search Pipeline

```
query
  │
  ├──► Vector Search (ChromaDB/HNSW, cosine similarity)
  │         fetch top_k (or top_k×5 if reranker enabled)
  │
  ├──► BM25 Keyword Search (bm25s, English stopwords)
  │         fetch top_k (or top_k×5 if reranker enabled)
  │
  ├──► RRF Fusion (configurable k, vector/BM25 weights)
  │         merge + rank candidates
  │
  ├──► [optional] Cross-Encoder Reranker
  │         rescore (query, doc) pairs for higher precision
  │
  ├──► Min Relevance Filter (configurable threshold)
  │
  └──► Return top_k results with relevance scores
```

---

## Web UI

Access at **http://localhost:8080** (HTTP Basic Auth — credentials shown on first start).

Features:
- System health panel: last index, last git pull, git commit, version, search metrics, quality score, skipped files count
- Index status and statistics (including reranker status)
- Embedding model selection (visual picker)
- **Search & Retrieval tuning**: cross-encoder reranker toggle + model picker, RRF weights, minimum relevance threshold
- Chunking strategy configuration
- Git sync settings (URL, branch, auto-push toggle)
- Test search interface
- Knowledge quality checker (also runs automatically after every reindex)
- Search metrics (hits/total, miss rate, per-tool breakdown)
- Skipped files indicator (files excluded from indexing due to critical quality issues)
- **"This is the Way" — Knowledge Bootstrap**: agent-driven project classification + in-repo cleanup (Web UI shows guidance + advanced scan)
- Multi-project switcher (manage multiple repos from one instance)
- Client configuration snippets (Cursor, Claude Desktop, Docker)
- Password management

---

## Development

```bash
# Clone
git clone https://github.com/dl4rce/flaiwheel.git
cd flaiwheel

# Install
pip install -e ".[dev]"

# Run tests (230 tests covering readers, quality checker, indexer, reranker, health tracker, MCP tools, model migration, multi-project, bootstrap, classification, file-context)
pytest

# Run locally (needs /docs and /data directories)
mkdir -p /tmp/flaiwheel-docs /tmp/flaiwheel-data
MCP_DOCS_PATH=/tmp/flaiwheel-docs MCP_VECTORSTORE_PATH=/tmp/flaiwheel-data python -m flaiwheel
```

---

## License

**Business Source License 1.1 (BSL 1.1)**

Flaiwheel is source-available under the [Business Source License 1.1](https://mariadb.com/bsl11/).

**You may use Flaiwheel for free** if:
- Your use is **non-commercial** (personal, educational, no revenue), or
- Your organization has **no more than 10 individuals** using it

**Commercial use beyond these limits** (e.g., teams of 11+ or commercial deployment) requires a paid license.

- Effective **2030-02-25**, this version converts to **Apache License 2.0** (fully open source)
- Commercial licenses: [info@4rce.com](mailto:info@4rce.com) | [https://4rce.com](https://4rce.com)

See [LICENSE.md](LICENSE.md) for full terms.**After install:**

| Agent | What to do |
|-------|-----------|
| **Cursor** | Restart Cursor → Settings → MCP → enable `flaiwheel` toggle |
| **Claude Desktop** (macOS app) | Quit and reopen Claude for Mac — hammer icon appears when connected |
| **Claude Code CLI** | Already registered automatically — run `/mcp` inside Claude Code to verify |
