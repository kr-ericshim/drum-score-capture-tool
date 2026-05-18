import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.job_store import Job, JobStatus, JobStore
from app.main import _run_job
from app.schemas import JobCreate


class TestJobReviewCandidates(unittest.TestCase):
    def test_run_job_exposes_deduped_review_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            source_path = jobs_root / "source.mp4"
            source_path.write_bytes(b"video")

            rectified_1 = artifact_dir / "rectified" / "capture_0001.png"
            rectified_2 = artifact_dir / "rectified" / "capture_0002.png"
            deduped_candidate = artifact_dir / "rectified" / "capture_0001_deduped.png"
            stitched_1 = artifact_dir / "stitched" / "page_0001.png"
            export_page = artifact_dir / "export" / "images" / "page_0001.png"

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(source_path),
                    youtube_url=None,
                    options={},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.QUEUED,
                )
            )

            payload = JobCreate(
                source_type="file",
                file_path=str(source_path),
                options={
                    "detect": {
                        "roi": [[0, 0], [320, 0], [320, 180], [0, 180]],
                    },
                },
            )

            with (
                patch("app.main.job_store", store),
                patch("app.main.jobs_root", jobs_root),
                patch("app.main._analyze_roi_health", return_value={"summary": "ok", "diagnostics": []}),
                patch("app.main.get_runtime_acceleration", return_value={}),
                patch("app.main.resolve_ffmpeg_bin", return_value="ffmpeg"),
                patch("app.main.runtime_public_info", return_value={}),
                patch("app.main._detect_source_resolution", return_value=(0, 0)),
                patch("app.main.extract_frames", return_value=[artifact_dir / "frames" / "frame_0001.png"]),
                patch("app.main.detect_sheet_regions", return_value=[{"id": "roi"}]),
                patch("app.main.rectify_frames", return_value=[rectified_1, rectified_2]),
                patch("app.main.select_review_candidates", return_value=[deduped_candidate], create=True),
                patch("app.main.stitch_pages", return_value=[stitched_1]),
                patch("app.main.upscale_frames", return_value=[stitched_1]),
                patch(
                    "app.main.export_frames",
                    return_value={
                        "images": [str(export_page)],
                        "pdf": None,
                        "raw_frames": [],
                        "page_diagnostics": [],
                    },
                ),
            ):
                _run_job("job-1", payload)

            job = store.get("job-1")
            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.DONE)
            self.assertEqual(
                job.result.get("review_candidates"),
                [str(deduped_candidate)],
            )


if __name__ == "__main__":
    unittest.main()
