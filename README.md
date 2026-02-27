# Flaiwheel

> **Flywheel with AI, for AI.** A self-improving knowledge base that makes AI coding agents smarter with every bug fixed and every decision documented.

---

## What is Flaiwheel?

Flaiwheel is a self-contained Docker service that:
- **Indexes** your project documentation (`.md` files) into a vector database
- **Provides an MCP server** that AI agents (Cursor, Claude Code, VS Code Copilot) connect to
- **Searches semantically** — agents find relevant docs by meaning, not keywords
- **Learns from bugfixes** — agents write bugfix summaries that are instantly indexed
- **Structured write tools** — 7 category-specific tools (bugfix, architecture, API, best-practice, setup, changelog, test case) that enforce quality at the source
- **Pre-commit validation** — `validate_doc()` checks freeform markdown before it enters the knowledge base
- **Ingest quality gate** — files with critical issues are automatically skipped during indexing (never deleted — you own your files)
- **Auto-syncs via Git** — pulls AND pushes to a dedicated knowledge repo
- **Tracks search metrics** — hit rate, miss rate, per-tool usage visible in the health panel
- **Proactive quality checks** — automatically validates knowledge base after every reindex
- **Includes a Web UI** for configuration, monitoring, and testing

The flywheel effect: **every bug fixed makes the next bug cheaper to fix**. Knowledge compounds.

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
4. Creates `.cursor/mcp.json` so Cursor connects to Flaiwheel
5. Creates `.cursor/rules/flaiwheel.mdc` so the AI knows how to use the tools
6. If existing `.md` docs are found, creates a migration guide — the AI will offer to organize them into the knowledge repo

**After install:**

1. Restart Cursor
2. Go to **Cursor Settings → MCP** and verify that `flaiwheel` appears in the server list
3. If the toggle next to `flaiwheel` is off, **enable it manually**
4. Wait for the green "connected" indicator

Once connected, the AI has access to all Flaiwheel tools. If you have existing docs, tell the AI: *"migrate docs"*.

---

## Updating

Run the same install command again from your project directory:

```bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
```

The installer detects the existing container, asks for confirmation, then:
- Rebuilds the Docker image with the latest code
- Recreates the container (preserves your data volume + config)
- Refreshes Cursor rules and agent guides

Your knowledge base, index, and credentials are preserved — only the code is updated.

---

## Quick Start — Manual Setup

<details>
<summary>Click to expand manual steps</summary>

### 1. Create a knowledge repo

```bash
# On GitHub, create: <your-project>-knowledge (private repo)
# Add initial structure:
mkdir -p architecture api bugfix-log best-practices setup changelog
echo "# Project Knowledge Base" > README.md
git add -A && git commit -m "init" && git push
```

### 2. Build and start Flaiwheel

```bash
# Clone and build
git clone https://github.com/dl4rce/flaiwheel.git /tmp/flaiwheel-build
docker build -t flaiwheel:latest /tmp/flaiwheel-build
rm -rf /tmp/flaiwheel-build

# Run
docker run -d \
  --name flaiwheel \
  -p 8080:8080 \
  -p 8081:8081 \
  -e MCP_GIT_REPO_URL=https://github.com/you/yourproject-knowledge.git \
  -e MCP_GIT_TOKEN=ghp_your_token \
  -v flaiwheel-data:/data \
  flaiwheel:latest
```

### 3. Connect your AI agent

Add to `.cursor/mcp.json` (or `claude_desktop_config.json`):

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

### 4. Done. Start coding.

</details>

Your AI agent now has access to these MCP tools:
- `search_docs` — semantic search across all documentation
- `search_bugfixes` — search bugfix summaries for past issues
- `search_by_type` — search filtered by category (architecture, api, bugfix, best-practice, setup, changelog, test)
- `write_bugfix_summary` — document fixes (auto-pushed to knowledge repo)
- `write_architecture_doc` — document architecture decisions
- `write_api_doc` — document API endpoints
- `write_best_practice` — document coding standards/patterns
- `write_setup_doc` — document setup/deployment procedures
- `write_changelog_entry` — document release notes
- `write_test_case` — document test cases (scenario, steps, expected result)
- `search_tests` — search test cases for existing coverage and patterns
- `validate_doc` — validate markdown before committing
- `git_pull_reindex` — pull latest from knowledge repo + re-index
- `get_index_stats` — show index statistics
- `reindex` — manual re-index after bulk changes
- `check_knowledge_quality` — validate knowledge base consistency
- `check_update` — check if a newer Flaiwheel version is available

---

## For AI Agents — YOUR FIRST STOP

