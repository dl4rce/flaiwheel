# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""Tests for automatic TLS provisioning (``flaiwheel.tls``).

These are deliberately *real* crypto tests rather than mocks: the whole point
of the feature is that the emitted material is accepted by a TLS stack, and a
mocked certificate would prove nothing about that. Every certificate built here
is loaded back and verified with the ``cryptography`` library, and the SANs are
read out of the extension that a client would actually inspect.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from flaiwheel.__main__ import _resolve_tls, _resolve_tls_material
from flaiwheel.config import Config
from flaiwheel.tls import (
    CA_FILENAME,
    CERT_FILENAME,
    KEY_FILENAME,
    classify_host,
    collect_names,
    ensure_automatic_tls,
    fingerprint_of,
    primary_ip,
)


def _load(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def _sans(cert: x509.Certificate) -> tuple[set[str], set[str]]:
    ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns = {n.lower() for n in ext.get_values_for_type(x509.DNSName)}
    ips = {str(i) for i in ext.get_values_for_type(x509.IPAddress)}
    return dns, ips


class TestClassifyHost:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("flaiwheel.example.com", ("flaiwheel.example.com", None)),
            ("flaiwheel.example.com:8081", ("flaiwheel.example.com", None)),
            ("https://flaiwheel.example.com:8081/sse", ("flaiwheel.example.com", None)),
            ("FlaiWheel.Example.COM.", ("flaiwheel.example.com", None)),
            ("192.168.178.230", (None, "192.168.178.230")),
            ("192.168.178.230:8081", (None, "192.168.178.230")),
            ("[fe80::1]:8081", (None, "fe80::1")),
            ("::1", (None, "::1")),
        ],
    )
    def test_splits_names_from_addresses(self, raw, expected):
        assert classify_host(raw) == expected

    @pytest.mark.parametrize("raw", ["0.0.0.0", "::", "", "   ", "http://0.0.0.0:8081"])
    def test_wildcard_binds_are_not_certifiable_names(self, raw):
        """A bind address is not a name to certify — including it would be junk."""
        assert classify_host(raw) == (None, None)


class TestCollectNames:
    def test_always_covers_loopback(self):
        dns, ips = collect_names([])
        assert "localhost" in dns
        assert "127.0.0.1" in ips
        assert "::1" in ips

    def test_includes_configured_hosts_and_bound_address(self):
        dns, ips = collect_names(
            ["flaiwheel.4rce.com", "192.168.178.230"], bind_host="0.0.0.0"
        )
        assert "flaiwheel.4rce.com" in dns
        assert "192.168.178.230" in ips

    def test_wildcard_bind_does_not_leak_into_sans(self):
        dns, ips = collect_names([], bind_host="0.0.0.0")
        assert "0.0.0.0" not in ips
        assert "0.0.0.0" not in dns

    def test_duplicates_are_collapsed(self):
        dns, ips = collect_names(["localhost", "localhost", "127.0.0.1"])
        assert dns.count("localhost") == 1
        assert ips.count("127.0.0.1") == 1

    def test_is_purely_config_derived(self):
        """Regression: environment-derived names made re-issuance probable.

        socket.gethostname() and the primary LAN address are per-container
        values under Docker (a random container id and the ephemeral bridge
        IP). Including them meant a recreated container presented a certificate
        missing entries the previous one had, so the completeness check
        re-issued the leaf -- and the CA with it -- invalidating every client
        that had trusted it.
        """
        dns, ips = collect_names(["flaiwheel.example.com"], bind_host="0.0.0.0")
        assert socket.gethostname() not in dns
        assert socket.gethostname().split(".", 1)[0] not in dns
        assert primary_ip() not in ips
        # Nothing outside the configured set and loopback may appear.
        assert set(dns) <= {"flaiwheel.example.com", "localhost"}
        assert set(ips) <= {"127.0.0.1", "::1"}

    def test_repeated_calls_return_identical_sets(self):
        """The SAN set must be deterministic for a given configuration."""
        first = collect_names(["a.example.com", "10.0.0.5"], bind_host="0.0.0.0")
        second = collect_names(["a.example.com", "10.0.0.5"], bind_host="0.0.0.0")
        assert first == second


