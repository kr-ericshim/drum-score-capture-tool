#!/usr/bin/env bash
set -euo pipefail

# One-shot setup for HAT on this project (tested on Python 3.13).
# It clones third-party repos, applies compatibility patches, installs deps,
# and downloads a pretrained weight.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
THIRD_PARTY_DIR="${BACKEND_DIR}/third_party"
HAT_DIR="${THIRD_PARTY_DIR}/HAT"
BASICSR_DIR="${THIRD_PARTY_DIR}/BasicSR"
VENV_PY="${BACKEND_DIR}/.venv/bin/python"
VENV_PIP="${BACKEND_DIR}/.venv/bin/pip"
VENV_GDOWN="${BACKEND_DIR}/.venv/bin/gdown"

if [[ ! -x "${VENV_PIP}" ]]; then
  echo "backend/.venv is missing. Create venv and install backend requirements first."
  exit 1
fi

mkdir -p "${THIRD_PARTY_DIR}"

if [[ ! -d "${HAT_DIR}" ]]; then
  git clone https://github.com/XPixelGroup/HAT.git "${HAT_DIR}"
fi

if [[ ! -d "${BASICSR_DIR}" ]]; then
  git clone https://github.com/XPixelGroup/BasicSR.git "${BASICSR_DIR}"
fi

"${VENV_PY}" - <<'PY'
from pathlib import Path

root = Path("backend/third_party")
hat_setup = root / "HAT/setup.py"
hat_reqs = root / "HAT/requirements.txt"
basicsr_setup = root / "BasicSR/setup.py"
basicsr_base = root / "BasicSR/basicsr/models/base_model.py"
basicsr_matlab = root / "BasicSR/basicsr/utils/matlab_functions.py"


def patch_text(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


# Python 3.13 compatibility for setup.py version extraction.
patch_text(
    hat_setup,
    "def get_version():\n    with open(version_file, 'r') as f:\n        exec(compile(f.read(), version_file, 'exec'))\n    return locals()['__version__']\n",
    "def get_version():\n    # Python 3.13 changed locals() behavior in function scope; execute into an\n    # explicit namespace so __version__ is reliably captured.\n    namespace = {}\n    with open(version_file, 'r') as f:\n        exec(compile(f.read(), version_file, 'exec'), namespace)\n    return namespace['__version__']\n",
)
patch_text(
    basicsr_setup,
    "def get_version():\n    with open(version_file, 'r') as f:\n        exec(compile(f.read(), version_file, 'exec'))\n    return locals()['__version__']\n",
    "def get_version():\n    # Python 3.13 changed locals() behavior in function scope; execute into an\n    # explicit namespace so __version__ is reliably captured.\n    namespace = {}\n    with open(version_file, 'r') as f:\n        exec(compile(f.read(), version_file, 'exec'), namespace)\n    return namespace['__version__']\n",
)

# HAT pin is too strict for current py3.13 flow; use installed BasicSR.
patch_text(
    hat_reqs,
    "basicsr==1.3.4.9\n",
    "basicsr>=1.4.2\n",
)

# Allow forcing MPS device via opt["device"] in BasicSR base model.
patch_text(
    basicsr_base,
    "        self.opt = opt\n        self.device = torch.device('cuda' if opt['num_gpu'] != 0 else 'cpu')\n        self.is_train = opt['is_train']\n",
    "        self.opt = opt\n        requested_device = str(opt.get('device', '')).strip().lower()\n        if requested_device in {'cpu', 'cuda', 'mps'}:\n            self.device = torch.device(requested_device)\n        else:\n            self.device = torch.device('cuda' if opt['num_gpu'] != 0 else 'cpu')\n        self.is_train = opt['is_train']\n",
)

# Old HAT modules import rgb2ycbcr from matlab_functions; re-export alias.
matlab_text = basicsr_matlab.read_text(encoding="utf-8")
if "from basicsr.utils.color_util import rgb2ycbcr as _rgb2ycbcr" not in matlab_text:
    matlab_text = matlab_text.replace(
        "import torch\n",
        "import torch\nfrom basicsr.utils.color_util import rgb2ycbcr as _rgb2ycbcr\n",
        1,
    )
if "def rgb2ycbcr(img, y_only=False):" not in matlab_text:
    matlab_text += "\n\ndef rgb2ycbcr(img, y_only=False):\n    \"\"\"Backward-compatible alias expected by older HAT data modules.\"\"\"\n    return _rgb2ycbcr(img, y_only=y_only)\n"
basicsr_matlab.write_text(matlab_text, encoding="utf-8")
PY

"${VENV_PIP}" install torchvision gdown
"${VENV_PIP}" install -e "${BASICSR_DIR}"
"${VENV_PIP}" install -e "${HAT_DIR}"

mkdir -p "${HAT_DIR}/experiments/pretrained_models"
WEIGHT_PATH="${HAT_DIR}/experiments/pretrained_models/HAT-L_SRx4_ImageNet-pretrain.pth"
if [[ ! -s "${WEIGHT_PATH}" ]]; then
  "${VENV_GDOWN}" --id 1uefIctjoNE3Tg6GTzelesTTshVogQdUf -O "${WEIGHT_PATH}"
fi

echo "HAT runtime setup complete."
echo "Next: source backend/scripts/enable_hat_env.sh"
