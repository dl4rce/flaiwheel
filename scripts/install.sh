#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com
#
# One-command installer: sets up Flaiwheel for any project.
# Usage: curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
set -euo pipefail

# ── Colors ──────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[flaiwheel]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
fail()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── Banner ──────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         Flaiwheel Installer                  ║${NC}"
echo -e "${BOLD}║   Flywheel with AI, for AI                   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ══════════════════════════════════════════════════════
#  PHASE 1: Prerequisites (fail fast)
# ══════════════════════════════════════════════════════

info "Checking prerequisites..."

# 1. gh CLI installed
if ! command -v gh &>/dev/null; then
    fail "GitHub CLI (gh) not installed. Install it: https://cli.github.com"
fi

# 2. gh authenticated
if ! gh auth status &>/dev/null; then
    fail "GitHub CLI not authenticated. Run: gh auth login"
fi

# 3. Inside a git repo
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    fail "Not inside a git repository. Run this from your project root."
fi

# 4. Has a remote
REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$REMOTE_URL" ]; then
    fail "No git remote 'origin' found. Push your project to GitHub first."
fi

# 5. Docker installed and running
if ! command -v docker &>/dev/null; then
    fail "Docker not installed. Install it: https://docs.docker.com/get-docker/"
fi
if ! docker info &>/dev/null 2>&1; then
    fail "Docker is not running. Start Docker first."
fi

ok "All prerequisites met"

# ══════════════════════════════════════════════════════
#  PHASE 2: Detect project info from git remote
# ══════════════════════════════════════════════════════

# Extract owner and repo name from remote URL
# Handles: git@github.com:owner/repo.git  AND  https://github.com/owner/repo.git
OWNER=$(echo "$REMOTE_URL" | sed -E 's|.*[:/]([^/]+)/[^/]+\.git$|\1|; s|.*[:/]([^/]+)/[^/]+$|\1|')
PROJECT=$(echo "$REMOTE_URL" | sed -E 's|.*[:/][^/]+/([^/]+)\.git$|\1|; s|.*[:/][^/]+/([^/]+)$|\1|')
KNOWLEDGE_REPO="${PROJECT}-knowledge"
PROJECT_DIR=$(git rev-parse --show-toplevel)

info "Project:        ${BOLD}${OWNER}/${PROJECT}${NC}"
info "Knowledge repo: ${BOLD}${OWNER}/${KNOWLEDGE_REPO}${NC}"
info "Project dir:    ${PROJECT_DIR}"
echo ""

# ══════════════════════════════════════════════════════
#  PHASE 3: Create knowledge repo (if it doesn't exist)
# ══════════════════════════════════════════════════════

if gh repo view "${OWNER}/${KNOWLEDGE_REPO}" &>/dev/null 2>&1; then
    ok "Knowledge repo ${OWNER}/${KNOWLEDGE_REPO} already exists"
    KNOWLEDGE_REPO_URL="https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git"
else
    info "Creating knowledge repo ${OWNER}/${KNOWLEDGE_REPO} (private)..."

    gh repo create "${OWNER}/${KNOWLEDGE_REPO}" --private --description "Knowledge base for ${PROJECT} (managed by Flaiwheel)" || \
        fail "Failed to create repo. Check your gh permissions."

    # Clone, init structure, push
    TMPDIR=$(mktemp -d)
    git clone "https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git" "$TMPDIR" 2>/dev/null || \
        gh repo clone "${OWNER}/${KNOWLEDGE_REPO}" "$TMPDIR" 2>/dev/null

    pushd "$TMPDIR" > /dev/null

    mkdir -p architecture api bugfix-log best-practices setup changelog

    cat > README.md << 'READMEEOF'
# Project Knowledge Base

