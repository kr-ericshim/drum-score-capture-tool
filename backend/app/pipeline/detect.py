from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2

from app.pipeline.process_control import checkpoint
import numpy as np

from app.schemas import DetectOptions
from app.pipeline.auto_roi import fit_white_score_region


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
    logger("fitting white score edges inside the selected region" if options.auto_fit else "using manual ROI for all frames")

    detections: List[Dict[str, Any]] = []
    for idx, frame_path in enumerate(frame_paths):
        checkpoint()
        selected_roi = roi.tolist()
        fit = {"status": "disabled"}
        if options.auto_fit:
            selected_roi, fit = fit_white_score_region(cv2.imread(str(frame_path)), selected_roi)
        detections.append(
            {
                "frame_path": str(frame_path),
                "roi": selected_roi,
                "requested_roi": roi.tolist(),
                "safe_roi": selected_roi,
                "auto_fit": fit,
                "score": 1.0,
                "frame_index": idx,
            }
        )
    if options.auto_fit:
        adjusted = sum(item["auto_fit"]["status"] == "adjusted" for item in detections)
        logger(f"white score fit: {adjusted}/{len(detections)} frames adjusted; other frames keep the selected boundary")
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
