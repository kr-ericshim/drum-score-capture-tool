import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.main import _probe_video_resolution


class TestSourceResolutionProbe(unittest.TestCase):
    def test_prefers_ffprobe_result_when_available(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "sample.webm"
            video_path.write_bytes(b"not-a-real-video")

            completed = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"streams": [{"width": 1920, "height": 1410}]}),
                stderr="",
            )

            with patch("app.main.resolve_ffprobe_bin", return_value="ffprobe"), patch(
                "app.main.subprocess.run",
                return_value=completed,
            ), patch(
                "app.main._probe_video_resolution_with_opencv",
                return_value=(490, 360),
            ) as opencv_probe:
                self.assertEqual(_probe_video_resolution(video_path), (1920, 1410))
                opencv_probe.assert_not_called()

    def test_falls_back_to_opencv_when_ffprobe_output_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "sample.webm"
            video_path.write_bytes(b"not-a-real-video")

            completed = SimpleNamespace(
                returncode=0,
                stdout="not-json",
                stderr="",
            )

            with patch("app.main.resolve_ffprobe_bin", return_value="ffprobe"), patch(
                "app.main.subprocess.run",
                return_value=completed,
            ), patch(
                "app.main._probe_video_resolution_with_opencv",
                return_value=(490, 360),
            ):
                self.assertEqual(_probe_video_resolution(video_path), (490, 360))


if __name__ == "__main__":
    unittest.main()
