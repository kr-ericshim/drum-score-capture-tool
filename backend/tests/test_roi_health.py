import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline.roi_health import (
    analyze_roi_health_for_source,
    analyze_roi_health_frames,
    pad_roi_rect,
    should_block_roi_capture,
)


ROI = [[100, 100], [700, 100], [700, 700], [100, 700]]


def _blank_frame():
    return np.full((800, 800, 3), 255, dtype=np.uint8)


def _frame_with_score(top=180, bottom=620):
    frame = _blank_frame()
    rows = np.linspace(top, bottom, 5).astype(int)
    for row in rows:
        cv2.line(frame, (130, row), (670, row), (0, 0, 0), 2)
        cv2.circle(frame, (220, row - 10), 8, (0, 0, 0), -1)
        cv2.circle(frame, (380, row + 8), 8, (0, 0, 0), -1)
        cv2.circle(frame, (560, row - 4), 8, (0, 0, 0), -1)
    return frame


class TestRoiHealthAnalysis(unittest.TestCase):
    def test_should_block_only_critical_roi(self):
        self.assertFalse(should_block_roi_capture({"risk_level": "info"}))
        self.assertFalse(should_block_roi_capture({"risk_level": "warning"}))
        self.assertTrue(should_block_roi_capture({"risk_level": "critical"}))

    def test_pad_roi_rect_expands_and_clamps_to_frame_bounds(self):
        padded = pad_roi_rect(
            [[4, 4], [24, 4], [24, 20], [4, 20]],
            image_width=30,
            image_height=25,
        )

        self.assertEqual(padded, [[0, 0], [28, 0], [28, 25], [0, 25]])

    def test_healthy_roi_reports_info(self):
        frames = [_frame_with_score(), _frame_with_score(), _frame_with_score()]

        result = analyze_roi_health_frames(frames, ROI)

        self.assertEqual(result["risk_level"], "info")
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("roi_healthy", codes)

    def test_tight_top_margin_reports_critical(self):
        frames = [
            _frame_with_score(top=104, bottom=520),
            _frame_with_score(top=108, bottom=520),
            _frame_with_score(top=112, bottom=520),
        ]

        result = analyze_roi_health_frames(frames, ROI)

        self.assertEqual(result["risk_level"], "critical")
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("top_edge_busy", codes)

    def test_sparse_roi_reports_warning(self):
        frames = [_blank_frame(), _blank_frame(), _blank_frame()]

        result = analyze_roi_health_frames(frames, ROI)

        self.assertEqual(result["risk_level"], "warning")
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("content_sparse", codes)

    def test_source_analysis_raises_when_all_preview_samples_fail(self):
        with patch("app.pipeline.roi_health.extract_preview_frame", side_effect=RuntimeError("seek failed")):
            with self.assertRaises(RuntimeError) as error:
                analyze_roi_health_for_source(
                    source_type="file",
                    file_path="/tmp/source.mp4",
                    youtube_url=None,
                    start_sec=0.0,
                    roi=ROI,
                    workspace=Path("/tmp/roi-health-test"),
                    logger=lambda *_: None,
                )

        self.assertIn("preview extraction failed", str(error.exception))


if __name__ == "__main__":
    unittest.main()
