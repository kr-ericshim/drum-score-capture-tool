---
status: investigating
trigger: "You are diagnosing the Score Capture Program in /Users/ericshim/Documents/myproject/score_capture_program. Scope: ROI loading/edit/apply + capture job creation boundary + runtime guards between ROI and export/review in renderer-v2. Diagnose only; do not edit. Find concrete bug risks, incomplete implementations, hidden state coupling, and broken edge cases that could surface during real user flow. Read at minimum: desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/app/session/selectors.js, desktop/renderer-v2/src/app/session/runtimeSafety.js, desktop/renderer-v2/src/features/roi/RoiScreen.js, desktop/renderer-v2/src/features/roi/roiEditor.js, desktop/renderer-v2/src/tests/roi-screen.test.js, desktop/renderer-v2/src/tests/roi-editor.test.js, desktop/renderer-v2/src/tests/app-runtime-flows.test.js, backend/tests/test_extract_preview_frame.py, backend/tests/test_capture_crop.py, backend/tests/test_roi_health.py, backend/tests/test_job_api_contract.py. Return only concrete findings with severity, exact file refs, trigger path, and missing/weak coverage. Use marker '## DEBUG COMPLETE'."
created: 2026-04-19T00:00:00+09:00
updated: 2026-04-19T00:20:00+09:00
---

## Current Focus

hypothesis: Confirmed: renderer-v2 uses separate truth sources for ROI draft/applied state and export/review job state, and some async export/review paths are not bound to a stable session token.
test: Correlate `applyRoi`, `getStepState`, `runExport`, `applyReviewSelection`, and runtime guard invalidation paths against scoped tests.
expecting: Confirmed findings should show stale export/review state surviving ROI edits, stale job payloads surviving UI edits, or old async completions writing into a newer session.
next_action: Return concrete findings with severity, trigger path, exact refs, and missing coverage.

## Symptoms

expected: Diagnose concrete bug risks in ROI load/edit/apply and capture job/export-review runtime boundaries before they surface in real user flow.
actual: Unknown until code and tests are traced.
errors: Unknown until investigation.
reproduction: Exercise ROI screen, ROI editor, capture job creation, and export/review guard flows in code and tests.
started: Audit request on 2026-04-19.

## Eliminated

## Evidence

- timestamp: 2026-04-19T00:06:00+09:00
  checked: desktop/renderer-v2/src/app/session/runtimeSafety.js
  found: `invalidatePreviewFlow()` clears ROI/export/review state on frame or preview-candidate changes, but no equivalent invalidation exists for ROI re-apply on the same preview.
  implication: ROI edits on the same frame can leave stale export/review artifacts live unless some other action happens to invalidate them.

- timestamp: 2026-04-19T00:10:00+09:00
  checked: desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/app/session/selectors.js, desktop/renderer-v2/src/app/routes.js
  found: `applyRoi()` only writes `appliedRect`, `layoutHint`, and `activeStep`, while step accessibility is computed solely from `appliedRect`, `jobId`, `runStatus`, and `review.pages`.
  implication: Pending or newly applied ROI changes do not relock export/review, so users can navigate with stale downstream job state.

- timestamp: 2026-04-19T00:13:00+09:00
  checked: desktop/renderer-v2/src/features/export/ExportScreen.js, desktop/renderer-v2/src/app/App.js
  found: Export format checkboxes remain interactive during `runStatus === "running"`, while `startExportRun()` captures a pre-await state snapshot and later builds the job payload from that stale snapshot.
  implication: UI-visible export options can diverge from the job actually created if the user edits formats during ROI health/job creation latency.

- timestamp: 2026-04-19T00:16:00+09:00
  checked: desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/app/session/runtimeSafety.js
  found: `startExportRun()` catch writes error state without rechecking `isCurrentExport(exportRun)`, and `applyReviewSelection()` only guards refresh by `activeJobHandle` when it is non-null.
  implication: Invalidated or superseded export/review requests can still write stale errors or old job snapshots into a newer source session.

- timestamp: 2026-04-19T00:18:00+09:00
  checked: desktop/renderer-v2/src/tests/roi-screen.test.js, desktop/renderer-v2/src/tests/app-runtime-flows.test.js
  found: Existing tests cover frame-time/candidate invalidation, duplicate export prevention, and ROI screen copy, but do not exercise ROI re-apply after export, pending-draft navigation guards, stale export failures after invalidation, or source changes during review apply.
  implication: The current suite protects only part of the runtime boundary and leaves the strongest stale-state paths untested.

## Resolution

root_cause: renderer-v2 does not model ROI draft/applied/export/review as one coherent state machine. It invalidates downstream state for frame changes, but not for same-frame ROI edits/re-apply, and some async export/review paths lack a session-stable token check on completion/error.
fix: Diagnose only; no fix applied.
verification: Confirmed by reading scoped renderer/backend code paths and matching them against the existing test suite's covered versus uncovered transitions.
files_changed: []
