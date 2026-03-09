import unittest

import cv2
import numpy as np

from app.pipeline.roi_health import analyze_roi_health_frames


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


if __name__ == "__main__":
    unittest.main()
