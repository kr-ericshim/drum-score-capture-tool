const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Writable } = require('node:stream');
const { newerVersion, pickInstallerAsset, createReleaseUpdates, verifyInstallerFile } = require('../release-updates');

const DOWNLOAD = 'https://github.com/kr-ericshim/drum-score-capture-tool/releases/download/v0.2.0/';
const PAYLOAD = Buffer.from('installer bytes '.repeat(4096));
const SHA = crypto.createHash('sha256').update(PAYLOAD).digest('hex');

function release(overrides = {}) {
  return {
    tag_name: 'v0.2.0',
    assets: [
      { name: 'Drum.Sheet.Capture-0.2.0-arm64.dmg', size: PAYLOAD.length, digest: `sha256:${SHA}`, browser_download_url: `${DOWNLOAD}Drum.Sheet.Capture-0.2.0-arm64.dmg` },
      { name: 'Drum.Sheet.Capture.Setup.0.2.0.exe', size: PAYLOAD.length, digest: `sha256:${SHA}`, browser_download_url: `${DOWNLOAD}Drum.Sheet.Capture.Setup.0.2.0.exe` },
      { name: 'ffmpeg-8.1.2-darwin-arm64-source.tar.gz', size: 10, digest: `sha256:${'0'.repeat(64)}`, browser_download_url: `${DOWNLOAD}ffmpeg.tar.gz` },
    ],
    ...overrides,
  };
}

function fakeFetch({ latest = release(), body = PAYLOAD, calls = [] } = {}) {
  return async (url) => {
    calls.push(url);
    if (url.includes('api.github.com')) return { ok: true, json: async () => latest };
    return {
      ok: true,
      body: (async function* chunks() { for (let i = 0; i < body.length; i += 8192) yield body.subarray(i, i + 8192); })(),
    };
  };
}

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function service(dir, overrides = {}) {
  return createReleaseUpdates({
    currentVersion: '0.1.34', cachePath: path.join(dir, 'cache.json'), downloadDir: path.join(dir, 'updates'),
    platform: 'darwin', arch: 'arm64', fetchImpl: fakeFetch(), ...overrides,
  });
}

test('version comparison rejects prereleases and compares numeric segments', () => {
  assert.equal(newerVersion('v0.1.100', '0.1.32'), true);
  for (const version of ['0.1.9', '0.1.32', '0.2.0-beta.1', 'garbage']) assert.equal(newerVersion(version, '0.1.32'), false);
});

test('installer asset must match this machine and carry a GitHub digest from this repository', () => {
  const { assets } = release();
  assert.equal(pickInstallerAsset(assets, 'darwin', 'arm64').url, `${DOWNLOAD}Drum.Sheet.Capture-0.2.0-arm64.dmg`);
  assert.equal(pickInstallerAsset(assets, 'win32', 'x64').ext, '.exe');
  assert.equal(pickInstallerAsset(assets, 'darwin', 'x64'), null);
  assert.equal(pickInstallerAsset(assets, 'linux', 'x64'), null);
  assert.equal(pickInstallerAsset([{ ...assets[0], digest: undefined }], 'darwin', 'arm64'), null);
  assert.equal(pickInstallerAsset([{ ...assets[0], browser_download_url: 'https://evil.example/x-arm64.dmg' }], 'darwin', 'arm64'), null);
});

test('startup check runs once per launch and honours a skipped version; a manual check does not', async t => {
  const dir = tempDir(t);
  const calls = [];
  const opts = { fetchImpl: fakeFetch({ calls }) };
  const updates = service(dir, opts);
  const [a, b] = await Promise.all([updates.check(), updates.check()]);
  assert.deepEqual(a, b);
  assert.equal(calls.length, 1);
  assert.equal(a.status, 'available');
  assert.equal(a.canInstall, true);
  assert.equal(a.url, 'https://github.com/kr-ericshim/drum-score-capture-tool/releases/tag/v0.2.0');
  assert.equal((await updates.check()).status, 'available');
  assert.equal(calls.length, 1);

  updates.dismiss();
  const relaunched = service(dir, opts);
  assert.equal((await relaunched.check()).status, 'idle');
  assert.equal(calls.length, 2, 'every launch asks GitHub once');
  const manual = await relaunched.check({ manual: true });
  assert.equal(manual.status, 'available');
  assert.equal(manual.manual, true);
});

