---
status: resolved
trigger: "You are diagnosing the Score Capture Program in /Users/ericshim/Documents/myproject/score_capture_program. Scope: Source selection + YouTube prepare + archive re-entry + transition into ROI in renderer-v2. This is diagnose-only; do not edit files. Find concrete bug risks, incomplete implementations, race conditions, broken assumptions, and user-flow dead ends. Focus on actual flow truth, not generic advice. Prioritize issues that can happen when a user follows the real app flow. Read at minimum: .planning/PROJECT.md, .planning/codebase/ARCHITECTURE.md, desktop/renderer-v2/src/app/App.js, desktop/renderer-v2/src/features/source/SourceScreen.js, desktop/renderer-v2/src/features/source/sourceController.js, desktop/renderer-v2/src/app/session/runtimeSafety.js, desktop/renderer-v2/src/lib/api.js, desktop/renderer-v2/src/tests/source-controller.test.js, desktop/renderer-v2/src/tests/source-screen.test.js, desktop/renderer-v2/src/tests/app-runtime-flows.test.js, backend/tests/test_source_prepare_jobs.py, backend/tests/test_preview_source_cache.py, backend/tests/test_local_media_registry.py. Return only concrete findings with severity, exact file refs, why it can happen, and whether tests already cover it. Use marker '## DEBUG COMPLETE'."
created: 2026-04-19T21:02:54+09:00
updated: 2026-04-19T21:08:40+09:00
---

## Current Focus

hypothesis: Multiple flow-contract gaps are real: YouTube prepare does not reset the previous source session, archive is browse-only rather than a re-entry path, and registry reload strips source identity/title metadata.
test: Compare App/source-controller/runtime-guard transitions against archive/local-media API contracts and requested tests, then confirm suspicious state transitions with a direct in-memory reproduction.
expecting: Evidence that users can remain on stale ROI/export paths during prepare, cannot re-enter ROI from archive, and lose YouTube/archive identity when reopening persisted media.
next_action: Return severity-ranked diagnose-only findings with exact refs and note which tests cover only happy paths.

## Symptoms

expected: A user can pick a source, prepare a YouTube source, re-enter from archived/persisted media, and move into ROI with correct state, recoverable errors, and no dead-end transitions.
actual: Diagnose-only audit requested for likely failures, broken assumptions, races, and incomplete coverage in that renderer-v2 flow.
errors:
reproduction: Open renderer-v2 and follow source selection -> prepare YouTube source or archive/local-media re-entry -> continue into ROI.
started: Investigation requested on 2026-04-19.

## Eliminated

## Evidence

- timestamp: 2026-04-19T21:05:00+09:00
  checked: required docs and flow code (.planning/PROJECT.md, ARCHITECTURE.md, App.js, SourceScreen.js, sourceController.js, runtimeSafety.js, api.js)
  found: renderer-v2 is the active source -> ROI -> export -> review UI, source/ROI/export/review accessibility is derived from in-memory session state, and archive/local-media are separate backend-fed surfaces.
  implication: flow bugs must be evaluated as state-transition bugs in the renderer, not as legacy-renderer issues.

- timestamp: 2026-04-19T21:06:10+09:00
  checked: source prepare start path in sourceController.js and App.js
  found: startYoutubePrepare() switches prepare status to loading but does not clear source.filePath/metadata or downstream ROI/export/review state, and prepareYoutubeSource() begins only a source-prepare guard without bumping the source session or stopping export polling.
  implication: a user can start YouTube prepare while the previous source session remains active and stale preview/export work can still mutate state during the prepare run.

- timestamp: 2026-04-19T21:06:40+09:00
  checked: direct js_repl reproduction using createSourceController + getAccessibleSteps
  found: after startYoutubePrepare(), state still had filePath=/tmp/old-source.mp4, exportJobId=job-old, reviewPages=1, and accessibleSteps=["source","roi","export","review"].
  implication: the stale-session risk is not theoretical; the current flow leaves the old capture/export path navigable while a new YouTube prepare is loading.

- timestamp: 2026-04-19T21:07:05+09:00
  checked: archive modal, App.js archive actions, backend archive schema/endpoint
  found: archive items expose only source_key/source_kind/display_name/pdf_path/output_dir; the modal supports select/open-pdf/open-folder only, and App.js has no action that loads an archive item back into source/ROI.
  implication: archive is a browse/open-files surface, so "archive re-entry into ROI" is currently an unimplemented dead end.

- timestamp: 2026-04-19T21:07:40+09:00
  checked: local-media registry API mapping, SourceScreen registry action payload, sourceController.selectLocalFile()
  found: registry items include sourceOrigin/youtubeUrl, but renderSourceScreen emits only data-file-path for load-registry-source and selectLocalFile() rewrites archiveSourceKind=file, archiveSourceKey=filePath, archiveDisplayName=basename.
  implication: reopening persisted prepared YouTube media loses the original source identity/title and future exports/archive grouping fall back to cache filenames and file-path keys.

## Resolution

root_cause: renderer-v2 has three concrete diagnose-only flow gaps in the requested scope: stale prior-session state survives YouTube prepare start, archive has no ROI re-entry path, and persisted-media reload strips original source identity.
fix:
verification: Read the requested implementation/tests end-to-end and confirmed the stale-session behavior with a direct in-memory reproduction using the real source controller/selectors.
files_changed: []
