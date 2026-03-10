import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.pipeline.extract import _extract_single_frame_with_ffmpeg, _preview_seek_candidates


class _Result:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


class TestPreviewFrameExtraction(unittest.TestCase):
    def test_seek_candidates_expand_beyond_initial_window(self):
        candidates = _preview_seek_candidates(0.0)
        self.assertEqual(candidates[:3], [0.0, 0.8, 1.8])
        self.assertIn(3.5, candidates)
        self.assertIn(6.0, candidates)

    def test_thumbnail_fallback_succeeds_after_seek_failures(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            source.write_bytes(b"fake-video")
            out_path = root / "preview.png"

            def fake_run(cmd, stdout=None, stderr=None, text=None):
                if any(isinstance(part, str) and "thumbnail=90" in part for part in cmd):
                    out_path.write_bytes(b"png")
                    return _Result(returncode=0)
                return _Result(returncode=1, stderr="seek failed")

            with patch("app.pipeline.extract.resolve_ffmpeg_bin", return_value="ffmpeg"), patch(
                "app.pipeline.extract.get_runtime_acceleration",
                return_value=SimpleNamespace(ffmpeg_hwaccel_flags=[[]]),
            ), patch("app.pipeline.extract.subprocess.run", side_effect=fake_run):
                _extract_single_frame_with_ffmpeg(
                    source_video=source,
                    out_path=out_path,
                    sec=0.0,
                    logger=lambda *_: None,
                )

            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
