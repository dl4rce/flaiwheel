# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Unified entry point: python -m flaiwheel

Runs Web-UI + MCP Server in a single process with shared state.
Web-UI in a background thread, MCP SSE server in the main thread.
Supports multiple projects via ProjectRegistry.
"""
import threading

import uvicorn
from chromadb.utils import embedding_functions

from .auth import AuthManager
from .config import Config
from .project import ProjectRegistry
from .server import create_mcp_server
from .web import create_web_app


def _create_embedding_fn(config: Config):
    """Create a single embedding function to share across all projects."""
    if config.embedding_provider == "local":
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.embedding_model
        )
    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=config.openai_api_key,
        model_name=config.openai_embedding_model,
    )


def _run_mcp_sse(mcp_server, host: str, port: int):
    """Run MCP server via SSE, compatible with both old and new mcp SDK versions."""
    try:
        sse_app = mcp_server.sse_app()
        uvicorn.run(sse_app, host=host, port=port, log_level="warning")
    except AttributeError:
        try:
            mcp_server.run(transport="sse", host=host, port=port)
        except TypeError:
            mcp_server.settings.host = host
            mcp_server.settings.port = port
            mcp_server.run(transport="sse")


def main():
    config = Config.load()
    config_lock = threading.Lock()

    print("Creating shared embedding model...")
    embedding_fn = _create_embedding_fn(config)

    registry = ProjectRegistry(config, embedding_fn=embedding_fn)
    registry.bootstrap()
    registry.start_all_watchers()

    n = len(registry)
    print(f"Loaded {n} project{'s' if n != 1 else ''}: {', '.join(registry.names()) or '(none)'}")

    auth = AuthManager(config)

    mcp_server = create_mcp_server(config, registry)
    web_app = create_web_app(
        config, registry, config_lock, auth,
        get_telemetry=mcp_server.get_telemetry_data,
    )

    def run_web():
        uvicorn.run(
            web_app, host="0.0.0.0", port=config.web_port,
            log_level="warning",
        )

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    print(f"Web-UI running on http://0.0.0.0:{config.web_port}")

    print(f"MCP server starting ({config.transport} transport)...")
    if config.transport == "sse":
        _run_mcp_sse(mcp_server, "0.0.0.0", config.sse_port)
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
