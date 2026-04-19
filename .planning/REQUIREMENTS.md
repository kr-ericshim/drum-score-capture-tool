# Requirements: Score Capture Program

**Defined:** 2026-04-19
**Core Value:** 개인 연주자가 영상으로부터 빠르고 정확하게 usable한 악보를 뽑고, 별도 편집 없이 바로 보관하거나 인쇄할 수 있는 문서 품질의 PDF를 얻어야 한다.

## v1 Requirements

### Source Intake

- [ ] **SRC-01**: User can open a local score video and confirm the source is ready before capture starts
- [ ] **SRC-02**: User can prepare a YouTube score source into the same local capture workflow without manual file wrangling
- [ ] **SRC-03**: User sees clear errors or quality warnings when a source is too weak, broken, or unsuitable for reliable capture

### Capture Accuracy

- [ ] **CAP-01**: User can define or adjust the score ROI on a preview frame and trust that capture uses the confirmed ROI
- [ ] **CAP-02**: User can run automatic capture that detects real score page changes while suppressing obvious near-duplicate frames
- [ ] **CAP-03**: User receives meaningful diagnostics when capture results look suspicious, incomplete, or noisy
- [ ] **CAP-04**: User can rerun capture with tuned settings and understand what changed in the result

### Review Control

- [ ] **REV-01**: User can review captured candidates in order and keep or remove pages before final export
- [ ] **REV-02**: User can quickly spot likely bad pages through preview, warnings, or diagnostics instead of checking every page blindly
- [ ] **REV-03**: User can preserve the intended final page order and avoid accidental duplicates or gaps in the exported result

### Export Document

- [x] **EXP-01**: User can export the selected score as PDF and page images from the desktop app
- [x] **EXP-02**: User can enter title, performer, date, BPM, and optional notes immediately before export
- [ ] **EXP-03**: Exported PDF renders the entered metadata in a clean score-style header at the top of the document
- [ ] **EXP-04**: Exported pages keep readable margins, consistent page sizing, and print-ready visual quality

### Release Readiness

- [ ] **REL-01**: User can install and launch packaged desktop builds on supported macOS and Windows without separately installing Python, Node, or FFmpeg
- [ ] **REL-02**: User always sees honest progress, completion, and error states for source prepare, capture, review, and export jobs
- [ ] **REL-03**: User can complete the default source -> ROI -> capture -> review -> export flow without hidden prerequisite knowledge
- [ ] **REL-04**: Official release verification proves the packaged app preserves the core source-to-export workflow on supported builds

## v2 Requirements

### Workflow Depth

- **WFLO-01**: User can save and reopen work-in-progress sessions as explicit project files
- **WFLO-02**: User can batch-process multiple source videos with reusable capture presets

### Export Flexibility

- **EXFX-01**: User can choose from multiple score-header templates or typographic themes
- **EXFX-02**: User can add richer document metadata such as composer, arranger, key, or memo blocks

## Out of Scope

| Feature | Reason |
|---------|--------|
| Account system | No central server or user-account product direction |
| Cloud sync | Local-first desktop workflow is the product baseline |
| Real-time collaboration | Target user is an individual player, not a team workspace |
| Template marketplace | Not necessary for proving release value |
| Online processing backend | Conflicts with the current local runtime model |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| EXP-01 | Phase 1 | Complete |
| EXP-02 | Phase 1 | Complete |
| EXP-03 | Phase 1 | Pending |
| EXP-04 | Phase 1 | Pending |
| CAP-01 | Phase 2 | Pending |
| CAP-02 | Phase 2 | Pending |
| CAP-03 | Phase 2 | Pending |
| SRC-03 | Phase 2 | Pending |
| CAP-04 | Phase 3 | Pending |
| REV-01 | Phase 3 | Pending |
| REV-02 | Phase 3 | Pending |
| REV-03 | Phase 3 | Pending |
| SRC-01 | Phase 4 | Pending |
| SRC-02 | Phase 4 | Pending |
| REL-02 | Phase 4 | Pending |
| REL-03 | Phase 4 | Pending |
| REL-01 | Phase 5 | Pending |
| REL-04 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-19*
*Last updated: 2026-04-19 after initial definition*
