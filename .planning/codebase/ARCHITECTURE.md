# Architecture

**Analysis Date:** 2026-04-17

## Pattern Overview

**Overall:** Local split-process desktop application with an Electron shell, a browser-based renderer, and a co-packaged FastAPI service that executes a file-backed processing pipeline.

**Key Characteristics:**
- `desktop/main.js` is the runtime supervisor. It creates the window, chooses the renderer via `desktop/renderer-entry.js`, launches the backend, and exposes OS capabilities through IPC.
- `backend/app/main.py` is both the HTTP API layer and the orchestration layer. There are no FastAPI router submodules; route handlers and background job runners live in the same file.
- `backend/app/pipeline/*.py` modules are processing stages, not API handlers. They transform files in a per-job workspace under `DRUMSHEET_JOBS_DIR` (`backend/jobs` by default).
- `desktop/renderer-v2/src/app/App.js` implements a unidirectional UI flow around a single in-memory session store in `desktop/renderer-v2/src/app/session/store.js`.
- `desktop/renderer-entry.js` resolves only `desktop/renderer-v2/index.html`; the legacy renderer has been retired from the product path.

## Layers

**Electron Main Process:**
- Purpose: Own the desktop runtime, backend lifecycle, packaging/runtime detection, and privileged OS actions.
- Location: `desktop/main.js`, `desktop/renderer-entry.js`
- Contains: `BrowserWindow` creation, backend spawn/stop logic, guided setup, file picker, clipboard access, path opening, backend health polling.
- Depends on: Electron APIs, Node child processes, the backend launcher in `backend/run.py` or `backend/runtime/drumsheet-backend/`.
- Used by: `desktop/preload.js`, the active renderer loaded into the window.

**Preload Bridge:**
- Purpose: Narrow the renderer's access to privileged capabilities and inject backend connection data.
- Location: `desktop/preload.js`
- Contains: `contextBridge.exposeInMainWorld("drumSheetAPI", ...)`, backend state subscriptions, session token exposure, API base exposure.
- Depends on: `ipcRenderer`, synchronous IPC channels `get-app-version` and `get-session-token`, async IPC handlers registered in `desktop/main.js`.
- Used by: `desktop/renderer-v2/src/app/bridge.js` and `desktop/renderer-v2/src/lib/api.js`.

**Renderer V2 Application:**
- Purpose: Drive the source -> ROI -> export -> review workflow in the browser context.
- Location: `desktop/renderer-v2/src/main.js`, `desktop/renderer-v2/src/app/`, `desktop/renderer-v2/src/features/`, `desktop/renderer-v2/src/ui/shell/`, `desktop/renderer-v2/src/lib/`
- Contains: session store, selectors, runtime guards, action handlers, feature screens, shell composition, fetch-based API client.
- Depends on: `window.drumSheetAPI`, backend HTTP endpoints in `backend/app/main.py`, DOM APIs, local feature modules.
- Used by: `desktop/renderer-v2/index.html`.

**Backend API and Job Orchestration:**
- Purpose: Validate requests, guard access, persist jobs, and run long-lived processing work outside the request thread.
- Location: `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/job_store.py`
- Contains: FastAPI app creation, middleware, request/response schemas, `Job` and `SourcePrepareJob` persistence, background job submission, artifact path guards.
- Depends on: FastAPI, Pydantic, `ThreadPoolExecutor`, processing stages in `backend/app/pipeline/`.
- Used by: renderer-v2 via HTTP and Electron startup health checks in `desktop/main.js`.

**Processing Pipeline:**
- Purpose: Convert a local video or downloaded YouTube source into captured pages and exported files.
- Location: `backend/app/pipeline/extract.py`, `backend/app/pipeline/detect.py`, `backend/app/pipeline/rectify.py`, `backend/app/pipeline/stitch.py`, `backend/app/pipeline/upscale.py`, `backend/app/pipeline/export.py`, plus support modules under `backend/app/pipeline/`
- Contains: source resolution/download, FFmpeg extraction, ROI-based detection, perspective rectification, temporal dedupe/stitching, optional GPU upscaling, PDF/image export, layout heuristics, runtime capability detection.
- Depends on: OpenCV, FFmpeg/ffprobe discovery from `backend/app/pipeline/ffmpeg_runtime.py`, optional HAT runtime in `backend/app/pipeline/hat_runtime.py`.
- Used by: `_run_job` and `_run_source_prepare_job` in `backend/app/main.py`.

**Artifact and Packaging Layer:**
- Purpose: Produce distributable desktop builds and optional frozen backend runtime.
- Location: `desktop/scripts/run-builder.js`, `desktop/electron-builder.config.js`, `backend/scripts/build_frozen_backend.py`
- Contains: packaging profile selection, runtime FFmpeg staging, optional PyInstaller backend build, electron-builder configuration.
- Depends on: `desktop/package.json`, `backend/requirements-build.txt`, PyInstaller, electron-builder.
- Used by: `npm run pack*` and `npm run dist*` commands in `desktop/package.json`.

