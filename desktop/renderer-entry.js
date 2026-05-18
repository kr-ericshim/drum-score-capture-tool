const path = require("node:path");

function resolveRendererIndexPath(options = {}) {
  const baseDir = options.baseDir || __dirname;
  return path.join(baseDir, "renderer-v2", "index.html");
}

module.exports = {
  resolveRendererIndexPath,
};
