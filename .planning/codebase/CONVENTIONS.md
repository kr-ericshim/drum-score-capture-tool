# Coding Conventions

**Analysis Date:** 2026-04-17

## Naming Patterns

**Files:**
- Python backend modules use `snake_case` filenames. Follow the patterns in `backend/app/job_store.py`, `backend/app/schemas.py`, and `backend/app/pipeline/sheet_finalize.py`.
- Backend test files use `test_<feature>.py` in `backend/tests/`, for example `backend/tests/test_review_export.py` and `backend/tests/test_source_prepare_jobs.py`.
- Renderer-v2 screen and shell view files use `PascalCase` filenames. Add new screens in the style of `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`, and `desktop/renderer-v2/src/ui/shell/TopBar.js`.
- Renderer-v2 controllers, state modules, helpers, and library modules use `camelCase` filenames. Follow `desktop/renderer-v2/src/features/source/sourceController.js`, `desktop/renderer-v2/src/app/session/runtimeSafety.js`, and `desktop/renderer-v2/src/lib/api.js`.
- Legacy renderer modules also use `camelCase` filenames under `desktop/renderer/modules/`, for example `desktop/renderer/modules/job-api.js` and `desktop/renderer/modules/video-range-picker.js`.
- Desktop Node tests use `*.test.mjs` or `*.test.cjs` in `desktop/tests/`. Renderer-v2 tests use `*.test.js` in `desktop/renderer-v2/src/tests/`.

**Functions:**
- Python functions are `snake_case`. Internal helpers use a leading underscore, for example `_normalize_source_inputs` in `backend/app/main.py`, `_download_youtube` in `backend/app/pipeline/extract.py`, and `_clear_previous_review_outputs` in `backend/app/pipeline/export.py`.
- Renderer-v2 functions are `camelCase`. Constructor-style factories use `create...`, such as `createApp` in `desktop/renderer-v2/src/app/App.js`, `createStore` in `desktop/renderer-v2/src/app/session/store.js`, and `createSourceController` in `desktop/renderer-v2/src/features/source/sourceController.js`.
- Renderer-v2 rendering modules commonly expose a `build...Model` helper plus a `render...` function. Use the pattern from `desktop/renderer-v2/src/features/source/SourceScreen.js` and `desktop/renderer-v2/src/features/export/ExportScreen.js`.
- Selector-style read helpers use `get...`, `can...`, `is...`, or `derive...`, for example `getAccessibleSteps`, `canRunExport`, `isRectValid`, and `deriveCapturePages` in `desktop/renderer-v2/src/app/session/selectors.js` and `desktop/renderer-v2/src/app/session/runtimeSafety.js`.

**Variables:**
- Python locals, parameters, and module-level settings use `snake_case`. Constants use `UPPER_SNAKE_CASE`, for example `SUPPORTED_YOUTUBE_HOSTS` in `backend/app/main.py` and `PDF_JPEG_QUALITY` in `backend/app/pipeline/export.py`.
- Renderer-v2 state keys use `camelCase`, for example `prepareStatus`, `frameTimeLabel`, `selectedPageIds`, and `blockingReason` in `desktop/renderer-v2/src/app/session/selectors.js`.
- API payloads crossing the backend boundary keep backend `snake_case` fields. `desktop/renderer-v2/src/lib/api.js` maps backend payloads such as `video_path`, `progress_mode`, and `log_tail` into UI-friendly `camelCase` objects like `videoPath`, `progressMode`, and `logLines`.

**Types:**
- Python data models, enums, and dataclasses use `PascalCase`, for example `Job`, `SourcePrepareJob`, `JobStatus`, and `PreviewSourceJobStatusResponse` in `backend/app/job_store.py` and `backend/app/schemas.py`.
- Literal alias names also use `PascalCase`, such as `LayoutHint`, `CaptureSensitivity`, and `PageFillMode` in `backend/app/schemas.py`.
- Renderer-v2 exports named constants in `UPPER_SNAKE_CASE`, for example `DEFAULT_FORMATS` and `STEP_ORDER` in `desktop/renderer-v2/src/app/types.js`.

## Code Style

**Formatting:**
- No formatter configuration file is checked in. `rg --files` found no `.eslintrc*`, `eslint.config.*`, `.prettierrc*`, `prettier.config.*`, `biome.json`, `.editorconfig`, `pytest.ini`, or `tsconfig.json` at the repository root.
- Preserve the existing manual formatting rather than introducing a new style tool.
- Python uses 4-space indentation and typed signatures in service and pipeline code. See `backend/run.py`, `backend/app/main.py`, and `backend/app/pipeline/export.py`.
- JavaScript uses 2-space indentation, semicolons, double-quoted strings, and explicit `.js` import extensions. See `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/features/source/SourceScreen.js`, and `desktop/renderer/modules/job-api.js`.
- Multi-line objects and arrays prefer trailing commas in JS and conventional hanging indentation in Python. Follow nearby formatting instead of rewrapping large blocks.

