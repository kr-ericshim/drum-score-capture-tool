from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app.schemas import DetectOptions


def detect_sheet_regions(
    *,
    frame_paths: List[Path],
    options: DetectOptions,
    workspace: Path,
    source_type: Optional[str] = None,
    logger,
) -> List[Dict[str, Any]]:
    del source_type  # reserved for compatibility with existing call sites
    workspace.mkdir(parents=True, exist_ok=True)
    if not frame_paths:
        return []

    roi = _parse_roi(options.roi)
    logger("using manual ROI for all frames")

    detections: List[Dict[str, Any]] = []
    for idx, frame_path in enumerate(frame_paths):
        detections.append(
            {
                "frame_path": str(frame_path),
                "roi": roi.tolist(),
                "score": 1.0,
                "frame_index": idx,
            }
        )
    return detections


def _parse_roi(raw_roi: List[List[float]]) -> np.ndarray:
    roi = np.array(raw_roi, dtype=np.float32).reshape(4, 2)
    roi = _order_points(roi)
    widths = np.linalg.norm(roi[0] - roi[1]) + np.linalg.norm(roi[2] - roi[3])
    heights = np.linalg.norm(roi[0] - roi[3]) + np.linalg.norm(roi[1] - roi[2])
    if widths <= 2 or heights <= 2:
        raise ValueError("roi is too small. drag a larger sheet region.")
    return roi


def _order_points(points: np.ndarray) -> np.ndarray:
    s = points.sum(axis=1)
    d = np.diff(points, axis=1)
    out = np.zeros((4, 2), dtype=np.float32)
    out[0] = points[np.argmin(s)]  # left-top
    out[2] = points[np.argmax(s)]  # right-bottom
    out[1] = points[np.argmin(d)]  # right-top
    out[3] = points[np.argmax(d)]  # left-bottom
    return out
