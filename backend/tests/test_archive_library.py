import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.job_store import Job, JobStatus, JobStore, SourcePrepareJob, SourcePrepareStore
from app.schemas import JobCreate


class TestArchiveLibrary(unittest.TestCase):
    def _import_main_with_stubbed_cv(self):
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

    def test_job_store_round_trip_preserves_source_identity_and_completed_at(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            store = JobStore(jobs_root)
            job = Job(
                id="job-1",
                source_type="file",
                file_path="/tmp/source.mp4",
                youtube_url=None,
                options={},
                artifact_dir=str(jobs_root / "job-1"),
                source_identity={
                    "kind": "youtube",
                    "key": "https://www.youtube.com/watch?v=abc123",
                    "display_name": "Blue in Green Drum Cover",
                },
                completed_at=1713526200.0,
            )

            store.create(job)
            reloaded = JobStore(jobs_root)
            loaded = reloaded.get("job-1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.source_identity["kind"], "youtube")
            self.assertEqual(
                loaded.source_identity["display_name"],
                "Blue in Green Drum Cover",
            )
            self.assertEqual(loaded.completed_at, 1713526200.0)

    def test_create_job_persists_source_identity_from_live_jobs_path(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            source_path = Path(td) / "source.mp4"
            source_path.write_bytes(b"video")

            payload = JobCreate(
                source_type="file",
                file_path=str(source_path),
                source_identity={
                    "kind": "youtube",
                    "key": "https://www.youtube.com/watch?v=abc123",
                    "display_name": "Blue in Green Drum Cover",
                },
                options={
                    "detect": {
                        "roi": [[0, 0], [320, 0], [320, 180], [0, 180]],
                    },
                },
            )

            submitted = []

            class _Executor:
                def submit(self, fn, *args):
                    submitted.append((fn, args))

            with (
                patch.object(main, "jobs_root", jobs_root),
                patch.object(main, "job_store", JobStore(jobs_root)),
                patch.object(main, "executor", _Executor()),
            ):
                response = main.create_job(payload)

            reloaded = JobStore(jobs_root)
            loaded = reloaded.get(response.job_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(
                loaded.source_identity,
                {
                    "kind": "youtube",
                    "key": "https://www.youtube.com/watch?v=abc123",
                    "display_name": "Blue in Green Drum Cover",
                },
            )
            self.assertEqual(len(submitted), 1)

    def test_set_state_stamps_completed_at_when_job_becomes_done(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-2"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-2",
                    source_type="file",
                    file_path="/tmp/source.mp4",
                    youtube_url=None,
                    options={},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                )
            )

            with patch("app.job_store.time.time", return_value=1713526200.0):
                store.set_state("job-2", JobStatus.DONE)

            loaded = store.get("job-2")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.completed_at, 1713526200.0)

    def test_set_state_done_does_not_overwrite_existing_completed_at(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-3"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-3",
                    source_type="file",
                    file_path="/tmp/source.mp4",
                    youtube_url=None,
                    options={},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                    completed_at=1713526200.0,
                )
            )

            with patch("app.job_store.time.time", return_value=1813526200.0):
                store.set_state("job-3", JobStatus.DONE)

            loaded = store.get("job-3")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.completed_at, 1713526200.0)

    def test_archive_prepare_snapshot_exposes_video_title_and_source_key(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            artifact_dir = store.root / "source-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store.create(
                SourcePrepareJob(
                    id="source-1",
                    youtube_url="https://www.youtube.com/watch?v=abc123",
                    artifact_dir=str(artifact_dir),
                )
            )

            with (
                patch.object(main, "source_prepare_store", store),
                patch.object(
                    main,
                    "_get_or_prepare_cached_youtube_video",
                    return_value={
                        "video_path": Path("/tmp/cache/abc123.mp4"),
                        "from_cache": True,
                        "video_title": "Take Five Drum Lesson",
                        "source_key": "https://www.youtube.com/watch?v=abc123",
                    },
                ),
                patch.object(main, "_to_jobs_files_url", return_value="/jobs-files/_preview/youtube.mp4"),
            ):
                main._run_source_prepare_job("source-1")

            job = store.get("source-1")
            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.DONE)
            result = job.result or {}
            self.assertEqual(result["video_title"], "Take Five Drum Lesson")
            self.assertEqual(result["source_key"], "https://www.youtube.com/watch?v=abc123")


if __name__ == "__main__":
    unittest.main()
