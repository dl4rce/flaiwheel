#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE.md. Commercial licensing: info@4rce.com
#
# Manual reindex trigger via CLI (requires auth)
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: reindex.sh <username> <password>"
    exit 1
fi
echo "Triggering reindex..."
curl -s -u "$1:$2" -X POST http://localhost:8080/api/reindex | python -m json.tool
