---
status: resolved
trigger: "You are diagnosing the Score Capture Program in /Users/ericshim/Documents/myproject/score_capture_program. Scope: backend job orchestration, persistence, source preparation, pipeline/export contracts, restart behavior, and filesystem truth across the whole flow. Diagnose only; do not edit. Find concrete backend-side failure modes or incomplete implementation seams that the frontend may not reveal immediately. Read at minimum: .planning/codebase/ARCHITECTURE.md, backend/app/main.py, backend/app/job_store.py, backend/app/schemas.py, backend/app/pipeline/extract.py, backend/app/pipeline/export.py, backend/tests/test_job_store_persistence.py, backend/tests/test_source_prepare_jobs.py, backend/tests/test_job_api_contract.py, backend/tests/test_review_export.py, backend/tests/test_review_export_refinalization.py, backend/tests/test_sheet_finalize.py, backend/tests/test_archive_library.py. Return only concrete findings with severity, exact file refs, reproduction path, and current test blind spots. Use marker '## DEBUG COMPLETE'."
created: 2026-04-19T12:03:06Z
updated: 2026-04-19T12:24:30Z
---

## Current Focus

hypothesis: Multiple backend-only seams are present around YouTube cache-miss handling, maintenance cache clearing, transient preview workspace cleanup, and registry hydration for direct YouTube jobs.
test: Confirm each suspected seam with direct code-path experiments and then collect exact file/line references plus the adjacent tests that fail to cover it.
expecting: Reproducible failures where runtime behavior diverges from filesystem truth or supported API contracts even though the current targeted test suite passes.
next_action: Collect exact line references for the confirmed failure modes and map each one to the current missing test coverage.

## Symptoms

expected: Backend orchestration, persistence, source preparation, export/finalization, restart behavior, and filesystem-backed truth remain correct across the full job lifecycle.
actual: Unknown; this session is auditing for hidden backend-side failure modes and incomplete seams that may not be visible in the frontend.
errors: None provided; investigation is evidence-driven from code and tests.
reproduction: Inspect backend lifecycle code and targeted tests, then derive concrete reproduction paths for uncovered or inconsistent states.
started: Not specified; proactive diagnosis request.

## Eliminated

## Evidence

- timestamp: 2026-04-19T12:14:00Z
  checked: Required architecture/backend/test files plus targeted backend unittest suite
  found: `.planning/codebase/ARCHITECTURE.md`, the required backend files, and the named backend tests were read completely; `PYTHONPATH=backend backend/.venv/bin/python -m unittest ...` ran 43 tests and all passed.
  implication: Current targeted regression coverage is green, so findings need to come from uncovered lifecycle seams rather than already-failing tests.

- timestamp: 2026-04-19T12:18:00Z
  checked: `backend/app/pipeline/extract.py` YouTube hook definitions and direct hook invocation with `progress_callback=None`
  found: `_build_youtube_progress_hook(progress_callback=None, ...)` and `_build_youtube_postprocessor_hook(progress_callback=None, ...)` both raise `TypeError: 'NoneType' object is not callable`.
  implication: Any YouTube cache-miss path that uses `_download_youtube()` without a progress callback can fail during yt-dlp progress/postprocess events.

- timestamp: 2026-04-19T12:20:00Z
  checked: `backend/app/main.py` maintenance clear-cache flow with a running `SourcePrepareJob`
  found: `clear_cache()` completed with `cleared_paths 1`, `cleared_jobs 0`, `prepare_job_still_in_memory True`, and `prepare_root_exists False`.
  implication: Cache clearing neither blocks on running source-prepare jobs nor clears their in-memory store, so backend state can point at deleted filesystem artifacts.

- timestamp: 2026-04-19T12:21:00Z
  checked: `backend/app/main.py` completed prepare-job lookup before and after `clear_cache()`
  found: `get_preview_source_job('source-1')` returned `status=done` both before and after cache clear, but the returned `video_path` no longer existed on disk after cache clear.
  implication: The preview-source job API can serve ghost success records after maintenance has deleted the underlying files.

- timestamp: 2026-04-19T12:22:00Z
  checked: `preview_frame()` and `preview_roi_health()` with patched workers and temp jobs root
  found: Both endpoints leave `_preview/<uuid>` or `_preview_health/<uuid>` directories on disk after returning successfully.
  implication: Transient preview requests leak per-request workspaces and grow the jobs directory over time.

- timestamp: 2026-04-19T12:23:00Z
  checked: `local_media_registry()` with a completed direct YouTube capture job (`source_type='youtube'`, `file_path=None`) and no prepare-job companion
  found: The registry returned `items 0` even though the job had a completed export PDF and normalized YouTube source identity.
  implication: The local-media registry only hydrates completed jobs that have a local `file_path`, so direct YouTube capture jobs disappear from that library surface.

## Resolution

root_cause: Backend lifecycle code had several uncovered seams around optional YouTube progress callbacks, cache-clear/source-prepare synchronization, transient preview workspace retention, and direct YouTube job hydration into the media registry.
fix: Current code now tolerates missing YouTube progress callbacks, blocks cache clear while capture/export or source-prepare jobs are active, serializes cache deletion with new capture/source-prepare job creation, clears both job stores when idle, hydrates direct YouTube jobs through cached/source result paths, deletes ROI-health temp workspaces immediately, and bounds preview-frame workspaces with request-triggered count plus TTL pruning so returned preview images remain loadable.
verification: Current verification on 2026-05-18 passed the full backend suite with `DRUMSHEET_JOBS_DIR` pointed at a fresh temporary directory, plus targeted preview/source/cache/local-media tests and renderer-v2 verification. Cache-clear coverage includes both already-running source-prepare jobs and the concurrent create-during-clear interleaving.
files_changed:
  - backend/app/main.py
  - backend/app/pipeline/extract.py
  - backend/tests/test_youtube_download.py
  - backend/tests/test_source_prepare_jobs.py
  - backend/tests/test_local_media_registry.py
  - backend/tests/test_extract_preview_frame.py
  - backend/tests/test_fixture_isolation.py
  - desktop/renderer-entry.js
  - desktop/tests/renderer-entry.test.cjs
