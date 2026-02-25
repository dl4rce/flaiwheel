# MCP Docs Vektor – Code Teil 6: Docker, Entrypoint & Projekt-Config

## `Dockerfile`

```dockerfile
FROM python:3.12-slim

# System-Dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python Dependencies zuerst (für Docker Layer Caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Embedding-Modell vorladen (damit erster Start schnell ist)
# Default: all-MiniLM-L6-v2 (22M params, ~90MB)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Source Code
COPY src/ src/
COPY scripts/ scripts/
RUN chmod +x scripts/*.sh

# Volumes
# /docs  = Deine Markdown-Dokumentation (mount oder git clone)
# /data  = Vektor-Index + Config (persistent!)
VOLUME ["/docs", "/data"]

# Default Environment
ENV MCP_DOCS_PATH=/docs \
    MCP_VECTORSTORE_PATH=/data/vectorstore \
    MCP_EMBEDDING_PROVIDER=local \
    MCP_EMBEDDING_MODEL=all-MiniLM-L6-v2 \
    MCP_CHUNK_STRATEGY=heading \
    MCP_TRANSPORT=sse \
    MCP_SSE_PORT=8081 \
    MCP_WEB_PORT=8080

# Ports
# 8080 = Web-UI
# 8081 = MCP SSE Transport
EXPOSE 8080 8081

# Health Check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/stats || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
```

* * *

## `scripts/entrypoint.sh`

```bash
#!/bin/bash
set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  🔍 MCP Docs Vector Server                  ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Docs:       ${MCP_DOCS_PATH}               "
echo "║  Embeddings: ${MCP_EMBEDDING_PROVIDER} (${MCP_EMBEDDING_MODEL})"
echo "║  Transport:  ${MCP_TRANSPORT}                "
echo "║  Web-UI:     http://0.0.0.0:${MCP_WEB_PORT} "
echo "║  MCP SSE:    http://0.0.0.0:${MCP_SSE_PORT} "
echo "╚══════════════════════════════════════════════╝"

# Verzeichnisse sicherstellen
mkdir -p /data/vectorstore

# Optional: Git Clone wenn URL gesetzt und /docs leer
if [ -n "${MCP_GIT_REPO_URL}" ] && [ ! "$(ls -A ${MCP_DOCS_PATH} 2>/dev/null)" ]; then
    echo ""
    echo "📥 Cloning ${MCP_GIT_REPO_URL} (branch: ${MCP_GIT_BRANCH:-main})..."
    
    CLONE_URL="${MCP_GIT_REPO_URL}"
    if [ -n "${MCP_GIT_TOKEN}" ]; then
        CLONE_URL=$(echo "${CLONE_URL}" | sed "s|https://|https://${MCP_GIT_TOKEN}@|")
    fi
    
    git clone \
        --branch "${MCP_GIT_BRANCH:-main}" \
        --single-branch \
        --depth 1 \
        "${CLONE_URL}" "${MCP_DOCS_PATH}"
    
    echo "✅ Clone abgeschlossen"
fi

# Starte Web-UI + MCP Server parallel
echo ""
echo "🚀 Starting services..."

# Web-UI im Hintergrund
python -m mcp_docs_vector.web &
WEB_PID=$!

# MCP Server im Vordergrund
python -m mcp_docs_vector.server &
MCP_PID=$!

echo "✅ Web-UI PID: ${WEB_PID}, MCP PID: ${MCP_PID}"

# Warte auf beide Prozesse
wait -n
exit $?
```

* * *

## `scripts/reindex.sh`

```bash
#!/bin/bash
# Manueller Reindex-Trigger via CLI
echo "🔄 Triggering reindex..."
curl -s -X POST http://localhost:8080/api/reindex | python -m json.tool
```

* * *

## `pyproject.toml`

```toml
[project]
name = "mcp-docs-vector"
version = "0.1.0"
description = "Self-contained MCP server with vector-indexed documentation search"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"

dependencies = [
    # MCP Server
    "mcp[cli]>=1.0.0",
    
    # Vektor-DB
    "chromadb>=0.5.0",
    
    # Lokale Embeddings
    "sentence-transformers>=3.0.0",
    
    # Web-UI
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    
    # Config
    "pydantic-settings>=2.0.0",
]

[project.optional-dependencies]
# Für OpenAI Embeddings (optional)
openai = ["openai>=1.0.0"]

# Für Entwicklung
dev = [
    "pytest>=8.0",
    "httpx>=0.27",  # Für FastAPI Tests
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_docs_vector"]
```

* * *

## `docker-compose.yml`

