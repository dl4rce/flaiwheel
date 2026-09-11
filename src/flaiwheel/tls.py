# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""Automatic TLS material for the MCP SSE endpoint.

Why this module exists
----------------------
Encrypting the MCP transport used to require the operator to obtain a
certificate first. For a containerised, self-hosted tool that is an
unreasonable ask: most deployments are reached by a LAN address
(``192.168.x.y``) for which no public CA will ever issue a certificate, and
hand-rolling one with ``openssl`` is not something to demand of every user.

So Flaiwheel manufactures its own: a private CA plus a server certificate
signed by it, generated on first start and persisted in a volume. The
operator never runs a certificate tool.

The one thing this module cannot do
-----------------------------------
It cannot make a *client* trust the CA. The container has no access to the
client machine's trust store — that is a hard boundary, and it is why even
``mkcert`` needs a per-machine install step. A client therefore has to be
told once, via a single environment variable::

    NODE_EXTRA_CA_CERTS=/data/tls/ca.pem

That is the minimum possible, and it is genuine TLS: encryption *and*
identity, with trust-on-first-use pinning of the CA.

Design decisions worth knowing
------------------------------
* A **CA plus leaf**, not a bare self-signed leaf. The operator pins the CA
  once, and the leaf can be re-issued later without touching client config.
* Certificates live in a **persistent directory** (``/data/tls``), because
  regenerating them on every container recreation silently invalidates every
  client that had already trusted the previous CA.
* The leaf is **reused while it is valid and covers the requested names**, so
  an ordinary upgrade does not change the fingerprint.
* Auto-TLS is **opt-in**. Flipping a running deployment from ``http://`` to
  ``https://`` without being asked would break every existing client — the
  same class of failure as an installer that refuses to upgrade.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .logutil import diag

# Names written by us, so a future format change can be detected.
CA_FILENAME = "ca.pem"
CERT_FILENAME = "server.crt"
KEY_FILENAME = "server.key"

# A private CA is pinned by hand, so it may outlive the public-CA lifetime
# limits. The leaf stays at 825 days (the historical client limit) so that
# the same material would remain acceptable if it were ever installed into
# a real trust store.
CA_VALID_DAYS = 3650
LEAF_VALID_DAYS = 825

# Re-issue the leaf when it has less than this much time left, so a
# deployment that is idle for months does not hand clients a cert that
# expires mid-session.
RENEW_MARGIN_DAYS = 30

KEY_SIZE = 2048
COMMON_NAME = "flaiwheel"


@dataclass(frozen=True)
class TlsMaterial:
    """Paths and fingerprints of an auto-generated certificate set."""

    ca_cert: Path
    server_cert: Path
    server_key: Path
    server_fingerprint: str
    ca_fingerprint: str
    generated: bool
    dns_names: tuple[str, ...]
    ip_addresses: tuple[str, ...]

    @property
    def client_snippet(self) -> str:
        """The single line a client machine needs in order to trust this CA."""
        return f"NODE_EXTRA_CA_CERTS={self.ca_cert}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_until(cert: x509.Certificate) -> datetime:
    """Certificate expiry as an aware datetime, across cryptography versions."""
    for attr in ("not_valid_after_utc", "not_valid_after"):
        value = getattr(cert, attr, None)
        if value is None:
            continue
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    raise AttributeError("certificate has no not_valid_after attribute")


def fingerprint(cert: x509.Certificate) -> str:
    """Colon-separated uppercase SHA-256 of the certificate DER body."""
    digest = cert.fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in digest)


def fingerprint_of(path: Path) -> str:
    """Fingerprint of a certificate on disk (PEM)."""
    return fingerprint(x509.load_pem_x509_certificate(path.read_bytes()))


