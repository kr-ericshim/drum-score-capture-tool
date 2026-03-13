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
            self.assertEqual(error.exception.detail, "capture crop is unavailable after review export")


if __name__ == "__main__":
    unittest.main()
