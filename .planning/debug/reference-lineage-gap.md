---
status: diagnosed
trigger: "Diagnose why a reviewer cannot identify a convincing desktop-tool reference lineage and instead just reads the UI as generally ugly. Focus on missing borrowed behaviors, mismatched hierarchy, and where the implementation drifted from the intended reference-backed direction. Diagnose only; do not edit."
created: 2026-04-20T03:45:05+09:00
updated: 2026-04-20T04:04:00+09:00
---

## Current Focus

hypothesis: Phase 06 promised a behavior-backed pro-desktop redesign, but the shipped renderer-v2 mostly kept a static four-edge workbench shell and generic panel/card patterns, so reviewers cannot see concrete borrowed desktop-tool lineage and instead read the UI as a generic dark control panel with unattractive chrome.
test: Compare the research/UI-spec behavior contract against AppShell/layout/components/screen code and the actual verification tests to see whether pro-tool hierarchy and borrowed behaviors were implemented or only approximated by copy/palette changes.
expecting: If correct, the docs will require contextual panels, hide/showable chrome, stage-first dominance, and sparse accent usage, while the code will still keep persistent shell chrome, heavy repeated panel styling, generic utility summaries, and tests that verify wording/regions rather than reference-fit behavior.
next_action: Return structured diagnosis with the confirmed root cause and the specific files where the reference-backed contract drifted.

## Symptoms

expected:
  A reviewer should be able to identify the closest desktop-tool reference family for the overall product, cite at least three concrete borrowed hierarchy or behavior choices, and point to only limited remaining drift.
actual:
  The reviewer cannot name a convincing reference lineage and instead reports the product as simply "구림", meaning the intended reference-backed direction is not legible in the rendered UI.
errors:
  No runtime error; failure is visual-language diagnosis and reference-fit gap.
reproduction:
  Open the current renderer-v2 shell and its source/export/review surfaces, then assess whether the desktop-tool lineage is concretely legible rather than vaguely "more polished".
started:
  After the Phase 06 reference-backed anti-AI renderer-v2 visual-language redesign implementation that was supposed to anchor the UI in pro desktop creative-tool references.

## Eliminated

- hypothesis: The reference-fit failure is mainly because the palette stayed amber-heavy and never moved to the neutral shell promised by Phase 06.
  evidence: `desktop/renderer-v2/src/styles/tokens.css:1-33` did reset the base palette to neutral graphite values (`#121418`, `#161a20`, `#1b1f26`) with accent separated out, so the remaining failure cannot be explained by the old amber slab alone.
  timestamp: 2026-04-20T04:04:00+09:00

- hypothesis: The reviewer failed to identify lineage mainly because obvious machine/workbench wording was never removed.
  evidence: `desktop/renderer-v2/src/lib/i18n.js:155-220,414-470` and `desktop/renderer-v2/src/tests/process-rail.test.js:102-141` show the worst `workflow/system/engine` wording was intentionally replaced/guarded, but the reviewer still reports the product as just ugly, so copy cleanup alone did not solve reference legibility.
  timestamp: 2026-04-20T04:04:00+09:00

## Evidence

- timestamp: 2026-04-20T03:45:05+09:00
  checked: /Users/ericshim/.codex/memories/MEMORY.md
  found: Prior repo memory for this exact redesign says the intended diagnosis/reference family was "monotone workstation + too much shell chrome + generic tool vocabulary + fake precision" and the target lineage was pro desktop creative tools like Final Cut Pro, Logic Pro, Ableton Live, OmniGraffle, and DaVinci Resolve.
  implication: The current diagnosis should test not only aesthetics but whether those specific desktop conventions became legible in renderer-v2.

- timestamp: 2026-04-20T03:56:00+09:00
  checked: .planning/phases/06-reference-backed-anti-ai-renderer-v2-visual-language-redesig/06-RESEARCH.md and 06-UI-SPEC.md
  found: The planned direction explicitly required a `navigation sidebar + dominant content stage + contextual inspector`, hide/showable panels, selection-based inspectors, sparse accent budget, and a ban on top bar + rail + context lane + status bar all feeling equally important.
  implication: The intended reference lineage depended on visible hierarchy and borrowed desktop-tool behaviors, not on palette/copy changes alone.

