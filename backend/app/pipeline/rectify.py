from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import cv2

from app.pipeline.process_control import checkpoint
import numpy as np

from app.schemas import RectifyOptions


def rectify_frames(
    *,
    detections: List[Dict[str, Any]],
    options: RectifyOptions,
    workspace: Path,
    logger,
) -> List[Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    out_paths: List[Path] = []

    if options.manual_points is not None:
        forced = np.array(options.manual_points, dtype=np.float32)
        for idx, item in enumerate(detections):
            checkpoint()
            if not item.get("roi"):
                item["roi"] = forced.tolist()
                item.pop("safe_roi", None)

    logger(f"rectify mode auto={options.auto}")
    for idx, item in enumerate(detections):
        checkpoint()
        frame_path = Path(item["frame_path"])
        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        roi = item.get("roi")
        if roi is None:
            raise ValueError("a capture region is required; refusing to export the full video frame")

        # The visible selection is the capture boundary. Historical safe_roi
        # padding must never override the user's region.
        points = np.array(roi, dtype=np.float32).reshape(4, 2)
        if not np.isfinite(points).all():
            raise ValueError("capture region must contain finite coordinates")
        points = _order_points(points)
        warped = _warp_sheet(image, points)
        if options.auto:
            warped = _enhance_sheet(warped)

        out_path = workspace / f"sheet_{idx:05d}.png"
        cv2.imwrite(str(out_path), warped)
        out_paths.append(out_path)

    if not out_paths:
        raise RuntimeError("rectification produced no output frames")
    logger(f"rectified {len(out_paths)} frames")
    return out_paths


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


def _enhance_sheet(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    merged = cv2.merge((cl, a, b))
    out = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    blur = cv2.GaussianBlur(out, (0, 0), 1.2)
    out = cv2.addWeighted(out, 1.6, blur, -0.6, 0)
    return out
