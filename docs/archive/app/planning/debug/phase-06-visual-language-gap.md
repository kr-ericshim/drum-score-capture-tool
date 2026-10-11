---
status: diagnosed
trigger: "Diagnose why the implementation still reads as a futuristic system panel / generic AI tool despite Phase 06 goals. Focus on concrete visual-language causes, hierarchy, density, shell dominance, token/copy combinations, and any contradictions against the UI spec. Diagnose only; do not edit."
created: 2026-04-20T00:00:00+09:00
updated: 2026-04-20T03:48:56+09:00
---

## Current Focus

hypothesis: the implementation still reads as a futuristic system panel because the shipped shell uses control-room composition and ornament everywhere: persistent multi-rail chrome, amber-emphasized status surfaces, and tiny technical labels repeat across every step and overpower the task surface
test: diagnosis complete
expecting: n/a
next_action: Return root-cause report with line-level evidence and fix direction only.

## Symptoms

expected: Ignoring branding, Source, ROI, Export, and Review should still read as a local score-capture desktop tool rather than a generic AI workbench, control-room dashboard, futuristic system panel, or monochrome amber mockup.
actual: The product still reads as a futuristic system panel and a typical AI design.
errors: No runtime error; issue is a visual-language mismatch against Phase 06 goals.
reproduction: Open the renderer-v2 app and inspect Source, ROI, Export, and Review screens with the shell chrome and copy in place.
started: Observed after Phase 06 implementation review; severity major.

## Eliminated

- hypothesis: the anti-AI gap is mainly caused by the base token palette still being amber-heavy
  evidence: tokens.css moves the foundation to neutral graphite, but components.css reintroduces accent/paper/system styling across top bar, rail, inspector, source, export, review, and archive surfaces
  timestamp: 2026-04-20T03:48:56+09:00

- hypothesis: the anti-AI gap is mainly caused by explicit AI/workflow wording
  evidence: many primary labels were already rewritten to task-first copy, but the shell still renders engine badges, preparation logs, status strips, inspector cards, progress bars, and micro-kickers that preserve a system-panel impression even without the old wording
  timestamp: 2026-04-20T03:48:56+09:00

## Evidence

- timestamp: 2026-04-20T03:47:05+09:00
  checked: Phase 06 UI spec, HUMAN-UAT, and VERIFICATION artifacts
  found: The phase contract explicitly requires task-first hierarchy, sparse accent usage, reduced shell chrome, and a blind anti-AI pass; verification still records the exact failed perception report "미래형 시스템 패널로 읽히고 전형적인 ai 디자인처럼 읽힘."
  implication: This is not a missing acceptance criterion; the implementation is violating the documented visual-language contract itself.

- timestamp: 2026-04-20T03:47:05+09:00
  checked: desktop/renderer-v2/src/styles/layout.css and shell components
  found: The default shell reserves a 212px left rail, 256px right context lane, top bar, and status bar simultaneously, while source/review screens still add an extra full-width headline band above the main work surface.
  implication: The shell still consumes a large portion of the viewport before the user reaches the actual task surface, which matches a dashboard/control-room read more than a focused local tool.

- timestamp: 2026-04-20T03:47:05+09:00
  checked: desktop/renderer-v2/src/styles/components.css and tokens.css
  found: Although tokens define a neutral palette, component styles repeatedly reintroduce accent-colored borders, pills, gradients, badges, progress bars, and paper/amber overlays across top bar, rail, inspector, source, export, review, and archive surfaces.
  implication: The live visual system is still amber-signaled almost everywhere, so the product reads as a stylized futuristic panel rather than a restrained desktop capture utility.

- timestamp: 2026-04-20T03:47:05+09:00
  checked: desktop/renderer-v2/src/lib/i18n.js and rendered shell/screen markup
  found: User-facing copy is less explicit than before, but the UI still relies heavily on micro support labels, status phrasing, and technical affordances such as engine badges, preparation status, logs, progress strips, summary pills, and inspector labels.
  implication: Even with task-first nouns, the density and framing of the supporting copy still cues "system console" instead of "single-purpose score capture workflow."

- timestamp: 2026-04-20T03:48:56+09:00
  checked: desktop/renderer-v2/src/ui/shell/AppShell.js, desktop/renderer-v2/src/app/App.js, and desktop/renderer-v2/src/features/roi/RoiScreen.js
  found: The mounted shell permanently includes top bar, process rail, stage pane, context lane, and status bar; the status bar always prints engine/source/session/pages telemetry; ROI still opens with a toolbar, candidate strip, stage, and status footer stacked inside the remaining stage column.
  implication: Even the best screen copy is framed by a persistent instrument panel, so the product keeps reading as a dashboarded machine workflow rather than a single-purpose desktop capture app.

## Resolution

root_cause:
  The Phase 06 implementation fixed the top-level vocabulary and base tokens, but it did not replace the underlying visual grammar. The shipped renderer still composes every step inside a control-panel shell: thick persistent rails plus top and bottom telemetry strips, repeated amber accent on pills/borders/progress badges, and high volumes of 10-11px support labels, mono/uppercase technical fragments, and status widgets. Because this chrome pattern repeats across Source, ROI, Export, and Review, the eye reads "system panel / AI workbench" before it reads "local score-capture tool."
fix:
  none - diagnosis only
verification:
  Confirmed by comparing the Phase 06 UI contract against the actual shell/layout/component/copy implementation and by matching the remaining human UAT failure to concrete code-level contradictions.
files_changed: []
