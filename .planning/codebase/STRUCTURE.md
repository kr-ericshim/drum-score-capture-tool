# Codebase Structure

**Analysis Date:** 2026-05-18

## Directory Layout

```text
score_capture_program/
├── backend/                    # FastAPI service, pipeline code, backend tests, backend build helpers
├── desktop/                    # Electron shell, preload bridge, active renderer-v2 UI, desktop tests
├── docs/                       # Release docs, reports, and historical planning/design artifacts
├── scripts/                    # Top-level setup helpers for local installs
├── .planning/codebase/         # Generated GSD codebase mapping documents
└── dist/                       # Ignored packaged desktop build outputs, generated locally or in CI
```

## Directory Purposes

**`backend/app/`:**
- Purpose: Backend application source.
- Contains: `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/job_store.py`, and the `backend/app/pipeline/` stage modules.
- Key files: `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/job_store.py`

**`backend/app/pipeline/`:**
- Purpose: Processing stages and runtime detection helpers.
- Contains: extraction, detection, rectification, stitching, upscaling, export, layout heuristics, FFmpeg/HAT runtime resolution.
- Key files: `backend/app/pipeline/extract.py`, `backend/app/pipeline/stitch.py`, `backend/app/pipeline/export.py`, `backend/app/pipeline/acceleration.py`

**`backend/tests/`:**
- Purpose: Backend verification for API contracts, source handling, persistence, and pipeline behavior.
- Contains: `unittest` test modules named `test_*.py`.
- Key files: `backend/tests/test_job_api_contract.py`, `backend/tests/test_job_store_persistence.py`, `backend/tests/test_stitch_regression.py`

**`backend/scripts/`:**
- Purpose: Backend setup and packaging helpers.
- Contains: runtime doctor scripts, HAT runtime setup, frozen-backend build scripts.
- Key files: `backend/scripts/doctor.py`, `backend/scripts/build_frozen_backend.py`, `backend/scripts/setup_hat_runtime.sh`

**`desktop/`:**
- Purpose: Desktop host application.
- Contains: Electron main/preload files, packaging config, build resources, tests, scripts, and the active `renderer-v2`.
- Key files: `desktop/main.js`, `desktop/preload.js`, `desktop/package.json`, `desktop/electron-builder.config.js`

**`desktop/renderer/`:**
- Purpose: Retired legacy renderer.
- Contains: Deleted legacy files in the current product path. Runtime entry and tests now keep `renderer-v2` as the only product renderer.
- Key files: none in the active product path.

**`desktop/renderer-v2/src/app/`:**
- Purpose: Runtime shell for the active workflow rewrite.
- Contains: app bootstrap, step gating, bridge access, session store, selectors, runtime safety, shared types.
- Key files: `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/app/bridge.js`, `desktop/renderer-v2/src/app/session/store.js`, `desktop/renderer-v2/src/app/session/selectors.js`

**`desktop/renderer-v2/src/features/`:**
- Purpose: Workflow-specific screens and controllers.
- Contains: feature folders for source selection, ROI, export, and review.
- Key files: `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/source/sourceController.js`, `desktop/renderer-v2/src/features/roi/RoiScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`

**`desktop/renderer-v2/src/ui/shell/`:**
- Purpose: Shared renderer-v2 layout chrome.
- Contains: shell frame, top bar, process rail, and context lane markup helpers.
- Key files: `desktop/renderer-v2/src/ui/shell/AppShell.js`, `desktop/renderer-v2/src/ui/shell/TopBar.js`, `desktop/renderer-v2/src/ui/shell/ProcessRail.js`

**`desktop/renderer-v2/src/lib/`:**
- Purpose: Renderer-v2 infrastructure utilities that are not feature-specific.
- Contains: HTTP client, i18n helpers, message formatting, path normalization helpers.
- Key files: `desktop/renderer-v2/src/lib/api.js`, `desktop/renderer-v2/src/lib/i18n.js`, `desktop/renderer-v2/src/lib/paths.js`

