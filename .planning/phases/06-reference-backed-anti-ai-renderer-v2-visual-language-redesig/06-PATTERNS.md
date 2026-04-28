# Phase 06: Reference-backed anti-AI renderer-v2 visual language redesign - Pattern Map

**Mapped:** 2026-04-19
**Files analyzed:** 18
**Analogs found:** 18 / 18

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `desktop/renderer-v2/src/styles/tokens.css` | design-token owner | visual contract | `desktop/renderer-v2/src/styles/tokens.css` | exact |
| `desktop/renderer-v2/src/styles/layout.css` | shell/layout owner | visual contract | `desktop/renderer-v2/src/styles/layout.css` | exact |
| `desktop/renderer-v2/src/styles/components.css` | shared component styling | visual contract | `desktop/renderer-v2/src/styles/components.css` | exact |
| `desktop/renderer-v2/src/ui/shell/AppShell.js` | shell landmark owner | event-driven | `desktop/renderer-v2/src/ui/shell/AppShell.js` | exact |
| `desktop/renderer-v2/src/ui/shell/TopBar.js` | shell header renderer | transform | `desktop/renderer-v2/src/ui/shell/TopBar.js` | exact |
| `desktop/renderer-v2/src/ui/shell/ProcessRail.js` | shell navigation renderer | transform | `desktop/renderer-v2/src/ui/shell/ProcessRail.js` | exact |
| `desktop/renderer-v2/src/ui/shell/ContextLane.js` | contextual inspector renderer | transform | `desktop/renderer-v2/src/ui/shell/ContextLane.js` | exact |
| `desktop/renderer-v2/src/app/App.js` | shell orchestration/controller | event-driven | `desktop/renderer-v2/src/app/App.js` | exact |
| `desktop/renderer-v2/src/app/session/selectors.js` | session summary/state helper | transform | `desktop/renderer-v2/src/app/session/selectors.js` | exact |
| `desktop/renderer-v2/src/features/source/SourceScreen.js` | source workspace renderer | transform | `desktop/renderer-v2/src/features/source/SourceScreen.js` | exact |
| `desktop/renderer-v2/src/features/roi/RoiScreen.js` | ROI workspace renderer | transform | `desktop/renderer-v2/src/features/roi/RoiScreen.js` | exact |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | export workspace renderer | transform | `desktop/renderer-v2/src/features/export/ExportScreen.js` | exact |
| `desktop/renderer-v2/src/features/review/ReviewScreen.js` | review workspace renderer | transform | `desktop/renderer-v2/src/features/review/ReviewScreen.js` | exact |
| `desktop/renderer-v2/src/lib/i18n.js` | copy registry | transform | `desktop/renderer-v2/src/lib/i18n.js` | exact |
| `desktop/renderer-v2/src/tests/stitch-fidelity.test.js` | screen-fidelity regression suite | transform | `desktop/renderer-v2/src/tests/stitch-fidelity.test.js` | exact |
| `desktop/renderer-v2/src/tests/process-rail.test.js` | shell-nav regression suite | transform | `desktop/renderer-v2/src/tests/process-rail.test.js` | exact |
| `desktop/renderer-v2/src/tests/context-lane.test.js` | inspector regression suite | transform | `desktop/renderer-v2/src/tests/context-lane.test.js` | exact |
| `desktop/scripts/check-renderer-v2.js` | structural contract guard | validation | `desktop/scripts/check-renderer-v2.js` | exact |

## Pattern Assignments

### Shell Landmarks Stay Stable, Meaning Changes

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/ui/shell/AppShell.js` | itself | The shell already has the correct landmark structure: top bar, process rail, stage pane, context lane, status bar. Phase 6 should change weight and semantics without breaking landmarks. |
| `desktop/renderer-v2/src/app/App.js` | itself | Shell visibility, stage routing, and lane rendering already flow through one controller. Contextual chrome changes should be orchestrated here instead of bolted into individual screens. |
| `desktop/scripts/check-renderer-v2.js` | itself | Structural guarantees for shell landmarks and high-level copy already live here and should absorb anti-AI guardrails. |

**Canonical shell seam** from `desktop/renderer-v2/src/ui/shell/AppShell.js`:

```js
export function mountShell(root) {
  root.innerHTML = `
    <main class="app-shell" data-shell="renderer-v2">
      <header id="topBar" class="topbar"></header>
      <section id="workspaceShell" class="workspace-shell">
        <aside id="processRail" class="process-rail" aria-label=""></aside>
        <section id="stagePane" class="stage-pane" tabindex="-1" role="region" aria-label=""></section>
        <aside id="contextLane" class="context-lane" aria-label=""></aside>
      </section>
      <footer id="statusBar" class="status-bar" role="status" aria-live="polite"></footer>
    </main>
  `;
}
```

**Pattern rule:** keep these landmarks intact. Phase 6 is a hierarchy reset, not a shell rewrite.

### Session-Orchestrated Copy And Step State

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/app/session/selectors.js` | itself | Step summaries, document header helpers, representative-frame candidates, and active-step labels already centralize renderer-v2 wording and state truth. |
| `desktop/renderer-v2/src/lib/i18n.js` | itself | All user-facing wording already flows through translation keys; Phase 6 copy changes should go here first, not as inline strings. |
| `desktop/renderer-v2/src/app/App.js` | itself | The runtime keeps export and ROI semantics honest here; Phase 6 must not reintroduce stale or misleading shell/state behavior. |

