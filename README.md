# Flaiwheel

> **Flywheel with AI, for AI.** A self-improving knowledge base that makes AI coding agents smarter with every bug fixed and every decision documented.

---

## What is Flaiwheel?

Flaiwheel is a self-contained Docker service that:
- **Indexes** your project documentation (`.md` files) into a vector database
- **Provides an MCP server** that AI agents (Cursor, Claude Code, VS Code Copilot) connect to
- **Searches semantically** — agents find relevant docs by meaning, not keywords
- **Learns from bugfixes** — agents write bugfix summaries that are instantly indexed
- **Auto-syncs via Git** — pulls AND pushes to a dedicated knowledge repo
- **Includes a Web UI** for configuration, monitoring, and testing

The flywheel effect: **every bug fixed makes the next bug cheaper to fix**. Knowledge compounds.

---

## Quick Start — One Command (recommended)

**Prerequisites:** [GitHub CLI](https://cli.github.com) authenticated (`gh auth login`), [Docker](https://docs.docker.com/get-docker/) running.

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

**After install:** restart Cursor. If you have existing docs, tell the AI: *"migrate docs"*.

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

### 2. Start Flaiwheel

```bash
docker run -d \
  --name flaiwheel \
  -p 8080:8080 \
  -p 8081:8081 \
  -e MCP_GIT_REPO_URL=https://github.com/you/yourproject-knowledge.git \
  -e MCP_GIT_TOKEN=ghp_your_token \
  -v flaiwheel-data:/data \
  ghcr.io/dl4rce/flaiwheel:latest
```

### 3. Connect your AI agent

Add to `.cursor/mcp.json` (or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "flaiwheel": {
      "url": "http://localhost:8081/sse"
    }
  }
}
```

### 4. Done. Start coding.

</details>

Your AI agent now has access to these MCP tools:
- `search_docs` — search all documentation before writing code
- `search_bugfixes` — learn from past bugs before fixing new ones
- `write_bugfix_summary` — document fixes (auto-pushed to knowledge repo)
- `check_knowledge_quality` — validate knowledge base consistency
- `reindex` — manual re-index after bulk changes

---

## For AI Agents — READ THIS SECTION

**If you are an AI agent (Cursor, Claude Code, Copilot) connected to this MCP server, follow these rules:**

### Before writing or changing code:
1. **ALWAYS** call `search_docs("what you're about to change")` first
2. Call `search_bugfixes("the problem you're solving")` to check for similar past issues
3. Prefer 2-3 targeted searches over one vague query

### After fixing a bug:
1. **ALWAYS** call `write_bugfix_summary()` with:
   - Clear title describing the bug
   - Technical root cause
   - What was changed to fix it
   - What should be done differently next time
2. This is **mandatory** — it builds the knowledge base for future agents

### Periodically:
1. Call `check_knowledge_quality()` to find issues in the knowledge base
2. Fix critical issues immediately (missing sections in bugfix entries, empty files)
3. Suggest improvements for warnings and info-level issues

### What you have access to:
| Tool | Purpose |
|------|---------|
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search only bugfix summaries |
| `search_by_type(query, doc_type, top_k)` | Filter by: docs, bugfix, best-practice, api, architecture, changelog, setup, readme |
| `write_bugfix_summary(title, root_cause, solution, lesson_learned, affected_files, tags)` | Document a bugfix and index immediately |
| `get_index_stats()` | Show index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base consistency |

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
└── changelog/             ← release notes
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

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Docker Container (single process)                    │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │  Web-UI (FastAPI)                   Port 8080   │ │
│  │  Config, monitoring, test search, quality check  │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │ shared state                   │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  MCP Server (FastMCP)               Port 8081   │ │
│  │  search_docs, write_bugfix_summary, etc.         │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  Indexer + ChromaDB (embedded, persistent)       │ │
│  │  Markdown chunking → vector embeddings           │ │
│  └──────────────────┬──────────────────────────────┘ │
│                      │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  Git Watcher (background thread)                 │ │
│  │  Auto pull + push, reindex on changes            │ │
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
- Index status and statistics
- Embedding model selection (visual picker)
- Chunking strategy configuration
- Git sync settings (URL, branch, auto-push toggle)
- Test search interface
- Knowledge quality checker
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

**Proprietary — Non-commercial use only.**

This software is the property of **4rce.com Digital Technologies GmbH**.

- Personal, non-commercial use is permitted
- **Commercial use requires a separate license**
- Contact: [info@4rce.com](mailto:info@4rce.com) | [https://4rce.com](https://4rce.com)

See [LICENSE.md](LICENSE.md) for full terms.
