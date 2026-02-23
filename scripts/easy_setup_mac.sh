#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
DESKTOP_DIR="${ROOT_DIR}/desktop"

print_header() {
  echo
  echo "=================================================="
  echo " Drum Sheet Capture - Easy Setup (macOS)"
  echo "=================================================="
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] Required command not found: $1"
    exit 1
  fi
}

find_python() {
  if [[ -n "${DRUMSHEET_PYTHON_BIN:-}" ]] && command -v "${DRUMSHEET_PYTHON_BIN}" >/dev/null 2>&1; then
    echo "${DRUMSHEET_PYTHON_BIN}"
    return
  fi

  if command -v python3.11 >/dev/null 2>&1; then
    echo "python3.11"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi

  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi

  echo ""
}

install_backend() {
  local py_bin="$1"
  local venv_py="${BACKEND_DIR}/.venv/bin/python"

  echo "[1/4] Python venv setup"
  "${py_bin}" -m venv "${BACKEND_DIR}/.venv"
  "${venv_py}" -m pip install --upgrade pip setuptools wheel

  echo "[2/4] Core backend dependencies"
  "${venv_py}" -m pip install -r "${BACKEND_DIR}/requirements.txt"

  echo "[3/4] Optional audio/beat dependencies"
  "${venv_py}" -m pip install -r "${BACKEND_DIR}/requirements-uvr.txt"
  "${venv_py}" -m pip install -r "${BACKEND_DIR}/requirements-beat-this.txt"
  "${venv_py}" -m pip install torch torchaudio torchcodec "soundfile>=0.12.0"

  echo "[4/4] Runtime check"
  "${venv_py}" "${BACKEND_DIR}/scripts/doctor.py" || true
}

install_desktop() {
  echo "[Desktop] npm install"
  (cd "${DESKTOP_DIR}" && npm install)
}

print_next_steps() {
  echo
  echo "Setup completed."
  echo "Run app:"
  echo "  1) Double click: run_app_mac.command"
  echo "  2) Or terminal: cd desktop && npm start"
}

main() {
  print_header
  require_cmd npm

  local py_bin
  py_bin="$(find_python)"
  if [[ -z "${py_bin}" ]]; then
    echo "[ERROR] Python is not installed."
    echo "Install Python 3.11 and run this script again."
    exit 1
  fi

  echo "Using python: ${py_bin}"
  install_backend "${py_bin}"
  install_desktop
  print_next_steps
}

main "$@"
