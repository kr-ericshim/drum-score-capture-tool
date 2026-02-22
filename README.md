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
# Optional (higher DBN precision on supported env)
python -m pip install madmom
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
# NVIDIA GPU 사용 권장: CUDA 빌드 torch/torchaudio 설치
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio
.\.venv\Scripts\python.exe -m pip install torchcodec

# Beat tracking
.\.venv\Scripts\python.exe -m pip install -r requirements-beat-this.txt
# Optional (DBN precision on supported env)
.\.venv\Scripts\python.exe -m pip install madmom
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
- FFmpeg/FFprobe resolution order:
  - `DRUMSHEET_FFMPEG_BIN` / `DRUMSHEET_FFPROBE_BIN`
  - bundled backend paths (`backend\\bin`, `backend\\ffmpeg\\bin`, `backend\\tools\\ffmpeg\\bin` 등)
  - system PATH (`ffmpeg.exe`, `ffprobe.exe`)
- Windows only hardening notes:
  - 윈도우에서만 파이프라인 시작 시 ffmpeg 경로를 엄격히 검사해 "명확한 누락 메시지"로 실패합니다.
  - macOS 동작 방식은 기존 fallback을 유지해 기존 동작에 영향이 없습니다.
- Always run `npm start` inside `score_capture_program\\desktop`.

운영 영향 변경사항 (최근)
- 2026-02-23: 오디오 분리 완료 후 `비트 분석`이 자동으로 시작됩니다.
- 2026-02-23: 비트 분석 기본 모델이 `final0`로 변경되었습니다.
- 2026-02-23: DBN 모드 요청 시 `madmom`이 없어도 작업이 실패하지 않도록 fallback(non-DBN) 처리됩니다.
- 2026-02-23: `Torchaudio + Demucs` 조합 사용 시 `torchcodec`가 없으면 저장 단계에서 실패할 수 있어, UVR 사용 시 `torchcodec` 설치를 필수 권장합니다.
- 2026-02-23: 유튜브 입력은 구간 선택/영역 선택/본 작업에서 공통 캐시(`backend/jobs/_preview_source/<hash>`)를 재사용해 중복 다운로드를 줄였습니다.
- 2026-02-23: Stepper는 입력 데이터가 채워져도 자동으로 다음 단계를 열지 않고, 사용자가 연 단계를 유지합니다.

실행/운영 체크리스트 (변경 시 반드시 확인)
- Python은 `3.11` 기준으로 운영하세요. (3.13 환경은 일부 패키지 호환 이슈가 보고됨)
- 오디오 분리 기능을 쓰려면 같은 venv(`backend/.venv`)에 `requirements-uvr.txt` + `torch/torchaudio/torchcodec`가 설치되어 있어야 합니다.
- DBN 정밀 모드를 반드시 쓰고 싶다면 `madmom` 설치 상태를 확인하세요. 미설치 시에도 앱은 fallback으로 진행됩니다.
- 의존성 설치/업데이트 후에는 `npm start`로 띄운 앱(백엔드 포함)을 완전히 재시작하세요.
- 배포/운영 전 `python scripts/doctor.py`로 런타임(GPU/FFmpeg/torch 디바이스) 점검을 먼저 수행하세요.

Quick environment check (recommended)
```bash
cd ../backend
source .venv/bin/activate
python scripts/doctor.py
```

