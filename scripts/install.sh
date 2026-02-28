#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE.md. Commercial licensing: info@4rce.com
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
echo -e "${BOLD}║         Flaiwheel Install / Update            ║${NC}"
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
REPO_NAME=$(echo "$REMOTE_URL" | sed -E 's|.*[:/][^/]+/([^/]+)\.git$|\1|; s|.*[:/][^/]+/([^/]+)$|\1|')
PROJECT_DIR=$(git rev-parse --show-toplevel)

# If running from inside a knowledge repo (ends with -knowledge), derive the
# actual project name so we don't create double-suffixed repos or containers
if [[ "$REPO_NAME" == *-knowledge ]]; then
    PROJECT="${REPO_NAME%-knowledge}"
    KNOWLEDGE_REPO="$REPO_NAME"
    warn "Running from inside the knowledge repo (${REPO_NAME})"
    info "Derived project name: ${BOLD}${PROJECT}${NC}"
else
    PROJECT="$REPO_NAME"
    KNOWLEDGE_REPO="${PROJECT}-knowledge"
fi

CONTAINER_NAME="flaiwheel-${PROJECT}"
VOLUME_NAME="flaiwheel-${PROJECT}-data"
IMAGE_NAME="flaiwheel:latest"
FLAIWHEEL_REPO="https://github.com/dl4rce/flaiwheel.git"

info "Project:        ${BOLD}${OWNER}/${PROJECT}${NC}"
info "Knowledge repo: ${BOLD}${OWNER}/${KNOWLEDGE_REPO}${NC}"
info "Project dir:    ${PROJECT_DIR}"
echo ""

# ══════════════════════════════════════════════════════
#  FAST PATH: detect running Flaiwheel → skip Docker
# ══════════════════════════════════════════════════════

FAST_PATH=false
RUNNING_FW=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^flaiwheel-' | head -1 || true)

if [ -n "$RUNNING_FW" ] && curl -sf http://localhost:8080/health &>/dev/null; then
    FAST_PATH=true
    echo -e "${GREEN}${BOLD}[✓] Flaiwheel already running (${RUNNING_FW}). Fast-connecting this project...${NC}"
    echo ""
fi

# ══════════════════════════════════════════════════════
#  PHASE 2b: Detect existing installation → update mode
#  (skipped on fast path — container is healthy, no rebuild needed)
# ══════════════════════════════════════════════════════

UPDATE_MODE=false

if [ "$FAST_PATH" = false ]; then
    # First: check for exact container name match
    # Second: check if ANY flaiwheel container is using ports 8080/8081
    EXISTING_CONTAINER=""

    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        EXISTING_CONTAINER="$CONTAINER_NAME"
    else
        PORT_CONTAINER=$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null \
            | grep -E '(8080|8081)' \
            | grep -E '^flaiwheel-' \
            | awk '{print $1}' \
            | head -1 || true)
        if [ -n "$PORT_CONTAINER" ]; then
            EXISTING_CONTAINER="$PORT_CONTAINER"
            warn "Found existing flaiwheel container '${PORT_CONTAINER}' on ports 8080/8081"
            warn "This may have been created under a different project name"
        fi
    fi

    if [ -n "$EXISTING_CONTAINER" ]; then
        echo ""
        echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
        echo -e "${BOLD}║  Existing installation detected!              ║${NC}"
        echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
        echo ""

        CURRENT_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$EXISTING_CONTAINER" 2>/dev/null || echo "unknown")
        CONTAINER_STATUS=$(docker inspect --format '{{.State.Status}}' "$EXISTING_CONTAINER" 2>/dev/null || echo "unknown")
        CREATED_AT=$(docker inspect --format '{{.Created}}' "$EXISTING_CONTAINER" 2>/dev/null | cut -d'T' -f1 || echo "unknown")
        echo -e "  Container:  ${GREEN}${EXISTING_CONTAINER}${NC} (${CONTAINER_STATUS})"
        echo -e "  Image:      ${CURRENT_IMAGE}"
        echo -e "  Created:    ${CREATED_AT}"
        echo ""

        read -p "  Update to latest version? [Y/n] " -n 1 -r REPLY
        echo ""

        if [[ "$REPLY" =~ ^[Nn]$ ]]; then
            info "Update cancelled. Existing installation unchanged."
            exit 0
        fi

        UPDATE_MODE=true
        ok "Update mode — will rebuild image and recreate container"

        OLD_ENV=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$EXISTING_CONTAINER" 2>/dev/null || true)
        OLD_REPO_URL=$(echo "$OLD_ENV" | grep "^MCP_GIT_REPO_URL=" | cut -d= -f2- || true)
        OLD_AUTO_PUSH=$(echo "$OLD_ENV" | grep "^MCP_GIT_AUTO_PUSH=" | cut -d= -f2- || true)
        OLD_WEBHOOK_SECRET=$(echo "$OLD_ENV" | grep "^MCP_WEBHOOK_SECRET=" | cut -d= -f2- || true)

        OLD_VOLUME=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$EXISTING_CONTAINER" 2>/dev/null || true)
        if [ -n "$OLD_VOLUME" ]; then
            VOLUME_NAME="$OLD_VOLUME"
        fi

        OLD_CONTAINER_NAME="$EXISTING_CONTAINER"
        echo ""
    fi
