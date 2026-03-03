# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE.md. Commercial licensing: info@4rce.com

# ── Stage 1: build deps ───────────────────────────────────────────────────
# Uses uv (Rust-based installer, parallel, 10-100x faster than pip).
# Layer is cached after first build — only rebuilds if pyproject.toml changes.
FROM python:3.12-slim AS builder

# Install uv — single binary, no deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

# uv installs in parallel using all available cores.
# --prefix=/install isolates packages so we copy only them to the runtime stage.
RUN uv pip install --system --no-cache --prefix=/install .

# ── Stage 2: runtime image ────────────────────────────────────────────────
# Only the installed packages are copied — no build tools, no compiler.
# Fewer files = faster layer export.
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source and scripts
COPY src/ src/
COPY scripts/ scripts/
RUN chmod +x scripts/*.sh

# Model is NOT baked into the image — downloaded on first start to /data volume.
# This keeps the image small and avoids OOM during docker build on low-RAM hosts.

# /docs = per-project knowledge repos (git cloned at runtime)
# /data = vectorstore + config + models (persistent volume)
VOLUME ["/docs", "/data"]

# OCI standard labels — used by installer to detect if rebuild is needed
ARG FLAIWHEEL_VERSION=dev
LABEL org.opencontainers.image.version="${FLAIWHEEL_VERSION}" \
      org.opencontainers.image.title="Flaiwheel" \
      org.opencontainers.image.source="https://github.com/dl4rce/flaiwheel" \
      org.opencontainers.image.licenses="BSL-1.1"

ENV MCP_DOCS_PATH=/docs \
    MCP_VECTORSTORE_PATH=/data/vectorstore \
    MCP_EMBEDDING_PROVIDER=local \
    MCP_EMBEDDING_MODEL=all-MiniLM-L12-v2 \
    MCP_RERANKER_ENABLED=true \
    MCP_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-12-v2 \
    MCP_CHUNK_STRATEGY=heading \
    MCP_TRANSPORT=sse \
    MCP_SSE_PORT=8081 \
    MCP_WEB_PORT=8080

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health 2>/dev/null || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
