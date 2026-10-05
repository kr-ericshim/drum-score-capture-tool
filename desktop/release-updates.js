const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pipeline } = require('node:stream/promises');
const REPO = 'kr-ericshim/drum-score-capture-tool';
const RELEASES_URL = `https://github.com/${REPO}/releases`;
const API_URL = `https://api.github.com/repos/${REPO}/releases/latest`;
const DOWNLOAD_PREFIX = `${RELEASES_URL}/download/`;
const STALL_MS = 60 * 1000;

function newerVersion(candidate, current) {
  const parse = value => /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(String(value));
  const a = parse(candidate); const b = parse(current);
  if (!a || !b) return false;
  for (let i = 1; i <= 3; i++) {
    if (BigInt(a[i]) !== BigInt(b[i])) return BigInt(a[i]) > BigInt(b[i]);
  }
  return false;
}

function olderSystem(current, required) {
  const parts = value => String(value).split('.').map(part => Number.parseInt(part, 10) || 0);
  const a = parts(current); const b = parts(required);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) < (b[i] || 0);
  }
  return false;
}

// Release notes declare what the new runtime needs, e.g. <!-- minimum-os: darwin=13.0 win32=10.0 -->.
// Old clients cannot know that a new Electron dropped their OS, so this is read before offering an install.
function parseMinimumOs(body) {
  const match = /<!--\s*minimum-os:([^>]*?)-->/.exec(String(body || ''));
  const minimum = {};
  for (const entry of match ? match[1].trim().split(/\s+/) : []) {
    const [platform, version] = entry.split('=');
    if (platform && /^\d+(\.\d+)*$/.test(version || '')) minimum[platform] = version;
  }
  return minimum;
}

// Only the installer built for this machine qualifies, and only with GitHub's own sha256 digest to verify it.
function pickInstallerAsset(assets, platform, arch) {
  const matches = platform === 'darwin'
    ? name => name.endsWith(`-${arch}.dmg`)
    : platform === 'win32' ? name => /setup/i.test(name) && name.endsWith('.exe') : () => false;
  const asset = (Array.isArray(assets) ? assets : []).find(item => item && matches(String(item.name || '')));
  if (!asset) return null;
  const digest = /^sha256:([0-9a-f]{64})$/.exec(String(asset.digest || ''));
  const url = String(asset.browser_download_url || '');
  const size = Number(asset.size);
  if (!digest || !url.startsWith(DOWNLOAD_PREFIX) || !Number.isSafeInteger(size) || size <= 0) return null;
  return { url, size, sha256: digest[1], ext: path.extname(asset.name) };
}

function validInstallerAsset(asset) {
  return Boolean(asset && Number.isSafeInteger(asset.size) && asset.size > 0
    && /^[0-9a-f]{64}$/.test(asset.sha256) && String(asset.url || '').startsWith(DOWNLOAD_PREFIX)
    && ['.dmg', '.exe'].includes(asset.ext));
}

async function verifyInstallerFile({ filePath, asset }) {
  if (!validInstallerAsset(asset)) return false;
  try {
    if ((await fs.promises.stat(filePath)).size !== asset.size) return false;
    const hash = crypto.createHash('sha256');
    let received = 0;
    for await (const chunk of fs.createReadStream(filePath)) {
      received += chunk.length;
      if (received > asset.size) return false;
      hash.update(chunk);
    }
    return received === asset.size && hash.digest('hex') === asset.sha256;
  } catch (_) { return false; }
}