Capture Behavior
- UI now uses `캡처 민감도` instead of direct FPS input.
- 악보 영역 선택은 `수동 지정(드래그)` 전용입니다. 자동 영역 탐지는 제거되었습니다.
- Stepper는 자동 넘김 없이 현재 열어둔 단계를 유지합니다.
- 입력 소스(파일/유튜브 URL)를 바꾸면 이전 ROI/프리뷰는 자동 초기화됩니다. 새 소스에서 `현재 프레임 불러오기`를 다시 눌러 영역을 지정하세요.
- `낮음`: fewer captures, strongest duplicate suppression.
- `보통`: balanced default.
- `높음`: more detailed capture, may produce more pages.
- `악보 업스케일 (GPU 전용)` 옵션을 켜면 최종 페이지를 2x/3x로 확대한 뒤 저장합니다.
- 업스케일은 CPU로 폴백하지 않고, GPU(OpenCV CUDA/OpenCL)가 없으면 작업을 중단합니다.
- `드럼 음원 분리 (UVR Demucs)` 옵션을 켜면 입력 영상에서 드럼 stem(wav/mp3)을 추출해 함께 저장합니다.
- 드럼 분리는 기본값이 `GPU 우선 + CPU 자동 전환`이며, `GPU 전용`을 켜면 GPU가 없을 때 중단됩니다.
- 오디오 탭에서 분리 완료 후 앱 안에서 바로 재생할 수 있고, stem별 볼륨/재생 속도 조절이 가능합니다.
- 오디오 탭의 `비트 분석 (Beat This!)`로 비트/다운비트를 감지하고 타임라인 마커로 확인할 수 있습니다.
- 최종 내보내기 단계에서 악보 이미지를 자동으로 정리합니다.
  - 내용 영역 자동 트림 + 배경 톤 정리
  - 다중 캡처를 세로로 자연스럽게 이어붙인 `sheet_complete.png` 생성(2장 이상일 때)
  - 긴 스크롤 악보 자동 페이지 분할
  - 출력 여백/프레임 정렬로 인쇄물에 가까운 형태로 저장
  - 기본 페이지 비율은 세로(A4 유사 비율)로 맞춰집니다.

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
- `beat_this` 실행 시 `torchcodec` 로딩/ffmpeg DLL 오류(Windows)로 실패:
  - 앱 실행 전에 `backend/bin` 또는 FFmpeg 폴더를 PATH에 넣거나,
  - 아래처럼 백엔드 Python에서 직접 진단해 주세요.
  - `cd backend` → `.\.venv\Scripts\python.exe scripts\doctor.py`
  - `backend/bin` 경로가 PATH/런타임 DLL 경로에 누락된 경우 `backend\\.venv` 기준으로 경로 재설정 후 앱 재시작.
- `ffmpeg ... not found` / `override path not found`:
  - 윈도우에서 ffmpeg 경로가 틀린 경우 새로 생긴 진단 메시지입니다.
  - 절대 경로 지정:
  - `set DRUMSHEET_FFMPEG_BIN=C:\\path\\to\\backend\\bin\\ffmpeg.exe`
  - `set DRUMSHEET_FFPROBE_BIN=C:\\path\\to\\backend\\bin\\ffprobe.exe`
- `GPU 전용, but CUDA/MPS is not available`:
  - Disable GPU-only option or confirm torch device availability (`python scripts/doctor.py`).
