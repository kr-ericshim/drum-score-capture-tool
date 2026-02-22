# Drum Sheet Capture Tool (MVP)

This project provides a local desktop workflow for capturing score sheets from video and exporting PNG/JPG/PDF outputs.

Architecture
- `desktop/`: Electron app (renderer + main process, plain HTML/CSS/JS for MVP UI)
- `backend/`: FastAPI processing engine (Python 3.11+, OpenCV + FFmpeg)

Quick Start

1. Install backend dependencies
```bash
cd score_capture_program/backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Optional: UVR-style drum stem separation
```bash
cd score_capture_program/backend
source .venv/bin/activate
python -m pip install -r requirements-uvr.txt
python -m pip install torch torchaudio torchcodec
```

Optional: Beat tracking (Beat This!)
```bash
cd score_capture_program/backend
source .venv/bin/activate
python -m pip install -r requirements-beat-this.txt
```

2. Install desktop dependencies
```bash
cd ../desktop
npm install
```

3. Run
```bash
npm start
```
Important: `npm start` must be run in `score_capture_program/desktop` where `package.json` exists.

Windows Quick Start (after `git pull`)

If you cloned/pulled this repo on Windows and want to run `npm start` right away, follow this exact PowerShell flow:

1. Move to backend and create venv with Python 3.11
```powershell
cd C:\path\to\score_capture_program\backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. (Optional) Install extra dependencies
```powershell
# UVR Demucs (audio separation)
.\.venv\Scripts\python.exe -m pip install -r requirements-uvr.txt
.\.venv\Scripts\python.exe -m pip install torch torchaudio torchcodec

# Beat tracking
.\.venv\Scripts\python.exe -m pip install -r requirements-beat-this.txt
```

3. Move to desktop and install Node packages
```powershell
cd ..\desktop
npm install
```

4. Run app
```powershell
npm start
```

5. If Python launcher/path is tricky on your machine, force backend python explicitly
```powershell
$env:DRUMSHEET_PYTHON_BIN = (Resolve-Path ..\backend\.venv\Scripts\python.exe).Path
npm start
```

Windows Notes
- Desktop launcher tries Python in this order:
  - `DRUMSHEET_PYTHON_BIN`
  - `backend\\.venv\\Scripts\\python.exe`
  - `py -3.11` → `py -3` → `py` → `python`
- If you see `python 9009`, Python is not discoverable by Windows shell. Install Python 3.11 (x64) and enable PATH.
- Always run `npm start` inside `score_capture_program\\desktop`.

Quick environment check (recommended)
```bash
cd ../backend
source .venv/bin/activate
python scripts/doctor.py
```

Capture Behavior
- UI now uses `캡처 민감도` instead of direct FPS input.
- `낮음`: fewer captures, strongest duplicate suppression.
- `보통`: balanced default.
- `높음`: more detailed capture, may produce more pages.
- `악보 업스케일 (GPU 전용)` 옵션을 켜면 최종 페이지를 2x/3x로 확대한 뒤 저장합니다.
- 업스케일은 CPU로 폴백하지 않고, GPU(OpenCV CUDA/OpenCL)가 없으면 작업을 중단합니다.
- `드럼 음원 분리 (UVR Demucs)` 옵션을 켜면 입력 영상에서 드럼 stem(wav/mp3)을 추출해 함께 저장합니다.
- 드럼 분리는 기본값이 `GPU 우선 + CPU 자동 전환`이며, `GPU 전용`을 켜면 GPU가 없을 때 중단됩니다.
- 오디오 탭에서 분리 완료 후 앱 안에서 바로 재생할 수 있고, stem별 볼륨/재생 속도 조절이 가능합니다.
- 오디오 탭의 `비트 분석 (Beat This!)`로 비트/다운비트를 감지하고 타임라인 마커로 확인할 수 있습니다.

Notes
- Electron app starts a local FastAPI server on `127.0.0.1:8000`.
- Backend outputs are written under `backend/jobs/<job_id>/`.
- Optional ffmpeg/yt-dlp availability is required for full features.

Troubleshooting
- `npm error enoent Could not read package.json`:
  - Run from `score_capture_program/desktop`, not project parent folder.
