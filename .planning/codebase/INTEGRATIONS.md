# External Integrations

**Analysis Date:** 2026-04-17

## APIs & External Services

**Local Service Boundary:**
- FastAPI backend over loopback HTTP - the Electron app starts a local service at `http://127.0.0.1:${DRUMSHEET_PORT}` and the renderers call it with `fetch`.
  - SDK/Client: browser `fetch` in `desktop/renderer-v2/src/lib/api.js` and `desktop/renderer/app.js`; Electron health checks in `desktop/main.js`
  - Auth: `DRUMSHEET_SESSION_TOKEN`, generated in `desktop/main.js`, exposed by `desktop/preload.js`, and enforced in `backend/app/main.py` via `X-DrumSheet-Token` or a `token` query parameter

**Media Source Acquisition:**
- YouTube download via `yt-dlp` - `backend/app/pipeline/extract.py` downloads and normalizes `youtube` sources before frame extraction.
  - SDK/Client: Python package `yt-dlp` from `backend/requirements.txt`
  - Auth: none detected
  - Runtime details: `backend/app/pipeline/extract.py` passes `ffmpeg_location` and can enable a Node JS runtime through `DRUMSHEET_NODE_BIN`

**Media Toolchain:**
- FFmpeg and FFprobe executables - used for video probing, frame extraction, preview generation, and hardware acceleration detection in `backend/app/pipeline/ffmpeg_runtime.py`, `backend/app/pipeline/extract.py`, and `backend/app/pipeline/acceleration.py`.
  - SDK/Client: resolved as OS executables; build-time staging from `ffmpeg-static` and `ffprobe-static` in `desktop/scripts/run-builder.js`
  - Auth: path override env vars `DRUMSHEET_FFMPEG_BIN` and `DRUMSHEET_FFPROBE_BIN`

**Optional Upscale Stack:**
- HAT and BasicSR third-party repositories - optional super-resolution runtime used by `backend/app/pipeline/hat_runtime.py` and `backend/app/pipeline/upscale.py`.
  - SDK/Client: manual setup via `backend/scripts/setup_hat_runtime.sh`; Python deps from `backend/requirements-hat.txt`
  - Auth: configuration through `DRUMSHEET_HAT_REPO`, `DRUMSHEET_HAT_WEIGHTS`, `DRUMSHEET_HAT_OPT_TEMPLATE`, `DRUMSHEET_HAT_PYTHON_BIN`, and related `DRUMSHEET_HAT_*` env vars
  - External endpoints: `backend/scripts/setup_hat_runtime.sh` clones `https://github.com/XPixelGroup/HAT.git` and `https://github.com/XPixelGroup/BasicSR.git`, then downloads pretrained weights with `gdown`

## Data Storage

**Databases:**
- Not detected.
  - Connection: Not applicable
  - Client: Not applicable

**File Storage:**
- Local filesystem only.
  - Job metadata and artifacts are persisted under `backend/jobs/` or the `DRUMSHEET_JOBS_DIR` override by `backend/app/job_store.py` and `backend/app/main.py`
  - Exported pages and PDFs are written into per-job workspaces by `backend/app/pipeline/export.py`
  - Packaged desktop artifacts are written to `dist/` by `desktop/electron-builder.config.js` and `desktop/scripts/run-builder.js`

**Caching:**
- On-disk preview/source cache under the jobs workspace.
  - Preview frames and prepared YouTube sources are staged below the jobs root from `backend/app/main.py`
  - No Redis, Memcached, or in-memory distributed cache client is present in `backend/app/` or `desktop/`

## Authentication & Identity

**Auth Provider:**
- Custom session-token boundary between Electron and the local FastAPI service.
  - Implementation: `desktop/main.js` creates a random token per desktop session, `desktop/preload.js` exposes it to the renderer, `desktop/renderer-v2/src/lib/api.js` attaches it to requests, and `backend/app/main.py` rejects non-`/health` traffic without a matching token

## Monitoring & Observability

**Error Tracking:**
- None detected. No Sentry, Bugsnag, Datadog, or similar SDK is imported in `backend/` or `desktop/`.

**Logs:**
- Desktop process logging uses stdout/stderr and UI-forwarded setup logs in `desktop/main.js`
- Backend runtime checks are exposed through `/runtime` in `backend/app/main.py` and the CLI helper `backend/scripts/doctor.py`
- Packaged release validation is done by `desktop/scripts/validate-packaged-release.js`

## CI/CD & Deployment

**Hosting:**
- GitHub Releases for packaged desktop binaries. The release workflow uploads `dist/*.exe`, `dist/*.dmg`, and `dist/*.blockmap` from `.github/workflows/release.yml`.

**CI Pipeline:**
- GitHub Actions.
  - Continuous validation: `.github/workflows/ci.yml`
  - Tagged release build and upload: `.github/workflows/release.yml`
  - Release upload action: `softprops/action-gh-release@v2` in `.github/workflows/release.yml`

## Environment Configuration

**Required env vars:**
- Core runtime: `DRUMSHEET_HOST`, `DRUMSHEET_PORT`, `DRUMSHEET_JOBS_DIR`, `DRUMSHEET_SESSION_TOKEN` from `backend/run.py` and `backend/app/main.py`
- Desktop launcher/runtime discovery: `DRUMSHEET_PYTHON_BIN`, `DRUMSHEET_NODE_BIN`, `DRUMSHEET_FFMPEG_BIN`, `DRUMSHEET_FFPROBE_BIN` from `desktop/main.js` and `backend/app/pipeline/ffmpeg_runtime.py`
- Acceleration and export behavior: `DRUMSHEET_HWACCEL`, `DRUMSHEET_OPENCV_ACCEL`, `DRUMSHEET_UPSCALE_ENGINE`, `DRUMSHEET_UPSCALE_SHARPEN` from `backend/app/pipeline/acceleration.py` and `backend/app/pipeline/upscale.py`
- Optional HAT runtime: `DRUMSHEET_HAT_ENABLE`, `DRUMSHEET_HAT_ALLOW_CPU`, `DRUMSHEET_HAT_TILE_SIZE`, `DRUMSHEET_HAT_TILE_PAD`, `DRUMSHEET_HAT_PYTHON_BIN`, `DRUMSHEET_HAT_REPO`, `DRUMSHEET_HAT_WEIGHTS`, `DRUMSHEET_HAT_OPT_TEMPLATE` from `backend/app/pipeline/hat_runtime.py`
- Packaging/signing: `DRUMSHEET_DIST_PROFILE`, `DRUMSHEET_ENABLE_SIGNING`, `CSC_IDENTITY_AUTO_DISCOVERY` from `desktop/scripts/run-builder.js` and `desktop/electron-builder.config.js`

**Secrets location:**
- No checked-in secret store or `.env` template was detected in this repository scan.
- Runtime secrets are expected to come from the parent shell, Electron launcher environment, or GitHub Actions environment in `.github/workflows/release.yml`
- Current release flow relies on GitHub’s built-in `GITHUB_TOKEN` in `.github/workflows/release.yml`

## Webhooks & Callbacks

**Incoming:**
- None. No webhook endpoint, external callback route, or public network listener is present beyond the local loopback FastAPI service in `backend/app/main.py`.

**Outgoing:**
- GitHub Release asset upload through `softprops/action-gh-release@v2` in `.github/workflows/release.yml`
- Manual HAT setup downloads from GitHub and model hosting through `backend/scripts/setup_hat_runtime.sh`
- No Stripe, Slack, email, OAuth callback, or third-party webhook client is detected in `backend/` or `desktop/`

---

*Integration audit: 2026-04-17*
