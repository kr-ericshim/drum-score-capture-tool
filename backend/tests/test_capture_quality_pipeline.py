import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app import main
from app.job_store import JobStore
from app.pipeline.detect import detect_sheet_regions
from app.schemas import DetectOptions, JobCreate


class TestCaptureQualityPipeline(unittest.TestCase):
    def make_job_payload(self, file_path: str) -> JobCreate:
        return JobCreate(
            source_type="file",
            file_path=file_path,
            options={
                "detect": {
                    "roi": [[10, 10], [70, 10], [70, 40], [10, 40]],
                    "layout_hint": "auto",
                },
                "stitch": {
                    "enable": True,
                    "layout_hint": "auto",
                },
            },
        )

    def test_create_job_queues_even_when_roi_health_would_be_critical(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            source_path = Path(td) / "source.mp4"
            source_path.write_bytes(b"video")
            executor = Mock()

            with (
                patch.object(main, "jobs_root", jobs_root),
                patch.object(main, "job_store", JobStore(jobs_root)),
                patch.object(main, "executor", executor),
                patch.object(
                    main,
                    "analyze_roi_health_for_source",
                    return_value={
                        "risk_level": "critical",
                        "summary": "ROI is unsafe for capture",
                        "diagnostics": [{"code": "roi_margin_tight", "level": "critical"}],
                        "sampled_frames": 3,
                        "checked_seconds": [0.0, 0.8, 1.6],
                        "metrics": {},
                    },
                ),
            ):
                response = main.create_job(self.make_job_payload(str(source_path)))

            self.assertTrue(response.job_id)
            executor.submit.assert_called_once()
            self.assertEqual(len(list(jobs_root.glob("*/job.json"))), 1)

    def test_detect_sheet_regions_attaches_padded_safe_roi(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            frame_path = workspace / "frame.png"
            image = np.full((100, 200, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(frame_path), image)

            detections = detect_sheet_regions(
                frame_paths=[frame_path],
                options=DetectOptions(
                    roi=[[10, 10], [70, 10], [70, 40], [10, 40]],
                    layout_hint="auto",
                ),
                workspace=workspace / "detect",
                logger=lambda *_: None,
            )

            self.assertEqual(len(detections), 1)
            self.assertEqual(detections[0]["roi"], [[10.0, 10.0], [70.0, 10.0], [70.0, 40.0], [10.0, 40.0]])
            self.assertIn("safe_roi", detections[0])
            self.assertEqual(detections[0]["safe_roi"], [[6.0, 2.0], [74.0, 2.0], [74.0, 48.0], [6.0, 48.0]])


if __name__ == "__main__":
    unittest.main()
