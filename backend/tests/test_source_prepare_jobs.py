import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.job_store import JobStatus, ProgressMode, SourcePrepareJob, SourcePrepareStore
from app.schemas import PreviewSourceJobCreateRequest


class FakeExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return None


class TestSourcePrepareJobs(unittest.TestCase):
    def test_prepare_job_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact_dir = root / "prepare-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = SourcePrepareStore(root)
            job = SourcePrepareJob(
                id="prepare-1",
                youtube_url="https://youtu.be/demo",
                artifact_dir=str(artifact_dir),
                status=JobStatus.DONE,
                stage="done",
                progress=1.0,
                progress_mode=ProgressMode.DETERMINATE,
                result={"video_path": str(artifact_dir / "video.mp4")},
            )
            store.create(job)

            reloaded = SourcePrepareStore(root)
            job = reloaded.get("prepare-1")

            self.assertIsNotNone(job)
            self.assertEqual(job.youtube_url, "https://youtu.be/demo")
            self.assertEqual(job.stage, "done")
            self.assertEqual(job.progress_mode, ProgressMode.DETERMINATE)

    def test_reload_marks_interrupted_prepare_job_as_recovered_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact_dir = root / "prepare-2"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = SourcePrepareStore(root)
            store.create(
                SourcePrepareJob(
                    id="prepare-2",
                    youtube_url="https://youtu.be/demo",
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                    stage="download",
                    message="downloading",
                )
            )

            reloaded = SourcePrepareStore(root)
            job = reloaded.get("prepare-2")

            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.ERROR)
            self.assertEqual(job.error_code, "RECOVERED_AFTER_RESTART")
            self.assertEqual(job.stage, "failed")

    def test_create_prepare_job_returns_job_id_and_queues_runner(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            executor = FakeExecutor()

            with patch.object(main, "source_prepare_store", store), patch.object(
                main,
                "source_prepare_executor",
                executor,
            ):
                response = main.create_preview_source_job(
                    PreviewSourceJobCreateRequest(youtube_url="https://youtu.be/demo")
                )

            self.assertTrue(response.job_id)
            self.assertEqual(len(executor.submissions), 1)
            job = store.get(response.job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job.youtube_url, "https://www.youtube.com/watch?v=demo")
            self.assertEqual(job.status, JobStatus.QUEUED)

    def test_get_prepare_job_returns_public_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            artifact_dir = store.root / "prepare-3"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            store.create(
                SourcePrepareJob(
                    id="prepare-3",
                    youtube_url="https://youtu.be/demo",
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                    stage="download",
                    message="downloading video 42%",
                    progress=0.42,
                    progress_mode=ProgressMode.DETERMINATE,
                    log=["stage started", "downloading 42%"],
                )
            )

            with patch.object(main, "source_prepare_store", store):
                response = main.get_preview_source_job("prepare-3")

            self.assertEqual(response.job_id, "prepare-3")
            self.assertEqual(response.status, "running")
            self.assertEqual(response.stage, "download")
            self.assertEqual(response.progress_mode, "determinate")
            self.assertAlmostEqual(response.progress, 0.42, places=2)
            self.assertEqual(response.log_tail[-1], "downloading 42%")

    def test_run_source_prepare_job_marks_done_and_persists_result(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            artifact_dir = store.root / "prepare-4"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            output = artifact_dir / "downloads" / "video.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"video")

            store.create(
                SourcePrepareJob(
                    id="prepare-4",
                    youtube_url="https://youtu.be/demo",
                    artifact_dir=str(artifact_dir),
                )
            )

            def fake_prepare(youtube_url, *, logger, progress_callback):
                logger("youtube cache miss: downloading source")
                progress_callback(
                    {
                        "stage": "download",
                        "progress": 0.42,
                        "progress_mode": "determinate",
                        "message": "downloading video 42%",
                    }
                )
                return output, False

            with patch.object(main, "source_prepare_store", store), patch.object(
                main,
                "_get_or_prepare_cached_youtube_video",
                side_effect=fake_prepare,
            ), patch.object(
                main,
                "_to_jobs_files_url",
                return_value="/jobs-files/_preview_source_jobs/prepare-4/downloads/video.mp4",
            ):
                main._run_source_prepare_job("prepare-4")

            job = store.get("prepare-4")
            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.DONE)
            self.assertEqual(job.stage, "done")
            self.assertAlmostEqual(job.progress, 1.0, places=3)
            self.assertEqual(job.result.get("video_path"), str(output))
            self.assertFalse(job.result.get("from_cache"))


if __name__ == "__main__":
    unittest.main()
