import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const indexHtml = fs.readFileSync(path.resolve(process.cwd(), "renderer/index.html"), "utf8");
const css = fs.readFileSync(path.resolve(process.cwd(), "renderer/style.css"), "utf8");

test("legacy support sheet is expressed as a proper dialog surface", () => {
  assert.match(indexHtml, /id="supportSheet"[\s\S]*role="dialog"/);
  assert.match(indexHtml, /id="supportSheet"[\s\S]*aria-modal="true"/);
  assert.match(indexHtml, /id="supportSheetTitle"/);
  assert.match(indexHtml, /id="supportSheetDescription"/);
});

test("legacy capture crop dialog exposes keyboard focus affordances", () => {
  assert.match(indexHtml, /id="captureCropDialog"[\s\S]*role="dialog"/);
  assert.match(indexHtml, /id="captureCropCanvas" tabindex="0"/);
  assert.match(css, /\.capture-crop-stage canvas:focus-visible/);
  assert.match(css, /\.support-sheet-panel:focus-visible,\s*\.capture-crop-dialog:focus-visible/);
});
