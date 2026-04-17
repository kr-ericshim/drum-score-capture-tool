# Testing Patterns

**Analysis Date:** 2026-04-17

## Test Framework

**Runner:**
- Backend: Python `unittest` with discovery from `backend/tests/`. There is no `pytest.ini`, `tox.ini`, or `setup.cfg` test configuration file.
- Desktop and renderer-v2: Node's built-in `node:test` runner via direct `node --test` commands and package scripts in `desktop/package.json` and `desktop/renderer-v2/package.json`.
- Structural verification: `desktop/scripts/check-renderer-v2.js` is not a `node:test` suite, but it is part of the required renderer-v2 verification path because `desktop/package.json` wires it into `npm run verify:renderer-v2`.
- Config: no `jest.config.*` or `vitest.config.*` detected. Test invocation lives in package scripts and command-line usage, not in a standalone config file.

**Assertion Library:**
- Backend: `unittest.TestCase` assertions plus `unittest.mock`.
- Desktop: `node:assert/strict`.

**Run Commands:**
```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_*.py'   # Backend suite
cd desktop && node --test tests/*.test.mjs tests/*.test.cjs renderer-v2/src/tests/*.test.js   # All Node suites
cd desktop && npm run verify:renderer-v2   # Renderer-v2 tests + structural contract checks
# Watch mode: Not configured
# Coverage: Not configured
```

## Test Inventory

- Current backend inventory: 17 test files under `backend/tests/`.
- Current desktop inventory: 7 test files under `desktop/tests/`.
- Current renderer-v2 inventory: 13 test files under `desktop/renderer-v2/src/tests/`.

Representative backend files:
- `backend/tests/test_review_export.py`
- `backend/tests/test_job_api_contract.py`
- `backend/tests/test_source_prepare_jobs.py`
- `backend/tests/test_youtube_download.py`
- `backend/tests/test_job_store_persistence.py`

Representative desktop files:
- `desktop/tests/preload-auth.test.mjs`
- `desktop/tests/status-ui.test.mjs`
- `desktop/tests/workflow-shell.test.mjs`
- `desktop/tests/validate-packaged-release.test.mjs`

Representative renderer-v2 files:
- `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`
- `desktop/renderer-v2/src/tests/source-controller.test.js`
- `desktop/renderer-v2/src/tests/source-screen.test.js`
- `desktop/renderer-v2/src/tests/session-selectors.test.js`
- `desktop/renderer-v2/src/tests/stitch-fidelity.test.js`

## Test File Organization

**Location:**
- Backend tests live in a dedicated `backend/tests/` folder and import production code through `PYTHONPATH=backend`.
- Electron shell and packaging tests live in `desktop/tests/`.
- Renderer-v2 tests are colocated with the rewrite under `desktop/renderer-v2/src/tests/`.

**Naming:**
- Backend: `backend/tests/test_*.py`
- Desktop Node tests: `desktop/tests/*.test.mjs` and `desktop/tests/*.test.cjs`
- Renderer-v2: `desktop/renderer-v2/src/tests/*.test.js`

**Structure:**
```text
backend/tests/
  test_api_auth.py
  test_job_api_contract.py
  test_review_export.py
  test_source_prepare_jobs.py
  ...

desktop/tests/
  build-profile-policy.test.mjs
  preload-auth.test.mjs
  renderer-entry.test.cjs
  status-ui.test.mjs
  validate-packaged-release.test.mjs
  workflow-shell.test.mjs

desktop/renderer-v2/src/tests/
  api.test.js
  app-runtime-flows.test.js
  context-lane.test.js
  export-screen.test.js
  review-screen.test.js
  session-selectors.test.js
  source-controller.test.js
  source-screen.test.js
  stitch-fidelity.test.js
  ...
```

## Test Structure

**Suite Organization:**

Backend pattern from `backend/tests/test_job_store_persistence.py` and `backend/tests/test_review_export.py`:

```python
class TestJobStorePersistence(unittest.TestCase):
    def test_reload_restores_completed_job_from_disk(self):
        with tempfile.TemporaryDirectory() as td:
            ...
            reloaded = JobStore(jobs_root)
            job = reloaded.get("job-1")
            self.assertEqual(job.status, JobStatus.DONE)
```

Renderer-v2 pattern from `desktop/renderer-v2/src/tests/source-controller.test.js`:

```javascript
test("controller promotes a completed youtube prepare snapshot into canonical file state", async () => {
  const { store, controller } = createController();
  ...
  await controller.completeYoutubePrepare(snapshot, requestToken);
  assert.equal(store.getState().ui.activeStep, "roi");
});
```

