"""MCP transport security for remote / LAN deployments.

Regression guards for the 2026-09-11 finding (CT-122): remote MCP clients
received ``HTTP 421 Invalid Host header`` because Flaiwheel constructs
``FastMCP`` itself and never passed ``host`` or ``transport_security``, so
the SDK's loopback-only allowlist applied while uvicorn happily bound
``0.0.0.0``. ``FASTMCP_HOST`` and
``FASTMCP_TRANSPORT_SECURITY__ENABLE_DNS_REBINDING_PROTECTION`` cannot fix
it — ``FastMCP.__init__`` passes both values into ``Settings(...)`` as
explicit init arguments, which outrank environment variables.

Evidence:
  architecture/2026-03-03-mcp-transport-security-tls-for-remote-deployments.md
  bugfix-log/2026-09-11-fastmcp-host-and-fastmcp-transport-security-are-silently-ign.md
"""
import asyncio

import pytest
from starlette.requests import Request

from flaiwheel.__main__ import _resolve_tls
from flaiwheel.config import Config, _split_list
from flaiwheel.project import ProjectConfig, ProjectRegistry
from flaiwheel.server import (
    _LOCALHOST_HOSTS,
    build_transport_security,
    create_mcp_server,
)


# ── Helpers ──────────────────────────────────────────


def _request(host: str, origin: str | None = None) -> Request:
    """Minimal Starlette Request carrying just the headers the guard reads."""
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "query_string": b"",
        "headers": headers,
    })


def _guard_status(settings, host: str, origin: str | None = None):
    """Run the SDK's real guard and return None (pass) or the HTTP status."""
    from mcp.server.transport_security import TransportSecurityMiddleware

    middleware = TransportSecurityMiddleware(settings)
    response = asyncio.run(middleware.validate_request(_request(host, origin)))
    return None if response is None else response.status_code


def _registry(tmp_path, **overrides) -> tuple[Config, ProjectRegistry]:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    cfg = Config(
        docs_path=str(docs),
        vectorstore_path=str(tmp_path / "vectorstore"),
        git_repo_url="",
        git_auto_push=False,
        **overrides,
    )
    registry = ProjectRegistry(cfg)
    registry.add(
        ProjectConfig(
            name="test",
            docs_path=str(docs),
            collection_name="project_docs",
        ),
        start_watcher=False,
    )
    return cfg, registry


# ── List parsing (comma OR JSON) ─────────────────────


class TestSplitList:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("a.example.com,b.example.com", ["a.example.com", "b.example.com"]),
            (" a.example.com , b.example.com ", ["a.example.com", "b.example.com"]),
            ('["a.example.com","b.example.com"]', ["a.example.com", "b.example.com"]),
            ("a.example.com", ["a.example.com"]),
            ("", []),
            (None, []),
            ([], []),
            (["a", " b "], ["a", "b"]),
        ],
    )
    def test_accepts_multiple_syntaxes(self, value, expected):
        assert _split_list(value) == expected

    def test_comma_form_does_not_raise_on_settings_load(self, monkeypatch):
        """The natural `docker run -e` syntax must not crash startup.

        Without NoDecode, pydantic-settings raises SettingsError for a
        non-JSON complex value — a confusing failure for a deployment knob.
        """
        monkeypatch.setenv("MCP_SSE_ALLOWED_HOSTS", "flaiwheel.4rce.com,flaiwheel.lan")
        cfg = Config()
        assert cfg.sse_allowed_hosts == ["flaiwheel.4rce.com", "flaiwheel.lan"]

    def test_json_form_still_works(self, monkeypatch):
        monkeypatch.setenv("MCP_SSE_ALLOWED_HOSTS", '["a.example.com"]')
        assert Config().sse_allowed_hosts == ["a.example.com"]


# ── Guard construction ───────────────────────────────


