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
from .health import HealthTracker
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
    health = HealthTracker()

    indexer = DocsIndexer(config)
    auth = AuthManager(config)
    quality_checker = KnowledgeQualityChecker(config)
    watcher = GitWatcher(config, indexer, index_lock, health, quality_checker=quality_checker)

    print(f"Initial indexing {config.docs_path} ...")
    result = indexer.index_all()
    health.record_index(
        ok=result.get("status") == "success",
        chunks=result.get("chunks_upserted", 0),
        files=result.get("files_indexed", 0),
        error=result.get("message") if result.get("status") != "success" else None,
    )
    try:
        qr = quality_checker.check_all()
        health.record_quality(
            qr["score"], qr.get("critical", 0),
            qr.get("warnings", 0), qr.get("info", 0),
        )
        print(f"Quality score: {qr['score']}/100")
    except Exception as e:
        print(f"Warning: Initial quality check failed: {e}")
    print(f"Done: {result}")

    watcher.start()

    web_app = create_web_app(
        config, indexer, watcher, index_lock, config_lock, auth, quality_checker, health,
    )
    mcp_server = create_mcp_server(
        config, indexer, index_lock, watcher, quality_checker, health,
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
