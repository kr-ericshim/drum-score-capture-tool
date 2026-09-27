const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { execFileSync, spawnSync } = require('node:child_process');
const {
  MAC_SWAP_SCRIPT, resolveMacAppBundle, macUpdateWorkDir, macInstallBlocker, prepareMacUpdate, launchMacSwap,
  launchWindowsInstaller, writeInstallMarker, takeInstallMarker,
} = require('../release-install');

const macOnly = process.platform !== 'darwin' && 'bash, hdiutil and codesign swaps are macOS only';

function tempDir(t) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'release-install-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function fakeSpawn(calls, { fail = false } = {}) {
  return (command, args, options) => {
    calls.push({ command, args, options });
    const child = new EventEmitter();
    child.unref = () => {};
    setImmediate(() => child.emit(fail ? 'error' : 'spawn', fail ? new Error('ENOENT') : undefined));
    return child;
  };
}

function makeBundle(parent, { version, id = 'com.ericshim.drumsheetcapture', name = 'Drum Sheet Capture.app' }) {
  const bundle = path.join(parent, name);
  fs.mkdirSync(path.join(bundle, 'Contents', 'MacOS'), { recursive: true });
  fs.writeFileSync(path.join(bundle, 'Contents', 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Drum Sheet Capture</string>
<key>CFBundleIdentifier</key><string>${id}</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>${version}</string>
</dict></plist>`);
  fs.writeFileSync(path.join(bundle, 'Contents', 'MacOS', 'Drum Sheet Capture'), `#!/bin/sh\necho ${version}\n`, { mode: 0o755 });
  return bundle;
}

const bundleVersion = bundle => /echo (\S+)/.exec(fs.readFileSync(path.join(bundle, 'Contents', 'MacOS', 'Drum Sheet Capture'), 'utf8'))[1];

// Runs the real swap script with a stub `open` that logs its argument and can fail on chosen calls.
function runSwap(dir, { pid = '999999', target, staged, backup, dmg, failOpenCalls = [] }) {
  const bin = path.join(dir, 'bin');
  fs.mkdirSync(bin, { recursive: true });
  const log = path.join(dir, 'opened.log');
  fs.writeFileSync(path.join(bin, 'open'), `#!/bin/sh
n=$(($(wc -l < "${log}" 2>/dev/null || echo 0) + 1))
echo "$1" >> "${log}"
case " ${failOpenCalls.join(' ')} " in *" $n "*) exit 1;; esac
exit 0
`, { mode: 0o755 });
  const script = path.join(dir, 'swap.sh');
  fs.writeFileSync(script, MAC_SWAP_SCRIPT);
  const result = spawnSync('/bin/bash', [script, String(pid), target, staged, backup, dmg], {
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, encoding: 'utf8',
  });
  const opened = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n') : [];
  return { status: result.status, opened };
}

function swapFixture(t) {
  const dir = tempDir(t);
  const apps = path.join(dir, 'Applications');
  const target = makeBundle(apps, { version: '0.1.34' });
  const workDir = macUpdateWorkDir(target);
  const staged = makeBundle(workDir, { version: '0.2.0' });
  const dmg = path.join(dir, 'update-0.2.0.dmg');
  fs.writeFileSync(dmg, 'dmg');
  return { dir, target, staged, backup: path.join(workDir, 'previous.app'), dmg };
}

test('mac bundle paths are computed with POSIX rules on every platform', () => {
  assert.equal(resolveMacAppBundle('/Applications/Drum Sheet Capture.app/Contents/MacOS/Drum Sheet Capture'), '/Applications/Drum Sheet Capture.app');
  assert.equal(resolveMacAppBundle('/usr/local/bin/electron'), '');
  assert.equal(macUpdateWorkDir('/Applications/Drum Sheet Capture.app'), '/Applications/.Drum Sheet Capture Update');
});

test('unsafe locations and a kept backup fall back to the DMG', () => {
  const fsOk = { accessSync() {}, existsSync: () => false };
  assert.equal(macInstallBlocker('', fsOk), 'not-bundle');
  assert.equal(macInstallBlocker('/private/var/folders/x/AppTranslocation/ABC/d/Drum Sheet Capture.app', fsOk), 'translocated');
  assert.equal(macInstallBlocker('/Volumes/Drum Sheet Capture 0.1.34/Drum Sheet Capture.app', fsOk), 'disk-image');
  assert.equal(macInstallBlocker('/Applications/Drum Sheet Capture.app', { ...fsOk, accessSync() { throw new Error('EACCES'); } }), 'not-writable');
  const seen = [];
  const withBackup = { ...fsOk, existsSync: p => { seen.push(p); return true; } };
  assert.equal(macInstallBlocker('/Applications/Drum Sheet Capture.app', withBackup), 'backup-present');
  assert.deepEqual(seen, ['/Applications/.Drum Sheet Capture Update/previous.app']);
  assert.equal(macInstallBlocker('/Applications/Drum Sheet Capture.app', fsOk), '');
});

test('windows installer runs silently in update mode and relaunches the app', async () => {
  const calls = [];
  await launchWindowsInstaller({ installerPath: 'C:\\updates\\update-0.2.0.exe', spawnImpl: fakeSpawn(calls) });
  assert.deepEqual(calls[0].args, ['--updated', '/S', '--force-run']);
  assert.equal(calls[0].options.detached, true);
  await assert.rejects(launchWindowsInstaller({ installerPath: 'missing.exe', spawnImpl: fakeSpawn([], { fail: true }) }));
});

test('launchMacSwap starts the script detached with the app pid, paths and DMG', async t => {
  const dir = tempDir(t);
  const calls = [];
  await launchMacSwap({
    pid: 42, bundlePath: '/Applications/A.app', stagedPath: '/Applications/.A Update/A.app', backupPath: '/Applications/.A Update/previous.app',
    dmgPath: `${dir}/update.dmg`, scriptDir: dir, spawnImpl: fakeSpawn(calls),
  });
  assert.equal(calls[0].command, '/bin/bash');
  assert.deepEqual(calls[0].args, [path.join(dir, 'swap-app.sh'), '42', '/Applications/A.app', '/Applications/.A Update/A.app', '/Applications/.A Update/previous.app', `${dir}/update.dmg`]);
  assert.equal(fs.readFileSync(path.join(dir, 'swap-app.sh'), 'utf8'), MAC_SWAP_SCRIPT);
});

test('install marker is read once and ignored when malformed', t => {
  const dir = tempDir(t);
  const marker = path.join(dir, 'update-install.json');
  writeInstallMarker(marker, { version: '0.2.0', filePath: '/x/update-0.2.0.dmg' });
  assert.deepEqual(takeInstallMarker(marker), { version: '0.2.0', filePath: '/x/update-0.2.0.dmg' });
  assert.equal(takeInstallMarker(marker), null);
  fs.writeFileSync(marker, '{"version": 3}');
  assert.equal(takeInstallMarker(marker), null);
});

test('swap waits for the running app to exit, swaps by rename and keeps the backup for the new version to remove', { skip: macOnly }, t => {
  const f = swapFixture(t);
  // Orphaned like the quitting app, so launchd reaps it and `kill -0` sees it exit.
  const pid = execFileSync('/bin/bash', ['-c', '/bin/sleep 1.5 >/dev/null 2>&1 & echo $!'], { encoding: 'utf8' }).trim();
  const started = Date.now();
  const { status, opened } = runSwap(f.dir, { ...f, pid });
  assert.equal(status, 0);
  assert.ok(Date.now() - started >= 1400, 'the swap did not start before the app exited');
  assert.equal(bundleVersion(f.target), '0.2.0');
  assert.equal(bundleVersion(f.backup), '0.1.34');
  assert.equal(fs.existsSync(f.staged), false);
  assert.deepEqual(opened, [f.target]);
});

test('swap restores the old app, opens the DMG and fails when the new bundle cannot be moved in', { skip: macOnly }, t => {
  const f = swapFixture(t);
  fs.rmSync(f.staged, { recursive: true });
  const { status, opened } = runSwap(f.dir, f);
  assert.equal(status, 1);
  assert.equal(bundleVersion(f.target), '0.1.34');
  assert.equal(fs.existsSync(f.backup), false);
  assert.deepEqual(opened, [f.target, f.dmg]);
});

test('swap rolls back when the new app cannot be opened', { skip: macOnly }, t => {
  const f = swapFixture(t);
  const { status, opened } = runSwap(f.dir, { ...f, failOpenCalls: [1] });
  assert.equal(status, 1);
  assert.equal(bundleVersion(f.target), '0.1.34');
  assert.equal(fs.existsSync(f.backup), false);
  assert.equal(fs.existsSync(f.staged), false);
  assert.deepEqual(opened, [f.target, f.target, f.dmg]);
});

test('swap never overwrites a backup kept from an earlier failure', { skip: macOnly }, t => {
  const f = swapFixture(t);
  makeBundle(path.dirname(f.backup), { version: '0.1.30', name: 'previous.app' });
  const { status, opened } = runSwap(f.dir, f);
  assert.equal(status, 1);
  assert.equal(bundleVersion(f.target), '0.1.34');
  assert.equal(bundleVersion(f.backup), '0.1.30');
  assert.deepEqual(opened, [f.target, f.dmg]);
});

test('DMG staging lands beside the app and rejects the wrong version or app', { skip: macOnly }, async t => {
  const dir = tempDir(t);
  const current = makeBundle(path.join(dir, 'Applications'), { version: '0.1.34' });
  function buildDmg(name, bundleOptions) {
    const source = path.join(dir, `${name}-src`);
    const bundle = makeBundle(source, bundleOptions);
    execFileSync('/usr/bin/codesign', ['--force', '--sign', '-', bundle]);
    const dmg = path.join(dir, `${name}.dmg`);
    execFileSync('/usr/bin/hdiutil', ['create', '-quiet', '-fs', 'HFS+', '-srcfolder', source, '-volname', name, dmg]);
    return dmg;
  }
  const workDir = macUpdateWorkDir(current);

  const good = buildDmg('good', { version: '0.2.0' });
  const { stagedPath, backupPath } = await prepareMacUpdate({ dmgPath: good, bundlePath: current, expectedVersion: '0.2.0' });
  assert.equal(stagedPath, path.join(workDir, 'Drum Sheet Capture.app'));
  assert.equal(backupPath, path.join(workDir, 'previous.app'));
  assert.equal(bundleVersion(stagedPath), '0.2.0');

  await assert.rejects(prepareMacUpdate({ dmgPath: good, bundlePath: current, expectedVersion: '0.3.0' }), /version/);
  assert.equal(fs.existsSync(stagedPath), false, 'a rejected image leaves nothing staged');
  const foreign = buildDmg('foreign', { version: '0.2.0', id: 'com.example.other' });
  await assert.rejects(prepareMacUpdate({ dmgPath: foreign, bundlePath: current, expectedVersion: '0.2.0' }), /different app/);
});
