#!/usr/bin/env bash
# Flaiwheel helper — Linux/WSL2 systemd --user service for Open WebUI "Open Terminal".
# Model: Codex 5.3
#
# Installs a user service that runs:
#   open-terminal run --host <HOST> --port <PORT>
#   OR  python3 -m open_terminal run ...
# with OPEN_TERMINAL_API_KEY from ~/.config/flaiwheel/open-terminal-api-key
#
# API key: always generated randomly and printed once per install/reset.
#
# Usage:
#   ./install-open-terminal-systemd-user.sh
#   AUTO_INSTALL_DEPS=1 ./install-open-terminal-systemd-user.sh
#   HOST=0.0.0.0 PORT=8000 ./install-open-terminal-systemd-user.sh
#   OPEN_TERMINAL_CORS_ALLOWED_ORIGINS='https://your-openwebui.example' ./install-open-terminal-systemd-user.sh
#
# Optional:
#   OPEN_TERMINAL_BIN=/absolute/path/to/open-terminal
#   PYTHON3_BIN=/absolute/path/to/python3.11+
#   SKIP_OT_SELF_CHECK=1
#
# Notes:
# - Do NOT run with sudo.
# - Requires systemd --user. On WSL2, enable systemd first:
#   - Add to /etc/wsl.conf:
#       [boot]
#       systemd=true
#   - Then run: wsl --shutdown (from Windows PowerShell) and reopen your distro.

set -euo pipefail

LABEL="com.flaiwheel.open-terminal-local"
STATE_DIR="${HOME}/.config/flaiwheel"
KEY_FILE="${STATE_DIR}/open-terminal-api-key"
WRAPPER="${STATE_DIR}/open-terminal-systemd-wrapper.sh"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SYSTEMD_USER_DIR}/${LABEL}.service"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
CORS_ALLOWED_ORIGINS="${OPEN_TERMINAL_CORS_ALLOWED_ORIGINS:-*}"

PY_MIN_MAJOR=3
PY_MIN_MINOR=11

die() {
  echo "error: $*" >&2
  exit 1
}

ask_yes() {
  local default_yes="$1" prompt="$2" ans
  if [[ "${AUTO_INSTALL_DEPS:-0}" == "1" ]]; then
    echo "${prompt} -> yes (AUTO_INSTALL_DEPS=1)"
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

refuse_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    echo "error: Do not run this script with sudo/root." >&2
    echo "  Run as your normal user: ./install-open-terminal-systemd-user.sh" >&2
    if [[ -n "${SUDO_USER:-}" ]]; then
      echo "  If files became root-owned, run as ${SUDO_USER}:" >&2
      echo "    sudo chown -R ${SUDO_USER}:${SUDO_USER} /home/${SUDO_USER}/.config/flaiwheel /home/${SUDO_USER}/.config/systemd/user" >&2
    fi
    exit 1
  fi
}

ensure_dirs() {
  mkdir -p "${STATE_DIR}" "${SYSTEMD_USER_DIR}"
}

ensure_writable() {
  if [[ -d "${STATE_DIR}" && ! -w "${STATE_DIR}" ]]; then
    die "${STATE_DIR} is not writable. Fix ownership, then re-run without sudo:
  sudo chown -R \"$(whoami):$(whoami)\" \"${STATE_DIR}\""
  fi
  if [[ -d "${SYSTEMD_USER_DIR}" && ! -w "${SYSTEMD_USER_DIR}" ]]; then
    die "${SYSTEMD_USER_DIR} is not writable. Fix ownership, then re-run without sudo:
  sudo chown -R \"$(whoami):$(whoami)\" \"${SYSTEMD_USER_DIR}\""
  fi
}

is_wsl() {
  grep -qiE "(microsoft|wsl)" /proc/version 2>/dev/null
}