fi

# ══════════════════════════════════════════════════════
#  PHASE 3: Create knowledge repo (if it doesn't exist)
# ══════════════════════════════════════════════════════

if gh repo view "${OWNER}/${KNOWLEDGE_REPO}" &>/dev/null 2>&1; then
    ok "Knowledge repo ${OWNER}/${KNOWLEDGE_REPO} already exists"
    KNOWLEDGE_REPO_URL="https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git"

    # Ensure FLAIWHEEL_TOOLS.md exists (add/update for existing repos)
    TMPDIR=$(mktemp -d)
    if gh repo clone "${OWNER}/${KNOWLEDGE_REPO}" "$TMPDIR" 2>/dev/null; then
        pushd "$TMPDIR" > /dev/null
        cat > FLAIWHEEL_TOOLS.md << 'TOOLSEOF'
# Flaiwheel MCP Tools

All tools accept an optional `project` parameter. When omitted, the active project (set via `set_project`) is used.

| Tool | Purpose |
|------|---------|
| `set_project(name)` | **Bind session to a project** (call at start of every conversation!) |
| `setup_project(name, git_repo_url, ...)` | Register + index a new project (auto-binds) |
| `get_active_project()` | Show which project is currently bound |
| `list_projects()` | List all registered projects with stats |
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search only bugfix summaries |
| `search_by_type(query, doc_type, top_k)` | Filter by type |
| `write_bugfix_summary(...)` | Document a bugfix (auto-pushed + reindexed) |
| `write_architecture_doc(...)` | Document architecture decisions |
| `write_api_doc(...)` | Document API endpoints |
| `write_best_practice(...)` | Document coding standards |
| `write_setup_doc(...)` | Document setup/deployment |
| `write_changelog_entry(...)` | Document release notes |
| `write_test_case(...)` | Document test cases (auto-pushed + reindexed) |
| `search_tests(query, top_k)` | Search test cases for coverage and patterns |
| `validate_doc(content, category)` | Validate markdown before committing |
| `git_pull_reindex()` | Pull latest from knowledge repo + re-index |
| `get_index_stats()` | Show index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base consistency |
| `check_update()` | Check if a newer Flaiwheel version is available |
| `analyze_knowledge_repo()` | Analyse knowledge repo structure and quality |
| `execute_cleanup(actions)` | Execute approved cleanup actions (never deletes files) |
| `classify_documents(files)` | Classify project docs for migration into knowledge base |
| `save_session_summary(...)` | Save session context for continuity (call at end of session) |
| `get_recent_sessions(limit)` | Retrieve recent session summaries (call at start of session) |

## "This is the Way" — Knowledge Bootstrap

Got a messy project with docs scattered everywhere? Tell your AI agent **"This is the Way"** (or just **"42"**) and it will:

### For NEW projects (docs in project repo, not yet in knowledge):
1. Scan the project directory locally for documentation files (.md, .txt, .pdf, .html, .rst, .docx)
2. Read the first ~2000 chars of each file
3. `classify_documents(files=JSON)` — Flaiwheel classifies using its embedding model
4. Review the migration plan with you (categories, duplicates, rewrite needs)
5. For each approved file: read it, restructure if needed, use the suggested `write_*` tool
6. `reindex()` — finalize

### For EXISTING knowledge repos (files already inside, but messy):
1. `analyze_knowledge_repo()` — full read-only scan of the knowledge repo
2. Review the report with you
3. `execute_cleanup(actions)` — execute only the actions you approve
4. `reindex()` — finalize

**Hard rule:** Flaiwheel never deletes files. It classifies, moves, and suggests — you decide.
TOOLSEOF
        # Ensure all expected directories exist with proper placeholder READMEs
        for dir in architecture api bugfix-log best-practices setup changelog tests; do
            mkdir -p "$dir"
            if [ ! -f "${dir}/README.md" ] || [ "$(wc -c < "${dir}/README.md")" -lt 30 ]; then
                echo -e "# ${dir}\n\nThis directory contains ${dir} documentation managed by Flaiwheel.\nAdd .md files here or use the corresponding write tool." > "${dir}/README.md"
            fi
        done
        git add -A
        git diff --staged --quiet || { git commit -m "docs: add/update Flaiwheel tools + ensure directory structure" && git push origin main 2>/dev/null || git push origin master 2>/dev/null; }
        popd > /dev/null
        ok "Knowledge repo updated (tools + directory structure)"
    fi
    rm -rf "$TMPDIR"
else
    info "Creating knowledge repo ${OWNER}/${KNOWLEDGE_REPO} (private)..."

    gh repo create "${OWNER}/${KNOWLEDGE_REPO}" --private --description "Knowledge base for ${PROJECT} (managed by Flaiwheel)" || \
        fail "Failed to create repo. Check your gh permissions."

    # Clone, init structure, push
    TMPDIR=$(mktemp -d)
    git clone "https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git" "$TMPDIR" 2>/dev/null || \
        gh repo clone "${OWNER}/${KNOWLEDGE_REPO}" "$TMPDIR" 2>/dev/null

    pushd "$TMPDIR" > /dev/null

    mkdir -p architecture api bugfix-log best-practices setup changelog tests

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
| `tests/` | Test cases, scenarios, regression patterns |

## How it works