**If you are an AI agent (Cursor, Claude Code, Copilot) connected to this MCP server:**

Flaiwheel is your **primary knowledge source** for this project. It contains architecture decisions, API documentation, past bugfixes with root causes, best practices, setup guides, and changelogs — things the source code alone cannot tell you.

### Knowledge Repo Location

The knowledge base lives in a **separate Git repo**: `<your-project>-knowledge` (private, on GitHub).
Flaiwheel clones it into a Docker container and serves it via MCP.

**DO NOT** access, read, or modify files inside the Docker container. Use MCP tools to search.
To add/update docs: commit and push to the knowledge repo, then call `git_pull_reindex()`.

### Step 1: Flaiwheel — Step 2: Native tools

For every task, follow this order:
1. **FIRST → Search Flaiwheel** for context, code understanding, architecture, past bugs, best practices
2. **THEN → Use your native tools** (file search, code reading, grep) for source code details

### Before writing or changing code:
1. **ALWAYS** call `search_docs("what you're about to change")` first — check for architecture decisions, patterns, constraints
2. Call `search_bugfixes("the problem you're solving")` — past issues, known pitfalls
3. Use `search_by_type("query", "architecture")` for targeted searches
4. Prefer 2-3 targeted searches over one vague query
5. THEN use your native file search/code reading for source code details

### Documenting knowledge (use structured write tools):
Instead of writing raw markdown, use the built-in write tools — they enforce correct structure, place files in the right directory, index immediately, and auto-push:
- `write_bugfix_summary()` — after every bugfix (**mandatory**)
- `write_architecture_doc()` — architecture decisions, system design
- `write_api_doc()` — API endpoints, contracts, schemas
- `write_best_practice()` — coding standards, patterns
- `write_setup_doc()` — setup, deployment, infrastructure
- `write_changelog_entry()` — release notes
- `write_test_case()` — test scenarios, steps, expected results
- `search_tests()` — find existing test cases and coverage

For freeform docs not covered by these tools: call `validate_doc(content, category)` before committing to catch quality issues early.

**Important:** Files that fail critical quality checks are skipped during indexing (not searchable). Flaiwheel never deletes or modifies your files — you own cleanup.

### After committing new/updated docs to the knowledge repo:
1. Push your changes to the `<project>-knowledge` repo
2. Call `git_pull_reindex()` so Flaiwheel pulls and indexes them immediately

### Updating Flaiwheel:
To update Flaiwheel to the latest version, tell the user to run this in their project directory:
```bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
```
You can also call `check_update()` to check if a newer version is available (works when the Flaiwheel repo is public).

### Periodically:
1. Call `check_knowledge_quality()` to find issues in the knowledge base
2. Fix critical issues immediately

### What the knowledge base contains:
| Category | Search with | What you'll find |
|----------|-------------|-----------------|
| `architecture` | `search_by_type("q", "architecture")` | System design, trade-offs, decisions |
| `api` | `search_by_type("q", "api")` | Endpoints, contracts, schemas |
| `bugfix` | `search_bugfixes("q")` | Root causes, solutions, lessons learned |
| `best-practice` | `search_by_type("q", "best-practice")` | Coding standards, patterns |
| `setup` | `search_by_type("q", "setup")` | Deployment, infrastructure, CI/CD |
| `changelog` | `search_by_type("q", "changelog")` | Release notes, breaking changes |
| `test` | `search_tests("q")` | Test cases, scenarios, regression patterns |
| _everything_ | `search_docs("q")` | Semantic search across all docs |

### All MCP tools:
| Tool | Purpose |
|------|---------|
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search only bugfix summaries |
| `search_by_type(query, doc_type, top_k)` | Filter by type |
| `write_bugfix_summary(title, root_cause, solution, ...)` | Document a bugfix (auto-pushed + reindexed) |
| `write_architecture_doc(title, overview, decisions, trade_offs, ...)` | Document architecture decisions |
| `write_api_doc(title, endpoint, method, request_schema, response_schema, ...)` | Document API endpoints |
| `write_best_practice(title, context, rule, rationale, ...)` | Document coding standards |
| `write_setup_doc(title, prerequisites, steps, verification, ...)` | Document setup/deployment |
| `write_changelog_entry(version, release_date, added, changed, fixed, breaking)` | Document release notes |
| `write_test_case(title, scenario, steps, expected_result, ...)` | Document test cases (auto-pushed + reindexed) |
| `search_tests(query, top_k)` | Search test cases for coverage and patterns |
| `validate_doc(content, category)` | Validate markdown before committing |
| `git_pull_reindex()` | Pull latest from knowledge repo + re-index |
| `get_index_stats()` | Show index statistics |
| `reindex(force=False)` | Re-index docs (diff-aware; force=True for full rebuild) |
| `check_knowledge_quality()` | Validate knowledge base consistency |
| `check_update()` | Check if a newer Flaiwheel version is available |

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

