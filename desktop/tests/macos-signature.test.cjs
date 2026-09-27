const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { verifyApp } = require('../scripts/verify-macos-signature');

test('macOS release gate accepts a sealed bundle and rejects changed resources', { skip: process.platform !== 'darwin' }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drumsheet-signature-test-'));
  const app = path.join(root, 'Fixture.app');
  try {
    const binaries = [
      'MacOS/Fixture',
      'Resources/backend/bin/ffmpeg',
      'Resources/backend/bin/ffprobe',
      'Resources/backend/runtime/drumsheet-backend/drumsheet-backend',
    ];
    for (const binary of binaries) {
      const destination = path.join(app, 'Contents', binary);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.copyFileSync('/usr/bin/true', destination);
      fs.chmodSync(destination, 0o755);
      execFileSync('codesign', ['--force', '--sign', '-', destination], { stdio: 'pipe' });
    }
    fs.writeFileSync(path.join(app, 'Contents', 'Info.plist'), `<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>com.drumsheet.signature-test</string><key>CFBundleExecutable</key><string>Fixture</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>`);
    const resource = path.join(app, 'Contents', 'Resources', 'app.asar');
    fs.writeFileSync(resource, 'original resource');
    execFileSync('codesign', ['--force', '--sign', '-', app], { stdio: 'pipe' });
    assert.doesNotThrow(() => verifyApp(app));
    fs.appendFileSync(resource, 'modified after signing');
    assert.throws(() => verifyApp(app), /codesign/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