**Patterns:**
- Backend setup is usually local to each test method. Use `tempfile.TemporaryDirectory()` and create minimal artifact trees with `Path` objects inside the test body.
- Backend teardown is mostly automatic through context managers. There is very little `setUp`/`tearDown`; the notable exception is local reset logic like `FakeYoutubeDL.plans = []` in `backend/tests/test_youtube_download.py`.
- Renderer-v2 tests prefer small helper functions inside each file, such as `createController` in `desktop/renderer-v2/src/tests/source-controller.test.js`, `createReviewState` in `desktop/renderer-v2/src/tests/review-screen.test.js`, and `createRoot` plus `installBrowserStubs` in `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`.
- Node-side cleanup is explicit. Tests that monkeypatch globals restore them in `finally` blocks, as shown in `desktop/renderer-v2/src/tests/api.test.js` and `desktop/tests/preload-auth.test.mjs`.
- Assertion style is direct and specific: equality checks for state transitions, regex checks for rendered markup, and explicit status code/detail assertions for backend failures.

## Mocking

**Framework:** `unittest.mock.patch` / `patch.object` on Python side, manual stubs plus monkeypatching globals or dependency injection on Node side

**Patterns:**

Backend example from `backend/tests/test_source_prepare_jobs.py`:

```python
with patch.object(main, "source_prepare_store", store), patch.object(
    main,
    "_get_or_prepare_cached_youtube_video",
    side_effect=fake_prepare,
):
    main._run_source_prepare_job("prepare-4")
```

Desktop example from `desktop/renderer-v2/src/tests/api.test.js`:

```javascript
globalThis.fetch = async (url, options) => {
  assert.match(String(url), /\/preview\/source$/);
  return {
    ok: true,
    async json() {
      return { video_path: "/tmp/cache/demo.mp4", from_cache: true };
    },
  };
};
```

Electron preload example from `desktop/tests/preload-auth.test.mjs`:

```javascript
Module._load = function patchedLoad(request, parent, isMain) {
  if (request === "electron") {
    return { contextBridge: ..., ipcRenderer: ... };
  }
  return originalLoad(request, parent, isMain);
};
```

**What to Mock:**
- Backend external boundaries: `YoutubeDL`, ffmpeg probing helpers, `subprocess.run`, background executors, `job_store`, and pipeline functions like `stitch_pages` or `export_selected_pages`.
- Desktop HTTP and Electron boundaries: `fetch`, `window.drumSheetAPI`, `document`, `navigator`, `Module._load`, and any file-system or packaging probes in build scripts.
- Renderer-v2 application boundaries: pass injected `api`, `bridge`, or `readVideoMetadata` implementations into `createApp` rather than mocking deep internals.

**What NOT to Mock:**
- Pure selectors and renderers. Existing tests call `getStepState`, `deriveCapturePages`, `renderSourceScreen`, `renderExportScreen`, and `renderReviewScreen` directly in `desktop/renderer-v2/src/tests/session-selectors.test.js`, `source-screen.test.js`, `export-screen.test.js`, and `review-screen.test.js`.
- `JobStore` persistence logic. `backend/tests/test_job_store_persistence.py` exercises the real `JobStore` against temporary directories instead of mocking persistence.
- State-transition helpers such as `createSourceController` and `createRuntimeGuards` should usually be exercised with stubbed dependencies but real state objects.

## Fixtures and Factories

**Test Data:**

Python fake object pattern from `backend/tests/test_youtube_download.py`:

```python
class FakeYoutubeDL:
    plans = []
    seen_opts = []
    ...
```

Renderer-v2 harness pattern from `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`:

```javascript
function createRoot() {
  const listeners = { click: [], input: [] };
  const nodes = { "#topBar": { innerHTML: "" }, "#stagePane": { innerHTML: "" }, ... };
  return { querySelector(selector) { return nodes[selector] || null; }, ... };
}
```

Renderer-v2 focused state factory from `desktop/renderer-v2/src/tests/review-screen.test.js`:

```javascript
function createReviewState() {
  const state = createInitialSessionState();
  state.review.pages = [{ id: "1", title: "페이지 1", ... }];
  return state;
}
```

**Location:**
- No shared fixture directory is used.
- Fake classes, state factories, DOM harnesses, and deferred promise helpers are defined inline within the test file that needs them.
- Synthetic images are created inside temporary directories for backend image pipeline tests such as `backend/tests/test_capture_crop.py`, `backend/tests/test_review_export.py`, and `backend/tests/test_stitch_regression.py`.

## Coverage

**Requirements:** None enforced

**View Coverage:**
```bash
# Coverage toolchain not configured
# No c8, nyc, coverage.py, or threshold config detected
```

- There is no automated coverage report command in `desktop/package.json`, `desktop/renderer-v2/package.json`, or backend config files.
- Treat missing coverage data as a real gap when planning risky changes.

## Test Types

