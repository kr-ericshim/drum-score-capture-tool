# Renderer V2 Locale And YouTube Source Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore whole-app Korean/English locale switching and YouTube URL source preparation in the default `renderer-v2` flow without regressing the existing local-file path.

**Architecture:** Add a small renderer-local i18n layer, thread locale through the session state and shell renderers, and extend the source step so YouTube preparation resolves to the same canonical local file path used by ROI/export/review. Keep backend contracts stable by reusing `/preview/source` and submitting file-backed jobs after preparation succeeds.

**Tech Stack:** Electron renderer ES modules, Node built-in test runner, existing preload bridge, existing FastAPI backend APIs

---

## File Structure

### New files

- `desktop/renderer-v2/src/lib/i18n.js`
  - Own locale detection, persistence, supported locales, translation lookup, and message formatting for `renderer-v2`.
- `desktop/renderer-v2/src/lib/messages.js`
  - Own locale-aware inline notices, validation copy, and quality-gate summary helpers so `App.js` does not accumulate string policy.
- `desktop/renderer-v2/src/features/source/sourceController.js`
  - Own YouTube/local source orchestration, stale-request rejection, and source-state reset rules so `App.js` stays on shell wiring.
- `desktop/renderer-v2/src/tests/i18n.test.js`
  - Guard locale detection, persistence fallback, and translation lookup behavior.
- `desktop/renderer-v2/src/tests/api.test.js`
  - Guard the `preparePreviewSource()` request/response mapping against the real API wrapper.
- `desktop/renderer-v2/src/tests/source-controller.test.js`
  - Guard source orchestration rules: success, failure, stale response rejection, low-quality mapping, and local-file takeover resets.

### Modified files

- `desktop/renderer-v2/src/app/App.js`
  - Initialize locale, handle locale switching, source-mode switching, YouTube prepare requests, and stale-response rejection.
- `desktop/renderer-v2/src/app/session/selectors.js`
  - Extend session state with locale and YouTube preparation fields, and route derived labels/blocking messages through translation helpers.
- `desktop/renderer-v2/src/lib/api.js`
  - Add preview-source preparation and generalize preview requests for source-aware use.
- `desktop/renderer-v2/src/features/source/SourceScreen.js`
  - Render local vs YouTube source controls, preparation status, logs, and quality-gate messaging.
- `desktop/renderer-v2/src/features/roi/RoiScreen.js`
  - Replace hard-coded strings with translation lookups.
- `desktop/renderer-v2/src/features/export/ExportScreen.js`
  - Replace hard-coded strings with translation lookups.
- `desktop/renderer-v2/src/features/review/ReviewScreen.js`
  - Replace hard-coded strings with translation lookups.
- `desktop/renderer-v2/src/ui/shell/ContextLane.js`
  - Render locale-aware source and review inspector surfaces.
- `desktop/renderer-v2/src/ui/shell/TopBar.js`
  - Add `KO/EN` controls and locale-aware shell labels.
- `desktop/renderer-v2/src/ui/shell/ProcessRail.js`
  - Render locale-aware step labels, summaries, and footer actions.
- `desktop/renderer-v2/src/tests/source-screen.test.js`
  - Cover dual-source rendering and YouTube preparation states.
- `desktop/renderer-v2/src/tests/session-selectors.test.js`
  - Cover extended source state and locale-aware blocking summaries.
- `desktop/renderer-v2/src/tests/process-rail.test.js`
  - Cover locale-aware shell output.
- `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`
  - Cover locale switching, YouTube prepare success/failure, stale request rejection, and local-file takeover after YouTube.

## Chunk 1: Locale Foundation And Shell Copy

### Task 1: Add renderer-v2 i18n foundation

**Files:**
- Create: `desktop/renderer-v2/src/lib/i18n.js`
- Test: `desktop/renderer-v2/src/tests/i18n.test.js`

- [ ] **Step 1: Write the failing i18n tests**

