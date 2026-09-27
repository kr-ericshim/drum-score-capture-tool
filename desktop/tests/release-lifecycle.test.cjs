const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');
const { createRequire } = require('node:module');
const releaseUpdates = require('../release-updates');
const mainPath = path.resolve(__dirname, '../main.js');
const localRequire = createRequire(mainPath);
const bytes = Buffer.from('verified installer');
const asset = {
  url: 'https://github.com/kr-ericshim/drum-score-capture-tool/releases/download/v0.2.0/update.exe',
  size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), ext: '.exe',
};

function mainHarness(t, { version = '0.1.35', busy = false, failSpawn = false } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-lifecycle-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const filePath = path.join(dir, 'updates', 'update-0.2.0.exe');
  fs.mkdirSync(path.dirname(filePath));
  fs.writeFileSync(filePath, bytes);
  fs.writeFileSync(path.join(dir, 'update-install.json'), JSON.stringify({ version: '0.2.0', filePath, asset }));
  const events = [];
  const app = new EventEmitter();
  Object.assign(app, { isPackaged: true, getPath: () => dir, getVersion: () => version,
    whenReady: () => ({ then() {} }), quit: () => events.push('quit') });
  const ipcMain = new EventEmitter();
  ipcMain.handle = () => {};
  const context = {
    require(name) {
      if (name === 'electron') return { app, ipcMain, BrowserWindow() {}, dialog: {}, shell: {}, clipboard: {} };
      if (name === './release-updates') return { ...releaseUpdates, createReleaseUpdates: options => releaseUpdates.createReleaseUpdates({ ...options, platform: 'win32' }) };
      if (name === './release-install') return { ...localRequire(name), launchWindowsInstaller: async () => {
        events.push('spawn');
        if (failSpawn) throw new Error('spawn failed');
      } };
      return localRequire(name);
    },
    process: { env: {}, platform: 'win32', pid: 42, execPath: path.join(dir, 'app.exe') },
    __dirname: path.dirname(mainPath), console, Buffer, URL, AbortSignal, setTimeout, clearTimeout,
    setImmediate: callback => callback(),
    fetch: async url => {
      const acquire = url.endsWith('/update-lock');
      events.push(acquire ? 'lock' : 'unlock');
      return { ok: !(acquire && busy), json: async () => ({ locked: acquire }) };
    },
    events,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(mainPath, 'utf8') + `
    backendProcess = {}; backendReady = true;
    stopBackend = async () => { events.push('stop'); backendProcess = null; };
    startBackendAndWait = async () => { events.push('restart'); };
    this.service = getReleaseUpdates();
    this.install = installReleaseUpdate;
  `, context, { filename: mainPath });
  return { context, events, filePath };
}

test('main rejects busy backend work and releases the update lock', async t => {
  const { context, events } = mainHarness(t, { busy: true });
  assert.equal((await context.install()).error, 'busy');
  assert.deepEqual(events, ['lock', 'unlock']);
});

test('main claims one installer and locks the backend before stopping it', async t => {
  const { context, events } = mainHarness(t);
  await Promise.all([context.install(), context.install()]);
  assert.deepEqual(events, ['lock', 'stop', 'spawn', 'quit']);
});

test('main restarts processing after a failed installer spawn', async t => {
  const { context, events } = mainHarness(t, { failSpawn: true });
  assert.equal((await context.install()).error, 'install');
  assert.deepEqual(events, ['lock', 'stop', 'spawn', 'restart']);
});

test('main does not launch a modified restored installer', async t => {
  const { context, events, filePath } = mainHarness(t);
  fs.writeFileSync(filePath, 'corrupted');
  assert.equal((await context.install()).error, 'download');
  assert.deepEqual(events, []);
});

test('main does not offer an older installer after a newer manual installation', t => {
  const { context } = mainHarness(t, { version: '0.3.0' });
  assert.equal(context.service.getState().status, 'idle');
  assert.equal(context.service.beginInstall(), null);
});

test('a fresh preload restores its POST gate from the check response without a state event', async () => {
  let api;
  let requests = 0;
  const ipcRenderer = new EventEmitter();
  ipcRenderer.sendSync = () => '';
  ipcRenderer.invoke = async () => ({ status: 'installing' });
  const context = {
    require: () => ({ ipcRenderer, webUtils: {}, contextBridge: { exposeInMainWorld: (_, value) => { api = value; } } }),
    process: { env: {} }, URL, AbortSignal,
    fetch: async () => { requests++; return { ok: true, status: 200, json: async () => ({}) }; },
  };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../preload.js'), 'utf8'), context);
  await api.checkReleaseUpdate();
  await assert.rejects(api.requestJson('/jobs', { method: 'POST' }), /update is being installed/);
  assert.equal(requests, 0);
  await api.requestJson('/maintenance/activity');
  assert.equal(requests, 1);
});