**`desktop/renderer-v2/src/tests/`:**
- Purpose: Renderer-v2 unit and flow tests.
- Contains: Node test runner suites for app flow, selectors, shell rendering, API helpers, and feature screens.
- Key files: `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`, `desktop/renderer-v2/src/tests/session-selectors.test.js`, `desktop/renderer-v2/src/tests/source-controller.test.js`

**`desktop/tests/`:**
- Purpose: Electron-shell and packaging tests outside renderer-v2.
- Contains: preload, renderer entry, workflow shell, auth, and packaged-release tests.
- Key files: `desktop/tests/preload-auth.test.mjs`, `desktop/tests/renderer-entry.test.cjs`, `desktop/tests/workflow-shell.test.mjs`

**`desktop/scripts/`:**
- Purpose: Packaging, validation, and structural checks for the desktop app.
- Contains: release builder wrapper, packaged-release validator, packaged smoke tests, renderer-v2 structural checks, locale/profile checks.
- Key files: `desktop/scripts/run-builder.js`, `desktop/scripts/validate-packaged-release.js`, `desktop/scripts/smoke-packaged-electron.js`, `desktop/scripts/smoke-packaged-runtime.js`, `desktop/scripts/check-renderer-v2.js`

**`docs/release/`:**
- Purpose: Release runbooks and release-specific checklists.
- Contains: shipping guidance and release notes.
- Key files: `docs/release/github-release-runbook.md`, `docs/release/final-production-checklist.md`

**`docs/reports/`:**
- Purpose: Audit or readiness writeups tied to concrete repository states.
- Contains: repository-specific production/readiness reports.
- Key files: `docs/reports/2026-03-09-github-production-readiness-report.md`

**`docs/superpowers/`:**
- Purpose: Planning and UI/design artifacts generated by the surrounding workflow.
- Contains: historical plans and specs for major UI and workflow efforts. Some older files reference the retired legacy renderer and should be treated as history, not current implementation guidance.
- Key files: `docs/superpowers/specs/2026-04-19-archive-library-design.md`

## Key File Locations

**Entry Points:**
- `backend/run.py`: Development backend launcher for Uvicorn.
- `backend/app/main.py`: FastAPI application definition and backend orchestration root.
- `desktop/main.js`: Electron main process entrypoint.
- `desktop/preload.js`: Preload bridge loaded into the renderer window.
- `desktop/renderer-v2/src/main.js`: Active renderer-v2 bootstrap.

**Configuration:**
- `backend/requirements.txt`: Runtime Python dependencies.
- `backend/requirements-build.txt`: Build-time Python dependencies for frozen backend packaging.
- `desktop/package.json`: Electron scripts, package metadata, and base electron-builder config.
- `desktop/electron-builder.config.js`: Packaging overrides and profile-aware filters.
- `desktop/renderer-v2/package.json`: Renderer-v2 local scripts.

**Core Logic:**
- `backend/app/job_store.py`: Job persistence and restart recovery.
- `backend/app/schemas.py`: Shared request/response contracts.
- `backend/app/pipeline/extract.py`: Source resolution, YouTube download, FFmpeg frame extraction.
- `backend/app/pipeline/stitch.py`: Dedupe and merge logic for scroll/page-turn workflows.
- `backend/app/pipeline/export.py`: Image/PDF export and page finalization.
- `desktop/renderer-v2/src/app/App.js`: Event orchestration and screen switching for the active UI.
- `desktop/renderer-v2/src/features/source/sourceController.js`: Source selection and YouTube prepare state transitions.

**Testing:**
- `backend/tests/`: Python backend tests.
- `desktop/tests/`: Electron shell and packaging tests.
- `desktop/renderer-v2/src/tests/`: Renderer-v2 feature and flow tests.

## Naming Conventions

