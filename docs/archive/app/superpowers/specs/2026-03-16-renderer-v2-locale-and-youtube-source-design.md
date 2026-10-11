# Renderer V2 Locale And YouTube Source Design

Date: 2026-03-16

## Goal

Restore two user-visible capabilities in the default `renderer-v2` experience:

1. Whole-app Korean/English UI switching
2. YouTube URL ingest that downloads/prepares a playable local video and then continues through the existing local-file ROI/export/review workflow

The result must preserve `renderer-v2` as the default Electron renderer and avoid regressing the current local-file workflow.

## User-Approved Constraints

- Scope is limited to `UI 전체` language switching and YouTube ingest.
- YouTube support does not need a separate "save MP4" product surface.
- After YouTube preparation, the flow should behave like a local video selection.
- The existing `renderer-v2` shell remains the product direction.
- Regressing to the legacy renderer is not acceptable as the main solution.

## Current State

### What already exists

- `backend/app/main.py` already supports:
  - `POST /preview/source` for file or YouTube source preparation
  - `POST /preview/frame` for file or YouTube preview extraction
  - `POST /jobs` with `source_type: "file" | "youtube"`
- `backend/app/pipeline/extract.py` already contains YouTube download logic and tests.
- `desktop/renderer/modules/i18n.js` and `desktop/renderer/app.js` already implement:
  - persisted `ko` / `en` locale selection
  - YouTube preparation state, logs, and quality-gate behavior in the legacy renderer

### What is missing in the default experience

- `desktop/renderer-v2/` has no locale model, no translation lookup, and no language toggle in the shell.
- `renderer-v2` source state assumes only `filePath`.
- `renderer-v2` source UI only exposes local file selection.
- `renderer-v2/src/lib/api.js` only requests preview frames for local files.
- The default workflow cannot currently drive the already-existing backend YouTube preparation path.

## Product Decision

Use `renderer-v2` as the single implementation target and lift only the required behavior from the legacy renderer.

This is intentionally a behavior recovery project, not a visual redesign. The shell, stage layout, and current `renderer-v2` structure stay in place. The work adds missing state, API calls, and source-step controls without turning `renderer-v2` into a copy of the legacy DOM.

## Approach Options Considered

### Option 1: Re-enable the legacy renderer as default

Fastest short-term recovery, but it abandons the current `renderer-v2` migration and forces a second merge later.

Rejected.

### Option 2: Embed legacy source-step logic directly inside `renderer-v2`

Behavior would return quickly, but state ownership and UI structure would become inconsistent. This would mix two renderer models and make future work brittle.

Rejected.

### Option 3: Rebuild the missing capabilities in `renderer-v2` using existing backend and legacy behavior as reference

This preserves the active renderer architecture, keeps the new shell intact, and limits risk to the source step, shell chrome, and API wrapper layer.

Approved.

## Functional Requirements

### 1. Whole-app locale switching

- The top bar must expose `KO` and `EN` controls.
- Switching locale updates all user-facing `renderer-v2` copy immediately without reload.
- The selected locale persists across app restarts.
- First-run locale selection follows the current product rule:
  - stored locale wins
  - otherwise, system locale starting with `ko` defaults to Korean
  - otherwise default to English
- Locale switching must cover:
  - shell chrome
  - source screen
  - ROI screen
  - export screen
  - review screen
  - inline notices and validation messages emitted from `renderer-v2`

### 2. YouTube source preparation

- The source step must allow either:
  - local file selection
  - YouTube URL entry
- Pressing the YouTube prepare action calls `POST /preview/source` with `source_type: "youtube"`.
- On success, the returned cached local video path becomes the active session source.
- After success, the session transitions exactly like a local file selection:
  - source metadata is populated
  - downstream ROI/export/review state resets
  - the active step moves to `roi`
- The prepared YouTube source is treated as a local file for preview-frame loading and later job execution in `renderer-v2`.

### 3. Failure handling

- Invalid or missing YouTube URLs show inline errors in the source step.
- Preparation failures surface readable inline errors.
- Preparation logs returned by the backend are visible in the source step.
- If the backend indicates low resolved video quality, `renderer-v2` must surface a quality gate equivalent in meaning to the legacy renderer:
  - explain that the downloaded resolution is not safe for score reading
  - recommend trying another source or a directly obtained local file