**Linting:**
- No repo-wide lint step is defined for Python.
- Desktop verification relies on syntax and structure checks instead of ESLint. `desktop/package.json` defines `check:renderer-syntax` and `check:renderer-v2`.
- `desktop/scripts/check-renderer-v2.js` is a required contract check. It parses every `desktop/renderer-v2/src/**/*.js` file with `node --check` and asserts the presence or absence of required HTML/CSS markers in `renderer-v2`.
- When adding renderer-v2 code, keep DOM markers, `data-action` hooks, and CSS class names stable enough for `desktop/scripts/check-renderer-v2.js` and the `desktop/renderer-v2/src/tests/*.test.js` suite.

## Import Organization

**Order:**
1. Python stdlib first, then third-party packages, then local `app.*` imports. `backend/app/main.py` and `backend/app/pipeline/extract.py` are the clearest examples.
2. Node builtins first in desktop tests, then application imports. See `desktop/tests/preload-auth.test.mjs`, `desktop/tests/validate-packaged-release.test.mjs`, and `desktop/renderer-v2/src/tests/api.test.js`.
3. Renderer-v2 application modules use explicit relative imports, often grouped by local app/session modules, then UI/features/lib modules. Follow the style in `desktop/renderer-v2/src/app/App.js`.

**Path Aliases:**
- Not detected. Use relative ESM imports with explicit `.js` suffixes in desktop code, for example `../lib/api.js` and `./session/store.js`.
- Backend imports use package-style absolute module paths under `app`, for example `from app.pipeline.export import export_frames`.

## Error Handling

**Patterns:**
- Backend helpers validate early and raise `ValueError`, `FileNotFoundError`, or `RuntimeError` close to the failure site. Examples: `_normalize_supported_youtube_url` in `backend/app/main.py`, `_resolve_source_video` in `backend/app/pipeline/extract.py`, and `_parse_roi` in `backend/app/pipeline/detect.py`.
- FastAPI route handlers in `backend/app/main.py` translate validation failures into `HTTPException` with explicit status codes. Use `400` for bad input, `404` for missing artifacts, `409` for invalid state transitions, and `500` only at the outer boundary after unexpected failures.
- Route helpers preserve explicit `HTTPException` values. The common pattern in `backend/app/main.py` is:

```python
try:
    ...
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc))
except HTTPException:
    raise
except Exception as exc:
    raise HTTPException(status_code=500, detail=f"...: {exc}")
```

- Backend long-running jobs record failure state in stores instead of printing directly. `backend/app/job_store.py` persists `status`, `message`, `error_code`, and truncated `log_tail`.
- Renderer-v2 API adapters throw plain `Error` instances with localized, user-facing text. `desktop/renderer-v2/src/lib/api.js` centralizes failed response parsing in `readJson`.
- Renderer-v2 controllers convert errors into state rather than letting them bubble into the DOM. `desktop/renderer-v2/src/features/source/sourceController.js` stores `prepareErrorDetail` and `error`, and screen renderers surface them through `.inline-error` elements with `role="alert"`.
- Legacy renderer code follows the same guard-then-throw approach. `desktop/renderer/modules/job-api.js` rejects missing ROI, empty file paths, empty format selections, and failed HTTP responses with explicit user-readable messages.

## Validation

**Backend request validation:**
- Prefer `pydantic.BaseModel` schemas with `Field`, `field_validator`, and `model_validator`. `backend/app/schemas.py` is the canonical pattern.
- Use `Literal` values to constrain option tokens. Examples: `LayoutHint`, `CaptureSensitivity`, `DedupeLevel`, and `PageFillMode` in `backend/app/schemas.py`.
- Keep cross-field validation inside schema validators. Examples:
  - `ExtractOptions.validate_window` ensures `end_sec > start_sec`.
  - `UpscaleOptions.validate_scale` rejects `enable=True` with `scale <= 1.0`.
  - `JobReviewExportRequest.validate_selection_mode` blocks mixed `keep_captures` and `keep_images`.
- Use backend helper validation for path normalization and security boundaries. `_resolve_jobs_file_path` in `backend/app/main.py` keeps file access inside `jobs_root`. `_normalize_existing_file_path` and `_normalize_supported_youtube_url` normalize or reject raw input before work starts.

**Frontend state and payload validation:**
- Renderer-v2 uses pure state guards before enabling actions. `desktop/renderer-v2/src/app/session/selectors.js` defines `isRectValid`, `getStepState`, `getAccessibleSteps`, and `getPrimaryAction`.
- Renderer-v2 runtime race protection is explicit. `desktop/renderer-v2/src/app/session/runtimeSafety.js` uses version tokens such as `sourceSession`, `previewVersion`, and `exportVersion` to reject stale async results.
- Legacy renderer payload assembly validates DOM input before sending API requests. `desktop/renderer/modules/job-api.js` uses `parseManualRoi`, `numberOrNull`, `checkedValue`, and `buildPayload` to reject bad UI state early.
- Renderer-v2 screens derive disabled states from validation helpers rather than inline DOM checks. `desktop/renderer-v2/src/features/source/SourceScreen.js` disables YouTube preparation until `isLikelyYoutubeUrl` succeeds.

