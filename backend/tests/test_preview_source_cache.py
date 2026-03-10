import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class TestPreviewSourceCache(unittest.TestCase):
    def test_cache_workspace_uses_namespaced_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace("https://example.com/watch?v=abc")

            self.assertEqual(cache_dir.parent.name, main.PREVIEW_SOURCE_CACHE_NAMESPACE)
            self.assertEqual(cache_dir.parent.parent, jobs_root / "_preview_source")

    def test_cache_lookup_ignores_legacy_directory_and_redownloads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            url = "https://example.com/watch?v=abc"
            legacy_key = main.hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
            legacy_dir = jobs_root / "_preview_source" / legacy_key
            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / "legacy.mp4").write_bytes(b"legacy-low-quality")

            fresh_video = jobs_root / "_preview_source" / main.PREVIEW_SOURCE_CACHE_NAMESPACE / legacy_key / "fresh.mp4"

            def fake_prepare_preview_source(**kwargs):
                workspace = kwargs["workspace"]
                workspace.mkdir(parents=True, exist_ok=True)
                fresh_video.parent.mkdir(parents=True, exist_ok=True)
                fresh_video.write_bytes(b"fresh-high-quality")
                return fresh_video

            with patch.object(main, "jobs_root", jobs_root), patch.object(
                main,
                "prepare_preview_source",
                side_effect=fake_prepare_preview_source,
            ) as prepare_source:
                resolved, from_cache = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertFalse(from_cache)
            self.assertEqual(resolved, fresh_video)
            prepare_source.assert_called_once()

    def test_cache_hit_uses_current_namespaced_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            url = "https://example.com/watch?v=abc"

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace(url)
                cached_video = cache_dir / "cached.mp4"
                cached_video.write_bytes(b"cached-video")

                with patch.object(main, "prepare_preview_source") as prepare_source:
                    resolved, from_cache = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertTrue(from_cache)
            self.assertEqual(resolved, cached_video)
            prepare_source.assert_not_called()

    def test_cache_hit_prefers_highest_resolution_video(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            url = "https://example.com/watch?v=abc"

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace(url)
                low = cache_dir / "sample-low.mp4"
                high = cache_dir / "sample-high.webm"
                low.write_bytes(b"low")
                high.write_bytes(b"high")

                def fake_probe(path: Path):
                    if path == high:
                        return (1920, 1080)
                    return (640, 360)

                with patch.object(main, "_probe_video_resolution", side_effect=fake_probe), patch.object(
                    main,
                    "prepare_preview_source",
                ) as prepare_source:
                    resolved, from_cache = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertTrue(from_cache)
            self.assertEqual(resolved, high)
            prepare_source.assert_not_called()

    def test_cache_hit_redownloads_low_resolution_video(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            url = "https://example.com/watch?v=abc"

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace(url)
                cached_video = cache_dir / "cached.mp4"
                refreshed_video = cache_dir / "fresh.mp4"
                cached_video.write_bytes(b"cached")

                def fake_prepare_preview_source(**kwargs):
                    refreshed_video.write_bytes(b"fresh")
                    return refreshed_video

                with patch.object(main, "_probe_video_resolution", return_value=(640, 360)), patch.object(
                    main,
                    "prepare_preview_source",
                    side_effect=fake_prepare_preview_source,
                ) as prepare_source:
                    resolved, from_cache = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertFalse(from_cache)
            self.assertEqual(resolved, refreshed_video)
            self.assertFalse(cached_video.exists())
            prepare_source.assert_called_once()


if __name__ == "__main__":
    unittest.main()
