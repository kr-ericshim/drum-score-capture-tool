import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import system_tracking as stk


class ManifestImageLoaderTest(unittest.TestCase):
    def test_repeated_passes_within_budget_decode_each_frame_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = []
            for i in range(80):
                cv2.imwrite(str(Path(tmp) / f"f{i}.png"), np.full((20, 30, 3), i, np.uint8))
                obs.append({"id": f"o{i}", "frame_path": f"f{i}.png"})
            reads = []
            original = cv2.imread
            def counting(path, *args):
                reads.append(path)
                return original(path, *args)
            cv2.imread = counting
            try:
                load = stk.manifest_image_loader(Path(tmp), {})
                for _ in range(3):
                    for o in obs:
                        self.assertEqual(int(load(o)[0, 0, 0]), int(o["id"][1:]))
            finally:
                cv2.imread = original
            self.assertEqual(len(reads), 80)  # the old 64-entry FIFO re-read every pass

    def test_budget_evicts_least_recently_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                cv2.imwrite(str(Path(tmp) / f"f{i}.png"), np.full((10, 10, 3), i, np.uint8))
            obs = [{"id": f"o{i}", "frame_path": f"f{i}.png"} for i in range(3)]
            load = stk.manifest_image_loader(Path(tmp), {}, max_bytes=2 * 300)
            a = load(obs[0]); load(obs[1]); load(obs[0]); load(obs[2])
            self.assertIs(load(obs[0]), a)  # recently used, kept
            self.assertEqual(int(load(obs[1])[0, 0, 0]), 1)  # evicted, decoded again


if __name__ == "__main__":
    unittest.main()