- While preparation is running, repeated submission is blocked.

## Non-Goals

- No new downloader product beyond YouTube URL ingest for the existing capture workflow
- No new source providers beyond YouTube and local files
- No range-trimming redesign
- No backend rewrite of the YouTube downloader
- No shell-wide theme redesign

## UX Contract

## Source Screen

- Keep the current `renderer-v2` source screen composition, but add a clear dual-source input surface.
- The source step presents:
  - one local-file action
  - one YouTube URL input with prepare action
  - compact current-source metadata
  - preparation status and recent log output when the active source mode is YouTube
- The current active source remains singular. Preparing a YouTube video replaces the previous session source the same way selecting a new local file does.
- The source summary shown in the shell uses:
  - file name for local files
  - a truncated YouTube URL or resolved file name after preparation for YouTube-origin sources

## Shell Locale Controls

- Add `KO` and `EN` controls to the `renderer-v2` top bar in the same header control cluster as other utility actions.
- The active locale is visually distinguished.
- Locale controls do not change workflow step or session data.

## State Model Changes

Extend `createInitialSessionState()` with the following focused additions:

- `source`
  - `sourceType: "file" | "youtube"`
  - `youtubeUrl: string`
  - `preparedFromYouTube: boolean`
  - `prepareStatus: "idle" | "loading" | "ready" | "error"`
  - `prepareLogs: string[]`
  - `preparedVideoPath: string`
- `ui`
  - `locale: "ko" | "en"`

Rules:

- `source.filePath` remains the canonical playable path used by ROI, preview, and export.
- For YouTube sessions, `preparedVideoPath` and `filePath` resolve to the same cached local video path after preparation.
- `sourceType` reflects the user’s chosen input mode, not merely the current backend path type.
- Locale state is separate from capture session state so changing language never resets the workflow.
- A separate monotonically increasing prepare-request token is required in app state or app-local controller state so stale async responses can be ignored safely.

## Architecture And File Responsibilities

### `desktop/renderer-v2/src/app/session/selectors.js`

- Extend initial state with locale and YouTube preparation fields.
- Add locale-aware step labels and blocking messages through translation lookup instead of hard-coded Korean strings.
- Keep selectors as pure state derivation only.

### `desktop/renderer-v2/src/app/App.js`

- Own new UI event handling for:
  - locale switching
  - source mode switching
  - YouTube URL input
  - YouTube preparation action
- Reuse the existing local-file reset semantics when a new prepared YouTube source becomes active.
- Treat ROI/export/review flows as source-agnostic once `source.filePath` is resolved.
- Centralize inline notice/error generation through locale-aware message helpers.

### `desktop/renderer-v2/src/features/source/SourceScreen.js`

- Render the dual-source controls and preparation status surface.
- Render source metadata for either prepared YouTube or local file sessions.
- Render preparation logs and quality-gate messaging when relevant.
- Remain a pure render module with no network logic.

### `desktop/renderer-v2/src/lib/api.js`

- Add `preparePreviewSource({ sourceType, filePath, youtubeUrl })`.
- Generalize `requestPreviewFrame()` so it can request by `source_type`, but `renderer-v2` should prefer the already-prepared local file path after YouTube preparation.
- Keep API helpers thin and stateless.

## Explicit API Contract

### `preparePreviewSource()`

Renderer request:

- local file mode
  - `source_type: "file"`
  - `file_path: <selected path>`
- YouTube mode
  - `source_type: "youtube"`
  - `youtube_url: <entered url>`

Renderer handling rules:

- On YouTube success, store:
  - `source.preparedFromYouTube = true`
  - `source.preparedVideoPath = response.video_path`
  - `source.filePath = response.video_path`
  - `source.prepareLogs = response.log_lines`
- `video_url` is optional transport metadata for future use and is not required for the `renderer-v2` flow.

### Low-quality detection signal

- `renderer-v2` will use the same explicit heuristic as the legacy renderer for Phase 1:
  - if preparation fails and backend detail or returned log lines contain `low resolution <width>x<height>` or `resolved to <width>x<height>`, treat it as a YouTube quality-gate case
  - otherwise treat it as a normal preparation failure
- This keeps the boundary aligned with the current backend contract without requiring a backend schema change in this project.

