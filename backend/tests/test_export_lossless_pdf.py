"""WP: exact lossless PDF pixels, format mutations and local delivery controls.

These tests do not call the legacy JPEG verifier. Delivery controls use the
lead's shared primitives; integration of stages A/B/C is a separate step.
"""
import io
import tempfile
import unittest
import zlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, PdfParser

from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_verify_common as vc
from app.pipeline.export import (
    COMPOSED_JPEG_QUALITY, COMPOSED_PREVIEW_WIDTH, export_composed_pages,
    pdf_page_count,
)


def decode_pages(path):
    """Independent Pillow object parsing + raw Flate decode, not the contract reader."""
    pdf = PdfParser.PdfParser(filename=str(path))
    result = []
    try:
        for ref in pdf.pages:
            page = pdf.read_indirect(ref)
            image = pdf.read_indirect(page[b"Resources"][b"XObject"][b"Im"])
            d = image.dictionary
            assert d[b"Filter"] == b"FlateDecode"
            channels = 1 if d[b"ColorSpace"] == b"DeviceGray" else 3
            raw = np.frombuffer(zlib.decompress(image.buf), np.uint8)
            shape = (d[b"Height"], d[b"Width"])
            result.append(raw.reshape(shape if channels == 1 else (*shape, 3)).copy())
    finally:
        pdf.close()
    return result


def fixture_pdf(path, *, image_extra=b"", page_extra=b"", contents=None,
                resources=None, size=(595.2, 841.92), width=2480, height=3508,
                color_space="DeviceGray", bpc=8, image_filter="FlateDecode",
                raw=None, encoded=None, compress_contents=False):
    """Explicit PDF objects let each malformed control change only one property."""
    w, h = size
    if raw is None:
        raw = b"\xff" * (width * height * (1 if color_space == "DeviceGray" else 3))
    if encoded is None:
        encoded = zlib.compress(raw, level=9)
    cmd = contents if contents is not None else f"q {w} 0 0 {h} 0 0 cm /Im Do Q".encode()
    content_filter = b""
    if compress_contents:
        cmd = zlib.compress(cmd)
        content_filter = b" /Filter /FlateDecode"
    resources = resources or b"<< /XObject << /Im 5 0 R >> >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Contents 4 0 R /Resources ".encode()
        + resources + page_extra + b" >>",
        f"<< /Length {len(cmd)}".encode() + content_filter + b" >>\nstream\n" + cmd + b"\nendstream",
        (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
         f"/ColorSpace /{color_space} /BitsPerComponent {bpc} /Filter /{image_filter} "
         f"/Length {len(encoded)}").encode() + image_extra + b" >>\nstream\n" + encoded + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for ident, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{ident} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend((f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
                 f"startxref\n{xref}\n%%EOF\n").encode())
    path.write_bytes(data)


class ExportLosslessPDFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="WP-")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def page(self):
        page = np.full((3508, 2480, 3), 255, np.uint8)
        patch = np.random.default_rng(17).integers(0, 256, (70, 90), dtype=np.uint8)
        page[30:100, 40:130] = patch[..., None]
        return page

    def export(self, pages, name="export", formats=None):
        return export_composed_pages(pages=pages, formats=formats or ["pdf"],
                                     workspace=self.work / name, logger=lambda _m: None)

    def test_gray_decode_equals_page_luminance_at_every_pixel(self):
        page = self.page()
        out = self.export([page])
        actual = decode_pages(out["pdf"])[0]
        np.testing.assert_array_equal(actual, cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))
        contract = rl.check_pdf_contract(out["pdf"])
        self.assertEqual(contract["status"], "pass", contract)
        self.assertEqual(contract["pages"][0]["profile"], "gray")
        self.assertEqual(contract["pages"][0]["dpi"], [300., 300.])
        self.assertEqual(pdf_page_count(Path(out["pdf"])), 1)

    def test_rgb_decode_equals_original_color_pixels(self):
        page = self.page()
        page[210:220, 150:160] = (240, 110, 35)
        out = self.export([page])
        np.testing.assert_array_equal(decode_pages(out["pdf"])[0], cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
        contract = rl.check_pdf_contract(out["pdf"])
        self.assertEqual(contract["status"], "pass", contract)
        self.assertEqual(contract["pages"][0]["profile"], "rgb")

    def test_max_chroma_threshold_is_inclusive_and_global(self):
        page = self.page()
        page[-1, -1] = (100, 112, 124)
        gray = self.export([page], "chroma24")
        self.assertEqual(rl.check_pdf_contract(gray["pdf"])["pages"][0]["profile"], "gray")
        np.testing.assert_array_equal(decode_pages(gray["pdf"])[0], cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))
        page[-1, -1, 2] = 125
        rgb = self.export([page], "chroma25")
        self.assertEqual(rl.check_pdf_contract(rgb["pdf"])["pages"][0]["profile"], "rgb")
        np.testing.assert_array_equal(decode_pages(rgb["pdf"])[0], cv2.cvtColor(page, cv2.COLOR_BGR2RGB))

    def test_mixed_pages_order_structure_and_deterministic_bytes(self):
        gray = self.page()
        rgb = gray.copy()
        rgb[160:170, 40:50] = (0, 128, 255)
        first = self.export([gray, rgb], "first")
        second = self.export([gray, rgb], "second")
        data = Path(first["pdf"]).read_bytes()
        self.assertEqual(data, Path(second["pdf"]).read_bytes())
        self.assertEqual(data.count(b"/Subtype /Image"), 2)
        self.assertEqual(data.count(b"/Filter /FlateDecode"), 2)
        self.assertNotIn(b"/DCTDecode", data)
        self.assertNotIn(b"/CreationDate", data)
        self.assertNotIn(b"/ID", data)
        contract = rl.check_pdf_contract(first["pdf"])
        self.assertEqual(contract["status"], "pass", contract)
        self.assertEqual([p["profile"] for p in contract["pages"]], ["gray", "rgb"])
        for p in contract["pages"]:
            self.assertEqual(p["media_box"], [0., 0., 595.2, 841.92])
        actual = decode_pages(first["pdf"])
        np.testing.assert_array_equal(actual[0], gray[..., 0])
        np.testing.assert_array_equal(actual[1], cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB))
        self.assertEqual(pdf_page_count(Path(first["pdf"])), 2)

    def test_png_color_pixels_jpg_quality_and_preview_bytes_unchanged(self):
        page = self.page()
        page[150:200, 180:230] = (80, 90, 100)  # near-gray PDF, original PNG/JPG
        out = self.export([page], formats=["png", "jpg", "pdf"])
        png, jpg = map(Path, out["images"])
        np.testing.assert_array_equal(cv2.imread(str(png)), page)
        with Image.open(png) as im:
            self.assertAlmostEqual(im.info["dpi"][0], 300, places=0)
        rgb = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
        self.addCleanup(rgb.close)
        expected = io.BytesIO()
        rgb.save(expected, "JPEG", quality=COMPOSED_JPEG_QUALITY, dpi=(300, 300))
        self.assertEqual(jpg.read_bytes(), expected.getvalue())
        scale = COMPOSED_PREVIEW_WIDTH / float(rgb.width)
        preview = rgb.resize((COMPOSED_PREVIEW_WIDTH, max(1, round(rgb.height * scale))), Image.LANCZOS)
        self.addCleanup(preview.close)
        expected = io.BytesIO()
        preview.save(expected, "JPEG", quality=88)
        self.assertEqual(Path(out["preview_images"][0]).read_bytes(), expected.getvalue())
        np.testing.assert_array_equal(decode_pages(out["pdf"])[0], cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))

    def test_pdf_not_requested_keeps_image_only_selection(self):
        page = np.full((180, 240, 3), 255, np.uint8)
        out = self.export([page], formats=["jpg"])
        self.assertIsNone(out["pdf"])
        self.assertEqual(out["formats"], ["jpg"])
        self.assertEqual(len(out["images"]), 1)
        self.assertEqual(len(out["preview_images"]), 1)
        self.assertFalse((self.work / "export" / "sheet_export.pdf").exists())

    def test_reject_dct_even_when_actual_jpeg_is_valid(self):
        buf = io.BytesIO()
        Image.fromarray(self.page()[..., 0]).save(buf, "JPEG", quality=92)
        path = self.work / "jpeg.pdf"
        fixture_pdf(path, encoded=buf.getvalue(), image_filter="DCTDecode")
        contract = rl.check_pdf_contract(path)
        self.assertEqual(contract["status"], "fail", contract)
        self.assertIn("FlateDecode", contract["issues"][0]["detail"])

    def test_each_format_violation_is_rejected(self):
        path = self.work / "mutation.pdf"
        fixture_pdf(path)
        self.assertEqual(rl.check_pdf_contract(path)["status"], "pass")
        mutations = {
            "bpc": {"bpc": 4}, "colorspace": {"color_space": "Indexed"},
            "filter_array": {"image_extra": b" /Filter [/FlateDecode]"},
            "smask": {"image_extra": b" /SMask 5 0 R"},
            "mask": {"image_extra": b" /Mask []"}, "decode": {"image_extra": b" /Decode [0 1]"},
            "predictor": {"image_extra": b" /DecodeParms << /Predictor 2 >>"},
            "interpolate": {"image_extra": b" /Interpolate true"},
            "annots": {"page_extra": b" /Annots []"}, "rotate": {"page_extra": b" /Rotate 90"},
            "rotate_zero": {"page_extra": b" /Rotate 0"},
            "crop": {"page_extra": b" /CropBox [0 0 500 800]"}, "size": {"size": (500, 800)},
            "dpi": {"width": 1240, "height": 1754}, "dimensions": {"width": 0},
            "extra_image": {"resources": b"<< /XObject << /Im 5 0 R /Second 5 0 R >> >>"},
            "name": {"resources": b"<< /XObject << /image 5 0 R >> >>"},
            "clip": {"contents": b"q 0 0 10 10 re W n 595.2 0 0 841.92 0 0 cm /Im Do Q"},
            "text": {"contents": b"q 595.2 0 0 841.92 0 0 cm /Im Do Q BT ET"},
            "matrix": {"contents": b"q 595.2 0 0 841.92 2 0 cm /Im Do Q"},
            "matrix_size": {"contents": b"q 595.205 0 0 841.92 0 0 cm /Im Do Q"},
            "comment": {"contents": b"q 595.2 0 0 841.92 0 0 cm /Im Do Q % extra\n"},
            "wrong_rgb_profile": {"color_space": "DeviceRGB"},
            "short_pixels": {"raw": b"\xff"},
            "extra_pixels": {"raw": b"\xff" * (2480 * 3508 + 1)},
            "trailing_stream": {"encoded": zlib.compress(b"\xff" * (2480 * 3508)) + b"extra"},
        }
        for name, kwargs in mutations.items():
            with self.subTest(name=name):
                fixture_pdf(path, **kwargs)
                contract = rl.check_pdf_contract(path)
                self.assertEqual(contract["status"], "fail", contract)
                self.assertTrue(all(i["code"] == "PDF_CONTRACT_VIOLATION" for i in contract["issues"]))

    def test_compressed_single_content_stream_remains_exact_after_decode(self):
        path = self.work / "compressed.pdf"
        fixture_pdf(path, compress_contents=True)
        self.assertEqual(rl.check_pdf_contract(path)["status"], "pass")

    def test_tampered_flate_stream_fails(self):
        encoded = bytearray(zlib.compress(b"\xff" * (2480 * 3508), level=9))
        encoded[-1] ^= 1  # Adler checksum corruption, valid object lengths and xref
        path = self.work / "tampered.pdf"
        fixture_pdf(path, encoded=bytes(encoded))
        contract = rl.check_pdf_contract(path)
        self.assertEqual(contract["status"], "fail", contract)
        self.assertEqual(contract["issues"][0]["code"], "PDF_CONTRACT_VIOLATION")

    def test_erased_staff_attached_dot_fails_local_delivery_comparison(self):
        page = np.full((3508, 2480, 3), 255, np.uint8)
        page[120, 40:2440] = 0
        page[119:122, 90:93] = 0
        missing = page.copy()
        missing[119:122, 90:93] = 255
        missing[120, 90:93] = 0  # staff unchanged; only attached dot removed
        expected = vc.contrast_map(page)
        features = vc.strip_features(expected)
        centres = vc.obligation_centres(features, expected.shape, expected)
        for raster, name, count in ((page, "control", 0), (missing, "erased", 1)):
            out = self.export([raster], name)
            # The format checker does not claim source preservation.
            self.assertEqual(rl.check_pdf_contract(out["pdf"])["status"], "pass")
            actual = vc.contrast_map(decode_pages(out["pdf"])[0])
            residual = np.maximum(expected.astype(np.int16) - actual.astype(np.int16), 0)
            failed = (vc.window_mean(residual) > 0) & centres
            findings = vc.group_findings(failed, "C", "fail", "DELIVERED_FEATURE_MISSING")
            self.assertEqual(len(findings), count)
            if count:
                self.assertEqual(findings[0]["severity"], "fail")
                x0, y0, x1, y1 = findings[0]["bbox"]
                self.assertTrue(x0 <= 91 < x1 and y0 <= 120 < y1)
                self.assertLessEqual(x1 - x0, 5)

    def test_input_resolution_and_raster_validation(self):
        for dpi in (0, -1, float("nan"), float("inf")):
            with self.subTest(dpi=dpi), self.assertRaises(ValueError):
                export_composed_pages(pages=[self.page()], formats=["pdf"],
                                      workspace=self.work, logger=lambda _m: None, dpi=dpi)
        for page in (np.zeros((10, 10), np.uint8), np.zeros((10, 10, 4), np.uint8),
                     np.zeros((10, 10, 3), np.float32), np.zeros((0, 10, 3), np.uint8)):
            with self.subTest(shape=page.shape, dtype=page.dtype), self.assertRaises(RuntimeError):
                self.export([page])


if __name__ == "__main__":
    unittest.main()
