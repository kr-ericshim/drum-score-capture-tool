# Technology Stack

**Analysis Date:** 2026-04-17

## Languages

**Primary:**
- Python 3.11 target runtime - backend API and processing pipeline in `backend/run.py`, `backend/app/main.py`, and `backend/app/pipeline/`. GitHub Actions pins Python 3.11 in `.github/workflows/ci.yml` and `.github/workflows/release.yml`.
- JavaScript (Node.js + Electron) - desktop main process, preload bridge, legacy renderer, and renderer-v2 rewrite in `desktop/main.js`, `desktop/preload.js`, `desktop/renderer/`, and `desktop/renderer-v2/src/`.

**Secondary:**
- Bash - setup and optional runtime helpers in `backend/scripts/setup_hat_runtime.sh`, `backend/scripts/enable_hat_env.sh`, and top-level launch helpers such as `easy_setup_mac.command`.
- YAML and JSON - CI/CD, package metadata, and build config in `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `desktop/package.json`, `desktop/package-lock.json`, and generated release metadata validated by `desktop/scripts/validate-packaged-release.js`.

## Runtime

**Environment:**
- CPython + Uvicorn - `backend/run.py` launches `app.main:app` with `uvicorn`.
- Frozen Python runtime via PyInstaller - release builds can run `backend/runtime/drumsheet-backend/drumsheet-backend` or `backend/runtime/drumsheet-backend/drumsheet-backend.exe`, produced by `backend/scripts/build_frozen_backend.py`.
- Electron desktop runtime - `desktop/package.json` pins `electron` `^37.2.0`; the app boots from `desktop/main.js`.
- Node.js 20 in CI - `.github/workflows/ci.yml` and `.github/workflows/release.yml` pin `node-version: "20"`. No `.nvmrc` or other local Node version file is present.

**Package Manager:**
- Python packages are installed with `pip` from `backend/requirements.txt`, `backend/requirements-build.txt`, and optional `backend/requirements-hat.txt`.
- Python lockfile: missing.
- Node packages are installed with `npm` from `desktop/package.json`.
- Lockfile: present at `desktop/package-lock.json` (`lockfileVersion: 3`).

## Frameworks

**Core:**
- FastAPI `>=0.110.0` - local HTTP API and job orchestration in `backend/app/main.py`.
- Electron `^37.2.0` - desktop shell, backend process manager, IPC bridge, and native dialogs in `desktop/main.js` and `desktop/preload.js`.
- Vanilla browser JavaScript - both `desktop/renderer/app.js` and the ESM rewrite under `desktop/renderer-v2/src/` use direct DOM and `fetch`; no React, Vue, Svelte, or TypeScript framework is detected.

**Testing:**
- Python `unittest` - backend test suite in `backend/tests/`, invoked by `.github/workflows/release.yml` and the repo guidance in `README.md`.
- Node built-in test runner - desktop and renderer-v2 tests in `desktop/tests/` and `desktop/renderer-v2/src/tests/`, wired through scripts in `desktop/package.json`.

**Build/Dev:**
- Uvicorn `>=0.23.0` (`uvicorn[standard]`) - ASGI server dependency declared in `backend/requirements.txt`.
- Electron Builder `^26.1.0` - desktop packaging defined in `desktop/package.json` and customized by `desktop/electron-builder.config.js`.
- PyInstaller `>=6.0.0` - frozen backend packaging from `backend/requirements-build.txt` and `backend/scripts/build_frozen_backend.py`.

## Key Dependencies

**Critical:**
- `opencv-python-headless>=4.8.0` - image and video processing backbone across `backend/app/pipeline/extract.py`, `backend/app/pipeline/detect.py`, `backend/app/pipeline/stitch.py`, `backend/app/pipeline/roi_health.py`, `backend/app/pipeline/sheet_finalize.py`, and `backend/app/pipeline/export.py`.
- `numpy>=1.26.0` - array and numeric operations used throughout the OpenCV pipeline in `backend/app/pipeline/`.
- `Pillow>=10.0.0` - image conversion and PDF export in `backend/app/pipeline/export.py`.
- `pydantic>=2.5.0` - request and response schemas in `backend/app/schemas.py`.
- `yt-dlp>=2025.1.0` - YouTube source download and normalization in `backend/app/pipeline/extract.py`.

**Infrastructure:**
- `PyYAML>=6.0.0` - HAT option-template load/save in `backend/app/pipeline/upscale.py`.
- `ffmpeg-static^5.3.0` and `ffprobe-static^3.1.0` - build-time staging of bundled media binaries in `desktop/scripts/run-builder.js`.
- Optional HAT dependency set - `torch>=2.2.0`, `torchvision>=0.17.0`, `basicsr==1.3.4.9`, `facexlib>=0.3.0`, and `gfpgan>=1.3.8` from `backend/requirements-hat.txt` support the optional upscale path in `backend/app/pipeline/hat_runtime.py` and `backend/app/pipeline/upscale.py`.

## Configuration

**Environment:**
- Environment is shell/launcher driven. No checked-in `.env`, `.env.local`, or `.env.example` file was detected in the repository root during this scan.
- Base backend runtime variables are read in `backend/run.py` and `backend/app/main.py`: `DRUMSHEET_HOST`, `DRUMSHEET_PORT`, `DRUMSHEET_JOBS_DIR`, `DRUMSHEET_SESSION_TOKEN`.
- Binary/runtime resolution variables are read in `desktop/main.js` and `backend/app/pipeline/ffmpeg_runtime.py`: `DRUMSHEET_PYTHON_BIN`, `DRUMSHEET_NODE_BIN`, `DRUMSHEET_FFMPEG_BIN`, `DRUMSHEET_FFPROBE_BIN`.
- Renderer/build selection variables are read in `desktop/renderer-entry.js`, `desktop/scripts/run-builder.js`, and `desktop/electron-builder.config.js`: `DRUMSHEET_RENDERER`, `DRUMSHEET_DIST_PROFILE`, `DRUMSHEET_ENABLE_SIGNING`, `CSC_IDENTITY_AUTO_DISCOVERY`.
- Acceleration and optional upscale variables are read in `backend/app/pipeline/acceleration.py`, `backend/app/pipeline/upscale.py`, and `backend/app/pipeline/hat_runtime.py`: `DRUMSHEET_HWACCEL`, `DRUMSHEET_OPENCV_ACCEL`, `DRUMSHEET_UPSCALE_ENGINE`, `DRUMSHEET_UPSCALE_SHARPEN`, and the `DRUMSHEET_HAT_*` variables.

**Build:**
- Desktop packaging entrypoints live in `desktop/package.json` scripts such as `dist:release`, `dist:compact`, `dist:full`, and `dist:lean`.
- Electron Builder profile logic lives in `desktop/electron-builder.config.js` and `desktop/scripts/run-builder.js`.
- Frozen backend build inputs live in `backend/requirements-build.txt`, `backend/scripts/build_frozen_backend.py`, and `backend/pyinstaller_hooks/hook-app.pipeline.extract.py`.
- CI/CD runtime pinning and release automation live in `.github/workflows/ci.yml` and `.github/workflows/release.yml`.

## Platform Requirements

**Development:**
- Python 3.11 is the documented and CI-pinned baseline in `.github/workflows/ci.yml`, `.github/workflows/release.yml`, and the guided setup fallback message in `desktop/main.js`.
- `backend/scripts/setup_hat_runtime.sh` explicitly patches third-party code for Python 3.13 compatibility, so the optional HAT path is maintained with newer local Python interpreters as well.
- Node.js with `npm` is required for `desktop/package.json`; CI uses Node 20, but the repo does not pin a local developer version file.
- FFmpeg and FFprobe can be bundled into `backend/bin/` by `desktop/scripts/run-builder.js` or supplied externally through `DRUMSHEET_FFMPEG_BIN` and `DRUMSHEET_FFPROBE_BIN`.

**Production:**
- The shipping target is a desktop app, not a hosted web service. Release artifacts are built into `dist/`.
- macOS target: arm64 DMG from `desktop/electron-builder.config.js` and `.github/workflows/release.yml`.
- Windows target: x64 NSIS installer from `desktop/electron-builder.config.js` and `.github/workflows/release.yml`.
- Release profile `npm run dist:release` builds a standalone package with the Electron shell plus a frozen backend runtime, validated by `desktop/scripts/validate-packaged-release.js`.

---

*Stack analysis: 2026-04-17*
