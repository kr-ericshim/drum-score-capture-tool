---
phase: 01
slug: score-style-export-header-and-layout
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-19
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` + `node --test` |
| **Config file** | none — repo uses direct commands |
| **Quick run command** | `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_job_api_contract backend.tests.test_review_export backend.tests.test_review_export_refinalization backend.tests.test_sheet_finalize backend.tests.test_export_document_header && cd desktop && node --test renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js renderer-v2/src/tests/session-selectors.test.js renderer-v2/src/tests/export-header-modal.test.js` |
| **Full suite command** | `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py' && cd desktop && npm run verify:renderer-v2` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run the targeted quick command for the touched surface
- **After every plan wave:** Run the full suite command
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | EXP-01, EXP-02 | — | Export metadata is validated, normalized, and persisted in `job.options.export` without breaking existing export/review contracts | unit | `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_job_api_contract backend.tests.test_review_export && cd desktop && node --test renderer-v2/src/tests/app-runtime-flows.test.js renderer-v2/src/tests/session-selectors.test.js` | ✅ | ✅ green |
| 01-02-01 | 02 | 2 | EXP-03, EXP-04 | — | First-page header is composed only once, page sizing stays consistent, and diagnostics do not mislabel the title band as clipped content | unit | `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_sheet_finalize backend.tests.test_review_export_refinalization backend.tests.test_export_document_header` | ✅ | ✅ green |
| 01-03-01 | 03 | 3 | EXP-01, EXP-02 | — | Export UI remains preflight-first, confirmed modal values reach the job payload, and blank metadata fields do not create fake rows | unit | `cd desktop && node --test renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js renderer-v2/src/tests/session-selectors.test.js renderer-v2/src/tests/export-header-modal.test.js` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/test_export_document_header.py` — first-page-only header, blank-row hiding, diagnostics masking, review-export parity
- [x] `desktop/renderer-v2/src/tests/export-header-modal.test.js` — modal defaults, confirm/cancel flow, payload assembly, PNG-only behavior

*Existing infrastructure covers the rest of the phase. New test files are only needed for the new header/modal surface.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| PDF first page reads like a real score document with Korean or English metadata | EXP-03, EXP-04 | Visual quality, typography, and score-like impression are not meaningfully provable from unit tests alone | Export a representative score as PDF on macOS and Windows packaged builds; confirm centered title hierarchy, hidden blank rows, and no collision between title band and music |
| PNG-only export does not regress while PDF export gains the header | EXP-01, EXP-03 | The product requirement intentionally diverges by format and the correct UX outcome is partly design-contract driven | Run one PNG-only export and one PDF export from the same source; confirm PNG pages stay raw page images and PDF page 1 carries the header |
| Export modal still feels preview-first and collapses cleanly at narrower widths | EXP-01, EXP-02 | Automated tests prove modal hooks and copy, but not the visual dominance of the preview workbench or the actual responsive feel | Open the export step with `pdf` selected at desktop and tablet-ish widths; confirm the preview stays visible behind the overlay, metadata inputs never become a permanent left-column form, and the confirm action remains immediately visible after the single-column collapse |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved after Phase 1 plan coverage review on 2026-04-19

## Validation Audit 2026-04-19

| Metric | Count |
|--------|-------|
| Coverage gaps found | 0 |
| Validation doc corrections | 4 |
| Escalations | 0 |

- Confirmed Wave 0 files now exist: `backend/tests/test_export_document_header.py`, `desktop/renderer-v2/src/tests/export-header-modal.test.js`.
- Verified targeted phase coverage green with the commands listed above.
- Verified full-suite equivalents green with `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'` and `cd desktop && npm run verify:renderer-v2`.
