---
phase: 06-reference-backed-anti-ai-renderer-v2-visual-language-redesig
plan: "03"
subsystem: step-surfaces
tags: [renderer-v2, source-screen, export-screen, screen-copy, hierarchy, regression-tests]
requires: [06-01, 06-02]
provides:
  - "Stronger first-action framing on the Source screen"
  - "Preview-first reinforcement on the Export screen"
  - "Updated per-screen regression expectations aligned to the new task-first wording"
affects: [06-04, source-flow, export-preflight, review-curation]
tech-stack:
  added: []
  patterns: [panel-kicker hierarchy, preview-first export, task-first per-screen wording]
key-files:
  created:
    - .planning/phases/06-reference-backed-anti-ai-renderer-v2-visual-language-redesig/06-03-SUMMARY.md
  modified:
    - desktop/renderer-v2/src/features/source/SourceScreen.js
    - desktop/renderer-v2/src/features/export/ExportScreen.js
    - desktop/renderer-v2/src/lib/i18n.js
    - desktop/renderer-v2/src/styles/layout.css
    - desktop/renderer-v2/src/styles/components.css
    - desktop/renderer-v2/src/tests/source-screen.test.js
    - desktop/renderer-v2/src/tests/roi-screen.test.js
    - desktop/renderer-v2/src/tests/export-screen.test.js
    - desktop/renderer-v2/src/tests/review-screen.test.js
key-decisions:
  - "Land visible hierarchy through Source/Export markup, shared copy, and CSS instead of broad rewrites of every screen component."
  - "Keep ROI and Review structure mostly intact in markup for this pass, updating their wording/test contract where the Phase 6 copy changed."
  - "Use small `panel-kicker` cues to surface first action and preview priority without adding new chrome."
patterns-established:
  - "Source ingest and registry sections now use a kicker-plus-heading pattern to distinguish first action from recent continuity."
  - "Export preview now explicitly announces preview-first hierarchy while per-screen tests reject dashboard drift."
requirements-completed: [SRC-01, SRC-02, CAP-01, REV-01, REV-02, REL-03]
duration: "not recorded"
completed: 2026-04-19
---

# Phase 06 Plan 03: Step Surface Refocus Summary

**Phase 6 screen work in the current diff sharpened Source and Export hierarchy directly, then aligned ROI and Review through copy/test updates so the per-step surfaces read more like task screens and less like shared shell overflow.**

## Performance

- **Duration:** not recorded in this turn
- **Completed:** 2026-04-19
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Added explicit first-action framing to the Source ingest area and recent-source registry so the opening screen now tells the user what to do first and what can be reopened.
- Added a preview kicker to the Export workbench and reinforced preview-first language in shared copy and styling.
- Updated Source, ROI, Export, and Review tests so the screen contract follows the new wording and rejects generic dashboard framing.

## Task Commits

No atomic git commits were created during this Phase 6 execution in this turn. This summary reflects the current workspace diff only.

## Verification

- `cd desktop && node --test renderer-v2/src/tests/source-screen.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/roi-editor.test.js renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/review-screen.test.js`
  Result: the first run exposed stale ROI expectations after the copy updates; after updating `renderer-v2/src/tests/roi-screen.test.js` to the new wording, the rerun exited `0`.
- `cd desktop && npm run check:renderer-v2`
  Result: exited `0` after the Wave 3 screen-level fixes.

## Files Created/Modified

- `desktop/renderer-v2/src/features/source/SourceScreen.js` - added `panel-kicker` hierarchy for the primary ingest action and recent-source registry.
- `desktop/renderer-v2/src/features/export/ExportScreen.js` - added a preview-first kicker above the export preview workbench.
- `desktop/renderer-v2/src/lib/i18n.js` - updated Source, ROI, Export, and Review copy to match the new first-action and curation language.
- `desktop/renderer-v2/src/styles/layout.css` - kept the stage and preview areas dominant under the slimmer shell proportions.
- `desktop/renderer-v2/src/styles/components.css` - added reusable `panel-kicker` styling and refined Source/ROI/Export/Review visual emphasis.
- `desktop/renderer-v2/src/tests/source-screen.test.js` - updated expectations around start-here and reopen-recent language.
- `desktop/renderer-v2/src/tests/roi-screen.test.js` - updated ROI wording expectations to match the new representative-frame/apply language.
- `desktop/renderer-v2/src/tests/export-screen.test.js` - added preview-first anti-dashboard coverage.
- `desktop/renderer-v2/src/tests/review-screen.test.js` - updated review expectations toward curation wording and anti-dashboard copy.

## Decisions Made

- Landed visible hierarchy improvements where the current diff already touched real UI markup: Source and Export.
- Kept ROI and Review structural changes narrow in this turn; their actual shipped delta here is mostly copy/styling/test alignment, not component rewrites.
- Reused the same shared copy and CSS primitives instead of introducing step-specific one-off styling systems.

## Deviations from Plan

### Auto-fixed Issues

**1. [Blocking] Updated stale ROI test expectations after the shared copy pass**
- **Found during:** Wave 3 targeted verification
- **Issue:** `desktop/renderer-v2/src/tests/roi-screen.test.js` still asserted the older ROI wording (`Recommended frames`, `APPLY ROI`, older status copy), so the planned verification command failed against the new Phase 6 text.
- **Fix:** Updated the ROI expectations to the new representative-frame and apply-region language, then reran the full Wave 3 command.
- **Files modified:** `desktop/renderer-v2/src/tests/roi-screen.test.js`
- **Verification:** `cd desktop && node --test renderer-v2/src/tests/source-screen.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/roi-editor.test.js renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/review-screen.test.js`

---

**Total deviations:** 1 auto-fixed
**Impact on plan:** No scope expansion. The fix kept the screen-verification suite aligned with the actual copy that shipped in this diff.

## Issues Encountered

- This turn did not preserve per-task commit boundaries, so there are no atomic hashes to cite for Wave 3 work.

## Known Stubs

- `desktop/renderer-v2/src/features/roi/RoiScreen.js` and `desktop/renderer-v2/src/features/review/ReviewScreen.js` were not structurally rewritten in the current diff; their Phase 6 alignment here is primarily copy/style/test-level.

## User Setup Required

None.

## Next Phase Readiness

- `06-04` can now lock the current screen wording and first-impression rules into final regression coverage and human UAT.
- The current Source/Export hierarchy is in place for later visual polish without reopening the shell contract.

## Self-Check: PASSED

- FOUND: `.planning/phases/06-reference-backed-anti-ai-renderer-v2-visual-language-redesig/06-03-SUMMARY.md`
- FOUND: `panel-kicker`
- FOUND: `Preview first`
- FOUND: no atomic commit hashes were created for this turn

---
*Phase: 06-reference-backed-anti-ai-renderer-v2-visual-language-redesig*
*Completed: 2026-04-19*
