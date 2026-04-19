#!/usr/bin/env bash
# Flaiwheel helper — macOS LaunchAgent for Open WebUI "Open Terminal" (bare-metal open-terminal).
# Model: Composer (Cursor agent)
#
# Installs a user LaunchAgent that runs:
#   open-terminal run --host <HOST> --port <PORT>
#   OR  python3 -m open_terminal run ...
# with OPEN_TERMINAL_API_KEY from ~/.config/flaiwheel/open-terminal-api-key
#
# API key: always generated randomly and printed once per install/reset (no typing). Update Open WebUI
# if you use menu option 2 (new key).
#
# Dependency bootstrap (interactive by default):
#   - Python 3.11+ via Homebrew (python@3.12) if missing
#   - Homebrew itself if missing (optional; official install script)
#   - open-terminal via pipx (preferred) or pip install --user
#
# Usage:
#   ./install-open-terminal-launchagent.sh
#   AUTO_INSTALL_DEPS=1 ./install-open-terminal-launchagent.sh   # non-interactive: yes to safe installs
#   BREW_PYTHON_FORMULA=python@3.13 HOST=127.0.0.1 PORT=8000 ./install-open-terminal-launchagent.sh
#   OPEN_TERMINAL_CORS_ALLOWED_ORIGINS='https://your-openwebui.example' ./install-open-terminal-launchagent.sh
#
# Default folder for Open Terminal (PTY / os.getcwd): launchd WorkingDirectory. Without it, cwd can be /private/tmp.
#   • Saved path: ~/.config/flaiwheel/open-terminal-working-directory (first line = directory). Set via fresh-install
#     prompt, menu →5, or by creating that file yourself. Persists across Update (menu →1).
#   • One-off override: OPEN_TERMINAL_WORKING_DIRECTORY=/path ./install-open-terminal-launchagent.sh (wins over saved file).
#   • Non-interactive fresh install: no prompt if AUTO_INSTALL_DEPS=1; use env or pre-create the saved-path file.
#   • Skip install prompt: SKIP_WORKING_DIR_PROMPT=1
# Directory must exist before it is saved. Default when nothing saved: $HOME.
#
# Optional: SKIP_OT_SELF_CHECK=1  — skip `run --help` smoke test
# Override: PYTHON3_BIN=/path/to/python3.12 OPEN_TERMINAL_BIN=/path/to/open-terminal
#
# Do NOT use sudo. User LaunchAgents load in gui/$(id -u); root gets launchctl error 125.
# If you see "Permission denied" on the API key or .plist (often after a past sudo run):
#   sudo chown -R "$(whoami)" ~/.config/flaiwheel ~/Library/LaunchAgents
#
# Default HOST is 127.0.0.1 (local only). Match a manual `open-terminal run --host 0.0.0.0` with:
#   HOST=0.0.0.0 ./install-open-terminal-launchagent.sh
#   (already installed? run again and choose menu (1) Update.)
#
# Same local install on every macOS: copy this script, run the same command (optionally
# AUTO_INSTALL_DEPS=1). Only set OPEN_TERMINAL_CORS_ALLOWED_ORIGINS if you need a non-* allowlist
# for cross-origin browser access; otherwise defaults match a normal local Open Terminal setup.

set -euo pipefail

LABEL="com.flaiwheel.open-terminal-local"
STATE_DIR="${HOME}/.config/flaiwheel"
KEY_FILE="${STATE_DIR}/open-terminal-api-key"
WRAPPER="${STATE_DIR}/open-terminal-launchagent-wrapper.sh"
# Optional: first line = absolute or ~/… path; used for launchd WorkingDirectory unless env overrides (see resolve_ot_working_directory).
WORKING_DIR_STATE_FILE="${STATE_DIR}/open-terminal-working-directory"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_OUT="${HOME}/Library/Logs/${LABEL}.out.log"
LOG_ERR="${HOME}/Library/Logs/${LABEL}.err.log"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
# Comma-separated origins for CORS when the Open WebUI tab is not same-origin as this service. Default *.
CORS_ALLOWED_ORIGINS="${OPEN_TERMINAL_CORS_ALLOWED_ORIGINS:-*}"
BREW_PYTHON_FORMULA="${BREW_PYTHON_FORMULA:-python@3.12}"

