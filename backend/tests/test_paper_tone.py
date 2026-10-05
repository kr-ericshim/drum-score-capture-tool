"""Paper background flattening keeps the ink and evens out the video's gray tone."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.paper_tone import flatten_capture_backgrounds, flatten_paper_background
from drum_score_fixture import groove_notes, render, strip_spec


def _video_tone(image: np.ndarray, left: float = 0.93, right: float = 0.96) -> np.ndarray:
    """Dim the page with a horizontal gradient like a captured video strip."""
    gain = np.linspace(left, right, image.shape[1], dtype=np.float32)[None, :, None]
    return np.clip(image.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def _ink(gray: np.ndarray) -> np.ndarray:
    return gray < 128


class TestPaperTone(unittest.TestCase):
    def setUp(self):
        self.clean = render(groove_notes(strip_spec(), seed=5))

    def test_gradient_paper_becomes_uniform_and_ink_is_kept(self):
        captured = _video_tone(self.clean)
        flattened = flatten_paper_background(captured)
        self.assertIsNotNone(flattened)
        gray = cv2.cvtColor(flattened, cv2.COLOR_BGR2GRAY)
        paper = ~cv2.dilate(_ink(gray).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        left, right = gray[:, :200][paper[:, :200]], gray[:, -200:][paper[:, -200:]]
        self.assertLessEqual(abs(float(np.median(left)) - float(np.median(right))), 1.0)
        self.assertGreaterEqual(float(np.median(gray[paper])), 245)
        clean_ink = _ink(cv2.cvtColor(self.clean, cv2.COLOR_BGR2GRAY))
        # Only anti-aliased edge pixels may cross the threshold after rounding.
        self.assertLessEqual(int((_ink(gray) != clean_ink).sum()), max(1, int(clean_ink.sum() * 0.001)))

    def test_gray_ink_keeps_its_ratio_to_the_paper(self):
        page = np.full((190, 1400, 3), 240, np.uint8)
        cv2.circle(page, (700, 95), 9, (160, 160, 160), -1)
        flattened = flatten_paper_background(page)
        self.assertIsNotNone(flattened)
        self.assertAlmostEqual(float(flattened[95, 700, 0]), 160 / 240 * 250, delta=3)

    def test_large_dark_block_is_not_lifted_to_paper(self):
        page = _video_tone(self.clean)
        page[40:150, 500:900] = 30
        flattened = flatten_paper_background(page)
        self.assertIsNotNone(flattened)
        self.assertLess(float(flattened[95, 700].mean()), 60)

    def test_edge_border_rule_is_cleared(self):
        page = _video_tone(self.clean)
        page[0] = 180
        flattened = flatten_paper_background(page)
        self.assertGreaterEqual(int(flattened[0].min()), 245)

    def test_staff_line_touching_the_roi_edge_is_not_a_border(self):
        spec = strip_spec(margin_x=10)
        page = _video_tone(render(groove_notes(spec, seed=5)))
        gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
        dark_rows = np.flatnonzero((gray < 128).mean(axis=1) >= 0.9)
        top_line, bottom_line = int(dark_rows[0]), int(dark_rows[-1])
        for cropped, edge in ((page[top_line:], 0), (page[: bottom_line + 1], -1)):
            with self.subTest(edge=edge):
                flattened = flatten_paper_background(cropped)
                self.assertIsNotNone(flattened)
                edge_gray = cv2.cvtColor(flattened, cv2.COLOR_BGR2GRAY)[edge]
                self.assertGreaterEqual(float((edge_gray < 128).mean()), 0.9)

    def test_dark_video_frame_and_settled_white_page_are_left_alone(self):
        self.assertIsNone(flatten_paper_background(np.full((190, 1400, 3), 60, np.uint8)))
        self.assertIsNone(flatten_paper_background(self.clean))

    def test_sources_are_preserved_and_own_composites_rewritten_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "rectified" / "sheet_0000.png"
            source.parent.mkdir()
            cv2.imwrite(str(source), _video_tone(self.clean))
            workspace = root / "clean"
            workspace.mkdir()
            composite = workspace / "sheet_0001_clean.png"
            cv2.imwrite(str(composite), _video_tone(self.clean))
            settled = root / "rectified" / "sheet_0002.png"
            cv2.imwrite(str(settled), self.clean)
            source_bytes = source.read_bytes()

            logs = []
            out = flatten_capture_backgrounds(paths=[source, composite, settled], workspace=workspace, logger=logs.append)

            self.assertEqual(out, [workspace / "sheet_0000_clean.png", composite, settled])
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertGreaterEqual(int(np.median(cv2.imread(str(composite)))), 245)
            self.assertEqual(logs, ["paper tone: 2 flattened, 1 kept as captured"])


if __name__ == "__main__":
    unittest.main()
