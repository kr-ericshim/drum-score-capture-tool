"""Frozen motif calibration. Run before dev-video diagnostics; no video tuning.

The production path here uses the real paper/resize/place helpers. Stage C's
expected path imports none of them. The lossless transport round trip is Flate
gray/RGB; the actual PDF grammar is covered separately in test_verify_page.
"""
from collections import Counter
import itertools
import json
from pathlib import Path
import tempfile
import time
import unittest
import zlib

import cv2
import numpy as np
from PIL import Image

from app.pipeline import reflow_measure as measure
from app.pipeline import reflow_render as production
from app.pipeline import reflow_verify_common as common
from app.pipeline import reflow_verify_page as page
from test_verify_page import certificate, feature_records, staff_and_dots, write_pdf


MOTIFS = ("isolated_dot", "staff_attached_dot", "thin_stroke", "stem_beam_junction", "x_notehead",
          "repeat_dots", "quarter_rest", "eighth_rest", "numeral", "gray_dynamic", "lyric_fragment",
          "staff_only", "barline", "double_barline", "open_notehead", "accent", "staccato",
          "tie", "ledger_note", "flag")
GAPS = (7, 9, 12, 16)
PHASES = (0., .25, .5, .75)
METHODS = ("area", "cubic")
CONTRASTS = (32, 48, 64, 96, 128, 192, 255)
WIDTHS = (1, 2, 3)
PLACEMENTS = ((8, 9), (19, 17))  # second set is held out from the fit
FROZEN_FIXTURE_VERSION = "wc-motifs-1"


