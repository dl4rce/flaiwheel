# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""Console diagnostics for MCP stdio: stdout is reserved for JSON-RPC only."""

import sys


def diag(*args, **kwargs) -> None:
    """Print to stderr so MCP clients (Glama, Claude) parsing stdout JSON-RPC are not broken."""
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)
