const fs = require('node:fs');
const path = require('node:path');
const REPO = 'kr-ericshim/drum-score-capture-tool';
const RELEASES_URL = `https://github.com/${REPO}/releases`;
const API_URL = `https://api.github.com/repos/${REPO}/releases/latest`;
const DAY = 24 * 60 * 60 * 1000;

function newerVersion(candidate, current) {
  const parse = value => /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(String(value));
  const a = parse(candidate); const b = parse(current);
  if (!a || !b) return false;
  for (let i = 1; i <= 3; i++) {
    if (BigInt(a[i]) !== BigInt(b[i])) return BigInt(a[i]) > BigInt(b[i]);
  }
  return false;
}
function createReleaseUpdates({ currentVersion, cachePath, fetchImpl = globalThis.fetch, now = Date.now }) {
  let cache = {};
  let pending;
  try { cache = JSON.parse(fs.readFileSync(cachePath, 'utf8')); } catch (_) { /* optional cache */ }
  if (!cache || typeof cache !== 'object' || Array.isArray(cache)) cache = {};
  function save() {
    try {
      fs.mkdirSync(path.dirname(cachePath), { recursive: true });
      fs.writeFileSync(cachePath + '.tmp', JSON.stringify(cache));
      fs.renameSync(cachePath + '.tmp', cachePath);
    } catch (_) { /* read-only disk must not block capture */ }
  }
  function result() {
    if (cache.version !== cache.dismissed && newerVersion(cache.version, currentVersion)) {
      return { version: cache.version, url: `${RELEASES_URL}/tag/v${cache.version}` };
    }
    return null;
  }
  return {
    check() {
      if (pending) return pending;
      const age = now() - Number(cache.checkedAt);
      if (Number.isFinite(age) && age >= 0 && age < DAY) return Promise.resolve(result());
      pending = (async () => {
        try {
          const response = await fetchImpl(API_URL, {
            headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Drum-Sheet-Capture' },
            signal: AbortSignal.timeout(5000), redirect: 'error',
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          if (!data.draft && !data.prerelease && /^v\d+\.\d+\.\d+$/.test(data.tag_name)) {
            cache.version = data.tag_name.slice(1);
          }
        } catch (_) { /* startup stays usable offline and on GitHub rate limits */ }
        cache.checkedAt = now();
        save();
        return result();
      })().finally(() => { pending = null; });
      return pending;
    },
    dismiss() { cache.dismissed = cache.version; save(); },
  };
}
module.exports = { createReleaseUpdates, newerVersion, RELEASES_URL };
