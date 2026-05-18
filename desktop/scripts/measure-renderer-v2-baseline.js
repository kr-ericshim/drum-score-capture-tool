const fs = require("node:fs");
const path = require("node:path");

function walkFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const nextPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(nextPath));
      continue;
    }
    if (entry.isFile()) {
      files.push(nextPath);
    }
  }

  return files.sort();
}

function summarizeRenderer(label, rootDir) {
  if (!fs.existsSync(rootDir)) {
    return {
      label,
      rootDir,
      fileCount: 0,
      totalBytes: 0,
      totalKiB: 0,
      retired: true,
    };
  }
  const files = walkFiles(rootDir).filter((filePath) => /\.(css|html|js|mjs|cjs)$/i.test(filePath));
  const totalBytes = files.reduce((sum, filePath) => sum + fs.statSync(filePath).size, 0);

  return {
    label,
    rootDir,
    fileCount: files.length,
    totalBytes,
    totalKiB: Number((totalBytes / 1024).toFixed(2)),
  };
}

const desktopDir = path.join(__dirname, "..");
const legacy = summarizeRenderer("legacy-renderer", path.join(desktopDir, "renderer"));
const rendererV2 = summarizeRenderer("renderer-v2", path.join(desktopDir, "renderer-v2"));

console.log(
  JSON.stringify(
    {
      measuredAt: new Date().toISOString(),
      note: "Static active-renderer footprint only. The legacy renderer is retired; packaged GUI launch and idle memory still require a real Electron smoke harness.",
      legacy,
      rendererV2,
    },
    null,
    2,
  ),
);