## Configuration

All config via environment variables (`MCP_` prefix), Web UI (http://localhost:8080), or `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DOCS_PATH` | `/docs` | Path to .md files inside container |
| `MCP_EMBEDDING_PROVIDER` | `local` | `local` (free, private) or `openai` |
| `MCP_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model name |
| `MCP_CHUNK_STRATEGY` | `heading` | `heading`, `fixed`, or `hybrid` |
| `MCP_GIT_REPO_URL` | | Knowledge repo URL (enables git sync) |
| `MCP_GIT_BRANCH` | `main` | Branch to sync |
| `MCP_GIT_TOKEN` | | GitHub token for private repos |
| `MCP_GIT_SYNC_INTERVAL` | `300` | Pull interval in seconds (0 = disabled) |
| `MCP_GIT_AUTO_PUSH` | `true` | Auto-commit + push bugfix summaries |
| `MCP_WEBHOOK_SECRET` | | GitHub webhook secret (enables `/webhook/github` HMAC verification) |
| `MCP_TRANSPORT` | `sse` | MCP transport: `sse` or `stdio` |
| `MCP_SSE_PORT` | `8081` | MCP SSE endpoint port |
| `MCP_WEB_PORT` | `8080` | Web UI port |

### Embedding Models (local, free)

| Model | RAM | Quality | Best for |
|-------|-----|---------|----------|
| `all-MiniLM-L6-v2` | 90MB | 78% | Large repos, low RAM |
| `nomic-ai/nomic-embed-text-v1.5` | 520MB | 87% | Best English quality |
| `BAAI/bge-m3` | 2.2GB | 86% | Multilingual (DE/EN) |

Select via Web UI or `MCP_EMBEDDING_MODEL` env var. Full list in the Web UI.

### GitHub Webhook (instant reindex)

Instead of waiting for the 300s polling interval, configure a GitHub webhook for instant reindex on push:

1. In your knowledge repo on GitHub: **Settings → Webhooks → Add webhook**
2. **Payload URL:** `http://your-server:8080/webhook/github`
3. **Content type:** `application/json`
4. **Secret:** set the same value as `MCP_WEBHOOK_SECRET`
5. **Events:** select "Just the push event"

The webhook endpoint verifies the HMAC signature if `MCP_WEBHOOK_SECRET` is set. Without a secret, any POST triggers a pull + reindex.

### Diff-aware Reindexing

Reindexing is incremental by default — only files whose content changed since the last run are re-embedded. On a 500-file repo, this means a typical reindex after a single-file push takes <1s instead of re-embedding everything.

Use `reindex(force=True)` via MCP or the Web UI "Reindex" button to force a full rebuild (e.g. after changing the embedding model).

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Docker Container (single process)                    │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │  Web-UI (FastAPI)                   Port 8080   │ │
│  │  Config, monitoring, test search, health panel   │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │ shared state                   │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  MCP Server (FastMCP)               Port 8081   │ │
│  │  15 tools: search, write, validate, manage       │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  Quality Checker + Ingest Gate                   │ │
│  │  Validates docs, skips critical failures         │ │
│  │  (never deletes or modifies user files)          │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  Indexer + ChromaDB (embedded, persistent)       │ │
│  │  Markdown chunking → vector embeddings           │ │
│  │  Diff-aware: only re-embeds changed files        │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  Git Watcher (background thread)                 │ │
│  │  Auto pull + push, reindex on changes            │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  Health Tracker (thread-safe)                    │ │
│  │  Index, git, search metrics, quality, skipped    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  /docs (volume) ← knowledge repo                     │
│  /data (volume) ← vector index + config              │
└──────────────────────────────────────────────────────┘
```

---

## Web UI

Access at **http://localhost:8080** (HTTP Basic Auth — credentials shown on first start).

Features:
- System health panel: last index, last git pull, git commit, version, search metrics, quality score, skipped files count
- Index status and statistics
- Embedding model selection (visual picker)
- Chunking strategy configuration
- Git sync settings (URL, branch, auto-push toggle)
- Test search interface
- Knowledge quality checker (also runs automatically after every reindex)
- Search metrics (hits/total, miss rate, per-tool breakdown)
- Skipped files indicator (files excluded from indexing due to critical quality issues)
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

See [LICENSE.md](LICENSE.md) for full terms.