```js
import test from "node:test";
import assert from "node:assert/strict";

import { detectInitialLocale, persistLocale, t } from "../lib/i18n.js";

test("detectInitialLocale prefers saved locale over navigator language", () => {
  const locale = detectInitialLocale({
    storageValue: "en",
    navigatorLanguage: "ko-KR",
  });

  assert.equal(locale, "en");
});

test("t falls back to english when a key is missing in the active locale", () => {
  const text = t("source.prepareYoutube", { locale: "ko" });
  assert.equal(typeof text, "string");
  assert.notEqual(text, "");
});

test("persistLocale stores a supported locale and a fresh read uses it", () => {
  const storage = new Map();
  persistLocale("ko", {
    setItem(key, value) { storage.set(key, value); },
  });

  const locale = detectInitialLocale({
    storageValue: storage.get("drum-sheet-language"),
    navigatorLanguage: "en-US",
  });

  assert.equal(locale, "ko");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test desktop/renderer-v2/src/tests/i18n.test.js`

Expected: FAIL because `../lib/i18n.js` does not exist yet.

- [ ] **Step 3: Implement the i18n module**

```js
const LOCALE_STORAGE_KEY = "drum-sheet-language";
const SUPPORTED_LOCALES = ["ko", "en"];

export function detectInitialLocale({ storageValue, navigatorLanguage } = {}) {
  if (SUPPORTED_LOCALES.includes(storageValue)) return storageValue;
  return String(navigatorLanguage || "").toLowerCase().startsWith("ko") ? "ko" : "en";
}

export function persistLocale(locale, storage = globalThis.localStorage) {
  if (!SUPPORTED_LOCALES.includes(locale) || !storage?.setItem) return locale;
  storage.setItem(LOCALE_STORAGE_KEY, locale);
  return locale;
}

export function t(key, { locale = "en", replacements = {} } = {}) {
  const table = translations[locale] || translations.en;
  const fallback = translations.en[key] || key;
  return interpolate(table[key] || fallback, replacements);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test desktop/renderer-v2/src/tests/i18n.test.js`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/renderer-v2/src/lib/i18n.js desktop/renderer-v2/src/tests/i18n.test.js
git commit -m "feat: add renderer-v2 i18n foundation"
```

### Task 2: Thread locale through session state and top bar

**Files:**
- Modify: `desktop/renderer-v2/src/app/session/selectors.js`
- Modify: `desktop/renderer-v2/src/app/App.js`
- Modify: `desktop/renderer-v2/src/ui/shell/TopBar.js`
- Create: `desktop/renderer-v2/src/lib/messages.js`
- Test: `desktop/renderer-v2/src/tests/session-selectors.test.js`
- Test: `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

- [ ] **Step 1: Write the failing tests for locale state and top-bar toggling**

```js
test("initial session state includes a supported locale", () => {
  const state = createInitialSessionState();
  assert.match(state.ui.locale, /^(ko|en)$/);
});

test("locale toggle updates the top bar labels immediately", async () => {
  const app = createApp(root, { exposeTestApi: true });
  await root.dispatchAction("set-locale", { locale: "en" });
  assert.match(root.querySelector("#topBar").innerHTML, /PRECISION MEDIA WORKBENCH|Select Video/);
});

test("locale toggle writes the chosen locale and localizes inline notices", async () => {
  const app = createApp(root, { exposeTestApi: true });
  await root.dispatchAction("set-locale", { locale: "en" });
  await root.dispatchAction("copy-output-dir");
  assert.match(app.debug.getState().ui.inlineNotice, /path|missing|copy/i);
});
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `node --test desktop/renderer-v2/src/tests/session-selectors.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: FAIL because locale state and `set-locale` action handling do not exist.

- [ ] **Step 3: Implement locale state bootstrapping and top-bar controls**

