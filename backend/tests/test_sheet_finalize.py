import unittest

import cv2
import numpy as np

from app.pipeline.sheet_finalize import (
    _frame_pages_as_printed_set,
    _resolve_overlapping_ranges,
    _slice_by_whitespace,
    _split_long_page,
)


class TestSheetFinalizePagination(unittest.TestCase):
    def test_frame_pages_as_printed_set_normalizes_page_size(self):
        page_a = np.full((1500, 1800, 3), 255, dtype=np.uint8)
        page_b = np.full((2100, 1800, 3), 255, dtype=np.uint8)

        framed = _frame_pages_as_printed_set([page_a, page_b], page_ratio=1.0 / 1.4142)

        self.assertEqual(len(framed), 2)
        self.assertEqual(framed[0].shape, framed[1].shape)
        self.assertGreaterEqual(int(framed[0].shape[0]), int(framed[0].shape[1]))

    def test_resolve_overlapping_ranges_removes_overlap(self):
        row_density = np.full(7444, 0.02, dtype=np.float32)
        # Simulate whitespace valleys inside overlapping windows.
        row_density[2190:2230] = 0.0009
        row_density[4375:4405] = 0.0009
        row_density[6640:6670] = 0.0009

        ranges = [(0, 2259), (2172, 4440), (4347, 6726), (6628, 7444)]
        resolved = _resolve_overlapping_ranges(ranges, row_density=row_density)

        self.assertEqual(len(resolved), 4)
        self.assertEqual(resolved[0][0], 0)
        self.assertEqual(resolved[-1][1], 7444)
        for idx in range(len(resolved) - 1):
            self.assertLessEqual(resolved[idx][1], resolved[idx + 1][0])

    def test_slice_by_whitespace_has_no_duplicate_rows_between_pages(self):
        h, w = 6200, 1800
        image = np.full((h, w, 3), 255, dtype=np.uint8)
        row_density = np.full(h, 0.02, dtype=np.float32)

        # Encourage split points near these rows.
        for cut in (2050, 4100):
            row_density[cut - 12 : cut + 12] = 0.0008

        pages = _slice_by_whitespace(image, row_density=row_density, target_h=2000)

        self.assertGreaterEqual(len(pages), 3)
        self.assertEqual(sum(int(page.shape[0]) for page in pages), h)

    def test_performance_mode_prefers_fuller_pages(self):
        h, w = 6000, 1800
        image = np.full((h, w, 3), 255, dtype=np.uint8)
        row_density = np.full(h, 0.02, dtype=np.float32)

        # Early whitespace valleys that balanced mode can over-prefer.
        row_density[1490:1510] = 0.0010
        row_density[3490:3510] = 0.0010
        # Near-target valleys that should be preferred in performance mode.
        row_density[1940:1960] = 0.0022
        row_density[3940:3960] = 0.0022

        pages_balanced = _slice_by_whitespace(
            image,
            row_density=row_density,
            target_h=2000,
            page_fill_mode="balanced",
        )
        pages_performance = _slice_by_whitespace(
            image,
            row_density=row_density,
            target_h=2000,
            page_fill_mode="performance",
        )

        self.assertGreaterEqual(len(pages_balanced), 2)
        self.assertGreaterEqual(len(pages_performance), 2)
        self.assertGreaterEqual(int(pages_performance[0].shape[0]), int(2000 * 0.90))
        self.assertGreater(int(pages_performance[0].shape[0]), int(pages_balanced[0].shape[0]))

    def test_split_long_page_preserves_sparse_rows_between_systems(self):
        h, w = 6200, 1800
        image = np.full((h, w, 3), 255, dtype=np.uint8)

        starts = [280, 950, 1620, 2290, 2960, 3630, 4300, 4970]
        for start in starts:
            for offset in [0, 10, 20, 30, 40]:
                y = start + offset
                cv2.line(image, (80, y), (1720, y), (0, 0, 0), 2)
            cv2.circle(image, (250, start + 15), 8, (0, 0, 0), -1)
            cv2.circle(image, (900, start + 27), 8, (0, 0, 0), -1)
            cv2.circle(image, (1500, start + 37), 8, (0, 0, 0), -1)

        # Sparse notation between systems should not be mistaken for empty whitespace.
        for y in [905, 1575, 2245, 2915, 3585, 4255, 4925]:
            cv2.line(image, (200, y), (1600, y), (0, 0, 0), 1)
            cv2.circle(image, (600, y - 8), 6, (0, 0, 0), -1)

        pages = _split_long_page(image, page_ratio=1.0 / 1.4142, page_fill_mode="performance")

        self.assertGreaterEqual(len(pages), 2)
        self.assertEqual(sum(int(page.shape[0]) for page in pages), h)

    def test_slice_by_whitespace_avoids_cutting_through_dense_boundary(self):
        h, w = 4300, 1800
        image = np.full((h, w, 3), 255, dtype=np.uint8)
        row_density = np.full(h, 0.018, dtype=np.float32)

        # A deceptive single-row valley near the target height should not be chosen
        # if the surrounding boundary is still dense like a real staff/lyric band.
        row_density[1936:1964] = 0.028
        row_density[1948:1952] = 0.0010
        row_density[2050:2080] = 0.0010

        pages = _slice_by_whitespace(
            image,
            row_density=row_density,
            target_h=2000,
            page_fill_mode="performance",
        )

        self.assertGreaterEqual(len(pages), 2)
        self.assertGreaterEqual(int(pages[0].shape[0]), 2045)


if __name__ == "__main__":
    unittest.main()