test('offline, rate limited and prerelease responses stay silent at startup and report on a manual check', async t => {
  const dir = tempDir(t);
  const failures = [
    async () => { throw new Error('offline'); },
    async () => ({ ok: false, status: 403 }),
  ];
  for (const [i, fetchImpl] of failures.entries()) {
    const cachePath = path.join(dir, String(i));
    assert.equal((await service(dir, { cachePath, fetchImpl }).check()).status, 'idle');
    const manual = await service(dir, { cachePath, fetchImpl }).check({ manual: true });
    assert.equal(manual.status, 'error');
    assert.equal(manual.error, 'check');
  }
  const prerelease = fakeFetch({ latest: release({ tag_name: 'v9.0.0', prerelease: true }) });
  assert.equal((await service(dir, { fetchImpl: prerelease }).check({ manual: true })).status, 'current');
  assert.equal((await service(dir, { currentVersion: '0.2.0' }).check({ manual: true })).status, 'current');
});

test('a release without a usable installer falls back to the download page', async t => {
  const dir = tempDir(t);
  const noDigest = release();
  noDigest.assets = noDigest.assets.map(asset => ({ ...asset, digest: null }));
  assert.equal((await service(dir, { fetchImpl: fakeFetch({ latest: noDigest }) }).check()).canInstall, false);
  assert.equal((await service(dir, { installSupported: false }).check()).canInstall, false);
});

test('download verifies size and sha256 before reporting ready, with progress along the way', async t => {
  const dir = tempDir(t);
  const states = [];
  const updates = service(dir, { onState: state => states.push(state) });
  await updates.check();
  const ready = await updates.download();
  assert.equal(ready.status, 'ready');
  assert.equal(ready.version, '0.2.0');
  assert.equal(ready.filePath, undefined, 'the renderer never sees local paths');
  const file = updates.getInstallerFile();
  assert.equal(path.basename(file), 'update-0.2.0.dmg');
  assert.deepEqual(fs.readFileSync(file), PAYLOAD);
  const progress = states.filter(state => state.status === 'downloading').map(state => state.progress);
  assert.equal(progress[0], 0);
  assert.equal(progress.at(-1), 100);
  assert.deepEqual(progress, [...progress].sort((x, y) => x - y));
  assert.equal((await updates.check({ manual: true })).status, 'ready', 'a finished download is not discarded by another check');
});

test('a corrupted or truncated download is deleted and reported as a retryable error', async t => {
  for (const body of [Buffer.from(PAYLOAD).fill(65, 0, 10), PAYLOAD.subarray(0, 100)]) {
    const dir = tempDir(t);
    const updates = service(dir, { fetchImpl: fakeFetch({ body }) });
    await updates.check();
    const result = await updates.download();
    assert.equal(result.status, 'error');
    assert.equal(result.error, 'download');
    assert.equal(result.canInstall, true);
    assert.equal(updates.getInstallerFile(), '');
    assert.equal(updates.beginInstall(), null);
    assert.deepEqual(fs.readdirSync(path.join(dir, 'updates')), []);
  }
});

test('a disk write error ends the download as a retryable error instead of hanging', async t => {
  const dir = tempDir(t);
  const failingDisk = () => new Writable({
    highWaterMark: 1,
    write(_chunk, _encoding, callback) { setImmediate(() => callback(Object.assign(new Error('no space'), { code: 'ENOSPC' }))); },
  });
  const updates = service(dir, { createWriteStream: failingDisk });
  await updates.check();
  const result = await Promise.race([
    updates.download(),
    new Promise((_, reject) => setTimeout(() => reject(new Error('download never settled')), 2000)),
  ]);
  assert.equal(result.status, 'error');
  assert.equal(result.error, 'download');
});