def motif(name, contrast, width, phase):
    mask = np.zeros((112, 144), np.uint8)
    c = 255
    if name in ("staff_attached_dot", "staff_only", "ledger_note"):
        for y in (24, 40, 56, 72, 88):
            cv2.line(mask, (6, y), (138, y), c, width)
    if name in ("isolated_dot", "staff_attached_dot", "staccato"):
        cv2.circle(mask, (65, 40 if name == "staff_attached_dot" else 62), width, c, -1)
    elif name == "thin_stroke":
        cv2.line(mask, (38, 68), (98, 30), c, width)
    elif name == "stem_beam_junction":
        cv2.line(mask, (48, 72), (48, 30), c, width)
        cv2.line(mask, (48, 30), (102, 22), c, width + 1)
    elif name == "x_notehead":
        cv2.line(mask, (55, 47), (75, 67), c, width)
        cv2.line(mask, (55, 67), (75, 47), c, width)
    elif name == "repeat_dots":
        for y in (46, 62):
            cv2.circle(mask, (65, y), width + 1, c, -1)
    elif name == "quarter_rest":
        cv2.polylines(mask, [np.array([[65, 28], [76, 40], [60, 52], [72, 63], [63, 77]], np.int32)], False, c, width)
    elif name == "eighth_rest":
        cv2.circle(mask, (63, 44), width + 1, c, -1)
        cv2.line(mask, (63, 44), (77, 39), c, width)
        cv2.line(mask, (77, 39), (67, 76), c, width)
    elif name in ("numeral", "gray_dynamic", "lyric_fragment"):
        text = {"numeral": "28", "gray_dynamic": "mf", "lyric_fragment": "la"}[name]
        cv2.putText(mask, text, (35, 70), cv2.FONT_HERSHEY_SIMPLEX, .8, c, width, cv2.LINE_8)
    elif name in ("barline", "double_barline"):
        cv2.line(mask, (63, 22), (63, 90), c, width)
        if name == "double_barline":
            cv2.line(mask, (70, 22), (70, 90), c, width + 1)
    elif name in ("open_notehead", "ledger_note"):
        cv2.ellipse(mask, (66, 56 if name == "open_notehead" else 104), (8, 5), -20, 0, 360, c, width)
        if name == "ledger_note":
            cv2.line(mask, (51, 104), (81, 104), c, width)
    elif name == "accent":
        cv2.polylines(mask, [np.array([[49, 44], [79, 55], [49, 66]], np.int32)], False, c, width)
    elif name == "tie":
        cv2.ellipse(mask, (68, 52), (30, 14), 0, 15, 165, c, width)
    elif name == "flag":
        cv2.line(mask, (54, 83), (54, 26), c, width)
        cv2.polylines(mask, [np.array([[54, 26], [75, 34], [83, 49], [71, 57]], np.int32)], False, c, width)
    if phase:
        mask = cv2.warpAffine(mask, np.array([[1, 0, phase], [0, 1, phase]], np.float32), (144, 112),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    ink = np.rint(mask.astype(np.float64) * contrast / 255).astype(np.uint8)
    image = np.repeat((255 - ink)[..., None], 3, axis=2)
    # Near-gray colored ink exercises Pillow/OpenCV gray conversion, without
    # changing the page's white paper or tuning to real-source chroma.
    image[..., 0] = np.minimum(image[..., 0].astype(np.uint16) + np.minimum(ink, 11), 255).astype(np.uint8)
    return image


def production_case(image, gap, method, origin):
    h, w = image.shape[:2]
    ow, oh = round(w * gap / 16), round(h * gap / 16)
    # Real resize and integer placement operations used in measure mode.
    resampled = cv2.resize(production._to_page_paper(image), (ow, oh), interpolation=page._METHOD[method])
    line = np.full((oh, ow, 3), 255, np.uint8)
    measure._place(line, resampled, 0, 0)
    final = production.resize_strip(production._to_page_paper(line), ow, oh)
    px = (190, 145)
    actual = np.full((px[1], px[0], 3), 255, np.uint8)
    measure._place(actual, final, *origin)
    cert = certificate(image, output_size=(ow, oh), method=method, origin=origin, page_px=px, features=False)
    expected = page.render_expected(cert, {"s": image}, [], 1)[0]
    return cert, actual, expected


def flate_roundtrip(image, profile):
    if profile == "lossless-gray":
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pixels = np.asarray(Image.fromarray(rgb).convert("L"))
    else:
        pixels = image
    restored = np.frombuffer(zlib.decompress(zlib.compress(pixels.tobytes())), np.uint8).reshape(pixels.shape)
    return restored


def run_benign_calibration():
    started = time.perf_counter()
    result = {"fixture_version": FROZEN_FIXTURE_VERSION, "dimensions": {"motifs": 20, "gaps": list(GAPS), "phases": list(PHASES),
              "methods": list(METHODS), "contrasts": list(CONTRASTS), "widths": list(WIDTHS), "placements": [list(p) for p in PLACEMENTS]},
              "profiles": {p: {"fit_cases": 0, "holdout_cases": 0, "benign_max": 0, "holdout_max": 0,
                                "residual_histogram": Counter()} for p in page.PROFILE_EPSILON}}
    for name, gap, phase, method, contrast, width in itertools.product(MOTIFS, GAPS, PHASES, METHODS, CONTRASTS, WIDTHS):
        image = motif(name, contrast, width, phase)
        for placement_index, origin in enumerate(PLACEMENTS):
            cert, actual, expected = production_case(image, gap, method, origin)
            ec = common.contrast_map(expected)
            held = phase == .75 or placement_index == 1
            for profile, stats in result["profiles"].items():
                delivered = flate_roundtrip(actual, profile)
                residual = np.abs(ec.astype(np.int16) - common.contrast_map(delivered).astype(np.int16))
                maximum = int(residual.max())
                stats["holdout_cases" if held else "fit_cases"] += 1
                field = "holdout_max" if held else "benign_max"
                stats[field] = max(stats[field], maximum)
                stats["residual_histogram"].update({int(k): int(v) for k, v in zip(*np.unique(residual, return_counts=True))})
    result["seconds"] = time.perf_counter() - started
    for profile, stats in result["profiles"].items():
        stats["epsilon"] = stats["benign_max"] + 2
        stats["holdout_pass"] = stats["holdout_max"] <= stats["epsilon"]
        stats["residual_histogram"] = dict(sorted(stats["residual_histogram"].items()))
    return result


class VerifyCalibration(unittest.TestCase):
    def test_frozen_full_matrix_and_holdouts(self):
        result = run_benign_calibration()
        for profile, stats in result["profiles"].items():
            self.assertEqual(stats["fit_cases"], 10080)
            self.assertEqual(stats["holdout_cases"], 16800)
            self.assertEqual(stats["benign_max"], page.CALIBRATION_BENIGN_MAX[profile])
            self.assertEqual(stats["epsilon"], page.PROFILE_EPSILON[profile])
            self.assertTrue(stats["holdout_pass"])
        root = Path("/tmp/wc"); root.mkdir(exist_ok=True)
        (root / "calibration-benign.json").write_text(json.dumps(result, indent=2))
        print("\nCALIBRATION " + json.dumps(result))

    def test_every_declared_destructive_variant_and_low_contrast_widths(self):
        counts = Counter()
        for contrast, width in itertools.product(CONTRASTS, WIDTHS):
            # Native-scale control deliberately retains the weak path at 32/48,
            # not only qualified strong black ink. Resizing is exercised below.
            image = staff_and_dots()
            image[55:58, 80:83] = 255 - contrast
            image[19:22, 60:63] = 255 - contrast
            image[20, 60:63] = 0
            image[5:8, 100:104] = 255 - contrast
            image[12:40, 30] = 255
            image[12:40, 30:30 + width] = 255 - contrast
            cert = certificate(image)
            expected = page.render_expected(cert, {"s": image}, [], 1)[0]
            baseline = page.verify_pages(cert, {"s": image}, None, generated=[], profile="lossless-rgb", pages=[expected])
            self.assertEqual(baseline["status"], "pass", baseline["findings"])
            variants = {}
            isolated = expected.copy(); isolated[65:68, 92:95] = 255
            variants["erased_isolated_dot"] = (isolated, image, "DELIVERED_FEATURE_MISSING")
            attached = expected.copy(); attached[29:32, 72:75] = 255; attached[30, 72:75] = 0
            variants["erased_staff_attached_dot"] = (attached, image, "DELIVERED_FEATURE_MISSING")
            branch = expected.copy(); branch[23:31, 42:42 + width] = 255
            variants["removed_thin_branch_beam"] = (branch, image, "DELIVERED_FEATURE_MISSING")
            dynamic = expected.copy(); dynamic[15:18, 112:116] = 255
            variants["removed_gray_dynamic"] = (dynamic, image, "DELIVERED_FEATURE_MISSING")
            duplicate = expected.copy(); duplicate[85:88, 150:153] = 255 - contrast
            variants["duplicated_feature"] = (duplicate, image, "DELIVERED_EXTRA_INK")
            shifted = np.full_like(expected, 255); shifted[10:80, 14:144] = image
            variants["piece_shifted_2px"] = (shifted, image, "PLACEMENT_MISMATCH")
            altered = image.copy(); altered[55:58, 80:83] = 255
            variants["altered_evidence"] = (expected, altered, "ARTIFACT_MISMATCH")
            for name, (actual, strip, code) in variants.items():
                for profile in page.PROFILE_EPSILON:
                    with self.subTest(variant=name, contrast=contrast, width=width, profile=profile):
                        delivered = flate_roundtrip(actual, profile)
                        result = page.verify_pages(cert, {"s": strip}, None, generated=[], profile=profile, pages=[delivered])
                        self.assertEqual(result["status"], "fail", result["findings"])
                        self.assertIn(code, {f["code"] for f in result["findings"]})
                        counts[name] += 1
        # Both resize kernels, every delivered staff gap and held-out .75 phase:
        # damage all locally qualified pixels, retain staff pixels for attached dots.
        for name, gap, method, phase in itertools.product(("isolated_dot", "staff_attached_dot", "stem_beam_junction", "gray_dynamic"), GAPS, METHODS, PHASES):
            image = motif(name, 128, 3, phase)
            cert, actual, expected = production_case(image, gap, method, PLACEMENTS[1])
            cert["features"] = {"s": feature_records(image, "s", supporters=["a", "b"])}
            ox, oy = PLACEMENTS[1]
            ow, oh = cert["instances"][0]["transform"][0]["pre_resample"]["output_size"]
            if name == "staff_attached_dot":
                staff = motif("staff_only", 128, 3, phase)
                _c, no_dot, _e = production_case(staff, gap, method, PLACEMENTS[1])
                actual = no_dot
            else:
                actual[oy:oy + oh, ox:ox + ow] = 255
            for profile in page.PROFILE_EPSILON:
                delivered = flate_roundtrip(actual, profile)
                result = page.verify_pages(cert, {"s": image}, None, generated=[], profile=profile, pages=[delivered])
                self.assertIn("DELIVERED_FEATURE_MISSING", {f["code"] for f in result["findings"]}, (name, gap, method, phase, profile, result["findings"]))
                counts["resized_" + name] += 1
        # Actual PDF placement and profile are structural controls, on full A4.
        image = staff_and_dots(); cert = certificate(image, page_px=page.PAGE_SIZE)
        expected = page.render_expected(cert, {"s": image}, [], 1)
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            path = Path(tmp) / "mutation.pdf"
            for profile in page.PROFILE_EPSILON:
                gray = profile == "lossless-gray"
                write_pdf(path, expected, gray=gray, commands=b"q 595.2756 0 0 841.8898 2 0 cm /Im Do Q")
                result = page.verify_pages(cert, {"s": image}, path, generated=[], profile=profile)
                self.assertIn("PDF_CONTRACT", {f["code"] for f in result["findings"]})
                counts["altered_pdf_placement"] += 1
                write_pdf(path, expected, gray=not gray)
                result = page.verify_pages(cert, {"s": image}, path, generated=[], profile=profile)
                self.assertIn("PDF_CONTRACT", {f["code"] for f in result["findings"]})
                counts["wrong_render_profile"] += 1
        root = Path("/tmp/wc"); root.mkdir(exist_ok=True)
        (root / "calibration-destructive.json").write_text(json.dumps(dict(counts), indent=2))
        print("\nDESTRUCTIVE " + json.dumps(dict(counts)))


if __name__ == "__main__":
    unittest.main()
