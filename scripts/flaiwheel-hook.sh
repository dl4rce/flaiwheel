#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE. Commercial licensing: info@4rce.com
#
# post-commit hook — captures git commits as structured knowledge docs.
# Installed automatically by install.sh into .git/hooks/post-commit
#
# This script NEVER blocks a commit. All failures are silent.
# It only captures Conventional Commit types: fix, feat, refactor, perf, docs
#
# No credentials needed: Flaiwheel trusts requests from localhost (127.0.0.1).

set -euo pipefail

# ── Load local Flaiwheel config ──────────────────────────────────────────────
# Config is written by install.sh to .cursor/flaiwheel-hook.conf (gitignored).
# Only FLAIWHEEL_URL and FLAIWHEEL_PROJECT are needed — no password required.
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
CONF_FILE="${PROJECT_ROOT}/.cursor/flaiwheel-hook.conf"

if [ ! -f "$CONF_FILE" ]; then
    exit 0
fi

# shellcheck source=/dev/null
source "$CONF_FILE"
# Variables expected after sourcing:
#   FLAIWHEEL_URL      e.g. http://localhost:8080
#   FLAIWHEEL_PROJECT  e.g. myproject

# ── Validate config ──────────────────────────────────────────────────────────
if [ -z "${FLAIWHEEL_URL:-}" ] || [ -z "${FLAIWHEEL_PROJECT:-}" ]; then
    exit 0
fi

# ── Check Flaiwheel is reachable (fail silently if offline) ──────────────────
if ! curl -sf --connect-timeout 2 "${FLAIWHEEL_URL}/health" > /dev/null 2>&1; then
    exit 0
fi

# ── Read commit info ─────────────────────────────────────────────────────────
COMMIT_HASH="$(git log -1 --format='%H' 2>/dev/null)" || exit 0
COMMIT_MSG="$(git log -1 --format='%s' 2>/dev/null)"  || exit 0

# Parse Conventional Commit prefix: type(scope): message
# Matches: fix:, feat(auth):, refactor: etc.
COMMIT_TYPE="$(echo "$COMMIT_MSG" | sed -nE 's/^([a-z]+)(\([^)]+\))?!?:.*/\1/p')"
COMMIT_SCOPE="$(echo "$COMMIT_MSG" | sed -nE 's/^[a-z]+\(([^)]+)\)!?:.*/\1/p')"
COMMIT_BODY="$(echo "$COMMIT_MSG" | sed -nE 's/^[a-z]+(\([^)]+\))?!?:[[:space:]]*(.*)/\2/p')"

# Only capture actionable types — skip chore, test, ci, style, build
case "${COMMIT_TYPE}" in
    fix|feat|refactor|perf|docs) ;;
    *) exit 0 ;;
esac

# ── Build list of changed files ───────────────────────────────────────────────
# Use HEAD~1 if available, else list all files from HEAD (first commit edge case)
if git rev-parse HEAD~1 > /dev/null 2>&1; then
    FILES_RAW="$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)"
else
    FILES_RAW="$(git show --name-only --format='' HEAD 2>/dev/null || true)"
fi

# Build a JSON array of filenames using Python3 (always available on systems with git)
FILES_JSON="$(python3 -c "
import json, sys
lines = [l.strip() for l in '''${FILES_RAW}'''.strip().splitlines() if l.strip()]
print(json.dumps(lines))
" 2>/dev/null)" || FILES_JSON="[]"

# ── Build diff summary (first 500 chars of stat) ─────────────────────────────
DIFF_SUMMARY="$(git diff --stat HEAD~1 HEAD 2>/dev/null | head -20 || true)"
if [ -z "$DIFF_SUMMARY" ]; then
    DIFF_SUMMARY="$(git show --stat --format='' HEAD 2>/dev/null | head -20 || true)"
fi

# ── Build JSON payload ───────────────────────────────────────────────────────
PAYLOAD="$(python3 -c "
import json
payload = {
    'commit_hash':   '${COMMIT_HASH}',
    'commit_type':   '${COMMIT_TYPE}',
    'commit_message': '${COMMIT_BODY:-$COMMIT_MSG}'.replace(\"'\", '').replace('\"', ''),
    'commit_scope':  '${COMMIT_SCOPE}',
    'files_changed': ${FILES_JSON},
    'diff_summary':  '''${DIFF_SUMMARY}'''[:500],
}
print(json.dumps(payload))
" 2>/dev/null)" || exit 0

# ── POST to Flaiwheel REST API ────────────────────────────────────────────────
# No credentials needed — Flaiwheel trusts requests from 127.0.0.1 (localhost).
RESPONSE="$(curl -sf \
    --connect-timeout 5 \
    --max-time 15 \
    -X POST \
    "${FLAIWHEEL_URL}/api/capture-commit?project=${FLAIWHEEL_PROJECT}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" 2>/dev/null)" || exit 0

# ── Show brief confirmation (non-blocking, friendly) ─────────────────────────
STATUS="$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "?")"
FILENAME="$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('filename',''))" 2>/dev/null || echo "")"

if [ "$STATUS" = "captured" ] && [ -n "$FILENAME" ]; then
    echo "[flaiwheel] ✓ Knowledge captured → ${FILENAME}"
elif [ "$STATUS" = "skipped" ]; then
    : # silently skip non-captured types
fi

exit 0
