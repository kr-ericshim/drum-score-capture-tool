import unittest

import numpy as np

from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_verify_common as vc


def page_with_staff_and_dot():
    img = np.full((60, 120), 255, np.uint8)
    for y in (10, 20, 30, 40, 50):
        img[y, 5:115] = 0
    img[19:22, 60:63] = 0          # dot attached to the second staff line
    img[44, 90] = 200              # faint isolated fleck (contrast 55: weak)
    return img


class VerifyCommonTest(unittest.TestCase):
    def test_contrast_and_classes(self):
        img = page_with_staff_and_dot()
        c = vc.contrast_map(img)
        self.assertEqual(int(c[10, 50]), 255)
        self.assertEqual(int(c[44, 90]), 55)
        strong, weak = vc.strong_weak(c)
        self.assertTrue(strong[20, 61] and weak[44, 90] and not strong[44, 90])
        dark = vc.contrast_map(255 - img, "dark")
        self.assertTrue(np.array_equal(dark, c))

    def test_features_are_local_tiles(self):
        c = vc.contrast_map(page_with_staff_and_dot())
        feats = vc.strip_features(c)
        self.assertTrue(all(f["bbox"][2] - f["bbox"][0] <= vc.TILE and f["bbox"][3] - f["bbox"][1] <= vc.TILE for f in feats))
        # the attached dot lies in a tile of a few hundred pixels at most, not in a 550-pixel staff component
        dot = [f for f in feats if f["bbox"][0] <= 61 < f["bbox"][2] and f["bbox"][1] <= 20 < f["bbox"][3]]
        self.assertEqual(len(dot), 1)
        self.assertLessEqual(int(dot[0]["mask"].sum()), vc.TILE * 3 + 9)
        self.assertTrue(any(f["kind"] == "weak" and f["bbox"][:2] == [90, 44] for f in feats))
        self.assertEqual(len({f["id"] for f in feats}), len(feats))
        canvas = vc.paint(c.shape, feats)
        self.assertTrue(np.array_equal(canvas, c >= vc.C_WEAK))

    def test_erased_attached_dot_is_a_local_window_failure(self):
        img = page_with_staff_and_dot()
        c = vc.contrast_map(img)
        centres = vc.obligation_centres(vc.strip_features(c), c.shape, c)
        erased = img.copy(); erased[19:22, 60:63] = 255; erased[20, 60:63] = 0
        d = vc.contrast_map(erased)
        miss = vc.window_mean(np.clip(c.astype(int) - d.astype(int), 0, 255))
        fails = (miss > 0) & centres
        groups = vc.group_findings(fails, "C", "fail", "DELIVERED_FEATURE_MISSING")
        self.assertEqual(len(groups), 1)
        x0, y0, x1, y1 = groups[0]["bbox"]
        self.assertTrue(x0 <= 61 < x1 and y0 <= 20 < y1 and x1 - x0 <= 5)

    def test_pack_roundtrip_hashes(self):
        m = np.random.default_rng(0).random((7, 13)) > .5
        self.assertTrue(np.array_equal(vc.unpack_mask(vc.pack_mask(m)), m))
        bad = vc.pack_mask(m); bad["shape"] = [9, 13]
        with self.assertRaises(ValueError):
            vc.unpack_mask(bad)
        a = np.arange(12, dtype=np.uint8).reshape(3, 4)
        self.assertEqual(vc.pixels_sha256(a), rl.pixels_hash(a))
        self.assertEqual(vc.json_sha256({"b": 1, "a": [1, 2]}), vc.json_sha256({"a": [1, 2], "b": 1}))
        with self.assertRaises(ValueError):
            vc.finding("Z", "fail", "X")


if __name__ == "__main__":
    unittest.main()
