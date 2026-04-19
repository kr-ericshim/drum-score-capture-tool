---
status: passed
task: 260419-hhk
verified_on: 2026-04-19
---

# Quick Task 260419-hhk Verification

## Result

Passed.

## Commands

- `cd /Users/ericshim/Documents/myproject/score_capture_program/desktop && node --test renderer-v2/src/tests/session-selectors.test.js renderer-v2/src/tests/source-controller.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js`
- `cd /Users/ericshim/Documents/myproject/score_capture_program/desktop && npm run verify:renderer-v2`

## Must-have Checks

- [x] ROI stage exposes exactly 3 preview candidates for the representative frame flow.
- [x] Source selection auto-selects the middle candidate and auto-loads ROI preview without an extra click.
- [x] Users can override the selected candidate before applying ROI.
- [x] Candidate timestamps can be non-zero while export payloads still keep `options.extract.start_sec = 0`.
- [x] Selector/controller/render/runtime tests cover candidate generation, auto-load, override, and start_sec regression.
