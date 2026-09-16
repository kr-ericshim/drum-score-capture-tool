import unittest

import cv2
import numpy as np

from app.pipeline.auto_roi import fit_white_score_region


class AutoRoiTests(unittest.TestCase):
    def test_follows_moving_white_panel_without_including_outside_pixels(self):
        roi = [[0, 80], [400, 80], [400, 200], [0, 200]]
        for displacement in (0, 3, 8, 16, 25):
            with self.subTest(displacement=displacement):
                image = np.full((220, 400, 3), (40, 110, 170), dtype=np.uint8)
                top = 80 + displacement
                image[top:200] = 250
                # A high accent at the very first paper row must survive.
                image[top:top + 8, 190:196] = 0
                cv2.line(image, (0, top + 30), (399, top + 30), (0, 0, 0), 1)
                fitted, details = fit_white_score_region(image, roi)
                self.assertEqual(fitted[0][1], top)
                self.assertEqual(fitted[2][1], 200)
                self.assertGreaterEqual(fitted[0][1], roi[0][1])
                self.assertEqual(details["trim_top"], displacement)

    def test_black_notation_on_white_does_not_get_trimmed(self):
        image = np.full((120, 400, 3), 250, dtype=np.uint8)
        image[:5, :250] = 0
        roi = [[0, 0], [400, 0], [400, 120], [0, 120]]
        fitted, details = fit_white_score_region(image, roi)
        self.assertEqual(fitted, roi)
        self.assertEqual(details["trim_top"], 0)

    def test_uncertain_dark_frame_keeps_selection(self):
        roi = [[0, 0], [400, 0], [400, 120], [0, 120]]
        fitted, details = fit_white_score_region(np.zeros((120, 400, 3), dtype=np.uint8), roi)
        self.assertEqual(fitted, roi)
        self.assertEqual(details["status"], "uncertain")

    def test_bottom_background_is_trimmed_without_cutting_paper(self):
        image = np.full((120, 400, 3), 250, dtype=np.uint8)
        image[110:] = (40, 110, 170)
        fitted, details = fit_white_score_region(image, [[0, 0], [400, 0], [400, 120], [0, 120]])
        self.assertEqual(fitted[2][1], 110)
        self.assertEqual(details["trim_bottom"], 10)