class TestBuildTransportSecurity:
    def test_default_is_loopback_only_with_protection_on(self):
        """No configuration must reproduce the historical safe default."""
        settings = build_transport_security(Config())
        assert settings.enable_dns_rebinding_protection is True
        assert settings.allowed_hosts == _LOCALHOST_HOSTS

    def test_configured_host_is_registered_bare_and_with_port(self):
        """A port-less Host (TLS on 443) and an explicit port must both match."""
        settings = build_transport_security(
            Config(sse_allowed_hosts=["flaiwheel.4rce.com"])
        )
        assert "flaiwheel.4rce.com" in settings.allowed_hosts
        assert "flaiwheel.4rce.com:*" in settings.allowed_hosts

    def test_loopback_entries_are_never_dropped(self):
        """SSH tunnels and Host-rewriting proxies arrive as localhost."""
        settings = build_transport_security(
            Config(sse_allowed_hosts=["flaiwheel.4rce.com"])
        )
        for loopback in _LOCALHOST_HOSTS:
            assert loopback in settings.allowed_hosts

    def test_duplicates_and_blanks_are_ignored(self):
        settings = build_transport_security(
            Config(sse_allowed_hosts=["a.example.com", "a.example.com", "", "  "])
        )
        assert settings.allowed_hosts.count("a.example.com") == 1
        assert "" not in settings.allowed_hosts

    def test_origins_are_extended_not_replaced(self):
        settings = build_transport_security(
            Config(sse_allowed_origins=["http://flaiwheel.4rce.com"])
        )
        assert "http://flaiwheel.4rce.com" in settings.allowed_origins
        assert "http://localhost:*" in settings.allowed_origins

    def test_disabling_protection_is_honoured(self):
        settings = build_transport_security(
            Config(sse_dns_rebinding_protection=False)
        )
        assert settings.enable_dns_rebinding_protection is False


# ── The guard as the SDK actually evaluates it ───────


class TestGuardBehaviour:
    def test_allowed_host_passes_and_others_still_get_421(self):
        """The whole point: one host opens, everything else stays loud."""
        settings = build_transport_security(
            Config(sse_allowed_hosts=["flaiwheel.4rce.com"])
        )

        # Configured host, with and without an explicit port.
        assert _guard_status(settings, "flaiwheel.4rce.com:8081") is None
        assert _guard_status(settings, "flaiwheel.4rce.com") is None

        # Loopback still works (health checks, SSH tunnel, existing proxy).
        assert _guard_status(settings, "localhost:8081") is None
        assert _guard_status(settings, "127.0.0.1:18081") is None

        # Everything else remains rejected — including lookalike suffixes,
        # which must not slip through the `startswith(base + ":")` match.
        assert _guard_status(settings, "evil.example.com:8081") == 421
        assert _guard_status(settings, "flaiwheel.4rce.com.evil.com:1") == 421

    def test_default_config_still_rejects_remote_hosts(self):
        """Unconfigured installs must not silently become reachable."""
        settings = build_transport_security(Config())
        assert _guard_status(settings, "flaiwheel.4rce.com:8081") == 421
        assert _guard_status(settings, "localhost:8081") is None

    def test_disallowed_browser_origin_is_rejected(self):
        settings = build_transport_security(
            Config(
                sse_allowed_hosts=["flaiwheel.4rce.com"],
                sse_allowed_origins=["http://flaiwheel.4rce.com"],
            )
        )
        assert _guard_status(settings, "flaiwheel.4rce.com:8081",
                             origin="http://flaiwheel.4rce.com") is None
        assert _guard_status(settings, "flaiwheel.4rce.com:8081",
                             origin="http://evil.example.com") == 403


# ── Wiring into the product ──────────────────────────


class TestCreateMcpServerWiring:
    def test_configured_hosts_reach_the_real_server(self, tmp_path):
        cfg, registry = _registry(
            tmp_path, sse_host="0.0.0.0", sse_allowed_hosts=["flaiwheel.4rce.com"]
        )
        mcp = create_mcp_server(cfg, registry)

        assert mcp.settings.host == "0.0.0.0"
        security = mcp.settings.transport_security
        assert security is not None, "guard must be explicit, not left to the SDK"
        assert security.enable_dns_rebinding_protection is True
        assert "flaiwheel.4rce.com:*" in security.allowed_hosts

    def test_unconfigured_server_keeps_loopback_guard(self, tmp_path):
        cfg, registry = _registry(tmp_path)
        mcp = create_mcp_server(cfg, registry)

        security = mcp.settings.transport_security
        assert security.enable_dns_rebinding_protection is True
        assert security.allowed_hosts == _LOCALHOST_HOSTS

    def test_non_localhost_bind_does_not_disable_protection(self, tmp_path):
        """The trap this fix avoids.

        Passing ``host='0.0.0.0'`` *without* ``transport_security`` makes the
        SDK skip its auto-enable entirely (``transport_security is None``),
        i.e. protection silently switches OFF. Binding wide must not mean
        guarding nothing.
        """
        cfg, registry = _registry(tmp_path, sse_host="0.0.0.0")
        mcp = create_mcp_server(cfg, registry)

        assert mcp.settings.transport_security is not None
        assert mcp.settings.transport_security.enable_dns_rebinding_protection is True


