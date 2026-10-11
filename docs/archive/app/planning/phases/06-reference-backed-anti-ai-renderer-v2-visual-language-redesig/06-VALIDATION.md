---
phase: 06
slug: reference-backed-anti-ai-renderer-v2-visual-language-redesig
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-19
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `node --test` + renderer-v2 structural checks |
| **Config file** | none — repo uses direct commands from `desktop/package.json` |
| **Quick run command** | `cd desktop && node --test tests/workflow-shell.test.mjs renderer-v2/src/tests/process-rail.test.js renderer-v2/src/tests/context-lane.test.js renderer-v2/src/tests/source-screen.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/roi-editor.test.js renderer-v2/src/tests/review-screen.test.js renderer-v2/src/tests/export-screen.test.js renderer-v2/src/tests/stitch-fidelity.test.js && npm run check:renderer-v2` |
| **Full suite command** | `cd desktop && npm run verify:renderer-v2` |
| **Estimated runtime** | ~45 seconds |

---

## Sampling Rate

- **After every task commit:** Run the targeted quick command for the touched renderer-v2 surfaces
- **After every plan wave:** Run the full suite command
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | Phase 6 visual language reset | T-06-01 | `tokens.css` and shared component styles demote generic shell chrome, keep accent budget restrained, and remove generic AI/workbench vocabulary from persistent UI copy | unit + structural | `cd desktop && node --test renderer-v2/src/tests/stitch-fidelity.test.js renderer-v2/src/tests/i18n.test.js && npm run check:renderer-v2` | ✅ | ⬜ pending |
| 06-02-01 | 02 | 1 | Phase 6 shell hierarchy reset | T-06-02 | top bar, process rail, and context lane keep task-first hierarchy, with the right lane staying selection-driven instead of a permanent utility bucket | unit + structural | `cd desktop && node --test tests/workflow-shell.test.mjs renderer-v2/src/tests/process-rail.test.js renderer-v2/src/tests/context-lane.test.js && npm run check:renderer-v2` | ✅ | ⬜ pending |
| 06-03-01 | 03 | 2 | Phase 6 step-specific surface rewrite | T-06-03 | Source, ROI, Export, and Review each read like score-capture tasks rather than a generic AI dashboard, while ROI direct manipulation remains the primary control | unit | `cd desktop && node --test renderer-v2/src/tests/source-screen.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/roi-editor.test.js renderer-v2/src/tests/review-screen.test.js renderer-v2/src/tests/export-screen.test.js` | ✅ | ⬜ pending |
| 06-04-01 | 04 | 2 | Phase 6 verification hardening | T-06-04 | anti-AI guardrails stay codified in stitch/process/context tests so shell regressions are caught before manual review | unit + structural | `cd desktop && node --test renderer-v2/src/tests/stitch-fidelity.test.js renderer-v2/src/tests/process-rail.test.js renderer-v2/src/tests/context-lane.test.js && npm run check:renderer-v2` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] Existing renderer-v2 test suites already cover shell structure, screen rendering, and copy-level assertions; Phase 6 extends those suites in place instead of requiring a new harness.
- [x] `desktop/scripts/check-renderer-v2.js` already enforces renderer-v2 shell landmarks and will remain the structural backstop during redesign.

*Existing infrastructure covers all phase requirements. Phase 6 adds stronger assertions to existing suites plus manual screenshot/audit evidence during verification.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Source, ROI, Export, and Review each have an obvious first action and read like score-capture workspaces | Phase 6 task-first product language | First-impression hierarchy and perceived workflow fit are not meaningfully provable from DOM/text assertions alone | Open each step in renderer-v2 and confirm the dominant surface matches the task: source preparation, capture region selection, export preflight, or page curation |
| The redesigned UI no longer looks like a generic AI mockup even with branding/microcopy mentally ignored | Phase 6 anti-AI visual contract | “AI-ishness” is a holistic visual judgment across chrome weight, palette distribution, and information hierarchy | Review representative screenshots for all four steps and fail the check if shell chrome reads before task content, if the screen still feels like one amber/brown slab, or if the product could plausibly be mistaken for a generic AI workbench |
| The resulting shell can be traced back to real desktop-tool references rather than copied silhouette aesthetics | Phase 6 reference-fit contract | Reference fidelity is about rationale and behavior, not just static markup | For each major screen, explain which reference family informed it (for example Final Cut, Logic, Ableton, OmniGraffle) and what concrete behavior or hierarchy rule was kept; fail if the explanation collapses into “it just looks modern” |

---

## Validation Sign-Off

- [x] All anticipated task groups have `<automated>` verification paths or existing harness coverage
- [x] Sampling continuity: no 3 consecutive task groups without automated verify
- [x] Wave 0 covers all missing infrastructure references
- [x] No watch-mode flags
- [x] Feedback latency < 45s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending — generated from Phase 6 research on 2026-04-19