ensure_systemd_user() {
  if ! command -v systemctl >/dev/null 2>&1; then
    die "systemctl not found. Install systemd (or run on a distro with systemd --user)."
  fi

  if ! systemctl --user show-environment >/dev/null 2>&1; then
    if is_wsl; then
      die "systemd --user is not active in this WSL2 distro.
Enable systemd in /etc/wsl.conf:
  [boot]
  systemd=true
Then run: wsl --shutdown (from Windows PowerShell), reopen WSL, and retry."
    fi
    die "systemd --user is not available for this session. Log in normally (not a minimal shell) and retry."
  fi
}

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

  candidates+=(
    "$(command -v python3.13 2>/dev/null || true)"
    "$(command -v python3.12 2>/dev/null || true)"
    "$(command -v python3.11 2>/dev/null || true)"
    "$(command -v python3 2>/dev/null || true)"
    /usr/bin/python3
    /usr/local/bin/python3
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

install_python3() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "Running: sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip"
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
    return
  fi
  if command -v dnf >/dev/null 2>&1; then
    echo "Running: sudo dnf install -y python3 python3-pip"
    sudo dnf install -y python3 python3-pip
    return
  fi
  if command -v yum >/dev/null 2>&1; then
    echo "Running: sudo yum install -y python3 python3-pip"
    sudo yum install -y python3 python3-pip
    return
  fi
  if command -v pacman >/dev/null 2>&1; then
    echo "Running: sudo pacman -Sy --noconfirm python python-pip"
    sudo pacman -Sy --noconfirm python python-pip
    return
  fi
  if command -v zypper >/dev/null 2>&1; then
    echo "Running: sudo zypper install -y python311 python311-pip"
    sudo zypper install -y python311 python311-pip
    return
  fi
  die "Unsupported package manager. Install Python 3.11+ manually and rerun."
}

ensure_python3() {
  local py ver
  if py="$(resolve_python3)"; then
    ver="$("${py}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    echo "  OK  Python ${py} (${ver})"
    return 0
  fi

  echo "  ... no Python ${PY_MIN_MAJOR}.${PY_MIN_MINOR}+ found."
  ask_yes 1 "Install Python via your system package manager?" || \
    die "Install Python 3.11+ manually, or set PYTHON3_BIN, then rerun."

  install_python3

  if ! py="$(resolve_python3)"; then
    die "Still no suitable Python after installation."
  fi
  ver="$("${py}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
  echo "  OK  Python ${py} (${ver})"
}

python3_has_open_terminal_module() {
  local py="$1"
  "${py}" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('open_terminal') else 1)" 2>/dev/null
}

ensure_pipx() {
  if command -v pipx >/dev/null 2>&1; then
    return 0
  fi

  ask_yes 1 "pipx not found. Install pipx?" || return 1

  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y pipx
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y pipx
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y pipx
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm pipx
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y pipx
  else
    return 1
  fi
}

OT_MODE=""
OT_PATH=""

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

  if [[ -x "${HOME}/.local/bin/open-terminal" ]]; then
    OT_MODE="bin"
    OT_PATH="${HOME}/.local/bin/open-terminal"
    return 0
  fi

  py="$(resolve_python3)" || return 1
  if python3_has_open_terminal_module "${py}"; then
    OT_MODE="module"
    OT_PATH="${py}"
    return 0
  fi

  return 1
}

install_open_terminal_package() {
  local py
  py="$(resolve_python3)" || die "python3 not found while installing open-terminal."

  if ensure_pipx && command -v pipx >/dev/null 2>&1; then
    echo "Installing open-terminal via pipx..."
    pipx install --force open-terminal || true
    hash -r 2>/dev/null || true
    if resolve_open_terminal; then
      return 0
    fi
  fi

  ask_yes 1 "pipx path did not resolve open-terminal. Install via pip --user instead?" || \
    die "open-terminal installation aborted."

  "${py}" -m pip install --user --upgrade pip
  "${py}" -m pip install --user --upgrade open-terminal
  export PATH="${HOME}/.local/bin:${PATH}"
  hash -r 2>/dev/null || true
  resolve_open_terminal || die "open-terminal still not found after install."
}

smoke_test_open_terminal() {
  [[ "${SKIP_OT_SELF_CHECK:-0}" == "1" ]] && return 0
  if [[ "${OT_MODE}" == "bin" ]]; then
    "${OT_PATH}" run --help >/dev/null
  else
    "${OT_PATH}" -m open_terminal run --help >/dev/null
  fi
}

check_all_dependencies() {
  echo "Checking dependencies..."
  ensure_systemd_user
  ensure_python3

  if resolve_open_terminal; then
    echo "  OK  open-terminal (${OT_MODE} @ ${OT_PATH})"
  else
    echo "  ... open-terminal not found."
    ask_yes 1 "Install open-terminal now?" || \
      die "Install open-terminal manually and rerun."
    install_open_terminal_package
    echo "  OK  open-terminal (${OT_MODE} @ ${OT_PATH})"
  fi

  smoke_test_open_terminal
}