AI agents write bugfix summaries here automatically. Documentation is indexed into a vector database and served via MCP, so every agent benefits from past knowledge.
READMEEOF

    cat > FLAIWHEEL_TOOLS.md << 'TOOLSEOF'
# Flaiwheel MCP Tools

All tools accept an optional `project` parameter. When omitted, the active project (set via `set_project`) is used.

| Tool | Purpose |
|------|---------|
| `set_project(name)` | **Bind session to a project** (call at start of every conversation!) |
| `setup_project(name, git_repo_url, ...)` | Register + index a new project (auto-binds) |
| `get_active_project()` | Show which project is currently bound |
| `list_projects()` | List all registered projects with stats |
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search only bugfix summaries |
| `search_by_type(query, doc_type, top_k)` | Filter by type |
| `write_bugfix_summary(...)` | Document a bugfix (auto-pushed + reindexed) |
| `write_architecture_doc(...)` | Document architecture decisions |
| `write_api_doc(...)` | Document API endpoints |
| `write_best_practice(...)` | Document coding standards |
| `write_setup_doc(...)` | Document setup/deployment |
| `write_changelog_entry(...)` | Document release notes |
| `write_test_case(...)` | Document test cases (auto-pushed + reindexed) |
| `search_tests(query, top_k)` | Search test cases for coverage and patterns |
| `validate_doc(content, category)` | Validate markdown before committing |
| `git_pull_reindex()` | Pull latest from knowledge repo + re-index |
| `get_index_stats()` | Show index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base consistency |
| `check_update()` | Check if a newer Flaiwheel version is available |
| `analyze_knowledge_repo()` | Analyse knowledge repo structure and quality |
| `execute_cleanup(actions)` | Execute approved cleanup actions (never deletes files) |
| `classify_documents(files)` | Classify project docs for migration into knowledge base |
| `save_session_summary(...)` | Save session context for continuity (call at end of session) |
| `get_recent_sessions(limit)` | Retrieve recent session summaries (call at start of session) |

## "This is the Way" — Knowledge Bootstrap

Got a messy project with docs scattered everywhere? Tell your AI agent **"This is the Way"** (or just **"42"**) and it will:

### For NEW projects (docs in project repo, not yet in knowledge):
1. Scan the project directory locally for documentation files (.md, .txt, .pdf, .html, .rst, .docx)
2. Read the first ~2000 chars of each file
3. `classify_documents(files=JSON)` — Flaiwheel classifies using its embedding model
4. Review the migration plan with you (categories, duplicates, rewrite needs)
5. For each approved file: read it, restructure if needed, use the suggested `write_*` tool
6. `reindex()` — finalize

### For EXISTING knowledge repos (files already inside, but messy):
1. `analyze_knowledge_repo()` — full read-only scan of the knowledge repo
2. Review the report with you
3. `execute_cleanup(actions)` — execute only the actions you approve
4. `reindex()` — finalize

**Hard rule:** Flaiwheel never deletes files. It classifies, moves, and suggests — you decide.
TOOLSEOF

    # Placeholder READMEs so folders are tracked
    for dir in architecture api bugfix-log best-practices setup changelog tests; do
        echo -e "# ${dir}\n\nThis directory contains ${dir} documentation managed by Flaiwheel.\nAdd .md files here or use the corresponding write tool." > "${dir}/README.md"
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
#  (skipped entirely on fast path — container already running)
# ══════════════════════════════════════════════════════

KNOWLEDGE_REPO_URL="${KNOWLEDGE_REPO_URL:-https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git}"