**Canonical state/copy seam** from `desktop/renderer-v2/src/app/session/selectors.js`:

```js
export function createInitialSessionState() {
  return {
    source: { ... },
    roi: { ... },
    exportConfig: createInitialExportConfig(),
    review: { ... },
    ui: { ... },
  };
}
```

**Pattern rule:** task language, active-step summaries, and first-action labels should continue to derive from centralized selectors/i18n instead of screen-local ad hoc strings.

### Screen Renderers Are HTML String Builders With Stable Regions

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/features/source/SourceScreen.js` | itself | The source workspace already separates ingest and registry regions; Phase 6 should rebalance emphasis, not invent a new structure. |
| `desktop/renderer-v2/src/features/roi/RoiScreen.js` | itself | The ROI screen already follows candidate strip + stage + footer action; Phase 6 should sharpen task-first hierarchy and avoid inspector relapse. |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | itself | Export already owns a strong preview-first split view and should be visually aligned, not structurally replaced. |
| `desktop/renderer-v2/src/features/review/ReviewScreen.js` | itself | Review already uses a grid-first curation workspace and should remain card/grid centric. |

**Canonical screen-region seam** from `desktop/renderer-v2/src/features/export/ExportScreen.js`:

```js
<div class="export-workbench">
  <div class="export-config-stack" data-stitch-region="export-config">...</div>
  <section class="export-preview-workbench" data-stitch-region="export-preview">...</section>
</div>
```

**Pattern rule:** preserve `data-stitch-region` landmarks and current screen responsibilities while changing emphasis, typography, copy, and shell competition.

### Shared CSS Is The Real House Style Lever

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/styles/tokens.css` | itself | The current monotone workbench feel starts here; palette and accent-budget reset belongs in tokens first. |
| `desktop/renderer-v2/src/styles/layout.css` | itself | Stage/rail/context spatial weight is encoded here. |
| `desktop/renderer-v2/src/styles/components.css` | itself | Top bar, rail, cards, buttons, labels, helper notes, and review cards all inherit the current tone from these selectors. |

**Canonical token seam** from `desktop/renderer-v2/src/styles/tokens.css`:

```css
:root {
  --bg-app: #17130f;
  --bg-shell: #1d1812;
  --bg-shell-alt: #241d15;
  --surface-paper: #f7f1e3;
  --accent: #e3b34d;
  --mono: ui-monospace, "SFMono-Regular", "JetBrains Mono", Consolas, monospace;
}
```

**Pattern rule:** start by rebalancing tokens and shared shell selectors before touching individual screens; otherwise the old tone bleeds back through every surface.

### Tests Already Encode Most Of The Shell Contract

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/tests/stitch-fidelity.test.js` | itself | Already asserts key render-path structure and anti-regression wording. |
| `desktop/renderer-v2/src/tests/process-rail.test.js` | itself | Already encodes rail/footer semantics and shell vocabulary constraints. |
| `desktop/renderer-v2/src/tests/context-lane.test.js` | itself | Already checks inspector semantics and English/Korean copy surfaces. |
| `desktop/tests/workflow-shell.test.mjs` | itself | Cross-screen step accessibility and shell behavior checks already live here. |

**Canonical guardrail seam** from `desktop/scripts/check-renderer-v2.js`:

```js
assert(appShell.includes('id="topBar"'), "renderer-v2 top bar landmark is missing.");
assert(processRail.includes('data-action="open-step"'), "renderer-v2 process rail step action is missing.");
assert(contextLane.includes("SOURCE SUMMARY") || contextLane.includes('t("lane.sourceSummary"'), "renderer-v2 context lane source summary is missing.");
```

**Pattern rule:** Phase 6 should extend these tests with anti-AI copy and hierarchy rules instead of relying on manual taste alone.

## Execution Guidance

- Prefer changing shared shell tone first, then shell semantics, then per-screen weighting, then regression harness.
- Do not create a new component system; reuse current HTML-string renderer modules and translation registry.
- When a plan touches copy, include `desktop/renderer-v2/src/lib/i18n.js` and the relevant test file together.
- When a plan touches layout weight, include `layout.css` plus the renderer module and a shell/screen regression test together.