- `The local processing service stopped unexpectedly`:
  - Check backend deps first: `python scripts/doctor.py`
  - Then run backend alone for logs: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload`
- `demucs is not installed`:
  - `pip install -r backend/requirements-uvr.txt`
- `No module named demucs`:
  - Activate the same venv used by Electron (`backend/.venv`) and reinstall UVR deps.
- `TorchCodec is required`:
  - `pip install torchcodec` (inside `backend/.venv`)
- `GPU 전용, but CUDA/MPS is not available`:
  - Disable GPU-only option or confirm torch device availability (`python scripts/doctor.py`).

Packaging (MVP)
- Add `electron-builder` install (already in `desktop/package.json`).
- Build distributable:
```bash
cd desktop
npm run dist
```
- Output:
  - Windows: `.exe` installer from `../dist`
  - macOS: `.dmg` from `../dist`

Backend Runtime
- The desktop app currently expects a local Python runtime and will try:
  - `DRUMSHEET_PYTHON_BIN` (if set)
  - `<backend>/.venv/bin/python3` or `<backend>/.venv/Scripts/python.exe`
  - default `python3` (or `python` on Windows)

API contract (local)
- `POST /jobs` → `{ "job_id": "..." }`
- `GET /jobs/{job_id}` → job progress/state
- `GET /jobs/{job_id}/files` → generated image/PDF path list
- `GET /health` → `{ "status": "ok" }`
- `GET /runtime` → active acceleration modes and detected device names
- `POST /preview/source` → source video for mini player (local passthrough / youtube cached download)
- `POST /audio/separate` → drum stem separation only (UVR Demucs path)
- `POST /audio/beat-track` → beat/downbeat analysis for selected audio input (Beat This!)

GPU / Acceleration (auto with CPU fallback)
- This app tries GPU first and falls back to CPU automatically when unavailable.
- FFmpeg decode acceleration order is chosen by OS (e.g., `videotoolbox` on macOS, `cuda`/`d3d11va` on Windows).
- OpenCV acceleration uses `CUDA` if available, then `OpenCL`, otherwise `CPU`.
- On macOS (Apple Silicon), upscale can use FFmpeg `scale_vt` (VideoToolbox/Metal path) when available.
- `scale_vt` is enabled only after a runtime self-test passes (to avoid exposing a broken GPU path).
- Current default upscale is interpolation-based (not AI super-resolution), tuned for better text/sheet clarity.
- Optional environment overrides:
  - `DRUMSHEET_HWACCEL=auto|none|cuda|videotoolbox|d3d11va|dxva2|vaapi|qsv`
  - `DRUMSHEET_OPENCV_ACCEL=auto|cuda|opencl|cpu`
  - `DRUMSHEET_UPSCALE_ENGINE=auto|hat|opencv|ffmpeg`
  - `DRUMSHEET_UPSCALE_SHARPEN=1|0` (default `1`, toggles post-upscale unsharp enhancement)

HAT Upscale (optional)
- This project can call HAT (`XPixelGroup/HAT`) as an upscale engine.
- HAT is disabled by default. Enable it only after cloning HAT and preparing weights.
- Quick setup (recommended):
  - `bash backend/scripts/setup_hat_runtime.sh`
  - `source backend/scripts/enable_hat_env.sh`
- Typical setup:
  - `git clone https://github.com/XPixelGroup/HAT.git backend/third_party/HAT`
  - `git clone https://github.com/XPixelGroup/BasicSR.git backend/third_party/BasicSR`
  - `python -m pip install -e backend/third_party/BasicSR`
  - `python -m pip install -e backend/third_party/HAT`
  - Download model weights into `backend/third_party/HAT/experiments/pretrained_models/`
  - `source backend/scripts/enable_hat_env.sh`
- Required environment variables:
  - `DRUMSHEET_HAT_ENABLE=1`
  - `DRUMSHEET_HAT_REPO=/absolute/path/to/HAT`
  - `DRUMSHEET_HAT_WEIGHTS=/absolute/path/to/your_hat_model.pth`
- Optional HAT tuning:
  - `DRUMSHEET_HAT_OPT_TEMPLATE=options/test/HAT_SRx4_ImageNet-LR.yml` (path inside HAT repo unless absolute)
  - `DRUMSHEET_HAT_TILE_SIZE=512`
  - `DRUMSHEET_HAT_TILE_PAD=32`
  - `DRUMSHEET_HAT_ALLOW_CPU=1` (default `0`; allows CPU-only HAT fallback)
  - `DRUMSHEET_HAT_PYTHON_BIN=/path/to/python`
- Optional HAT dependencies list: `backend/requirements-hat.txt`
- Restart the backend process after changing HAT/upscale environment variables.

Non-goals for MVP (postponed)
- Full OCR/OMR pipeline
- Robust commercial-grade multi-page scroll sheet stitching
- Distribution signing/notarization
