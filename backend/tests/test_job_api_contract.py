import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app.job_store import Job, JobStatus, JobStore
from app.main import crop_capture, review_export
from app.schemas import CaptureCropRequest, JobReviewExportRequest


class TestJobApiContract(unittest.TestCase):
    def test_review_export_rejects_capture_outside_current_review_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "images"
            hidden_dir = artifact_dir / "debug"
            export_dir.mkdir(parents=True, exist_ok=True)
            hidden_dir.mkdir(parents=True, exist_ok=True)

            candidate_path = export_dir / "page_0001.png"
            hidden_path = hidden_dir / "shadow.png"
            candidate_path.write_bytes(b"candidate")
            hidden_path.write_bytes(b"hidden")

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "review_candidates": [str(candidate_path)],
                        "images": [str(candidate_path)],
                    },
                )
            )

            with (
                patch("app.main.job_store", store),
                patch("app.main.export_selected_pages") as export_selected_pages,
            ):
                with self.assertRaises(HTTPException) as error:
                    review_export(
                        "job-1",
                        JobReviewExportRequest(keep_captures=[str(hidden_path)], formats=["png"]),
                    )

            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(error.exception.detail, f"capture is not selectable for this job: {hidden_path}")
            export_selected_pages.assert_not_called()

    def test_capture_crop_rejects_capture_outside_current_review_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            review_dir = artifact_dir / "review"
            hidden_dir = artifact_dir / "debug"
            review_dir.mkdir(parents=True, exist_ok=True)
            hidden_dir.mkdir(parents=True, exist_ok=True)

            candidate_path = review_dir / "capture_0001.png"
            hidden_path = hidden_dir / "shadow.png"
            image = np.full((200, 300, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(candidate_path), image)
            cv2.imwrite(str(hidden_path), image)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "review_candidates": [str(candidate_path)],
                        "upscaled_frames": [str(candidate_path)],
                    },
                )
            )

            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as error:
                    crop_capture(
                        "job-1",
                        CaptureCropRequest(
                            capture_path=str(hidden_path),
                            roi=[[10, 10], [120, 10], [120, 120], [10, 120]],
                        ),
                    )

            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(error.exception.detail, f"capture is not selectable for this job: {hidden_path}")


if __name__ == "__main__":
    unittest.main()
