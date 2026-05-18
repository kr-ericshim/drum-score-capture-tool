import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main
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


class TestPreviewWorkspaceCleanup(unittest.TestCase):
    def test_preview_frame_prunes_expired_workspaces_without_removing_current_image(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            preview_root = jobs_root / "_preview"
            preview_root.mkdir(parents=True, exist_ok=True)
            source = jobs_root / "source.mp4"
            source.write_bytes(b"fake-video")

            expired_at = 1_700_000_000
            for name in ("expired-a", "expired-b"):
                stale_workspace = preview_root / name
                stale_workspace.mkdir()
                (stale_workspace / "stale.txt").write_text("stale", encoding="utf-8")
                os.utime(stale_workspace, (expired_at, expired_at))

            def fake_extract_preview_frame(**kwargs):
                workspace = kwargs["workspace"]
                image_path = workspace / "preview" / "preview_frame.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(b"png")
                return image_path

            with patch.object(main, "jobs_root", jobs_root), patch.object(
                main,
                "extract_preview_frame",
                side_effect=fake_extract_preview_frame,
            ), patch.object(main, "_preview_cleanup_now", return_value=expired_at + 3_600):
                response = main.preview_frame(
                    main.PreviewFrameRequest(
                        source_type="file",
                        file_path=str(source),
                        start_sec=0,
                    )
                )

            current_image = Path(response.image_path)
            self.assertTrue(current_image.exists())
            self.assertEqual(response.image_url, f"/jobs-files/{current_image.relative_to(jobs_root).as_posix()}")
            self.assertEqual([path.name for path in preview_root.iterdir() if path.is_dir()], [current_image.parents[1].name])

    def test_preview_frame_workspaces_remain_bounded_across_repeated_calls(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            source = jobs_root / "source.mp4"
            source.write_bytes(b"fake-video")

            def fake_extract_preview_frame(**kwargs):
                workspace = kwargs["workspace"]
                image_path = workspace / "preview" / "preview_frame.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(b"png")
                return image_path

            with patch.object(main, "jobs_root", jobs_root), patch.object(
                main,
                "extract_preview_frame",
                side_effect=fake_extract_preview_frame,
            ):
                for _ in range(6):
                    response = main.preview_frame(
                        main.PreviewFrameRequest(
                            source_type="file",
                            file_path=str(source),
                            start_sec=0,
                        )
                    )
                    self.assertTrue(Path(response.image_path).exists())

            preview_workspaces = [path for path in (jobs_root / "_preview").iterdir() if path.is_dir()]
            self.assertLessEqual(len(preview_workspaces), main.PREVIEW_FRAME_WORKSPACE_KEEP + 1)

    def test_preview_roi_health_removes_temp_workspace_after_response(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            source = jobs_root / "source.mp4"
            source.write_bytes(b"fake-video")
            seen_workspaces = []

            def fake_analyze_roi_health(**kwargs):
                workspace = kwargs["workspace"]
                self.assertTrue(workspace.exists())
                (workspace / "sample.txt").write_text("sample", encoding="utf-8")
                seen_workspaces.append(workspace)
                return {
                    "risk_level": "info",
                    "summary": "ok",
                    "diagnostics": [],
                    "sampled_frames": 1,
                    "checked_seconds": [0.0],
                    "metrics": {},
                }

            with patch.object(main, "jobs_root", jobs_root), patch.object(
                main,
                "_analyze_roi_health",
                side_effect=fake_analyze_roi_health,
            ):
                response = main.preview_roi_health(
                    main.PreviewRoiHealthRequest(
                        source_type="file",
                        file_path=str(source),
                        start_sec=0,
                        roi=[[0, 0], [1, 0], [1, 1], [0, 1]],
                    )
                )

            self.assertEqual(response.risk_level, "info")
            self.assertEqual(len(seen_workspaces), 1)
            self.assertFalse(seen_workspaces[0].exists())


if __name__ == "__main__":
    unittest.main()
