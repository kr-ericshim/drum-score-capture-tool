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
