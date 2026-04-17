# Codebase Concerns

**Analysis Date:** 2026-04-17

## Tech Debt

**Monolithic backend orchestration layer:**
- Issue: `backend/app/main.py` concentrates API routing, cache management, job scheduling, file-path validation, export staging, source probing, and YouTube cache coordination in one 1300+ line module.
- Files: `backend/app/main.py`, `backend/app/job_store.py`
- Impact: Small feature changes cut across unrelated concerns, raise merge-conflict risk, and make regressions hard to localize.
- Fix approach: Split route handlers from job orchestration, cache/services, and file-resolution helpers so unit boundaries match behavior boundaries.

**Dual renderer stacks with duplicated workflow logic:**
- Issue: The app still carries the legacy renderer in `desktop/renderer/` while the default path resolves to `desktop/renderer-v2/index.html` when present.
- Files: `desktop/renderer-entry.js`, `desktop/renderer/app.js`, `desktop/renderer/modules/job-api.js`, `desktop/renderer/modules/i18n.js`, `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/lib/api.js`, `desktop/renderer-v2/src/lib/i18n.js`
- Impact: API contract, locale, and workflow fixes need to land in two UI implementations, which increases drift and doubles the regression surface.
- Fix approach: Either retire the legacy renderer or move shared client/state/i18n logic behind version-neutral modules with one contract.

**Regression fixtures are mixed into runtime cache paths:**
- Issue: backend regression tests read sample assets from `backend/jobs/<uuid>/...`, which is the same tree used for live job artifacts and preview caches.
- Files: `backend/tests/test_stitch_regression.py`, `backend/tests/test_sheet_finalize.py`, `backend/app/main.py`, `.gitignore`
- Impact: Test data is easy to delete with cache cleanup, hard to version safely, and tightly coupled to local workstation state instead of tracked fixtures.
- Fix approach: Move immutable samples into a versioned `backend/tests/fixtures/` tree and keep runtime cache directories disposable.

**Release validation is coupled to packaged source text:**
- Issue: post-build validation checks exact source strings inside packaged Python files instead of validating behavior through public interfaces.
- Files: `desktop/scripts/validate-packaged-release.js`, `backend/app/main.py`, `backend/app/pipeline/extract.py`
- Impact: Safe refactors can break release builds even when runtime behavior is still correct, and the package contract now depends on duplicated source files being shipped next to the frozen runtime.
- Fix approach: Validate the packaged executable and HTTP/API behavior directly, and remove source-text assertions that are only proxy signals.

## Known Bugs

**Cache clear can corrupt active YouTube prepare jobs:**
- Symptoms: Cache cleanup can delete `_preview_source` and `_preview_source_jobs` artifacts while a source-prepare job is still running, leaving stale in-memory status and missing files on disk.
- Files: `backend/app/main.py`, `backend/app/job_store.py`
- Trigger: Call `/maintenance/clear-cache` while `/preview/source-jobs` work created by `create_preview_source_job()` is active.
- Workaround: Do not run cache cleanup during YouTube prepare; restart the backend or desktop app if a prepare job becomes stuck after cleanup.

**Renderer-v2 regressions can bypass CI and release workflows:**
- Symptoms: Changes under `desktop/renderer-v2/src/` can merge without the workflow failing, even though renderer-v2 is the default UI path.
- Files: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `desktop/package.json`, `desktop/renderer-entry.js`
- Trigger: Modify renderer-v2 behavior without manually running `cd desktop && npm run verify:renderer-v2`.
- Workaround: Run `npm run verify:renderer-v2` locally before release or review.

**Backend regression tests depend on ignored local artifacts:**
- Symptoms: Clean clones or freshly provisioned CI environments do not have the required image fixtures, so tests that assert those files exist can fail immediately.
- Files: `backend/tests/test_stitch_regression.py`, `backend/tests/test_sheet_finalize.py`, `.gitignore`
- Trigger: Run the backend suite on a machine that does not already contain the ignored `backend/jobs/...` sample directories.
- Workaround: Preserve the local `backend/jobs/` fixture directories on developer machines until the samples are moved into tracked test fixtures.

## Security Considerations

**Unescaped HTML rendering in the Electron renderer:**
- Risk: Renderer-v2 builds markup with template strings and writes it via `innerHTML`, while interpolated values include file names, file paths, job messages, YouTube log lines, and backend error text.
- Files: `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/ui/shell/AppShell.js`, `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`, `desktop/renderer-v2/src/features/export/ExportScreen.js`, `desktop/preload.js`
- Current mitigation: `desktop/main.js` enables `contextIsolation` and disables `nodeIntegration`.
- Recommendations: Escape all dynamic strings before interpolation or stop using `innerHTML` for stateful renderer updates.

