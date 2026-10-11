---
phase: 01-score-style-export-header-and-layout
verified: 2026-04-19T04:04:46Z
status: human_needed
score: 8/10 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Packaged macOS/Windows PDF font smoke"
    expected: "A representative packaged-build PDF renders Korean and English metadata with a readable score-style header, hidden blank optional rows, and no collision with the score body."
    why_human: "The backend currently resolves fonts from OS-specific paths instead of a bundled asset, and this verification did not run packaged app exports. Release-grade packaged proof is scoped later in Phase 5."
  - test: "Live PNG-only vs PDF export comparison"
    expected: "PNG-only export bypasses the modal and outputs raw page images, while a PDF-selected export opens the document-info modal and page 1 shows the header without breaking the preview-first export workbench feel."
    why_human: "This requires interactive renderer flow plus visual inspection of generated artifacts. Automated tests only prove code paths, markup, and pipeline behavior."
---

# Phase 1: Score-Style Export Header And Layout Verification Report

**Phase Goal:** export 직전에 문서 메타데이터를 입력하고, PDF 최상단이 실제 악보처럼 정돈된 헤더를 갖도록 만들어 export 결과물의 문서 가치를 끌어올린다.
**Verified:** 2026-04-19T04:04:46Z
**Status:** human_needed
**Re-verification:** Yes — follow-up rerun after full-suite recheck

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 사용자는 export 직전에 제목, 연주자, 날짜, BPM, 메모를 입력할 수 있다. | ✓ VERIFIED | `desktop/renderer-v2/src/features/export/ExportScreen.js:228-317` renders the modal fields; `desktop/renderer-v2/src/app/App.js:800-811` gates PDF runs through the modal; renderer tests cover modal open/default/confirm behavior in `desktop/renderer-v2/src/tests/export-header-modal.test.js:118-320`. |
| 2 | Export metadata has one normalized home under `options.export.document_header` across renderer state, API schema, job storage, and review export. | ✓ VERIFIED | `desktop/renderer-v2/src/app/session/selectors.js:63-99`, `desktop/renderer-v2/src/app/App.js:602-640`, `backend/app/schemas.py:81-128`, and `backend/app/main.py:583-586,874-878` all use the same shape; backend contract tests in `backend/tests/test_job_api_contract.py:17-104` and `backend/tests/test_review_export.py:14-68` prove reuse. |
| 3 | Confirmed metadata reaches `createJob(...)` before export starts, so the renderer does not submit stale document info. | ✓ VERIFIED | `desktop/renderer-v2/src/app/App.js:767-798` writes `exportConfig.documentHeader` before `startExportRun(store.getState())`; `desktop/renderer-v2/src/tests/export-header-modal.test.js:268-320` proves the payload sees normalized confirmed values. |
| 4 | Optional header fields remain truly blank and do not become fake placeholder rows in the contract or PDF header. | ✓ VERIFIED | Renderer normalization preserves empty optional fields in `desktop/renderer-v2/src/app/session/selectors.js:73-99`; PDF composition only appends populated rows in `backend/app/pipeline/export.py:332-352`; coverage exists in `desktop/renderer-v2/src/tests/session-selectors.test.js:83-102` and `backend/tests/test_export_document_header.py:68-96`. |
| 5 | Only the PDF path gets the score-style header; PNG/JPG exports remain raw page-image outputs. | ✓ VERIFIED | `backend/app/pipeline/export.py:93-113,195-215,270-298` composes headers only for PDF output; `backend/tests/test_export_document_header.py:98-145` proves PDF invokes the compositor and PNG does not. |
| 6 | The first-page title band consumes real layout space and preserves page geometry instead of overlaying or shrinking the score body unpredictably. | ✓ VERIFIED | `backend/app/pipeline/export.py:279-291` builds a taller first-page canvas, and `backend/app/pipeline/export.py:537-547` scales against score-content height using `score_header_band_height`; regression coverage exists in `backend/tests/test_export_document_header.py:44-67,147-157`. |
| 7 | Diagnostics and review re-export still describe score content truthfully after header composition. | ✓ VERIFIED | Diagnostics are computed on finalized score pages before PDF composition in `backend/app/pipeline/export.py:85,186,560-592`; stored metadata is reused in `backend/app/main.py:583-618`; tests cover diagnostics parity and review-export reuse in `backend/tests/test_export_document_header.py:98-127` and `backend/tests/test_review_export.py:14-68`. |
| 8 | The export step still reads as a preview-first preflight workbench, not a long settings form. | ✓ VERIFIED | `desktop/renderer-v2/src/features/export/ExportScreen.js:150-227` keeps the compact left stack and dominant preview workbench, while `desktop/renderer-v2/src/features/export/ExportScreen.js:228-318` layers the modal as an overlay; layout/CSS support appears in `desktop/renderer-v2/src/styles/layout.css:111-119,221-230` and `desktop/renderer-v2/src/styles/components.css:1229-1377`; locked by `desktop/renderer-v2/src/tests/export-screen.test.js:81-198`. |
| 9 | Exported PDF page 1 visually reads like a clean score-style header to a human reviewer. | ? UNCERTAIN | The compositor exists in `backend/app/pipeline/export.py:301-403`, but this verification did not inspect a rendered PDF by eye on representative content. |
| 10 | Packaged macOS/Windows output keeps correct font rendering and print-ready visual quality. | ? UNCERTAIN | Font resolution is OS-path based in `backend/app/pipeline/export.py:406-429`, and no packaged-build smoke run was executed in this verification. |

