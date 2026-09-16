import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const { fileBytes, writeSizeReport } = createRequire(import.meta.url)("../scripts/measure-packaged-size.js");

test("size measurement does not count framework symlink aliases twice", { skip: process.platform === "win32" }, (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "package-bytes-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, "version"));
  fs.writeFileSync(path.join(root, "version", "binary"), Buffer.alloc(37));
  fs.symlinkSync("version", path.join(root, "current"));
  assert.equal(fileBytes(root), 37);
});

test("size report separates installed files from compressed installer bytes", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "package-report-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const appRoot = path.join(root, "app");
  const resources = process.platform === "darwin"
    ? path.join(appRoot, "Contents", "Resources")
    : path.join(appRoot, "resources");
  const backend = path.join(resources, "backend");
  for (const dir of ["app", "runtime", "bin"]) fs.mkdirSync(path.join(backend, dir), { recursive: true });
  fs.writeFileSync(path.join(backend, "app", "main.py"), "abc");
  fs.writeFileSync(path.join(backend, "runtime", "backend"), Buffer.alloc(10));
  fs.writeFileSync(path.join(backend, "bin", "ffmpeg"), Buffer.alloc(20));
  fs.writeFileSync(path.join(resources, "app.asar"), Buffer.alloc(5));
  const installer = path.join(root, "installer.dmg");
  fs.writeFileSync(installer, Buffer.alloc(17));
  const outputPath = path.join(root, "report.json");
  const report = writeSizeReport({
    packagedBackendMainPath: path.join(backend, "app", "main.py"),
    installerArtifacts: [installer], version: "1.0.0", outputPath,
  });
  assert.equal(report.appBytes, 38);
  assert.equal(report.components.other, 3);
  assert.equal(report.installers[0].bytes, 17);
  assert.deepEqual(JSON.parse(fs.readFileSync(outputPath, "utf8")), report);
});
