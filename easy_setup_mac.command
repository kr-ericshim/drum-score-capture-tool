#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "${SCRIPT_DIR}/scripts/easy_setup_mac.sh"

echo
read -r -p "Press Enter to close..."
