from __future__ import annotations

import cv2
import numpy as np


def _order_points(points):
    points = np.array(points, dtype=np.float32)
    s = points.sum(axis=1)
    d = np.diff(points, axis=1)
    out = np.zeros((4, 2), dtype=np.float32)
    out[0] = points[np.argmin(s)]  # left-top
    out[2] = points[np.argmax(s)]  # right-bottom
    out[1] = points[np.argmin(d)]  # right-top
    out[3] = points[np.argmax(d)]  # left-bottom
    return out


def _warp_sheet(image, points):
    (tl, tr, br, bl) = points
    if np.allclose([tl[1], tr[0], br[1], bl[0]], [tr[1], br[0], bl[1], tl[0]]):
        # Rectangle bounds are half-open, exactly like the renderer selection.
        # A direct slice avoids resampling pixels from outside the boundary.
        h, w = image.shape[:2]
        x1, y1 = np.ceil(tl).astype(int)
        x2, y2 = np.floor(br).astype(int)
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            raise ValueError("capture region is empty or too small")
        return image[y1:y2, x1:x2].copy()
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_w = max(int(width_a), int(width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_h = max(int(height_a), int(height_b))

    if max_w <= 1 or max_h <= 1:
        raise ValueError("capture region is empty or too small")

    destination = np.array(
        [
            [0, 0],
            [max_w - 1, 0],
            [max_w - 1, max_h - 1],
            [0, max_h - 1],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(points, destination)
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, points.astype(np.int32), 255)
    bounded = image.copy()
    bounded[mask == 0] = 255
    warped = cv2.warpPerspective(bounded, matrix, (max_w, max_h), borderValue=(255, 255, 255))
    return warped