```js
// selectors.js
ui: {
  locale: detectInitialLocale(),
  activeStep: "source",
  ...
}

// App.js
if (action === "set-locale") {
  const locale = persistLocale(target.dataset.locale);
  setState((next) => {
    next.ui.locale = locale;
    return next;
  });
}

// TopBar.js
<button data-action="set-locale" data-locale="ko">KO</button>
<button data-action="set-locale" data-locale="en">EN</button>

// messages.js
export function notice(key, { locale, replacements } = {}) {
  return t(`notice.${key}`, { locale, replacements });
}
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `node --test desktop/renderer-v2/src/tests/session-selectors.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/renderer-v2/src/app/session/selectors.js desktop/renderer-v2/src/app/App.js desktop/renderer-v2/src/ui/shell/TopBar.js desktop/renderer-v2/src/lib/messages.js desktop/renderer-v2/src/tests/session-selectors.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js
git commit -m "feat: add locale state and top bar controls"
```

### Task 3: Localize renderer-v2 shell and screen copy

**Files:**
- Modify: `desktop/renderer-v2/src/features/source/SourceScreen.js`
- Modify: `desktop/renderer-v2/src/features/roi/RoiScreen.js`
- Modify: `desktop/renderer-v2/src/features/export/ExportScreen.js`
- Modify: `desktop/renderer-v2/src/features/review/ReviewScreen.js`
- Modify: `desktop/renderer-v2/src/ui/shell/ContextLane.js`
- Modify: `desktop/renderer-v2/src/ui/shell/ProcessRail.js`
- Test: `desktop/renderer-v2/src/tests/source-screen.test.js`
- Test: `desktop/renderer-v2/src/tests/process-rail.test.js`
- Test: `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

- [ ] **Step 1: Write the failing markup tests for locale-aware copy**

```js
test("source screen renders english helper copy when locale is en", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  const markup = renderSourceScreen(state);
  assert.match(markup, /YouTube URL|Browse|Choose/i);
});

test("process rail renders english review actions when locale is en", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "review";
  const markup = renderProcessRail(state, getProcessRailItems(state));
  assert.match(markup, /OPEN PDF|OUTPUT DIR/);
});

test("localized shell surfaces replace korean-only inspector copy", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "source";
  const markup = renderContextLane(state);
  assert.match(markup, /SOURCE SUMMARY|NEXT STEP/);
  assert.doesNotMatch(markup, /대표 프레임|먼저 로컬 영상을 선택합니다/);
});

test("app inline validation strings follow the active locale", async () => {
  const app = createApp(root, { exposeTestApi: true });
  app.debug.setState((next) => {
    next.ui.locale = "en";
    next.source.filePath = "/tmp/source.mp4";
    next.roi.appliedRect = [[0, 0], [10, 0], [10, 10], [0, 10]];
    next.exportConfig.formats = [];
    return next;
  });
  await root.dispatchAction("run-export");
  assert.match(app.debug.getState().exportConfig.error, /select at least one|format/i);
});
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `node --test desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/process-rail.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: FAIL because the renderers still emit hard-coded Korean copy and the app still emits Korean-only inline validation strings.

- [ ] **Step 3: Replace hard-coded strings with translation lookups**

```js
import { t } from "../../lib/i18n.js";

const locale = state.ui.locale;
const title = t("source.title", { locale });
const helper = t("source.helper", { locale });
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `node --test desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/process-rail.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/renderer-v2/src/features/source/SourceScreen.js desktop/renderer-v2/src/features/roi/RoiScreen.js desktop/renderer-v2/src/features/export/ExportScreen.js desktop/renderer-v2/src/features/review/ReviewScreen.js desktop/renderer-v2/src/ui/shell/ContextLane.js desktop/renderer-v2/src/ui/shell/ProcessRail.js desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/process-rail.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js
git commit -m "feat: localize renderer-v2 shell and screens"
```

## Chunk 2: YouTube Prepare Flow And Source State

### Task 4: Extend source state and source-step rendering for YouTube mode

**Files:**
- Modify: `desktop/renderer-v2/src/app/session/selectors.js`
- Modify: `desktop/renderer-v2/src/features/source/SourceScreen.js`
- Test: `desktop/renderer-v2/src/tests/source-screen.test.js`
- Test: `desktop/renderer-v2/src/tests/session-selectors.test.js`

- [ ] **Step 1: Write the failing tests for dual-source state and YouTube source UI**

```js
test("initial session state starts in file mode with empty youtube preparation state", () => {
  const state = createInitialSessionState();
  assert.equal(state.source.sourceType, "file");
  assert.equal(state.source.youtubeUrl, "");
  assert.equal(state.source.prepareStatus, "idle");
});