class TestFastMcpEnvVarsRemainInert:
    """Canary from the knowledge base — revisit on any MCP SDK upgrade.

    ``FASTMCP_HOST`` looks like the obvious fix for remote access and is not.
    If this ever starts failing, the SDK has changed precedence and the
    reverse proxy may have become removable by configuration alone.
    """

    def test_fastmcp_host_env_var_does_not_override_init_default(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP

        monkeypatch.setenv("FASTMCP_HOST", "0.0.0.0")
        assert FastMCP("x").settings.host == "127.0.0.1"

    def test_fastmcp_transport_security_env_var_does_not_override(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP

        monkeypatch.setenv(
            "FASTMCP_TRANSPORT_SECURITY__ENABLE_DNS_REBINDING_PROTECTION", "false"
        )
        settings = FastMCP("x").settings.transport_security
        assert settings.enable_dns_rebinding_protection is True


# ── Backwards compatibility ──────────────────────────


def test_default_bind_host_is_unchanged():
    """0.0.0.0 is deliberate.

    Pre-fix, __main__ hardcoded 0.0.0.0 for the SSE bind. Defaulting to
    127.0.0.1 would silently break every existing published-port deployment,
    so the historical value is preserved and opt-in narrows it.
    """
    assert Config().sse_host == "0.0.0.0"


# ── Native TLS ───────────────────────────────────────


class TestResolveTls:
    def test_no_tls_configured_returns_empty(self):
        assert _resolve_tls(Config()) == {}

    def test_complete_pair_returns_uvicorn_kwargs(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert")
        key.write_text("key")

        assert _resolve_tls(
            Config(sse_tls_certfile=str(cert), sse_tls_keyfile=str(key))
        ) == {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}

    def test_surrounding_whitespace_is_tolerated(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert")
        key.write_text("key")

        result = _resolve_tls(
            Config(sse_tls_certfile=f"  {cert}  ", sse_tls_keyfile=f"\t{key}")
        )
        assert result["ssl_certfile"] == str(cert)
        assert result["ssl_keyfile"] == str(key)

    def test_cert_without_key_fails_closed(self, tmp_path):
        """Never downgrade to plaintext when the operator asked for TLS."""
        cert = tmp_path / "cert.pem"
        cert.write_text("cert")
        with pytest.raises(ValueError, match="MCP_SSE_TLS_KEYFILE"):
            _resolve_tls(Config(sse_tls_certfile=str(cert)))

    def test_key_without_cert_fails_closed(self, tmp_path):
        key = tmp_path / "key.pem"
        key.write_text("key")
        with pytest.raises(ValueError, match="MCP_SSE_TLS_CERTFILE"):
            _resolve_tls(Config(sse_tls_keyfile=str(key)))

    def test_missing_cert_file_fails_closed(self, tmp_path):
        key = tmp_path / "key.pem"
        key.write_text("key")
        with pytest.raises(ValueError, match="readable file"):
            _resolve_tls(
                Config(
                    sse_tls_certfile=str(tmp_path / "absent.pem"),
                    sse_tls_keyfile=str(key),
                )
            )

    def test_directory_path_fails_closed(self, tmp_path):
        """A directory is not a readable certificate."""
        key = tmp_path / "key.pem"
        key.write_text("key")
        with pytest.raises(ValueError, match="readable file"):
            _resolve_tls(
                Config(sse_tls_certfile=str(tmp_path), sse_tls_keyfile=str(key))
            )


class TestTlsConfigFlags:
    def test_configured_requires_both(self, tmp_path):
        assert Config(sse_tls_certfile="c").sse_tls_configured is False
        assert Config(sse_tls_keyfile="k").sse_tls_configured is False
        assert Config(sse_tls_certfile="c", sse_tls_keyfile="k").sse_tls_configured

    def test_blank_strings_are_not_configuration(self):
        assert Config(sse_tls_certfile="  ", sse_tls_keyfile=" ").sse_tls_configured is False

    def test_partial_detects_half_configured_pairs(self):
        assert Config(sse_tls_certfile="c").sse_tls_partial is True
        assert Config(sse_tls_keyfile="k").sse_tls_partial is True
        assert Config().sse_tls_partial is False
        assert Config(sse_tls_certfile="c", sse_tls_keyfile="k").sse_tls_partial is False
