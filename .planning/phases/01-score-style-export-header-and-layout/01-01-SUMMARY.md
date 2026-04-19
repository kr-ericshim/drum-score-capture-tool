---
phase: 01-score-style-export-header-and-layout
plan: "01"
subsystem: export
tags: [renderer-v2, fastapi, pydantic, export-contract, testing]
requires: []
provides:
  - "Canonical document_header state and normalization under exportConfig"
  - "Stored export-option reuse across initial export and review re-export"
  - "Schema guard that rejects review-export metadata override payloads"
affects: [01-02, 01-03, export-pipeline, review-export]
tech-stack:
  added: []
  patterns: [state-owned export metadata, stored export option reuse, schema-level extra-field rejection]
key-files:
  created: [.planning/phases/01-score-style-export-header-and-layout/01-01-SUMMARY.md]
  modified:
    - desktop/renderer-v2/src/app/session/selectors.js
    - desktop/renderer-v2/src/app/App.js
    - backend/app/schemas.py
    - backend/app/main.py
    - backend/app/pipeline/export.py
    - backend/tests/test_job_api_contract.py
    - backend/tests/test_review_export.py
    - desktop/renderer-v2/src/tests/session-selectors.test.js
    - desktop/renderer-v2/src/tests/app-runtime-flows.test.js
key-decisions:
  - "exportConfig.documentHeader is the single renderer-side home for title, performer, bpm, date, and memo defaults."
  - "Both _run_job() and review_export() resolve document_header from stored job.options.export instead of trusting review-time request payloads."
  - "JobReviewExportRequest forbids extra fields so review export cannot grow a second metadata contract."
patterns-established:
  - "Renderer export payloads normalize document_header once before createJob."
  - "Backend export entrypoints accept document_header as a pass-through seam before PDF rendering lands in 01-02."
requirements-completed: [EXP-01, EXP-02]
duration: 9m
completed: 2026-04-19
---

# Phase 01 Plan 01: Define export metadata contract Summary

**Renderer state, API schema, and stored job export options now share one `options.export.document_header` contract for title, performer, bpm, date, and memo.**

## Performance

- **Duration:** 9m
- **Started:** 2026-04-19T03:14:16Z
- **Completed:** 2026-04-19T03:23:20Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Locked renderer-side export metadata into `exportConfig.documentHeader` with source-filename and today defaults plus one normalization helper.
- Extended backend schema and review API guards so `document_header` is validated once and review export cannot introduce a second metadata payload.
- Reused stored export options across `_run_job()` and `review_export()` so initial export and review re-export keep the same metadata contract.

## Task Commits

Each task was committed atomically:

1. **Task 1: Normalize `document_header` state and payload before export job creation**
   - `c77052a` (`test`) add failing document header contract coverage
   - `3e9c007` (`feat`) normalize export document header contract
2. **Task 2: Reuse stored document metadata across `_run_job()` and `review_export()` without a review-only API**
   - `610811d` (`test`) add failing stored metadata reuse coverage
   - `40a5c9c` (`feat`) reuse stored document header across export paths

## Files Created/Modified

- `desktop/renderer-v2/src/app/session/selectors.js` - document header defaults, reset config factory, and normalization helpers.
- `desktop/renderer-v2/src/app/App.js` - renderer export payload now writes `options.export.document_header`.
- `backend/app/schemas.py` - nested document_header model plus review-export extra-field rejection.
- `backend/app/main.py` - stored export option resolver used by both initial export and review export.
- `backend/app/pipeline/export.py` - pass-through seam for document_header until header rendering work lands.
- `backend/tests/test_job_api_contract.py` - stored-option reuse and review override rejection coverage.
- `backend/tests/test_review_export.py` - review export keeps stored document_header coverage.
- `desktop/renderer-v2/src/tests/session-selectors.test.js` - state contract and normalization coverage.
- `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` - createJob payload timing coverage.

## Decisions Made

- Kept document metadata defaults in session helpers instead of UI markup so later modal work cannot fork the contract.
- Resolved export options from persisted `job.options.export` in backend flows so initial export and review export share one truth source.
- Forbid extra review-export request fields so the API cannot silently accept a review-only metadata override.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added pass-through `document_header` seams in the export pipeline**
- **Found during:** Task 2 (stored metadata reuse)
- **Issue:** `backend/app/main.py` needed to forward stored metadata into both export entrypoints, but `backend/app/pipeline/export.py` could not accept `document_header` on review export or initial export.
- **Fix:** Added no-op `document_header` parameters to `export_frames()` and `export_selected_pages()` so the contract can flow end-to-end before PDF rendering work in 01-02.
- **Files modified:** `backend/app/pipeline/export.py`, `backend/app/main.py`, `backend/tests/test_job_api_contract.py`, `backend/tests/test_review_export.py`
- **Verification:** `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_job_api_contract backend.tests.test_review_export`
- **Committed in:** `40a5c9c`

**2. [Rule 3 - Blocking] Updated a stale locale test expectation so task verification could run green**
- **Found during:** Task 2 verification
- **Issue:** `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` still expected older top-bar copy (`PRECISION MEDIA WORKBENCH`, etc.) even though the current UI renders `Drum Sheet Capture` / `Choose video`, causing the planned verification command to fail unrelated to document-header work.
- **Fix:** Adjusted the test to assert the current top-bar copy tokens already used elsewhere in the renderer-v2 test suite.
- **Files modified:** `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`
- **Verification:** `cd desktop && node --test renderer-v2/src/tests/app-runtime-flows.test.js renderer-v2/src/tests/session-selectors.test.js`
- **Committed in:** `40a5c9c`

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes were required to make the contract path testable and keep the planned verification command green. No user-facing scope expansion beyond the contract seam.

## Issues Encountered

- The shell environment has no `python` alias. Backend verification used `backend/.venv/bin/python` with `PYTHONPATH=backend` instead.

## Known Stubs

- `backend/app/pipeline/export.py`: `document_header` is accepted and forwarded but intentionally unused for layout/rendering in this plan. Plan `01-02` is responsible for composing the visible score-style PDF header.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `01-02` can now consume one stable `document_header` payload from both initial export and review re-export.
- Renderer modal work in `01-03` can write into `exportConfig.documentHeader` without inventing a second payload path.
- Visible PDF header rendering still does not exist yet; this plan only locked the contract and persistence path.

## Self-Check: PASSED

- FOUND: `.planning/phases/01-score-style-export-header-and-layout/01-01-SUMMARY.md`
- FOUND: `c77052a`
- FOUND: `3e9c007`
- FOUND: `610811d`
- FOUND: `40a5c9c`

---
*Phase: 01-score-style-export-header-and-layout*
*Completed: 2026-04-19*
