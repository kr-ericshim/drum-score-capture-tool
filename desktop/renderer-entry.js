const fs = require("node:fs");
const path = require("node:path");

function normalizeRendererPreference(value = "") {
  return String(value || "").trim().toLowerCase();
}

function resolveRendererIndexPath(options = {}) {
  const baseDir = options.baseDir || __dirname;
  const existsFile = options.existsFile || ((candidate) => fs.existsSync(candidate));
  const preference = normalizeRendererPreference(options.preference ?? process.env.DRUMSHEET_RENDERER);
  const legacyPath = path.join(baseDir, "renderer", "index.html");
  const rendererV2Path = path.join(baseDir, "renderer-v2", "index.html");

  if (preference === "legacy" || preference === "renderer" || preference === "v1") {
    return legacyPath;
  }

  if (existsFile(rendererV2Path)) {
    return rendererV2Path;
  }

  if (existsFile(legacyPath)) {
    return legacyPath;
  }

  return rendererV2Path;
}

module.exports = {
  normalizeRendererPreference,
  resolveRendererIndexPath,
};
