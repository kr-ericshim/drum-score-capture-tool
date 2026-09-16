import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app.job_store import Job, JobStatus, JobStore
from app.main import crop_capture
from app.schemas import CaptureCropRequest


class TestCaptureCrop(unittest.TestCase):
    def test_capture_crop_rejects_review_preview_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            preview_dir = artifact_dir / "export" / "preview"
            preview_dir.mkdir(parents=True, exist_ok=True)

            preview_path = preview_dir / "preview_0001.png"
            image = np.full((200, 300, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(preview_path), image)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "preview_images": [str(preview_path)],
                        "review_candidates": [str(preview_path)],
                        "review_export": {"kept_count": 1, "requested_count": 1},
                    },
                )
            )

            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as error:
                    crop_capture(
                        "job-1",
                        CaptureCropRequest(
                            capture_path=str(preview_path),
                            roi=[[10, 10], [120, 10], [120, 120], [10, 120]],
                        ),
                    )

            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(error.exception.detail, "edit the original capture, not an exported preview")

    def test_capture_crop_preserves_original_after_review_export(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            review_dir = artifact_dir / "review"
            review_dir.mkdir(parents=True, exist_ok=True)

            capture_path = review_dir / "capture_0001.png"
            image = np.full((200, 300, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(capture_path), image)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "review_candidates": [str(capture_path)],
                        "review_export": {
                            "kept_count": 1,
                            "requested_count": 1,
                            "selection_mode": "captures",
                            "selected_captures": [str(capture_path)],
                        },
                    },
                )
            )

            before = capture_path.read_bytes()
            with patch("app.main.job_store", store):
                response = crop_capture("job-1", CaptureCropRequest(capture_path=str(capture_path), roi=[[10, 10], [120, 10], [120, 120], [10, 120]]))
                self.assertNotEqual(Path(response.capture_path), capture_path)
                self.assertEqual((response.width, response.height), (110, 110))
                self.assertEqual(capture_path.read_bytes(), before)
                reset = crop_capture("job-1", CaptureCropRequest(capture_path=str(capture_path), roi=[]))
                self.assertEqual(Path(reset.capture_path), capture_path.resolve())
                self.assertEqual(store.get("job-1").result["capture_edits"], {})


if __name__ == "__main__":
    unittest.main()
