#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   source backend/scripts/enable_hat_env.sh
#
# This script enables HAT upscale with the bundled third_party checkout.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HAT_REPO="${BACKEND_DIR}/third_party/HAT"
HAT_WEIGHTS="${HAT_REPO}/experiments/pretrained_models/HAT-L_SRx4_ImageNet-pretrain.pth"

export DRUMSHEET_HAT_ENABLE=1
export DRUMSHEET_UPSCALE_ENGINE=hat
export DRUMSHEET_HAT_REPO="${HAT_REPO}"
export DRUMSHEET_HAT_WEIGHTS="${HAT_WEIGHTS}"
export DRUMSHEET_HAT_OPT_TEMPLATE="options/test/HAT-L_SRx4_ImageNet-pretrain.yml"

# Keep default GPU-only behavior if CUDA is available.
# On CPU-only environments (like many Apple setups in this project), allow HAT CPU fallback.
export DRUMSHEET_HAT_ALLOW_CPU=1

echo "HAT env enabled:"
echo "  DRUMSHEET_HAT_REPO=${DRUMSHEET_HAT_REPO}"
echo "  DRUMSHEET_HAT_WEIGHTS=${DRUMSHEET_HAT_WEIGHTS}"