**Files:**
- Python backend modules use snake_case filenames such as `backend/app/job_store.py` and `backend/app/pipeline/layout_profiles.py`.
- Renderer-v2 screen files use PascalCase for screen/shell renderers such as `desktop/renderer-v2/src/features/source/SourceScreen.js` and `desktop/renderer-v2/src/ui/shell/ProcessRail.js`.
- Renderer-v2 controllers, stores, selectors, and helpers use camelCase filenames such as `desktop/renderer-v2/src/features/source/sourceController.js` and `desktop/renderer-v2/src/app/session/runtimeSafety.js`.
- Test files use `test_*.py` under `backend/tests/` and `*.test.js` / `*.test.mjs` / `*.test.cjs` under `desktop/tests/` and `desktop/renderer-v2/src/tests/`.

**Directories:**
- Backend directories are functional and lowercase: `backend/app/`, `backend/app/pipeline/`, `backend/tests/`, `backend/scripts/`.
- Renderer-v2 directories are split by role: `src/app/` for state/runtime, `src/features/` for workflow slices, `src/ui/` for shared shell, `src/lib/` for infra helpers, `src/tests/` for tests.
- Feature directories are lowercase single-purpose folders such as `desktop/renderer-v2/src/features/source/` and `desktop/renderer-v2/src/features/review/`.

## Where to Add New Code

**New Feature:**
- Backend endpoint or request contract: update `backend/app/main.py` and `backend/app/schemas.py`.
- Backend processing stage or algorithm: add a new module under `backend/app/pipeline/` and wire it into `_run_job()` or the relevant preview helper in `backend/app/main.py`.
- Renderer-v2 workflow step or screen: add a feature folder or file under `desktop/renderer-v2/src/features/` and connect it from `desktop/renderer-v2/src/app/App.js`.
- Renderer-v2 step accessibility or derived workflow logic: update `desktop/renderer-v2/src/app/types.js`, `desktop/renderer-v2/src/app/routes.js`, and `desktop/renderer-v2/src/app/session/selectors.js`.
- Electron-facing privileged action: add the IPC handler in `desktop/main.js`, expose it in `desktop/preload.js`, then consume it from `desktop/renderer-v2/src/app/bridge.js`.
- Tests: mirror the subsystem. Use `backend/tests/` for backend changes, `desktop/tests/` for Electron/preload/entry changes, and `desktop/renderer-v2/src/tests/` for renderer-v2 logic or screen rendering.

**New Component/Module:**
- Shared renderer-v2 shell or layout UI: place it in `desktop/renderer-v2/src/ui/shell/`.
- Feature-specific renderer-v2 view/controller code: place it in the corresponding `desktop/renderer-v2/src/features/<feature>/` directory.
- Shared renderer-v2 browser helper: place it in `desktop/renderer-v2/src/lib/`.

**Utilities:**
- Shared backend runtime/probing helpers: place them in `backend/app/pipeline/` if they support processing stages, or in `backend/app/` only if they are API/job-store specific.
- Top-level developer or packaging utilities: place them in `backend/scripts/`, `desktop/scripts/`, or root `scripts/` depending on which runtime owns the command.

## Special Directories

**`backend/jobs/`:**
- Purpose: Default on-disk workspace for job artifacts, preview images, and cached YouTube downloads.
- Generated: Yes
- Committed: No

**`backend/runtime/`:**
- Purpose: Output directory for the optional PyInstaller-built backend runtime used by packaged desktop builds.
- Generated: Yes
- Committed: No

**`.tmp/pyinstaller-build/`:**
- Purpose: Temporary build work directory for the frozen backend build.
- Generated: Yes
- Committed: No

**`dist/`:**
- Purpose: Electron packaging output directory configured by `desktop/package.json` and `desktop/electron-builder.config.js`.
- Generated: Yes
- Committed: No

**`stitch_exports/`:**
- Purpose: External export artifact directory outside the per-job backend workspace.
- Generated: Yes
- Committed: No

**`.planning/codebase/`:**
- Purpose: Generated repository mapping documents consumed by later GSD planning/execution steps.
- Generated: Yes
- Committed: Yes

---

*Structure analysis: 2026-04-17*