**Session token is accepted and emitted through query strings:**
- Risk: Protected asset URLs append `?token=...`, which increases exposure through logs, devtools, copied URLs, and any injected markup that can read rendered DOM.
- Files: `backend/app/main.py`, `desktop/renderer-v2/src/lib/api.js`, `desktop/renderer/modules/job-api.js`, `desktop/preload.js`
- Current mitigation: The token is random per launch and the backend binds to loopback by default through `backend/run.py`.
- Recommendations: Keep auth in headers only, or proxy asset reads through Electron IPC so renderer image/video requests do not need token-bearing URLs.

**Packaged app ships more backend surface than it executes:**
- Risk: Release packaging includes the backend source tree plus the frozen runtime, even though packaged launch uses the executable path when present.
- Files: `desktop/package.json`, `desktop/electron-builder.config.js`, `desktop/main.js`
- Current mitigation: `desktop/scripts/validate-packaged-release.js` checks that the frozen runtime exists and `.venv` is absent.
- Recommendations: Trim packaged backend contents to the runtime assets actually used by `desktop/main.js` and keep source-only files out of release bundles.

## Performance Bottlenecks

**Full job metadata is rewritten on every log and progress update:**
- Problem: Every call to `log()` or `set_state()` serializes the full job record back to `job.json`, including the growing `log` array.
- Files: `backend/app/job_store.py`, `backend/app/main.py`
- Cause: Persistence is synchronous and unbatched for both `JobStore` and `SourcePrepareStore`.
- Improvement path: Debounce disk writes, cap stored log history, and persist state snapshots separately from append-only logs.

**Export keeps full page sets in memory during finalization and PDF generation:**
- Problem: Export paths load all source images, finalized pages, and PIL PDF images into memory before writing outputs.
- Files: `backend/app/pipeline/export.py`, `backend/app/pipeline/sheet_finalize.py`
- Cause: `export_frames()` and `export_selected_pages()` fully materialize page lists instead of streaming page-by-page.
- Improvement path: Stream page transforms and PDF append operations, and avoid duplicating OpenCV and PIL copies when the page count grows.

**Cache accounting gets slower as artifact directories accumulate:**
- Problem: Cache usage and cleanup walk the entire jobs root on demand.
- Files: `backend/app/main.py`
- Cause: `_cache_usage_summary()` and `_path_size_bytes()` recurse through every file under `jobs_root`.
- Improvement path: Track artifact sizes incrementally or add retention limits so maintenance endpoints do not degrade with disk growth.

## Fragile Areas

**Stitch and page-finalize heuristics:**
- Files: `backend/app/pipeline/stitch.py`, `backend/app/pipeline/sheet_finalize.py`, `backend/app/pipeline/layout_profiles.py`
- Why fragile: The pipeline depends on many thresholded image heuristics such as overlap scoring, near-duplicate filtering, whitespace slicing, and page-turn detection.
- Safe modification: Treat threshold changes as regression-prone; add or refresh fixture-backed tests before altering overlap, dedupe, or page-fill behavior.
- Test coverage: Coverage exists, but it mixes synthetic images with local `backend/jobs/...` samples instead of a clean tracked fixture corpus.

**YouTube prepare and cache flow:**
- Files: `backend/app/pipeline/extract.py`, `backend/app/main.py`, `desktop/renderer-v2/src/features/source/sourceController.js`
- Why fragile: Downloader strategy fallback, cache reuse, progress reporting, Node runtime handoff, resolution gating, and stale-response handling are spread across backend and renderer code.
- Safe modification: Verify cache hit, cache reject, low-resolution reject, retry, and stale-poll scenarios together, not file-by-file.
- Test coverage: There are targeted unit tests, but no end-to-end packaged flow that exercises the actual Electron renderer against the backend prepare job path.

**Release packaging contract:**
- Files: `desktop/main.js`, `desktop/scripts/run-builder.js`, `desktop/scripts/validate-packaged-release.js`, `backend/scripts/build_frozen_backend.py`
- Why fragile: Runtime staging, backend executable discovery, ffmpeg staging, builder profiles, and validator assumptions all have to line up exactly across Node and Python.
- Safe modification: Change one path contract at a time and update the validator in the same patch.
- Test coverage: Validation is mostly file-presence and string-match based; there is no packaged UI smoke test in CI.

## Scaling Limits

**Job execution capacity is effectively serialized:**
- Current capacity: `backend/app/main.py` allows 1 capture/export worker and 1 source-prepare worker via separate `ThreadPoolExecutor(max_workers=1)` instances.
- Limit: Additional jobs queue behind the current task, which increases wait time and makes the app feel stalled under repeated retries or batch use.
- Scaling path: Make concurrency explicit in the product model, or add configurable worker counts and queue visibility instead of silently serializing everything.

