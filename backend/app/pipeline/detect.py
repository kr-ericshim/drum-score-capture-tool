from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from app.pipeline.acceleration import get_runtime_acceleration
from app.pipeline.layout_profiles import (
    LAYOUT_BOTTOM_BAR,
    LAYOUT_PAGE_TURN,
    DetectionProfile,
    get_detection_profile,
    resolve_layout_hint,
)
from app.schemas import DetectOptions


def detect_sheet_regions(
    *,
    frame_paths: List[Path],
    options: DetectOptions,
    workspace: Path,
    source_type: Optional[str] = None,
    logger,
) -> List[Dict[str, Any]]:
    workspace.mkdir(parents=True, exist_ok=True)
    detections: List[Dict[str, Any]] = []
    accel = get_runtime_acceleration(logger=logger)
    opencv_mode = accel.opencv_mode

    layout_mode = resolve_layout_hint(
        options.layout_hint,
        source_type=source_type,
        prefer_bottom=options.prefer_bottom,
    )
    profile = get_detection_profile(layout_mode)
    logger(f"layout mode selected: {layout_mode}")
    if layout_mode == LAYOUT_BOTTOM_BAR:
        logger("youtube bottom-priority detection enabled")

    if options.mode == "manual":
        if options.roi is None:
            raise ValueError("manual mode requires roi")
        roi = np.array(options.roi, dtype=np.float32)
        roi = _order_points(roi)
        logger("using manual ROI for all frames")
        for frame_path in frame_paths:
            detections.append(
                {
                    "frame_path": str(frame_path),
                    "roi": roi.tolist(),
                    "score": 1.0,
                    "frame_index": len(detections),
                }
            )
        return detections

    history = deque(maxlen=3 if layout_mode == LAYOUT_PAGE_TURN else 5)
    for idx, frame_path in enumerate(frame_paths):
        image = cv2.imread(str(frame_path))
        if image is None:
            detections.append({"frame_path": str(frame_path), "roi": None, "score": 0.0, "frame_index": idx})
            continue

        candidates = _find_quadrilateral_candidates(image, layout_mode=layout_mode, opencv_mode=opencv_mode)
        if layout_mode == LAYOUT_BOTTOM_BAR:
            bottom_strip = _detect_bottom_strip_candidate(image)
            if bottom_strip is not None:
                candidates.append(bottom_strip)
        else:
            full_page = _detect_full_page_candidate(image)
            if full_page is not None:
                candidates.append(full_page)

        previous_roi = history[-1] if history else None
        roi, confidence = _pick_best_candidate(
            candidates,
            image,
            profile=profile,
            layout_mode=layout_mode,
            previous_roi=previous_roi,
        )

        if previous_roi is not None and (roi is None or confidence < profile.confidence_threshold):
            roi = previous_roi
            logger("low-confidence detection, reusing previous region")
            confidence = max(confidence, profile.confidence_threshold)
        elif roi is None or confidence < profile.confidence_threshold:
            roi = _default_roi_for_layout(image.shape, profile)
            logger(_fallback_message_for(profile))
            confidence = max(confidence, profile.confidence_threshold)

        if roi is not None:
            if layout_mode == LAYOUT_PAGE_TURN and previous_roi is not None:
                if _temporal_iou_score(roi, previous_roi) < 0.16:
                    history.clear()
                    logger("page transition detected, resetting ROI smoothing")

            history.append(roi)
            roi_out = roi if layout_mode == LAYOUT_PAGE_TURN else _smooth_roi(history)
            detections.append(
                {
                    "frame_path": str(frame_path),
                    "roi": roi_out.tolist(),
                    "score": float(max(0.0, min(1.0, confidence))),
                    "frame_index": idx,
                }
            )
        else:
            detections.append({"frame_path": str(frame_path), "roi": None, "score": 0.0, "frame_index": idx})

        if idx % 20 == 0:
            logger(f"detected frame {idx+1}/{len(frame_paths)}")

    return detections


def _fallback_message_for(profile: DetectionProfile) -> str:
    if profile.fallback_mode == "bottom":
        return "low-confidence detection, using youtube bottom fallback region"
    if profile.fallback_mode == "full_page":
        return "low-confidence detection, using full-page fallback region"
    return "low-confidence detection, using center fallback region"