## Logging

**Framework:** callback-based logging plus persisted job log buffers, not `logging`/`winston`/console-heavy instrumentation

**Patterns:**
- Pipeline functions accept a `logger` callback and sometimes a `progress_callback`. See `backend/app/pipeline/extract.py`, `backend/app/pipeline/detect.py`, `backend/app/pipeline/export.py`, `backend/app/pipeline/rectify.py`, and `backend/app/pipeline/stitch.py`.
- Use short, progress-oriented log strings rather than structured logger objects. Examples include `"starting frame extraction"`, `"youtube download strategy=..."`, and `"review export saved: ..."`.
- Logs are surfaced to the UI through persisted `log_tail` arrays in `backend/app/job_store.py` and consumed by `desktop/renderer-v2/src/lib/api.js` as `logLines`.
- Renderer-v2 exposes progress and logs in the source preparation UI rather than writing to the console. `desktop/renderer-v2/src/features/source/SourceScreen.js` renders the preparation log region with `aria-live="polite"`.

## Comments

**When to Comment:**
- Comments are sparse in UI/state code. Most files under `desktop/renderer-v2/src/` are intentionally comment-light and rely on descriptive names instead.
- Add comments only when behavior is heuristic, algorithmic, or platform-specific. Good examples:
  - `backend/app/pipeline/extract.py` documents Windows single-frame preview fallbacks.
  - `backend/app/pipeline/sheet_finalize.py` explains page split heuristics and whitespace slicing tradeoffs.
  - `backend/app/pipeline/stitch.py` documents overlap confidence handling.
  - `desktop/renderer/modules/job-api.js` has a single targeted comment explaining layout inference.

**JSDoc/TSDoc:**
- Not used.
- Do not introduce JSDoc/TSDoc as a new default. Match the current codebase, which prefers readable names and tests over inline API docs.

## Function Design

**Size:** large orchestrators are acceptable at subsystem boundaries; extract reusable pure helpers for anything that needs isolated validation or tests

**Parameters:**
- Backend pipeline functions prefer keyword-only arguments with `*` and explicit types. Reuse the shape from `backend/app/pipeline/extract.py` and `backend/app/pipeline/export.py`.

```python
def export_frames(
    *,
    frame_paths: List[Path],
    options: ExportOptions,
    workspace: Path,
    logger,
) -> Dict[str, object]:
```

- Renderer-v2 factories prefer dependency injection objects so tests can stub behavior. See `createApp` in `desktop/renderer-v2/src/app/App.js` and `createSourceController` in `desktop/renderer-v2/src/features/source/sourceController.js`.

```javascript
export function createSourceController({
  store,
  readMetadata,
  formatSecondsLabel,
  resetDownstream,
  baseName,
  messages,
}) {
  ...
}
```

**Return Values:**
- Backend helpers usually return concrete domain values: `Path`, `List[Path]`, `Dict[str, object]`, or Pydantic response models.
- Renderer-v2 rendering modules return HTML strings, not DOM nodes. `renderSourceScreen`, `renderRoiScreen`, `renderExportScreen`, and `renderReviewScreen` all follow this contract.
- Renderer-v2 builder helpers return plain objects consumed by renderers or tests. `buildSourceScreenModel` and `buildExportScreenModel` are the standard pattern.
- Controller methods may return booleans when they conditionally accept or reject async updates, as in `applyPrepareJobStarted`, `applyPrepareJobSnapshot`, and `completeYoutubePrepare` in `desktop/renderer-v2/src/features/source/sourceController.js`.

## Module Design

**Exports:** named exports only for application modules

**Barrel Files:** not used

- Renderer-v2 modules export named functions and constants. No `export default` usage was detected under `desktop/renderer-v2/src/`.
- Legacy renderer modules also prefer named exports in ESM files, for example `desktop/renderer/modules/job-api.js` and `desktop/renderer/modules/status-ui.js`.
- CommonJS is reserved for Electron entry/build tooling and a small number of compatibility tests, such as `desktop/tests/renderer-entry.test.cjs` and `desktop/scripts/check-renderer-v2.js`.
- Shared state is centralized in a single session shape in `desktop/renderer-v2/src/app/session/selectors.js` and mutated through `createStore` in `desktop/renderer-v2/src/app/session/store.js`.
- Backend persistence concerns are centralized in `backend/app/job_store.py`; pipeline modules under `backend/app/pipeline/` stay mostly function-oriented and stateless outside filesystem workspaces.

---

*Convention analysis: 2026-04-17*
