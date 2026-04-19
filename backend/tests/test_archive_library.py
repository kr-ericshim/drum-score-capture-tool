import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.job_store import Job, JobStore
from app.schemas import JobCreate


class TestArchiveLibrary(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