def _build_detection_edges(image, *, opencv_mode: str):
    if opencv_mode == "cuda":
        edges = _build_detection_edges_cuda(image)
        if edges is not None:
            return edges

    if opencv_mode in {"opencl", "cuda"}:
        edges = _build_detection_edges_opencl(image)
        if edges is not None:
            return edges

    return _build_detection_edges_cpu(image)


def _build_detection_edges_cpu(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 140)
    kernel = np.ones((3, 3), np.uint8)
    return cv2.dilate(edges, kernel, iterations=1)


def _build_detection_edges_opencl(image):
    try:
        umat = cv2.UMat(image)
        gray = cv2.cvtColor(umat, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 40, 140)
        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=1)
        if isinstance(dilated, cv2.UMat):
            return dilated.get()
        return dilated
    except Exception:
        return None


def _build_detection_edges_cuda(image):
    if not hasattr(cv2, "cuda"):
        return None

    try:
        gpu = cv2.cuda_GpuMat()
        gpu.upload(image)
        gray_gpu = cv2.cuda.cvtColor(gpu, cv2.COLOR_BGR2GRAY)
        gauss = cv2.cuda.createGaussianFilter(cv2.CV_8UC1, cv2.CV_8UC1, (5, 5), 0)
        blur_gpu = gauss.apply(gray_gpu)
        canny = cv2.cuda.createCannyEdgeDetector(40, 140)
        edges_gpu = canny.detect(blur_gpu)
        kernel = np.ones((3, 3), np.uint8)
        morph = cv2.cuda.createMorphologyFilter(cv2.MORPH_DILATE, cv2.CV_8UC1, kernel)
        dilated_gpu = morph.apply(edges_gpu)
        return dilated_gpu.download()
    except Exception:
        return None


def _find_quadrilateral_candidates(image, *, layout_mode: str, opencv_mode: str):
    edges = _build_detection_edges(image, opencv_mode=opencv_mode)
    if edges is None:
        return []

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(image.shape[0] * image.shape[1])
    min_rect_ratio = 0.015 if layout_mode == LAYOUT_BOTTOM_BAR else 0.03
    max_rect_ratio = 0.94 if layout_mode == LAYOUT_BOTTOM_BAR else 0.985
    max_aspect = 8.5 if layout_mode == LAYOUT_BOTTOM_BAR else 3.8

    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * min_rect_ratio:
            continue
        if area > image_area * 0.995:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter < 40:
            continue

        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        approx = approx.reshape(-1, 2)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            pts = approx.astype(np.float32)
            x, y, w, h = cv2.boundingRect(pts)
            if w <= 0 or h <= 0:
                continue
            rect_ratio = (w * h) / max(1.0, image_area)
            if rect_ratio < min_rect_ratio or rect_ratio > max_rect_ratio:
                continue
            candidates.append(_order_points(pts))
            continue

        rect = cv2.minAreaRect(contour)
        width, height = rect[1]
        if width <= 0 or height <= 0:
            continue
        area_ratio = area / max(1.0, (width * height))
        aspect = max(width, height) / max(1.0, min(width, height))
        if 0.35 < area_ratio < 1.2 and 0.45 < aspect < max_aspect:
            candidates.append(_order_points(cv2.boxPoints(rect).astype(np.float32)))

    return candidates


def _pick_best_candidate(candidates, image, *, profile: DetectionProfile, layout_mode: str, previous_roi):
    if not candidates:
        return None, 0.0

    image_shape = image.shape
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    best = None
    best_score = -1.0

    for candidate in candidates:
        area_score = _area_score(candidate, image_shape, profile)
        aspect_score = _aspect_score(candidate, profile, layout_mode=layout_mode)
        horizontal_score = _horizontal_line_score(gray, candidate)
        brightness_score = _brightness_score(gray, candidate)
        temporal_score = _temporal_iou_score(candidate, previous_roi)
        center_score = _center_y_score(candidate, image_shape, profile)
        boundary_penalty = _boundary_penalty(candidate, image_shape, layout_mode=layout_mode)
        bottom_strip_score = _bottom_strip_score(gray, candidate, image_shape) if layout_mode == LAYOUT_BOTTOM_BAR else 0.0
        full_page_score = _full_page_score(gray, candidate, image_shape) if layout_mode != LAYOUT_BOTTOM_BAR else 0.0

        score = _combine_scores(
            layout_mode=layout_mode,
            area_score=area_score,
            aspect_score=aspect_score,
            horizontal_score=horizontal_score,
            brightness_score=brightness_score,
            temporal_score=temporal_score,
            center_score=center_score,
            boundary_penalty=boundary_penalty,
            bottom_strip_score=bottom_strip_score,
            full_page_score=full_page_score,
            bottom_bias=_bottom_bias_score(candidate, image_shape, profile),
        )
        if score > best_score:
            best_score = score
            best = candidate
    return best, float(max(0.0, min(1.0, best_score)))


