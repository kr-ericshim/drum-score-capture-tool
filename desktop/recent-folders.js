const fs = require("node:fs");
const path = require("node:path");

// The folders last used to open a video and to save a PDF, kept across restarts.
// A folder that no longer exists is not offered; the dialogs then use their own default.
function createRecentFolders(filePath) {
  let folders = {};
  try {
    const stored = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (stored && typeof stored === "object") folders = stored;
  } catch (_) { /* first launch or an unreadable file: start empty */ }

  function get(kind) {
    const dir = folders[kind];
    if (typeof dir !== "string" || !path.isAbsolute(dir)) return undefined;
    try { return fs.statSync(dir).isDirectory() ? dir : undefined; } catch (_) { return undefined; }
  }

  function remember(kind, dir) {
    if (typeof dir !== "string" || !path.isAbsolute(dir) || folders[kind] === dir) return;
    folders = { ...folders, [kind]: dir };
    try {
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, JSON.stringify(folders));
    } catch (_) { /* kept for this launch only */ }
  }

  return { get, remember };
}

module.exports = { createRecentFolders };
