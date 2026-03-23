# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
Unified entry point: python -m flaiwheel

Runs Web-UI + MCP Server in a single process with shared state.
Web-UI in a background thread, MCP SSE server in the main thread.
Supports multiple projects via ProjectRegistry.
"""
import json
import threading
from pathlib import Path

import uvicorn

from .auth import AuthManager
from .config import Config
from .logutil import diag
from .project import PROJECTS_FILE, ProjectRegistry
from .server import create_mcp_server
from .web import create_web_app


def _stdio_cold_start(config: Config) -> bool:
    """Skip heavy embedding/bootstrap for stdio when there is nothing to load.

    MCP over stdio must not write to stdout except JSON-RPC. We also avoid
    pulling models when Glama (or similar) runs with empty Docker volumes:
    ``/data`` exists as a VOLUME but has no ``projects.json`` yet.
    """
    if config.transport != "stdio":
        return False
    if not Path("/data").exists():
        return True
    if PROJECTS_FILE.exists():
        try:
            raw = json.loads(PROJECTS_FILE.read_text())
            if isinstance(raw, list) and len(raw) > 0:
                return False
        except Exception:
            pass
    if config.git_repo_url:
        return False
    docs = Path(config.docs_path)
    if docs.exists():
        try:
            if any(docs.iterdir()):
                return False
        except OSError:
            return True
    return True


def _create_embedding_fn(config: Config):
    """Create a single embedding function to share across all projects."""
    from chromadb.utils import embedding_functions
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

    # In stdio mode (e.g. Glama inspection), skip heavy init when volumes are empty.
    # The MCP server starts immediately and responds to capability negotiation;
    # tools that require an index return a graceful "no projects configured" message.
    stdio_cold_start = _stdio_cold_start(config)

    if not stdio_cold_start:
        diag("Creating shared embedding model...")
    embedding_fn = _create_embedding_fn(config) if not stdio_cold_start else None

    registry = ProjectRegistry(config, embedding_fn=embedding_fn)
    if not stdio_cold_start:
        registry.bootstrap()
        registry.start_all_watchers()

    n = len(registry)
    if not stdio_cold_start:
        diag(
            f"Loaded {n} project{'s' if n != 1 else ''}: "
            f"{', '.join(registry.names()) or '(none)'}"
        )

    auth = AuthManager(config) if not stdio_cold_start else None

    mcp_server = create_mcp_server(config, registry)

    diag(f"MCP server starting ({config.transport} transport)...")
    if config.transport == "sse":
        web_app = create_web_app(
            config, registry, config_lock, auth,
            get_telemetry=mcp_server.get_telemetry_data,
            get_impact_metrics=mcp_server.get_impact_metrics,
            record_ci_guardrail=mcp_server.record_ci_guardrail_report,
        )

        def run_web():
            uvicorn.run(
                web_app, host="0.0.0.0", port=config.web_port,
                log_level="warning",
            )

        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()
        diag(f"Web-UI running on http://0.0.0.0:{config.web_port}")
        _run_mcp_sse(mcp_server, "0.0.0.0", config.sse_port)
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
