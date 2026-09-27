const test = require('node:test');
const assert = require('node:assert/strict');
const { redactDiagnostic, createDiagnosticLog } = require('../support-diagnostics');
test('diagnostics omit credentials, URLs and local user paths', () => {
  const text = redactDiagnostic('Authorization: Bearer secret\nCookie: private\nhttps://youtube.com/watch?v=private\n/Users/alice/My Videos/private.mp4\nC:\\Users\\bob\\private.mp4\nsession-secret', ['session-secret']);
  for (const secret of ['Bearer', 'secret', 'private', 'alice', 'bob']) assert.equal(text.includes(secret),false);
});
test('diagnostic history is bounded and does not retain raw secrets', () => {
  const log = createDiagnosticLog(['secret-value']);
  for (let i=0;i<120;i++) log.append(`line ${i} secret-value`);
  const report = log.report({version:'0.1.32',backend:{ready:false},detail:'failure'});
  assert.equal(report.includes('secret-value'),false); assert.equal(report.includes('line 0 '),false); assert.match(report,/line 119/);
});