def _combine_scores(
    *,
    layout_mode: str,
    area_score: float,
    aspect_score: float,
    horizontal_score: float,
    brightness_score: float,
    temporal_score: float,
    center_score: float,
    boundary_penalty: float,
    bottom_strip_score: float,
    full_page_score: float,
    bottom_bias: float,
) -> float:
    if layout_mode == LAYOUT_BOTTOM_BAR:
        return (
            area_score * 0.2
            + aspect_score * 0.14
            + horizontal_score * 0.22
            + brightness_score * 0.1
            + temporal_score * 0.16
            + center_score * 0.06
            + bottom_strip_score * 0.38
            + bottom_bias
            - boundary_penalty * 0.3
        )

    if layout_mode == LAYOUT_PAGE_TURN:
        return (
            area_score * 0.24
            + aspect_score * 0.18
            + horizontal_score * 0.16
            + brightness_score * 0.14
            + temporal_score * 0.3
            + center_score * 0.1
            + full_page_score * 0.22
            - boundary_penalty * 0.22
        )

    return (
        area_score * 0.24
        + aspect_score * 0.16
        + horizontal_score * 0.2
        + brightness_score * 0.14
        + temporal_score * 0.2
        + center_score * 0.12
        + full_page_score * 0.2
        - boundary_penalty * 0.24
    )


def _smooth_roi(history):
    arr = np.array(history, dtype=np.float32)
    return np.median(arr, axis=0)


def _roi_area(roi, image_shape):
    if roi is None:
        return 0.0
    x, y, w, h = cv2.boundingRect(roi.astype(np.int32))
    bounds = image_shape[0] * image_shape[1]
    return max(0.0, min(1.0, (w * h) / max(1.0, bounds)))


def _roi_aspect_ratio(roi):
    widths = np.linalg.norm(roi[0] - roi[1]) + np.linalg.norm(roi[2] - roi[3])
    heights = np.linalg.norm(roi[0] - roi[3]) + np.linalg.norm(roi[1] - roi[2])
    if heights <= 0:
        return 0.0
    return (widths / 2.0) / (heights / 2.0)


def _center_y_score(roi, image_shape, profile: DetectionProfile):
    h = float(max(1, image_shape[0]))
    center_y = float(np.mean(roi[:, 1])) / h
    return _score_around_target(center_y, profile.center_y_target, profile.center_y_tolerance)


def _bottom_bias_score(roi, image_shape, profile: DetectionProfile):
    if not profile.prefer_bottom:
        return 0.0
    h = float(max(1, image_shape[0]))
    center_y = float(np.mean(roi[:, 1])) / h
    return _score_around_target(center_y, profile.center_y_target, profile.center_y_tolerance) * 0.42


def _default_roi_for_layout(image_shape, profile: DetectionProfile):
    if profile.fallback_mode == "bottom":
        return _default_bottom_roi(image_shape)
    if profile.fallback_mode == "full_page":
        return _default_full_page_roi(image_shape)
    return _default_center_roi(image_shape)


def _default_bottom_roi(image_shape):
    h, w = image_shape[:2]
    x1 = int(w * 0.04)
    x2 = int(w * 0.96)
    y1 = int(h * 0.56)
    y2 = int(h * 0.96)
    roi = np.array(
        [
            [x1, y1],
            [x2, y1],
            [x2, y2],
            [x1, y2],
        ],
        dtype=np.float32,
    )
    return _order_points(roi)


