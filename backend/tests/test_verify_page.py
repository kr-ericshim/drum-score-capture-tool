"""Stage C controls; adapters here are provisional until Stage B lands."""
import base64
import copy
from pathlib import Path
import tempfile
import unittest
import zlib

import cv2
import numpy as np
from PIL import Image

from app.pipeline import reflow_verify_common as common
from app.pipeline import reflow_verify_page as page


def packed(image):
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("PNG encode failed")
    return {"png": base64.b64encode(buf).decode(), "sha256": common.pixels_sha256(image)}


def feature_records(image, sid, *, supporters, **extra):
    # Stage A assigns its own stable IDs; shared strip_features' temporary IDs
    # can collide on multi-component real strips (request for the lead).
    out = []
    for index, feature in enumerate(common.strip_features(common.contrast_map(image))):
        feature = dict(feature, id=f"{sid}:feature-{index}")
        out.append(common.feature_record(feature, supporters=supporters, **extra))
    return out


def resize_stage(sw, sh, ow, oh, method="cubic", *, x=0, y=0):
    sx, sy = ow / sw, oh / sh
    spec = {"source_size": [sw, sh], "output_size": [ow, oh], "interpolation": method}
    matrix = [[sx, 0, x + (sx - 1) / 2], [0, sy, y + (sy - 1) / 2], [0, 0, 1]]
    return spec, matrix


def certificate(image, *, output_size=None, method="cubic", origin=(12, 10), page_px=(170, 100), features=True):
    h, w = image.shape[:2]
    ow, oh = output_size or (w, h)
    spec, pre = resize_stage(w, h, ow, oh, method)
    pg, matrix = resize_stage(ow, oh, ow, oh, "cubic", x=origin[0], y=origin[1])
    rec = {"strip_id": "s", "page_index": 0, "copy_index": 0, "line_id": "l", "owned_strip_bbox": [0, 0, w, h],
           "transform": [{"stage": "strip_to_line", "kind": "piecewise", "pre_matrix": pre, "pre_resample": spec,
                          "pieces": [{"src_bbox": [0, 0, ow, oh], "matrix": np.eye(3).tolist()}]},
                         {"stage": "line_to_page", "kind": "affine", "matrix": matrix, "resample": pg}]}
    cert = {"plan_sha256": common.json_sha256({"instances": [rec]}), "strips": {"s": common.pixels_sha256(image)},
            "instances": [rec], "page_px": list(page_px), "findings": []}
    if features:
        cert["features"] = {"s": feature_records(image, "s", supporters=["a", "b"])}
    return cert


