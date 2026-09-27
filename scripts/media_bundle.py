#!/usr/bin/env python3
"""Create and restore pinned native media bundles (stdlib only)."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'kr-ericshim/drum-score-capture-tool'
TARGETS = ('darwin-arm64', 'win32-x64')
RECIPE_FILES = ('scripts/build-media-tools.sh', 'scripts/media_bundle.py',
                'desktop/scripts/media-tool-policy.js', '.github/workflows/media-tools.yml')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def recipe(root=ROOT):
    digest = hashlib.sha256()
    for name in RECIPE_FILES:
        digest.update(name.encode() + b'\0' + (root / name).read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return digest.hexdigest()


def target():
    machine = platform.machine().lower()
    if platform.system() == 'Darwin' and machine == 'arm64':
        return 'darwin-arm64'
    if platform.system() == 'Windows' and machine in ('amd64', 'x86_64'):
        return 'win32-x64'
    raise ValueError('Supported bundle hosts: macOS arm64 and Windows x64')


def required_files(native):
    if native not in TARGETS:
        raise ValueError('Unsupported bundle target')
    ext = '.exe' if native == 'win32-x64' else ''
    files = [f'backend/bin/{tool}{ext}' for tool in ('ffmpeg', 'ffprobe')]
    licenses = ['COPYING.LGPLv2.1', 'LICENSE.md', 'SOURCE.txt',
                'build-media-tools.sh', 'DAV1D-LICENSE.txt']
    if native == 'win32-x64':
        licenses.append('ZLIB-LICENSE.txt')
    files += ['backend/bin/licenses/' + name for name in licenses]
    files.append(f'.tmp/media-tools/ffmpeg-8.1.2-{native}-source.tar.gz')
    return files


def validate_runtime(root=ROOT):
    subprocess.run(['node', '-e',
                    "require('./desktop/scripts/media-tool-policy').validateMediaTools('backend/bin')"],
                   cwd=root, check=True)


def pack(output, root=ROOT):
    native = target()
    validate_runtime(root)
    expected = recipe(root)
    # The bundle must carry the actual recipe used for the binaries.
    if (root / 'backend/bin/licenses/build-media-tools.sh').read_bytes() != (root / 'scripts/build-media-tools.sh').read_bytes():
        raise ValueError('Staged media build script does not match the current recipe')
    output.mkdir(parents=True, exist_ok=True)
    asset = f'media-tools-{native}.tar.gz'
    with tarfile.open(output / asset, 'w:gz') as archive:
        for name in required_files(native):
            source = root / name
            if not source.is_file() or source.is_symlink() or not source.stat().st_size:
                raise ValueError(f'Missing or invalid bundle input: {name}')
            archive.add(source, arcname=name, recursive=False)
    record = {'schema': 1, 'recipe': expected, 'target': native,
              'asset': asset, 'sha256': sha256((output / asset).read_bytes())}
    (output / f'{native}.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def combine(directory, root=ROOT):
    expected = recipe(root)
    bundles = {}
    for native in TARGETS:
        item = json.loads((directory / f'{native}.json').read_text())
        if item['schema'] != 1 or item['recipe'] != expected or item['target'] != native:
            raise ValueError(f'Unexpected recipe or target: {native}')
        asset = f'media-tools-{native}.tar.gz'
        if item['asset'] != asset or sha256((directory / asset).read_bytes()) != item['sha256']:
            raise ValueError(f'Bundle checksum mismatch: {native}')
        bundles[native] = {'asset': asset, 'sha256': item['sha256']}
    lock = {'schema': 1, 'repository': REPOSITORY, 'recipe': expected,
            'tag': 'media-tools-' + expected[:20], 'bundles': bundles}
    (directory / 'media-tools.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    return lock


def verify_archive(data, lock, native, expected_recipe):
    if lock.get('schema') != 1 or lock.get('repository') != REPOSITORY:
        raise ValueError('Invalid media lock schema or repository')
    if lock.get('recipe') != expected_recipe or lock.get('tag') != 'media-tools-' + expected_recipe[:20]:
        raise ValueError('Media recipe changed; build a new bundle and update the lock')
    item = lock['bundles'][native]
    if item['asset'] != f'media-tools-{native}.tar.gz' or sha256(data) != item['sha256']:
        raise ValueError('Media bundle SHA-256 or asset mismatch')
    result = {}
    required = set(required_files(native))
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            if member.name not in required or member.name in result or not member.isfile() or member.size <= 0:
                raise ValueError(f'Unexpected archive entry: {member.name}')
            if member.size > 200 * 1024 * 1024:
                raise ValueError('Oversized media bundle entry')
            result[member.name] = archive.extractfile(member).read()
    if set(result) != required:
        raise ValueError('Incomplete media bundle (binaries, licenses and source are required)')
    return result


def restore(root=ROOT):
    lock = json.loads((root / 'backend/media-tools.lock.json').read_text())
    expected = recipe(root)
    if lock.get('recipe') != expected:
        raise ValueError('Media recipe changed; build a new bundle and update backend/media-tools.lock.json')
    native = target()
    # Validate all URL components before accessing the network.
    if lock.get('repository') != REPOSITORY or lock.get('tag') != 'media-tools-' + expected[:20]:
        raise ValueError('Invalid pinned media release')
    asset = f'media-tools-{native}.tar.gz'
    if lock['bundles'][native]['asset'] != asset:
        raise ValueError('Invalid pinned asset name')
    url = f'https://github.com/{REPOSITORY}/releases/download/{lock["tag"]}/{asset}'
    print(f'Restoring {url}', flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read(200 * 1024 * 1024 + 1)
    if len(data) > 200 * 1024 * 1024:
        raise ValueError('Oversized media bundle')
    files = verify_archive(data, lock, native, expected)
    if files['backend/bin/licenses/build-media-tools.sh'] != (root / 'scripts/build-media-tools.sh').read_bytes():
        raise ValueError('Bundled build script differs from the pinned recipe')
    # Fully validate before modifying the workspace; never tar.extract untrusted paths.
    for name, content in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temp:
            temporary = Path(temp.name)
            temp.write(content)
        try:
            temporary.chmod(0o755 if name in required_files(native)[:2] else 0o644)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    validate_runtime(root)
    print(f'Verified {native} media bundle: {lock["bundles"][native]["sha256"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('pack', 'combine', 'restore', 'recipe'))
    parser.add_argument('--directory', type=Path, default=ROOT / '.tmp/media-bundle')
    args = parser.parse_args()
    if args.command == 'pack':
        print(json.dumps(pack(args.directory)))
    elif args.command == 'combine':
        print(json.dumps(combine(args.directory)))
    elif args.command == 'recipe':
        print(recipe())
    else:
        restore()


if __name__ == '__main__':
    main()