- `Audio separation requires GPU, but CUDA/MPS is not available` (Windows + NVIDIA, e.g. RTX 5080):
  - 원인: 앱이 다른 Python을 쓰거나, 현재 venv에 CPU용 torch가 설치된 경우가 대부분입니다.
  - 참고: 상단 런타임의 GPU 표시는 FFmpeg/OpenCV 기준입니다. 오디오 분리는 `오디오 분리 GPU(torch)` 상태를 별도로 봐야 합니다.
  - 특히 `backend/.venv`에 CPU 빌드 torch가 설치된 경우:
    - `torch.version.cuda`가 `None`으로 나옵니다.
    - 이 경우 GPU가 달려 있어도 오디오 분리는 CUDA를 못 씁니다.
  - `torch_gpu_reason` 해석:
    - `cuda_build_missing`: CUDA wheel이 아닌 torch(CPU 빌드) 설치
    - `cuda_no_visible_device`: torch가 CUDA 장치를 읽지 못함
    - `cuda_runtime_unavailable`: CUDA 빌드는 있으나 드라이버/런타임 비활성
    - `torch_missing`: torch 미설치/로드 실패
  - PowerShell에서 아래를 순서대로 실행하세요.
  - `cd C:\path\to\score_capture_program\backend`
  - `.\.venv\Scripts\python.exe -c "import sys,torch;print('py=',sys.executable);print('torch=',torch.__version__);print('torch_cuda=',torch.version.cuda);print('cuda=',torch.cuda.is_available());print('gpu_count=',torch.cuda.device_count())"`
  - 판정:
    - `torch_cuda=None` -> CPU 빌드 torch
    - `torch_cuda` 값이 있는데 `cuda=False` -> 드라이버/런타임/환경 이슈
  - `cuda=False`라면 GPU torch 재설치:
    - `.\.venv\Scripts\python.exe -m pip uninstall -y torch torchaudio torchvision`
    - `.\.venv\Scripts\python.exe -m pip install -U pip`
    - `.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio`
    - `.\.venv\Scripts\python.exe -m pip install torchcodec`
    - `.\.venv\Scripts\python.exe -m pip install -r requirements-uvr.txt`
    - `.\.venv\Scripts\python.exe scripts\doctor.py`
  - 추가 확인(권장):
    - `nvidia-smi`가 정상 출력되는지 확인
    - `scripts\doctor.py`에서 `audio_gpu_mode(torch)=cuda`, `audio_gpu_ready(torch)=True` 확인
  - 데스크톱 앱 실행 시 같은 Python 강제:
    - `cd ..\desktop`
    - `$env:DRUMSHEET_PYTHON_BIN = (Resolve-Path ..\backend\.venv\Scripts\python.exe).Path`
    - `npm start`
  - 참고: 에러 문구의 `MPS`는 macOS용 GPU 경로입니다. Windows에서는 `CUDA`만 확인하면 됩니다.
- `ffmpeg`가 상대 경로/잘못된 경로로 잡히는 경우(Windows):
  - 증상 예: `WinError 2`, `No such file or directory: 'ffmpeg'`, 혹은 상대 경로 호출 실패
  - 절대 경로를 강제로 지정해 실행:
  - `cd C:\path\to\score_capture_program\desktop`
  - `$env:DRUMSHEET_FFMPEG_BIN = (Resolve-Path ..\backend\bin\ffmpeg.exe).Path`
  - `$env:DRUMSHEET_FFPROBE_BIN = (Resolve-Path ..\backend\bin\ffprobe.exe).Path`
  - `npm start`
  - 시스템 PATH ffmpeg를 쓸 경우에는:
  - `where ffmpeg`
  - `where ffprobe`
  - 경로가 나오지 않으면 FFmpeg 설치 또는 PATH 설정이 필요합니다.
- 새 영상인데 이전 프레임이 ROI 화면에 보이는 경우:
  - 소스 변경 직후 이전 ROI는 자동으로 초기화됩니다.
  - 그래도 섞여 보이면 `현재 프레임 불러오기`를 다시 눌러 새 프레임을 가져오세요.

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
- Audio separation/beat tracking GPU는 PyTorch(CUDA/MPS) 기준이며 FFmpeg/OpenCV 감지와 별개입니다.
- On macOS (Apple Silicon), upscale can use FFmpeg `scale_vt` (VideoToolbox/Metal path) when available.
- `scale_vt` is enabled only after a runtime self-test passes (to avoid exposing a broken GPU path).
- Current default upscale is interpolation-based (not AI super-resolution), tuned for better text/sheet clarity.
- Optional environment overrides:
  - `DRUMSHEET_HWACCEL=auto|none|cuda|videotoolbox|d3d11va|dxva2|vaapi|qsv`
  - `DRUMSHEET_OPENCV_ACCEL=auto|cuda|opencl|cpu`
  - `DRUMSHEET_UPSCALE_ENGINE=auto|hat|opencv|ffmpeg`
  - `DRUMSHEET_UPSCALE_SHARPEN=1|0` (default `1`, toggles post-upscale unsharp enhancement)
  - `DRUMSHEET_FFMPEG_BIN=/absolute/path/to/ffmpeg(.exe)`
  - `DRUMSHEET_FFPROBE_BIN=/absolute/path/to/ffprobe(.exe)`

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
