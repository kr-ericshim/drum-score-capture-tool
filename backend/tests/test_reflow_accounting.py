"""reflow_accounting: exact native-resolution reconstruction and the protected-pixel ledger."""

import unittest

import numpy as np

from app.pipeline import reflow_accounting as ra
from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_units as ru
from test_reflow_boundaries import G, TOP, _proposed_seam_x, make_strip, observations_of


def col_units(xs, w, h):
    edges = [0] + list(xs) + [w]
    return [{"id": f"u{i}", "occurrence_id": "sys-001", "box": [edges[i], 0, edges[i + 1], h]} for i in range(len(edges) - 1)]


class Reconstruction(unittest.TestCase):
    def setUp(self):
        img, self.rec = make_strip(lyrics=True, blur=0.7)
        # one-pixel dots (dark and faint) and anti-aliased fringes near the seams
        s = _proposed_seam_x(1)
        img[TOP + 4 * G + 45, s - 9] = (30, 30, 30)
        img[TOP - 45, s + 11] = (200, 200, 200)
        self.img = img
        self.an = rb.analyse_strip(img, self.rec, observations=observations_of(img))

    def test_split_at_safe_seams_reassembles_exactly(self):
        bnds = rb.strip_boundaries(self.an)
        self.assertTrue(any(b["class"] == rb.SAFE for b in bnds))
        units = ru.system_units(self.an, bnds, occurrence_id="sys-001", asset={"pixels_sha256": "a", "size": [1, 1]})
        acc = ra.account_asset(self.img, units, self.an.protected)
        self.assertTrue(acc["exact_reconstruction"])
        self.assertEqual(acc["lost_px"], 0)
        self.assertEqual(acc["duplicated_px"], 0)
        self.assertEqual(acc["mismatched_px"], 0)
        self.assertEqual(acc["protected_lost_px"], 0)
        self.assertEqual(acc["protected_duplicated_px"], 0)
        self.assertEqual(sum(e["protected_px"] for e in acc["entries"]), acc["protected_px"])
        self.assertEqual(sum(e["pixels"] for e in acc["entries"]), acc["pixels"])

    def test_every_split_position_reassembles_exactly(self):
        h, w = self.img.shape[:2]
        for xs in ([1], [w - 1], [7, 8, 9], list(range(50, w, 97))):
            acc = ra.account_asset(self.img, col_units(xs, w, h), self.an.protected)
            self.assertTrue(acc["exact_reconstruction"], xs)

    def test_overlap_is_reported_as_duplication(self):
        h, w = self.img.shape[:2]
        units = col_units([400], w, h)
        units[1]["box"][0] = 398
        acc = ra.account_asset(self.img, units, self.an.protected)
        self.assertFalse(acc["exact_reconstruction"])
        self.assertEqual(acc["duplicated_px"], 2 * h)

    def test_gap_is_reported_as_lost_protected_content(self):
        h, w = self.img.shape[:2]
        s = _proposed_seam_x(1)
        units = col_units([s - 10], w, h)
        units[0]["box"][2] = s - 12  # the column with the one-pixel dot belongs to nobody
        units[1]["box"][0] = s - 8
        acc = ra.account_asset(self.img, units, self.an.protected)
        self.assertFalse(acc["exact_reconstruction"])
        self.assertEqual(acc["lost_px"], 4 * h)
        self.assertGreaterEqual(acc["protected_lost_px"], 1)

    def test_non_rectangular_ownership_masks(self):
        h, w = self.img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        a = (xx + yy) % 3 == 0
        units = [{"id": "a", "box": [0, 0, w, h], "_mask": a}, {"id": "b", "box": [0, 0, w, h], "_mask": ~a}]
        acc = ra.account_asset(self.img, units, self.an.protected)
        self.assertTrue(acc["exact_reconstruction"])
        units[1]["_mask"] = ~a | (xx == 5)
        self.assertFalse(ra.account_asset(self.img, units)["exact_reconstruction"])

    def test_document_totals(self):
        doc, _ = ru.build_document(job_id="j", revision=1, systems=[
            dict(system_id="sys-001", image=self.img, record=self.rec, observations=observations_of(self.img))])
        tot = doc["audit"]["accounting"]["totals"]
        self.assertEqual((tot["lost_px"], tot["duplicated_px"], tot["mismatched_px"]), (0, 0, 0))
        self.assertTrue(tot["exact_reconstruction"])
        self.assertEqual(tot["replicas"], [])
        self.assertEqual(tot["scaffold_operations"], [])
        self.assertEqual(len(doc["audit"]["accounting"]["ledger"]), len(doc["measure_units"]))


class CutStrip(unittest.TestCase):
    def test_cut_strip_must_match_the_uncut_pixels(self):
        uncut, rec = make_strip()
        rec = dict(rec, box_crop=[0, 0, 1200, uncut.shape[0]], uncut={"box_crop": [0, 0, uncut.shape[1], uncut.shape[0]]})
        strip = uncut[:, :1200].copy()
        self.assertTrue(ra.cut_strip_consistency(strip, uncut, rec)["consistent"])
        strip[100, 600] = 0 if strip[100, 600, 0] > 128 else 255
        self.assertFalse(ra.cut_strip_consistency(strip, uncut, rec)["consistent"])


if __name__ == "__main__":
    unittest.main()
