import tempfile
import unittest
from pathlib import Path

from app.job_store import Job, JobStore


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


if __name__ == "__main__":
    unittest.main()