test('a manual check that joins the startup request still shows a skipped version and reports failures', async t => {
  const dir = tempDir(t);
  fs.writeFileSync(path.join(dir, 'cache.json'), JSON.stringify({ dismissed: '0.2.0' }));
  let release_ = () => {};
  const held = async (url) => {
    await new Promise(resolve => { release_ = resolve; });
    return fakeFetch()(url);
  };
  const updates = service(dir, { fetchImpl: held });
  const startup = updates.check();
  const manual = updates.check({ manual: true });
  assert.equal(updates.getState().manual, true);
  release_();
  assert.equal((await manual).status, 'available');
  assert.equal((await startup).status, 'available');

  const offline = service(tempDir(t), { fetchImpl: async () => { await new Promise(r => setImmediate(r)); throw new Error('offline'); } });
  const quiet = offline.check();
  const asked = offline.check({ manual: true });
  assert.equal((await asked).status, 'error');
  await quiet;
});

test('install is claimed once, and download or dismiss cannot disturb it', async t => {
  const dir = tempDir(t);
  const updates = service(dir);
  await updates.check();
  await updates.download();
  const claim = updates.beginInstall();
  assert.equal(claim.version, '0.2.0');
  assert.equal(path.basename(claim.filePath), 'update-0.2.0.dmg');
  assert.equal(updates.getState().status, 'installing');
  assert.equal(updates.beginInstall(), null, 'a second install call gets nothing to run');
  assert.equal((await updates.download()).status, 'installing');
  assert.equal(updates.dismiss().status, 'installing');
  assert.equal((await updates.check({ manual: true })).status, 'installing');
  assert.ok(fs.existsSync(claim.filePath), 'the installer file survives the attempts above');

  updates.finishInstall({ status: 'ready', version: '0.2.0', error: 'busy' });
  assert.ok(updates.beginInstall(), 'returning to ready allows a later retry');
});

test('a failed earlier install is restored with its file for a retry or the manual installer', async t => {
  const dir = tempDir(t);
  const updates = service(dir);
  const filePath = path.join(dir, 'updates', 'update-0.2.0.dmg');
  const asset = pickInstallerAsset(release().assets, 'darwin', 'arm64');
  const restored = updates.restoreInstall({ version: '0.2.0', filePath, asset, status: 'manual', reason: 'swap-failed' });
  assert.equal(restored.status, 'manual');
  assert.equal(restored.reason, 'swap-failed');
  assert.equal(updates.getInstallerFile(), filePath);
  assert.equal((await updates.check()).status, 'manual', 'the startup check does not hide the fallback');
});

test('restored installers must be newer and carry valid integrity metadata inside the download folder', t => {
  const dir = tempDir(t);
  const asset = pickInstallerAsset(release().assets, 'darwin', 'arm64');
  const filePath = path.join(dir, 'updates', 'update-0.2.0.dmg');
  for (const candidate of [
    { version: '0.1.34', filePath, asset },
    { version: '0.1.33', filePath, asset },
    { version: '0.2.0', filePath },
    { version: '0.2.0', filePath: path.join(dir, 'outside.dmg'), asset },
  ]) {
    const updates = service(dir);
    assert.equal(updates.restoreInstall(candidate).status, 'idle');
    assert.equal(updates.beginInstall(), null);
  }
});

test('a changed cached installer fails verification and can be downloaded again', async t => {
  const dir = tempDir(t);
  const updates = service(dir);
  await updates.check();
  await updates.download();
  const installer = updates.getInstaller();
  assert.equal(await verifyInstallerFile(installer), true);
  fs.writeFileSync(installer.filePath, Buffer.from(PAYLOAD).fill(65, 0, 10));
  assert.equal(await verifyInstallerFile(installer), false);
  updates.invalidateInstaller();
  assert.equal(updates.beginInstall(), null);
  assert.equal((await updates.download()).status, 'ready');
  assert.equal(await verifyInstallerFile(updates.getInstaller()), true);
});
