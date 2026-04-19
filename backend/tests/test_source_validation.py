import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _import_main_with_stubs():
    acceleration = types.ModuleType("app.pipeline.acceleration")
    acceleration.get_runtime_acceleration = lambda *args, **kwargs: {}
    acceleration.runtime_public_info = lambda *args, **kwargs: {}

    extract = types.ModuleType("app.pipeline.extract")
    extract.YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "test"
    extract.extract_frames = lambda *args, **kwargs: []
    extract.extract_preview_frame = lambda *args, **kwargs: None
    extract.prepare_preview_source = lambda *args, **kwargs: None

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
        "app.pipeline.extract": extract,
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


class TestSourceValidation(unittest.TestCase):
    def test_accepts_supported_youtube_hosts(self):
        self.assertEqual(
            main._normalize_supported_youtube_url("https://www.youtube.com/watch?v=abc12345678"),
            "https://www.youtube.com/watch?v=abc12345678",
        )
        self.assertEqual(
            main._normalize_supported_youtube_url("https://youtu.be/abc12345678"),
            "https://www.youtube.com/watch?v=abc12345678",
        )

    def test_canonicalizes_equivalent_youtube_url_forms_to_one_key(self):
        expected = "https://www.youtube.com/watch?v=abc12345678"
        self.assertEqual(
            main._normalize_supported_youtube_url("https://youtu.be/abc12345678?si=demo"),
            expected,
        )
        self.assertEqual(
            main._normalize_supported_youtube_url("https://m.youtube.com/watch?v=abc12345678&t=43"),
            expected,
        )
        self.assertEqual(
            main._normalize_supported_youtube_url("https://www.youtube.com/embed/abc12345678?start=10"),
            expected,
        )
        self.assertEqual(
            main._normalize_supported_youtube_url("https://www.youtube.com/shorts/abc12345678"),
            expected,
        )

    def test_rejects_non_http_or_unsupported_hosts(self):
        with self.assertRaises(ValueError):
            main._normalize_supported_youtube_url("file:///tmp/video.mp4")

        with self.assertRaises(ValueError):
            main._normalize_supported_youtube_url("https://example.com/video")


if __name__ == "__main__":
    unittest.main()