def classify_host(raw: str) -> tuple[str | None, str | None]:
    """Split a user-supplied host into (dns_name, ip_address).

    Accepts the shapes people actually paste: ``host``, ``host:port``,
    ``https://host:port/path``, ``[::1]:8081``, ``192.168.1.5``.
    Returns ``(None, None)`` for anything unusable (including the wildcard
    binds ``0.0.0.0`` / ``::``, which are addresses to *listen on*, not
    names to certify).
    """
    text = (raw or "").strip()
    if not text:
        return None, None
    # Strip scheme.
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    # Strip port, honouring bracketed IPv6 literals.
    if text.startswith("["):
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]
    text = text.strip().rstrip(".")
    if not text:
        return None, None

    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return text.lower(), None
    if addr.is_unspecified:
        # 0.0.0.0 / :: — a bind, never a SAN.
        return None, None
    return None, str(addr)


def primary_ip() -> str | None:
    """Best-effort local address of the default route.

    Uses a UDP ``connect`` to a documentation-range address: this performs
    no I/O and needs no network, it only asks the kernel which source
    address it *would* use.

    NOTE: deliberately **not** used when building certificates. The kernel's
    choice of source address is a property of the current network namespace,
    so inside Docker it resolves to the container's ephemeral bridge address
    (``172.17.0.x``) — a value that changes on every recreation. A SAN that
    changes forces re-issuance, and re-issuance produces a new CA, which
    invalidates every client that trusted the previous one. Kept here only
    because it is genuinely useful for diagnostics.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # RFC 5737 TEST-NET-1
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def collect_names(
    hosts: list[str] | tuple[str, ...] | None = None,
    bind_host: str | None = None,
) -> tuple[list[str], list[str]]:
    """Work out the DNS names and IP addresses a certificate must cover.

    The set is derived **only from configuration** — the ``MCP_SSE_ALLOWED_HOSTS``
    entries and the bind address — plus loopback. Nothing is read from the
    running environment.

    That restriction is deliberate and it is what makes re-issuance safe.
    Earlier versions also added ``socket.gethostname()`` and the primary LAN
    address. Inside Docker those are per-container values (a random hostname
    and the ephemeral bridge IP), so a recreated container presented a
    certificate missing entries that the previous one had. The name-completeness
    check then saw a gap, re-issued the leaf, and re-issued the **CA** with it —
    invalidating every client that had already trusted it. Regenerating is the
    one failure this module exists to avoid.

    Dropping them costs nothing in practice: a client can only connect to a
    host the transport guard already accepts, and that allowlist is exactly
    what this function certifies. The two can no longer disagree.
    """
    dns: list[str] = []
    ips: list[str] = []

    def add_dns(name: str) -> None:
        if name and name not in dns:
            dns.append(name)

    def add_ip(addr: str) -> None:
        if addr and addr not in ips:
            ips.append(addr)

    for raw in hosts or []:
        name, addr = classify_host(raw)
        if name:
            add_dns(name)
        if addr:
            add_ip(addr)

    if bind_host:
        name, addr = classify_host(bind_host)
        if name:
            add_dns(name)
        if addr:
            add_ip(addr)

    # Loopback is always present: health checks and `ssh -L` forwards arrive
    # as localhost, and they must keep working without extra configuration.
    add_dns("localhost")
    add_ip("127.0.0.1")
    add_ip("::1")

    return dns, ips


def _write_secret(path: Path, data: bytes) -> None:
    """Write a private key with 0600 permissions, even if the file exists."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _write_public(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)


def _pem_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _san(dns: list[str], ips: list[str]) -> x509.SubjectAlternativeName:
    entries: list[x509.GeneralName] = [x509.DNSName(name) for name in dns]
    entries += [x509.IPAddress(ipaddress.ip_address(a)) for a in ips]
    if not entries:
        raise ValueError("refusing to issue a certificate with no subjectAltName")
    return x509.SubjectAlternativeName(entries)


