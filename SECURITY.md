# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.15.x (latest) | ✅ |
| 3.14.x | ✅ |
| < 3.14 | ❌ |

## Reporting a Vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Report security issues by emailing **[security@4rce.com](mailto:security@4rce.com)** (or [info@4rce.com](mailto:info@4rce.com)).

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Affected version(s)

You will receive an acknowledgement within **48 hours** and a resolution timeline within **7 days**.

## Scope

Flaiwheel runs entirely self-hosted inside a Docker container on your own infrastructure. There is no Flaiwheel cloud backend, no telemetry sent to external servers, and no SaaS component.

**In scope:**
- Vulnerabilities in the Flaiwheel MCP server or Web UI
- Dependency vulnerabilities in `pyproject.toml`
- Docker image security issues
- Authentication/authorization bypass

**Out of scope:**
- Security of the AI agent or IDE you connect to Flaiwheel
- Security of the Git hosting platform (GitHub, GitLab, etc.) you use for knowledge repos
- Findings from automated scanners without proof of exploitability

## Transport Security (MCP SSE)

Flaiwheel's MCP SSE endpoint speaks **plain HTTP**. It is safe only when the
traffic never leaves the machine, so the default posture is loopback-only.

**Default (safe):** the MCP transport carries DNS-rebinding protection with an
allowlist of `127.0.0.1`, `localhost` and `[::1]`. Remote clients receive
`HTTP 421 Invalid Host header`. This is intentional and does not depend on
which address the server binds to.

**Serving remote / LAN clients.** Add the deployment's hostnames to the
allowlist:

```bash
-e MCP_SSE_ALLOWED_HOSTS=flaiwheel.example.com,flaiwheel.lan
```

Each entry is accepted both with and without a port. Loopback entries are
always retained, so SSH tunnels and Host-rewriting proxies keep working.

> ⚠️ **Allowlisting removes the `421` — it does not add encryption.** MCP
> traffic carries search queries, document content, bugfix summaries and write
> operations. On a non-localhost connection that is cleartext on the wire.
> See `architecture/2026-03-03-mcp-transport-security-tls-for-remote-deployments.md`:
> **TLS is required for any non-localhost deployment.** Configure it before
> announcing the endpoint:

| Deployment | Encrypted by | Allowlist needed |
|-----------|--------------|------------------|
| Same machine | n/a (loopback) | No |
| **Auto TLS** (`MCP_SSE_TLS_AUTO=true`) | Flaiwheel-issued certificate | ✅ yes |
| **Native TLS** (`MCP_SSE_TLS_CERTFILE` + `MCP_SSE_TLS_KEYFILE`) | Flaiwheel itself | ✅ yes |
| SSH local port forward (`ssh -L 8081:localhost:8081`) | SSH | No — arrives as `localhost` |
| WireGuard / Tailscale | Overlay VPN | No — arrives as `localhost` |
| Reverse proxy terminating TLS (Caddy/nginx) | Proxy | No — rewrite `Host` to `localhost` |
| Direct LAN / DNS access | ❌ nothing | ✅ yes — **then terminate TLS** |

**Native TLS.** Setting `MCP_SSE_TLS_CERTFILE` and `MCP_SSE_TLS_KEYFILE` serves
the MCP endpoint over HTTPS directly, so a remote deployment needs **no
reverse proxy**. Use the full chain, and keep the key readable only by the
container. This is **fail-closed**: a partial pair or an unreadable file aborts
startup rather than silently downgrading to plain HTTP, because an operator who
requested encryption must never unknowingly receive cleartext. The Web UI
(`MCP_WEB_PORT`) is *not* covered and remains plain HTTP.

**Auto TLS (`MCP_SSE_TLS_AUTO=true`).** A private IP cannot be certified by a
public CA, so obtaining a certificate for a LAN deployment is not possible in
the normal way. With this flag Flaiwheel issues its own: a private CA plus a
server certificate, generated on first start into `MCP_SSE_TLS_DIR`
(`/data/tls`), covering the allowlisted hosts, the hostname, loopback and the
machine's LAN address.

What this does and does not give you:

- ✅ **Confidentiality** — the link is encrypted (verified: TLSv1.3).
- ✅ **Server identity** — provided each client pins the CA once via
  `NODE_EXTRA_CA_CERTS=/data/tls/ca.pem`. This is trust-on-first-use, so the
  protection holds from the first connection onward.
- ⚠️ **No third-party attestation.** Nothing outside your deployment vouches
  for the certificate. That is the trade-off for a private address, and it is
  why the CA must stay in a persistent volume — regenerating it invalidates
  every client that pinned it.
- ❌ **Never** "make it work" with `NODE_TLS_REJECT_UNAUTHORIZED=0`. That
  disables verification for the whole client process and defeats the point of
  the exercise; it is not a supported configuration.

The key is written `0600`; the certificates are `0644` so clients can read the
CA. Auto TLS is **opt-in** because it changes the endpoint's scheme, and it
**fails closed**: if provisioning fails, startup aborts rather than serving
cleartext. If you need clients to connect with **no** configuration at all, use
a certificate from a real CA for a public hostname instead — a private address
can never be validated automatically.

**Do not disable the guard casually.** `MCP_SSE_DNS_REBINDING_PROTECTION=false`
turns off validation of **both** the `Host` and `Origin` headers for every
client, which is what protects a browser on the same network from DNS-rebinding
attacks against the endpoint. Flaiwheel logs a warning at startup when it is
off. Prefer allowlisting a specific hostname.

**`FASTMCP_HOST` does not work — do not rely on it.** `FastMCP.__init__` passes
`host` and `transport_security` into its `Settings(...)` as explicit init
arguments, and pydantic-settings gives init arguments precedence over
environment variables. Both `FASTMCP_HOST` and
`FASTMCP_TRANSPORT_SECURITY__ENABLE_DNS_REBINDING_PROTECTION` are therefore
read and silently discarded. Use `MCP_SSE_HOST` and
`MCP_SSE_ALLOWED_HOSTS` instead.

## Dependency Auditing

Project dependencies are audited with `pip-audit` against the OSV database. No known vulnerabilities exist in the current release (`pip-audit .` returns clean).

**`mcp` is pinned to `>=1.23.0,<2.0.0`.** Below 1.23.0 the MCP Python SDK shipped DNS-rebinding protection **disabled by default** for HTTP-based servers (CVE-2025-66416 / GHSA-9h52-p55h-vw2f): an unauthenticated localhost server could be reached by a malicious website via DNS rebinding, invoking tools on the user's behalf. 1.23.0 enables the guard automatically for loopback binds. Flaiwheel now passes `TransportSecuritySettings` explicitly, so the guard is on regardless — but the floor prevents a fresh resolve from landing on a build where the surrounding behaviour differs from what is documented and tested here.

## Disclosure Policy

We follow responsible disclosure. Once a fix is released, we will publish a summary in `CHANGELOG.md`. Credit will be given to reporters who wish to be acknowledged.
