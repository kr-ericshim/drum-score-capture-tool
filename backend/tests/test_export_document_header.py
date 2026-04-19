import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from app.pipeline.export import (
    _compose_pdf_pages_with_document_header,
    _diagnose_page_image,
    _finalize_export_pages,
    _prepare_pdf_image,
    _render_document_header_band,
    export_selected_pages,
)


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
    def test_prepare_pdf_image_does_not_force_jpeg_reencode(self):
        gradient = np.zeros((1800, 1200, 3), dtype=np.uint8)
        gradient[:, :, 0] = np.tile(np.arange(1200, dtype=np.uint16) % 256, (1800, 1)).astype(np.uint8)
        gradient[:, :, 1] = np.tile((np.arange(1800, dtype=np.uint16) % 256).reshape(1800, 1), (1, 1200)).astype(np.uint8)
        gradient[:, :, 2] = ((gradient[:, :, 0].astype(np.uint16) + gradient[:, :, 1].astype(np.uint16)) % 256).astype(np.uint8)
        image = Image.fromarray(gradient, "RGB")
        self.addCleanup(image.close)

        prepared = _prepare_pdf_image(image)
        self.addCleanup(prepared.close)

        self.assertEqual(prepared.mode, "RGB")
        self.assertTrue(np.array_equal(np.asarray(prepared), gradient))

    def test_finalize_export_pages_preserves_color_channels_for_output_pages(self):
        page = np.zeros((220, 220, 3), dtype=np.uint8)
        page[:, :, 2] = 200

        finalized = _finalize_export_pages([page], page_fill_mode="performance")

        self.assertEqual(len(finalized), 1)
        self.assertFalse(np.array_equal(finalized[0][:, :, 0], finalized[0][:, :, 2]))

    def test_compose_pdf_pages_with_document_header_adds_band_to_first_page_only(self):
        page_one = _make_score_page(label="One")
        page_two = _make_score_page(label="Two", top_staff_y=260)

        composed = _compose_pdf_pages_with_document_header(
            [page_one, page_two],
            {
                "title": "Moonlight Etude",
                "performer": "Eric Shim",
                "bpm": 92,
                "date": "2026-04-19",
                "memo": "swing intro",
            },
        )
        self.addCleanup(lambda: [image.close() for image in composed])

        self.assertEqual(len(composed), 2)
        self.assertEqual(composed[0].size[0], page_one.shape[1])
        self.assertGreater(composed[0].size[1], page_one.shape[0])
        self.assertEqual(composed[1].size, (page_two.shape[1], page_two.shape[0]))

        first_band = np.asarray(composed[0])[:320]
        self.assertLess(int(first_band.min()), 245)

    def test_compose_pdf_pages_with_document_header_hides_blank_rows_and_caps_growth(self):
        page = _make_score_page(label="Cap")

        minimal = _compose_pdf_pages_with_document_header([page], {"title": "Caprice"})
        blank_optionals = _compose_pdf_pages_with_document_header(
            [page],
            {
                "title": "Caprice",
                "performer": "   ",
                "bpm": None,
                "date": "",
                "memo": "   ",
            },
        )
        verbose = _compose_pdf_pages_with_document_header(
            [page],
            {
                "title": "Very Long Title " * 18,
                "performer": "Long Performer Name",
                "bpm": 180,
                "date": "2026-04-19",
                "memo": "memo " * 120,
            },
        )
        self.addCleanup(lambda: [image.close() for image in minimal + blank_optionals + verbose])

        self.assertEqual(minimal[0].size, blank_optionals[0].size)
        self.assertGreater(verbose[0].size[1], minimal[0].size[1])
        self.assertLess(verbose[0].size[1] - page.shape[0], int(page.shape[0] * 0.4))

    def test_render_document_header_band_uses_side_credits_instead_of_centered_metadata_stack(self):
        band = _render_document_header_band(
            page_size=(1100, 1500),
            document_header={
                "title": "노래는 불빛처럼 달린다",
                "performer": "유다빈밴드",
                "bpm": 124,
                "date": "2026-04-19",
                "memo": "유다빈밴드의 'Twenty Plenty' 수록곡",
            },
        )
        self.addCleanup(band.close)

        band_pixels = np.asarray(band)
        ink_mask = np.any(band_pixels < 235, axis=2)
        height, width = ink_mask.shape
        lower_band = ink_mask[int(height * 0.56):int(height * 0.9)]
        left_ink = int(lower_band[:, :int(width * 0.32)].sum())
        center_ink = int(lower_band[:, int(width * 0.34):int(width * 0.66)].sum())
        right_ink = int(lower_band[:, int(width * 0.68):].sum())

        self.assertGreater(left_ink, 120)
        self.assertGreater(right_ink, 120)
        self.assertLess(center_ink, min(left_ink, right_ink))

    def test_export_selected_pages_applies_document_header_only_to_pdf_and_keeps_diagnostics_on_score(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page_path = root / "capture.png"
            source_page = _make_score_page(label="PDF")
            cv2.imwrite(str(page_path), source_page)

            finalized = _finalize_export_pages([source_page], page_fill_mode="performance")
            self.assertEqual(len(finalized), 1)
            expected_diagnostics = _diagnose_page_image(finalized[0], 1)

            with patch(
                "app.pipeline.export._compose_pdf_pages_with_document_header",
                wraps=_compose_pdf_pages_with_document_header,
            ) as compose_pdf:
                pdf_result = export_selected_pages(
                    page_paths=[page_path],
                    formats=["pdf"],
                    document_header={"title": "PDF Title", "memo": "header"},
                    workspace=root / "pdf-export",
                    logger=lambda _msg: None,
                )

            compose_pdf.assert_called_once()
            self.assertEqual(pdf_result["images"], [])
            self.assertEqual(len(pdf_result["preview_images"]), 1)
            self.assertTrue(Path(pdf_result["preview_images"][0]).exists())
            self.assertTrue(Path(pdf_result["pdf"]).exists())
            self.assertEqual(pdf_result["page_diagnostics"], [expected_diagnostics])
            self.assertFalse(pdf_result["page_diagnostics"][0]["suspicious"])

            with patch(
                "app.pipeline.export._compose_pdf_pages_with_document_header",
                wraps=_compose_pdf_pages_with_document_header,
            ) as compose_png:
                png_result = export_selected_pages(
                    page_paths=[page_path],
                    formats=["png"],
                    document_header={"title": "PNG Title"},
                    workspace=root / "png-export",
                    logger=lambda _msg: None,
                )

            compose_png.assert_not_called()
            self.assertEqual(len(png_result["images"]), 1)
            png_image = cv2.imread(png_result["images"][0])
            self.assertIsNotNone(png_image)
            self.assertEqual(tuple(png_image.shape[:2]), tuple(finalized[0].shape[:2]))

    def test_prepare_pdf_image_keeps_first_page_music_scale_when_header_band_makes_page_taller(self):
        page = _make_score_page(label="Scale", top_staff_y=260)
        page = cv2.resize(page, (1760, 2400), interpolation=cv2.INTER_LINEAR)

        composed = _compose_pdf_pages_with_document_header([page], {"title": "Scale Guard"})
        prepared = _prepare_pdf_image(composed[0])
        self.addCleanup(composed[0].close)
        self.addCleanup(prepared.close)

        self.assertEqual(prepared.size[0], page.shape[1])
        self.assertGreater(prepared.size[1], page.shape[0])


if __name__ == "__main__":
    unittest.main()
