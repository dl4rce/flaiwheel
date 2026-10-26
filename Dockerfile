# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE. Commercial licensing: info@4rce.com

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

COPY security-constraints.txt ./

# Install CPU-only PyTorch FIRST — prevents sentence-transformers from pulling
# the full CUDA/cuDNN stack (~7GB of nvidia libs, useless without a GPU).
# This alone shrinks the image from ~8GB to ~1GB.
RUN uv pip install --system --no-cache --prefix=/install \
    torch torchvision --no-deps --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml README.md ./
COPY src/ src/

# uv installs in parallel using all available cores.
# torch is already satisfied from CPU index above — won't be re-downloaded.
RUN uv pip install --system --no-cache --prefix=/install \
    --constraint security-constraints.txt '.[full]' setuptools wheel pillow filelock

# Build the scanner from its release source with patched transitive modules.
# Upstream release binaries can retain an older Go standard library.
FROM golang:1.27.3 AS scanner
ARG GITLEAKS_VERSION=8.30.1
WORKDIR /scanner
RUN git clone --depth 1 --branch "v${GITLEAKS_VERSION}" \
    https://github.com/gitleaks/gitleaks.git . \
    && go get github.com/klauspost/compress@v1.18.7 \
        golang.org/x/crypto@v0.55.0 golang.org/x/text@v0.41.0 \
    && CGO_ENABLED=0 go build -trimpath \
        -ldflags="-s -w -X github.com/zricethezav/gitleaks/v8/version.Version=${GITLEAKS_VERSION}" \
        -o /gitleaks .

# ── Stage 2: runtime image ────────────────────────────────────────────────
# Only the installed packages are copied — no build tools, no compiler.
# Fewer files = faster layer export.
FROM python:3.12-slim

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

# gitleaks — commits are created INSIDE this container by the watcher, so the
# secret scanner must live here too. A scanner on the host never sees them.
COPY --from=scanner /gitleaks /usr/local/bin/gitleaks
RUN gitleaks version

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
RUN python -m pip check \
    && python -m pip uninstall -y pip
# Runtime installs, when needed, use uv; pip's bundled dependency copies are removed.

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
    MCP_GITLEAKS_MODE=block \
    MCP_TRANSPORT=sse \
    MCP_SSE_PORT=8081 \
    MCP_WEB_PORT=8080

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health 2>/dev/null || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