def _default_full_page_roi(image_shape):
    h, w = image_shape[:2]
    x1 = int(w * 0.03)
    x2 = int(w * 0.97)
    y1 = int(h * 0.06)
    y2 = int(h * 0.95)
    roi = np.array(
        [
            [x1, y1],
            [x2, y1],
            [x2, y2],
            [x1, y2],
        ],
        dtype=np.float32,
    )
    return _order_points(roi)


def _default_center_roi(image_shape):
    h, w = image_shape[:2]
    x1 = int(w * 0.08)
    x2 = int(w * 0.92)
    y1 = int(h * 0.2)
    y2 = int(h * 0.9)
    roi = np.array(
        [
            [x1, y1],
            [x2, y1],
            [x2, y2],
            [x1, y2],
        ],
        dtype=np.float32,
    )
    return _order_points(roi)


def _score_around_target(value, target, tolerance):
    return max(0.0, 1.0 - abs(value - target) / max(1e-6, tolerance))


def _area_score(roi, image_shape, profile: DetectionProfile):
    area_norm = _roi_area(roi, image_shape)
    return _score_around_target(area_norm, profile.area_target, profile.area_tolerance)


def _aspect_score(roi, profile: DetectionProfile, *, layout_mode: str):
    ratio = _roi_aspect_ratio(roi)
    page_like = _score_around_target(ratio, profile.page_aspect_target, profile.page_aspect_tolerance)
    if layout_mode != LAYOUT_BOTTOM_BAR:
        return page_like

    strip_like = _score_around_target(ratio, profile.strip_aspect_target, profile.strip_aspect_tolerance)
    return max(page_like, strip_like)