# Process initial cwd for open-terminal (launchd WorkingDirectory). See header comment.
# Precedence: OPEN_TERMINAL_WORKING_DIRECTORY (env) → saved file → $HOME.
_expand_working_path_fragment() {
  local raw="$1"
  case "${raw}" in
    \~|\~/)
      printf '%s' "${HOME}"
      ;;
    \~/*)
      printf '%s' "${HOME}/${raw#\~/}"
      ;;
    *)
      printf '%s' "${raw}"
      ;;
  esac
}

resolve_ot_working_directory() {
  local raw=""
  if [[ -n "${OPEN_TERMINAL_WORKING_DIRECTORY-}" ]]; then
    raw="${OPEN_TERMINAL_WORKING_DIRECTORY}"
  elif [[ -f "${WORKING_DIR_STATE_FILE}" ]]; then
    raw="$(sed -n '1p' "${WORKING_DIR_STATE_FILE}" 2>/dev/null | tr -d '\r')"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
  fi
  if [[ -z "${raw}" ]]; then
    printf '%s' "${HOME}"
    return 0
  fi
  _expand_working_path_fragment "${raw}"
}

canonicalize_existing_dir() {
  local d="$1"
  if [[ ! -d "${d}" ]]; then
    die "Not a directory: ${d}"
  fi
  if command -v realpath >/dev/null 2>&1; then
    realpath "${d}"
  else
    (cd "${d}" && pwd)
  fi
}

save_working_directory_state() {
  local abs="$1"
  ensure_state_dir_writable
  printf '%s\n' "${abs}" >"${WORKING_DIR_STATE_FILE}"
  chmod 600 "${WORKING_DIR_STATE_FILE}" 2>/dev/null || true
}

clear_working_directory_state() {
  rm -f "${WORKING_DIR_STATE_FILE}"
  echo "Removed saved working directory — default is now \$HOME (until you save another path)."
}

prompt_fresh_working_directory_once() {
  if [[ ! -t 0 ]] || [[ "${SKIP_WORKING_DIR_PROMPT:-0}" == "1" ]] || [[ "${AUTO_INSTALL_DEPS:-0}" == "1" ]]; then
    return 0
  fi
  if [[ -f "${WORKING_DIR_STATE_FILE}" ]]; then
    return 0
  fi
  local line exp
  echo ""
  echo "Open Terminal’s initial folder (launchd WorkingDirectory). Press Enter to use \$HOME, or enter a path (~/… ok)."
  read -r -p "Path [${HOME}]: " line || true
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  if [[ -z "${line}" ]]; then
    return 0
  fi
  exp="$(_expand_working_path_fragment "${line}")"
  exp="$(canonicalize_existing_dir "${exp}")"
  save_working_directory_state "${exp}"
  echo "Saved working directory: ${exp}"
}

configure_saved_working_directory() {
  refuse_root
  ensure_dirs
  ensure_state_dir_writable
  local line exp cur
  cur="$(resolve_ot_working_directory)"
  echo ""
  echo "Effective directory for this script run: ${cur}"
  if [[ -n "${OPEN_TERMINAL_WORKING_DIRECTORY-}" ]]; then
    echo "Note: OPEN_TERMINAL_WORKING_DIRECTORY is set in the environment and overrides the saved file for this run."
  fi
  if [[ -f "${WORKING_DIR_STATE_FILE}" ]]; then
    echo "Saved in: ${WORKING_DIR_STATE_FILE}"
  else
    echo "No file saved yet — default is \$HOME."
  fi
  echo "Enter a folder path to save (~/… ok), or leave blank to clear the saved path and use \$HOME."
  read -r -p "Path: " line || true
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  if [[ -z "${line}" ]]; then
    clear_working_directory_state
    if [[ -f "${PLIST}" ]]; then
      check_all_dependencies
      write_plist
      load_agent
      echo "LaunchAgent reloaded."
    fi
    return 0
  fi
  exp="$(_expand_working_path_fragment "${line}")"
  exp="$(canonicalize_existing_dir "${exp}")"
  save_working_directory_state "${exp}"
  echo "Saved: ${exp}"
  if [[ -f "${PLIST}" ]]; then
    check_all_dependencies
    write_plist
    load_agent
    echo "LaunchAgent reloaded with new WorkingDirectory."
  fi
}

plist_xml_escape() {
  local s="$1"
  s="${s//&/&amp;}"
  s="${s//</&lt;}"
  s="${s//>/&gt;}"
  printf '%s' "${s}"
}

# open-terminal requires Python 3.11+ (see upstream pyproject.toml).
PY_MIN_MAJOR=3
PY_MIN_MINOR=11

die() {
  echo "error: $*" >&2
  exit 1
}

ensure_dirs() {
  mkdir -p "${STATE_DIR}" "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"
}

# ~/.config/flaiwheel created with sudo is root-owned → printf to KEY_FILE fails for normal user.
ensure_state_dir_writable() {
  if [[ -d "${STATE_DIR}" && ! -w "${STATE_DIR}" ]]; then
    die "${STATE_DIR} is not writable (often after a past 'sudo' run). Fix, then re-run **without** sudo:
  sudo chown -R \"$(whoami)\" \"${STATE_DIR}\""
  fi
  if [[ -f "${KEY_FILE}" && ! -w "${KEY_FILE}" ]]; then
    die "${KEY_FILE} is not writable. Fix, then re-run without sudo:
  sudo chown \"$(whoami)\" \"${KEY_FILE}\" && chmod 600 \"${KEY_FILE}\""
  fi
  if [[ -f "${WRAPPER}" && ! -w "${WRAPPER}" ]]; then
    die "${WRAPPER} is not writable. Fix:
  sudo chown \"$(whoami)\" \"${WRAPPER}\" && chmod 700 \"${WRAPPER}\""
  fi
  if [[ -f "${WORKING_DIR_STATE_FILE}" && ! -w "${WORKING_DIR_STATE_FILE}" ]]; then
    die "${WORKING_DIR_STATE_FILE} is not writable. Fix:
  sudo chown \"$(whoami)\" \"${WORKING_DIR_STATE_FILE}\" && chmod 600 \"${WORKING_DIR_STATE_FILE}\""
  fi
}

# ~/Library/LaunchAgents root-owned → cat > *.plist fails with "Permission denied".
ensure_launch_agents_writable() {
  local la="${HOME}/Library/LaunchAgents"
  mkdir -p "${la}" 2>/dev/null || true
  if [[ ! -w "${la}" ]]; then
    echo "error: ${la} is not writable (often after a past 'sudo' run)." >&2
    if ask_yes_no_auto 0 "Fix with: sudo chown -R $(whoami) on that folder? (password may be required)"; then
      sudo chown -R "$(whoami)" "${la}" || die "sudo chown failed."
    else
      die "Run manually: sudo chown -R \"$(whoami)\" \"${la}\""
    fi
    if [[ ! -w "${la}" ]]; then
      die "${la} still not writable after chown."
    fi
  fi
  if [[ -f "${PLIST}" && ! -w "${PLIST}" ]]; then
    echo "error: ${PLIST} is not writable (e.g. root-owned plist from an old sudo run)." >&2
    if ask_yes_no_auto 0 "Fix with: sudo chown $(whoami) on this file? (password may be required)"; then
      sudo chown "$(whoami)" "${PLIST}" && sudo chmod 644 "${PLIST}" || die "sudo chown/chmod failed."
    else
      die "Run manually: sudo chown \"$(whoami)\" \"${PLIST}\" && chmod 644 \"${PLIST}\""
    fi
    if [[ ! -w "${PLIST}" ]]; then
      die "${PLIST} still not writable after chown."
    fi
  fi
}

refuse_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    echo "error: Do not run this script with sudo." >&2
    echo "  User LaunchAgents live in ~/Library/LaunchAgents and use launchctl gui/<your-uid>." >&2
    echo "  As root you get: Bootstrap failed: 125 (Domain does not support specified action)." >&2
    echo "  Run as your normal macOS user:  ./install-open-terminal-launchagent.sh" >&2
    if [[ -n "${SUDO_USER:-}" ]]; then
      echo "  If files became root-owned, run as ${SUDO_USER}:" >&2
      echo "    sudo chown -R ${SUDO_USER} /Users/${SUDO_USER}/.config/flaiwheel /Users/${SUDO_USER}/Library/LaunchAgents" >&2
    fi
    exit 1
  fi
}

# AUTO_INSTALL_DEPS=1 → answer "yes" to install prompts (Homebrew install script still requires [y/N] carefully).
ask_yes() {
  local default_yes="$1" prompt="$2" ans
  if [[ "${AUTO_INSTALL_DEPS:-0}" == "1" ]]; then
    echo "${prompt} → yes (AUTO_INSTALL_DEPS=1)"
    return 0
  fi
  if [[ "${default_yes}" == "1" ]]; then
    read -rp "${prompt} [Y/n]: " ans
    [[ -z "${ans}" || "${ans}" =~ ^[Yy] ]]
  else
    read -rp "${prompt} [y/N]: " ans
    [[ "${ans}" =~ ^[Yy] ]]
  fi
}

# Never implied by AUTO_INSTALL_DEPS (sudo must stay an explicit human choice).
ask_yes_no_auto() {
  local default_yes="$1" prompt="$2" ans
  if [[ "${default_yes}" == "1" ]]; then
    read -rp "${prompt} [Y/n]: " ans
    [[ -z "${ans}" || "${ans}" =~ ^[Yy] ]]
  else
    read -rp "${prompt} [y/N]: " ans
    [[ "${ans}" =~ ^[Yy] ]]
  fi
}

# --- Homebrew ----------------------------------------------------------------

eval_brew_shellenv_if_possible() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

find_brew() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    echo /opt/homebrew/bin/brew
    return 0
  fi
  if [[ -x /usr/local/bin/brew ]]; then
    echo /usr/local/bin/brew
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    command -v brew
    return 0
  fi
  return 1
}

ensure_homebrew() {
  if find_brew >/dev/null 2>&1; then
    return 0
  fi
  echo "Homebrew was not found."
  ask_yes 0 "Install Homebrew using the official script (https://brew.sh)? This runs a downloaded bash script and may prompt for your password." || \
    die "Install Homebrew manually from https://brew.sh — then re-run this script."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval_brew_shellenv_if_possible
  hash -r 2>/dev/null || true
  if ! find_brew >/dev/null 2>&1; then
    echo "" >&2
    echo "Homebrew was installed but is not on PATH in this shell." >&2
    echo "  Apple Silicon: eval \"\$(/opt/homebrew/bin/brew shellenv)\"" >&2
    echo "  Intel:         eval \"\$(/usr/local/bin/brew shellenv)\"" >&2
    echo "Then re-run this script." >&2
    die "brew not on PATH after install."
  fi
}

install_homebrew_python() {
  local brew_bin
  brew_bin="$(find_brew)"
  echo "Running: ${brew_bin} install ${BREW_PYTHON_FORMULA}"
  "${brew_bin}" install "${BREW_PYTHON_FORMULA}"
}

# --- Python ------------------------------------------------------------------

python3_version_ok() {
  local py="${1:-python3}"
  "${py}" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (${PY_MIN_MAJOR}, ${PY_MIN_MINOR}) else 1)" 2>/dev/null
}

resolve_python3() {
  local c candidates=()

  if [[ -n "${PYTHON3_BIN:-}" && -x "${PYTHON3_BIN}" ]]; then
    echo "${PYTHON3_BIN}"
    return 0
  fi

  local static=(
    /opt/homebrew/opt/python@3.13/bin/python3.13
    /opt/homebrew/opt/python@3.12/bin/python3.12
    /opt/homebrew/opt/python@3.11/bin/python3.11
    /usr/local/opt/python@3.13/bin/python3.13
    /usr/local/opt/python@3.12/bin/python3.12
    /usr/local/opt/python@3.11/bin/python3.11
  )
  for c in "${static[@]}"; do
    [[ -x "${c}" ]] && candidates+=("${c}")
  done

  local b px
  b="$(find_brew 2>/dev/null)" || true
  if [[ -n "${b}" ]]; then
    for f in python@3.13 python@3.12 python@3.11; do
      px="$("${b}" --prefix "${f}" 2>/dev/null)" || continue
      if [[ -d "${px}/bin" ]]; then
        shopt -s nullglob
        for c in "${px}/bin/python3."[0-9]*; do
          [[ -x "${c}" ]] && candidates+=("${c}")
        done
        shopt -u nullglob
        [[ -x "${px}/bin/python3" ]] && candidates+=("${px}/bin/python3")
      fi
    done
  fi

  candidates+=(
    "$(command -v python3.13 2>/dev/null || true)"
    "$(command -v python3.12 2>/dev/null || true)"
    "$(command -v python3.11 2>/dev/null || true)"
    "$(command -v python3 2>/dev/null || true)"
  )

  for c in "${candidates[@]}"; do
    [[ -z "${c}" || ! -x "${c}" ]] && continue
    if python3_version_ok "${c}"; then
      echo "${c}"
      return 0
    fi
  done
  return 1
}

ensure_python3() {
  local py ver
  if py="$(resolve_python3)"; then
    ver="$("${py}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    echo "  OK  Python ${py} (${ver})"
    return 0
  fi

  echo "  … no Python ${PY_MIN_MAJOR}.${PY_MIN_MINOR}+ on PATH or in common Homebrew locations."

  ask_yes 1 "Install Python via Homebrew (${BREW_PYTHON_FORMULA})? (Installs Homebrew first if needed.)" || \
    die "Set PYTHON3_BIN to a Python 3.11+ executable, or install Python manually."

  ensure_homebrew
  eval_brew_shellenv_if_possible
  install_homebrew_python
  eval_brew_shellenv_if_possible

  hash -r 2>/dev/null || true
  if ! py="$(resolve_python3)"; then
    echo "" >&2
    echo "Python was installed but this shell may not see it yet. Try:" >&2
    echo "  eval \"\$(\"$(find_brew)\" shellenv)\"" >&2
    echo "Then re-run this script." >&2
    die "Still no suitable python3 after brew install ${BREW_PYTHON_FORMULA}."
  fi
  ver="$("${py}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
  echo "  OK  Python ${py} (${ver})"
}

python3_has_open_terminal_module() {
  local py="$1"
  "${py}" -c "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('open_terminal') else 1)" 2>/dev/null
}

# --- open-terminal -----------------------------------------------------------

# Sets globals: OT_MODE (bin|module), OT_PATH
resolve_open_terminal() {
  OT_MODE=""
  OT_PATH=""
  local c py

  if [[ -n "${OPEN_TERMINAL_BIN:-}" && -x "${OPEN_TERMINAL_BIN}" ]]; then
    OT_MODE="bin"
    OT_PATH="${OPEN_TERMINAL_BIN}"
    return 0
  fi

  c="$(command -v open-terminal 2>/dev/null || true)"
  if [[ -n "${c}" && -x "${c}" ]]; then
    OT_MODE="bin"
    OT_PATH="${c}"
    return 0
  fi

  for c in /opt/homebrew/bin/open-terminal /usr/local/bin/open-terminal "${HOME}/.local/bin/open-terminal"; do
    if [[ -x "${c}" ]]; then
      OT_MODE="bin"
      OT_PATH="${c}"
      return 0
    fi
  done

  py="$(resolve_python3)" || return 1
  if python3_has_open_terminal_module "${py}"; then
    OT_MODE="module"
    OT_PATH="${py}"
    return 0
  fi

  return 1
}

ensure_pipx() {
  command -v pipx >/dev/null 2>&1 && return 0
  local brew_bin
  brew_bin="$(find_brew)" || die "Homebrew required to install pipx."
  ask_yes 1 "Install pipx via Homebrew (recommended for open-terminal)?" || return 1
  "${brew_bin}" install pipx
  hash -r 2>/dev/null || true
  command -v pipx >/dev/null 2>&1 || die "pipx not on PATH after brew install pipx. Run: eval \"\$($(find_brew) shellenv)\" — then re-run."
}

ensure_open_terminal_package() {
  if resolve_open_terminal; then
    return 0
  fi

  echo "  … open-terminal CLI / module not found."

  local py
  py="$(resolve_python3)" || die "Python missing (ensure_python3 should have run first)."

  ask_yes 1 "Install open-terminal now? (prefers pipx; falls back to: ${py} -m pip install --user)" || \
    die "Install open-terminal, then re-run: pipx install open-terminal"

  if command -v pipx >/dev/null 2>&1; then
    pipx install open-terminal
  elif ensure_pipx; then
    pipx install open-terminal
  else
    echo "  … installing with: ${py} -m pip install --user open-terminal"
    "${py}" -m pip install --user open-terminal
    hash -r 2>/dev/null || true
  fi

  if ! resolve_open_terminal; then
    die "open-terminal still not found. Run: eval \"\$(/opt/homebrew/bin/brew shellenv)\" (Apple Silicon) or eval \"\$(/usr/local/bin/brew shellenv)\" (Intel), then re-run; or: pipx install open-terminal"
  fi
}

verify_open_terminal_runs() {
  [[ "${SKIP_OT_SELF_CHECK:-0}" == "1" ]] && return 0
  if [[ "${OT_MODE}" == bin ]]; then
    "${OT_PATH}" run --help >/dev/null 2>&1 || die "open-terminal at ${OT_PATH} failed (run --help). Try: pipx reinstall open-terminal"
  else
    "${OT_PATH}" -m open_terminal run --help >/dev/null 2>&1 || die "python -m open_terminal failed (run --help) with ${OT_PATH}"
  fi
}

check_all_dependencies() {
  echo "Checking dependencies (install missing pieces when you confirm; set AUTO_INSTALL_DEPS=1 to auto-yes)..."
  eval_brew_shellenv_if_possible
  ensure_python3

  if ! command -v launchctl >/dev/null 2>&1; then
    die "launchctl not found (unexpected on macOS)."
  fi
  echo "  OK  launchctl"

  ensure_open_terminal_package

  if [[ "${OT_MODE}" == bin ]]; then
    echo "  OK  open-terminal binary: ${OT_PATH}"
  else
    echo "  OK  open-terminal via: ${OT_PATH} -m open_terminal"
  fi

  verify_open_terminal_runs
  echo "  OK  open-terminal smoke test (run --help)"

  if command -v openssl >/dev/null 2>&1; then
    echo "  OK  openssl (for random API keys)"
  else
    echo "  OK  python secrets fallback (openssl not in PATH)"
  fi
  echo ""
}

write_wrapper() {
  ensure_state_dir_writable
  local mode="$1" path="$2"
  local cors_q
  cors_q="$(printf '%q' "${CORS_ALLOWED_ORIGINS}")"
  if [[ "${mode}" == bin ]]; then
    cat >"${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export OPEN_TERMINAL_API_KEY="\$(cat "\${HOME}/.config/flaiwheel/open-terminal-api-key")"
exec "${path}" run --host "${HOST}" --port "${PORT}" --cors-allowed-origins ${cors_q}
EOF
  else
    cat >"${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export OPEN_TERMINAL_API_KEY="\$(cat "\${HOME}/.config/flaiwheel/open-terminal-api-key")"
exec "${path}" -m open_terminal run --host "${HOST}" --port "${PORT}" --cors-allowed-origins ${cors_q}
EOF
  fi
  chmod 700 "${WRAPPER}"
}

write_random_api_key() {
  ensure_state_dir_writable
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr -d '\n' >"${KEY_FILE}"
  else
    local py
    py="$(resolve_python3)" || die "python3 needed for random key"
    "${py}" -c 'import secrets; print(secrets.token_urlsafe(32), end="")' >"${KEY_FILE}"
  fi
  chmod 600 "${KEY_FILE}"
}

write_plist() {
  ensure_launch_agents_writable
  local wd wd_esc
  wd="$(resolve_ot_working_directory)"
  if [[ ! -d "${wd}" ]]; then
    die "Working directory does not exist: ${wd} — create it, or unset OPEN_TERMINAL_WORKING_DIRECTORY to use ${HOME}."
  fi
  wd_esc="$(plist_xml_escape "${wd}")"
  cat >"${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${WRAPPER}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${wd_esc}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_OUT}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_ERR}</string>
</dict>
</plist>
EOF
}

load_agent() {
  launchctl bootout "gui/$(id -u)" "${PLIST}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "${PLIST}"
  launchctl enable "gui/$(id -u)/${LABEL}"
  launchctl kickstart -k "gui/$(id -u)/${LABEL}"
}

restart_agent_if_loaded() {
  if [[ -f "${PLIST}" ]]; then
    launchctl kickstart -k "gui/$(id -u)/${LABEL}" 2>/dev/null || true
  fi
}

unload_remove() {
  launchctl bootout "gui/$(id -u)" "${PLIST}" 2>/dev/null || true
  rm -f "${PLIST}"
  echo "LaunchAgent disabled and plist removed."
  echo "Wrapper, API key, and optional ${WORKING_DIR_STATE_FILE} are still on disk (delete manually if desired)."
}

print_owui_hint() {
  local key wd_hint
  key="$(cat "${KEY_FILE}")"
  wd_hint="$(resolve_ot_working_directory)"
  if [[ ! -d "${wd_hint}" ]]; then
    wd_hint="${wd_hint} (directory missing — fix before menu →1 Update)"
  fi
  echo ""
  echo "=== Open WebUI — Open Terminal ==="
  echo "URL:  http://localhost:${PORT}"
  echo "API key (Bearer):  ${key}"
  echo "Docs: http://localhost:${PORT}/docs"
  echo ""
  echo "LaunchAgent WorkingDirectory (open-terminal initial cwd): ${wd_hint}"
  if [[ -n "${OPEN_TERMINAL_WORKING_DIRECTORY-}" ]]; then
    echo "This run: OPEN_TERMINAL_WORKING_DIRECTORY is set (overrides saved file for this script only)."
  fi
  if [[ -f "${WORKING_DIR_STATE_FILE}" ]]; then
    echo "Saved path file: ${WORKING_DIR_STATE_FILE} — change with menu →5 or edit that file."
  else
    echo "No saved custom path (defaults to \$HOME). Menu →5 to save a folder; or OPEN_TERMINAL_WORKING_DIRECTORY for one-off."
  fi
  echo ""
  echo "Listening on ${HOST}:${PORT} (default is 127.0.0.1 — use HOST=0.0.0.0 to match: open-terminal run --host 0.0.0.0 … then menu →1 Update)."
  echo "CORS allowlist: ${CORS_ALLOWED_ORIGINS} (override with OPEN_TERMINAL_CORS_ALLOWED_ORIGINS=… then menu →1 Update)."
  if [[ "${CORS_ALLOWED_ORIGINS}" == "*" ]]; then
    echo "Note: Cross-origin browser errors → set OPEN_TERMINAL_CORS_ALLOWED_ORIGINS to your Open WebUI origin, re-run, menu (1) Update."
  fi
  if command -v pipx >/dev/null 2>&1 && [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
    echo ""
    echo "Tip: pipx said ~/.local/bin is not on PATH — fine for this daemon (full paths), but for your shell run: pipx ensurepath"
  fi
}

install_fresh() {
  refuse_root
  ensure_dirs
  ensure_state_dir_writable
  prompt_fresh_working_directory_once
  check_all_dependencies
  write_random_api_key
  write_wrapper "${OT_MODE}" "${OT_PATH}"
  write_plist
  load_agent
  print_owui_hint
  echo "LaunchAgent installed: ${PLIST}"
}

update_agent() {
  refuse_root
  ensure_dirs
  ensure_state_dir_writable
  check_all_dependencies
  if [[ ! -f "${KEY_FILE}" ]]; then
    write_random_api_key
    echo "  (created missing API key file — copy Bearer from summary below into Open WebUI)"
  fi
  write_wrapper "${OT_MODE}" "${OT_PATH}"
  write_plist
  load_agent
  print_owui_hint
  echo "LaunchAgent updated and reloaded."
}

reset_api_key_and_restart() {
  refuse_root
  ensure_dirs
  ensure_state_dir_writable
  if [[ ! -f "${PLIST}" ]]; then
    die "LaunchAgent not installed; run this script once without an existing plist."
  fi
  check_all_dependencies
  write_random_api_key
  restart_agent_if_loaded
  print_owui_hint
  echo "New random API key is active — update the Bearer token in Open WebUI to match the line above."
}

menu_second_run() {
  echo "Open Terminal LaunchAgent is already installed (${LABEL})."
  echo "  1) Update / reload (refresh wrapper + plist + restart agent; keeps current API key)"
  echo "  2) Reset API key (new random key + restart agent; update Open WebUI)"
  echo "  3) Disable / uninstall agent (unload + remove plist)"
  echo "  4) Cancel"
  echo "  5) Set saved working directory (Open Terminal start folder; persists for future 1/Update)"
  read -r -p "Choose [1-5]: " choice
  case "${choice}" in
    1) update_agent ;;
    2) reset_api_key_and_restart ;;
    3) unload_remove ;;
    4) echo "No changes." ;;
    5) configure_saved_working_directory; print_owui_hint ;;
    *) die "invalid choice" ;;
  esac
}

main() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    die "This script is for macOS only."
  fi

  if [[ -f "${PLIST}" ]]; then
    refuse_root
    menu_second_run
  else
    install_fresh
  fi
}

main "$@"
