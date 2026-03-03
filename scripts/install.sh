#!/bin/bash
# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# BSL 1.1. See LICENSE.md. Commercial licensing: info@4rce.com
#
# One-command installer: sets up Flaiwheel for any project.
# Usage: bash <(curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh)
set -euo pipefail

# ── Version (keep in sync with src/flaiwheel/__init__.py) ───────────────────
_FW_VERSION="3.7.8"

# ── Detect curl | bash (stdin is a pipe, not a terminal) ────────────────────
# curl | bash connects stdin to the pipe — interactive read prompts break.
# Re-exec from a temp file so stdin is the terminal again.
# IMPORTANT: re-exec from THIS script's own path (already on disk or $0),
# never re-download — that would fetch a potentially stale CDN-cached version.
if [ ! -t 0 ]; then
    _TMP_SCRIPT=$(mktemp /tmp/flaiwheel-install-XXXXXX.sh)
    # If we were piped in, $0 is "bash" — read ourselves from stdin via /proc or re-download pinned tag
    if [ -f "$0" ] && [ "$0" != "bash" ] && [ "$0" != "/bin/bash" ]; then
        # Running as a file (e.g. bash /tmp/fw-install.sh) — just re-exec with stdin from /dev/tty
        exec bash "$0" "$@" </dev/tty
    else
        # Truly piped via curl | bash — download pinned to current version tag
        _PINNED_URL="https://raw.githubusercontent.com/dl4rce/flaiwheel/v${_FW_VERSION}/scripts/install.sh"
        if curl -sSL "$_PINNED_URL" -o "$_TMP_SCRIPT" 2>/dev/null && [ -s "$_TMP_SCRIPT" ]; then
            chmod +x "$_TMP_SCRIPT"
            exec bash "$_TMP_SCRIPT" "$@" </dev/tty
        else
            echo "Error: could not download installer. Try: bash <(curl -sSL ${_PINNED_URL})" >&2
            exit 1
        fi
    fi
fi

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

# ── Parallel job helpers ─────────────────────────────
# Usage:
#   run_parallel job_name "commands..." &
#   _PIDS+=($!)  _PJOBS+=("job_name")
#   wait_all
_PIDS=()
_PJOBS=()

# Run a named block in a subshell; on failure print its log and exit 1
run_parallel() {
    local _name="$1"; shift
    local _log; _log=$(mktemp /tmp/fw-job-XXXXXX.log)
    (
        # Subshell inherits all exported vars; capture stdout+stderr to log
        exec > "$_log" 2>&1
        "$@"
    )
    local _rc=$?
    cat "$_log"          # merge output into main stream (already serialised per-job)
    rm -f "$_log"
    if [ $_rc -ne 0 ]; then
        echo -e "${RED}[✗]${NC} Parallel job '${_name}' failed (exit ${_rc})" >&2
        exit $_rc
    fi
}

wait_all() {
    local _failed=0
    for i in "${!_PIDS[@]}"; do
        if ! wait "${_PIDS[$i]}"; then
            echo -e "${RED}[✗]${NC} Job '${_PJOBS[$i]}' failed" >&2
            _failed=1
        fi
    done
    _PIDS=(); _PJOBS=()
    [ $_failed -eq 0 ] || exit 1
}

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

# 1. gh CLI installed — auto-install if missing
if ! command -v gh &>/dev/null; then
    warn "GitHub CLI (gh) not found. Attempting auto-install..."

    _OS="$(uname -s)"
    _ARCH="$(uname -m)"
    _GH_INSTALLED=false

    if [ "$_OS" = "Darwin" ]; then
        # macOS — use Homebrew if available, otherwise install Homebrew first
        if command -v brew &>/dev/null; then
            info "Installing gh via Homebrew..."
            brew install gh && _GH_INSTALLED=true
        else
            info "Homebrew not found. Installing Homebrew first..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" && \
                eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)" && \
                brew install gh && _GH_INSTALLED=true
        fi

    elif [ "$_OS" = "Linux" ]; then
        if command -v apt-get &>/dev/null; then
            # Debian / Ubuntu
            info "Installing gh via apt (Debian/Ubuntu)..."
            (type -p wget >/dev/null || (apt-get update && apt-get install -y wget)) &&
                mkdir -p -m 755 /etc/apt/keyrings &&
                wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                    | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null &&
                chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg &&
                echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                    | tee /etc/apt/sources.list.d/github-cli.list >/dev/null &&
                apt-get update &&
                apt-get install -y gh && _GH_INSTALLED=true

        elif command -v dnf &>/dev/null; then
            # Fedora / RHEL 8+
            info "Installing gh via dnf (Fedora/RHEL)..."
            dnf install -y 'dnf-command(config-manager)' &&
                dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo &&
                dnf install -y gh && _GH_INSTALLED=true

        elif command -v yum &>/dev/null; then
            # CentOS / RHEL 7
            info "Installing gh via yum (CentOS/RHEL)..."
            yum install -y yum-utils &&
                yum-config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo &&
                yum install -y gh && _GH_INSTALLED=true

        elif command -v zypper &>/dev/null; then
            # openSUSE
            info "Installing gh via zypper (openSUSE)..."
            zypper addrepo https://cli.github.com/packages/rpm/gh-cli.repo &&
                zypper ref &&
                zypper install -y gh && _GH_INSTALLED=true

        elif command -v pacman &>/dev/null; then
            # Arch Linux
            info "Installing gh via pacman (Arch)..."
            pacman -Sy --noconfirm github-cli && _GH_INSTALLED=true

        else
            # Generic Linux fallback: download binary directly
            info "Trying generic binary install for Linux (${_ARCH})..."
            _GH_VERSION=$(curl -sf https://api.github.com/repos/cli/cli/releases/latest \
                | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))" 2>/dev/null || echo "")
            if [ -n "$_GH_VERSION" ]; then
                case "$_ARCH" in
                    x86_64)  _GH_ARCH="amd64" ;;
                    aarch64) _GH_ARCH="arm64" ;;
                    armv6*)  _GH_ARCH="armv6" ;;
                    *)       _GH_ARCH="amd64" ;;
                esac
                _GH_URL="https://github.com/cli/cli/releases/download/v${_GH_VERSION}/gh_${_GH_VERSION}_linux_${_GH_ARCH}.tar.gz"
                _GH_TMP=$(mktemp -d)
                curl -sSL "$_GH_URL" | tar -xz -C "$_GH_TMP" &&
                    install -m 755 "$_GH_TMP/gh_${_GH_VERSION}_linux_${_GH_ARCH}/bin/gh" /usr/local/bin/gh &&
                    rm -rf "$_GH_TMP" && _GH_INSTALLED=true
            fi
        fi
    fi

    if [ "$_GH_INSTALLED" = true ] && command -v gh &>/dev/null; then
        ok "GitHub CLI installed: $(gh --version | head -1)"
    else
        echo ""
        echo -e "  ${RED}${BOLD}Auto-install failed or unsupported on this platform.${NC}"
        echo -e "  Install GitHub CLI manually, then re-run this script:"
        echo ""
        echo -e "  ${BOLD}macOS:${NC}   brew install gh"
        echo -e "  ${BOLD}Ubuntu:${NC}  ${GREEN}https://github.com/cli/cli/blob/trunk/docs/install_linux.md${NC}"
        echo -e "  ${BOLD}Other:${NC}   ${GREEN}https://cli.github.com${NC}"
        echo ""
        exit 1
    fi
