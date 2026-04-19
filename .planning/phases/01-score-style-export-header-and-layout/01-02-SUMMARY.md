---
phase: 01-score-style-export-header-and-layout
plan: "02"
subsystem: export
tags: [pdf, pillow, fastapi, export-pipeline, diagnostics]
requires:
  - phase: 01-01
    provides: "Persisted `document_header` metadata flowing through initial export and review re-export"
provides:
  - "Shared first-page PDF score header composition across initial export and review export"
  - "Deterministic score-header font fallback with wrapped and capped metadata rows"
  - "Header-safe PDF prep that preserves first-page music scale and score-based diagnostics"
affects: [01-03, review-export, pdf-layout, export-pipeline]
tech-stack:
  added: []
  patterns: [shared PDF header composer, header-band-aware PDF scaling, diagnostics-before-composition]
key-files:
  created:
    - .planning/phases/01-score-style-export-header-and-layout/01-02-SUMMARY.md
    - backend/tests/test_export_document_header.py
  modified:
    - backend/app/pipeline/export.py
key-decisions:
  - "Only the PDF path composes the score-style header; PNG/JPG exports and review previews stay raw finalized page images."
  - "Page diagnostics remain based on finalized score pages before header composition so the new title band cannot create false suspicious-page warnings."
  - "Composed PDF pages carry `score_header_band_height` metadata so `_prepare_pdf_image()` preserves first-page music scale even when the header makes the page taller."
patterns-established:
  - "Initial export and review export both route PDF pages through `_compose_pdf_pages_with_document_header()` before `_prepare_pdf_image()`."
  - "Header growth is bounded by explicit wrap and line caps instead of allowing long title or memo text to expand the first page without limit."
requirements-completed: [EXP-03, EXP-04]
duration: 6m
completed: 2026-04-19
---

# Phase 01 Plan 02: Score-style PDF Header Composition Summary

**Shared Pillow-based first-page score header composition now gives PDF exports a document-grade title band while keeping PNG/JPG output, diagnostics, and review-export preview behavior unchanged.**

## Performance

- **Duration:** 6m
- **Started:** 2026-04-19T03:30:51Z
- **Completed:** 2026-04-19T03:37:07Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added one shared PDF-only header compositor for both `export_frames()` and `export_selected_pages()` with first-page-only layout expansion.
- Added focused backend coverage for first-page-only rendering, blank optional-row hiding, PNG/PDF divergence, diagnostics honesty, and first-page scale preservation.
- Hardened PDF prep so header-only height growth no longer shrinks the first page's music content relative to later pages.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add one shared first-page PDF header composer with deterministic font fallback**
   - `3988f96` (`test`) add failing PDF header compositor coverage
   - `3c234e8` (`feat`) compose first-page PDF score header
2. **Task 2: Keep diagnostics, page sizing, and review-export parity honest after the title band exists**
   - `957507c` (`test`) add failing PDF header scale guard
   - `138f213` (`feat`) preserve PDF score-page scale with header band

## Files Created/Modified

- `backend/app/pipeline/export.py` - shared PDF header composition, font fallback, capped wrapping, and header-band-aware PDF scaling.
- `backend/tests/test_export_document_header.py` - targeted proof for first-page-only header rendering, diagnostics safety, PNG/PDF divergence, and scale preservation.

## Decisions Made

- Kept the score-style header entirely in the PDF path so image exports and review previews remain trustworthy page-image artifacts.
- Reused one compositor in both export entrypoints instead of allowing initial export and review export to drift.
- Preserved diagnostics from finalized score pages and taught PDF prep to ignore header-only height when deciding whether to downscale the first page.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed first-page score shrink caused by header-only PDF downscaling**
- **Found during:** Task 2 (Keep diagnostics, page sizing, and review-export parity honest after the title band exists)
- **Issue:** After adding the header band, `_prepare_pdf_image()` still scaled against the full composed height, which could shrink the first page's music content even when only the header pushed the page past `PDF_IMAGE_MAX_EDGE`.
- **Fix:** Stored `score_header_band_height` on composed PDF pages and updated `_prepare_pdf_image()` to scale against the original score-content height instead of the extra header-only height.
- **Files modified:** `backend/app/pipeline/export.py`, `backend/tests/test_export_document_header.py`
- **Verification:** `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_review_export_refinalization backend.tests.test_export_document_header` and `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_sheet_finalize`
- **Committed in:** `138f213`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The auto-fix was required to satisfy the plan's geometry invariant. No scope expansion beyond the planned PDF header work.

## Issues Encountered

- The repository shell environment does not expose a `python` alias, so verification used `backend/.venv/bin/python` with `PYTHONPATH=backend`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `01-03` can now build the export-time document-info modal against a stable backend contract where PDF-only header behavior, blank-row hiding, and review-export parity are already proven.
- Manual packaged-app smoke checks for macOS/Windows font rendering are still valuable because the backend currently relies on OS font fallback paths instead of a bundled font asset.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: `.planning/phases/01-score-style-export-header-and-layout/01-02-SUMMARY.md`
- FOUND: `3988f96`
- FOUND: `3c234e8`
- FOUND: `957507c`
- FOUND: `138f213`

---
*Phase: 01-score-style-export-header-and-layout*
*Completed: 2026-04-19*