### `createJob()` payload rule

- Once a YouTube source has been prepared successfully, `renderer-v2` must submit downstream preview and job requests as file-backed requests:
  - `source_type: "file"`
  - `file_path: source.filePath`
- `renderer-v2` must not submit `source_type: "youtube"` to `POST /jobs` after preparation succeeds.
- `source.sourceType` remains a UI-origin field used for:
  - restoring the active input mode
  - rendering source-step copy
  - distinguishing a prepared YouTube session from a direct local-file session
- `source.sourceType` does not control the downstream backend payload once `source.filePath` has been resolved.

### New `desktop/renderer-v2/src/lib/i18n.js`

- Own:
  - supported locales
  - translation dictionary
  - locale persistence helpers
  - `t()` lookup with fallback to English
  - first-run locale detection
- `renderer-v2` must not depend on the legacy renderer i18n module directly.

### Shell renderers

- `desktop/renderer-v2/src/ui/shell/TopBar.js`
- `desktop/renderer-v2/src/ui/shell/ProcessRail.js`
- `desktop/renderer-v2/src/ui/shell/ContextLane.js`
- screen modules under `src/features/`

These modules must accept translated labels from shared helpers instead of embedding static Korean copy.

## Data Flow

### Local file path

1. User clicks local file selection.
2. Electron bridge returns a local path.
3. Metadata is read in the renderer.
4. Session source is updated.
5. Downstream state resets.
6. Active step moves to `roi`.

### YouTube path

1. User chooses YouTube mode and enters a URL.
2. User presses prepare.
3. `renderer-v2` captures a new prepare-request token and calls `POST /preview/source`.
4. Backend downloads or reuses cached local video and returns:
   - `video_path`
   - optional `video_url`
   - `from_cache`
   - `log_lines`
5. Renderer ignores the response unless its token is still the latest active prepare request.
6. Renderer stores logs, sets `preparedFromYouTube`, and promotes `video_path` into the canonical `source.filePath`.
7. Renderer reads metadata from the returned local file path.
8. Downstream state resets.
9. Active step moves to `roi`.
10. ROI/export/review use the same file-based flow as local input.

## Error And Edge Cases

- Empty YouTube input: block request and show inline validation.
- Unsupported host or malformed URL: show backend validation message in localized form.
- Preparation timeout or downloader error: show inline error and keep the user in the source step.
- Cached success with no log lines: still show successful prepared state.
- User selects a local file after a prepared YouTube source: local file becomes canonical and YouTube-specific status is cleared.
- User prepares a second YouTube URL while one is already active: new prepared source replaces the previous one and resets downstream state.
- User edits the YouTube URL, switches input mode, or selects a local file while YouTube preparation is still running: the previous prepare request becomes stale and its eventual response must be ignored.
- Locale switch during active preparation: visible text updates immediately, but in-flight request continues and applies normally when finished.
- Backend log lines may remain verbatim English diagnostics; wrapper labels, headings, statuses, buttons, and inline summary messages must still follow the active locale.

## Testing Requirements

### Renderer unit tests

- Update source-screen tests to cover:
  - dual-source UI presence
  - YouTube prepare state rendering
  - current-source metadata rendering for prepared YouTube
- Add session selector tests for:
  - locale initialization
  - source step enablement with prepared YouTube source
- Add app-flow tests for:
  - locale toggle updates shell copy
  - YouTube prepare success promotes cached video path and enters ROI
  - YouTube prepare failure keeps the user on source with error
  - stale YouTube prepare responses are ignored after the user changes source intent
  - selecting a local file after YouTube preparation resets YouTube state cleanly

### Backend regression coverage

- Existing backend YouTube tests remain the guardrail.
- No new backend behavior is required unless implementation exposes a missing contract during integration.

## Acceptance Criteria

- Launching the default app shows `renderer-v2` with visible `KO` / `EN` controls.
- Changing locale updates the whole visible `renderer-v2` UI without restart.
- Locale persists across reload/restart.
- Entering a supported YouTube URL and preparing it transitions into the same ROI workflow as local-file selection.
- The resulting ROI/export/review path works without requiring separate YouTube-specific handling.
- Preparation failures and low-quality outcomes are visible and understandable in the source step.
- Existing local-file behavior remains intact.
