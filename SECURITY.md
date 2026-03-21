# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.9.x (latest) | ✅ |
| < 3.9 | ❌ |

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

## Dependency Auditing

Project dependencies are audited with `pip-audit` against the OSV database. No known vulnerabilities exist in the current release (`pip-audit .` returns clean).

## Disclosure Policy

We follow responsible disclosure. Once a fix is released, we will publish a summary in `CHANGELOG.md`. Credit will be given to reporters who wish to be acknowledged.