## Data Flow

**Application Startup:**

1. `desktop/main.js` creates the `BrowserWindow`, resolves the renderer HTML with `resolveRendererIndexPath()` from `desktop/renderer-entry.js`, and loads `desktop/renderer-v2/index.html`.
2. The same file launches the backend either by spawning `backend/run.py` with Python in development or a bundled executable under `backend/runtime/drumsheet-backend/` when packaged.
3. `desktop/main.js` polls `GET /health` on the FastAPI app in `backend/app/main.py` until ready, then emits backend state through IPC.
4. `desktop/preload.js` exposes `apiBase`, `apiToken`, and the small IPC bridge to the renderer through `window.drumSheetAPI`.

**Local File Capture Flow:**

1. `desktop/renderer-v2/src/features/source/sourceController.js` receives a file path from `bridge.selectVideoFile()` in `desktop/renderer-v2/src/app/bridge.js` and reads browser-side video metadata.
2. `desktop/renderer-v2/src/app/App.js` stores source metadata in the session store and moves the UI to the ROI step.
3. `desktop/renderer-v2/src/lib/api.js` calls `POST /preview/frame` so `backend/app/main.py` can extract a preview image through `extract_preview_frame()` in `backend/app/pipeline/extract.py`.
4. After ROI confirmation, `desktop/renderer-v2/src/app/App.js` builds a job payload and sends `POST /jobs`.
5. `backend/app/main.py` creates a `Job`, persists `job.json` through `backend/app/job_store.py`, and submits `_run_job()` on a background executor.
6. `_run_job()` executes the stage chain `extract_frames()` -> `detect_sheet_regions()` -> `rectify_frames()` -> `select_review_candidates()` / `stitch_pages()` -> `upscale_frames()` -> `export_frames()`.
7. The renderer polls `GET /jobs/{job_id}` via `getJob()` in `desktop/renderer-v2/src/lib/api.js`, converts job results into review pages with `deriveCapturePages()` in `desktop/renderer-v2/src/app/session/selectors.js`, and advances to review.

**YouTube Source Preparation Flow:**

1. `desktop/renderer-v2/src/features/source/SourceScreen.js` captures the YouTube URL and `desktop/renderer-v2/src/app/App.js` starts a prepare request through `createPreviewSourceJob()`.
2. `backend/app/main.py` creates a `SourcePrepareJob` in `SourcePrepareStore` and runs `_run_source_prepare_job()` on a dedicated executor.
3. `_run_source_prepare_job()` calls `_get_or_prepare_cached_youtube_video()`, which reuses or refreshes a cached download under `backend/jobs/_preview_source/<strategy>/<cache-key>/`.
4. Progress snapshots are written to `job.json` through `backend/app/job_store.py` and polled by `getPreviewSourceJob()` in `desktop/renderer-v2/src/lib/api.js`.
5. `desktop/renderer-v2/src/features/source/sourceController.js` turns the completed prepared video into the active local source and resets downstream UI state.

**Review Export Flow:**

1. The renderer keeps or excludes capture candidates in `desktop/renderer-v2/src/features/review/ReviewScreen.js`.
2. `desktop/renderer-v2/src/lib/api.js` sends `POST /jobs/{job_id}/review-export` with `keep_captures`.
3. `backend/app/main.py` resolves selections inside the current job directory, optionally restitches the chosen captures, exports them into a staged `export/` workspace, and atomically swaps the staged output into place.
4. The refreshed job result replaces the review list in the renderer.

**State Management:**
- Frontend state is in-memory only and centered in `desktop/renderer-v2/src/app/session/store.js`.
- Derived UI state lives in pure selector functions in `desktop/renderer-v2/src/app/session/selectors.js`.
- Async race protection is handled by versioned runtime guards in `desktop/renderer-v2/src/app/session/runtimeSafety.js`.
- Backend job state is persisted on disk through `backend/app/job_store.py`, allowing restart recovery and artifact discovery from each job directory.

## Key Abstractions

**Job / SourcePrepareJob:**
- Purpose: Represent long-running backend work and persist status independently of request lifetimes.
- Examples: `backend/app/job_store.py`
- Pattern: Dataclass + JSON persistence to `<artifact_dir>/job.json`, exposed to clients through `to_public_dict()`.

**Pydantic Workflow Contract:**
- Purpose: Define the canonical API payloads and stage options for the processing pipeline.
- Examples: `backend/app/schemas.py`
- Pattern: Nested request models (`JobCreate`, `JobOptions`, `ExtractOptions`, `StitchOptions`, `ExportOptions`) with validators for ROI shape, time windows, and review export semantics.

**File-Backed Job Workspace:**
- Purpose: Keep every processing run self-contained and inspectable.
- Examples: default root `backend/jobs/`, per-job directories referenced by `artifact_dir` in `backend/app/job_store.py`
- Pattern: Every major stage writes named subdirectories such as `frames/`, `detect/`, `rectified/`, `stitched/`, `upscaled/`, and `export/`.

