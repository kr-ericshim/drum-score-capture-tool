---
status: investigating
trigger: "You are diagnosing the Score Capture Program in /Users/ericshim/Documents/myproject/score_capture_program. Scope: Review page selection + review export + export metadata modal + final export behavior in renderer-v2 and backend. Diagnose only; do not edit. Find concrete bug risks, incomplete implementation seams, contract drift, or user-visible inconsistencies that could appear in real review/export flows. Read at minimum: .planning/phases/01-score-style-export-header-and-layout/01-VERIFICATION.md, desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/app/session/selectors.js, desktop/renderer-v2/src/features/review/ReviewScreen.js, desktop/renderer-v2/src/features/export/ExportScreen.js, desktop/renderer-v2/src/lib/api.js, desktop/renderer-v2/src/tests/review-screen.test.js, desktop/renderer-v2/src/tests/export-screen.test.js, desktop/renderer-v2/src/tests/export-header-modal.test.js, desktop/renderer-v2/src/tests/app-runtime-flows.test.js, backend/app/main.py, backend/app/schemas.py, backend/app/pipeline/export.py, backend/tests/test_review_export.py, backend/tests/test_review_export_refinalization.py, backend/tests/test_export_document_header.py. Return only concrete findings with severity, exact file refs, why the flow can break, and whether the current tests miss it. Use marker '## DEBUG COMPLETE'."
created: 2026-04-19T12:02:54Z
updated: 2026-04-19T12:08:10Z
---

## Current Focus

hypothesis: concrete diagnosis is now centered on three seams: renderer capture-only review export, empty-format review export fallback, and PDF metadata bypass when formats change after the initial run
test: finalize evidence against exact file refs and compare those seams with current automated coverage
expecting: a short list of user-visible findings with clear severity and explicit test gaps
next_action: map each confirmed seam to its exact source lines and note which existing tests do not exercise it

## Symptoms

expected: review page selection, review export, export metadata modal, and final export should behave consistently across renderer-v2 and backend with accurate selection semantics and persisted metadata
actual: unknown yet; user requested a diagnosis of real-flow bug risks and inconsistencies
errors: none provided
reproduction: use renderer-v2 review/export flow with both page and capture selection modes, metadata modal input, and final export job submission
started: current code audit requested on 2026-04-19

## Eliminated

## Evidence

- timestamp: 2026-04-19T12:03:40Z
  checked: required verification doc plus minimum frontend/backend implementation and tests
  found: verification asserts metadata modal, normalized document_header contract, and review-export reuse, but human gaps remain for live export flow and packaged PDF rendering
  implication: diagnosis should focus on cross-step runtime seams and contract drift rather than basic phase wiring

- timestamp: 2026-04-19T12:03:40Z
  checked: renderer-v2 review/export orchestration and API layer
  found: App.js review apply path sends selected page capturePath values through api.reviewExport(jobId, keepCaptures, formats), and api.js only serializes keep_captures with no keep_images branch
  implication: backend page-mode review export contract is not reachable from the current renderer flow

- timestamp: 2026-04-19T12:03:40Z
  checked: backend review_export and export_selected_pages
  found: review_export accepts keep_captures or keep_images, but empty formats flow through to export_selected_pages where _normalize_formats() falls back to ['png', 'pdf']
  implication: a review export can generate outputs the user did not actively keep selected if renderer sends an empty format list

- timestamp: 2026-04-19T12:07:05Z
  checked: js_repl experiment with deriveCapturePages() plus rendered review screen markup
  found: a page-mode result carrying one selected page plus stale review_candidates produced two derived review cards, both marked previewKind='capture', dropped the single page diagnostic, and rendered kept 1 / 2 instead of showing the final output page
  implication: page-mode review export is not fully wired through renderer selectors/UI; if that contract is exercised, the review screen misrepresents the final export

- timestamp: 2026-04-19T12:07:05Z
  checked: js_repl experiment rendering ReviewScreen with exportConfig.formats = []
  found: the apply-review button remained enabled as long as jobId, runStatus=done, and at least one selected page were present
  implication: review export can be triggered with no selected output formats, leaving backend fallback logic to choose formats unexpectedly

- timestamp: 2026-04-19T12:08:10Z
  checked: App.js review/apply flow, routes.js step reopening, selectors document-header defaults, and backend review_export reuse path
  found: users can reopen the export step after the initial run, change formats, then apply review; runExport is the only place that opens the PDF metadata modal, while review_export reuses the original stored document_header from the job record
  implication: adding PDF only at review time can generate a final PDF with stale or auto-filled header metadata and no fresh prompt

## Resolution

root_cause:
fix:
verification:
files_changed: []
