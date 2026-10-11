---
status: diagnosed
trigger: "PDF-selected export fails after confirming document information modal; diagnose root cause only without using the rejected start_sec theory."
created: 2026-04-19T18:55:39Z
updated: 2026-04-19T19:00:56Z
---

## Current Focus

hypothesis: confirmed root cause is a duplicated synchronous ROI-health gate before job creation, with no timeout on the frontend fetch path
test: completed
expecting: n/a
next_action: return root-cause diagnosis only

## Symptoms

expected: After entering document information for a PDF-selected export, confirming the modal should still generate the PDF successfully.
actual: PDF generation still fails after document information is entered and confirmed.
errors: User report only: "아직도 문서 정보 작성 후 pdf 생성 안되는 오류 있음."
reproduction: Select PDF export, enter document information in the modal, confirm, then observe that PDF generation does not complete successfully.
started: Reported on 2026-04-20; exact regression start unknown from provided context.

## Eliminated

- hypothesis: review re-export is the primary explanation for the user's current repro
  evidence: User clarified the failure happens immediately after clicking confirm in the document-info modal, before any visible work starts.
  timestamp: 2026-04-19T19:00:56Z

- hypothesis: the confirm click handler itself is not wired in the current renderer
  evidence: export-header-modal tests drive dispatchAction(\"confirm-export-metadata\") through the real App.js click delegation and reach both successful createJob() and pending-state assertions.
  timestamp: 2026-04-19T19:00:56Z

- hypothesis: title/BPM validation is the primary silent failure path
  evidence: validateExportMetadataDraft() only blocks blank title or non-digit BPM, and the focused modal tests assert visible validation/error rendering rather than silent return.
  timestamp: 2026-04-19T19:00:56Z

## Evidence

- timestamp: 2026-04-19T19:00:56Z
  checked: App.js confirm-export path and runtime guards
  found: confirmExportMetadata() validates the draft, persists documentHeader, then awaits startExportRun(); startExportRun() immediately enters runStatus='running' and blocks on requestPreviewRoiHealth() before createJob()
  implication: the earliest post-confirm stall point is the ROI health preflight, not the PDF renderer or review re-export path

- timestamp: 2026-04-19T19:00:56Z
  checked: backend/app/main.py preview_roi_health and backend/app/pipeline/roi_health.py
  found: /preview/roi-health runs synchronously and extracts three preview frames via analyze_roi_health_for_source() before returning; create_job itself is only called after this preflight succeeds
  implication: confirm can spend noticeable time before any job starts, so a stuck/slow preflight would exactly match "confirm clicked but nothing starts"

- timestamp: 2026-04-19T19:00:56Z
  checked: ExportScreen.js pending-state rendering plus export-header-modal tests
  found: while runStatus is running and the metadata modal remains open, the modal switches the confirm label to a busy copy and renders pending text; however, the pending state still occurs before any job is created or polled, and the tests do not cover an indefinitely unresolved preflight request
  implication: the renderer already shows some busy feedback, so the stronger failure seam is not missing click wiring but a pre-job pending state that can hang without timeout or recovery

- timestamp: 2026-04-19T19:00:56Z
  checked: backend job artifacts with stored pdf outputs
  found: existing jobs such as 430466a3-5d12-46b8-95e8-a01cbec328bd and 659c7da2-0498-48f3-a84f-14e79f385b05 are status=done and their export/sheet_export.pdf files exist
  implication: the repo does not exhibit a blanket "PDF generation is broken" failure; the narrower seam is before job creation or user-visible startup feedback

- timestamp: 2026-04-19T19:00:56Z
  checked: App.js startExportRun(), backend create_job(), and roi-health backend implementation
  found: confirm-export first awaits /preview/roi-health in the renderer, then /jobs runs _enforce_roi_capture_gate() again before returning job_id, and each gate performs three preview-frame extractions synchronously
  implication: the confirm path can spend two sequential round-trips doing expensive ROI analysis before any job exists, so if either gate stalls the user sees a modal pending state and no export job starts

- timestamp: 2026-04-19T19:00:56Z
  checked: frontend API transport and tests
  found: requestPreviewRoiHealth() and createJob() use bare fetch with no timeout/abort handling, while current tests mock roi-health success/failure or manually resolve a deferred promise but never cover real transport stalls or the backend's duplicate gate
  implication: current tests can all pass even though packaged/runtime repros get stuck before job creation

## Resolution

root_cause:
root_cause: The modal confirm path does not start the export job directly. It first waits for a synchronous ROI-health preflight in the renderer, then waits for a second synchronous ROI-health gate inside POST /jobs before the backend creates and starts the job. Because both gates run before any job_id exists and the frontend transport has no timeout/abort path, a stall in either gate leaves the modal in pending state and makes confirm look like a no-op even though the PDF pipeline itself can work.
fix:
verification:
files_changed: []