**Renderer Session Model:**
- Purpose: Keep the active workflow deterministic and renderable from one tree.
- Examples: `desktop/renderer-v2/src/app/session/selectors.js`, `desktop/renderer-v2/src/app/types.js`, `desktop/renderer-v2/src/app/session/store.js`
- Pattern: One store object with `source`, `roi`, `exportConfig`, `review`, and `ui` slices; selectors derive step accessibility and summaries instead of spreading logic across components.

**Feature Screen + Shell Composition:**
- Purpose: Separate workflow-specific markup from the common application frame.
- Examples: `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/roi/RoiScreen.js`, `desktop/renderer-v2/src/features/export/ExportScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`, `desktop/renderer-v2/src/ui/shell/AppShell.js`
- Pattern: Screen modules return HTML strings, while `desktop/renderer-v2/src/app/App.js` mounts the shell once and swaps stage markup based on `ui.activeStep`.

**Runtime Capability Detection:**
- Purpose: Choose extraction/upscaling behavior from the actual local machine.
- Examples: `backend/app/pipeline/acceleration.py`, `backend/app/pipeline/ffmpeg_runtime.py`, `backend/app/pipeline/hat_runtime.py`
- Pattern: Probe local FFmpeg/OpenCV/HAT availability once, cache the result, and surface a normalized capability payload to both jobs and `/runtime`.

## Entry Points

**Backend Server:**
- Location: `backend/run.py`
- Triggers: Development startup and PyInstaller packaging target.
- Responsibilities: Read host/port env vars and boot Uvicorn with `backend/app/main.py`.

**FastAPI Application:**
- Location: `backend/app/main.py`
- Triggers: Imported by `backend/run.py` or the frozen backend executable.
- Responsibilities: Define routes, enforce the session token middleware, own job stores/executors, and orchestrate the pipeline.

**Electron Desktop Shell:**
- Location: `desktop/main.js`
- Triggers: `electron .` from `desktop/package.json` or the packaged app binary.
- Responsibilities: Start the backend, create the window, register IPC handlers, and manage guided setup and shutdown.

**Renderer V2 Bootstrap:**
- Location: `desktop/renderer-v2/src/main.js`
- Triggers: `<script type="module" src="./src/main.js">` in `desktop/renderer-v2/index.html`
- Responsibilities: Create the app and wire accessibility affordances such as the skip link focus behavior.

**Release Builders:**
- Location: `desktop/scripts/run-builder.js`, `backend/scripts/build_frozen_backend.py`
- Triggers: `npm run pack*`, `npm run dist*`
- Responsibilities: Stage runtime binaries, optionally freeze the backend, run electron-builder, and validate packaged output.

## Error Handling

**Strategy:** Fail fast on invalid input at the API boundary, convert background failures into persisted job state, and let the renderer recover from stale async work through version guards instead of implicit cancellation.

**Patterns:**
- Route handlers in `backend/app/main.py` raise `HTTPException` for user-correctable errors such as bad ROI, missing jobs, invalid selection sets, and unauthorized artifact paths.
- Background workers `_run_job()` and `_run_source_prepare_job()` catch broad exceptions, log the failure, and store `ERROR` state plus an `error_code` in `backend/app/job_store.py`.
- `backend/app/job_store.py` recovers interrupted `queued` or `running` jobs as `ERROR` on restart and preserves corrupt metadata as `job.corrupt.json`.
- `desktop/renderer-v2/src/app/App.js` catches async errors per action and writes them into `source.error`, `roi.error`, `exportConfig.error`, or `review.error`.
- `desktop/renderer-v2/src/app/session/runtimeSafety.js` prevents stale preview, export, and YouTube-prepare responses from mutating the store after the user has changed source or frame selection.
- `desktop/main.js` tracks backend startup failure separately from renderer errors and surfaces unexpected process exits through backend state events and desktop dialogs.

## Cross-Cutting Concerns

**Logging:** Backend job logs are accumulated in `backend/app/job_store.py` and emitted by pipeline stages through logger callbacks. Electron setup/back-end lifecycle logs are emitted from `desktop/main.js`. Renderer-v2 shows user-facing notices via `desktop/renderer-v2/src/lib/messages.js` and inline state fields.

**Validation:** Schema-level validation lives in `backend/app/schemas.py`. File containment and artifact safety checks live in helper functions inside `backend/app/main.py`. Frontend guards such as `isRectValid()` and `canRunExport()` in `desktop/renderer-v2/src/app/session/` block impossible actions before a request is sent.

**Authentication:** The application uses a session token generated in `desktop/main.js`, exposed through `desktop/preload.js`, and attached by `desktop/renderer-v2/src/lib/api.js` as `X-DrumSheet-Token`. `backend/app/main.py` enforces it for every path except `/health` and rejects query-string tokens on protected routes.

---

*Architecture analysis: 2026-04-17*