if [ "$FAST_PATH" = true ]; then
    # ── Fast path: register project with the already-running container ──
    info "Registering project '${PROJECT}' via API..."

    REG_PASS=$(docker exec "$RUNNING_FW" cat /data/.admin_password 2>/dev/null || true)
    if [ -z "$REG_PASS" ]; then
        REG_PASS=$(docker logs "$RUNNING_FW" 2>&1 | grep -m1 "Password:" | awk '{print $NF}' || true)
    fi

    MULTI_PROJECT_REGISTERED=false
    if [ -n "$REG_PASS" ]; then
        REG_RESULT=$(curl -sf -X POST -u "admin:${REG_PASS}" \
            -H "Content-Type: application/json" \
            -d "{\"name\": \"${PROJECT}\", \"git_repo_url\": \"${KNOWLEDGE_REPO_URL}\", \"git_branch\": \"main\", \"git_token\": \"${GH_TOKEN}\", \"git_auto_push\": true}" \
            http://localhost:8080/api/projects 2>/dev/null || true)

        if echo "$REG_RESULT" | grep -q '"status"'; then
            ok "Project '${PROJECT}' registered with running Flaiwheel (${RUNNING_FW})"
            MULTI_PROJECT_REGISTERED=true
        else
            warn "API registration returned unexpected response — project may already exist"
            MULTI_PROJECT_REGISTERED=true
        fi
    else
        warn "Could not extract credentials — project may need manual setup in Web UI"
    fi

    # On fast path, container is already healthy
    HEALTHY=true
    CONTAINER_NAME="$RUNNING_FW"
    ADMIN_PASS="$REG_PASS"

    if [ -n "$ADMIN_PASS" ]; then
        ok "Flaiwheel is ready"
        info "Indexing Flaiwheel reference docs..."
        curl -sf -X POST -u "admin:${ADMIN_PASS}" http://localhost:8080/api/index-flaiwheel-docs &>/dev/null || true
        ok "Flaiwheel docs indexed"
    fi

else
    # ── Full install / update path ──

    build_image() {
        info "Building Flaiwheel Docker image..."

        BUILD_DIR=$(mktemp -d)
        GH_TOKEN_FOR_CLONE=$(gh auth token 2>/dev/null || true)

        CLONE_URL=$(echo "$FLAIWHEEL_REPO" | sed "s|https://|https://${GH_TOKEN_FOR_CLONE}@|")
        git clone --depth 1 "$CLONE_URL" "$BUILD_DIR" 2>/dev/null || \
            fail "Could not clone Flaiwheel repo. Check your gh permissions for dl4rce/flaiwheel."

        docker build -t "$IMAGE_NAME" "$BUILD_DIR" || \
            fail "Docker build failed. Check the build output above."

        rm -rf "$BUILD_DIR"
        ok "Docker image built: ${IMAGE_NAME}"
    }

    start_container() {
        local repo_url="${1:-$KNOWLEDGE_REPO_URL}"
        local auto_push="${2:-true}"
        local webhook_secret="${3:-}"

        local extra_env=""
        if [ -n "$webhook_secret" ]; then
            extra_env="-e MCP_WEBHOOK_SECRET=${webhook_secret}"
        fi

        docker run -d \
            --name "$CONTAINER_NAME" \
            -p 8080:8080 \
            -p 8081:8081 \
            -e MCP_GIT_REPO_URL="$repo_url" \
            -e MCP_GIT_TOKEN="$GH_TOKEN" \
            -e MCP_GIT_AUTO_PUSH="$auto_push" \
            $extra_env \
            -v "${VOLUME_NAME}:/data" \
            --restart unless-stopped \
            "$IMAGE_NAME"
    }

    if [ "$UPDATE_MODE" = true ]; then
        info "Stopping container ${OLD_CONTAINER_NAME}..."
        docker stop "$OLD_CONTAINER_NAME" 2>/dev/null || true
        docker rm "$OLD_CONTAINER_NAME" 2>/dev/null || true
        ok "Old container removed (data volume ${VOLUME_NAME} preserved)"

        docker rmi "$IMAGE_NAME" 2>/dev/null || true
        build_image

        info "Recreating container as ${CONTAINER_NAME}..."
        start_container \
            "${OLD_REPO_URL:-$KNOWLEDGE_REPO_URL}" \
            "${OLD_AUTO_PUSH:-true}" \
            "${OLD_WEBHOOK_SECRET:-}"
        ok "Container recreated with latest version"

    else
        if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
            build_image
        else
            ok "Docker image ${IMAGE_NAME} already exists"
        fi

        info "Starting Flaiwheel container: ${CONTAINER_NAME}..."
        start_container
        ok "Flaiwheel container started"
    fi

    # Wait for container to be healthy and extract credentials
    info "Waiting for Flaiwheel to be ready..."
    HEALTHY=false
    for i in $(seq 1 60); do
        if curl -sf http://localhost:8080/health &>/dev/null; then
            HEALTHY=true
            break
        fi
        sleep 2
    done

    if [ "$HEALTHY" = false ]; then
        warn "Container did not become healthy within 120s."
        warn "Check logs: docker logs ${CONTAINER_NAME}"
    fi

    ADMIN_PASS=""
    for i in $(seq 1 15); do
        ADMIN_PASS=$(docker exec "$CONTAINER_NAME" cat /data/.admin_password 2>/dev/null || true)
        if [ -n "$ADMIN_PASS" ]; then break; fi
        ADMIN_PASS=$(docker logs "$CONTAINER_NAME" 2>&1 | grep -m1 "Password:" | awk '{print $NF}' || true)
        if [ -n "$ADMIN_PASS" ]; then break; fi
        sleep 1
    done

    if [ -n "$ADMIN_PASS" ]; then
        ok "Flaiwheel is ready"
        if [ "$HEALTHY" = true ]; then
            info "Indexing Flaiwheel reference docs..."
            if curl -sf -X POST -u "admin:${ADMIN_PASS}" http://localhost:8080/api/index-flaiwheel-docs &>/dev/null; then
                ok "Flaiwheel docs indexed"
            else
                warn "Index request failed (docs may still be syncing)"
            fi
        fi
    else
        warn "Could not extract credentials automatically."
    fi
fi

echo ""

# ══════════════════════════════════════════════════════
#  PHASE 6: Create Cursor MCP config
# ══════════════════════════════════════════════════════

CURSOR_DIR="${PROJECT_DIR}/.cursor"
MCP_JSON="${CURSOR_DIR}/mcp.json"

mkdir -p "$CURSOR_DIR"

if [ -f "$MCP_JSON" ]; then
    if grep -q "flaiwheel" "$MCP_JSON" 2>/dev/null; then
        ok ".cursor/mcp.json already has flaiwheel configured"
    else
        info "Adding flaiwheel to existing .cursor/mcp.json..."
        python3 -c "
import json, sys
try:
    data = json.load(open('$MCP_JSON', encoding='utf-8'))
except Exception:
    data = {}
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['flaiwheel'] = {'type': 'sse', 'url': 'http://localhost:8081/sse'}
json.dump(data, open('$MCP_JSON', 'w', encoding='utf-8'), indent=2)
"
        ok "Added flaiwheel to .cursor/mcp.json (existing config preserved)"
    fi
else
    cat > "$MCP_JSON" << 'EOF'
{
  "mcpServers": {
    "flaiwheel": {
      "type": "sse",
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

cat > "$RULE_FILE" << RULEEOF
---
description: Flaiwheel knowledge base integration
globs: *
---

# Flaiwheel – Project Knowledge Base (MCP) — YOUR FIRST STOP

This project has a **semantic knowledge base** powered by Flaiwheel (MCP endpoint: http://localhost:8081/sse).

## Knowledge Repo Location

The knowledge base lives in a **separate Git repo**: \`${KNOWLEDGE_REPO_URL}\`
It is cloned and served by Flaiwheel inside a Docker container.

**IMPORTANT — DO NOT:**
- Do NOT try to access, read, or modify files inside the Docker container
- Do NOT try to find the knowledge base on the local filesystem
- Do NOT try to \`docker exec\` into the Flaiwheel container

**INSTEAD:**
- Use the MCP tools below to **search** the knowledge base
- Use \`write_bugfix_summary()\` to **add** bugfix entries (auto-pushed to the repo)
- To add/update other docs: commit and push to the knowledge repo directly, then call \`git_pull_reindex()\`

## Session Setup — ALWAYS DO THIS FIRST

At the **start of every conversation**, call:
\`\`\`
set_project("${PROJECT}")
\`\`\`
This binds all subsequent Flaiwheel calls to **this project** so nothing goes to the wrong repo.
If the project is not registered, call \`setup_project(name="${PROJECT}", git_repo_url="${KNOWLEDGE_REPO_URL}")\` first.

## Step 1: Flaiwheel — Step 2: Native tools

**For every task, follow this order:**

1. **FIRST → Search Flaiwheel** for context: architecture decisions, past bugs, best practices, API docs, code understanding, application questions
2. **THEN → Use your native tools** (file search, code reading, grep, etc.) for source code details

Flaiwheel knows things the source code cannot tell you: the _why_ behind decisions, past mistakes to avoid, patterns to follow, and how components relate. Your native tools (Cursor, Claude Code, VS Code) are best for reading and editing actual source files. **Use both — but always start with Flaiwheel.**

## What the knowledge base contains

| Category | Search with | What you'll find |
|----------|-------------|-----------------|
| \`architecture\` | \`search_by_type("query", "architecture")\` | System design, component relationships, trade-offs, decisions |
| \`api\` | \`search_by_type("query", "api")\` | Endpoints, contracts, schemas, integration patterns |
| \`bugfix\` | \`search_bugfixes("query")\` | Root causes, solutions, lessons learned from past bugs |
| \`best-practice\` | \`search_by_type("query", "best-practice")\` | Coding standards, patterns, conventions for this project |
| \`setup\` | \`search_by_type("query", "setup")\` | Environment setup, deployment, infrastructure, CI/CD |
| \`changelog\` | \`search_by_type("query", "changelog")\` | Release notes, breaking changes, migration guides |
| \`test\` | \`search_tests("query")\` | Test cases, scenarios, regression patterns |
| _all docs_ | \`search_docs("query")\` | Semantic search across everything |

## Rules — MANDATORY

### Before writing or changing code:
1. **ALWAYS search Flaiwheel first:**
   - \`search_docs("what you're about to change")\` — architecture, patterns, constraints
   - \`search_bugfixes("the problem you're solving")\` — past issues, known pitfalls
   - \`search_by_type()\` for targeted searches — e.g. \`search_by_type("auth", "architecture")\`
2. Prefer 2-3 targeted searches over one vague query
3. THEN use your native file search/code reading for source code details

### Before writing or modifying tests:
1. **ALWAYS call \`search_tests("what you're testing")\` first** — check for existing test cases, patterns, and coverage
2. After writing/updating tests, **call \`write_test_case()\`** to document the test scenario as searchable knowledge
3. Include: title, scenario (what & why), steps, expected result, preconditions, status (pass/fail/pending), tags

### Documenting knowledge (use structured write tools):
Instead of writing raw markdown, use the built-in write tools — they enforce correct structure, place files in the right directory, index immediately, and auto-push:
- \`write_bugfix_summary()\` — after every bugfix (**mandatory**)
- \`write_architecture_doc()\` — architecture decisions, system design
- \`write_api_doc()\` — API endpoints, contracts, schemas
- \`write_best_practice()\` — coding standards, patterns
- \`write_setup_doc()\` — setup, deployment, infrastructure
- \`write_changelog_entry()\` — release notes
- \`write_test_case()\` — after writing/modifying tests, document the scenario, steps, and expected result
- \`search_tests()\` — **before** writing new tests, check what's already covered

For freeform docs: call \`validate_doc(content, category)\` before committing.

**Important:** Files with critical quality issues are skipped during indexing (not searchable). Flaiwheel NEVER deletes or modifies user files.

### After committing new/updated docs to the knowledge repo:
1. Push your changes to the knowledge repo (\`${KNOWLEDGE_REPO_URL}\`)
2. Call \`git_pull_reindex()\` so Flaiwheel pulls and indexes them immediately

### Periodically:
1. Call \`check_knowledge_quality()\` to find issues in the knowledge base
2. Fix critical issues immediately

### "This is the Way" — Knowledge Bootstrap
When the user says **"This is the Way"** or **"42"**, trigger the bootstrap:

**For NEW projects** (docs in project repo, not yet in knowledge):
1. Scan the project directory locally for doc files (.md, .txt, .pdf, .html, .rst, .docx)
2. Read the first ~2000 chars of each file
3. \`classify_documents(files=JSON)\` — send content previews, get Flaiwheel's classification
4. Present the migration plan to the user — never auto-execute
5. For each approved file: read it, restructure if needed, use the suggested \`write_*\` tool
6. \`reindex()\` — finalize

**For EXISTING knowledge repos** (files already inside, but messy):
1. \`analyze_knowledge_repo()\` — read-only scan of knowledge repo
2. Review the report with the user
3. \`execute_cleanup(actions)\` — execute approved actions only
4. \`reindex()\` — finalize
**Hard rule:** Flaiwheel never deletes files. It moves, copies, and suggests — the user decides.

## The flywheel effect

Every piece of knowledge you capture (bugfixes, decisions, patterns) gets pushed to the repo and automatically reindexed. The next search finds it. **Every task you document makes the next task faster.** You are part of this cycle — always close the loop.

## Documentation Triggers

**MANDATORY:** After fixing ANY bug → \`write_bugfix_summary()\` (no exceptions)

**RECOMMENDED:**
- Architecture decision → \`write_architecture_doc()\`
- API change → \`write_api_doc()\`
- New coding pattern → \`write_best_practice()\`
- Deployment/infra change → \`write_setup_doc()\`
- Tests written/modified → \`write_test_case()\`

**SESSION CONTINUITY:**
- At START of session → \`get_recent_sessions()\` (see what was done before)
- At END of session → \`save_session_summary()\` (preserve context for next time)

## Updating Flaiwheel

To update Flaiwheel, tell the user to run this in their project directory:
\`\`\`bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
\`\`\`
You can also call \`check_update()\` to check if a newer version is available.

## All MCP Tools

All tools accept an optional \`project\` parameter as explicit override. When omitted, the active project (set via \`set_project\`) is used.

| Tool | Purpose |
|------|---------|
| \`set_project(name)\` | **Bind session to a project** (call first!) |
| \`setup_project(name, git_repo_url, ...)\` | Register + index a new project (auto-binds) |
| \`get_active_project()\` | Show which project is currently bound |
| \`list_projects()\` | List all registered projects with stats |
| \`search_docs(query, top_k)\` | Semantic search across all documentation |
| \`search_bugfixes(query, top_k)\` | Search only bugfix summaries |
| \`search_by_type(query, doc_type, top_k)\` | Filter by type |
| \`write_bugfix_summary(...)\` | Document a bugfix (auto-pushed + reindexed) |
| \`write_architecture_doc(...)\` | Document architecture decisions |
| \`write_api_doc(...)\` | Document API endpoints |
| \`write_best_practice(...)\` | Document coding standards |
| \`write_setup_doc(...)\` | Document setup/deployment |
| \`write_changelog_entry(...)\` | Document release notes |
| \`write_test_case(...)\` | Document test cases (auto-pushed + reindexed) |
| \`search_tests(query, top_k)\` | Search test cases for coverage and patterns |
| \`validate_doc(content, category)\` | Validate markdown before committing |
| \`git_pull_reindex()\` | Pull latest from knowledge repo + re-index |
| \`get_index_stats()\` | Show index statistics |
| \`reindex()\` | Re-index all documentation |
| \`check_knowledge_quality()\` | Validate knowledge base consistency |
| \`check_update()\` | Check if a newer Flaiwheel version is available |
| \`analyze_knowledge_repo()\` | Analyse knowledge repo structure and quality |
| \`execute_cleanup(actions)\` | Execute approved cleanup actions (never deletes files) |
| \`classify_documents(files)\` | **"This is the Way"** — classify project docs for knowledge migration |
| \`save_session_summary(...)\` | Save session context for continuity (call at end of session) |
| \`get_recent_sessions(limit)\` | Retrieve recent session summaries (call at start of session) |
RULEEOF

ok "Created .cursor/rules/flaiwheel.mdc"

# ══════════════════════════════════════════════════════
#  PHASE 7b: Create AGENTS.md (for Claude Code and other agents)
# ══════════════════════════════════════════════════════

AGENTS_FILE="${PROJECT_DIR}/AGENTS.md"

FLAIWHEEL_AGENTS_BLOCK=$(cat << BLOCKEOF
## Flaiwheel — Project Knowledge Base (MCP) — YOUR FIRST STOP

This project has a **semantic knowledge base** powered by Flaiwheel.
MCP endpoint: \`http://localhost:8081/sse\`

### Knowledge Repo

The knowledge base lives in a **separate Git repo**: \`${KNOWLEDGE_REPO_URL}\`

**DO NOT** access, read, or modify files inside the Flaiwheel Docker container.
Use the MCP tools to search, and commit/push to the knowledge repo to add docs.

### Session Setup — ALWAYS DO THIS FIRST

At the **start of every conversation**, call:
\`\`\`
set_project("${PROJECT}")
\`\`\`
This binds all subsequent Flaiwheel calls to **this project**.
If the project is not registered, call \`setup_project(name="${PROJECT}", git_repo_url="${KNOWLEDGE_REPO_URL}")\` first.

### Step 1: Flaiwheel — Step 2: Native tools

For every task, follow this order:
1. **FIRST → Search Flaiwheel** for context: architecture decisions, past bugs, best practices, API docs, setup guides, application questions
2. **THEN → Use your native tools** (file search, code reading, grep, etc.) for source code details

Flaiwheel knows things the source code cannot tell you: the _why_ behind decisions, past mistakes to avoid, patterns to follow. Your native tools are best for reading and editing actual source files. **Use both — but always start with Flaiwheel.**

### Mandatory workflow

1. **FIRST: Search Flaiwheel** — \`search_docs("what you're working on")\`, \`search_bugfixes("the problem")\`, \`search_by_type("query", "architecture")\` BEFORE touching code
2. **THEN: Use native tools** to read/edit source code with the knowledge you found
3. **Document knowledge using structured write tools** (they enforce structure, auto-push, auto-index):
   - \`write_bugfix_summary()\` — after every bugfix (**mandatory**)
   - \`write_architecture_doc()\`, \`write_api_doc()\`, \`write_best_practice()\`, \`write_setup_doc()\`, \`write_changelog_entry()\`
   - For freeform docs: \`validate_doc(content, category)\` before committing
4. **Before writing/modifying tests:**
   - \`search_tests("what you're testing")\` — check existing test cases and coverage FIRST
   - After writing tests: \`write_test_case()\` — document scenario, steps, expected result, status, tags
5. **AFTER committing new/updated docs to the knowledge repo:** call \`git_pull_reindex()\`
6. **Periodically:** \`check_knowledge_quality()\` and fix issues
7. **"This is the Way"** — for messy repos, the user says this phrase (or "42"):
   - **New project:** scan local project for docs → \`classify_documents(files=JSON)\` → review plan → \`write_*\` tools → \`reindex()\`
   - **Existing knowledge repo:** \`analyze_knowledge_repo()\` → review plan → \`execute_cleanup(actions)\` → \`reindex()\`

**Important:** Files with critical quality issues are skipped during indexing. Flaiwheel NEVER deletes or modifies user files.

### Documentation Triggers

**MANDATORY:** After fixing ANY bug → \`write_bugfix_summary()\` (no exceptions)

**RECOMMENDED:**
- Architecture decision → \`write_architecture_doc()\`
- API change → \`write_api_doc()\`
- New coding pattern → \`write_best_practice()\`
- Deployment/infra change → \`write_setup_doc()\`
- Tests written/modified → \`write_test_case()\`

**SESSION CONTINUITY:**
- At START of session → \`get_recent_sessions()\` (see what was done before)
- At END of session → \`save_session_summary()\` (preserve context for next time)

### What the knowledge base contains

| Category | Search with | What you'll find |
|----------|-------------|-----------------|
| \`architecture\` | \`search_by_type("q", "architecture")\` | System design, trade-offs, decisions |
| \`api\` | \`search_by_type("q", "api")\` | Endpoints, contracts, schemas |
| \`bugfix\` | \`search_bugfixes("q")\` | Root causes, solutions, lessons learned |
| \`best-practice\` | \`search_by_type("q", "best-practice")\` | Coding standards, patterns |
| \`setup\` | \`search_by_type("q", "setup")\` | Deployment, infrastructure, CI/CD |
| \`changelog\` | \`search_by_type("q", "changelog")\` | Release notes, breaking changes |
| \`test\` | \`search_tests("q")\` | Test cases, scenarios, regression patterns |
| _everything_ | \`search_docs("q")\` | Semantic search across all docs |

### Updating Flaiwheel

To update Flaiwheel, tell the user to run this in their project directory:
\`\`\`bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
\`\`\`
You can also call \`check_update()\` to check if a newer version is available.

### All tools

All tools accept an optional \`project\` parameter as explicit override.

| Tool | Purpose |
|------|---------|
| \`set_project(name)\` | **Bind session to a project** (call first!) |
| \`setup_project(name, git_repo_url, ...)\` | Register + index a new project (auto-binds) |
| \`get_active_project()\` | Show which project is currently bound |
| \`list_projects()\` | List all registered projects with stats |
| \`search_docs(query, top_k)\` | Semantic search across all documentation |
| \`search_bugfixes(query, top_k)\` | Search bugfix summaries only |
| \`search_by_type(query, doc_type, top_k)\` | Filter by type |
| \`write_bugfix_summary(...)\` | Document a bugfix (auto-pushed + reindexed) |
| \`write_architecture_doc(...)\` | Document architecture decisions |
| \`write_api_doc(...)\` | Document API endpoints |
| \`write_best_practice(...)\` | Document coding standards |
| \`write_setup_doc(...)\` | Document setup/deployment |
| \`write_changelog_entry(...)\` | Document release notes |
| \`write_test_case(...)\` | Document test cases (auto-pushed + reindexed) |
| \`search_tests(query, top_k)\` | Search test cases for coverage and patterns |
| \`validate_doc(content, category)\` | Validate markdown before committing |
| \`git_pull_reindex()\` | Pull latest from knowledge repo + re-index |
| \`get_index_stats()\` | Index statistics |
| \`reindex()\` | Re-index all documentation |
| \`check_knowledge_quality()\` | Validate knowledge base |
| \`check_update()\` | Check for newer Flaiwheel version |
| \`analyze_knowledge_repo()\` | Analyse knowledge repo structure and quality |
| \`execute_cleanup(actions)\` | Execute approved cleanup actions (never deletes files) |
| \`classify_documents(files)\` | **"This is the Way"** — classify project docs for knowledge migration |
| \`save_session_summary(...)\` | Save session context for continuity (call at end of session) |
| \`get_recent_sessions(limit)\` | Retrieve recent session summaries (call at start of session) |
BLOCKEOF
)

if [ -f "$AGENTS_FILE" ]; then
    if grep -q "flaiwheel\|Flaiwheel" "$AGENTS_FILE" 2>/dev/null; then
        # Remove old Flaiwheel section and replace with current version
        sed '/^---$/,/^---$/{ /^## Flaiwheel/,$ { /^## [^F]/!d; }; }' "$AGENTS_FILE" > /dev/null 2>&1 || true
        # Simpler approach: remove everything from "## Flaiwheel" to next non-Flaiwheel h2 or EOF
        python3 -c "
import re, sys
content = open('$AGENTS_FILE', encoding='utf-8').read()
# Remove old Flaiwheel section (from ## Flaiwheel to next ## that isn't Flaiwheel, or EOF)
content = re.sub(
    r'(?:^---\n+)?^## Flaiwheel.*?(?=^## (?!Flaiwheel)|\Z)',
    '', content, flags=re.MULTILINE | re.DOTALL
).rstrip()
open('$AGENTS_FILE', 'w', encoding='utf-8').write(content + '\n')
"
        # Append fresh Flaiwheel section
        printf '\n---\n\n%s\n' "$FLAIWHEEL_AGENTS_BLOCK" >> "$AGENTS_FILE"
        ok "Updated Flaiwheel section in AGENTS.md"
    else
        printf '\n---\n\n%s\n' "$FLAIWHEEL_AGENTS_BLOCK" >> "$AGENTS_FILE"
        ok "Appended Flaiwheel section to existing AGENTS.md"
    fi
else
    printf '# AI Agent Instructions\n\n%s\n' "$FLAIWHEEL_AGENTS_BLOCK" > "$AGENTS_FILE"
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
   - Test cases, scenarios, regression tests → \`tests/\`
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
if [ "$FAST_PATH" = true ]; then
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║     Project Connected to Flaiwheel           ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Container:${NC}     ${GREEN}${CONTAINER_NAME}${NC} (already running)"
    echo -e "  ${BOLD}This project:${NC}  ${GREEN}${PROJECT}${NC} (registered)"
    echo -e "  ${BOLD}Knowledge:${NC}     ${GREEN}https://github.com/${OWNER}/${KNOWLEDGE_REPO}${NC}"
    echo -e "  ${BOLD}Config:${NC}        ${GREEN}.cursor/mcp.json${NC} + ${GREEN}.cursor/rules/flaiwheel.mdc${NC} + ${GREEN}AGENTS.md${NC}"
    echo ""
    echo -e "  ${BOLD}What to do next:${NC}"
    echo -e "    1. Restart Cursor to connect MCP (or toggle MCP off/on in Settings)"
    echo -e "    2. Tell your AI agent: ${GREEN}set_project(\"${PROJECT}\")${NC}"
    echo -e "    3. Say ${YELLOW}\"This is the Way\"${NC} to bootstrap a messy docs repo"
elif [ "$UPDATE_MODE" = true ]; then
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║         Update Complete                       ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}What was updated:${NC}"
    echo -e "    Container:       ${GREEN}${CONTAINER_NAME}${NC} (rebuilt with latest code)"
    echo -e "    Data volume:     ${GREEN}${VOLUME_NAME}${NC} (preserved)"
    echo -e "    Config files:    ${GREEN}refreshed${NC}"
    echo ""
    echo -e "  ${BOLD}What to do next:${NC}"
    echo -e "    1. Restart Cursor to reconnect MCP"
    echo -e "    2. Open the Web UI at ${GREEN}http://localhost:8080${NC} to verify"
else
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
    echo -e "    1. Restart Cursor"
    echo -e "    2. Go to ${BOLD}Cursor Settings → MCP${NC} and enable ${GREEN}flaiwheel${NC} if the toggle is off"
    echo -e "    3. Wait for the green ${GREEN}connected${NC} indicator"
    echo -e "    4. Open the Web UI at ${GREEN}http://localhost:8080${NC} to verify"
    echo -e "    5. See the full README: ${GREEN}https://github.com/dl4rce/flaiwheel#readme${NC}"
fi
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
if [ "$FAST_PATH" = true ]; then
    echo -e "  ${BOLD}Web UI Login:${NC} existing credentials are preserved."
    echo -e "  If you forgot them: ${YELLOW}docker logs ${CONTAINER_NAME} 2>&1 | grep 'Password:'${NC}"
elif [ "$UPDATE_MODE" = true ]; then
    echo -e "  ${BOLD}Web UI Login:${NC} your existing credentials are preserved."
    echo -e "  If you forgot them: ${YELLOW}docker logs ${CONTAINER_NAME} 2>&1 | grep 'Password:'${NC}"
elif [ -n "${ADMIN_PASS:-}" ]; then
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
