# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY scripts/ scripts/

RUN pip install --no-cache-dir . && \
    chmod +x scripts/*.sh

# Pre-load default embedding model so first start is fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# /docs = your markdown docs (mount or git clone)
# /data = vector index + config (persistent!)
VOLUME ["/docs", "/data"]

ENV MCP_DOCS_PATH=/docs \
    MCP_VECTORSTORE_PATH=/data/vectorstore \
    MCP_EMBEDDING_PROVIDER=local \
    MCP_EMBEDDING_MODEL=all-MiniLM-L6-v2 \
    MCP_CHUNK_STRATEGY=heading \
    MCP_TRANSPORT=sse \
    MCP_SSE_PORT=8081 \
    MCP_WEB_PORT=8080

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health 2>/dev/null || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
