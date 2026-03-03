#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE.md. Commercial licensing: info@4rce.com
set -e

echo "================================================"
echo "  Flaiwheel Server"
echo "================================================"
echo "  Docs:       ${MCP_DOCS_PATH:-/docs}"
echo "  Embeddings: ${MCP_EMBEDDING_PROVIDER:-local} (${MCP_EMBEDDING_MODEL:-all-MiniLM-L6-v2})"
echo "  Transport:  ${MCP_TRANSPORT:-sse}"
echo "  Web-UI:     http://0.0.0.0:${MCP_WEB_PORT:-8080}"
echo "  MCP SSE:    http://0.0.0.0:${MCP_SSE_PORT:-8081}"
echo "================================================"

mkdir -p /data/vectorstore /data/models

# ── Embedding model cache ────────────────────────────────────────────────────
# Models are stored on the persistent /data volume so they survive restarts.
# First start downloads once (~80 MB for all-MiniLM-L6-v2); subsequent starts
# are instant. SENTENCE_TRANSFORMERS_HOME points the library at the cache dir.
export SENTENCE_TRANSFORMERS_HOME=/data/models
export HF_HOME=/data/models/huggingface
export TRANSFORMERS_CACHE=/data/models/huggingface

_MODEL="${MCP_EMBEDDING_MODEL:-all-MiniLM-L6-v2}"
_MODEL_CACHE="/data/models/sentence-transformers_${_MODEL//\//__}"

if [ ! -d "$_MODEL_CACHE" ] && [ "${MCP_EMBEDDING_PROVIDER:-local}" = "local" ]; then
    echo ""
    echo "  Downloading embedding model '${_MODEL}' to /data/models (first run only)..."
    python -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('${_MODEL}', cache_folder='/data/models')
print('  Embedding model cached.')
" || echo "  Warning: embedding model download failed — will retry on first search"
    echo ""
fi

# Pre-download reranker model if enabled
_RERANKER_MODEL="${MCP_RERANKER_MODEL:-cross-encoder/ms-marco-MiniLM-L-12-v2}"
_RERANKER_CACHE="/data/models/$(echo "$_RERANKER_MODEL" | tr '/' '_')"
if [ "${MCP_RERANKER_ENABLED:-true}" = "true" ] && [ ! -d "$_RERANKER_CACHE" ]; then
    echo "  Downloading reranker model '${_RERANKER_MODEL}' (first run only)..."
    python -c "
from sentence_transformers import CrossEncoder
CrossEncoder('${_RERANKER_MODEL}', cache_folder='/data/models')
print('  Reranker model cached.')
" || echo "  Warning: reranker model download failed — reranking disabled until available"
    echo ""
fi

# Derive project name from git repo URL (strip -knowledge suffix)
PROJ_NAME=""
if [ -n "${MCP_GIT_REPO_URL}" ]; then
    PROJ_NAME=$(basename "${MCP_GIT_REPO_URL}" .git)
    PROJ_NAME=${PROJ_NAME%-knowledge}
fi

# Clone into /docs/{name} (isolated per-project directory)
if [ -n "${MCP_GIT_REPO_URL}" ] && [ -n "${PROJ_NAME}" ]; then
    CLONE_TARGET="/docs/${PROJ_NAME}"
    if [ ! "$(ls -A "${CLONE_TARGET}" 2>/dev/null)" ]; then
        echo ""
        echo "Cloning ${MCP_GIT_REPO_URL} -> ${CLONE_TARGET} (branch: ${MCP_GIT_BRANCH:-main})..."

        CLONE_URL="${MCP_GIT_REPO_URL}"
        if [ -n "${MCP_GIT_TOKEN}" ]; then
            CLONE_URL=$(echo "${CLONE_URL}" | sed "s|https://|https://${MCP_GIT_TOKEN}@|")
        fi

        mkdir -p /docs
        git clone \
            --branch "${MCP_GIT_BRANCH:-main}" \
            --single-branch \
            "${CLONE_URL}" "${CLONE_TARGET}"

        echo "Clone complete"
    fi
fi

# Single unified process (Web-UI + MCP server share state)
exec python -m flaiwheel
