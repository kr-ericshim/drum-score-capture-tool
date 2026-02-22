from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import cv2
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
            if not item.get("roi"):
                item["roi"] = forced.tolist()

    logger(f"rectify mode auto={options.auto}")
    for idx, item in enumerate(detections):
        frame_path = Path(item["frame_path"])
        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        roi = item.get("roi")
        if roi is None:
            out_paths.append(frame_path)
            continue

        points = np.array(roi, dtype=np.float32).reshape(4, 2)
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
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_w = max(int(width_a), int(width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_h = max(int(height_a), int(height_b))

    if max_w <= 1 or max_h <= 1:
        return image

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
    warped = cv2.warpPerspective(image, matrix, (max_w, max_h))
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