fi

# 2. gh authenticated
if ! gh auth status &>/dev/null; then
    fail "GitHub CLI not authenticated. Run: gh auth login"
fi

# 3. Inside a git repo — if not, offer to clone or cd into one
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo ""
    echo -e "  ${YELLOW}${BOLD}Not inside a git repository.${NC}"
    echo -e "  Flaiwheel needs to be run from your project root."
    echo ""
    echo -e "  Options:"
    echo -e "    ${BOLD}1)${NC} Enter the path to an existing local project"
    echo -e "    ${BOLD}2)${NC} Clone a GitHub repo now"
    echo ""
    # Read from /dev/tty so interactive prompts work even when piped through curl | bash
    read -p "  Choose [1/2]: " -n 1 -r _REPO_CHOICE </dev/tty
    echo ""

    if [[ "$_REPO_CHOICE" == "2" ]]; then
        read -p "  GitHub repo (owner/repo or full URL): " _CLONE_URL </dev/tty
        # Normalise: accept "owner/repo", "github.com/owner/repo", or full https/ssh URL
        if [[ "$_CLONE_URL" =~ ^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$ ]]; then
            _CLONE_URL="https://github.com/${_CLONE_URL}.git"
        elif [[ "$_CLONE_URL" =~ ^github\.com/ ]]; then
            _CLONE_URL="https://${_CLONE_URL}"
        fi
        # Strip trailing .git for display, ensure it ends with .git for clone
        _CLONE_URL="${_CLONE_URL%.git}.git"
        _CLONE_DIR=$(basename "${_CLONE_URL%.git}")
        # Inject gh token into https URL so clone doesn't prompt for credentials
        _GH_TOKEN_FOR_CLONE=$(gh auth token 2>/dev/null || true)
        if [ -n "$_GH_TOKEN_FOR_CLONE" ] && [[ "$_CLONE_URL" == https://github.com/* ]]; then
            _AUTHED_URL="${_CLONE_URL/https:\/\//https:\/\/${_GH_TOKEN_FOR_CLONE}@}"
        else
            _AUTHED_URL="$_CLONE_URL"
        fi
        info "Cloning ${_CLONE_URL}..."
        if [ -d "$_CLONE_DIR" ]; then
            warn "Directory '${_CLONE_DIR}' already exists."
            echo ""
            echo -e "  ${BOLD}1)${NC} Use existing directory (skip clone)"
            echo -e "  ${BOLD}2)${NC} Delete and re-clone"
            echo ""
            read -p "  Choose [1/2]: " -n 1 -r _CLONE_CHOICE </dev/tty
            echo ""
            if [[ "$_CLONE_CHOICE" == "2" ]]; then
                rm -rf "$_CLONE_DIR"
                git clone "$_AUTHED_URL" "$_CLONE_DIR" 2>&1 | grep -v 'token\|password\|credential' \
                    || fail "Clone failed. Check the repo name and your GitHub access."
                ok "Re-cloned: ${_CLONE_DIR}"
            else
                ok "Using existing directory: ${_CLONE_DIR}"
            fi
        else
            git clone "$_AUTHED_URL" "$_CLONE_DIR" 2>&1 | grep -v 'token\|password\|credential' \
                || fail "Clone failed. Check the repo name and your GitHub access."
        fi
        cd "$_CLONE_DIR" || fail "Could not enter cloned directory."
        ok "Cloned and entered: $(pwd)"
    else
        read -p "  Path to your project directory: " _PROJECT_PATH </dev/tty
        _PROJECT_PATH="${_PROJECT_PATH/#\~/$HOME}"
        if [ ! -d "$_PROJECT_PATH" ]; then
            fail "Directory not found: ${_PROJECT_PATH}"
        fi
        cd "$_PROJECT_PATH" || fail "Could not cd into ${_PROJECT_PATH}"
        if ! git rev-parse --is-inside-work-tree &>/dev/null; then
            fail "Still not inside a git repo at: $(pwd)\nRun: git init && git remote add origin <your-github-url>"
        fi
        ok "Using project at: $(pwd)"
    fi
fi

# 4. Has a remote
REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$REMOTE_URL" ]; then
    fail "No git remote 'origin' found. Push your project to GitHub first.\n  Run: git remote add origin https://github.com/YOUR_ORG/YOUR_REPO.git"
fi

# 5. Docker installed and running — auto-install if missing
if ! command -v docker &>/dev/null; then
    warn "Docker not found. Attempting auto-install..."
    _OS="$(uname -s)"
    _DOCKER_INSTALLED=false

    if [ "$_OS" = "Darwin" ]; then
        # macOS — Docker Desktop via Homebrew Cask
        if command -v brew &>/dev/null; then
            info "Installing Docker Desktop via Homebrew..."
            brew install --cask docker && _DOCKER_INSTALLED=true
        else
            echo ""
            echo -e "  ${RED}${BOLD}Docker Desktop cannot be auto-installed on macOS without Homebrew.${NC}"
            echo -e "  Download it from: ${GREEN}https://docs.docker.com/desktop/mac/install/${NC}"
            echo ""
            exit 1
        fi

    elif [ "$_OS" = "Linux" ]; then
        # Linux — use Docker's official convenience script (works on all major distros)
        info "Installing Docker via official install script..."
        curl -fsSL https://get.docker.com | sh && _DOCKER_INSTALLED=true

        if [ "$_DOCKER_INSTALLED" = true ]; then
            # Start and enable Docker daemon
            systemctl enable docker 2>/dev/null || true
            systemctl start  docker 2>/dev/null || true
        fi
    fi

    if [ "$_DOCKER_INSTALLED" = true ] && command -v docker &>/dev/null; then
        ok "Docker installed: $(docker --version)"
    else
        echo ""
        echo -e "  ${RED}${BOLD}Docker auto-install failed.${NC}"
        echo -e "  Install it manually: ${GREEN}https://docs.docker.com/get-docker/${NC}"
        echo ""
        exit 1
    fi
fi

if ! docker info &>/dev/null 2>&1; then
    _OS="$(uname -s)"
    if [ "$_OS" = "Linux" ]; then
        info "Docker daemon not running — attempting to start..."
        systemctl start docker 2>/dev/null || service docker start 2>/dev/null || true
        sleep 3
    fi
    if ! docker info &>/dev/null 2>&1; then
        fail "Docker is not running. Start it with: systemctl start docker"
    fi
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
#  Only if running version matches latest version.
#  If version mismatch → fall through to update mode.
# ══════════════════════════════════════════════════════

FAST_PATH=false
RUNNING_FW=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^flaiwheel-' | head -1 || true)

if [ -n "$RUNNING_FW" ] && curl -sf http://localhost:8080/health &>/dev/null; then
    RUNNING_VERSION=$(curl -sf http://localhost:8080/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','0.0.0'))" 2>/dev/null || echo "0.0.0")
    LATEST_VERSION=$(curl -sf "https://raw.githubusercontent.com/dl4rce/flaiwheel/v${_FW_VERSION}/src/flaiwheel/__init__.py" | grep '__version__' | cut -d'"' -f2 2>/dev/null || echo "0.0.0")

    if [ "$RUNNING_VERSION" = "$LATEST_VERSION" ]; then
        FAST_PATH=true
        echo -e "${GREEN}${BOLD}[✓] Flaiwheel v${RUNNING_VERSION} already running (${RUNNING_FW}). Fast-connecting this project...${NC}"
        echo ""
    else
        echo -e "${YELLOW}${BOLD}[↑] Flaiwheel update available: v${RUNNING_VERSION} → v${LATEST_VERSION}${NC}"
        EXISTING_CONTAINER="$RUNNING_FW"
    fi
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

        read -p "  Update to latest version? [Y/n] " -n 1 -r REPLY </dev/tty
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
        git add FLAIWHEEL_TOOLS.md architecture/ api/ bugfix-log/ best-practices/ setup/ changelog/ tests/
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

    git add README.md FLAIWHEEL_TOOLS.md architecture/ api/ bugfix-log/ best-practices/ setup/ changelog/ tests/
    git commit -m "init: knowledge base structure (created by Flaiwheel installer)"
    git push origin main 2>/dev/null || git push origin master 2>/dev/null

    popd > /dev/null
    rm -rf "$TMPDIR"

    KNOWLEDGE_REPO_URL="https://github.com/${OWNER}/${KNOWLEDGE_REPO}.git"
    ok "Knowledge repo created and initialized"
fi

echo ""

# ══════════════════════════════════════════════════════
#  PHASE 4: Get GitHub token (runs in parallel with Phase 3 above)
# ══════════════════════════════════════════════════════

# Phase 3 already ran synchronously (needs KNOWLEDGE_REPO_URL output).
# Token fetch is instant but kept here for clarity.
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

        # Pre-build cleanup: stale containerd ingest data accumulates from
        # interrupted builds and is NOT cleared by 'docker builder prune'.
        # Wipe it before every build so we never hit "no space left on device"
        # during layer export on small disks.
        _INGEST_DIR="/var/lib/containerd/io.containerd.content.v1.content/ingest"
        if [ -d "$_INGEST_DIR" ] && [ "$(ls -A "$_INGEST_DIR" 2>/dev/null | wc -l)" -gt 0 ]; then
            info "Clearing stale containerd ingest cache before build..."
            systemctl stop docker 2>/dev/null || true
            rm -rf "${_INGEST_DIR:?}"/*
            systemctl start docker
            sleep 2
        fi
        # Also clear dangling build cache layers
        docker builder prune -f --filter "until=24h" >/dev/null 2>&1 || true

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

    # ── Embedding model selection ──────────────────────────────────────────
    # Detect currently configured model from a running container (update mode)
    # or from an existing container's env vars (any mode).
    _CURRENT_MODEL=""
    _DETECTED_FROM=""
    if [ -n "${EXISTING_CONTAINER:-}" ]; then
        _CURRENT_MODEL=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
            "$EXISTING_CONTAINER" 2>/dev/null \
            | grep "^MCP_EMBEDDING_MODEL=" | cut -d= -f2- || true)
        [ -n "$_CURRENT_MODEL" ] && _DETECTED_FROM="existing container"
    fi
    # Also check any running flaiwheel container on this host
    if [ -z "$_CURRENT_MODEL" ] && [ -n "${RUNNING_FW:-}" ]; then
        _CURRENT_MODEL=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
            "$RUNNING_FW" 2>/dev/null \
            | grep "^MCP_EMBEDDING_MODEL=" | cut -d= -f2- || true)
        [ -n "$_CURRENT_MODEL" ] && _DETECTED_FROM="running container"
    fi
    # Default if nothing detected
    _DEFAULT_MODEL="${_CURRENT_MODEL:-all-MiniLM-L12-v2}"

    echo ""
    echo -e "  ${BOLD}Embedding model${NC} (cached on /data volume after first download):"
    if [ -n "$_CURRENT_MODEL" ]; then
        echo -e "  ${GREEN}Currently using:${NC} ${BOLD}${_CURRENT_MODEL}${NC} (from ${_DETECTED_FROM})"
        echo -e "  Press ${BOLD}Enter${NC} to keep it, or pick a different one:"
    else
        echo -e "  Press ${BOLD}Enter${NC} for default, or pick a model:"
    fi
    echo ""
    echo -e "    ${BOLD}1)${NC} all-MiniLM-L12-v2         — fast, good quality (~130MB)"
    echo -e "    ${BOLD}2)${NC} all-MiniLM-L6-v2          — fastest, smallest (~80MB)"
    echo -e "    ${BOLD}3)${NC} all-mpnet-base-v2          — good quality (~420MB)"
    echo -e "    ${BOLD}4)${NC} BAAI/bge-base-en-v1.5      — best value English (~420MB)"
    echo -e "    ${BOLD}5)${NC} nomic-ai/nomic-embed-text-v1.5 — best English quality (~520MB)"
    echo -e "    ${BOLD}6)${NC} intfloat/multilingual-e5-base  — DE/EN/Multi (~1.1GB)"
    echo -e "    ${BOLD}7)${NC} BAAI/bge-m3                — best multilingual (~2.2GB)"
    echo -e "    ${BOLD}c)${NC} Enter custom model name"
    echo ""
    if [ -n "$_CURRENT_MODEL" ]; then
        read -p "  Choose [1-7/c, Enter=keep current]: " -n 1 -r _MODEL_CHOICE </dev/tty
    else
        read -p "  Choose [1-7/c, Enter=default (all-MiniLM-L12-v2)]: " -n 1 -r _MODEL_CHOICE </dev/tty
    fi
    echo ""
    case "$_MODEL_CHOICE" in
        1) EMBEDDING_MODEL="all-MiniLM-L12-v2" ;;
        2) EMBEDDING_MODEL="all-MiniLM-L6-v2" ;;
        3) EMBEDDING_MODEL="all-mpnet-base-v2" ;;
        4) EMBEDDING_MODEL="BAAI/bge-base-en-v1.5" ;;
        5) EMBEDDING_MODEL="nomic-ai/nomic-embed-text-v1.5" ;;
        6) EMBEDDING_MODEL="intfloat/multilingual-e5-base" ;;
        7) EMBEDDING_MODEL="BAAI/bge-m3" ;;
        c|C)
            read -p "  Custom model (HuggingFace ID): " EMBEDDING_MODEL </dev/tty
            ;;
        *) EMBEDDING_MODEL="$_DEFAULT_MODEL" ;;
    esac
    ok "Embedding model: ${EMBEDDING_MODEL}"
    echo ""

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
            -e MCP_EMBEDDING_MODEL="${EMBEDDING_MODEL:-all-MiniLM-L12-v2}" \
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
        # Only rebuild if the image was actually removed (i.e. not reused)
        if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
            build_image
        else
            ok "Docker image ${IMAGE_NAME} already up to date — skipping rebuild"
        fi

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

    # Wait for container to be healthy and extract credentials.
    # On first install the embedding model is downloaded at startup (~60-120s).
    # We poll for up to 5 minutes so fresh installs don't time out.
    info "Waiting for Flaiwheel to be ready (first start downloads the embedding model)..."
    HEALTHY=false
    for i in $(seq 1 150); do   # 150 × 2s = 300s = 5 min
        if curl -sf http://localhost:8080/health &>/dev/null; then
            HEALTHY=true
            break
        fi
        # Print a dot every 10s so the user knows it's alive
        [ $((i % 5)) -eq 0 ] && printf "."
        sleep 2
    done
    [ "$HEALTHY" = true ] && echo "" || echo ""

    if [ "$HEALTHY" = false ]; then
        warn "Container not healthy yet after 5 min — still starting (model download may be slow)."
        warn "Check logs: docker logs ${CONTAINER_NAME}"
        warn "Re-run the installer once it's up to finish registration."
    fi

    # Extract credentials — password is written to /data/.admin_password early in startup,
    # before the model download, so this usually succeeds even if health check timed out.
    ADMIN_PASS=""
    for i in $(seq 1 30); do
        ADMIN_PASS=$(docker exec "$CONTAINER_NAME" cat /data/.admin_password 2>/dev/null || true)
        if [ -n "$ADMIN_PASS" ]; then break; fi
        ADMIN_PASS=$(docker logs "$CONTAINER_NAME" 2>&1 | grep -m1 "Password:" | awk '{print $NF}' || true)
        if [ -n "$ADMIN_PASS" ]; then break; fi
        sleep 2
    done

    if [ -n "$ADMIN_PASS" ]; then
        ok "Credentials extracted"
        if [ "$HEALTHY" = true ]; then
            info "Indexing Flaiwheel reference docs..."
            if curl -sf -X POST -u "admin:${ADMIN_PASS}" http://localhost:8080/api/index-flaiwheel-docs &>/dev/null; then
                ok "Flaiwheel docs indexed"
            else
                warn "Index request failed (docs may still be syncing)"
            fi
        fi
    else
        warn "Could not extract credentials yet — container may still be starting."
        warn "Retrieve them later with: docker logs ${CONTAINER_NAME} 2>&1 | grep 'Password:'"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════
#  PHASES 6-10: Write config files in parallel
#  All phases write to different paths — no conflicts.
# ══════════════════════════════════════════════════════

info "Writing config files (parallel)..."

# Initialise summary flags — set here so the Done section never hits unbound variable.
# Parallel subshells cannot write back to the parent; these are best-effort defaults.
CLAUDE_DESKTOP_REGISTERED=false
CLAUDE_MCP_REGISTERED=false
VSCODE_REGISTERED=false

# ── Helper: atomic log line (prevents interleaved output) ──────────────────
_LOG_LOCK=$(mktemp /tmp/fw-lock-XXXXXX)
plog() { flock "$_LOG_LOCK" echo -e "$1"; }
pok()  { plog "${GREEN}[✓]${NC} $1"; }
pwarn(){ plog "${YELLOW}[!]${NC} $1"; }
pinfo(){ plog "${BLUE}[flaiwheel]${NC} $1"; }

# Export all variables needed by the parallel subshells
export PROJECT_DIR OWNER PROJECT KNOWLEDGE_REPO KNOWLEDGE_REPO_URL
export CURSOR_DIR="${PROJECT_DIR}/.cursor"
export RULES_DIR="${PROJECT_DIR}/.cursor/rules"
export GITIGNORE="${PROJECT_DIR}/.gitignore"
mkdir -p "$CURSOR_DIR" "$RULES_DIR" "${PROJECT_DIR}/.github" "${PROJECT_DIR}/.vscode" "${PROJECT_DIR}/.git/hooks"

# ══════════════════════════════════════════════════════
#  PHASE 6: Create Cursor MCP config
# ══════════════════════════════════════════════════════

_phase6_cursor_mcp() {
MCP_JSON="${CURSOR_DIR}/mcp.json"

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
} # end _phase6_cursor_mcp

# ══════════════════════════════════════════════════════
#  PHASE 7: Create Cursor rule for AI agents
# ══════════════════════════════════════════════════════

_phase7_cursor_rule() {
RULE_FILE="${RULES_DIR}/flaiwheel.mdc"

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
} # end _phase7_cursor_rule

# ══════════════════════════════════════════════════════
#  PHASE 7b: Create AGENTS.md (for Claude Code and other agents)
# ══════════════════════════════════════════════════════

_phase7b_agents_md() {
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
} # end _phase7b_agents_md

# ══════════════════════════════════════════════════════
#  PHASE 7c: Create .mcp.json + CLAUDE.md (for Claude Code)
# ══════════════════════════════════════════════════════

_phase7c_claude() {
MCP_JSON_ROOT="${PROJECT_DIR}/.mcp.json"

if [ -f "$MCP_JSON_ROOT" ]; then
    if grep -q "flaiwheel" "$MCP_JSON_ROOT" 2>/dev/null; then
        ok ".mcp.json already has flaiwheel configured"
    else
        info "Adding flaiwheel to existing .mcp.json..."
        python3 -c "
import json, sys
with open('$MCP_JSON_ROOT', encoding='utf-8') as f:
    cfg = json.load(f)
cfg.setdefault('mcpServers', {})['flaiwheel'] = {'type': 'sse', 'url': 'http://localhost:8081/sse'}
with open('$MCP_JSON_ROOT', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
    f.write('\n')
"
        ok "Added flaiwheel to .mcp.json (existing config preserved)"
    fi
else
    cat > "$MCP_JSON_ROOT" << MCPEOF
{
  "mcpServers": {
    "flaiwheel": {
      "type": "sse",
      "url": "http://localhost:8081/sse"
    }
  }
}
MCPEOF
    ok "Created .mcp.json (Claude Code MCP config)"
fi

CLAUDE_FILE="${PROJECT_DIR}/CLAUDE.md"
FLAIWHEEL_CLAUDE_BLOCK=$(cat << CLAUDEEOF
## Flaiwheel — Project Knowledge Base (MCP) — YOUR FIRST STOP

> Full AI agent instructions (including Flaiwheel workflow) are in **AGENTS.md** — read it fully before doing anything else.

### ⚠️ First-time setup — check MCP connection before anything else

1. Type \`/mcp\` to see connected servers
2. If \`flaiwheel\` is **not listed**, tell the user:

   > "Flaiwheel MCP is not connected. Please run this command in your terminal, then restart Claude Code:
   >
   > \`claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse\`"

3. Do **not** proceed until Flaiwheel is connected — it is the primary knowledge source for this project.

### Session Start — ALWAYS DO THIS FIRST

1. Check MCP connection (see above)
2. Read \`AGENTS.md\` in this project root
3. Call \`set_project("${PROJECT}")\` via the Flaiwheel MCP tool
4. Call \`get_recent_sessions()\` to restore context from the last session

### Flaiwheel MCP

- **Endpoint:** \`http://localhost:8081/sse\` (configured in \`.mcp.json\`)
- **Register once:** \`claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse\`
- **Verify:** type \`/mcp\` — \`flaiwheel\` should appear with 27 tools
- **Rule:** Search Flaiwheel BEFORE reading source code. Always.
- **Rule:** After every bugfix, call \`write_bugfix_summary()\`. No exceptions.
- **Rule:** End every session with \`save_session_summary()\`.
CLAUDEEOF
)

if [ -f "$CLAUDE_FILE" ]; then
    if grep -q "flaiwheel\|Flaiwheel" "$CLAUDE_FILE" 2>/dev/null; then
        python3 -c "
import re
content = open('$CLAUDE_FILE', encoding='utf-8').read()
content = re.sub(
    r'(?:^---\n+)?^## Flaiwheel.*?(?=^## (?!Flaiwheel)|\Z)',
    '', content, flags=re.MULTILINE | re.DOTALL
).rstrip()
open('$CLAUDE_FILE', 'w', encoding='utf-8').write(content + '\n')
"
        printf '\n---\n\n%s\n' "$FLAIWHEEL_CLAUDE_BLOCK" >> "$CLAUDE_FILE"
        ok "Updated Flaiwheel section in CLAUDE.md"
    else
        printf '\n---\n\n%s\n' "$FLAIWHEEL_CLAUDE_BLOCK" >> "$CLAUDE_FILE"
        ok "Appended Flaiwheel section to existing CLAUDE.md"
    fi
else
    printf '# Claude Code — Project Instructions\n\n%s\n' "$FLAIWHEEL_CLAUDE_BLOCK" > "$CLAUDE_FILE"
    ok "Created CLAUDE.md (Claude Code instructions)"
fi

# Auto-configure Claude Desktop (macOS) if installed
CLAUDE_DESKTOP_REGISTERED=false
CLAUDE_DESKTOP_CONFIG="${HOME}/Library/Application Support/Claude/claude_desktop_config.json"
if [ -f "$CLAUDE_DESKTOP_CONFIG" ]; then
    info "Claude Desktop detected — adding Flaiwheel to claude_desktop_config.json..."
    # Claude Desktop only supports stdio servers — use mcp-proxy as a stdio→SSE bridge.
    # Requires npx (Node.js). If npx is not available, skip and print instructions.
    if command -v npx >/dev/null 2>&1; then
        RESULT=$(python3 -c "
import json
path = '$CLAUDE_DESKTOP_CONFIG'
try:
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
except Exception:
    cfg = {}
servers = cfg.setdefault('mcpServers', {})
if 'flaiwheel' in servers:
    print('already_configured')
else:
    servers['flaiwheel'] = {
        'command': 'npx',
        'args': ['-y', 'mcp-remote', 'http://localhost:8081/sse']
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
        f.write('\n')
    print('configured')
" 2>/dev/null)
        if [ "$RESULT" = "already_configured" ]; then
            ok "Claude Desktop: flaiwheel MCP already configured"
        else
            ok "Claude Desktop: flaiwheel added — restart Claude for Mac to connect"
        fi
        CLAUDE_DESKTOP_REGISTERED=true
    else
        warn "Claude Desktop found but npx is not installed — cannot configure mcp-proxy"
        warn "  Install Node.js, then add to claude_desktop_config.json manually:"
        warn '  "flaiwheel": {"command":"npx","args":["-y","mcp-remote","http://localhost:8081/sse"]}'
    fi
fi

# Auto-register with Claude Code CLI if available
CLAUDE_MCP_REGISTERED=false
CLAUDE_CLI_MISSING=false
if command -v claude >/dev/null 2>&1; then
    info "Claude Code CLI detected — registering Flaiwheel MCP automatically..."
    CLAUDE_REGISTER_OUT=$(claude mcp add --transport sse --scope project flaiwheel "http://localhost:8081/sse" 2>&1)
    CLAUDE_REGISTER_RC=$?
    if [ $CLAUDE_REGISTER_RC -eq 0 ]; then
        ok "Claude Code: flaiwheel MCP registered (project scope)"
        CLAUDE_MCP_REGISTERED=true
    elif echo "$CLAUDE_REGISTER_OUT" | grep -qi "already exists\|already configured\|already added"; then
        ok "Claude Code: flaiwheel MCP already registered"
        CLAUDE_MCP_REGISTERED=true
    else
        warn "Claude Code CLI found but registration failed:"
        warn "  ${CLAUDE_REGISTER_OUT}"
        CLAUDE_CLI_MISSING=true
    fi
else
    CLAUDE_CLI_MISSING=true
fi

if [ "$CLAUDE_CLI_MISSING" = true ]; then
    echo ""
    echo -e "  ${YELLOW}${BOLD}┌─────────────────────────────────────────────────────┐${NC}"
    echo -e "  ${YELLOW}${BOLD}│  ACTION REQUIRED — Claude Code MCP registration     │${NC}"
    echo -e "  ${YELLOW}${BOLD}└─────────────────────────────────────────────────────┘${NC}"
    echo -e "  Run this command ${BOLD}once${NC} in your terminal to connect Claude Code:"
    echo ""
    echo -e "  ${GREEN}claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse${NC}"
    echo ""
    echo -e "  Then type ${BOLD}/mcp${NC} inside Claude Code to verify the connection."
    echo -e "  ${BOLD}Cursor${NC} users: no action needed — .cursor/mcp.json handles it."
    echo ""
fi
} # end _phase7c_claude

# ══════════════════════════════════════════════════════
#  PHASE 7d: Create .vscode/mcp.json + .github/copilot-instructions.md (VS Code / GitHub Copilot)
# ══════════════════════════════════════════════════════

_phase7d_vscode() {
VSCODE_DIR="${PROJECT_DIR}/.vscode"
VSCODE_MCP="${VSCODE_DIR}/mcp.json"
VSCODE_REGISTERED=false

if [ -f "$VSCODE_MCP" ]; then
    if grep -q "flaiwheel" "$VSCODE_MCP" 2>/dev/null; then
        ok ".vscode/mcp.json already has flaiwheel configured"
        VSCODE_REGISTERED=true
    else
        info "Adding flaiwheel to existing .vscode/mcp.json..."
        python3 -c "
import json
with open('$VSCODE_MCP', encoding='utf-8') as f:
    cfg = json.load(f)
cfg.setdefault('servers', {})['flaiwheel'] = {'type': 'sse', 'url': 'http://localhost:8081/sse'}
with open('$VSCODE_MCP', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
    f.write('\n')
"
        ok "Added flaiwheel to .vscode/mcp.json (existing config preserved)"
        VSCODE_REGISTERED=true
    fi
else
    cat > "$VSCODE_MCP" << VSCODEEOF
{
  "servers": {
    "flaiwheel": {
      "type": "sse",
      "url": "http://localhost:8081/sse"
    }
  }
}
VSCODEEOF
    ok "Created .vscode/mcp.json (VS Code / GitHub Copilot MCP config)"
    VSCODE_REGISTERED=true
fi

# .github/copilot-instructions.md — VS Code Copilot's equivalent of AGENTS.md
GITHUB_DIR="${PROJECT_DIR}/.github"
COPILOT_FILE="${GITHUB_DIR}/copilot-instructions.md"
FLAIWHEEL_COPILOT_BLOCK=$(cat << COPILOTEOF
## Flaiwheel — Project Knowledge Base (MCP)

> Full AI agent instructions are in **AGENTS.md** in the project root — read it at session start.

### MCP Connection

Flaiwheel is configured in \`.vscode/mcp.json\`. Verify the connection:
- Open the Command Palette (\`Ctrl+Shift+P\` / \`Cmd+Shift+P\`)
- Run **MCP: List Servers** — \`flaiwheel\` should appear as running

If it is not running:
1. Open \`.vscode/mcp.json\` and confirm the server entry is present
2. Run **MCP: List Servers** → select \`flaiwheel\` → click **Start**
3. Requires VS Code 1.99+ with GitHub Copilot

### Session Start — ALWAYS DO THIS FIRST

1. Verify MCP connection (see above)
2. Read \`AGENTS.md\` in this project root
3. Call \`set_project("${PROJECT}")\` via Flaiwheel MCP
4. Call \`get_recent_sessions()\` to restore context from the last session

### Rules

- Search Flaiwheel BEFORE reading source code. Always.
- After every bugfix: \`write_bugfix_summary()\`. No exceptions.
- End every session with \`save_session_summary()\`.
COPILOTEOF
)

mkdir -p "$GITHUB_DIR"
if [ -f "$COPILOT_FILE" ]; then
    if grep -q "flaiwheel\|Flaiwheel" "$COPILOT_FILE" 2>/dev/null; then
        python3 -c "
import re
content = open('$COPILOT_FILE', encoding='utf-8').read()
content = re.sub(
    r'(?:^---\n+)?^## Flaiwheel.*?(?=^## (?!Flaiwheel)|\Z)',
    '', content, flags=re.MULTILINE | re.DOTALL
).rstrip()
open('$COPILOT_FILE', 'w', encoding='utf-8').write(content + '\n')
"
        printf '\n---\n\n%s\n' "$FLAIWHEEL_COPILOT_BLOCK" >> "$COPILOT_FILE"
        ok "Updated Flaiwheel section in .github/copilot-instructions.md"
    else
        printf '\n---\n\n%s\n' "$FLAIWHEEL_COPILOT_BLOCK" >> "$COPILOT_FILE"
        ok "Appended Flaiwheel section to existing .github/copilot-instructions.md"
    fi
else
    printf '# Copilot Instructions\n\n%s\n' "$FLAIWHEEL_COPILOT_BLOCK" > "$COPILOT_FILE"
    ok "Created .github/copilot-instructions.md (VS Code Copilot instructions)"
fi
} # end _phase7d_vscode

# ══════════════════════════════════════════════════════
#  PHASE 8: Detect existing docs and create migration guide
# ══════════════════════════════════════════════════════

_phase8_migration() {
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
} # end _phase8_migration

# ══════════════════════════════════════════════════════
#  PHASE 9: Add .cursor entries to .gitignore (if needed)
# ══════════════════════════════════════════════════════

_phase9_gitignore() {
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
} # end _phase9_gitignore

# ══════════════════════════════════════════════════════
#  PHASE 10: Install post-commit git hook (Knowledge Capture)
# ══════════════════════════════════════════════════════

_phase10_hook() {
HOOK_CONF="${PROJECT_DIR}/.cursor/flaiwheel-hook.conf"
HOOK_DEST="${PROJECT_DIR}/.git/hooks/post-commit"

# Write hook config — no password needed.
# Flaiwheel trusts requests from 127.0.0.1 (localhost), so the hook
# authenticates implicitly by running on the same machine as the server.
cat > "$HOOK_CONF" << HOOKCONFEOF
# Flaiwheel hook config — DO NOT COMMIT (gitignored via .cursor/)
# Auto-generated by install.sh
# No credentials stored: Flaiwheel grants localhost requests without a password.
FLAIWHEEL_URL=http://localhost:8080
FLAIWHEEL_PROJECT=${PROJECT}
HOOKCONFEOF
chmod 600 "$HOOK_CONF"
ok "Hook config written: .cursor/flaiwheel-hook.conf (no credentials needed)"

# Download (or copy) the hook script and install it
HOOK_SCRIPT_URL="https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/flaiwheel-hook.sh"
HOOK_TMP=$(mktemp)

if curl -sSL "$HOOK_SCRIPT_URL" -o "$HOOK_TMP" 2>/dev/null && [ -s "$HOOK_TMP" ]; then
    install -m 755 "$HOOK_TMP" "$HOOK_DEST"
    rm -f "$HOOK_TMP"
    ok "post-commit hook installed: .git/hooks/post-commit"
    info "Every fix/feat/refactor/perf/docs commit will auto-capture knowledge"
elif [ -f "$(dirname "$0")/flaiwheel-hook.sh" ]; then
    # Fallback: use local copy when running from the repo itself
    install -m 755 "$(dirname "$0")/flaiwheel-hook.sh" "$HOOK_DEST"
    rm -f "$HOOK_TMP"
    ok "post-commit hook installed from local scripts/ (offline mode)"
else
    rm -f "$HOOK_TMP"
    warn "Could not install post-commit hook (network unavailable and no local copy)"
fi

# Ensure hook config is gitignored (already covered by .cursor/ rule, but be explicit)
if [ -f "$GITIGNORE" ] && ! grep -q "flaiwheel-hook.conf" "$GITIGNORE" 2>/dev/null; then
    echo "# Flaiwheel hook config (contains local credentials)" >> "$GITIGNORE"
    echo ".cursor/flaiwheel-hook.conf" >> "$GITIGNORE"
fi
} # end _phase10_hook

# ══════════════════════════════════════════════════════
#  Launch Phases 6-10 in parallel
# ══════════════════════════════════════════════════════

_phase6_cursor_mcp  & _PIDS+=($!) _PJOBS+=("cursor-mcp")
_phase7_cursor_rule & _PIDS+=($!) _PJOBS+=("cursor-rule")
_phase7b_agents_md  & _PIDS+=($!) _PJOBS+=("agents-md")
_phase7c_claude     & _PIDS+=($!) _PJOBS+=("claude-md")
_phase7d_vscode     & _PIDS+=($!) _PJOBS+=("vscode")
_phase8_migration   & _PIDS+=($!) _PJOBS+=("migration-guide")
_phase9_gitignore   & _PIDS+=($!) _PJOBS+=("gitignore")
_phase10_hook       & _PIDS+=($!) _PJOBS+=("git-hook")

wait_all
ok "All config files written"
rm -f "$_LOG_LOCK"

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
    echo -e "  ${BOLD}Config:${NC}        ${GREEN}.cursor/mcp.json${NC} + ${GREEN}.mcp.json${NC} + ${GREEN}.vscode/mcp.json${NC} + ${GREEN}.cursor/rules/flaiwheel.mdc${NC} + ${GREEN}AGENTS.md${NC} + ${GREEN}CLAUDE.md${NC}"
    echo ""
    echo -e "  ${BOLD}What to do next:${NC}"
    echo -e "    1. Restart Cursor to connect MCP (or toggle MCP off/on in Settings)"
    if [ "$CLAUDE_DESKTOP_REGISTERED" = true ]; then
        echo -e "    2. Claude Desktop: restart Claude for Mac to connect ${GREEN}✓${NC}"
    fi
    if [ "$CLAUDE_MCP_REGISTERED" = true ]; then
        echo -e "    3. Claude Code CLI: MCP already registered ${GREEN}✓${NC}"
    else
        echo -e "    3. Claude Code CLI: run once to register MCP:"
        echo -e "       ${GREEN}claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse${NC}"
    fi
    if [ "$VSCODE_REGISTERED" = true ]; then
        echo -e "    4. VS Code: open project, run ${BOLD}MCP: List Servers${NC} → start ${GREEN}flaiwheel${NC} ${GREEN}✓${NC}"
    fi
    echo -e "    5. Tell your AI agent: ${GREEN}set_project(\"${PROJECT}\")${NC}"
    echo -e "    6. Say ${YELLOW}\"This is the Way\"${NC} to bootstrap a messy docs repo"
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
    if [ "$CLAUDE_DESKTOP_REGISTERED" = true ]; then
        echo -e "    2. Claude Desktop: restart Claude for Mac to reconnect ${GREEN}✓${NC}"
    fi
    if [ "$CLAUDE_MCP_REGISTERED" = true ]; then
        echo -e "    3. Claude Code CLI: MCP already registered ${GREEN}✓${NC}"
    else
        echo -e "    3. Claude Code CLI: re-run if needed:"
        echo -e "       ${GREEN}claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse${NC}"
    fi
    if [ "$VSCODE_REGISTERED" = true ]; then
        echo -e "    4. VS Code: run ${BOLD}MCP: List Servers${NC} → restart ${GREEN}flaiwheel${NC} if needed ${GREEN}✓${NC}"
    fi
    echo -e "    5. Open the Web UI at ${GREEN}http://localhost:8080${NC} to verify"
else
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║         Setup Complete                       ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}What was created:${NC}"
    echo -e "    Knowledge repo:  ${GREEN}https://github.com/${OWNER}/${KNOWLEDGE_REPO}${NC}"
    echo -e "    Container:       ${GREEN}${CONTAINER_NAME}${NC}"
    echo -e "    Cursor config:   ${GREEN}.cursor/mcp.json${NC} + ${GREEN}.cursor/rules/flaiwheel.mdc${NC}"
    echo -e "    Claude Desktop:  ${GREEN}~/Library/Application Support/Claude/claude_desktop_config.json${NC}"
    echo -e "    Claude Code CLI: ${GREEN}.mcp.json${NC} + ${GREEN}CLAUDE.md${NC}"
    echo -e "    VS Code:         ${GREEN}.vscode/mcp.json${NC} + ${GREEN}.github/copilot-instructions.md${NC}"
    echo -e "    Agent guide:     ${GREEN}AGENTS.md${NC}"
    echo -e "    Git hook:        ${GREEN}.git/hooks/post-commit${NC} (auto-captures commits)"
    echo ""
    echo -e "  ${BOLD}What to do next:${NC}"
    echo -e "    1. Restart Cursor"
    echo -e "    2. Go to ${BOLD}Cursor Settings → MCP${NC} and enable ${GREEN}flaiwheel${NC} if the toggle is off"
    if [ "$CLAUDE_DESKTOP_REGISTERED" = true ]; then
        echo -e "    3. Restart ${BOLD}Claude for Mac${NC} to connect Flaiwheel ${GREEN}✓${NC}"
    fi
    if [ "$CLAUDE_MCP_REGISTERED" = true ]; then
        echo -e "    4. Claude Code CLI: MCP already registered ${GREEN}✓${NC}"
    else
        echo -e "    4. Claude Code CLI: run once to register MCP:"
        echo -e "       ${GREEN}claude mcp add --transport sse --scope project flaiwheel http://localhost:8081/sse${NC}"
    fi
    if [ "$VSCODE_REGISTERED" = true ]; then
        echo -e "    5. VS Code: open project, run ${BOLD}MCP: List Servers${NC} (Cmd+Shift+P), start ${GREEN}flaiwheel${NC} ${GREEN}✓${NC}"
    fi
    echo -e "    6. Open the Web UI at ${GREEN}http://localhost:8080${NC} to verify"
    echo -e "    7. See the full README: ${GREEN}https://github.com/dl4rce/flaiwheel#readme${NC}"
fi
echo ""
if [ "${MD_COUNT:-0}" -gt 2 ]; then
    echo -e "  ${YELLOW}Tip:${NC} Tell Cursor AI: \"migrate docs\" to organize existing"
    echo -e "       documentation into the knowledge repo."
    echo ""
fi
echo -e "  ${BOLD}Endpoints:${NC}"
echo -e "    Web UI:     ${GREEN}http://localhost:8080${NC}"
echo -e "    MCP (SSE):  ${GREEN}http://localhost:8081/sse${NC}"
echo ""

# Always try to show credentials — consolidate all sources here in the summary.
# FAST_PATH/UPDATE_MODE: password unchanged, try to read from running container.
# Fresh install: ADMIN_PASS was set during health-check polling.
# Fallback: one final read attempt in case container just finished starting.
_DISPLAY_PASS="${ADMIN_PASS:-}"
if [ -z "$_DISPLAY_PASS" ]; then
    _DISPLAY_PASS=$(docker exec "${CONTAINER_NAME}" cat /data/.admin_password 2>/dev/null || true)
fi
if [ -z "$_DISPLAY_PASS" ]; then
    _DISPLAY_PASS=$(docker logs "${CONTAINER_NAME}" 2>&1 | grep -m1 "Password:" | awk '{print $NF}' || true)
fi

if [ -n "$_DISPLAY_PASS" ]; then
    echo -e "  ${BOLD}╔════════════════════════════════════════════╗${NC}"
    echo -e "  ${BOLD}║  Web UI Login                              ║${NC}"
    echo -e "  ${BOLD}║                                            ║${NC}"
    echo -e "  ${BOLD}║  URL:       ${GREEN}http://localhost:8080${NC}${BOLD}         ║${NC}"
    echo -e "  ${BOLD}║  Username:  ${GREEN}admin${NC}${BOLD}                           ║${NC}"
    echo -e "  ${BOLD}║  Password:  ${GREEN}${_DISPLAY_PASS}${BOLD}${NC}${BOLD}              ║${NC}"
    echo -e "  ${BOLD}║                                            ║${NC}"
    echo -e "  ${BOLD}║  ${YELLOW}Save this — it won't be shown again!${NC}${BOLD}     ║${NC}"
    echo -e "  ${BOLD}╚════════════════════════════════════════════╝${NC}"
else
    echo -e "  ${YELLOW}${BOLD}Container is still starting (embedding model download in progress).${NC}"
    echo -e "  Watch progress:  ${GREEN}docker logs -f ${CONTAINER_NAME}${NC}"
    echo -e "  Get credentials: ${GREEN}docker logs ${CONTAINER_NAME} 2>&1 | grep 'Password:'${NC}"
    echo -e "  Or read file:    ${GREEN}docker exec ${CONTAINER_NAME} cat /data/.admin_password${NC}"
fi
echo ""
