# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

"""
Unified entry point: python -m flaiwheel

Runs Web-UI + MCP Server in a single process with shared state.
Web-UI in a background thread, MCP SSE server in the main thread.
"""
import threading

import uvicorn

from .auth import AuthManager
from .config import Config
from .indexer import DocsIndexer
from .quality import KnowledgeQualityChecker
from .server import create_mcp_server
from .watcher import GitWatcher
from .web import create_web_app


def _run_mcp_sse(mcp_server, host: str, port: int):
    """Run MCP server via SSE, compatible with both old and new mcp SDK versions."""
    # Try sse_app() first (mcp >= 1.20), fall back to run() for older versions
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

    index_lock = threading.Lock()
    config_lock = threading.Lock()

    indexer = DocsIndexer(config)
    auth = AuthManager(config)
    watcher = GitWatcher(config, indexer, index_lock)
    quality_checker = KnowledgeQualityChecker(config)

    print(f"Initial indexing {config.docs_path} ...")
    result = indexer.index_all()
    print(f"Done: {result}")

    watcher.start()

    web_app = create_web_app(
        config, indexer, watcher, index_lock, config_lock, auth, quality_checker,
    )
    mcp_server = create_mcp_server(
        config, indexer, index_lock, watcher, quality_checker,
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