- timestamp: 2026-04-20T03:58:00+09:00
  checked: desktop/renderer-v2/src/ui/shell/AppShell.js, desktop/renderer-v2/src/styles/layout.css, desktop/renderer-v2/src/app/App.js
  found: The shipped shell still mounts a persistent top bar, process rail, stage pane, context lane slot, and footer status bar (`AppShell.js:3-11`), with the default layout staying three-column plus footer (`layout.css:1-23,149-176`) and live status text always injected in the footer (`App.js:484-535`).
  implication: The product-level silhouette remains a static workbench frame, so the user sees broad shell chrome before any distinctly borrowed desktop-tool behavior.

- timestamp: 2026-04-20T03:59:00+09:00
  checked: desktop/renderer-v2/src/ui/shell/TopBar.js, ProcessRail.js, ContextLane.js, desktop/renderer-v2/src/styles/components.css, desktop/renderer-v2/src/lib/i18n.js
  found: Although the worst banned wording was removed, the shell still relies on generic utility summaries and persistent support chrome such as engine badge, rail footer summaries, output path actions, and source/review inspector blocks (`TopBar.js:22-63`, `ProcessRail.js:15-95`, `ContextLane.js:11-113`, `i18n.js:155-220,414-470`). Shared styling also keeps gradients, inset shadows, accent pills, micro labels, and inspector cards repeated across top bar, rail, panel, and modal surfaces (`components.css:1-313,401-760`).
  implication: The redesign preserved a generic dark-toolkit grammar; the UI may be cleaner than before, but it still lacks unmistakable reference-family cues and still over-emphasizes chrome.

- timestamp: 2026-04-20T04:00:00+09:00
  checked: desktop/renderer-v2/src/features/source/SourceScreen.js, ExportScreen.js, ReviewScreen.js
  found: Source is still composed as an ingest card + YouTube utility block + registry table, Export as a config-stack + preview-stage split, and Review as a card grid with pills and checkbox controls (`SourceScreen.js:204-307`, `ExportScreen.js:160-335`, `ReviewScreen.js:14-89`). These are sensible layouts, but they do not implement the stronger borrowed pro-tool behaviors named in research such as hide/showable work areas, contextual inspectors, quick-help affordances, or unmistakable tool-specific hierarchy rhythms.
  implication: Reviewers can maybe recognize generic “software UI” competence, but they do not get concrete lineage signals strong enough to say “this is borrowing from Final Cut/Logic/Ableton/OmniGraffle.”

- timestamp: 2026-04-20T04:02:00+09:00
  checked: .planning/phases/06-reference-backed-anti-ai-renderer-v2-visual-language-redesig/06-VERIFICATION.md, desktop/renderer-v2/src/tests/stitch-fidelity.test.js, desktop/renderer-v2/src/tests/process-rail.test.js
  found: Verification already admitted that anti-AI and reference-fit required human review (`06-VERIFICATION.md:7-16,41-43,75-79,89-99`), but the automated tests mostly lock DOM regions, banned strings, and existence of persistent shell structures such as the footer status bar (`stitch-fidelity.test.js:32-194`, `process-rail.test.js:10-193`) rather than verifying screenshot-level hierarchy or borrowed desktop-tool behavior.
  implication: The phase could pass green while still missing the actual human-legible reference lineage the redesign was supposed to create.

## Resolution

root_cause: Phase 06 drifted from a reference-backed desktop-tool adaptation into a mostly structural reskin of the existing renderer-v2 shell. The implementation did reset palette and some copy, but it kept a persistent multi-edge workbench frame, repeated generic panel/chip chrome, and screen compositions that resemble competent generic software panels more than identifiable Final Cut/Logic/Ableton/OmniGraffle behaviors. Because the borrowed behavior contract (hide/showable chrome, stronger contextual inspector logic, more unmistakable stage dominance and focus modes, more reference-specific interaction economy) was not materially implemented, a reviewer cannot cite lineage and instead collapses the result into “just ugly.” The green verification also masked this by testing vocabulary/markup more than actual screenshot-level reference fit.
fix: []
verification: Diagnosis only. Root cause confirmed by comparing Phase 06 research/UI-spec/verification against the current renderer-v2 shell, shared styling, screen implementations, and test guardrails.
files_changed: []
