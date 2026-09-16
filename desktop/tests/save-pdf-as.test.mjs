import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
const { savePdfAs, pdfFileName } = createRequire(import.meta.url)("../save-pdf-as.js");

async function fixture(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "score-pdf-save-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const source = path.join(dir, "original.pdf");
  const bytes = Buffer.from("%PDF-1.4\noriginal score\n%%EOF\n");
  await fs.writeFile(source, bytes);
  return { dir, source, bytes };
}

test("save as copies exact PDF bytes to the chosen path and retains the original", async t => {
  const { dir, source, bytes } = await fixture(t);
  const destination = path.join(dir, "내 악보.pdf");
  const parentWindow = {};
  const result = await savePdfAs({ sourcePath: source, suggestedName: '항해/연습.mp4', locale: "ko" }, {
    parentWindow, downloadsPath: dir,
    dialog: { async showSaveDialog(parent, options) {
      assert.equal(parent, parentWindow);
      assert.equal(options.defaultPath, path.join(dir, "항해_연습.pdf"));
      assert.deepEqual(options.filters, [{ name: "PDF", extensions: ["pdf"] }]);
      return { canceled: false, filePath: destination };
    } },
  });
  assert.deepEqual(result, { canceled: false, filePath: destination });
  assert.deepEqual(await fs.readFile(destination), bytes);
  assert.deepEqual(await fs.readFile(source), bytes);
});

test("canceling the dialog creates no file", async t => {
  const { dir, source } = await fixture(t);
  const result = await savePdfAs({ sourcePath: source }, {
    downloadsPath: dir, dialog: { showSaveDialog: async () => ({ canceled: true, filePath: path.join(dir, "unused.pdf") }) },
  });
  assert.equal(result.canceled, true);
  assert.deepEqual(await fs.readdir(dir), ["original.pdf"]);
});

test("choosing the original PDF is safe and unchanged", async t => {
  const { dir, source, bytes } = await fixture(t);
  await savePdfAs({ sourcePath: source }, { downloadsPath: dir,
    dialog: { showSaveDialog: async () => ({ canceled: false, filePath: source }) } });
  assert.deepEqual(await fs.readFile(source), bytes);
});

test("appended PDF extension never silently replaces a different existing path", async t => {
  const { dir, source } = await fixture(t);
  const destination = path.join(dir, "existing.pdf");
  await fs.writeFile(destination, "keep me");
  let asked = false;
  const result = await savePdfAs({ sourcePath: source }, { downloadsPath: dir, dialog: {
    showSaveDialog: async () => ({ canceled: false, filePath: path.join(dir, "existing") }),
    showMessageBox: async () => { asked = true; return { response: 0 }; },
  } });
  assert.equal(asked, true);
  assert.equal(result.canceled, true);
  assert.equal(await fs.readFile(destination, "utf8"), "keep me");
});

test("extensionless new targets receive .pdf and missing sources or unwritable targets reject", async t => {
  const { dir, source, bytes } = await fixture(t);
  const dialog = { showSaveDialog: async () => ({ canceled: false, filePath: path.join(dir, "copy") }) };
  const result = await savePdfAs({ sourcePath: source }, { downloadsPath: dir, dialog });
  assert.deepEqual(await fs.readFile(result.filePath), bytes);
  await assert.rejects(savePdfAs({ sourcePath: path.join(dir, "missing.pdf") }, { downloadsPath: dir, dialog }), /ENOENT/);
  dialog.showSaveDialog = async () => ({ canceled: false, filePath: path.join(dir, "missing-dir", "copy.pdf") });
  await assert.rejects(savePdfAs({ sourcePath: source }, { downloadsPath: dir, dialog }), /ENOENT/);
});

test("suggested names keep PDF extension, preserve Korean, and avoid invalid Windows names", () => {
  assert.equal(pdfFileName("CON"), "_CON.pdf");
  assert.equal(pdfFileName("연습.pdf"), "연습.pdf");
  assert.equal(pdfFileName("../a:b?.mp4"), ".._a_b_.pdf");
});
