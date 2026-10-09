import test from "node:test";
import assert from "node:assert/strict";

import { describeError, detectInitialLocale, errorDetailText, persistLocale, pickLocalizedText, t } from "../lib/i18n.js";

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

  assert.equal(t("topbar.step.source", { locale: "ko" }), "영상 선택");
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

test("bilingual backend notes show only the UI language", () => {
  const note = "재생 표시가 남아 있을 수 있습니다 / A playback mark may remain";
  assert.equal(pickLocalizedText(note, "ko"), "재생 표시가 남아 있을 수 있습니다");
  assert.equal(pickLocalizedText(note, "en"), "A playback mark may remain");
  // OVERLAY_COVERS_NOTATION (backend main.REFLOW_ISSUE_REASONS)
  const chrome = "화면 표시가 음표에 닿아 그대로 두었어요. 확인이 필요해요 / Screen overlay touches notation; kept as is. Please check";
  assert.equal(pickLocalizedText(chrome, "ko"), "화면 표시가 음표에 닿아 그대로 두었어요. 확인이 필요해요");
  assert.equal(pickLocalizedText(chrome, "en"), "Screen overlay touches notation; kept as is. Please check");
  // a slash inside one language's part stays with that part
  const jump = "양쪽을 / 모두 남겼습니다 / Both sides / are kept";
  assert.equal(pickLocalizedText(jump, "ko"), "양쪽을 / 모두 남겼습니다");
  assert.equal(pickLocalizedText(jump, "en"), "Both sides / are kept");
  assert.equal(pickLocalizedText("A / B in one language", "ko"), "A / B in one language");
  assert.equal(pickLocalizedText("한 언어 / 그대로", "en"), "한 언어 / 그대로");
});

test("error objects become readable messages, never [object Object]", () => {
  assert.equal(errorDetailText({}), "");
  assert.equal(errorDetailText({ detail: [{ loc: ["body", "formats"], msg: "field required" }, { msg: "bad order" }] }), "field required; bad order");
  assert.equal(errorDetailText({ message: { detail: "nested" } }), "nested");
  assert.equal(describeError({}, "ko"), t("error.unknown", { locale: "ko" }));
  assert.equal(describeError(undefined, "en"), t("error.unknown", { locale: "en" }));
  assert.equal(describeError(new Error("REQUEST_TIMEOUT: POST /x did not answer within 30 s"), "en"), t("error.requestTimeout", { locale: "en" }));
  assert.equal(describeError({ name: "TimeoutError" }, "ko"), t("error.requestTimeout", { locale: "ko" }));
  assert.equal(describeError(new Error("REQUEST_FAILED: Failed to fetch"), "ko"), t("error.requestFailed", { locale: "ko" }));
  assert.equal(describeError(new Error("저장 실패 / Save failed"), "en"), "Save failed");
  for (const value of [{}, { a: 1 }, [{}], new Error(""), { message: {} }]) {
    assert.doesNotMatch(describeError(value, "ko"), /\[object Object\]/);
  }
});
