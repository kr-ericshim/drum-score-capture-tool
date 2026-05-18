const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { resolveRendererIndexPath } = require("../renderer-entry.js");

test("loads renderer-v2 by default when it exists", () => {
  const baseDir = path.join("/tmp", "desktop");

  const rendererPath = resolveRendererIndexPath({
    baseDir,
    preference: "",
    existsFile(candidate) {
      return candidate === path.join(baseDir, "renderer-v2", "index.html");
    },
  });

  assert.equal(rendererPath, path.join(baseDir, "renderer-v2", "index.html"));
});

test("keeps renderer-v2 even when legacy is explicitly requested", () => {
  const baseDir = path.join("/tmp", "desktop");

  const rendererPath = resolveRendererIndexPath({
    baseDir,
    preference: "legacy",
    existsFile() {
      return true;
    },
  });

  assert.equal(rendererPath, path.join(baseDir, "renderer-v2", "index.html"));
});

test("keeps renderer-v2 as the only product entry when renderer-v2 is missing", () => {
  const baseDir = path.join("/tmp", "desktop");

  const rendererPath = resolveRendererIndexPath({
    baseDir,
    preference: "v2",
    existsFile(candidate) {
      return candidate === path.join(baseDir, "renderer", "index.html");
    },
  });

  assert.equal(rendererPath, path.join(baseDir, "renderer-v2", "index.html"));
});
