# Phase 01 — Research

**Date:** 2026-04-19  
**Question:** 무엇을 알아야 Phase 1을 얕지 않게 계획할 수 있는가?  
**Confidence:** High for current code seams and workflow contracts. Medium for cross-platform font packaging until packaged builds are manually checked.

## Current Baseline

- Renderer-v2 export step is intentionally a `preflight` screen, not a long settings page. The current screen only exposes format toggles, processing profile summary, app-managed destination, dominant preview stage, and the run button.
- `desktop/renderer-v2/src/app/App.js` currently builds export jobs through `buildJobPayload()` and sends only `formats`, `include_raw_frames`, and `page_fill_mode` into `options.export`.
- `backend/app/schemas.py` defines `ExportOptions` with no document metadata fields yet, so there is no durable path today for title/performer/BPM/date/memo to survive job creation or review re-export.
- `backend/app/main.py` stores export options on the job and `review_export()` later reuses the stored export config when it regenerates the final output. This is the key reuse seam: metadata should live in `job.options.export`, not in a separate review-only payload.
- `backend/app/pipeline/export.py` already owns final export composition. It finalizes page images first, then emits PNG/JPG assets and writes the PDF from PIL images. That makes it the correct place to insert a first-page document header.
- `backend/app/pipeline/sheet_finalize.py` already normalizes page size, scale, and print margins. Header work should extend this page-composition path, not bypass it with a second page-sizing system.

## Standard Stack

- **Renderer state and flow:** keep using the dependency-free renderer-v2 session model in `desktop/renderer-v2/src/app/session/selectors.js` and the app action dispatcher in `desktop/renderer-v2/src/app/App.js`.
- **UI mechanism:** implement the export-time metadata step as an app-managed modal/overlay inside renderer-v2. Do not add a modal library for Phase 1.
- **API contract:** extend `ExportOptions` with a nested document-header payload so the metadata is validated once at the API boundary and then persisted in `job.options`.
- **PDF composition:** use the existing Pillow-based export path in `backend/app/pipeline/export.py` for header drawing and first-page layout composition. Avoid introducing a second PDF engine.
- **Typography asset strategy:** use a backend font-resolution helper with packaged-font support plus OS fallbacks. This is required because Korean metadata must render reliably on both macOS and Windows release builds.
- **Verification stack:** keep backend verification in `unittest` and renderer verification in `node --test`; extend current suites rather than introducing a new harness.

## Architecture Patterns

### 1. Confirm Metadata At Export Time, Not In The Screen Body

- The export screen must remain a compact preflight stage.
- The user decision `D-05` and the renderer specs both point to the same implementation: pressing the primary export action should open a focused metadata modal, and the actual job creation should happen only after confirm.
- Defaults belong in renderer state so the user sees them before the payload is built:
  - title from source filename
  - date from "today"
  - BPM and memo empty by default

### 2. Normalize Metadata Once And Reuse It Everywhere

- Metadata should be normalized in one shape under `options.export`, then reused by:
  - initial export in `_run_job()`
  - review re-export in `review_export()`
- This avoids the common failure where the first PDF gets a header but the final post-review PDF loses it.

### 3. Compose The Header As Real First-Page Layout Space

- The header must consume actual vertical space on page 1, not draw on top of the music image.
- The cleanest seam is a shared export helper in `backend/app/pipeline/export.py` that:
  - receives finalized page images
  - expands the first page canvas with a title/header band
  - pastes the music content lower on page 1
  - leaves page 2+ unchanged
- Reuse `_prepare_pdf_image()` after composition so compression and PDF writing stay centralized.

### 4. Keep PNG/JPG Behavior Separate From PDF Header Composition

- Phase 1 requirement only promises a score-style header in the PDF.
- PNG/JPG page outputs should stay page-image exports unless the plan explicitly decides otherwise later.
- Planner should therefore treat header composition as a PDF-path concern while preserving image-export parity and avoiding hidden behavioral drift.

### 5. Preserve Review Workflow By Sharing The Same Composer

- `export_frames()` and `export_selected_pages()` both emit PDFs today.
- Header composition must be implemented through a shared helper used by both functions. Duplicating logic in both places will almost certainly drift.
- `review_export()` already stages output and rewrites paths safely. Reuse that path; do not invent a second review artifact flow.

### 6. Keep Diagnostics Honest

- `page_diagnostics` currently flags dense top/bottom edges to catch split errors.
- If the header text is drawn before diagnostics without accounting for the new title band, page 1 can become a false positive.
- Either:
  - compute diagnostics on the music-content image before the header band is added, or
  - teach diagnostics to ignore the header band on page 1.

## Don't Hand-Roll

- Do **not** introduce HTML-to-PDF or browser-print rendering for Phase 1. The repo already has a Pillow PDF path that is close enough to extend safely.
- Do **not** build a second page sizing / margin system outside `sheet_finalize.py`.
- Do **not** duplicate header rendering logic between initial export and review export.
- Do **not** rely on Pillow's default bitmap font. It will not meet Korean release quality.
- Do **not** put metadata only in renderer-local temporary state; it has to survive into `job.options.export` so review re-export can reuse it.