class TestGeneration:
    def test_creates_all_three_files(self, tmp_path):
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        assert material.generated is True
        for name in (CA_FILENAME, CERT_FILENAME, KEY_FILENAME):
            assert (tmp_path / name).is_file(), name

    def test_leaf_is_signed_by_the_ca(self, tmp_path):
        """The chain must actually verify, not merely look plausible."""
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        ca = _load(material.ca_cert)
        leaf = _load(material.server_cert)
        ca.public_key().verify(
            leaf.signature,
            leaf.tbs_certificate_bytes,
            padding.PKCS1v15(),
            leaf.signature_hash_algorithm,
        )

    def test_ca_is_a_ca_and_leaf_is_not(self, tmp_path):
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        ca_bc = _load(material.ca_cert).extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
        leaf_bc = _load(material.server_cert).extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
        assert ca_bc.ca is True
        assert ca_bc.path_length == 0
        assert leaf_bc.ca is False

    def test_has_server_auth_eku(self, tmp_path):
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        eku = _load(material.server_cert).extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        ).value
        assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in eku

    def test_sans_cover_requested_names_and_addresses(self, tmp_path):
        material = ensure_automatic_tls(
            tmp_path, hosts=["flaiwheel.4rce.com", "192.168.178.230"]
        )
        dns, ips = _sans(_load(material.server_cert))
        assert "flaiwheel.4rce.com" in dns
        assert "192.168.178.230" in ips
        assert all(ipaddress.ip_address(i) for i in ips)

    def test_cert_contains_the_full_chain(self, tmp_path):
        """A client that trusts only the CA must still see the issuer."""
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        body = material.server_cert.read_text()
        assert body.count("BEGIN CERTIFICATE") == 2

    def test_key_is_private(self, tmp_path):
        if os.name == "nt":  # POSIX permission bits are meaningless here
            pytest.skip("POSIX permissions")
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        mode = stat.S_IMODE(material.server_key.stat().st_mode)
        assert mode == 0o600, oct(mode)

    def test_existing_loose_key_permissions_are_tightened(self, tmp_path):
        ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        key = tmp_path / KEY_FILENAME
        os.chmod(key, 0o644)
        # Force a regeneration path, then confirm the mode is repaired.
        (tmp_path / CERT_FILENAME).unlink()
        ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        assert stat.S_IMODE(key.stat().st_mode) == 0o600

    def test_leaf_is_usable_for_tls(self, tmp_path):
        """The pair must load the way uvicorn loads it."""
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        key = serialization.load_pem_private_key(
            material.server_key.read_bytes(), password=None
        )
        cert = _load(material.server_cert)
        assert key.public_key().public_numbers() == cert.public_key().public_numbers()

    def test_leaf_validity_within_ca_validity(self, tmp_path):
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        ca = _load(material.ca_cert)
        leaf = _load(material.server_cert)
        assert leaf.not_valid_after_utc <= ca.not_valid_after_utc


class TestIdempotence:
    def test_second_call_reuses_material(self, tmp_path):
        """Stability matters: a changed fingerprint breaks every pinned client."""
        first = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        second = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        assert second.generated is False
        assert second.server_fingerprint == first.server_fingerprint

    def test_unchanged_files_are_not_rewritten(self, tmp_path):
        ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        before = {
            name: (tmp_path / name).read_bytes()
            for name in (CA_FILENAME, CERT_FILENAME, KEY_FILENAME)
        }
        ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        for name, data in before.items():
            assert (tmp_path / name).read_bytes() == data, name

    def test_new_name_forces_regeneration(self, tmp_path):
        """A cert that cannot cover a new host is a client-visible failure."""
        first = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        second = ensure_automatic_tls(
            tmp_path, hosts=["flaiwheel.lan", "flaiwheel.4rce.com"]
        )
        assert second.generated is True
        dns, _ = _sans(_load(second.server_cert))
        assert "flaiwheel.4rce.com" in dns
        assert second.server_fingerprint != first.server_fingerprint

    def test_corrupt_material_is_rebuilt(self, tmp_path):
        ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        (tmp_path / CA_FILENAME).write_text("not a certificate")
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        assert material.generated is True
        _load(material.ca_cert)  # parses again

    def test_mismatched_key_is_replaced(self, tmp_path):
        ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        # A key that does not match the certificate must never be served.
        other = ensure_automatic_tls(tmp_path / "other", hosts=["flaiwheel.lan"])
        (tmp_path / KEY_FILENAME).write_bytes(other.server_key.read_bytes())
        material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
        assert material.generated is True
        key = serialization.load_pem_private_key(
            material.server_key.read_bytes(), password=None
        )
        cert = _load(material.server_cert)
        assert key.public_key().public_numbers() == cert.public_key().public_numbers()

    def test_directory_is_created_when_absent(self, tmp_path):
        target = tmp_path / "nested" / "tls"
        ensure_automatic_tls(target, hosts=["flaiwheel.lan"])
        assert target.is_dir()


