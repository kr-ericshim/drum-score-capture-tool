import importlib.util
import io
import tarfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('media_bundle', Path(__file__).parents[1] / 'media_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def fixture(self, change=None, native='darwin-arm64'):
        entries = [(name, b'example', tarfile.REGTYPE) for name in bundle.required_files(native)]
        if change:
            entries = change(entries)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, data, kind in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(data) if kind == tarfile.REGTYPE else 0
                info.linkname = '/tmp/outside'
                archive.addfile(info, io.BytesIO(data) if info.size else None)
        data = stream.getvalue()
        recipe = 'a' * 64
        lock = {'schema': 1, 'repository': bundle.REPOSITORY, 'recipe': recipe,
                'tag': 'media-tools-' + recipe[:20], 'bundles': {
                    native: {'asset': f'media-tools-{native}.tar.gz', 'sha256': bundle.sha256(data)}}}
        return data, lock, native, recipe

    def test_complete_platform_bundles(self):
        for native in bundle.TARGETS:
            args = self.fixture(native=native)
            self.assertEqual(set(bundle.verify_archive(*args)), set(bundle.required_files(native)))

    def test_corruption_rejected(self):
        data, *args = self.fixture()
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            bundle.verify_archive(data + b'corruption', *args)

    def test_recipe_change_rejected(self):
        args = list(self.fixture())
        args[-1] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'recipe'):
            bundle.verify_archive(*args)

    def test_missing_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            bundle.verify_archive(*self.fixture(lambda entries: entries[:-1]))

    def test_missing_windows_license_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            bundle.verify_archive(*self.fixture(lambda entries: [e for e in entries if 'ZLIB' not in e[0]], 'win32-x64'))

    def test_unsafe_entries_rejected_even_with_matching_digest(self):
        for entry in [('../outside', b'x', tarfile.REGTYPE),
                      ('/tmp/outside', b'x', tarfile.REGTYPE),
                      ('backend/bin/ffmpeg', b'', tarfile.SYMTYPE),
                      ('backend/bin/ffmpeg', b'', tarfile.LNKTYPE)]:
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, 'Unexpected'):
                bundle.verify_archive(*self.fixture(lambda entries: entries[1:] + [entry]))

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            bundle.verify_archive(*self.fixture(lambda entries: entries + entries[:1]))

    def test_wrong_repository_rejected(self):
        args = list(self.fixture())
        args[1]['repository'] = 'other/repository'
        with self.assertRaisesRegex(ValueError, 'repository'):
            bundle.verify_archive(*args)

    def test_wrong_asset_rejected(self):
        args = list(self.fixture())
        args[1]['bundles']['darwin-arm64']['asset'] = 'other.tar.gz'
        with self.assertRaisesRegex(ValueError, 'asset'):
            bundle.verify_archive(*args)


if __name__ == '__main__':
    unittest.main()