def write_pdf(path, pages, *, gray=True, dct=False, commands=None, page_extra=b"", parent_extra=b"", image_extra=b""):
    """A narrow lossless fixture writer independent of the expected renderer.

    Also emits malformed-container controls. Actual export writer tests belong
    to WP; this helper does not certify production export integration.
    """
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    refs = []
    for pixels in pages:
        rgb = pixels if pixels.ndim == 2 else cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
        if gray:
            raster = np.asarray(Image.fromarray(rgb).convert("L"))
        else:
            raster = np.asarray(Image.fromarray(rgb).convert("RGB"))
        h, w = raster.shape[:2]
        pi = len(objects) + 1
        ii, ci = pi + 1, pi + 2
        refs.append(pi)
        mw, mh = page.A4_POINTS
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {mw:.8f} {mh:.8f}] /Resources << /XObject << /Im {ii} 0 R >> >> /Contents {ci} 0 R ".encode() + page_extra + b" >>")
        payload = zlib.compress(raster.tobytes())
        dictionary = f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /BitsPerComponent 8 /ColorSpace /{'DeviceGray' if gray else 'DeviceRGB'} /Filter /{'DCTDecode' if dct else 'FlateDecode'} /Length {len(payload)} ".encode()
        objects.append(dictionary + image_extra + b" >>\nstream\n" + payload + b"\nendstream")
        command = commands or f"q {mw:.8f} 0 0 {mh:.8f} 0 0 cm /Im Do Q".encode()
        objects.append(f"<< /Length {len(command)} >>\nstream\n".encode() + command + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Count {len(refs)} /Kids [".encode() + b" ".join(f"{p} 0 R".encode() for p in refs) + b"] " + parent_extra + b" >>"
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    offset = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for position in offsets[1:]:
        result.extend(f"{position:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF\n".encode())
    Path(path).write_bytes(result)


def staff_and_dots():
    image = np.full((70, 130, 3), 255, np.uint8)
    for y in (10, 20, 30, 40, 50):
        image[y, 5:125] = 0
    image[19:22, 60:63] = 0
    image[55:58, 80:83] = 0
    image[12:40, 30] = 0
    image[5:8, 100:104] = 127
    return image


class VerifyPage(unittest.TestCase):
    def setUp(self):
        self.image = staff_and_dots()
        self.cert = certificate(self.image)
        self.expected = page.render_expected(self.cert, {"s": self.image}, [], 1)

    def verify(self, actual, *, cert=None, image=None, generated=None, profile="lossless-rgb"):
        return page.verify_pages(cert or self.cert, {"s": self.image if image is None else image}, None,
                                 generated=generated or [], profile=profile, pages=[actual])

    def codes(self, result):
        return {f["code"] for f in result["findings"]}

    def test_clean_page_pass(self):
        result = self.verify(self.expected[0])
        self.assertEqual(result["status"], "pass", result["findings"])
        self.assertFalse(result["counters"]["pdf_contract_checked"])
        self.assertIsNone(result["pdf_sha256"])

    def test_erased_isolated_dot(self):
        actual = self.expected[0].copy()
        actual[65:68, 92:95] = 255
        result = self.verify(actual)
        self.assertEqual(result["status"], "fail")
        self.assertIn("DELIVERED_FEATURE_MISSING", self.codes(result))

    def test_erased_staff_attached_dot(self):
        actual = self.expected[0].copy()
        actual[29:32, 72:75] = 255
        actual[30, 72:75] = 0  # Keep every staff pixel, erase only the attached dot.
        result = self.verify(actual)
        self.assertIn("DELIVERED_FEATURE_MISSING", self.codes(result))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["counters"]["line_registrations"][0]["offset"], [0, 0])

    def test_added_two_by_two_dot_anywhere_on_page(self):
        actual = self.expected[0].copy()
        actual[85:87, 150:152] = 0
        result = self.verify(actual)
        self.assertIn("DELIVERED_EXTRA_INK", self.codes(result))
        self.assertEqual(result["status"], "fail")

    def test_one_offset_for_whole_line_one_pixel_pass_two_pixels_fail(self):
        for dx, dy in ((1, 0), (0, 1), (-1, -1), (2, 0), (0, -2), (3, 3)):
            with self.subTest(offset=(dx, dy)):
                actual = np.full_like(self.expected[0], 255)
                actual[10 + dy:80 + dy, 12 + dx:142 + dx] = self.image
                result = self.verify(actual)
                self.assertEqual(result["counters"]["line_registrations"][0]["offset"], [dx, dy])
                self.assertEqual(result["status"], "pass" if max(abs(dx), abs(dy)) <= 1 else "fail", result["findings"])
                self.assertEqual("PLACEMENT_MISMATCH" in self.codes(result), max(abs(dx), abs(dy)) > 1)

    def test_area_shrink_feature_erased_in_both_is_review(self):
        image = np.full((48, 48, 3), 255, np.uint8)
        image[17, 17] = 0
        cert = certificate(image, output_size=(6, 6), method="area")
        expected = page.render_expected(cert, {"s": image}, [], 1)[0]
        result = self.verify(expected, cert=cert, image=image)
        self.assertEqual(result["status"], "review_required", result["findings"])
        self.assertIn("OUTPUT_FIDELITY", self.codes(result))

    def test_staff_seam_and_preexisting_paper(self):
        actual = self.expected[0].copy()
        actual[20:61, 82] = 255
        result = self.verify(actual)
        self.assertIn("STAFF_SEAM", self.codes(result))
        self.assertTrue(all(f["severity"] == "review_required" for f in result["findings"] if f["code"] == "STAFF_SEAM"))
        image = self.image.copy(); image[10:51, 70] = 255
        cert = certificate(image)
        clean = page.render_expected(cert, {"s": image}, [], 1)[0]
        self.assertNotIn("STAFF_SEAM", self.codes(self.verify(clean, cert=cert, image=image)))

    def test_committed_strip_tampering_fails(self):
        image = self.image.copy(); image[19:22, 60:63] = 255
        result = self.verify(self.expected[0], image=image)
        self.assertEqual(result["status"], "fail")
        self.assertIn("ARTIFACT_MISMATCH", self.codes(result))

    def test_forwarded_feature_evidence_tampering_fails(self):
        cert = copy.deepcopy(self.cert)
        feature = next(f for f in cert["features"]["s"] if f["bbox"][:2] == [80, 55])
        feature["mask"] = common.pack_mask(np.zeros_like(common.unpack_mask(feature["mask"])))
        actual = self.expected[0].copy(); actual[65:68, 92:95] = 255
        result = self.verify(actual, cert=cert)
        self.assertEqual(result["status"], "fail")
        self.assertIn("ARTIFACT_MISMATCH", self.codes(result))

    def test_generated_template_header_and_tamper(self):
        template = np.full((4, 6, 3), 255, np.uint8); template[1:3, 1:5] = 0
        gen = {"page_index": 0, "origin": [4, 85], "template": packed(template), "generator": "fixture", "inputs": {"text": "header"}}
        cert = copy.deepcopy(self.cert); cert["generated_sha256"] = common.json_sha256([gen])
        actual = page.render_expected(self.cert, {"s": self.image}, [gen], 1)[0]
        self.assertEqual(self.verify(actual, cert=cert, generated=[gen])["status"], "pass")
        changed = template.copy(); changed[1, 1] = 255
        bad = copy.deepcopy(gen); bad["template"]["png"] = packed(changed)["png"]
        result = self.verify(actual, generated=[bad])
        self.assertEqual(result["status"], "fail")
        self.assertIn("RENDER_CONTRACT", self.codes(result))
        bad["template"] = packed(changed)  # Updating a self-hash is not an anchor.
        result = self.verify(actual, cert=cert, generated=[bad])
        self.assertIn("ARTIFACT_MISMATCH", self.codes(result))
        self.assertEqual(self.verify(actual, generated=[gen])["status"], "review_required")

    def test_bad_resize_metadata_missing_feature_records_and_unknown_profile(self):
        cert = copy.deepcopy(self.cert)
        cert["instances"][0]["transform"][0]["pre_matrix"][0][2] += 2
        self.assertIn("RENDER_CONTRACT", self.codes(self.verify(self.expected[0], cert=cert)))
        cert = copy.deepcopy(self.cert); cert.pop("features")
        self.assertEqual(self.verify(self.expected[0], cert=cert)["status"], "review_required")
        self.assertIn("PDF_CONTRACT", self.codes(self.verify(self.expected[0], profile="jpeg")))

    def test_local_resample_replays_global_phase(self):
        image = np.random.default_rng(42).integers(0, 256, (43, 67), dtype=np.uint8)
        for method, size in (("area", (37, 29)), ("cubic", (89, 61)), ("cubic", (37, 29))):
            spec, _m = resize_stage(67, 43, *size, method)
            actual = cv2.resize(image, size, interpolation=page._METHOD[method])
            box = [3, 4, 19, 23]
            local = page._local_resize(image, spec, box)
            self.assertLessEqual(int(np.abs(actual[4:23, 3:19].astype(int) - local).max()), 1)

    def test_lossless_pdf_gray_and_rgb_contract_and_digest(self):
        cert = certificate(self.image, page_px=page.PAGE_SIZE, origin=(100, 100))
        expected = page.render_expected(cert, {"s": self.image}, [], 1)
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            path = Path(directory) / "page.pdf"
            for gray in (True, False):
                profile = "lossless-gray" if gray else "lossless-rgb"
                write_pdf(path, expected, gray=gray)
                result = page.verify_pages(cert, {"s": self.image}, path, generated=[], profile=profile)
                self.assertEqual(result["status"], "pass", result["findings"])
                self.assertEqual(result["pdf_sha256"], common.file_sha256(path))
                self.assertTrue(result["counters"]["pdf_contract_checked"])

    def test_current_production_lossless_writer(self):
        from app.pipeline.export import _write_composed_pdf
        cert = certificate(self.image, page_px=page.PAGE_SIZE, origin=(100, 100))
        expected = page.render_expected(cert, {"s": self.image}, [], 1)
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            path = Path(tmp) / "production.pdf"
            _write_composed_pdf(path, expected, 300.)
            result = page.verify_pages(cert, {"s": self.image}, path, generated=[], profile="lossless-gray")
            self.assertEqual(result["status"], "pass", result["findings"])
            self.assertTrue(np.array_equal(page.decode_lossless_pdf(path, profile="lossless-gray")[0], common.gray(expected[0])))

    def test_mixed_gray_rgb_production_pdf_uses_each_frozen_profile(self):
        from app.pipeline.export import _write_composed_pdf
        color = self.image.copy(); color[55:58, 80:83] = [0, 0, 200]
        cert = certificate(self.image, page_px=page.PAGE_SIZE, origin=(100, 100))
        second = copy.deepcopy(cert["instances"][0]); second.update(strip_id="c", page_index=1, line_id="l2")
        cert["instances"].append(second)
        cert["strips"]["c"] = common.pixels_sha256(color)
        cert["features"]["c"] = feature_records(color, "c", supporters=["a", "b"])
        images = {"s": self.image, "c": color}
        expected = page.render_expected(cert, images, [], 2)
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            path = Path(tmp) / "mixed.pdf"
            _write_composed_pdf(path, expected, 300.)
            result = page.verify_pages(cert, images, path, generated=[], profile="lossless")
            self.assertEqual(result["status"], "pass", result["findings"])
            self.assertEqual([p["profile"] for p in result["pages"]], ["lossless-gray", "lossless-rgb"])

    def test_wb_plan_records_bind_instances_and_generated(self):
        cert = copy.deepcopy(self.cert)
        rec = cert["instances"][0]
        payload = {"page_px": cert.pop("page_px"), "placements": [{**{k: rec[k] for k in ("strip_id", "page_index", "copy_index", "line_id")},
                    "stages": copy.deepcopy(rec["transform"])}], "generated_origins": []}
        cert.update(plan_records=payload, plan_sha256=common.json_sha256(payload))
        self.assertEqual(self.verify(self.expected[0], cert=cert)["status"], "pass")
        cert["instances"][0]["transform"][1]["matrix"][0][2] += 2
        self.assertIn("ARTIFACT_MISMATCH", self.codes(self.verify(self.expected[0], cert=cert)))
        cert["plan_records"]["page_px"][0] += 1
        self.assertIn("ARTIFACT_MISMATCH", self.codes(self.verify(self.expected[0], cert=cert)))

    def test_pdf_dct_placement_masks_rotation_and_wrong_profile_fail(self):
        cert = certificate(self.image, page_px=page.PAGE_SIZE, origin=(100, 100))
        expected = page.render_expected(cert, {"s": self.image}, [], 1)
        variants = [{"dct": True}, {"commands": b"q 595.2756 0 0 841.8898 2 0 cm /Im Do Q"},
                    {"commands": b"q 595.2756 0 0 841.8898 0 0 cm /Im Do Q 1 0 0 rg"},
                    {"page_extra": b"/Annots []"}, {"parent_extra": b"/Rotate 90"}, {"image_extra": b"/SMask 5 0 R"}]
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            path = Path(directory) / "bad.pdf"
            for kwargs in variants:
                with self.subTest(kwargs=kwargs):
                    write_pdf(path, expected, **kwargs)
                    result = page.verify_pages(cert, {"s": self.image}, path, generated=[], profile="lossless-gray")
                    self.assertEqual(result["status"], "fail")
                    self.assertIn("PDF_CONTRACT", self.codes(result))
            write_pdf(path, expected, gray=True)
            result = page.verify_pages(cert, {"s": self.image}, path, generated=[], profile="lossless-rgb")
            self.assertIn("PDF_CONTRACT", self.codes(result))

    def test_two_piece_ownership_and_two_stage_resize(self):
        cert = certificate(self.image, output_size=(104, 56), method="area")
        rec = cert["instances"][0]
        rec["transform"][0]["pieces"] = [{"src_bbox": [0, 0, 52, 56], "matrix": np.eye(3).tolist()},
                                         {"src_bbox": [54, 0, 104, 56], "matrix": [[1, 0, -2], [0, 1, 0], [0, 0, 1]]}]
        spec, matrix = resize_stage(102, 56, 112, 62, "cubic", x=12, y=10)
        rec["transform"][1].update(resample=spec, matrix=matrix)
        actual = page.render_expected(cert, {"s": self.image}, [], 1)[0]
        self.assertFalse(any(f["severity"] == "fail" for f in self.verify(actual, cert=cert)["findings"]))

    def test_recorded_column_replica_is_repeated_without_affine_blur(self):
        image = np.full((24, 24, 3), 255, np.uint8)
        image[10, 12] = 0
        cert = certificate(image)
        spec, matrix = resize_stage(40, 24, 40, 24, "cubic", x=12, y=10)
        rec = cert["instances"][0]
        rec["transform"][0]["pieces"] = [{"src_bbox": [12, 0, 13, 24], "column_repeat": 5,
                                         "matrix": [[5, 0, -50], [0, 1, 0], [0, 0, 1]]}]
        rec["transform"][1].update(resample=spec, matrix=matrix)
        actual = page.render_expected(cert, {"s": image}, [], 1)[0]
        self.assertTrue((actual[20, 20:25] == 0).all())
        result = self.verify(actual, cert=cert, image=image)
        self.assertFalse(any(f["severity"] == "fail" for f in result["findings"]), result["findings"])

    def test_scaffold_donor_cache_can_later_supply_obligations(self):
        cert = certificate(self.image, page_px=(170, 190))
        first = cert["instances"][0]
        first["strip_id"] = "t"
        second = copy.deepcopy(first); second.update(strip_id="s", line_id="l2")
        second["transform"][1]["matrix"][1][2] = 100
        first["transform"][0]["pieces"] = [{"src_bbox": [0, 0, 51, 70], "matrix": np.eye(3).tolist()},
                                           {"src_bbox": [54, 0, 130, 70], "matrix": np.eye(3).tolist()}]
        cert["instances"].append(second)
        cert["strips"]["t"] = cert["strips"]["s"]
        cert["features"]["t"] = cert["features"]["s"]
        template = np.repeat(self.image[:, 14:15], 3, axis=1)
        gen = {"kind": "staff_scaffold", "line_id": "l", "page_index": 0, "strip_id": "s",
               "box_L": [51, 0, 54, 70], "source_resample": first["transform"][0]["pre_resample"],
               "source_column_R": 14, "source_y_L": 0, "template": packed(template), "origin": [63, 10],
               "generator": "fixture", "inputs": {"op": "insert_scaffold_columns"}}
        cert["generated_sha256"] = common.json_sha256([gen])
        images = {"s": self.image, "t": self.image}
        expected = page.render_expected(cert, images, [gen], 1)
        result = page.verify_pages(cert, images, None, generated=[gen], profile="lossless-rgb", pages=expected)
        self.assertEqual(result["status"], "pass", result["findings"])


if __name__ == "__main__":
    unittest.main()
