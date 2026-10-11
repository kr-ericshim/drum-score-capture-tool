# Codebase Concerns

**Analysis Date:** 2026-04-17
**Last Updated:** 2026-05-18

## Tech Debt

**Monolithic backend orchestration layer:**
- Issue: `backend/app/main.py` concentrates API routing, cache management, job scheduling, file-path validation, export staging, source probing, and YouTube cache coordination in one 1300+ line module.
- Files: `backend/app/main.py`, `backend/app/job_store.py`
- Impact: Small feature changes cut across unrelated concerns, raise merge-conflict risk, and make regressions hard to localize.
- Fix approach: Split route handlers from job orchestration, cache/services, and file-resolution helpers so unit boundaries match behavior boundaries.

**Legacy renderer stack retired:**
- Status: Mitigated 2026-05-18. `desktop/renderer/` and legacy-only desktop tests were removed, and `desktop/renderer-entry.js` resolves `renderer-v2/index.html` as the only product UI.
- Residual risk: Historic docs and old planning artifacts may still mention the retired renderer for context, but runtime and release verification now target renderer-v2 only.

**Regression fixtures are guarded against runtime cache coupling:**
- Status: Mitigated 2026-05-18. Current backend tests synthesize temporary job trees or use synthetic image data, and `backend/tests/test_fixture_isolation.py` now fails if future backend tests reference the runtime `backend/jobs` tree directly.
- Residual risk: Desktop renderer tests still contain sample display paths that look like `backend/jobs/...`, but they do not read runtime artifacts.

**Release validation still includes packaged source-text compatibility checks:**
- Status: Partially mitigated 2026-05-18. The validator now treats source-text checks as current-source vs packaged-source compatibility markers, while backend behavior is covered by unit tests and frozen-runtime smoke.
- Issue: Post-build validation still reads packaged Python source because release packages intentionally ship the backend source tree next to the frozen runtime.
- Files: `desktop/scripts/validate-packaged-release.js`, `backend/app/main.py`, `backend/app/pipeline/extract.py`
- Impact: Safe refactors are less likely to break on hardcoded strings now, but the package contract still depends on duplicated source files being shipped next to the frozen runtime.
- Fix approach: Decide whether packaged Python fallback remains supported, then replace source-package checks with packaged executable/API behavior checks and trim source-only files from release bundles.

## Known Bugs

**Cache clear/source-prepare race is fixed and covered:**
- Status: Fixed before 2026-05-18 and covered by `backend/tests/test_source_prepare_jobs.py`.
- Previous symptoms: Cache cleanup could delete `_preview_source` and `_preview_source_jobs` artifacts while a source-prepare job was still running, leaving stale in-memory status and missing files on disk.
- Files: `backend/app/main.py`, `backend/app/job_store.py`
- Current behavior: `/maintenance/clear-cache` returns `409` while capture/export or source-prepare jobs are active, clears both job stores when idle, and shares a maintenance lock with new capture/source-prepare job creation so cache deletion cannot interleave with new job persistence.

**Renderer-v2 CI/release coverage is now enforced:**
- Status: Fixed. CI and release workflows both run `npm run verify:renderer-v2`.
- Previous symptoms: Changes under `desktop/renderer-v2/src/` could merge without the workflow failing, even though renderer-v2 is the default UI path.
- Files: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `desktop/package.json`, `desktop/renderer-entry.js`

**Backend regression tests are isolated from ignored local artifacts:**
- Status: Mitigated 2026-05-18 by the fixture isolation guard and full backend-suite verification with `DRUMSHEET_JOBS_DIR` pointed at a fresh temporary directory.
- Files: `backend/tests/test_fixture_isolation.py`, `backend/tests/test_sheet_finalize.py`

## Security Considerations

**Unescaped HTML rendering in the Electron renderer:**
- Risk: Renderer-v2 still builds markup with template strings and writes it via `innerHTML`, so new dynamic fields must be escaped before interpolation.
- Files: `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/ui/shell/AppShell.js`, `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`, `desktop/renderer-v2/src/features/export/ExportScreen.js`, `desktop/preload.js`
- Current mitigation: `desktop/main.js` enables `contextIsolation` and disables `nodeIntegration`; active renderer-v2 surfaces use `escapeHtml` / `escapeAttr` or local escape helpers for user/backend-controlled values, with regression tests covering source, review, export, process rail, and profile rows.
- Recommendation: Keep adding focused escaping tests whenever a new dynamic renderer-v2 field is introduced.

**Session token leakage through query strings:**
- Status: Mitigated 2026-05-18 after legacy renderer retirement.
- Risk: Token-bearing URLs can leak through logs, browser history, and developer tools if future code reintroduces query-string auth.
- Files: `backend/app/main.py`, `desktop/renderer-v2/src/lib/api.js`, `desktop/preload.js`
- Current mitigation: Backend protected routes authenticate only through `X-DrumSheet-Token`; renderer-v2 preview images are fetched through `readJobAsset()` / header-authenticated fetch and rendered as `blob:` URLs; blob URLs are revoked on stale preview responses, preview replacement, and app destroy.
- Recommendation: Keep query-token rejection covered by backend tests and keep protected renderer-v2 assets behind header-authenticated fetches.

**Packaged app ships more backend surface than it executes:**
- Risk: Release packaging includes the backend source tree plus the frozen runtime, even though packaged launch uses the executable path when present.
- Files: `desktop/package.json`, `desktop/electron-builder.config.js`, `desktop/main.js`
- Current mitigation: `desktop/scripts/validate-packaged-release.js` checks that the frozen runtime exists, is at least as fresh as the backend source, `.venv` is absent, and packaged backend source-text compatibility markers match current source.
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
- Test coverage: Coverage exists and backend tests are guarded against direct runtime `backend/jobs` fixture reads.

