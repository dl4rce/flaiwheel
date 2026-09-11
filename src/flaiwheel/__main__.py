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
from .tls import TlsMaterial, ensure_automatic_tls
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


def _resolve_tls(config: Config) -> dict:
    """Return uvicorn ``ssl_*`` kwargs for the MCP SSE server, or ``{}``.

    TLS is deliberately all-or-nothing and **fails closed**. If an operator
    sets a certificate but it is unreadable, or sets only one half of the
    pair, this raises instead of serving the endpoint in cleartext. The
    operator asked for encrypted transport; silently downgrading to plain
    HTTP while appearing to honour their configuration is the worst
    possible outcome — worse than refusing to start.

    The same rule applies to ``MCP_SSE_TLS_AUTO``: if provisioning fails, this
    raises rather than quietly falling back to cleartext.
    """
    return _resolve_tls_material(config)[0]


def _resolve_tls_material(config: Config) -> tuple[dict, "TlsMaterial | None"]:
    """Resolve TLS, also returning generated material for startup reporting."""
    cert = config.sse_tls_certfile.strip()
    key = config.sse_tls_keyfile.strip()

    if cert or key:
        if not (cert and key):
            present, missing = (
                ("MCP_SSE_TLS_CERTFILE", "MCP_SSE_TLS_KEYFILE") if cert
                else ("MCP_SSE_TLS_KEYFILE", "MCP_SSE_TLS_CERTFILE")
            )
            raise ValueError(
                f"{present} is set but {missing} is not. MCP SSE TLS requires "
                "both. Refusing to serve the MCP endpoint over plain HTTP."
            )

        for var, path in (
            ("MCP_SSE_TLS_CERTFILE", cert),
            ("MCP_SSE_TLS_KEYFILE", key),
        ):
            if not Path(path).is_file():
                raise ValueError(
                    f"{var} does not point to a readable file: {path}. Refusing "
                    "to serve the MCP endpoint over plain HTTP."
                )

        return {"ssl_certfile": cert, "ssl_keyfile": key}, None

    if config.sse_tls_auto:
        try:
            material = ensure_automatic_tls(
                config.sse_tls_dir_resolved,
                hosts=config.sse_allowed_hosts,
                bind_host=config.sse_host,
            )
        except Exception as exc:  # noqa: BLE001 - any failure must not degrade to HTTP
            raise ValueError(
                f"MCP_SSE_TLS_AUTO could not provision a certificate "
                f"({type(exc).__name__}: {exc}). Refusing to serve the MCP "
                "endpoint over plain HTTP."
            ) from exc
        return (
            {
                "ssl_certfile": str(material.server_cert),
                "ssl_keyfile": str(material.server_key),
            },
            material,
        )

    return {}, None


def _run_mcp_sse(mcp_server, host: str, port: int, tls: dict | None = None):
    """Run MCP server via SSE, compatible with both old and new mcp SDK versions."""
    tls = tls or {}
    try:
        sse_app = mcp_server.sse_app()
        uvicorn.run(sse_app, host=host, port=port, log_level="warning", **tls)
    except AttributeError:
        try:
            mcp_server.run(transport="sse", host=host, port=port, **tls)
        except TypeError:
            mcp_server.settings.host = host
            mcp_server.settings.port = port
            mcp_server.run(transport="sse")


def main():
    config = Config.load()
    config_lock = threading.Lock()

    # Validate TLS before any watcher starts or any git operation runs: a
    # misconfigured certificate must abort immediately, leaving nothing
    # half-started behind it.
    tls: dict = {}
    auto_tls: TlsMaterial | None = None
    if config.transport == "sse":
        try:
            tls, auto_tls = _resolve_tls_material(config)
        except ValueError as exc:
            diag(f"FATAL: {exc}")
            raise SystemExit(2) from None

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
            reset_telemetry=mcp_server.reset_project_telemetry,
        )

        def run_web():
            uvicorn.run(
                web_app, host="0.0.0.0", port=config.web_port,
                log_level="warning",
            )

        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()
        diag(f"Web-UI running on http://0.0.0.0:{config.web_port}")
        if config.sse_allowed_hosts and config.sse_dns_rebinding_protection:
            diag(
                "MCP transport guard allows non-localhost hosts: "
                + ", ".join(config.sse_allowed_hosts)
            )
        elif not config.sse_dns_rebinding_protection:
            diag(
                "WARNING: MCP DNS-rebinding protection is DISABLED "
                "(MCP_SSE_DNS_REBINDING_PROTECTION=false) — the Host and "
                "Origin guard is off for every client."
            )

        loopback_bind = config.sse_host.strip() in ("127.0.0.1", "localhost", "::1")
        if not tls and not loopback_bind:
            diag(
                "  WARNING: MCP SSE is plain HTTP on a non-loopback address. "
                "Serving it to other machines sends queries and document content "
                "in cleartext — set MCP_SSE_TLS_AUTO=true to have Flaiwheel issue "
                "its own certificate, set MCP_SSE_TLS_CERTFILE + "
                "MCP_SSE_TLS_KEYFILE, terminate TLS at a proxy, or use an "
                "encrypted tunnel. See SECURITY.md."
            )

        if auto_tls is not None:
            if auto_tls.generated:
                diag("Auto-TLS: generated a private CA and server certificate")
            else:
                diag("Auto-TLS: reusing existing certificate")
            diag(f"  certificates : {auto_tls.server_cert.parent}")
            diag(f"  covers       : {' '.join(auto_tls.dns_names)} {' '.join(auto_tls.ip_addresses)}")
            diag(f"  SHA-256      : {auto_tls.server_fingerprint}")
            diag(
                "  Each client machine must trust the CA once. For Node-based "
                "MCP clients (Cursor, Claude Code, VS Code) add this to the "
                "server's env block:"
            )
            diag(f'    "{auto_tls.client_snippet}"')

        if tls:
            served = (
                f"{config.sse_host}:{config.sse_port}"
            )
            diag(f"MCP SSE served over HTTPS on {served} (cert: {tls['ssl_certfile']})")
        _run_mcp_sse(mcp_server, config.sse_host, config.sse_port, tls)
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
