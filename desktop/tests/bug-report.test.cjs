const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveBugReportEndpoint, buildBugReportPayload, sendBugReport, buildIssueUrl } = require('../bug-report');

test('only https relays, or a local http relay, are accepted as endpoints', () => {
  assert.equal(resolveBugReportEndpoint({ DRUMSHEET_BUG_REPORT_URL: 'https://relay.example/reports' }), 'https://relay.example/reports');
  assert.equal(resolveBugReportEndpoint({ DRUMSHEET_BUG_REPORT_URL: 'http://127.0.0.1:8787/reports' }), 'http://127.0.0.1:8787/reports');
  assert.equal(resolveBugReportEndpoint({ DRUMSHEET_BUG_REPORT_URL: 'http://relay.example/reports' }), '');
  assert.equal(resolveBugReportEndpoint({ DRUMSHEET_BUG_REPORT_URL: 'not a url' }), '');
});

test('the payload carries only what the user chose to include', () => {
  const prepared = { diagnostics: 'reviewed log', screenshot: Buffer.from('jpeg') };
  const meta = { version: '0.1.35', locale: 'en' };
  const none = buildBugReportPayload({ description: '  broken\r\n', email: '' }, prepared, meta).payload;
  assert.equal(none.description, 'broken');
  assert.equal(none.diagnostics, '');
  assert.equal(none.screenshot, '');
  assert.equal(none.appVersion, '0.1.35');
  const all = buildBugReportPayload({ description: 'x', includeDiagnostics: true, includeScreenshot: true }, prepared, meta).payload;
  assert.equal(all.diagnostics, 'reviewed log');
  assert.equal(all.screenshot, Buffer.from('jpeg').toString('base64'));
});

test('an empty description or a malformed reply address is sent back to the user', () => {
  assert.deepEqual(buildBugReportPayload({ description: '  ' }), { error: 'description' });
  assert.deepEqual(buildBugReportPayload({ description: 'x', email: 'nope' }), { error: 'email' });
});

test('relay responses map to the dialog states', async () => {
  const reply = (status) => async () => ({ ok: status < 300, status });
  const send = (fetchImpl, endpoint = 'https://relay.example/reports') => sendBugReport({ description: 'x' }, { endpoint, fetchImpl });
  assert.deepEqual(await send(reply(200)), { status: 'sent' });
  assert.deepEqual(await send(reply(429)), { status: 'error', reason: 'rate-limited' });
  assert.deepEqual(await send(reply(400)), { status: 'error', reason: 'rejected' });
  assert.deepEqual(await send(reply(502)), { status: 'error', reason: 'server' });
  assert.deepEqual(await send(async () => { throw new Error('offline'); }), { status: 'error', reason: 'network' });
  assert.deepEqual(await send(reply(200), ''), { status: 'error', reason: 'not-configured' });
});

test('a relay that never answers times out as a network failure', async () => {
  const hang = (_, init) => new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(new Error('aborted'))));
  assert.deepEqual(await sendBugReport({}, { endpoint: 'https://relay.example/reports', fetchImpl: hang, timeoutMs: 10 }), { status: 'error', reason: 'network' });
});

test('the GitHub fallback pre-fills the issue but never the reply address', () => {
  const url = new URL(buildIssueUrl({ description: 'Pages missing\nmore', steps: '1. capture', email: 'me@example.com', includeDiagnostics: true }, { version: '0.1.35' }));
  assert.equal(url.origin + url.pathname, 'https://github.com/kr-ericshim/drum-score-capture-tool/issues/new');
  assert.equal(url.searchParams.get('title'), 'Pages missing');
  const body = url.searchParams.get('body');
  assert.match(body, /Pages missing\nmore/);
  assert.match(body, /1\. capture/);
  assert.match(body, /Drum Sheet Capture 0\.1\.35/);
  assert.match(body, /### Diagnostics/);
  assert.equal(body.includes('me@example.com'), false);
});
