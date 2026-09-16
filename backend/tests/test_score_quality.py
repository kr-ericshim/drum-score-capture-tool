import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline.export import _diagnose_page_image, diagnose_capture_sequence


def score_image(*, color=(255, 255, 255), ink=0, lines=5):
    image = np.full((240, 640, 3), color, dtype=np.uint8)
    for offset in range(lines):
        cv2.line(image, (30, 80 + 12 * offset), (610, 80 + 12 * offset), (ink,) * 3, 1)
    for x, y in ((110, 92), (250, 110), (420, 116)):
        cv2.ellipse(image, (x, y), (7, 4), -15, 0, 360, (ink,) * 3, -1)
        cv2.line(image, (x + 6, y), (x + 6, y - 28), (ink,) * 3, 2)
    return image


class TestScoreQuality(unittest.TestCase):
    def test_scores_survive_color_dark_background_fading_and_small_tilt(self):
        normal = score_image()
        transform = cv2.getRotationMatrix2D((320, 120), 2, 1)
        variants = {
            "normal": normal,
            "colored_paper": score_image(color=(170, 235, 255)),
            "dark_mode": 255 - normal,
            "faded": cv2.GaussianBlur(score_image(ink=165), (3, 3), 0),
            "tilted": cv2.warpAffine(normal, transform, (640, 240), borderValue=(255, 255, 255)),
            "low_resolution": cv2.resize(normal, (320, 120), interpolation=cv2.INTER_AREA),
        }
        for label, image in variants.items():
            with self.subTest(label=label):
                d = _diagnose_page_image(image, 1)
                self.assertEqual(d["score_classification"], "score", d)
                self.assertNotEqual(d["recommended_action"], "exclude", d)

    def test_partial_and_one_line_percussion_are_retained_for_review(self):
        for image in (score_image(lines=1), score_image(lines=3), score_image()[100:]):
            d = _diagnose_page_image(image, 1)
            self.assertNotEqual(d["recommended_action"], "exclude", d)
            self.assertEqual(d["score_classification"], "uncertain", d)

    def test_sparse_one_line_percussion_on_large_colored_page_is_not_discarded(self):
        image = np.full((2400, 640, 3), (170, 235, 255), np.uint8)
        image[300:540] = score_image(color=(170, 235, 255), lines=1)
        d = _diagnose_page_image(image, 1)
        self.assertEqual(d["recommended_action"], "review", d)
        self.assertTrue(d["score_evidence"]["possible_single_line_notation"])

    def test_regular_rules_without_notation_do_not_establish_a_score(self):
        for lines in (5, 12):
            image = np.full((260, 640, 3), 255, np.uint8)
            for y in range(30, 30 + lines * 12, 12):
                cv2.line(image, (30, y), (610, y), (0, 0, 0), 1)
            d = _diagnose_page_image(image, 1)
            self.assertEqual(d["score_classification"], "uncertain", d)
            self.assertEqual(d["recommended_action"], "review", d)

    def test_text_is_uncertain_not_asserted_to_be_a_score(self):
        image = np.full((240, 640, 3), 255, np.uint8)
        for y in (50, 110, 170):
            cv2.putText(image, "This is a document, not notation", (25, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        d = _diagnose_page_image(image, 1)
        self.assertEqual(d["score_classification"], "uncertain", d)

    def test_blank_color_scene_and_gray_texture_are_excluded(self):
        rng = np.random.default_rng(7)
        gray = rng.integers(25, 175, (240, 640), dtype=np.uint8)
        scenes = [np.full((240, 640, 3), 255, np.uint8),
                  np.full((240, 640, 3), (50, 120, 180), np.uint8),
                  cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)]
        for image in scenes:
            d = _diagnose_page_image(image, 1)
            self.assertEqual(d["score_classification"], "non_score", d)
            self.assertEqual(d["recommended_action"], "exclude", d)

    def test_sequence_needs_two_matching_neighbors_and_partial_staff_evidence(self):
        image = score_image()
        clear = _diagnose_page_image(image, 1)
        weak = {**clear, "score_classification": "uncertain", "suspicious": True,
                "recommended_action": "review", "diagnostic_codes": ["score_structure_uncertain"],
                "warning_reasons": ["uncertain"], "score_evidence": {**clear["score_evidence"], "has_score_structure": False}}
        with tempfile.TemporaryDirectory() as td:
            paths = [Path(td) / f"{idx}.png" for idx in range(3)]
            for path in paths:
                cv2.imwrite(str(path), image)
            with patch("app.pipeline.export._diagnose_page_image", side_effect=[clear, weak, clear]):
                result = diagnose_capture_sequence(paths)
            self.assertTrue(result[str(paths[1])]["score_evidence"]["neighbor_supported"])
            self.assertEqual(result[str(paths[1])]["recommended_action"], "keep")
            # A real intervening blank remains excluded even between matching scores.
            cv2.imwrite(str(paths[1]), np.full_like(image, 255))
            result = diagnose_capture_sequence(paths)
            self.assertEqual(result[str(paths[1])]["recommended_action"], "exclude")
            # Only one neighbor is insufficient evidence to promote a partial crop.
            cv2.imwrite(str(paths[1]), image[100:])
            result = diagnose_capture_sequence(paths[:2])
            self.assertEqual(result[str(paths[1])]["score_classification"], "uncertain")


if __name__ == "__main__":
    unittest.main()