def _build_ca(now: datetime) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _new_key()
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, f"Flaiwheel Local CA ({socket.gethostname()})")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=CA_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _build_leaf(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    dns: list[str],
    ips: list[str],
    now: datetime,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _new_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, COMMON_NAME)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=LEAF_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_san(dns, ips), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _reusable(
    directory: Path, dns: list[str], ips: list[str], now: datetime
) -> TlsMaterial | None:
    """Return existing material if it is intact, unexpired and covers ``dns``/``ips``.

    Returning ``None`` simply means "regenerate". Anything unreadable or
    inconsistent is treated as absent rather than raising, because the caller
    can always rebuild from scratch — but a *regeneration* is a visible event,
    so the reasons are logged.
    """
    ca_path = directory / CA_FILENAME
    cert_path = directory / CERT_FILENAME
    key_path = directory / KEY_FILENAME
    if not all(p.is_file() for p in (ca_path, cert_path, key_path)):
        return None

    try:
        ca_cert = x509.load_pem_x509_certificate(ca_path.read_bytes())
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except Exception as exc:  # noqa: BLE001 - any parse failure means "rebuild"
        diag(f"Auto-TLS: existing material unreadable ({exc}) — regenerating")
        return None

    if _valid_until(ca_cert) < now + timedelta(days=RENEW_MARGIN_DAYS):
        diag("Auto-TLS: CA near expiry — regenerating")
        return None
    leaf_expiry = _valid_until(cert)
    if leaf_expiry < now + timedelta(days=RENEW_MARGIN_DAYS):
        diag(f"Auto-TLS: certificate expires {leaf_expiry:%Y-%m-%d} — regenerating")
        return None

    if cert.issuer != ca_cert.subject:
        diag("Auto-TLS: certificate was not issued by the stored CA — regenerating")
        return None

    if key.public_key().public_numbers() != cert.public_key().public_numbers():
        diag("Auto-TLS: private key does not match the certificate — regenerating")
        return None

    try:
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        diag("Auto-TLS: certificate has no subjectAltName — regenerating")
        return None

    have_dns = {n.lower() for n in names.get_values_for_type(x509.DNSName)}
    have_ips = {str(i) for i in names.get_values_for_type(x509.IPAddress)}
    missing_dns = [n for n in dns if n.lower() not in have_dns]
    missing_ips = [i for i in ips if i not in have_ips]
    if missing_dns or missing_ips:
        diag(
            "Auto-TLS: certificate does not cover "
            f"{', '.join(missing_dns + missing_ips)} — regenerating"
        )
        return None

    return TlsMaterial(
        ca_cert=ca_path,
        server_cert=cert_path,
        server_key=key_path,
        server_fingerprint=fingerprint(cert),
        ca_fingerprint=fingerprint(ca_cert),
        generated=False,
        dns_names=tuple(sorted(have_dns)),
        ip_addresses=tuple(sorted(have_ips)),
    )


def ensure_automatic_tls(
    directory: str | os.PathLike[str],
    hosts: list[str] | tuple[str, ...] | None = None,
    bind_host: str | None = None,
) -> TlsMaterial:
    """Ensure a usable CA + server certificate exist, generating if needed.

    Idempotent: a second call with the same names reuses the existing pair and
    returns ``generated=False``, so the fingerprint a client pinned stays
    stable across restarts and upgrades.
    """
    directory = Path(directory)
    dns, ips = collect_names(hosts, bind_host)
    now = _now()

    existing = _reusable(directory, dns, ips, now)
    if existing is not None:
        return existing

    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass

    ca_key, ca_cert = _build_ca(now)
    leaf_key, leaf_cert = _build_leaf(ca_key, ca_cert, dns, ips, now)

    _write_public(directory / CA_FILENAME, ca_cert.public_bytes(serialization.Encoding.PEM))
    # Serve the full chain so a client that trusts only the CA still verifies
    # even if it does not have the root present locally.
    _write_public(
        directory / CERT_FILENAME,
        leaf_cert.public_bytes(serialization.Encoding.PEM)
        + ca_cert.public_bytes(serialization.Encoding.PEM),
    )
    _write_secret(directory / KEY_FILENAME, _pem_key(leaf_key))

    return TlsMaterial(
        ca_cert=directory / CA_FILENAME,
        server_cert=directory / CERT_FILENAME,
        server_key=directory / KEY_FILENAME,
        server_fingerprint=fingerprint(leaf_cert),
        ca_fingerprint=fingerprint(ca_cert),
        generated=True,
        dns_names=tuple(sorted(dns)),
        ip_addresses=tuple(sorted(ips)),
    )
