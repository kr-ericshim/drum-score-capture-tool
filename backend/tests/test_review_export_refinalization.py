import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.export import export_selected_pages


def _make_score_strip(*, label: str, add_bottom_staff: bool) -> np.ndarray:
    image = np.full((980, 1800, 3), 255, dtype=np.uint8)

    if add_bottom_staff:
        base_y = 610
    else:
        base_y = 120

    for offset in [0, 12, 24, 36, 48]:
        y = base_y + offset
        cv2.line(image, (70, y), (1730, y), (0, 0, 0), 2)

    cv2.putText(
        image,
        label,
        (120, base_y + 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.2,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )
    cv2.circle(image, (380, base_y + 18), 14, (0, 0, 0), -1)
    cv2.circle(image, (920, base_y + 30), 14, (0, 0, 0), -1)
    cv2.circle(image, (1420, base_y + 42), 14, (0, 0, 0), -1)
    return image


class TestReviewExportRefinalization(unittest.TestCase):
    def test_export_selected_pages_preserves_selected_page_inputs_as_individual_pages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page_one = root / "capture_1.png"
            page_two = root / "capture_2.png"

            cv2.imwrite(str(page_one), _make_score_strip(label="A", add_bottom_staff=False))
            cv2.imwrite(str(page_two), _make_score_strip(label="B", add_bottom_staff=True))

            result = export_selected_pages(
                page_paths=[page_one, page_two],
                formats=["png", "pdf"],
                workspace=root / "export",
                logger=lambda _msg: None,
            )

            self.assertEqual(len(result["images"]), 2)
            self.assertTrue(str(result["pdf"]).endswith("sheet_export.pdf"))
            self.assertEqual(len(result["page_diagnostics"]), 2)

    def test_export_selected_pages_avoids_cutting_staff_across_page_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page_one = root / "capture_top.png"
            page_two = root / "capture_bottom.png"

            cv2.imwrite(str(page_one), _make_score_strip(label="TOP", add_bottom_staff=False))
            cv2.imwrite(str(page_two), _make_score_strip(label="BOTTOM", add_bottom_staff=True))

            result = export_selected_pages(
                page_paths=[page_one, page_two],
                formats=["png"],
                workspace=root / "export",
                logger=lambda _msg: None,
            )

            self.assertEqual(len(result["images"]), 2)
            first = cv2.imread(result["images"][0], cv2.IMREAD_GRAYSCALE)
            second = cv2.imread(result["images"][1], cv2.IMREAD_GRAYSCALE)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(first.shape, second.shape)
            self.assertFalse(np.array_equal(first, second))

    def test_export_selected_pages_writes_preview_images_for_pdf_only_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page_one = root / "capture_1.png"

            cv2.imwrite(str(page_one), _make_score_strip(label="PDF", add_bottom_staff=False))

            result = export_selected_pages(
                page_paths=[page_one],
                formats=["pdf"],
                workspace=root / "export",
                logger=lambda _msg: None,
            )

            self.assertEqual(result["images"], [])
            self.assertEqual(len(result["preview_images"]), 1)
            self.assertTrue(Path(result["preview_images"][0]).exists())
            self.assertTrue(str(result["pdf"]).endswith("sheet_export.pdf"))
            self.assertTrue(Path(result["pdf"]).exists())
            self.assertEqual(len(result["page_diagnostics"]), 1)


if __name__ == "__main__":
    unittest.main()
