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
  const text = t("__missing_translation_key__", { locale: "ko" });

  assert.equal(text, "__missing_translation_key__");
});

test("shell translations stay task-first and avoid machine-style wording", () => {
  const shellKeys = [
    "topbar.engine.ready",
    "topbar.engine.waiting",
    "rail.pipeline",
    "rail.workbenchStatus",
    "lane.inspectionView",
    "status.engineReady",
    "status.localTool",
  ];
  const disallowed = /workflow|system status|inspection view|engine_ready|workbench status|local_tool|pipeline/i;

  for (const key of shellKeys) {
    assert.doesNotMatch(t(key, { locale: "ko" }), disallowed);
    assert.doesNotMatch(t(key, { locale: "en" }), disallowed);
  }

  assert.equal(t("topbar.step.source", { locale: "ko" }), "소스");
  assert.equal(t("topbar.step.source", { locale: "en" }), "Source");
  assert.equal(t("rail.pipeline", { locale: "en" }), "Steps");
  assert.equal(t("rail.workbenchStatus", { locale: "en" }), "Ready");
  assert.equal(t("status.engineReady", { locale: "en" }), "Processor ready");
});

test("persistLocale stores a supported locale and a fresh read uses it", () => {
  const storage = new Map();

  persistLocale("ko", {
    setItem(key, value) {
      storage.set(key, value);
    },
  });

  const locale = detectInitialLocale({
    storageValue: storage.get("drum-sheet-language"),
    navigatorLanguage: "en-US",
  });

  assert.equal(locale, "ko");
});

test("detectInitialLocale normalizes stored locale tags before applying precedence", () => {
  const locale = detectInitialLocale({
    storageValue: "ko-KR",
    navigatorLanguage: "en-US",
  });

  assert.equal(locale, "ko");
});
