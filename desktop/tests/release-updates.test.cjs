const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { newerVersion, createReleaseUpdates } = require('../release-updates');

test('version comparison rejects prereleases and compares numeric segments', () => {
  assert.equal(newerVersion('v0.1.100', '0.1.32'), true);
  for (const version of ['0.1.9', '0.1.32', '0.2.0-beta.1', 'garbage']) assert.equal(newerVersion(version, '0.1.32'), false);
});
test('update check coalesces requests, persists dismissal and ignores untrusted URLs', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  let calls = 0;
  const opts = { currentVersion: '0.1.32', cachePath: path.join(dir, 'cache.json'), now: () => 1000000000,
    fetchImpl: async () => { calls++; return { ok: true, json: async () => ({ tag_name: 'v0.2.0', html_url: 'https://evil.example/' }) }; } };
  const service = createReleaseUpdates(opts);
  const [a,b] = await Promise.all([service.check(), service.check()]);
  assert.deepEqual(a,b); assert.equal(calls,1); assert.equal(a.url, 'https://github.com/kr-ericshim/drum-score-capture-tool/releases/tag/v0.2.0');
  service.dismiss();
  assert.equal(await createReleaseUpdates(opts).check(), null); assert.equal(calls,1);
});
test('offline, rate limited and prerelease responses never block startup', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-errors-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  for (const [i,fetchImpl] of [async () => { throw new Error('offline'); }, async () => ({ok:false,status:403}), async () => ({ok:true,json:async()=>({tag_name:'v9.0.0',prerelease:true})})].entries()) {
    assert.equal(await createReleaseUpdates({currentVersion:'0.1.32',cachePath:path.join(dir,String(i)),fetchImpl}).check(),null);
  }
});
