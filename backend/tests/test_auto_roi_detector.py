import unittest

import cv2
import numpy as np

from app.pipeline.auto_roi_detector import estimate_auto_roi


def score_overlay(*, dark=False, x1=80, y1=360, x2=880, y2=520):
    background = np.full((540, 960, 3), (48, 74, 105), dtype=np.uint8)
    paper = 24 if dark else 245
    ink = 235 if dark else 15
    background[y1:y2, x1:x2] = paper
    for line_index in range(5):
        y = y1 + 48 + line_index * 12
        cv2.line(background, (x1 + 24, y), (x2 - 24, y), (ink,) * 3, 1)
    for x, y in ((180, y1 + 60), (350, y1 + 84), (610, y1 + 72), (760, y1 + 96)):
        cv2.ellipse(background, (x, y), (7, 4), -15, 0, 360, (ink,) * 3, -1)
        cv2.line(background, (x + 6, y), (x + 6, y - 28), (ink,) * 3, 2)
    return background


class AutoRoiDetectorTests(unittest.TestCase):
    def test_suggests_bottom_score_overlay_from_repeated_frames(self):
        frames = [score_overlay() for _ in range(3)]

        result = estimate_auto_roi(frames)

        self.assertEqual(result["status"], "suggested", result)
        self.assertEqual(result["evidence_level"], "high", result)
        x1, y1 = result["roi"][0]
        x2, y2 = result["roi"][2]
        self.assertLessEqual(x1, 110)
        self.assertGreaterEqual(x2, 850)
        self.assertLessEqual(y1, 380)
        self.assertGreaterEqual(y2, 490)
        self.assertGreaterEqual(result["diagnostics"]["supporting_frames"], 2)

    def test_supports_light_notation_on_dark_panel(self):
        result = estimate_auto_roi([score_overlay(dark=True) for _ in range(3)])

        self.assertEqual(result["status"], "suggested", result)
        self.assertTrue(result["is_dark_mode"], result)

    def test_static_scene_without_staff_returns_no_suggestion(self):
        scene = np.full((540, 960, 3), (60, 100, 150), dtype=np.uint8)
        cv2.rectangle(scene, (100, 100), (860, 440), (80, 120, 170), 4)

        result = estimate_auto_roi([scene for _ in range(3)])

        self.assertEqual(result["status"], "not_found", result)
        self.assertIsNone(result["roi"])


if __name__ == "__main__":
    unittest.main()