test("source screen renders youtube controls and preparation log region", () => {
  const state = createInitialSessionState();
  const markup = renderSourceScreen(state);
  assert.match(markup, /youtube|유튜브/i);
  assert.match(markup, /prepare|준비/i);
});
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `node --test desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/session-selectors.test.js`

Expected: FAIL because the source state and source screen are still file-only.

- [ ] **Step 3: Add source-mode and preparation state fields**

```js
source: {
  sourceType: "file",
  filePath: "",
  displayName: "",
  metadata: null,
  status: "idle",
  error: "",
  youtubeUrl: "",
  preparedFromYouTube: false,
  prepareStatus: "idle",
  prepareLogs: [],
  preparedVideoPath: "",
}
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `node --test desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/session-selectors.test.js`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/renderer-v2/src/app/session/selectors.js desktop/renderer-v2/src/features/source/SourceScreen.js desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/session-selectors.test.js
git commit -m "feat: add renderer-v2 youtube source state"
```

### Task 5: Add source preparation API wrapper

**Files:**
- Modify: `desktop/renderer-v2/src/lib/api.js`
- Create: `desktop/renderer-v2/src/tests/api.test.js`

- [ ] **Step 1: Write the failing API-flow tests**

```js
import { preparePreviewSource } from "../lib/api.js";

test("preparePreviewSource posts youtube payload and maps the backend response", async () => {
  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /\/preview\/source$/);
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), {
      source_type: "youtube",
      file_path: null,
      youtube_url: "https://youtu.be/demo",
    });
    return {
      ok: true,
      async json() {
        return {
          video_path: "/tmp/cache/demo.mp4",
          video_url: "/jobs-files/_preview/demo.mp4",
          from_cache: true,
          log_lines: ["youtube download saved: /tmp/cache/demo.mp4"],
        };
      },
    };
  };

  const result = await preparePreviewSource({
    sourceType: "youtube",
    youtubeUrl: "https://youtu.be/demo",
  });

  assert.equal(result.videoPath, "/tmp/cache/demo.mp4");
  assert.equal(result.fromCache, true);
  assert.equal(result.logLines.length, 1);
});
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `node --test desktop/renderer-v2/src/tests/api.test.js`

Expected: FAIL because `preparePreviewSource()` is not implemented.

- [ ] **Step 3: Implement `preparePreviewSource()` and source-aware preview helpers**

```js
export async function preparePreviewSource({ sourceType, filePath, youtubeUrl }) {
  const response = await fetch(`${resolveApiBase()}/preview/source`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      source_type: sourceType,
      file_path: filePath || null,
      youtube_url: youtubeUrl || null,
    }),
  });
  const data = await readJson(response, "소스를 준비하지 못했습니다.");
  return {
    videoPath: data.video_path,
    videoUrl: data.video_url ? authorizedPath(data.video_url) : "",
    fromCache: Boolean(data.from_cache),
    logLines: Array.isArray(data.log_lines) ? data.log_lines : [],
  };
}
```

- [ ] **Step 4: Run the targeted test to verify it passes**

Run: `node --test desktop/renderer-v2/src/tests/api.test.js`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/renderer-v2/src/lib/api.js desktop/renderer-v2/src/tests/api.test.js
git commit -m "feat: add renderer-v2 source preparation api"
```

### Task 6: Extract source orchestration into a focused controller

**Files:**
- Create: `desktop/renderer-v2/src/features/source/sourceController.js`
- Create: `desktop/renderer-v2/src/tests/source-controller.test.js`
- Modify: `desktop/renderer-v2/src/app/App.js`

- [ ] **Step 1: Write the failing source-controller tests**

