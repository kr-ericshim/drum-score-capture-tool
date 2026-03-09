#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const indexHtml = fs.readFileSync(path.join(projectRoot, "renderer", "index.html"), "utf8");
const i18nModule = fs.readFileSync(path.join(projectRoot, "renderer", "modules", "i18n.js"), "utf8");

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
  /const stored = window\.localStorage\.getItem\(LOCALE_STORAGE_KEY\);[\s\S]*if \(stored\) \{[\s\S]*return normalizeLocale\(stored\);/,
);
assertMatch(
  "i18n ko normalization",
  i18nModule,
  /if \(value\.startsWith\("ko"\)\) \{[\s\S]*return "ko";[\s\S]*\}[\s\S]*return "en";/,
);
assertMatch(
  "i18n navigator fallback",
  i18nModule,
  /return normalizeLocale\(navigator\.language \|\| navigator\.userLanguage \|\| "en"\);/,
);

console.log("[check-locale-init] locale bootstrap and renderer policy are aligned");
