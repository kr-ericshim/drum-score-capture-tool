"""Source-frame seams: bypass only the invisible-continuation edge veto."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_measure as rm
from test_reflow_boundaries import G, INK, analyse, boundary_at, make_strip


def manifest(y=841, scale=1.0, height=1080):
    return {"source": {"frame_size": [1500, height]},
            "source_to_crop": [scale, 0, 0, 0, scale, -y * scale, 0, 0, 1]}


class FrameMappingTests(unittest.TestCase):
    def test_half_open_bottom_is_last_pixel_row(self):
        self.assertEqual(rb.source_frame_edges([0, 6, 1500, 239], manifest()),
                         {"top": False, "bottom": True})
        self.assertFalse(rb.source_frame_edges([0, 6, 1500, 238], manifest())["bottom"])

    def test_top_and_half_pixel_tolerance(self):
        for y, expected in ((0, True), (.5, True), (.501, False), (-.5, True), (-.501, False)):
            with self.subTest(y=y):
                self.assertEqual(rb.source_frame_edges([0, 0, 500, 100], manifest(y=y))["top"], expected)

    def test_downscale_maps_back_before_tolerance(self):
        self.assertTrue(rb.source_frame_edges([0, 1, 750, 120], manifest(scale=.5))["bottom"])
        self.assertFalse(rb.source_frame_edges([0, 1, 750, 119], manifest(scale=.5))["bottom"])

    def test_invalid_or_missing_mapping_fails_closed(self):
        for m in ({}, {"source": {"frame_size": [1500, 1080]}},
                  dict(manifest(), source_to_crop=[0]*9),
                  dict(manifest(), source_to_crop=[float('nan')]*9)):
            with self.subTest(manifest=m):
                self.assertEqual(rb.source_frame_edges([0, 0, 10, 239], m),
                                 {"top": False, "bottom": False})

    def test_skewed_row_is_not_a_global_frame_edge(self):
        m = manifest(y=0)
        m["source_to_crop"][3] = .01
        self.assertFalse(rb.source_frame_edges([0, 0, 1500, 100], m)["top"])

    def test_jump_owner_offsets_and_trim_are_used(self):
        rec = {"size": [2000, 233], "box_crop": [0, 6, 2000, 239], "jump": {"owners": [
            {"strip_cols": [0, 1000], "offset_x": 0, "offset_y": -6},
            {"strip_cols": [1000, 2000], "offset_x": 900, "offset_y": -6}]}}
        self.assertTrue(rb.strip_frame_edges(rec, manifest())["bottom"])
        mixed = copy.deepcopy(rec)
        mixed["jump"]["owners"][1]["offset_y"] = -5
        self.assertFalse(rb.strip_frame_edges(mixed, manifest())["bottom"])
        rec["size"][1] -= 1
        self.assertFalse(rb.strip_frame_edges(rec, manifest())["bottom"])
        self.assertFalse(rb.strip_frame_edges({"jump": {"owners": []}}, manifest())["bottom"])


class EdgeVetoTests(unittest.TestCase):
    def fixture(self, side="bottom", **kwargs):
        image, rec = make_strip(**kwargs)
        an = analyse(image, rec)
        seam = boundary_at(rb.strip_boundaries(an), 2)["seam_x"]
        # A narrow visible stem stays clear of the seam, but its invisible
        # continuation falls within the original edge-veto reach.
        x = seam - G // 2
        if side == "bottom":
            cv2.rectangle(image, (x, image.shape[0]-12), (x+1, image.shape[0]-1), INK, -1)
        else:
            cv2.rectangle(image, (x, 0), (x+1, 12), INK, -1)
        return image, rec, seam

    def classify(self, image, rec, seam):
        return rb.classify_seam(analyse(image, rec), seam)

    def test_top_and_bottom_frame_edges_remove_only_edge_reason(self):
        for side in ("top", "bottom"):
            with self.subTest(side=side):
                image, rec, seam = self.fixture(side)
                pixels = image.copy()
                before = self.classify(image, rec, seam)
                self.assertEqual(before["unknown_reasons"], ["CONTENT_AT_STRIP_EDGE"])
                rec["frame_edges"] = {side: True}
                after = self.classify(image, rec, seam)
                self.assertEqual(after["class"], rb.SAFE, after)
                self.assertEqual(after["evidence"]["edge_veto_skipped"], "source_frame_edge")
                self.assertEqual(after["evidence"]["edge_veto_skipped_sides"], [side])
                np.testing.assert_array_equal(image, pixels)

    def test_interior_roi_keeps_edge_veto(self):
        image, rec, seam = self.fixture()
        rec["frame_edges"] = {"top": False, "bottom": False}
        result = self.classify(image, rec, seam)
        self.assertIn("CONTENT_AT_STRIP_EDGE", result["unknown_reasons"])
        self.assertNotIn("edge_veto_skipped", result["evidence"])

    def test_opposite_edge_still_vetoes(self):
        image, rec, seam = self.fixture()
        cv2.rectangle(image, (seam-G//2, 0), (seam-G//2+1, 12), INK, -1)
        rec["frame_edges"] = {"bottom": True}
        result = self.classify(image, rec, seam)
        self.assertEqual(result["class"], rb.UNKNOWN)
        self.assertIn("CONTENT_AT_STRIP_EDGE", result["unknown_reasons"])
        self.assertEqual(result["evidence"]["edge_veto_skipped_sides"], ["bottom"])

    def test_visible_crossing_remains_locked(self):
        image, rec, seam = self.fixture()
        cv2.rectangle(image, (seam-20, image.shape[0]-3), (seam+20, image.shape[0]-1), INK, -1)
        rec["frame_edges"] = {"bottom": True}
        result = self.classify(image, rec, seam)
        self.assertEqual(result["class"], rb.LOCKED, result)
        self.assertTrue(result["locked_reasons"])

    def test_visible_clearance_still_required(self):
        image, rec, seam = self.fixture()
        image[220, seam-2] = INK
        rec["frame_edges"] = {"bottom": True}
        result = self.classify(image, rec, seam)
        self.assertEqual(result["class"], rb.UNKNOWN, result)
        self.assertIn("INSUFFICIENT_CLEARANCE", result["unknown_reasons"])

    def test_source_clipped_diagnostic_alone_keeps_the_veto(self):
        # without verified frame geometry the page's clipping diagnosis does not waive the veto
        image, rec, seam = self.fixture()
        rec["source_clipped"] = {"sides": ["bottom"], "columns": [0, image.shape[1]]}
        result = self.classify(image, rec, seam)
        self.assertEqual(result["class"], rb.UNKNOWN)
        self.assertIn("CONTENT_AT_STRIP_EDGE", result["unknown_reasons"])

    def test_crossing_on_the_last_pixel_row_is_not_safe(self):
        image, rec, seam = self.fixture()
        image[image.shape[0] - 1, seam - 25:seam + 25] = INK  # a beam visible only on the last row
        rec["frame_edges"] = {"bottom": True}
        self.assertNotEqual(self.classify(image, rec, seam)["class"], rb.SAFE)

    def test_thin_line_crossing_just_above_the_edge_is_not_safe(self):
        image, rec, seam = self.fixture()
        h = image.shape[0]
        cv2.line(image, (seam - 60, h - 6), (seam + 60, h - 3), INK, 1)  # a hairpin leg running off the frame
        rec["frame_edges"] = {"bottom": True}
        self.assertNotEqual(self.classify(image, rec, seam)["class"], rb.SAFE)

    def test_no_audit_skip_when_no_edge_veto_was_needed(self):
        image, rec = make_strip()
        rec["frame_edges"] = {"top": True, "bottom": True}
        result = boundary_at(rb.strip_boundaries(analyse(image, rec)), 2)
        self.assertEqual(result["class"], rb.SAFE)
        self.assertNotIn("edge_veto_skipped", result["evidence"])

    def test_measure_build_threads_manifest_without_mutating_record(self):
        image, rec, _seam = self.fixture()
        original = copy.deepcopy(rec)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"strip.png"
            cv2.imwrite(str(path), image)
            decided = [{"system": {"id": "sys-t", "layout": "bottom_bar", "strip": rec},
                        "variant": "clean", "strip_path": str(path)}]
            # Registration is supplied separately; inspect the real analysis input.
            observed = []
            real = rb.analyse_strip
            def capture(img, record, **kw):
                observed.append(copy.deepcopy(record))
                return real(img, record, **kw)
            m = manifest(y=0, height=image.shape[0])
            with patch.object(rb, "analyse_strip", side_effect=capture):
                rm.build_atoms(decided, target_gap_px=G, context={"manifest": m})
        self.assertEqual(observed[0]["frame_edges"], {"top": True, "bottom": True})
        self.assertEqual(rec, original)


if __name__ == "__main__":
    unittest.main()
