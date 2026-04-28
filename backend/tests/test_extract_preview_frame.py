import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.pipeline.extract import _extract_single_frame_with_ffmpeg, _extract_with_ffmpeg, _preview_seek_candidates


class _Result:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class _FakeProgressProcess:
    def __init__(self, out_path: Path):
        self.returncode = 0
        self.stdout = iter(
            [
                "frame=1\n",
                "out_time=00:00:02.000000\n",
                "progress=continue\n",
                "frame=2\n",
                "out_time=00:00:05.000000\n",
                "progress=end\n",
            ]
        )
        self.stderr = self
        self._out_path = out_path

    def wait(self):
        self._out_path.write_bytes(b"png")
        return self.returncode

    def read(self):
        return ""


class TestPreviewFrameExtraction(unittest.TestCase):
    def test_main_frame_extraction_emits_live_progress(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            source.write_bytes(b"fake-video")
            out_dir = root / "frames"
            out_dir.mkdir()
            out_path = out_dir / "frame_000001.png"
            updates = []

            def fake_popen(cmd, stdout=None, stderr=None, text=None):
                self.assertIn("-progress", cmd)
                self.assertIn("pipe:1", cmd)
                return _FakeProgressProcess(out_path)

            def fake_run(cmd, stdout=None, stderr=None, text=None, check=None):
                return _Result(returncode=0, stdout="10.0\n")

            with patch("app.pipeline.extract.resolve_ffmpeg_bin", return_value="ffmpeg"), patch(
                "app.pipeline.extract.get_runtime_acceleration",
                return_value=SimpleNamespace(ffmpeg_hwaccel_flags=[[]]),
            ), patch("app.pipeline.extract.resolve_ffprobe_bin", return_value="ffprobe"), patch(
                "app.pipeline.extract.subprocess.run",
                side_effect=fake_run,
            ), patch(
                "app.pipeline.extract.subprocess.Popen",
                side_effect=fake_popen,
            ):
                frames = _extract_with_ffmpeg(
                    source_video=source,
                    out_dir=out_dir,
                    fps=1.0,
                    start_sec=None,
                    end_sec=None,
                    runtime_info={},
                    logger=lambda *_: None,
                    progress_callback=updates.append,
                )

            self.assertEqual(frames, [out_path])
            self.assertIn("frame extraction 20%", [update["message"] for update in updates])
            self.assertIn("frame extraction 50%", [update["message"] for update in updates])
            self.assertEqual(updates[-1]["progress"], 1.0)

    def test_seek_candidates_expand_beyond_initial_window(self):
        candidates = _preview_seek_candidates(0.0)
        self.assertEqual(candidates[:3], [0.0, 0.8, 1.8])
        self.assertIn(3.5, candidates)
        self.assertIn(6.0, candidates)

    def test_preview_uses_cpu_only_on_windows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            source.write_bytes(b"fake-video")
            out_path = root / "preview.png"
            seen = []

            def fake_run(cmd, stdout=None, stderr=None, text=None):
                seen.append(cmd)
                out_path.write_bytes(b"png")
                return _Result(returncode=0)

            with patch("app.pipeline.extract.platform.system", return_value="Windows"), patch(
                "app.pipeline.extract.resolve_ffmpeg_bin",
                return_value="ffmpeg.exe",
            ), patch("app.pipeline.extract.subprocess.run", side_effect=fake_run):
                _extract_single_frame_with_ffmpeg(
                    source_video=source,
                    out_path=out_path,
                    sec=0.0,
                    logger=lambda *_: None,
                )

            joined = " ".join(" ".join(map(str, cmd)) for cmd in seen)
            self.assertNotIn("-hwaccel", joined)

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