**Artifact retention is unbounded until manual cleanup:**
- Current capacity: The app keeps outputs, preview caches, source-prepare metadata, and exported review artifacts under `backend/jobs/` until `/maintenance/clear-cache` is called.
- Limit: Long-lived environments accumulate disk usage and slow maintenance operations, while the same tree is also used by some regression tests.
- Scaling path: Separate test fixtures from runtime artifacts and add TTL, quota, or per-job cleanup policies.

## Dependencies at Risk

**Python runtime version is inconsistent across setup paths:**
- Risk: The desktop bootstrap asks for Python 3.11, GitHub workflows install Python 3.11, and HAT setup notes a Python 3.13 flow.
- Files: `desktop/main.js`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `backend/scripts/setup_hat_runtime.sh`
- Impact: Native package behavior and PyInstaller/HAT compatibility can drift by environment, especially for OpenCV, torch, and packaged runtime generation.
- Migration plan: Choose one supported Python baseline for development, CI, and release builds, then enforce it in docs and launcher checks.

**Python dependencies are broad and effectively floating:**
- Risk: `backend/requirements.txt` uses `>=` ranges and there is no committed lockfile or constraints file.
- Files: `backend/requirements.txt`
- Impact: `yt-dlp`, `fastapi`, `opencv-python-headless`, and related transitive dependencies can change behavior between environments and release dates.
- Migration plan: Add a locked or constrained Python dependency set for release and CI reproducibility.

**HAT setup depends on live upstream repositories and local patching:**
- Risk: The setup script clones third-party repos from GitHub and rewrites upstream files in place to make the current environment work.
- Files: `backend/scripts/setup_hat_runtime.sh`, `backend/scripts/enable_hat_env.sh`, `backend/app/pipeline/hat_runtime.py`
- Impact: Upstream repo changes can break setup unexpectedly, and the local patch sequence is hard to reproduce in clean or offline environments.
- Migration plan: Pin known-good commits or vendor a controlled dependency snapshot instead of patching moving upstream targets.

## Missing Critical Features

**No true resume or cancel for long-running work:**
- Problem: Restart recovery only converts running work to an error state; it does not resume capture jobs or YouTube prepare jobs.
- Files: `backend/app/job_store.py`, `backend/app/main.py`, `desktop/renderer-v2/src/app/App.js`
- Blocks: Reliable recovery for long downloads, long exports, and interrupted desktop sessions.

**No packaged end-to-end renderer smoke automation:**
- Problem: Release automation validates the backend executable and artifact metadata, but not the packaged Electron UI flow from file selection through export.
- Files: `.github/workflows/release.yml`, `desktop/scripts/validate-packaged-release.js`, `desktop/main.js`, `desktop/preload.js`
- Blocks: Confident detection of renderer/preload/backend integration regressions before shipping installers.

## Test Coverage Gaps

**Maintenance endpoints are untested:**
- What's not tested: `/maintenance/clear-cache` and `/maintenance/cache-usage`, including interactions with `_preview_source_jobs` and `_preview_source`.
- Files: `backend/app/main.py`
- Risk: The current cache-clear/source-prepare race can persist unnoticed, and future cleanup changes can silently break job persistence.
- Priority: High

**Renderer-v2 checks are not part of GitHub workflows:**
- What's not tested: The renderer-v2 Node test suite and structural checks in `desktop/renderer-v2/src/tests/` and `desktop/scripts/check-renderer-v2.js`.
- Files: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `desktop/package.json`, `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`
- Risk: The default UI can regress without CI or release blockers.
- Priority: High

**Legacy-only locale/syntax checks leave the active UI uncovered:**
- What's not tested: renderer-v2 locale bootstrap and syntax by the current release guard scripts.
- Files: `desktop/scripts/check-locale-init.js`, `desktop/package.json`, `desktop/renderer/modules/i18n.js`, `desktop/renderer-v2/src/lib/i18n.js`
- Risk: Locale or markup regressions in renderer-v2 can ship even when the legacy-only checks still pass.
- Priority: High

**Security-sensitive rendering paths have no escaping tests:**
- What's not tested: Malicious file names, YouTube URLs, backend error strings, and prepare logs rendered through template-string HTML.
- Files: `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`
- Risk: Markup breakage or injection issues can slip into packaged builds.
- Priority: High

**Windows release builds do not run the backend suite:**
- What's not tested: The backend test suite on the Windows runner that actually produces the Windows installer.
- Files: `.github/workflows/release.yml`
- Risk: Windows-only runtime or path issues can survive until manual smoke testing.
- Priority: Medium

---

*Concerns audit: 2026-04-17*
