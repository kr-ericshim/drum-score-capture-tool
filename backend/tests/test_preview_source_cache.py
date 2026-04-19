import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _import_main_with_stubs():
    acceleration = types.ModuleType("app.pipeline.acceleration")
    acceleration.get_runtime_acceleration = lambda *args, **kwargs: {}
    acceleration.runtime_public_info = lambda *args, **kwargs: {}

    detect = types.ModuleType("app.pipeline.detect")
    detect.detect_sheet_regions = lambda *args, **kwargs: []

    layout_profiles = types.ModuleType("app.pipeline.layout_profiles")
    layout_profiles.infer_layout_hint_from_roi = lambda *args, **kwargs: "full_scroll"

    roi_health = types.ModuleType("app.pipeline.roi_health")
    roi_health.analyze_roi_health_for_source = lambda *args, **kwargs: {}

    rectify = types.ModuleType("app.pipeline.rectify")
    rectify.rectify_frames = lambda *args, **kwargs: []

    stitch = types.ModuleType("app.pipeline.stitch")
    stitch.select_review_candidates = lambda *args, **kwargs: []
    stitch.stitch_pages = lambda *args, **kwargs: []

    upscale = types.ModuleType("app.pipeline.upscale")
    upscale.upscale_frames = lambda *args, **kwargs: []

    export = types.ModuleType("app.pipeline.export")
    export.export_frames = lambda *args, **kwargs: {}
    export.export_selected_pages = lambda *args, **kwargs: {}

    stubbed_modules = {
        "cv2": types.ModuleType("cv2"),
        "app.pipeline.acceleration": acceleration,
        "app.pipeline.detect": detect,
        "app.pipeline.layout_profiles": layout_profiles,
        "app.pipeline.roi_health": roi_health,
        "app.pipeline.rectify": rectify,
        "app.pipeline.stitch": stitch,
        "app.pipeline.upscale": upscale,
        "app.pipeline.export": export,
    }
    previous_main = sys.modules.pop("app.main", None)
    try:
        with patch.dict(sys.modules, stubbed_modules):
            return importlib.import_module("app.main")
    finally:
        sys.modules.pop("app.main", None)
        if previous_main is not None:
            sys.modules["app.main"] = previous_main


main = _import_main_with_stubs()


class TestPreviewSourceCache(unittest.TestCase):
    def test_cache_workspace_uses_namespaced_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace("https://example.com/watch?v=abc")

            self.assertEqual(cache_dir.parent.name, main.PREVIEW_SOURCE_CACHE_NAMESPACE)
            self.assertEqual(cache_dir.parent.parent, jobs_root / "_preview_source")

    def test_cache_workspace_collapses_equivalent_youtube_urls(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            with patch.object(main, "jobs_root", jobs_root):
                first = main._preview_source_cache_workspace("https://youtu.be/abc12345678?si=demo")
                second = main._preview_source_cache_workspace("https://www.youtube.com/watch?v=abc12345678&t=43")

            self.assertEqual(first, second)

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
                prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertFalse(prepared["from_cache"])
            self.assertEqual(prepared["video_path"], fresh_video)
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

                with patch.object(main, "_probe_video_resolution", return_value=(1920, 1080)), patch.object(
                    main,
                    "prepare_preview_source",
                ) as prepare_source:
                    prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertTrue(prepared["from_cache"])
            self.assertEqual(prepared["video_path"], cached_video)
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
                    prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertTrue(prepared["from_cache"])
            self.assertEqual(prepared["video_path"], high)
            prepare_source.assert_not_called()

    def test_cache_hit_reads_source_metadata_for_title_and_key(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            url = "https://example.com/watch?v=abc"

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace(url)
                cached_video = cache_dir / "cached.mp4"
                cached_video.write_bytes(b"cached-video")
                (cache_dir / "source.json").write_text(
                    '{"source_key":"https://www.youtube.com/watch?v=abc123","video_title":"Take Five Drum Lesson"}',
                    encoding="utf-8",
                )

                with patch.object(main, "_probe_video_resolution", return_value=(1920, 1080)), patch.object(
                    main,
                    "prepare_preview_source",
                ) as prepare_source:
                    prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertTrue(prepared["from_cache"])
            self.assertEqual(prepared["video_path"], cached_video)
            self.assertEqual(prepared["video_title"], "Take Five Drum Lesson")
            self.assertEqual(prepared["source_key"], "https://www.youtube.com/watch?v=abc123")
            prepare_source.assert_not_called()

    def test_cache_hit_normalizes_legacy_source_key_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_root = Path(tmp_dir) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            url = "https://youtu.be/abc12345678"

            with patch.object(main, "jobs_root", jobs_root):
                cache_dir = main._preview_source_cache_workspace(url)
                cached_video = cache_dir / "cached.mp4"
                cached_video.write_bytes(b"cached-video")
                (cache_dir / "source.json").write_text(
                    '{"source_key":"https://youtu.be/abc12345678?si=legacy","video_title":"Take Five Drum Lesson"}',
                    encoding="utf-8",
                )

                with patch.object(main, "_probe_video_resolution", return_value=(1920, 1080)):
                    prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertTrue(prepared["from_cache"])
            self.assertEqual(prepared["source_key"], "https://www.youtube.com/watch?v=abc12345678")

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
                    prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertFalse(prepared["from_cache"])
            self.assertEqual(prepared["video_path"], refreshed_video)
            self.assertFalse(cached_video.exists())
            prepare_source.assert_called_once()

    def test_cache_hit_redownloads_invalid_zero_dimension_video(self):
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

                with patch.object(main, "_probe_video_resolution", return_value=(0, 0)), patch.object(
                    main,
                    "prepare_preview_source",
                    side_effect=fake_prepare_preview_source,
                ) as prepare_source:
                    prepared = main._get_or_prepare_cached_youtube_video(url, logger=lambda *_: None)

            self.assertFalse(prepared["from_cache"])
            self.assertEqual(prepared["video_path"], refreshed_video)
            self.assertFalse(cached_video.exists())
            prepare_source.assert_called_once()


if __name__ == "__main__":
    unittest.main()