## Common Pitfalls

### Cross-Platform Font Drift

- The repo currently ships no `.ttf/.otf/.ttc` assets.
- Renderer CSS already assumes Korean-capable UI font fallbacks (`Pretendard`, `SUIT`, `Noto Sans KR`, `Apple SD Gothic Neo`), but backend PDF rendering does not have that luxury unless it resolves an actual font file.
- On the current macOS machine, `/System/Library/Fonts/AppleSDGothicNeo.ttc` exists, but Phase 1 must also hold on Windows release builds. That means the planner should decide whether to:
  - ship a font asset with the app, or
  - implement a deterministic cross-platform fallback chain and verify it in packaged smoke tests.

### Initial Export / Review Export Divergence

- If metadata is only read during `_run_job()`, the final PDF produced after review selection will regress to headerless output.
- The safe design is: metadata stored in `job.options.export`, both export paths consume the same payload.

### False Suspicious Diagnostics On Page 1

- The current top-edge density heuristic can mistake the title band for clipped music content.
- Planner must include a task that keeps diagnostics meaningful after the header band exists.

### Stale Payload Snapshots Around The Modal

- `runExport()` currently reads `store.getState()` and immediately calls `createJob(buildJobPayload(state))`.
- Once a confirm modal exists, the confirmed metadata must be written into state before `buildJobPayload()` runs, or the payload will lag one interaction behind.

### Undefined PNG-Only Interaction

- The user decision locked the modal at export time, but the product requirement only demands PDF header rendering.
- UI-SPEC needs to settle the UX for PNG-only runs:
  - still show metadata modal and explain it only affects PDF when selected, or
  - skip the modal for non-PDF runs.
- This is a design-contract issue, not a backend blocker.

### Unbounded Text Growth

- Long title/memo strings can easily collide with the score content or create a comically tall first-page band.
- The composer needs explicit wrapping, line limits, and blank-row hiding.

## Code Examples

| File | Why it matters |
|------|----------------|
| `desktop/renderer-v2/src/app/session/selectors.js` | canonical export state shape and the default-value seam |
| `desktop/renderer-v2/src/app/App.js` | `buildJobPayload()`, `runExport()`, and `applyJobSnapshot()` are the renderer/backend contract bridge |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | current preflight composition that must not collapse into a generic form |
| `desktop/renderer-v2/src/tests/export-screen.test.js` | existing export-screen contract tests to extend for modal affordance and preflight preservation |
| `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` | existing job-run flow tests where payload assembly and export reset behavior are already asserted |
| `backend/app/schemas.py` | Pydantic seam for durable export metadata validation |
| `backend/app/main.py` | `_run_job()` and `review_export()` are the two export entrypoints that must stay behaviorally aligned |
| `backend/app/pipeline/export.py` | shared final export logic, PDF write path, and page diagnostics |
| `backend/app/pipeline/sheet_finalize.py` | existing page framing/margin normalization that should remain the source of truth |
| `backend/tests/test_review_export.py` | proves review re-export depends on stored export options and staged export flow |
| `backend/tests/test_review_export_refinalization.py` | existing PDF/preview refinalization behavior to extend without regressing |
| `backend/tests/test_sheet_finalize.py` | protects page split/margin behavior that header work must not destabilize |

## Validation Architecture

### Automated Coverage Shape

- **Renderer unit/flow tests**
  - metadata modal default values
  - blank-field hiding semantics exposed in screen summaries or payload shape
  - job payload contains normalized header metadata after confirm
  - export screen remains a preflight layout, not a stacked form
- **Backend export tests**
  - first page gets a header band, later pages do not
  - empty metadata rows are omitted
  - first-page composition keeps consistent page size and print margins
  - review re-export preserves the same header metadata
  - diagnostics remain honest after header composition
- **Manual PDF checks**
  - Korean and English metadata both render correctly
  - first-page visual impression reads like a real score document
  - music does not collide with the title band

### Recommended Commands

- **Targeted quick loop**
  - `PYTHONPATH=backend python -m unittest backend.tests.test_review_export backend.tests.test_review_export_refinalization backend.tests.test_sheet_finalize`
  - `cd desktop && node --test renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js renderer-v2/src/tests/session-selectors.test.js`
- **Full phase suite**
  - `PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_*.py'`
  - `cd desktop && npm run verify:renderer-v2`

## Planning Implications

- The roadmap's existing 3-plan split is correct:
  - contract/state/backend schema
  - export pipeline composition
  - export-time UX plus regression coverage
- The phase is technically ready for planning from a backend-contract perspective.
- However, the planner should **not** finalize renderer tasks until a UI contract exists for:
  - modal shape and confirm/cancel behavior
  - PNG-only run behavior
  - how document metadata is previewed or summarized without turning export into a settings page

## Recommendation

- **Research result:** proceed with planning inputs, but honor the UI safety gate first.
- **Immediate next prerequisite:** generate `01-UI-SPEC.md` so the planner can write renderer tasks without inventing modal IA on the fly.