```yaml
version: "3.8"

services:
  mcp-docs:
    build: .
    # Oder vom Registry:
    # image: ghcr.io/dein-user/mcp-docs-vector:latest
    
    ports:
      - "${WEB_PORT:-8080}:8080"     # Web-UI
      - "${SSE_PORT:-8081}:8081"     # MCP SSE Transport
    
    volumes:
      # === OPTION A: Lokale Docs mounten ===
      - ${DOCS_PATH:-./example-docs}:/docs:ro
      
      # === Persistenter Index (überlebt Container-Restarts) ===
      - mcp-data:/data
    
    environment:
      # Embedding
      - MCP_EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER:-local}
      - MCP_EMBEDDING_MODEL=${EMBEDDING_MODEL:-all-MiniLM-L6-v2}
      
      # OpenAI (optional)
      - MCP_OPENAI_API_KEY=${OPENAI_API_KEY:-}
      
      # Git (optional, alternativ zu Volume-Mount)
      - MCP_GIT_REPO_URL=${GIT_REPO_URL:-}
      - MCP_GIT_BRANCH=${GIT_BRANCH:-main}
      - MCP_GIT_SYNC_INTERVAL=${GIT_SYNC_INTERVAL:-300}
      - MCP_GIT_TOKEN=${GIT_TOKEN:-}
      
      # Chunking
      - MCP_CHUNK_STRATEGY=${CHUNK_STRATEGY:-heading}
      
      # Transport
      - MCP_TRANSPORT=sse
    
    restart: unless-stopped
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/stats"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  mcp-data:
    name: mcp-docs-vectorstore
```

* * *

## `.env.example`

```env
# ╔══════════════════════════════════════════════════════╗
# ║  MCP Docs Vector – Konfiguration                    ║
# ╚══════════════════════════════════════════════════════╝

# ── Dokumentation ────────────────────────────────────
# Pfad zu deinen .md Dateien (für Volume-Mount)
DOCS_PATH=./my-project/docs

# ── ODER: Git Repo (wird automatisch geklont) ────────
# GIT_REPO_URL=https://github.com/your-team/docs.git
# GIT_BRANCH=main
# GIT_SYNC_INTERVAL=300    # Sekunden (0 = aus)
# GIT_TOKEN=ghp_xxx        # Für private Repos

# ── Embedding Modell ─────────────────────────────────
# "local" = kostenlos, läuft lokal im Container
# "openai" = besser, braucht API-Key
EMBEDDING_PROVIDER=local

# Lokale Modelle (wählbar in Web-UI):
#   all-MiniLM-L6-v2              → ⚡ Schnell, 90MB RAM
#   all-MiniLM-L12-v2             → Ausgewogen
#   all-mpnet-base-v2             → Gut, 420MB RAM
#   BAAI/bge-base-en-v1.5         → Sehr gut EN, 420MB
#   nomic-ai/nomic-embed-text-v1.5 → 🏆 Beste Qualität, 520MB
#   intfloat/multilingual-e5-base  → 🌍 Mehrsprachig, 1.1GB
#   BAAI/bge-m3                    → 🌍 Bestes Multilingual, 2.2GB
EMBEDDING_MODEL=all-MiniLM-L6-v2

# OpenAI (nur wenn EMBEDDING_PROVIDER=openai)
# OPENAI_API_KEY=sk-...

# ── Chunking ─────────────────────────────────────────
# heading = Split an ## Headings (empfohlen)
# fixed   = Feste Größe mit Overlap
# hybrid  = Heading + Unterteilen bei zu großen Chunks
CHUNK_STRATEGY=heading

# ── Ports ────────────────────────────────────────────
WEB_PORT=8080     # Web-UI
SSE_PORT=8081     # MCP SSE Endpoint
```

* * *

## `src/mcp_docs_vector/__init__.py`

```python
"""MCP Docs Vector – Self-contained vector-indexed documentation search."""
__version__ = "0.1.0"
```

* * *

## `src/mcp_docs_vector/__main__.py`

```python
"""Ermöglicht `python -m mcp_docs_vector`"""
import sys
import threading
from .config import Config
from .web import run_web
from .server import run_mcp

def main():
    config = Config.load()
    
    # Web-UI in eigenem Thread
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    
    # MCP Server im Main Thread
    run_mcp()

if __name__ == "__main__":
    main()
```

* * *

## `examples/cursor-mcp.json`

```json
{
  "mcpServers": {
    "project-docs": {
      "url": "http://localhost:8081/sse"
    }
  }
}
```

## `examples/claude-desktop.json`

```json
{
  "mcpServers": {
    "project-docs": {
      "url": "http://localhost:8081/sse"
    }
  }
}
```

* * *

## Quickstart

```bash
# 1. Repo klonen
git clone https://github.com/dein-user/mcp-docs-vector.git
cd mcp-docs-vector

# 2. Config anpassen
cp .env.example .env
# → DOCS_PATH oder GIT_REPO_URL eintragen

# 3. Starten
docker-compose up -d

# 4. Web-UI öffnen
open http://localhost:8080

# 5. In Cursor: .cursor/mcp.json
# { "mcpServers": { "project-docs": { "url": "http://localhost:8081/sse" } } }

# 6. Fertig! 🎉
```