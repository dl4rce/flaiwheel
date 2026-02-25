#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com
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

mkdir -p /data/vectorstore

# Optional: git clone if URL set and /docs empty
if [ -n "${MCP_GIT_REPO_URL}" ] && [ ! "$(ls -A ${MCP_DOCS_PATH:-/docs} 2>/dev/null)" ]; then
    echo ""
    echo "Cloning ${MCP_GIT_REPO_URL} (branch: ${MCP_GIT_BRANCH:-main})..."

    CLONE_URL="${MCP_GIT_REPO_URL}"
    if [ -n "${MCP_GIT_TOKEN}" ]; then
        CLONE_URL=$(echo "${CLONE_URL}" | sed "s|https://|https://${MCP_GIT_TOKEN}@|")
    fi

    git clone \
        --branch "${MCP_GIT_BRANCH:-main}" \
        --single-branch \
        --depth 1 \
        "${CLONE_URL}" "${MCP_DOCS_PATH:-/docs}"

    echo "Clone complete"
fi

# Single unified process (Web-UI + MCP server share state)
exec python -m flaiwheel