**Unit Tests:**
- Backend pure/helper coverage includes validation, layout, ROI health, and youtube download helper behavior in files such as `backend/tests/test_source_validation.py`, `backend/tests/test_layout_profiles.py`, `backend/tests/test_extract_preview_frame.py`, and `backend/tests/test_youtube_download.py`.
- Renderer-v2 unit tests cover selectors, renderers, locale helpers, and controller behavior in `desktop/renderer-v2/src/tests/session-selectors.test.js`, `source-screen.test.js`, `export-screen.test.js`, `review-screen.test.js`, `i18n.test.js`, and `source-controller.test.js`.
- Legacy desktop unit tests cover narrow modules like `desktop/tests/status-ui.test.mjs`, `desktop/tests/job-api-auth.test.mjs`, and `desktop/tests/build-profile-policy.test.mjs`.

**Integration Tests:**
- Backend integration-style tests assemble realistic job folders and real `JobStore` instances, then patch only outer services. See `backend/tests/test_review_export.py`, `backend/tests/test_job_api_contract.py`, `backend/tests/test_source_prepare_jobs.py`, and `backend/tests/test_preview_source_cache.py`.
- Renderer-v2 flow tests use a multi-module harness around `createApp` in `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`. These tests validate state transitions, race handling, and UI status propagation across controller, selector, and render layers.
- Packaging/build contract tests validate desktop release logic without building the full app. See `desktop/tests/renderer-entry.test.cjs`, `desktop/tests/preload-auth.test.mjs`, and `desktop/tests/validate-packaged-release.test.mjs`.

**E2E Tests:**
- Not used.
- No Playwright, Cypress, Selenium, or real Electron UI automation was detected.
- No FastAPI `TestClient` or HTTP-level ASGI tests were detected.

## Common Patterns

**Async Testing:**

Renderer-v2 race-control pattern from `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` and `source-controller.test.js`:

```javascript
function deferred() {
  let resolve = () => {};
  let reject = () => {};
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
```

- Use deferred promises when validating stale-response handling, cancellation by version token, or multi-step async UI flows.
- `await` test bodies are normal for renderer-v2 API/controller tests. Use small `flush()` helpers when the code under test schedules microtasks, as done in `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`.

**Error Testing:**

Backend error pattern from `backend/tests/test_job_api_contract.py`:

```python
with self.assertRaises(HTTPException) as error:
    review_export(...)
self.assertEqual(error.exception.status_code, 409)
self.assertEqual(error.exception.detail, "job must be completed successfully before review export")
```

Desktop error/contract pattern from `desktop/tests/validate-packaged-release.test.mjs`:

```javascript
assert.throws(
  () => validator.assertRuntimeContract(...),
  /frozen backend runtime/i,
);
```

- Backend tests assert both exception type and exact `status_code`/`detail` strings.
- Renderer-v2 tests commonly use `assert.match` and `assert.doesNotMatch` against rendered HTML to lock down real UI copy, accessibility attributes, and the removal of deprecated controls.
- Accessibility contracts are treated as first-class test targets. Examples include `aria-describedby`, `aria-current`, `aria-valuenow`, and checkbox `aria-label` assertions in `desktop/renderer-v2/src/tests/source-screen.test.js`, `process-rail.test.js`, `export-screen.test.js`, and `review-screen.test.js`.

## Testing Gaps

- No backend HTTP-level API suite exists. `backend/tests/test_api_auth.py` and `backend/tests/test_source_validation.py` call helper functions directly, but there is no `TestClient` coverage for middleware, response models, CORS behavior, or route wiring in `backend/app/main.py`.
- No browser-level or Electron window-level E2E coverage exists. Renderer-v2 tests stub `window`, `document`, and root nodes in files like `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`, so real DOM layout, CSS behavior, and event behavior inside Chromium are not exercised.
- Coverage metrics are not measured or enforced. Large orchestrators such as `backend/app/main.py` and `desktop/renderer-v2/src/app/App.js` have meaningful test coverage around selected flows, but there is no quantitative guardrail for untested branches.
- Legacy renderer coverage is selective. `desktop/tests/` covers entry, preload, auth headers, status rendering, workflow shell, and packaging, but modules such as `desktop/renderer/modules/roi-controller.js`, `desktop/renderer/modules/video-range-picker.js`, and `desktop/renderer/modules/runtime-status-ui.js` have no direct dedicated tests.
- Full external-tool integration is mostly mocked. Backend tests patch `YoutubeDL`, ffmpeg helpers, and pipeline functions rather than running a real end-to-end capture job from source ingest through export. Use extra manual verification when changing `backend/app/pipeline/extract.py`, `backend/app/pipeline/upscale.py`, or packaged runtime behavior.

---

*Testing analysis: 2026-04-17*