class TestResolveTlsAuto:
    def test_disabled_by_default(self):
        assert _resolve_tls(Config()) == {}

    def test_explicit_pair_still_wins_over_auto(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert")
        key.write_text("key")
        result = _resolve_tls(
            Config(
                sse_tls_certfile=str(cert),
                sse_tls_keyfile=str(key),
                sse_tls_auto=True,
                sse_tls_dir=str(tmp_path / "generated"),
            )
        )
        assert result == {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}

    def test_auto_generates_and_selects_the_generated_pair(self, tmp_path):
        tls, material = _resolve_tls_material(
            Config(
                sse_tls_auto=True,
                sse_tls_dir=str(tmp_path),
                sse_host="0.0.0.0",
                sse_allowed_hosts=["flaiwheel.lan"],
            )
        )
        assert material is not None
        assert tls["ssl_certfile"] == str(tmp_path / CERT_FILENAME)
        assert tls["ssl_keyfile"] == str(tmp_path / KEY_FILENAME)
        assert Path(tls["ssl_certfile"]).is_file()

    def test_auto_reuses_on_second_resolve(self, tmp_path):
        config = Config(
            sse_tls_auto=True, sse_tls_dir=str(tmp_path), sse_host="0.0.0.0"
        )
        _, first = _resolve_tls_material(config)
        _, second = _resolve_tls_material(config)
        assert first is not None and second is not None
        assert second.generated is False
        assert second.server_fingerprint == first.server_fingerprint

    def test_client_snippet_points_at_the_ca(self, tmp_path):
        _, material = _resolve_tls_material(
            Config(sse_tls_auto=True, sse_tls_dir=str(tmp_path), sse_host="0.0.0.0")
        )
        assert material is not None
        assert material.client_snippet == f"NODE_EXTRA_CA_CERTS={material.ca_cert}"
        assert "BEGIN CERTIFICATE" in material.ca_cert.read_text()

    def test_fails_closed_when_provisioning_is_impossible(self, tmp_path):
        """Never silently serve cleartext because generation failed."""
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file, not a directory")
        with pytest.raises(ValueError, match="MCP_SSE_TLS_AUTO"):
            _resolve_tls(
                Config(sse_tls_auto=True, sse_tls_dir=str(blocker), sse_host="0.0.0.0")
            )

    def test_partial_pair_still_fails_closed_even_with_auto_enabled(self, tmp_path):
        cert = tmp_path / "cert.pem"
        cert.write_text("cert")
        with pytest.raises(ValueError, match="MCP_SSE_TLS_KEYFILE"):
            _resolve_tls(
                Config(
                    sse_tls_certfile=str(cert),
                    sse_tls_auto=True,
                    sse_tls_dir=str(tmp_path / "generated"),
                )
            )


class TestTlsDirResolution:
    def test_explicit_directory_is_honoured(self, tmp_path):
        assert Config(sse_tls_dir=str(tmp_path)).sse_tls_dir_resolved == tmp_path

    def test_default_is_stable_across_calls(self):
        config = Config()
        assert config.sse_tls_dir_resolved == config.sse_tls_dir_resolved

    def test_default_prefers_a_persistent_location(self):
        """Wherever it resolves, it must not be inside the image layer."""
        resolved = Config().sse_tls_dir_resolved
        assert "tls" in resolved.parts
        assert resolved != Path("/tmp")


def test_fingerprint_is_sha256_of_der(tmp_path):
    material = ensure_automatic_tls(tmp_path, hosts=["flaiwheel.lan"])
    digest = _load(material.server_cert).fingerprint(hashes.SHA256())
    assert fingerprint_of(material.server_cert) == ":".join(f"{b:02X}" for b in digest)