**Score:** 8/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `desktop/renderer-v2/src/app/session/selectors.js` | Canonical document-header state, defaults, normalization, modal draft state | ✓ VERIFIED | Present and substantive; referenced from `App.js` and covered by `session-selectors.test.js`. |
| `desktop/renderer-v2/src/app/App.js` | Renderer orchestration for payload building, modal gating, confirm/close actions | ✓ VERIFIED | Present and wired to both DOM actions and backend payload assembly. |
| `backend/app/schemas.py` | Backend validation contract for nested `document_header` | ✓ VERIFIED | Present and wired via `JobCreate` / `ExportOptions`; rejects invalid title/BPM and extra review-export fields. |
| `backend/app/main.py` | Stored export-option reuse for `_run_job()` and `review_export()` | ✓ VERIFIED | Present and wired to both export entrypoints. |
| `backend/app/pipeline/export.py` | Shared PDF header composition, diagnostics-safe export, font fallback | ✓ VERIFIED | Present and wired from both export entrypoints. |
| `backend/tests/test_export_document_header.py` | Focused proof for PDF header composition and invariants | ✓ VERIFIED | Present, substantive, and passing. |
| `backend/tests/test_review_export_refinalization.py` | Review-export parity and preview-image behavior | ✓ VERIFIED | Present, substantive, and passing. |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | Export workbench plus document-info modal markup | ✓ VERIFIED | Present, wired from `App.js`, and rendered in screen tests. |
| `desktop/renderer-v2/src/lib/i18n.js` | Modal/validation/CTA copy in Korean and English | ✓ VERIFIED | Present and consumed by `ExportScreen.js` / selectors validation paths. |
| `desktop/renderer-v2/src/tests/export-header-modal.test.js` | Focused modal regression coverage | ✓ VERIFIED | Present, substantive, and passing. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `desktop/renderer-v2/src/app/App.js` | `backend/app/schemas.py` | `options.export.document_header` payload contract | ✓ WIRED | `buildJobPayload()` writes `document_header`; backend schema accepts the same nested shape. `gsd-tools verify key-links` reported verified. |
| `backend/app/main.py` | `backend/app/pipeline/export.py` | Stored export options reused by both export entrypoints | ✓ WIRED | `_run_job()` and `review_export()` both pass stored `document_header` into `export_frames()` / `export_selected_pages()`. |
| `backend/app/pipeline/export.py` | `backend/tests/test_export_document_header.py` | Header composition, diagnostics, PNG/PDF divergence | ✓ WIRED | Tests call `_compose_pdf_pages_with_document_header()` and `export_selected_pages()` directly. |
| `desktop/renderer-v2/src/app/App.js` | `desktop/renderer-v2/src/features/export/ExportScreen.js` | Modal-open state, field updates, confirm/dismiss actions | ✓ WIRED | DOM actions `run-export`, `update-export-metadata`, `confirm-export-metadata`, and `close-export-metadata` are implemented in `App.js` and rendered in `ExportScreen.js`. |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | `desktop/renderer-v2/src/lib/i18n.js` | PDF-aware CTA labels, helper copy, validation/discard copy | ✓ WIRED | Screen model pulls all modal/helper strings through `t(...)`; `gsd-tools verify key-links` reported verified. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `desktop/renderer-v2/src/app/App.js` | `documentHeader` in `buildJobPayload()` | `state.exportConfig.documentHeader`, populated by `confirmExportMetadata()` | Yes — modal confirm updates state before `createJob(...)` | ✓ FLOWING |
| `backend/app/main.py` | `configured_document_header` | Stored `job.options.export.document_header` via `_resolve_job_export_options(job)` | Yes — same stored config feeds `_run_job()` and `review_export()` | ✓ FLOWING |
| `backend/app/pipeline/export.py` | `normalized_header` | `document_header` args passed from export entrypoints | Yes — row rendering reads real title/performer/BPM/date/memo fields | ✓ FLOWING |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | `metadataModal.draft` / `helperText` | `state.exportConfig.metadataModal` and `isPdfSelected(formats)` | Yes — current state drives live modal inputs and PDF-only helper copy | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase backend contract tests | `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_job_api_contract backend.tests.test_review_export backend.tests.test_review_export_refinalization backend.tests.test_export_document_header backend.tests.test_sheet_finalize` | `Ran 27 tests ... OK` | ✓ PASS |
| Phase renderer export tests | `cd desktop && node --test renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js renderer-v2/src/tests/session-selectors.test.js renderer-v2/src/tests/export-header-modal.test.js` | `54/54` passing | ✓ PASS |
| Full backend suite | `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'` | `Ran 74 tests ... OK` | ✓ PASS |
| Full renderer-v2 verification | `cd desktop && npm run verify:renderer-v2` | renderer entry/workflow/renderer tests all green; `renderer-v2 checks passed (39 JS modules parsed)` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `EXP-01` | `01-01`, `01-03` | User can export the selected score as PDF and page images from the desktop app | ✓ SATISFIED | PNG-only bypass and PDF modal-gated path are covered in `desktop/renderer-v2/src/tests/export-header-modal.test.js:118-143`; export pipeline paths pass in `backend/tests/test_export_document_header.py:98-145`. |
| `EXP-02` | `01-01`, `01-03` | User can enter title, performer, date, BPM, and optional notes immediately before export | ✓ SATISFIED | Modal fields and validation live in `desktop/renderer-v2/src/features/export/ExportScreen.js:228-317` and `desktop/renderer-v2/src/app/App.js:767-798`; renderer tests prove defaults/validation/confirm behavior. |
| `EXP-03` | `01-02` | Exported PDF renders the entered metadata in a clean score-style header at the top of the document | ? NEEDS HUMAN | Automated composition and tests are present, but “clean score-style” still needs visual PDF inspection on representative content. |
| `EXP-04` | `01-02` | Exported pages keep readable margins, consistent page sizing, and print-ready visual quality | ? NEEDS HUMAN | Geometry and scaling regressions are covered automatically, but final print-ready quality and packaged font behavior still need human review. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | No blocking anti-patterns found in phase files. Grep hits were benign default initializers (`[]`, `null`, empty validation state) and helper returns, not user-visible stubs. | ℹ️ Info | No evidence of placeholder UI/API behavior in the implemented phase surfaces. |

### Human Verification Required

### 1. Packaged macOS/Windows Font Smoke

**Test:** Export a representative score as PDF from packaged macOS and Windows builds using both Korean and English metadata.
**Expected:** The title hierarchy is centered and readable, optional blank rows disappear, metadata glyphs render correctly, and the header does not collide with the music body.
**Why human:** Automated tests do not exercise packaged runtime font availability, and the current implementation depends on OS font fallback paths rather than a bundled font asset.

### 2. Live PNG-only vs PDF Export Flow

**Test:** In renderer-v2, run one PNG-only export and one PDF-selected export from the same source/ROI.
**Expected:** PNG-only export starts immediately without the modal and produces raw page images; PDF export pauses for document info, then outputs a first page with the score-style header while the export step still feels preview-first.
**Why human:** This requires end-to-end UI interaction plus visual artifact inspection; unit tests only confirm the code path and rendered markup.

### Gaps Summary

No code or automated-test gaps were found in Phase 01. The implementation, key links, data flow, targeted phase tests, full backend suite, and full `verify:renderer-v2` command all passed. The remaining work is human-only verification of visual PDF quality and packaged-build font/render behavior.

---

_Verified: 2026-04-19T04:04:46Z_  
_Verifier: Codex (gsd-verifier)_
