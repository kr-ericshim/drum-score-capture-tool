import tempfile
import unittest
from pathlib import Path

from app.job_store import Job, JobStatus, JobStore


class TestJobStorePersistence(unittest.TestCase):
    def test_reload_restores_completed_job_from_disk(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path="/tmp/source.mp4",
                    youtube_url=None,
                    options={"export": {"formats": ["png"]}},
                    artifact_dir=str(artifact_dir),
                )
            )
            store.set_state(
                "job-1",
                JobStatus.DONE,
                progress=1.0,
                current_step="done",
                message="finished",
                result={"images": ["page-1.png"]},
            )

            reloaded = JobStore(jobs_root)
            job = reloaded.get("job-1")

            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.DONE)
            self.assertEqual(job.result.get("images"), ["page-1.png"])

    def test_reload_marks_interrupted_running_job_as_recovered_error(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-2"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-2",
                    source_type="youtube",
                    file_path=None,
                    youtube_url="https://www.youtube.com/watch?v=abc12345678",
                    options={"export": {"formats": ["png"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                    current_step="exporting",
                    message="working",
                )
            )

            reloaded = JobStore(jobs_root)
            job = reloaded.get("job-2")

            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.ERROR)
            self.assertEqual(job.error_code, "RECOVERED_AFTER_RESTART")
            self.assertIn("restart", job.message.lower())

    def test_reload_recovers_corrupt_metadata_as_error_job(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-3"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = artifact_dir / "job.json"
            metadata_path.write_text("{not-valid-json", encoding="utf-8")

            reloaded = JobStore(jobs_root)
            job = reloaded.get("job-3")

            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.ERROR)
            self.assertEqual(job.error_code, "RECOVERED_CORRUPT_METADATA")
            self.assertTrue((artifact_dir / "job.corrupt.json").exists())
            self.assertIn("corrupt", job.message.lower())


if __name__ == "__main__":
    unittest.main()