write_random_api_key() {
  ensure_writable
  umask 077
  python3 - <<'PY' > "${KEY_FILE}"
import secrets
print(secrets.token_urlsafe(48))
PY
  chmod 600 "${KEY_FILE}"
}

write_wrapper() {
  ensure_writable
  local cors_q
  cors_q="$(printf '%q' "${CORS_ALLOWED_ORIGINS}")"
  if [[ "${OT_MODE}" == "bin" ]]; then
    cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export OPEN_TERMINAL_API_KEY="\$(cat "\${HOME}/.config/flaiwheel/open-terminal-api-key")"
exec "${OT_PATH}" run --host "${HOST}" --port "${PORT}" --cors-allowed-origins ${cors_q}
EOF
  else
    cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export OPEN_TERMINAL_API_KEY="\$(cat "\${HOME}/.config/flaiwheel/open-terminal-api-key")"
exec "${OT_PATH}" -m open_terminal run --host "${HOST}" --port "${PORT}" --cors-allowed-origins ${cors_q}
EOF
  fi
  chmod 700 "${WRAPPER}"
}

write_service() {
  ensure_writable
  cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Flaiwheel Open Terminal local service
After=default.target

[Service]
Type=simple
ExecStart=${WRAPPER}
Restart=always
RestartSec=2
Environment=PATH=${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=${HOME}

[Install]
WantedBy=default.target
EOF
  chmod 644 "${SERVICE_FILE}"
}

daemon_reload_enable_start() {
  systemctl --user daemon-reload
  systemctl --user enable --now "${LABEL}.service"
}

stop_disable_service() {
  systemctl --user disable --now "${LABEL}.service" >/dev/null 2>&1 || true
  systemctl --user daemon-reload >/dev/null 2>&1 || true
}

print_hint() {
  local key
  key="$(cat "${KEY_FILE}")"
  echo ""
  echo "=== Open WebUI - Open Terminal ==="
  echo "URL:  http://localhost:${PORT}"
  echo "API key (Bearer):  ${key}"
  echo "Docs: http://localhost:${PORT}/docs"
  echo ""
  echo "Listening on ${HOST}:${PORT} (default HOST is 127.0.0.1)."
  echo "CORS allowlist: ${CORS_ALLOWED_ORIGINS}"
  if [[ "${CORS_ALLOWED_ORIGINS}" == "*" ]]; then
    echo "Note: for stricter CORS set OPEN_TERMINAL_CORS_ALLOWED_ORIGINS='https://your-openwebui.example' and rerun."
  fi
  echo ""
  echo "Service status:"
  echo "  systemctl --user status ${LABEL}.service"
  echo "Logs:"
  echo "  journalctl --user -u ${LABEL}.service -f"
}

install_fresh() {
  check_all_dependencies
  write_random_api_key
  write_wrapper
  write_service
  daemon_reload_enable_start
  print_hint
}

update_service() {
  check_all_dependencies
  if [[ ! -f "${KEY_FILE}" ]]; then
    echo "API key file missing; generating a new one."
    write_random_api_key
  fi
  write_wrapper
  write_service
  daemon_reload_enable_start
  print_hint
}

reset_api_key_and_restart() {
  check_all_dependencies
  write_random_api_key
  write_wrapper
  write_service
  daemon_reload_enable_start
  print_hint
}

disable_service() {
  stop_disable_service
  echo "Disabled ${LABEL}.service (files kept):"
  echo "  ${SERVICE_FILE}"
  echo "  ${WRAPPER}"
  echo "  ${KEY_FILE}"
}

menu_existing() {
  echo ""
  echo "Existing service found: ${SERVICE_FILE}"
  echo "Choose:"
  echo "  1) Update/reload service"
  echo "  2) Reset API key and restart service"
  echo "  3) Disable service (keep files)"
  echo "  4) Exit"
  local choice
  read -rp "Select [1-4]: " choice
  case "${choice}" in
    1) update_service ;;
    2) reset_api_key_and_restart ;;
    3) disable_service ;;
    4) exit 0 ;;
    *) die "Invalid choice." ;;
  esac
}

main() {
  refuse_root
  ensure_dirs
  ensure_writable
  if [[ -f "${SERVICE_FILE}" ]]; then
    menu_existing
  else
    install_fresh
  fi
}

main "$@"