```js
import { createSourceController } from "../features/source/sourceController.js";

test("controller promotes a prepared youtube source into canonical file state", async () => {
  const controller = createSourceController({ ...deps });
  await controller.prepareYoutube("https://youtu.be/demo");
  assert.equal(store.getState().source.filePath, "/tmp/cache/demo.mp4");
  assert.equal(store.getState().ui.activeStep, "roi");
});

test("controller ignores stale prepare responses after source intent changes", async () => {
  const slow = deferred();
  const controller = createSourceController({ ...deps, api: { preparePreviewSource: () => slow.promise } });
  const pending = controller.prepareYoutube("https://youtu.be/old");
  controller.selectLocalFile("/tmp/manual.mp4");
  slow.resolve({ videoPath: "/tmp/cache/old.mp4", fromCache: false, logLines: [] });
  await pending;
  assert.equal(store.getState().source.filePath, "/tmp/manual.mp4");
});

test("controller maps low-resolution prepare failures to quality gate state", async () => {
  const controller = createSourceController({ ...deps, api: { preparePreviewSource: async () => { throw new Error("low resolution 640x360"); } } });
  await controller.prepareYoutube("https://youtu.be/soft");
  assert.equal(store.getState().source.prepareStatus, "error");
  assert.match(store.getState().source.error, /640x360/);
});
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `node --test desktop/renderer-v2/src/tests/source-controller.test.js`

Expected: FAIL because `sourceController.js` does not exist yet.

- [ ] **Step 3: Implement the focused source controller**

```js
export function createSourceController({ store, api, readMetadata, resetDownstream, formatSecondsLabel, messages }) {
  let sourceRequestToken = 0;

  function bumpSourceToken() {
    sourceRequestToken += 1;
    return sourceRequestToken;
  }

  async function prepareYoutube(youtubeUrl) {
    const token = bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = youtubeUrl;
      next.source.prepareStatus = "loading";
      next.source.error = "";
      return next;
    });

    try {
      const prepared = await api.preparePreviewSource({ sourceType: "youtube", youtubeUrl });
      if (token !== sourceRequestToken) return;
      const metadata = await readMetadata(prepared.videoPath);
      if (token !== sourceRequestToken) return;
      store.setState((next) => {
        next.source.filePath = prepared.videoPath;
        next.source.displayName = baseName(prepared.videoPath);
        next.source.metadata = metadata;
        next.source.preparedFromYouTube = true;
        next.source.preparedVideoPath = prepared.videoPath;
        next.source.prepareLogs = prepared.logLines;
        next.source.prepareStatus = "ready";
        next.source.status = "ready";
        resetDownstream(next);
        next.roi.frameTime = metadata?.durationSec ? Math.min(5, Math.floor(metadata.durationSec / 3)) : 0;
        next.roi.frameTimeLabel = formatSecondsLabel(next.roi.frameTime);
        next.ui.activeStep = "roi";
        return next;
      });
    } catch (error) {
      if (token !== sourceRequestToken) return;
      store.setState((next) => {
        next.source.prepareStatus = "error";
        next.source.error = messages.youtubePrepareError(error, next.ui.locale);
        next.source.prepareLogs = messages.mergePrepareLogs(next.source.prepareLogs, error);
        return next;
      });
    }
  }

  async function selectLocalFile(filePath) {
    const token = bumpSourceToken();
    const metadata = await readMetadata(filePath);
    if (token !== sourceRequestToken) return;
    store.setState((next) => {
      next.source.sourceType = "file";
      next.source.filePath = filePath;
      next.source.displayName = baseName(filePath);
      next.source.metadata = metadata;
      next.source.status = "ready";
      next.source.error = "";
      next.source.preparedFromYouTube = false;
      next.source.preparedVideoPath = "";
      next.source.prepareStatus = "idle";
      next.source.prepareLogs = [];
      resetDownstream(next);
      next.roi.frameTime = metadata?.durationSec ? Math.min(5, Math.floor(metadata.durationSec / 3)) : 0;
      next.roi.frameTimeLabel = formatSecondsLabel(next.roi.frameTime);
      next.ui.activeStep = "roi";
      return next;
    });
  }

  function setSourceType(sourceType) {
    bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = sourceType;
      if (sourceType === "file") {
        next.source.prepareStatus = "idle";
      }
      return next;
    });
  }

  function setYoutubeUrl(youtubeUrl) {
    const token = bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = youtubeUrl;
      if (token === sourceRequestToken) {
        next.source.prepareStatus = "idle";
      }
      return next;
    });
  }

  return {
    prepareYoutube,
    selectLocalFile,
    setSourceType,
    setYoutubeUrl,
  };
}
```

- [ ] **Step 4: Run the targeted test to verify it passes**

Run: `node --test desktop/renderer-v2/src/tests/source-controller.test.js`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/renderer-v2/src/features/source/sourceController.js desktop/renderer-v2/src/tests/source-controller.test.js desktop/renderer-v2/src/app/App.js
git commit -m "feat: add renderer-v2 source controller"
```

