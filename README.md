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

2. Install desktop dependencies
```bash
cd ../desktop
npm install
```

3. Run
```bash
npm start
```

Capture Behavior
- UI now uses `캡처 민감도` instead of direct FPS input.
- `낮음`: fewer captures, strongest duplicate suppression.
- `보통`: balanced default.
- `높음`: more detailed capture, may produce more pages.
- `악보 업스케일 (GPU 전용)` 옵션을 켜면 최종 페이지를 2x/3x로 확대한 뒤 저장합니다.
- 업스케일은 CPU로 폴백하지 않고, GPU(OpenCV CUDA/OpenCL)가 없으면 작업을 중단합니다.

Notes
- Electron app starts a local FastAPI server on `127.0.0.1:8000`.
- Backend outputs are written under `backend/jobs/<job_id>/`.
- Optional ffmpeg/yt-dlp availability is required for full features.

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

GPU / Acceleration (auto with CPU fallback)
- This app tries GPU first and falls back to CPU automatically when unavailable.
- FFmpeg decode acceleration order is chosen by OS (e.g., `videotoolbox` on macOS, `cuda`/`d3d11va` on Windows).
- OpenCV acceleration uses `CUDA` if available, then `OpenCL`, otherwise `CPU`.
- Optional environment overrides:
  - `DRUMSHEET_HWACCEL=auto|none|cuda|videotoolbox|d3d11va|dxva2|vaapi|qsv`
  - `DRUMSHEET_OPENCV_ACCEL=auto|cuda|opencl|cpu`

Non-goals for MVP (postponed)
- Full OCR/OMR pipeline
- Robust commercial-grade multi-page scroll sheet stitching
- Distribution signing/notarization