**YouTube prepare and cache flow:**
- Files: `backend/app/pipeline/extract.py`, `backend/app/main.py`, `desktop/renderer-v2/src/features/source/sourceController.js`
- Why fragile: Downloader strategy fallback, cache reuse, progress reporting, Node runtime handoff, resolution gating, and stale-response handling are spread across backend and renderer code.
- Safe modification: Verify cache hit, cache reject, low-resolution reject, retry, and stale-poll scenarios together, not file-by-file.
- Test coverage: There are targeted unit tests, but no end-to-end packaged flow that exercises the actual Electron renderer against the backend prepare job path.

**Release packaging contract:**
- Files: `desktop/main.js`, `desktop/scripts/run-builder.js`, `desktop/scripts/validate-packaged-release.js`, `backend/scripts/build_frozen_backend.py`
- Why fragile: Runtime staging, backend executable discovery, ffmpeg staging, builder profiles, and validator assumptions all have to line up exactly across Node and Python.
- Safe modification: Change one path contract at a time and update the validator in the same patch.
- Test coverage: Validation now includes runtime freshness, frozen backend `/health` smoke in release CI, renderer-v2 verification, and no-GUI Electron startup smoke; full packaged click-through remains manual.

## Scaling Limits

**Job execution capacity is effectively serialized:**
- Current capacity: `backend/app/main.py` allows 1 capture/export worker and 1 source-prepare worker via separate `ThreadPoolExecutor(max_workers=1)` instances.
- Limit: Additional jobs queue behind the current task, which increases wait time and makes the app feel stalled under repeated retries or batch use.
- Scaling path: Make concurrency explicit in the product model, or add configurable worker counts and queue visibility instead of silently serializing everything.

**Artifact retention remains partly manual after preview cleanup:**
- Current capacity: The app keeps outputs, source-prepare metadata, and exported review artifacts under `backend/jobs/` until `/maintenance/clear-cache` is called; preview-frame workspaces now have bounded request-triggered retention.
- Limit: Long-lived environments can still accumulate completed job outputs and source caches.
- Scaling path: Add explicit retention policy for completed exports and source caches, and keep runtime artifacts separate from tests.

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

**Packaged end-to-end renderer smoke remains manual:**
- Status: Partially mitigated 2026-05-18. Release automation now runs `npm run test:desktop-smoke`, which mocks Electron/backend startup and verifies renderer-v2 loading, isolated preload settings, IPC auth channels, and backend health polling.
- Remaining gap: It still does not install or launch the real packaged app and click through file selection -> ROI -> export.
- Files: `.github/workflows/release.yml`, `desktop/tests/main-startup-smoke.test.mjs`, `desktop/scripts/validate-packaged-release.js`, `desktop/main.js`, `desktop/preload.js`
- Blocks: Full confidence that packaged GUI behavior matches manual smoke expectations before shipping installers.

## Test Coverage Gaps

**Maintenance endpoints have focused regression coverage:**
- Status: Mitigated 2026-05-18. `/maintenance/clear-cache` is covered for active source-prepare blocking and creation serialization; `/maintenance/cache-usage` is covered for isolated job roots, recursive byte totals, disappearing files during scan, and a representative nested artifact tree.
- What's still not tested: Hard performance budgets for very large production artifact trees.
- Files: `backend/app/main.py`
- Risk: Future cache accounting or retention changes can still become slow at very large scale, but correctness regressions are now covered.
- Priority: Medium

**Renderer-v2 checks are part of GitHub workflows:**
- Status: Fixed. The renderer-v2 Node test suite and structural checks are part of CI and release workflows through `npm run verify:renderer-v2`.
- Files: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `desktop/package.json`, `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`
- Priority: Closed

**Renderer-v2 locale/syntax checks cover the active UI:**
- Status: Fixed. `npm run verify:renderer-v2` includes renderer-v2 tests, structural parsing, and `check:locale-init`.
- Files: `desktop/scripts/check-locale-init.js`, `desktop/package.json`, `desktop/renderer-v2/src/lib/i18n.js`
- Priority: Closed

**Security-sensitive rendering paths need continued escaping coverage:**
- Status: Partially mitigated. Renderer-v2 has focused escaping tests for several user/backend-controlled fields, including source, review, export, process rail, and processing-profile rows.
- What's still not exhaustively tested: Every future dynamic field rendered through template-string HTML.
- Files: `desktop/renderer-v2/src/app/App.js`, `desktop/renderer-v2/src/features/source/SourceScreen.js`, `desktop/renderer-v2/src/features/review/ReviewScreen.js`
- Risk: New unescaped template interpolations can still slip in without a test.
- Priority: Medium

**Windows release builds run the backend suite:**
- Status: Fixed 2026-05-18. The release workflow now runs backend `unittest` discovery on both Windows and macOS after installing `backend/requirements-build.txt`.
- Files: `.github/workflows/release.yml`, `backend/requirements-build.txt`, `backend/requirements.txt`, `backend/tests/`
- Residual risk: This catches Windows unit-level path/runtime regressions before packaging, but the real packaged Windows GUI flow still depends on frozen-backend smoke checks and manual installer smoke testing.
- Priority: Closed

---

*Concerns audit: 2026-04-17; remediation notes updated 2026-05-18*
