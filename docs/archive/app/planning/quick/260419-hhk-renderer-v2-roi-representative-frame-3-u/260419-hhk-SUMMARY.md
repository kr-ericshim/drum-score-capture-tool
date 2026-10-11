---
phase: quick-260419-hhk
plan: 260419-hhk
subsystem: [renderer-v2, roi]
tags: [renderer-v2, roi, preview-candidates]
provides:
  - "ROI stage now seeds three representative preview candidates and auto-loads the recommended one."
  - "Users can override the recommended candidate before applying ROI."
  - "Export payloads remain locked to extract.start_sec=0."
affects: [roi preview flow, export start_sec contract]
tech-stack:
  added: []
  patterns: [client-side candidate orchestration, roi-state reset on candidate override]
key-files:
  created: []
  modified:
    - desktop/renderer-v2/src/app/App.js
    - desktop/renderer-v2/src/app/session/selectors.js
    - desktop/renderer-v2/src/app/session/runtimeSafety.js
    - desktop/renderer-v2/src/features/source/sourceController.js
    - desktop/renderer-v2/src/features/roi/RoiScreen.js
    - desktop/renderer-v2/src/lib/i18n.js
    - desktop/renderer-v2/src/styles/layout.css
    - desktop/renderer-v2/src/styles/components.css
    - desktop/renderer-v2/src/tests/app-runtime-flows.test.js
    - desktop/renderer-v2/src/tests/roi-screen.test.js
    - desktop/renderer-v2/src/tests/session-selectors.test.js
    - desktop/renderer-v2/src/tests/source-controller.test.js
key-decisions:
  - "Representative preview candidates use 20/33/50 percent of duration, with the middle candidate auto-selected."
  - "Candidate switching invalidates preview, ROI, export, and review state, but keeps the candidate strip intact."
duration: 29m
completed: 2026-04-19
status: complete
---

# Quick Task 260419-hhk Summary

**Renderer-v2 ROI now enters with three recommended preview candidates, auto-loads the middle recommendation, and still keeps export start time pinned to zero.**

## Accomplishments

- Added a representative-frame candidate model to ROI state and seeded it from both local-file and YouTube-prepared source flows.
- Auto-loaded the selected candidate on ROI entry so users no longer land on an empty canvas.
- Added a visible three-choice ROI picker with override support and reset behavior that relocks downstream export/review steps.
- Locked the candidate rule and regression behavior with selector, controller, ROI render, and runtime tests.

## Verification

- Targeted suite:
  - `cd desktop && node --test renderer-v2/src/tests/session-selectors.test.js renderer-v2/src/tests/source-controller.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js`
- Full suite:
  - `cd desktop && npm run verify:renderer-v2`

## Task Commits

1. **Implement recommended ROI preview candidates** - `68214df`

## Next Readiness

The ROI step now has a stable recommended-frame entry flow. Future work can improve candidate quality scoring without changing the export contract.
