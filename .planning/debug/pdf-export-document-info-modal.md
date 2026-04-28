---
status: investigating
trigger: "Diagnose why the PDF export path can still fail after the document-info modal is filled and confirmed. Focus on the exact modal-confirm -> payload-build -> export-run path and any frontend/backend contract drift that could still prevent PDF generation. Diagnose only; do not edit."
created: 2026-04-20T00:00:00+09:00
updated: 2026-04-20T04:02:00+0900
---

## Current Focus
hypothesis: the previous `start_sec` drift theory may be invalid because current workspace docs/code intentionally pin export capture start to `0`; the real PDF failure is elsewhere in the modal-confirm -> createJob -> backend export/result contract
test: verify the pinned-0 contract in current phase docs, then trace post-confirm PDF-specific payload handling and result consumption to find a different falsifiable cause
expecting: either the docs/code will disprove the previous theory, or they will explicitly show why the pinned contract itself is wrong
next_action: search current phase docs and code for the intentional `start_sec = 0` export contract, then inspect PDF result handling after job completion

## Symptoms
expected: After entering document information for a PDF-selected export and confirming the modal, the PDF should still generate successfully.
actual: PDF generation can still fail after the user fills the document info modal and confirms it.
errors: User report only: "아직도 문서 정보 작성 후 pdf 생성 안되는 오류 있음."
reproduction: Choose PDF export, enter document information in the modal, confirm, then run export.
started: not yet specified

## Eliminated

## Evidence

- timestamp: 2026-04-20T03:49:07+0900
  checked: .planning/phases/06-reference-backed-anti-ai-renderer-v2-visual-language-redesig/06-HUMAN-UAT.md and .planning/phases/01-score-style-export-header-and-layout/01-VERIFICATION.md
  found: Phase 01 verification claimed modal-confirm payload flow was verified, but the latest UAT still reports "아직도 문서 정보 작성 후 pdf 생성 안되는 오류 있음."
  implication: the remaining failure is not basic modal visibility/copy; an uncovered runtime path still breaks after confirm

- timestamp: 2026-04-20T03:49:07+0900
  checked: desktop/renderer-v2/src/app/App.js
  found: `confirmExportMetadata()` stores the normalized `documentHeader`, then calls `startExportRun(store.getState())`; `startExportRun()` creates the job from `buildJobPayload(state)`; `buildJobPayload()` hardcodes `options.extract.start_sec` to `0` while sending the confirmed `options.export.document_header`
  implication: document info is preserved, but the export payload still ignores the user's selected ROI frame time

- timestamp: 2026-04-20T03:49:07+0900
  checked: desktop/renderer-v2/src/app/App.js and backend/app/main.py
  found: `startExportRun()` preflights ROI health with `requestPreviewRoiHealth({ startSec: state.roi.frameTime, ... })`, but backend `POST /jobs` immediately re-runs `_enforce_roi_capture_gate(... start_sec=payload.options.extract.start_sec, ...)`
  implication: frontend preflight and backend job creation validate different timestamps for the same ROI, which can make modal-confirm succeed locally but job creation fail remotely

- timestamp: 2026-04-20T03:49:07+0900
  checked: backend/app/pipeline/extract.py
  found: ffmpeg extraction applies `-ss <start_sec>` when `start_sec` is provided
  implication: the hardcoded `0` is not cosmetic; it changes the actual export frame range the backend processes

- timestamp: 2026-04-20T03:49:07+0900
  checked: desktop/renderer-v2/src/tests/export-header-modal.test.js and desktop/renderer-v2/src/tests/app-runtime-flows.test.js
  found: the current tests explicitly assert `seenPayload.options.extract.start_sec === 0` even when `roi.frameTime` is set to `12.8` or `60`
  implication: the regression suite currently locks in the drift instead of catching it, which explains why modal/IME fixes could land while the real export failure remained

## Resolution
root_cause: The modal-confirm path correctly normalizes and forwards `options.export.document_header`, but the same payload still hardcodes `options.extract.start_sec` to `0` in `buildJobPayload()`. That drifts from the selected ROI/export context (`state.roi.frameTime`) used by the UI and ROI-health preflight, so backend `/jobs` validation and ffmpeg extraction run against the wrong timestamp and can reject or fail the PDF export after the user confirms document info.
fix: Align `buildJobPayload()` with the selected export context by sending `state.roi.frameTime` as `options.extract.start_sec`, then update the modal/export tests that currently assert `0` so they prove the payload matches the chosen ROI frame.
verification: Diagnosis only. Verified by tracing the modal-confirm call chain, backend `/jobs` gate, ffmpeg extraction use of `start_sec`, and the current tests that enshrine `start_sec === 0`.
files_changed: []
