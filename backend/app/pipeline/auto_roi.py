"""Conservative paper-edge fitting inside the user's capture boundary."""
from __future__ import annotations

import cv2
import numpy as np


def fit_white_score_region(image, roi):
    original = [[float(x), float(y)] for x, y in roi]
    points = np.asarray(roi, dtype=np.float32)
    if image is None or points.shape != (4, 2) or not np.isfinite(points).all():
        return original, {"status": "uncertain", "trim_top": 0, "trim_bottom": 0}
    # This mode follows rectangular overlay panels, not perspective documents.
    if len(np.unique(points[:, 0])) != 2 or len(np.unique(points[:, 1])) != 2:
        return original, {"status": "uncertain", "trim_top": 0, "trim_bottom": 0}
    height, width = image.shape[:2]
    x1, y1 = np.maximum(np.ceil(points.min(axis=0)).astype(int), 0)
    x2, y2 = np.minimum(np.floor(points.max(axis=0)).astype(int), [width, height])
    if x2 - x1 < 80 or y2 - y1 < 40:
        return original, {"status": "uncertain", "trim_top": 0, "trim_bottom": 0}
    hsv = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    paper = ((hsv[:, :, 1] < 28) & (hsv[:, :, 2] > 225)).mean(axis=1)
    limit = min(64, int(len(paper) * 0.25))

    def edge_trim(colors, white):
        if min(white[:2]) >= 0.85:
            return 0
        for offset in range(1, limit):
            if min(white[offset:offset + 2]) < 0.85 or white[offset:offset + 12].mean() < 0.70:
                continue
            discarded = colors[:offset]
            photo_fraction = ((discarded[:, :, 1] > 35) & (discarded[:, :, 2] > 35)).mean()
            # White margins and black notation are not evidence of video
            # background. Leave them intact, even if a later row is whiter.
            if photo_fraction > 0.08 and white[:offset].mean() < 0.75:
                return offset
            return 0
        return 0

    top = edge_trim(hsv, paper)
    bottom = edge_trim(hsv[::-1], paper[::-1])
    if not top and not bottom:
        return original, {"status": "unchanged" if paper.mean() > 0.6 else "uncertain", "trim_top": 0, "trim_bottom": 0}
    fitted = [[float(x1), float(y1 + top)], [float(x2), float(y1 + top)],
              [float(x2), float(y2 - bottom)], [float(x1), float(y2 - bottom)]]
    return fitted, {"status": "adjusted", "trim_top": top, "trim_bottom": bottom}