function createReleaseUpdates({
  currentVersion, cachePath, downloadDir, platform = process.platform, arch = process.arch, systemVersion = '',
  installSupported = true, fetchImpl = globalThis.fetch, onState = () => {}, createWriteStream = fs.createWriteStream,
}) {
  let cache = {};
  try { cache = JSON.parse(fs.readFileSync(cachePath, 'utf8')); } catch (_) { /* optional cache */ }
  if (!cache || typeof cache !== 'object' || Array.isArray(cache)) cache = {};
  let state = { status: 'idle', currentVersion };
  let release = null;
  let pendingCheck = null;
  let pendingDownload = null;
  let checkedOnce = false;
  let checkIsManual = false;
  let readyFile = '';
  // The minimum travels with the asset into the install marker, so a restored installer is checked again.
  const cannotRun = asset => Boolean(asset?.minimumOs && systemVersion && olderSystem(systemVersion, asset.minimumOs));

  function save() {
    try {
      fs.mkdirSync(path.dirname(cachePath), { recursive: true });
      fs.writeFileSync(cachePath + '.tmp', JSON.stringify({ dismissed: cache.dismissed }));
      fs.renameSync(cachePath + '.tmp', cachePath);
    } catch (_) { /* read-only disk must not block capture */ }
  }
  function setState(next) {
    state = { currentVersion, ...next };
    try { onState(state); } catch (_) { /* a closed window must not break updates */ }
    return state;
  }
  function availableState(extra = {}) {
    return {
      status: 'available', version: release.version, url: `${RELEASES_URL}/tag/v${release.version}`,
      canInstall: Boolean(installSupported && release.asset && !release.requiredOs),
      ...(release.requiredOs ? { requiredOs: release.requiredOs } : {}), ...extra,
    };
  }

  async function fetchLatest() {
    const response = await fetchImpl(API_URL, {
      headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Drum-Sheet-Capture' },
      signal: AbortSignal.timeout(8000), redirect: 'error',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.draft || data.prerelease || !/^v\d+\.\d+\.\d+$/.test(String(data.tag_name))) return null;
    const required = parseMinimumOs(data.body)[platform];
    const picked = pickInstallerAsset(data.assets, platform, arch);
    const asset = picked && required ? { ...picked, minimumOs: required } : picked;
    const requiredOs = required && systemVersion && olderSystem(systemVersion, required) ? { platform, version: required } : null;
    return { version: data.tag_name.slice(1), asset, requiredOs };
  }

  function check({ manual = false } = {}) {
    // A download in progress or finished already answers the question.
    if (['downloading', 'ready', 'installing', 'manual'].includes(state.status)) return Promise.resolve(state);
    if (pendingCheck) {
      // A manual check joining the startup request shares the network call but not its silence.
      if (manual && !checkIsManual) {
        checkIsManual = true;
        setState({ status: 'checking', manual: true });
      }
      return pendingCheck;
    }
    if (!manual && checkedOnce) return Promise.resolve(state);
    checkedOnce = true;
    checkIsManual = manual;
    setState({ status: 'checking', manual });
    pendingCheck = (async () => {
      let latest;
      try {
        latest = await fetchLatest();
      } catch (_) {
        // Startup stays silent offline and on GitHub rate limits; a manual check reports the failure.
        return setState(checkIsManual ? { status: 'error', error: 'check', manual: true } : { status: 'idle' });
      }
      if (!latest || !newerVersion(latest.version, currentVersion)) {
        release = null;
        return setState({ status: 'current', manual: checkIsManual });
      }
      release = latest;
      // Startup respects "skip this version"; an explicit check always reports it.
      if (!checkIsManual && cache.dismissed === latest.version) return setState({ status: 'idle' });
      return setState(availableState({ manual: checkIsManual }));
    })().finally(() => { pendingCheck = null; });
    return pendingCheck;
  }

  async function streamToFile(asset, target) {
    const controller = new AbortController();
    let stallTimer = setTimeout(() => controller.abort(), STALL_MS);
    const resetStall = () => { clearTimeout(stallTimer); stallTimer = setTimeout(() => controller.abort(), STALL_MS); };
    const hash = crypto.createHash('sha256');
    let received = 0;
    let lastReported = -1;
    try {
      const response = await fetchImpl(asset.url, {
        headers: { 'User-Agent': 'Drum-Sheet-Capture' }, signal: controller.signal, redirect: 'follow',
      });
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
      // pipeline() settles on a network, disk-full or abort error in any stage and closes the file.
      await pipeline(response.body, async function* verify(source) {
        for await (const chunk of source) {
          resetStall();
          const bytes = Buffer.from(chunk);
          received += bytes.length;
          if (received > asset.size) throw new Error('download larger than release asset');
          hash.update(bytes);
          const percent = Math.floor((received / asset.size) * 100);
          if (percent !== lastReported) {
            lastReported = percent;
            setState({ status: 'downloading', version: release.version, progress: percent });
          }
          yield bytes;
        }
      }, createWriteStream(target), { signal: controller.signal });
    } finally {
      clearTimeout(stallTimer);
    }
    if (received !== asset.size) throw new Error('download size mismatch');
    if (hash.digest('hex') !== asset.sha256) throw new Error('download checksum mismatch');
  }

  function download() {
    if (pendingDownload) return pendingDownload;
    // Deleting the download folder now would pull the installer out from under a running install.
    if (['ready', 'installing', 'manual'].includes(state.status)) return Promise.resolve(state);
    if (!release || !release.asset || release.requiredOs || !installSupported) return Promise.resolve(state);
    const { version, asset } = release;
    pendingDownload = (async () => {
      const target = path.join(downloadDir, `update-${version}${asset.ext}`);
      const partial = target + '.partial';
      try {
        fs.rmSync(downloadDir, { recursive: true, force: true });
        fs.mkdirSync(downloadDir, { recursive: true });
        setState({ status: 'downloading', version, progress: 0 });
        await streamToFile(asset, partial);
        fs.renameSync(partial, target);
        readyFile = target;
        return setState({ status: 'ready', version });
      } catch (_) {
        try { fs.rmSync(partial, { force: true }); } catch (_) { /* cleared on the next attempt */ }
        return setState(availableState({ status: 'error', error: 'download' }));
      }
    })().finally(() => { pendingDownload = null; });
    return pendingDownload;
  }

  return {
    check,
    download,
    getState: () => state,
    // Moves ready -> installing exactly once; a second caller gets null instead of a second installer.
    beginInstall() {
      if (state.status !== 'ready' || !readyFile || cannotRun(release?.asset)) return null;
      setState({ status: 'installing', version: state.version });
      return { version: state.version, filePath: readyFile, asset: release.asset };
    },
    // The verified DMG stays available for the manual fallback.
    getInstallerFile: () => (['ready', 'manual'].includes(state.status) && !cannotRun(release?.asset) ? readyFile : ''),
    getInstaller: () => ({ filePath: readyFile, asset: release?.asset }),
    invalidateInstaller() {
      readyFile = '';
      return setState(availableState({ status: 'error', error: 'download' }));
    },
    finishInstall(next) {
      return setState(next);
    },
    // A previous install attempt that did not take effect keeps its verified file for a retry.
    restoreInstall({ version, filePath, asset, status = 'ready', ...extra }) {
      const ext = platform === 'darwin' ? '.dmg' : platform === 'win32' ? '.exe' : '';
      if (!newerVersion(version, currentVersion) || !validInstallerAsset(asset) || asset.ext !== ext
        || filePath !== path.join(downloadDir, `update-${version}${ext}`) || cannotRun(asset)) return state;
      release = { version, asset };
      readyFile = filePath;
      return setState({ status, version, ...extra });
    },
    dismiss() {
      if (!release || ['downloading', 'ready', 'installing', 'manual'].includes(state.status)) return state;
      cache.dismissed = release.version;
      save();
      return setState({ status: 'idle' });
    },
  };
}
module.exports = { createReleaseUpdates, newerVersion, olderSystem, parseMinimumOs, pickInstallerAsset, verifyInstallerFile, RELEASES_URL };
