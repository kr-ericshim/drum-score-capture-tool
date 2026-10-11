---
status: investigating
trigger: "You are diagnosing the Score Capture Program in /Users/ericshim/Documents/myproject/score_capture_program. Scope: cross-cutting shell/runtime/legacy-fallback/verification gaps after recent parallel implementation. Diagnose only; do not edit. Find places where flows are partially wired, tests give false confidence, main shell state disagrees with screen state, or renderer-v2 and fallback/packaged behavior can diverge. Read at minimum: desktop/main.js, desktop/preload.js, desktop/renderer-entry.js, desktop/tests/workflow-shell.test.mjs, desktop/tests/renderer-entry.test.cjs, desktop/tests/preload-auth.test.mjs, desktop/tests/validate-packaged-release.test.mjs, desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/ui/shell/AppShell.js, desktop/renderer-v2/src/ui/shell/ProcessRail.js, desktop/renderer-v2/src/ui/shell/ContextLane.js, desktop/renderer-v2/src/tests/process-rail.test.js, desktop/renderer-v2/src/tests/context-lane.test.js, README.md. Return only concrete findings with severity, exact file refs, why user-visible behavior can drift, and which gaps are not covered by current verification. Use marker '## DEBUG COMPLETE'."
created: 2026-04-19T00:00:00+09:00
updated: 2026-04-19T00:26:00+09:00
---

## Current Focus

hypothesis: Confirmed: renderer-v2 currently proves the happy-path workflow but not the shared shell/runtime contract. Recovery controls are legacy-only, backend state is collapsed in renderer-v2 chrome, and packaged validation can silently pass while the app falls back to legacy.
test: Verified by code comparison and passing test runs (`npm run verify:renderer-v2`, targeted preload/package tests) while the searched test surface contains no coverage for setup/restart/always-on-top/main IPC seams.
expecting: Return diagnosis-only findings with exact refs and verification gaps.
next_action: Return concrete findings ordered by severity.

## Symptoms

expected: Shell state, screen state, preload bridges, renderer-v2, fallback renderer, and packaged release behavior should present one consistent workflow truth.
actual: Recent parallel implementation may have left partially wired flows, mismatched shell and screen state, and verification that does not exercise real packaged/fallback behavior end to end.
errors: None provided; investigation is scoped to drift and false-confidence risks.
reproduction: Compare runtime wiring in desktop main/preload/entry and renderer-v2 shell components against current tests and packaged validation.
started: After recent parallel implementation.

## Eliminated

## Evidence

- timestamp: 2026-04-19T00:08:00+09:00
  checked: README.md, desktop/renderer-entry.js, desktop/tests/renderer-entry.test.cjs, memory quick pass
  found: README declares dist:release as the recommended public build while renderer-entry tests only prove path selection and memory notes confirm renderer-v2 is the active default with legacy as fallback.
  implication: Entry selection is covered only as a filesystem preference decision, not as a real packaged runtime parity check across renderer-v2 and legacy surfaces.

- timestamp: 2026-04-19T00:18:00+09:00
  checked: desktop/preload.js, desktop/renderer-v2/src/app/bridge.js, desktop/renderer-v2/src/app/App.js, desktop/renderer/app.js
  found: preload exposes restart/setup/setup-log/setup-state/always-on-top hooks, legacy renderer consumes setup/backend events and recovery controls, but renderer-v2 bridge forwards only select/open/copy/backend-state and App.js never handles repair actions or setup logs.
  implication: Recovery and shell-control flows are only partially wired in renderer-v2, so the same main-process state can be actionable in legacy fallback but invisible or unreachable in renderer-v2.

- timestamp: 2026-04-19T00:18:00+09:00
  checked: desktop/main.js, desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/ui/shell/ProcessRail.js
  found: main emits backend state with ready, starting, running, error, setupRunning, and platform, while renderer-v2 status chrome derives user-facing engine state from ready alone.
  implication: Renderer-v2 can show generic waiting/active labels even when the main process has a concrete backend error or setup-in-progress state.

- timestamp: 2026-04-19T00:18:00+09:00
  checked: desktop/scripts/validate-packaged-release.js, desktop/tests/validate-packaged-release.test.mjs, desktop/package.json, desktop/main.js
  found: packaged-release validation asserts backend/runtime/version files only; it never checks renderer-v2 asset presence or which renderer path main will load in packaged builds, and the associated test only covers helper functions.
  implication: A packaged build can silently fall back to legacy UI while release validation and renderer-v2 verification both stay green.

- timestamp: 2026-04-19T00:26:00+09:00
  checked: desktop/package.json, desktop/tests/preload-auth.test.mjs, desktop/tests/validate-packaged-release.test.mjs, desktop/tests/workflow-shell.test.mjs, desktop/renderer-v2/src/tests/process-rail.test.js, desktop/renderer-v2/src/tests/context-lane.test.js, desktop/renderer-v2/src/tests/app-runtime-flows.test.js, repo-wide test search
  found: verify:renderer-v2 passed, preload/package helper tests passed, and repo-wide test search returned no renderer-v2 or desktop test coverage for runGuidedSetup, restartBackend, onSetupState, onSetupLog, getAlwaysOnTop, setAlwaysOnTop, setupRunning, or backend error-state copy.
  implication: Current green verification gives strong confidence for renderer-v2 happy-path rendering but leaves main-process IPC, repair flows, and backend error-state UX effectively unverified.

## Resolution

root_cause:
  Cross-cutting shell/runtime parity is incomplete. The main process and preload expose richer backend/setup/window-control contracts than renderer-v2 consumes, renderer-v2 shell chrome reduces backend state to ready/wait, and packaged validation verifies backend payloads without proving renderer-v2 remains the shipped runtime instead of silently falling back to legacy.
fix:
verification:
files_changed: []