def _horizontal_line_score(gray, roi):
    x, y, w, h = cv2.boundingRect(roi.astype(np.int32))
    if w < 80 or h < 60:
        return 0.0
    crop = gray[y : y + h, x : x + w]
    if crop.size == 0:
        return 0.0

    blur = cv2.GaussianBlur(crop, (3, 3), 0)
    bin_inv = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    kernel_len = max(20, w // 12)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    horiz = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, h_kernel)
    density = float(cv2.countNonZero(horiz)) / float(max(1, w * h))
    return max(0.0, min(1.0, density * 20.0))


def _brightness_score(gray, roi):
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillPoly(mask, [roi.astype(np.int32)], 255)
    mean_val = cv2.mean(gray, mask=mask)[0] / 255.0
    return _score_around_target(mean_val, 0.78, 0.45)


def _full_page_score(gray, roi, image_shape):
    ratio = _roi_aspect_ratio(roi)
    h = float(max(1, image_shape[0]))
    center_y = float(np.mean(roi[:, 1])) / h
    area_score = _score_around_target(_roi_area(roi, image_shape), 0.66, 0.42)
    ratio_score = _score_around_target(ratio, 1.6, 1.25)
    center_score = _score_around_target(center_y, 0.52, 0.5)
    white_score = _brightness_score(gray, roi)
    line_score = _horizontal_line_score(gray, roi)
    return max(
        0.0,
        min(
            1.0,
            (area_score * 0.34) + (ratio_score * 0.22) + (center_score * 0.16) + (white_score * 0.14) + (line_score * 0.14),
        ),
    )


def _bottom_strip_score(gray, roi, image_shape):
    ratio = _roi_aspect_ratio(roi)
    if ratio < 2.0:
        return 0.0

    h = float(max(1, image_shape[0]))
    center_y = float(np.mean(roi[:, 1])) / h
    if center_y < 0.55:
        return 0.0

    white_score = _brightness_score(gray, roi)
    line_score = _horizontal_line_score(gray, roi)
    location = _score_around_target(center_y, 0.82, 0.35)
    ratio_score = _score_around_target(ratio, 4.5, 3.5)
    return max(0.0, min(1.0, (white_score * 0.28) + (line_score * 0.42) + (location * 0.2) + (ratio_score * 0.2)))


def _temporal_iou_score(roi, previous_roi):
    if previous_roi is None:
        return 0.0
    ax, ay, aw, ah = cv2.boundingRect(roi.astype(np.int32))
    bx, by, bw, bh = cv2.boundingRect(previous_roi.astype(np.int32))

    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    inter_w = max(0, min(ax2, bx2) - max(ax, bx))
    inter_h = max(0, min(ay2, by2) - max(ay, by))
    inter = inter_w * inter_h
    union = (aw * ah) + (bw * bh) - inter
    if union <= 0:
        return 0.0
    return max(0.0, min(1.0, inter / union))


def _boundary_penalty(roi, image_shape, *, layout_mode: str):
    h, w = image_shape[:2]
    x, y, rw, rh = cv2.boundingRect(roi.astype(np.int32))
    margin_x = int(w * 0.02)
    margin_y = int(h * 0.02)

    touches = 0.0
    if layout_mode == LAYOUT_BOTTOM_BAR:
        if x <= margin_x:
            touches += 0.8
        if y <= margin_y:
            touches += 1.0
        if x + rw >= w - margin_x:
            touches += 0.8
        if y + rh >= h - margin_y:
            touches += 0.15
        penalty = touches * 0.22
    else:
        if x <= margin_x:
            touches += 0.18
        if y <= margin_y:
            touches += 0.12
        if x + rw >= w - margin_x:
            touches += 0.18
        if y + rh >= h - margin_y:
            touches += 0.12
        penalty = touches * 0.1

    area_norm = _roi_area(roi, image_shape)
    if area_norm > 0.985:
        penalty += 0.2
    if area_norm < 0.02:
        penalty += 0.2
    return max(0.0, min(1.0, penalty))


def _detect_bottom_strip_candidate(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    y_start = int(h * 0.45)
    row_mean = gray[y_start:, :].mean(axis=1) / 255.0
    if row_mean.size < 20:
        return None

    smoothed = cv2.GaussianBlur(row_mean.astype(np.float32).reshape(-1, 1), (1, 15), 0).reshape(-1)
    bright_mask = smoothed > 0.54

    best_seg = None
    seg_start = None
    for idx, is_bright in enumerate(bright_mask):
        if is_bright and seg_start is None:
            seg_start = idx
        elif not is_bright and seg_start is not None:
            seg = (seg_start, idx - 1)
            if best_seg is None or (seg[1] - seg[0]) > (best_seg[1] - best_seg[0]):
                best_seg = seg
            seg_start = None
    if seg_start is not None:
        seg = (seg_start, len(bright_mask) - 1)
        if best_seg is None or (seg[1] - seg[0]) > (best_seg[1] - best_seg[0]):
            best_seg = seg

    if best_seg is None:
        return None

    y1 = y_start + best_seg[0]
    y2 = y_start + best_seg[1]
    strip_h = y2 - y1 + 1
    if strip_h < int(h * 0.1):
        return None
    if y2 < int(h * 0.62):
        return None

    x_margin = int(w * 0.01)
    roi = np.array(
        [
            [x_margin, y1],
            [w - x_margin, y1],
            [w - x_margin, min(h - 1, y2)],
            [x_margin, min(h - 1, y2)],
        ],
        dtype=np.float32,
    )
    return _order_points(roi)


def _detect_full_page_candidate(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    image_area = float(h * w)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(thresh) < 110:
        _, thresh = cv2.threshold(blur, 180, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best = None
    best_score = -1.0
    for contour in contours:
        area = cv2.contourArea(contour)
        area_ratio = area / max(1.0, image_area)
        if area_ratio < 0.28 or area_ratio > 0.99:
            continue

        rect = cv2.minAreaRect(contour)
        width, height = rect[1]
        if width <= 0 or height <= 0:
            continue

        aspect = max(width, height) / max(1.0, min(width, height))
        if aspect < 0.7 or aspect > 2.8:
            continue

        box = _order_points(cv2.boxPoints(rect).astype(np.float32))
        center_y = float(np.mean(box[:, 1])) / max(1.0, float(h))
        score = (
            _score_around_target(area_ratio, 0.68, 0.35) * 0.56
            + _score_around_target(center_y, 0.52, 0.45) * 0.24
            + _score_around_target(aspect, 1.6, 1.2) * 0.2
        )
        if score > best_score:
            best_score = score
            best = box
    return best


def _order_points(pts: np.ndarray) -> np.ndarray:
    pts = np.array(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(diff)]
    ordered[3] = pts[np.argmax(diff)]
    return ordered