### Task 7: Wire YouTube controller into app actions and source UI

**Files:**
- Modify: `desktop/renderer-v2/src/app/App.js`
- Modify: `desktop/renderer-v2/src/features/source/SourceScreen.js`
- Modify: `desktop/renderer-v2/src/lib/messages.js`
- Test: `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

- [ ] **Step 1: Write the failing app-flow tests**

```js
test("youtube prepare success promotes the resolved path and enters roi", async () => {
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      preparePreviewSource: async () => ({ videoPath: "/tmp/cache/youtube.mp4", fromCache: false, logLines: [] }),
      createJob: async (payload) => {
        assert.equal(payload.source_type, "file");
        assert.equal(payload.file_path, "/tmp/cache/youtube.mp4");
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
      requestPreviewFrame: async () => ({ imagePath: "/tmp/frame.png", sourcePath: "/tmp/frame.png", diagnostics: [] }),
    },
    readVideoMetadata: async () => ({ durationSec: 60, durationLabel: "01:00", resolutionLabel: "1920x1080" }),
  });
  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.youtubeUrl = "https://youtu.be/demo";
    return next;
  });
  await root.dispatchAction("prepare-source-youtube");
  assert.equal(app.debug.getState().ui.activeStep, "roi");
  assert.equal(app.debug.getState().source.filePath, "/tmp/cache/youtube.mp4");
});

test("export after prepared youtube submits a file-backed payload", async () => {
  let seenPayload = null;
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      preparePreviewSource: async () => ({ videoPath: "/tmp/cache/youtube.mp4", fromCache: false, logLines: [] }),
      createJob: async (payload) => {
        seenPayload = payload;
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
      requestPreviewFrame: async () => ({ imagePath: "/tmp/frame.png", sourcePath: "/tmp/frame.png", diagnostics: [] }),
    },
    readVideoMetadata: async () => ({ durationSec: 60, durationLabel: "01:00", resolutionLabel: "1920x1080" }),
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/cache/youtube.mp4";
    next.source.sourceType = "youtube";
    next.source.preparedFromYouTube = true;
    next.roi.appliedRect = [[0, 0], [200, 0], [200, 120], [0, 120]];
    next.exportConfig.formats = ["png"];
    return next;
  });
  await root.dispatchAction("run-export");
  assert.equal(seenPayload.source_type, "file");
  assert.equal(seenPayload.file_path, "/tmp/cache/youtube.mp4");
});

test("prepare failure stays on source and shows a localized error", async () => {
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      preparePreviewSource: async () => { throw new Error("preview source preparation failed"); },
      requestPreviewFrame: async () => ({ imagePath: "/tmp/frame.png", sourcePath: "/tmp/frame.png", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
    readVideoMetadata: async () => ({ durationSec: 60, durationLabel: "01:00", resolutionLabel: "1920x1080" }),
  });
  app.debug.setState((next) => {
    next.ui.locale = "en";
    next.source.sourceType = "youtube";
    next.source.youtubeUrl = "https://youtu.be/fail";
    return next;
  });
  await root.dispatchAction("prepare-source-youtube");
  assert.equal(app.debug.getState().ui.activeStep, "source");
  assert.match(app.debug.getState().source.error, /could not|prepare/i);
});

