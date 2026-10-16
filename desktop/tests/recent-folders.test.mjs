import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
const { createRecentFolders } = createRequire(import.meta.url)("../recent-folders.js");
const { savePdfAs } = createRequire(import.meta.url)("../save-pdf-as.js");

async function tempDir(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "score-recent-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  return dir;
}

test("remembered folders survive a restart and vanish when the folder is gone", async t => {
  const dir = await tempDir(t);
  const store = path.join(dir, "state", "recent-folders.json");
  const videos = path.join(dir, "videos");
  const scores = path.join(dir, "scores");
  await fs.mkdir(videos);
  await fs.mkdir(scores);
  const first = createRecentFolders(store);
  assert.equal(first.get("video"), undefined);
  first.remember("video", videos);
  first.remember("pdf", scores);
  first.remember("pdf", "relative/dir");
  const restarted = createRecentFolders(store);
  assert.equal(restarted.get("video"), videos);
  assert.equal(restarted.get("pdf"), scores);
  await fs.rm(scores, { recursive: true });
  assert.equal(restarted.get("pdf"), undefined);
});

test("an unreadable store starts empty", async t => {
  const dir = await tempDir(t);
  const store = path.join(dir, "recent-folders.json");
  await fs.writeFile(store, "{not json");
  assert.equal(createRecentFolders(store).get("video"), undefined);
});

test("save as opens in the remembered folder when one is given", async t => {
  const dir = await tempDir(t);
  const source = path.join(dir, "original.pdf");
  await fs.writeFile(source, "%PDF-1.4\n%%EOF\n");
  const scores = path.join(dir, "scores");
  let defaultPath;
  await savePdfAs({ sourcePath: source, suggestedName: "곡" }, {
    downloadsPath: dir, defaultDir: scores,
    dialog: { showSaveDialog: async options => { defaultPath = options.defaultPath; return { canceled: true }; } },
  });
  assert.equal(defaultPath, path.join(scores, "곡.pdf"));
});
