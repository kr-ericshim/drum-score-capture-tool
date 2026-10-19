import unittest

import cv2
import numpy as np

from app.pipeline.export import _diagnose_page_image


def _make_score_page(*, label: str, top_staff_y: int = 220) -> np.ndarray:
    image = np.full((1500, 1100, 3), 255, dtype=np.uint8)

    for block_index in range(3):
        base_y = top_staff_y + (block_index * 360)
        for offset in [0, 14, 28, 42, 56]:
            y = base_y + offset
            cv2.line(image, (90, y), (1010, y), (0, 0, 0), 2)
        cv2.circle(image, (220, base_y + 18), 10, (0, 0, 0), -1)
        cv2.circle(image, (620, base_y + 30), 10, (0, 0, 0), -1)
        cv2.circle(image, (900, base_y + 42), 10, (0, 0, 0), -1)

    cv2.putText(
        image,
        label,
        (120, top_staff_y + 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.6,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    return image


class TestExportDocumentHeader(unittest.TestCase):
    def test_diagnose_page_image_emits_actionable_codes_for_sparse_and_video_pages(self):
        sparse = np.full((1500, 1100, 3), 255, dtype=np.uint8)
        cv2.putText(sparse, "John 14:6", (430, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
        sparse_diagnostic = _diagnose_page_image(sparse, 1)

        self.assertTrue(sparse_diagnostic["suspicious"])
        self.assertIn("mostly_blank_page", sparse_diagnostic["diagnostic_codes"])
        self.assertEqual(sparse_diagnostic["recommended_action"], "exclude")

        video_mixed = _make_score_page(label="Video", top_staff_y=560)
        video_mixed[80:470, 90:1010] = (60, 120, 210)
        cv2.circle(video_mixed, (520, 260), 120, (35, 170, 240), -1)
        video_diagnostic = _diagnose_page_image(video_mixed, 2)

        self.assertTrue(video_diagnostic["suspicious"])
        self.assertIn("mixed_visual_content", video_diagnostic["diagnostic_codes"])
        self.assertEqual(video_diagnostic["recommended_action"], "review")
        self.assertEqual(video_diagnostic["score_classification"], "score")


if __name__ == "__main__":
    unittest.main()
