const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function binaryArchitecture(file) {
  const data = fs.readFileSync(file);
  if (data.readUInt32LE(0) === 0xfeedfacf) {
    return data.readUInt32LE(4) === 0x0100000c ? 'arm64' : 'x64';
  }
  if (data.toString('ascii', 0, 2) === 'MZ') {
    const offset = data.readUInt32LE(0x3c);
    if (data.toString('ascii', offset, offset + 4) !== 'PE\0\0') throw new Error('Invalid PE header');
    return data.readUInt16LE(offset + 4) === 0x8664 ? 'x64' : 'unsupported';
  }
  throw new Error(`Unrecognized executable: ${file}`);
}

function validateMediaTools(binDir, { platform = process.platform, arch = process.arch } = {}) {
  const suffix = platform === 'win32' ? '.exe' : '';
  for (const tool of ['ffmpeg', 'ffprobe']) {
    const file = path.join(binDir, tool + suffix);
    if (!fs.existsSync(file)) throw new Error(`Missing ${file}. Run bash scripts/build-media-tools.sh first.`);
    if (binaryArchitecture(file) !== arch) throw new Error(`${tool} architecture does not match ${arch}`);
    const result = spawnSync(file, ['-version'], { encoding: 'utf8', timeout: 15000, windowsHide: true });
    const text = `${result.stdout || ''}\n${result.stderr || ''}`;
    if (result.error || result.status !== 0) throw new Error(`${tool} cannot run: ${result.error || text}`);
    if (!text.includes(`${tool} version 8.1.2`) || /--enable-(gpl|nonfree)(?:\s|$)/.test(text)
        || !text.includes('--disable-gpl') || !text.includes('--disable-nonfree') || !text.includes('--enable-libdav1d')) {
      throw new Error(`${tool} must be the pinned LGPL build produced by scripts/build-media-tools.sh`);
    }
  }
  if (platform === 'win32') {
    const result = spawnSync(path.join(binDir, 'ffmpeg.exe'), ['-hide_banner', '-hwaccels'], { encoding: 'utf8', timeout: 15000, windowsHide: true });
    if (result.status !== 0 || !/^d3d11va\s*$/m.test(result.stdout || '') || !/^dxva2\s*$/m.test(result.stdout || '')) {
      throw new Error('Windows media build must expose D3D11VA and DXVA2 (runtime GPU availability is separate).');
    }
    if (!fs.existsSync(path.join(binDir, 'licenses', 'ZLIB-LICENSE.txt'))) throw new Error('Missing Windows zlib license');
  }
  for (const file of ['COPYING.LGPLv2.1', 'LICENSE.md', 'SOURCE.txt', 'build-media-tools.sh', 'DAV1D-LICENSE.txt']) {
    if (!fs.existsSync(path.join(binDir, 'licenses', file))) throw new Error(`Missing media license/provenance: ${file}`);
  }
}
module.exports = { binaryArchitecture, validateMediaTools };
