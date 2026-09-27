const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile, spawn } = require('node:child_process');

const posix = path.posix;

// Runs after the app has quit. Every move is a rename inside the app's own folder, so a failure cannot leave
// half a copy at the install path. The old bundle stays as the backup until the new version reports it started.
const MAC_SWAP_SCRIPT = `#!/bin/bash
pid="$1"; target="$2"; staged="$3"; backup="$4"; dmg="$5"
fail() { rm -rf "$staged"; if [ -e "$dmg" ]; then open "$dmg"; fi; exit 1; }
waited=0
while kill -0 "$pid" 2>/dev/null; do
  if [ "$waited" -ge 240 ]; then fail; fi
  sleep 0.25; waited=$((waited + 1))
done
sleep 1
if [ -e "$backup" ]; then open "$target"; fail; fi
if ! mv "$target" "$backup"; then open "$target"; fail; fi
if ! mv "$staged" "$target"; then
  if [ ! -e "$target" ] && mv "$backup" "$target"; then open "$target"; fi
  fail
fi
if ! open "$target"; then
  if mv "$target" "$staged" && mv "$backup" "$target"; then open "$target"; fi
  fail
fi
`;

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { timeout: 120000 }, (error, stdout) => (error ? reject(error) : resolve(String(stdout))));
  });
}

function resolveMacAppBundle(execPath) {
  const bundle = posix.resolve(String(execPath), '..', '..', '..');
  return bundle.endsWith('.app') ? bundle : '';
}

// Hidden sibling folder: same volume as the app, so the swap never falls back to copy-and-delete.
function macUpdateWorkDir(bundlePath) {
  return posix.join(posix.dirname(bundlePath), `.${posix.basename(bundlePath, '.app')} Update`);
}

// Returns why the bundle cannot be replaced in place; the caller then opens the DMG instead.
function macInstallBlocker(bundlePath, fsImpl = fs) {
  if (!bundlePath) return 'not-bundle';
  if (bundlePath.includes('/AppTranslocation/')) return 'translocated';
  if (bundlePath.startsWith('/Volumes/')) return 'disk-image';
  try {
    fsImpl.accessSync(posix.dirname(bundlePath), fs.constants.W_OK);
    fsImpl.accessSync(bundlePath, fs.constants.W_OK);
  } catch (_) {
    return 'not-writable';
  }
  // A backup kept from an earlier failed swap may be the only intact copy of the app.
  if (fsImpl.existsSync(posix.join(macUpdateWorkDir(bundlePath), 'previous.app'))) return 'backup-present';
  return '';
}

async function readPlistValue(bundlePath, key, runImpl) {
  return (await runImpl('/usr/bin/plutil', ['-extract', key, 'raw', '-o', '-', posix.join(bundlePath, 'Contents', 'Info.plist')])).trim();
}

async function prepareMacUpdate({ dmgPath, bundlePath, expectedVersion, runImpl = run }) {
  const workDir = macUpdateWorkDir(bundlePath);
  const staged = posix.join(workDir, posix.basename(bundlePath));
  fs.rmSync(staged, { recursive: true, force: true });
  fs.mkdirSync(workDir, { recursive: true });
  const mountPoint = fs.mkdtempSync(path.join(os.tmpdir(), 'drumsheet-update-'));
  await runImpl('/usr/bin/hdiutil', ['attach', dmgPath, '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', mountPoint]);
  try {
    const source = path.join(mountPoint, posix.basename(bundlePath));
    if (!fs.existsSync(source)) throw new Error('update image does not contain the app');
    await runImpl('/usr/bin/ditto', [source, staged]);
  } finally {
    await runImpl('/usr/bin/hdiutil', ['detach', mountPoint, '-force']).catch(() => {});
    fs.rmSync(mountPoint, { recursive: true, force: true });
  }
  try {
    await runImpl('/usr/bin/codesign', ['--verify', '--deep', '--strict', staged]);
    const [version, stagedId, currentId] = await Promise.all([
      readPlistValue(staged, 'CFBundleShortVersionString', runImpl),
      readPlistValue(staged, 'CFBundleIdentifier', runImpl),
      readPlistValue(bundlePath, 'CFBundleIdentifier', runImpl),
    ]);
    if (version !== expectedVersion) throw new Error(`update image version ${version} is not ${expectedVersion}`);
    if (!stagedId || stagedId !== currentId) throw new Error('update image belongs to a different app');
  } catch (error) {
    fs.rmSync(staged, { recursive: true, force: true });
    throw error;
  }
  return { stagedPath: staged, backupPath: posix.join(workDir, 'previous.app') };
}

// Resolves once the detached process really started, so the app never quits without an installer running.
function startDetached(spawnImpl, command, args) {
  return new Promise((resolve, reject) => {
    const child = spawnImpl(command, args, { detached: true, stdio: 'ignore' });
    child.once('error', reject);
    child.once('spawn', () => { child.unref(); resolve(); });
  });
}

function launchMacSwap({ pid, bundlePath, stagedPath, backupPath, dmgPath, scriptDir, spawnImpl = spawn }) {
  const scriptPath = path.join(scriptDir, 'swap-app.sh');
  fs.writeFileSync(scriptPath, MAC_SWAP_SCRIPT, { mode: 0o700 });
  return startDetached(spawnImpl, '/bin/bash', [scriptPath, String(pid), bundlePath, stagedPath, backupPath, dmgPath]);
}

// Same flags electron-updater passes: silent install that stops the old processes and relaunches the app.
function launchWindowsInstaller({ installerPath, spawnImpl = spawn }) {
  return startDetached(spawnImpl, installerPath, ['--updated', '/S', '--force-run']);
}

// The next launch compares its own version with this record to learn whether the install took effect.
function writeInstallMarker(markerPath, { version, filePath, asset }) {
  fs.writeFileSync(markerPath, JSON.stringify({ version, filePath, asset }));
}

function takeInstallMarker(markerPath) {
  let marker = null;
  try { marker = JSON.parse(fs.readFileSync(markerPath, 'utf8')); } catch (_) { return null; }
  try { fs.rmSync(markerPath, { force: true }); } catch (_) { /* read once per launch at most */ }
  if (!marker || typeof marker.version !== 'string' || typeof marker.filePath !== 'string') return null;
  return marker;
}

module.exports = {
  MAC_SWAP_SCRIPT,
  resolveMacAppBundle,
  macUpdateWorkDir,
  macInstallBlocker,
  prepareMacUpdate,
  launchMacSwap,
  launchWindowsInstaller,
  writeInstallMarker,
  takeInstallMarker,
};
