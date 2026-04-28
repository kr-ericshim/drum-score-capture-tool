#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const indexHtml = fs.readFileSync(path.join(projectRoot, "renderer-v2", "index.html"), "utf8");
const i18nModule = fs.readFileSync(path.join(projectRoot, "renderer-v2", "src", "lib", "i18n.js"), "utf8");

function assertMatch(label, source, pattern) {
  if (!pattern.test(source)) {
    console.error(`[check-locale-init] missing expected ${label}`);
    process.exit(1);
  }
}

assertMatch(
  "bootstrap locale storage key",
  indexHtml,
  /const localeKey = "drum-sheet-language";/,
);
assertMatch(
  "bootstrap stored locale precedence",
  indexHtml,
  /const savedLocale = localStorage\.getItem\(localeKey\);[\s\S]*savedLocale === "ko" \|\| savedLocale === "en"/,
);
assertMatch(
  "bootstrap ko fallback",
  indexHtml,
  /navigator\.language \|\| ""\)\.toLowerCase\(\)\.startsWith\("ko"\) \? "ko" : "en"/,
);
assertMatch(
  "i18n storage precedence",
  i18nModule,
  /const savedLocale = storageValue \?\? globalThis\?\.localStorage\?\.getItem\?\.\(LOCALE_STORAGE_KEY\);[\s\S]*if \(savedLocale\) \{[\s\S]*return normalizeLocale\(savedLocale\);/,
);
assertMatch(
  "i18n ko normalization",
  i18nModule,
  /const normalized = String\(locale \|\| ""\)\.trim\(\)\.toLowerCase\(\);[\s\S]*return normalized\.startsWith\("ko"\) \? "ko" : "en";/,
);
assertMatch(
  "i18n navigator fallback",
  i18nModule,
  /const browserLocale = navigatorLanguage \?\? globalThis\?\.navigator\?\.language;[\s\S]*return normalizeLocale\(browserLocale\);/,
);

console.log("[check-locale-init] renderer-v2 locale bootstrap and translation policy are aligned");