test("prepare action stays disabled while prepareStatus is loading", async () => {
  const app = createApp(root, { exposeTestApi: true });
  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.youtubeUrl = "https://youtu.be/demo";
    next.source.prepareStatus = "loading";
    return next;
  });
  assert.match(root.querySelector("#stagePane").innerHTML, /disabled/);
});

test("selecting a local file after youtube preparation clears youtube-only state", async () => {
  const app = createApp(root, {
    exposeTestApi: true,
    bridge: {
      selectVideoFile: async () => "/tmp/manual.mp4",
      openPath: async () => "",
      copyText: async () => true,
      getBackendState: async () => ({ ready: true, starting: false, running: true, error: "" }),
      onBackendState: () => () => {},
    },
    readVideoMetadata: async () => ({ durationSec: 60, durationLabel: "01:00", resolutionLabel: "1920x1080" }),
  });
  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.filePath = "/tmp/cache/youtube.mp4";
    next.source.preparedFromYouTube = true;
    next.source.preparedVideoPath = "/tmp/cache/youtube.mp4";
    next.source.prepareLogs = ["youtube download saved"];
    next.source.prepareStatus = "ready";
    return next;
  });
  await root.dispatchAction("select-source-file");
  assert.equal(app.debug.getState().source.preparedFromYouTube, false);
  assert.equal(app.debug.getState().source.preparedVideoPath, "");
  assert.deepEqual(app.debug.getState().source.prepareLogs, []);
});
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `node --test desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: FAIL because the app is not yet wired to the new source controller and the source screen does not expose the required action/state affordances.

- [ ] **Step 3: Implement controller wiring and failure-state rendering**

```js
// App.js
const sourceController = createSourceController({ store, api: runtimeApi, readMetadata, resetDownstream, formatSecondsLabel, messages });

if (action === "prepare-source-youtube") {
  await sourceController.prepareYoutube(store.getState().source.youtubeUrl);
  return;
}

if (action === "select-source-file") {
  const filePath = await runtimeBridge.selectVideoFile();
  if (!filePath) return;
  await sourceController.selectLocalFile(filePath);
  return;
}

// SourceScreen.js
<button class="button button-primary" data-action="prepare-source-youtube" ${model.prepareDisabled ? "disabled" : ""}>
  ${model.prepareActionLabel}
</button>
${model.showQualityGate ? `<div class="source-quality-gate"><strong>${model.qualityGateTitle}</strong><p>${model.qualityGateBody}</p></div>` : ""}
${model.prepareLogs.length ? `<pre class="source-prepare-log">${model.prepareLogs.join("\n")}</pre>` : ""}
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `node --test desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: PASS

- [ ] **Step 5: Run focused renderer-v2 verification**

Run: `node --test desktop/renderer-v2/src/tests/i18n.test.js desktop/renderer-v2/src/tests/api.test.js desktop/renderer-v2/src/tests/source-controller.test.js desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/session-selectors.test.js desktop/renderer-v2/src/tests/process-rail.test.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add desktop/renderer-v2/src/app/App.js desktop/renderer-v2/src/features/source/SourceScreen.js desktop/renderer-v2/src/lib/messages.js desktop/renderer-v2/src/tests/app-runtime-flows.test.js desktop/renderer-v2/src/tests/api.test.js desktop/renderer-v2/src/tests/source-controller.test.js desktop/renderer-v2/src/tests/i18n.test.js desktop/renderer-v2/src/tests/source-screen.test.js desktop/renderer-v2/src/tests/session-selectors.test.js desktop/renderer-v2/src/tests/process-rail.test.js
git commit -m "feat: restore renderer-v2 youtube source flow"
```

## Final Verification

- [ ] Run: `npm --prefix desktop run test:renderer-v2`
  - Expected: PASS
- [ ] Run: `npm --prefix desktop run check:renderer-v2`
  - Expected: PASS
- [ ] Run a manual smoke check in the desktop app:
  - Launch default renderer-v2
  - Toggle `KO` / `EN`
  - Prepare a known-good YouTube URL
  - Load ROI preview
  - Start an export job using the prepared source
- [ ] If any command fails, fix before claiming completion.