This knowledge base is managed by [Flaiwheel](https://github.com/dl4rce/flaiwheel).

## Structure

| Folder | Content |
|--------|---------|
| `architecture/` | System design, ADRs, diagrams |
| `api/` | Endpoint docs, contracts, schemas |
| `bugfix-log/` | Auto-generated bugfix summaries |
| `best-practices/` | Coding standards, patterns |
| `setup/` | Deployment, environment setup |
| `changelog/` | Release notes |

## How it works

AI agents write bugfix summaries here automatically. Documentation is indexed into a vector database and served via MCP, so every agent benefits from past knowledge.
READMEEOF

    # Placeholder READMEs so folders are tracked
    for dir in architecture api bugfix-log best-practices setup changelog; do
        echo "# ${dir}" > "${dir}/README.md"
    done

    git add -A
    git commit -m "init: knowledge base structure (created by Flaiwheel installer)"
    git push origin main 2>/dev/null || git push origin master 2>/dev/null

    popd > /dev/null
    rm -rf "$TMPDIR"

    KNOWLEDGE_REPO_URL="https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git"
    ok "Knowledge repo created and initialized"
fi

echo ""

# ══════════════════════════════════════════════════════
#  PHASE 4: Get GitHub token for Flaiwheel container
# ══════════════════════════════════════════════════════

GH_TOKEN=$(gh auth token 2>/dev/null || true)
if [ -z "$GH_TOKEN" ]; then
    fail "Could not retrieve GitHub token from gh CLI. Run: gh auth login"
fi

# ══════════════════════════════════════════════════════
#  PHASE 5: Build and start Flaiwheel Docker container
# ══════════════════════════════════════════════════════

CONTAINER_NAME="flaiwheel-${PROJECT}"
VOLUME_NAME="flaiwheel-${PROJECT}-data"
IMAGE_NAME="flaiwheel:latest"
FLAIWHEEL_REPO="https://github.com/dl4rce/flaiwheel.git"

# Build image if it doesn't exist locally
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    info "Building Flaiwheel Docker image (first time only)..."

    BUILD_DIR=$(mktemp -d)
    GH_TOKEN_FOR_CLONE=$(gh auth token 2>/dev/null || true)

    CLONE_URL=$(echo "$FLAIWHEEL_REPO" | sed "s|https://|https://${GH_TOKEN_FOR_CLONE}@|")
    git clone --depth 1 "$CLONE_URL" "$BUILD_DIR" 2>/dev/null || \
        fail "Could not clone Flaiwheel repo. Check your gh permissions for dl4rce/flaiwheel."

    docker build -t "$IMAGE_NAME" "$BUILD_DIR" || \
        fail "Docker build failed. Check the build output above."

    rm -rf "$BUILD_DIR"
    ok "Docker image built: ${IMAGE_NAME}"
else
    ok "Docker image ${IMAGE_NAME} already exists"
fi

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    warn "Container ${CONTAINER_NAME} already exists"
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        ok "Container is already running"
    else
        info "Starting existing container..."
        docker start "$CONTAINER_NAME"
        ok "Container started"
    fi
else
    info "Starting Flaiwheel container: ${CONTAINER_NAME}..."

    docker run -d \
        --name "$CONTAINER_NAME" \
        -p 8080:8080 \
        -p 8081:8081 \
        -e MCP_GIT_REPO_URL="$KNOWLEDGE_REPO_URL" \
        -e MCP_GIT_TOKEN="$GH_TOKEN" \
        -e MCP_GIT_AUTO_PUSH=true \
        -v "${VOLUME_NAME}:/data" \
        --restart unless-stopped \
        "$IMAGE_NAME"

    ok "Flaiwheel container started"
fi

# Wait for container to be healthy and extract credentials
info "Waiting for Flaiwheel to be ready..."
ADMIN_PASS=""
for i in $(seq 1 60); do
    if curl -sf http://localhost:8080/health &>/dev/null; then
        ADMIN_PASS=$(docker logs "$CONTAINER_NAME" 2>&1 | grep "Password:" | tail -1 | awk '{print $NF}' || true)
        break
    fi
    sleep 2
done

if [ -z "$ADMIN_PASS" ]; then
    warn "Could not extract credentials automatically."
    warn "Run this to get them:  docker logs ${CONTAINER_NAME} 2>&1 | grep 'Password:'"
else
    ok "Flaiwheel is ready"
fi

echo ""

# ══════════════════════════════════════════════════════
#  PHASE 6: Create Cursor MCP config
# ══════════════════════════════════════════════════════

CURSOR_DIR="${PROJECT_DIR}/.cursor"
MCP_JSON="${CURSOR_DIR}/mcp.json"

mkdir -p "$CURSOR_DIR"

if [ -f "$MCP_JSON" ]; then
    # Check if flaiwheel is already configured
    if grep -q "flaiwheel" "$MCP_JSON" 2>/dev/null; then
        ok ".cursor/mcp.json already has flaiwheel configured"
    else
        warn ".cursor/mcp.json exists but doesn't have flaiwheel"
        warn "Add this manually to your mcpServers:"
        echo '    "flaiwheel": { "url": "http://localhost:8081/sse" }'
    fi
else
    cat > "$MCP_JSON" << 'EOF'
{
  "mcpServers": {
    "flaiwheel": {
      "url": "http://localhost:8081/sse"
    }
  }
}
EOF
    ok "Created .cursor/mcp.json"
fi

# ══════════════════════════════════════════════════════
#  PHASE 7: Create Cursor rule for AI agents
# ══════════════════════════════════════════════════════

RULES_DIR="${CURSOR_DIR}/rules"
RULE_FILE="${RULES_DIR}/flaiwheel.mdc"

mkdir -p "$RULES_DIR"

cat > "$RULE_FILE" << 'EOF'
---
description: Flaiwheel knowledge base integration
globs: *
---

# Flaiwheel – Knowledge Base MCP

This project uses **Flaiwheel**, a self-improving knowledge base served via MCP.
The MCP endpoint is at http://localhost:8081/sse.

## How the knowledge flywheel works

Every bugfix you document and every doc you update gets pushed to the knowledge repo,
which triggers automatic reindexing. The next time any AI agent searches, it finds
that new knowledge. This means: **every bug fixed makes the next bug cheaper to fix.**

The cycle: fix bug → document via `write_bugfix_summary` → auto-push to repo → reindex → better search results → faster next fix

**You are part of this cycle. Always close the loop by documenting what you did.**

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search only bugfix summaries |
| `search_by_type(query, doc_type, top_k)` | Filter by: docs, bugfix, best-practice, api, architecture, changelog, setup, readme |
| `write_bugfix_summary(title, root_cause, solution, lesson_learned, affected_files, tags)` | Document a bugfix (auto-pushed + reindexed) |
| `get_index_stats()` | Show index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base consistency |

## Rules — MANDATORY

### Before writing or changing code:
1. **ALWAYS** call `search_docs("what you're about to change")` first
2. Call `search_bugfixes("the problem you're solving")` to check for similar past issues
3. Prefer 2-3 targeted searches over one vague query

### After fixing a bug:
1. **ALWAYS** call `write_bugfix_summary()` with:
   - Clear title describing the bug
   - Technical root cause
   - What was changed to fix it
   - What should be done differently next time
2. This is **mandatory** — skipping this breaks the flywheel

### After updating documentation or architecture decisions:
1. If you update or create .md files in the knowledge repo, call `reindex()` so changes are searchable immediately

### Periodically:
1. Call `check_knowledge_quality()` to find issues in the knowledge base
2. Fix critical issues immediately
EOF

ok "Created .cursor/rules/flaiwheel.mdc"

# ══════════════════════════════════════════════════════
#  PHASE 7b: Create AGENTS.md (for Claude Code and other agents)
# ══════════════════════════════════════════════════════

AGENTS_FILE="${PROJECT_DIR}/AGENTS.md"

if [ -f "$AGENTS_FILE" ]; then
    if grep -q "flaiwheel\|Flaiwheel" "$AGENTS_FILE" 2>/dev/null; then
        ok "AGENTS.md already has Flaiwheel section"
    else
        cat >> "$AGENTS_FILE" << 'AGENTSEOF'

---

## Flaiwheel — Knowledge Base (MCP)

This project uses **Flaiwheel** for self-improving documentation search.
MCP endpoint: `http://localhost:8081/sse`

### The knowledge flywheel

Every bugfix documented and every doc updated gets pushed to the knowledge repo,
triggering automatic reindexing. The next agent search finds that new knowledge.
**Every bug fixed makes the next bug cheaper to fix.**

### Mandatory workflow

1. **Before changing code:** call `search_docs("what you're changing")` and `search_bugfixes("the problem")`
2. **After fixing a bug:** call `write_bugfix_summary(title, root_cause, solution, lesson_learned, affected_files, tags)` — this auto-pushes to the knowledge repo and reindexes
3. **After updating docs:** call `reindex()` so changes are searchable immediately
4. **Periodically:** call `check_knowledge_quality()` and fix issues

### Available tools

| Tool | Purpose |
|------|---------|
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search bugfix summaries only |
| `search_by_type(query, doc_type, top_k)` | Filter by type: docs, bugfix, best-practice, api, architecture, changelog, setup, readme |
| `write_bugfix_summary(...)` | Document a bugfix (auto-pushed + reindexed) |
| `get_index_stats()` | Index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base |
AGENTSEOF
        ok "Appended Flaiwheel section to existing AGENTS.md"
    fi
else
    cat > "$AGENTS_FILE" << 'AGENTSEOF'
# AI Agent Instructions

## Flaiwheel — Knowledge Base (MCP)

This project uses **Flaiwheel** for self-improving documentation search.
MCP endpoint: `http://localhost:8081/sse`

### The knowledge flywheel

Every bugfix documented and every doc updated gets pushed to the knowledge repo,
triggering automatic reindexing. The next agent search finds that new knowledge.
**Every bug fixed makes the next bug cheaper to fix.**

### Mandatory workflow

1. **Before changing code:** call `search_docs("what you're changing")` and `search_bugfixes("the problem")`
2. **After fixing a bug:** call `write_bugfix_summary(title, root_cause, solution, lesson_learned, affected_files, tags)` — this auto-pushes to the knowledge repo and reindexes
3. **After updating docs:** call `reindex()` so changes are searchable immediately
4. **Periodically:** call `check_knowledge_quality()` and fix issues

### Available tools

| Tool | Purpose |
|------|---------|
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search bugfix summaries only |
| `search_by_type(query, doc_type, top_k)` | Filter by type: docs, bugfix, best-practice, api, architecture, changelog, setup, readme |
| `write_bugfix_summary(...)` | Document a bugfix (auto-pushed + reindexed) |
| `get_index_stats()` | Index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base |
AGENTSEOF
    ok "Created AGENTS.md with Flaiwheel instructions"
fi

# ══════════════════════════════════════════════════════
#  PHASE 8: Detect existing docs and create migration guide
# ══════════════════════════════════════════════════════

MD_COUNT=$(find "$PROJECT_DIR" -name "*.md" \
    -not -path "*/.git/*" \
    -not -path "*/.cursor/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/vendor/*" \
    -not -path "*/dist/*" \
    -not -path "*/.next/*" \
    | wc -l | tr -d ' ')

if [ "$MD_COUNT" -gt 2 ]; then
    MIGRATE_FILE="${RULES_DIR}/flaiwheel-migrate.mdc"

    cat > "$MIGRATE_FILE" << MIGRATEEOF
---
description: Flaiwheel migration guide — existing documentation detected
globs: *
alwaysApply: true
---

# Flaiwheel Migration — Existing Documentation Detected

This project has **${MD_COUNT} markdown files** that may contain valuable knowledge.
A dedicated knowledge repo has been created at: **${OWNER}/${KNOWLEDGE_REPO}**

## Your task (AI agent)

When the user starts a conversation or asks about setup/documentation, proactively offer to help migrate existing docs:

1. **Scan** the project for .md files (exclude .git, .cursor, node_modules, vendor, dist)
2. **Categorize** each file:
   - System design, ADRs, architecture decisions → \`architecture/\`
   - API docs, endpoint specs, schemas → \`api/\`
   - Bug reports, incident postmortems → \`bugfix-log/\`
   - Coding standards, patterns, conventions → \`best-practices/\`
   - Deploy guides, environment setup, install instructions → \`setup/\`
   - Release notes, version history → \`changelog/\`
3. **Present** a migration plan to the user (table: source file → destination folder)
4. **Ask** the user to confirm before copying anything
5. **Copy** approved files to the knowledge repo (clone it, copy, commit, push)
6. **Run** \`reindex()\` via MCP after migration
7. **Run** \`check_knowledge_quality()\` to verify

## Important
- Do NOT move files from the project — COPY them to the knowledge repo
- Do NOT delete this rule file — the user can remove it after migration is complete
- If the user says "migrate docs" or "organize knowledge", start this process immediately
MIGRATEEOF

    ok "Detected ${MD_COUNT} markdown files — created migration guide"
    info "Cursor AI will offer to organize them into the knowledge repo"
else
    info "Few or no existing docs detected — skipping migration guide"
fi

echo ""

# ══════════════════════════════════════════════════════
#  PHASE 9: Add .cursor entries to .gitignore (if needed)
# ══════════════════════════════════════════════════════

GITIGNORE="${PROJECT_DIR}/.gitignore"
if [ -f "$GITIGNORE" ]; then
    if ! grep -q "\.cursor/mcp\.json" "$GITIGNORE" 2>/dev/null; then
        echo "" >> "$GITIGNORE"
        echo "# Flaiwheel (local MCP config — token may differ per developer)" >> "$GITIGNORE"
        echo ".cursor/mcp.json" >> "$GITIGNORE"
        ok "Added .cursor/mcp.json to .gitignore (contains local config)"
    fi
else
    cat > "$GITIGNORE" << 'EOF'
# Flaiwheel (local MCP config — token may differ per developer)
.cursor/mcp.json
EOF
    ok "Created .gitignore with .cursor/mcp.json exclusion"
fi

# ══════════════════════════════════════════════════════
#  Done
# ══════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         Setup Complete                       ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}What was created:${NC}"
echo -e "    Knowledge repo:  ${GREEN}https://github.com/${OWNER}/${KNOWLEDGE_REPO}${NC}"
echo -e "    Container:       ${GREEN}${CONTAINER_NAME}${NC}"
echo -e "    Cursor config:   ${GREEN}.cursor/mcp.json${NC} + ${GREEN}.cursor/rules/flaiwheel.mdc${NC}"
echo -e "    Agent guide:     ${GREEN}AGENTS.md${NC}"
echo ""
echo -e "  ${BOLD}What to do next:${NC}"
echo -e "    1. Restart Cursor to activate the MCP connection"
echo -e "    2. Open the Web UI at ${GREEN}http://localhost:8080${NC} to verify"
echo -e "    3. See the full README: ${GREEN}https://github.com/dl4rce/flaiwheel#readme${NC}"
echo ""
if [ "$MD_COUNT" -gt 2 ]; then
    echo -e "  ${YELLOW}Tip:${NC} Tell Cursor AI: \"migrate docs\" to organize existing"
    echo -e "       documentation into the knowledge repo."
    echo ""
fi
echo -e "  ${BOLD}Endpoints:${NC}"
echo -e "    Web UI:     ${GREEN}http://localhost:8080${NC}"
echo -e "    MCP (SSE):  ${GREEN}http://localhost:8081/sse${NC}"
echo ""
if [ -n "${ADMIN_PASS:-}" ]; then
    echo -e "  ${BOLD}╔════════════════════════════════════════════╗${NC}"
    echo -e "  ${BOLD}║  Web UI Login                              ║${NC}"
    echo -e "  ${BOLD}║                                            ║${NC}"
    echo -e "  ${BOLD}║  Username:  ${GREEN}admin${NC}${BOLD}                           ║${NC}"
    echo -e "  ${BOLD}║  Password:  ${GREEN}${ADMIN_PASS}${NC}${BOLD}              ║${NC}"
    echo -e "  ${BOLD}║                                            ║${NC}"
    echo -e "  ${BOLD}║  ${YELLOW}Save this — it won't be shown again!${NC}${BOLD}     ║${NC}"
    echo -e "  ${BOLD}╚════════════════════════════════════════════╝${NC}"
else
    echo -e "  ${YELLOW}To retrieve your Web UI credentials:${NC}"
    echo -e "    docker logs ${CONTAINER_NAME} 2>&1 | grep 'Password:'"
fi
echo ""
