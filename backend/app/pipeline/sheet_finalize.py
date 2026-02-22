from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np


LANDSCAPE_PAGE_RATIO = 1.58  # width / height


def finalize_sheet_pages(image, *, page_ratio: float = LANDSCAPE_PAGE_RATIO) -> List[np.ndarray]:
    if image is None or image.size == 0:
        return []

    prepared = _normalize_score_tone(image)
    cropped = _crop_to_content(prepared)
    pages = _split_long_page(cropped, page_ratio=page_ratio)
    if not pages:
        pages = [cropped]
    return [_frame_as_printed_page(page, page_ratio=page_ratio) for page in pages]


def _normalize_score_tone(image) -> np.ndarray:
    if image.ndim == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    gray = cv2.medianBlur(gray, 3)
    low = float(np.percentile(gray, 1.0))
    high = float(np.percentile(gray, 99.0))
    if high - low > 1.0:
        scaled = np.clip((gray.astype(np.float32) - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
    else:
        scaled = gray.copy()

    lifted = cv2.convertScaleAbs(scaled, alpha=1.06, beta=6)
    return cv2.cvtColor(lifted, cv2.COLOR_GRAY2BGR)


def _crop_to_content(image) -> np.ndarray:
    h, w = image.shape[:2]
    if h <= 8 or w <= 8:
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inv = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    inv = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel)

    row_density = (inv > 0).sum(axis=1).astype(np.float32) / float(max(1, w))
    col_density = (inv > 0).sum(axis=0).astype(np.float32) / float(max(1, h))
    active_rows = np.where(row_density > 0.003)[0]
    active_cols = np.where(col_density > 0.003)[0]
    if active_rows.size == 0 or active_cols.size == 0:
        return image

    pad = max(8, int(min(h, w) * 0.012))
    y0 = max(0, int(active_rows[0]) - pad)
    y1 = min(h, int(active_rows[-1]) + pad + 1)
    x0 = max(0, int(active_cols[0]) - pad)
    x1 = min(w, int(active_cols[-1]) + pad + 1)
    if y1 <= y0 or x1 <= x0:
        return image
    return image[y0:y1, x0:x1].copy()


def _split_long_page(image, *, page_ratio: float) -> List[np.ndarray]:
    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        return []

    target_h = max(260, int(round(w / max(0.4, page_ratio))))
    if h <= int(target_h * 1.22):
        return [image]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inv = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    row_density = (inv > 0).sum(axis=1).astype(np.float32) / float(max(1, w))
    threshold = float(np.clip(np.percentile(row_density, 72) * 0.34, 0.004, 0.03))
    active = row_density > threshold
    bands = _extract_active_bands(active, min_len=max(6, int(h * 0.004)))

    if not bands:
        return _slice_by_whitespace(image, row_density=row_density, target_h=target_h)

    gap_pad = max(8, int(h * 0.012))
    expanded = [(max(0, s - gap_pad), min(h, e + gap_pad)) for s, e in bands]

    pages: List[Tuple[int, int]] = []
    cur_s, cur_e = expanded[0]
    for s, e in expanded[1:]:
        if e - cur_s <= int(target_h * 1.12):
            cur_e = e
            continue
        pages.append((cur_s, cur_e))
        cur_s, cur_e = s, e
    pages.append((cur_s, cur_e))

    normalized_pages: List[np.ndarray] = []
    for s, e in pages:
        if e - s > int(target_h * 1.45):
            oversized = image[s:e]
            sub_density = row_density[s:e]
            normalized_pages.extend(_slice_by_whitespace(oversized, row_density=sub_density, target_h=target_h))
            continue
        normalized_pages.append(image[s:e].copy())

    return normalized_pages or _slice_by_whitespace(image, row_density=row_density, target_h=target_h)


def _extract_active_bands(active_mask: np.ndarray, *, min_len: int) -> List[Tuple[int, int]]:
    bands: List[Tuple[int, int]] = []
    start = -1
    for idx, value in enumerate(active_mask.tolist()):
        if value and start < 0:
            start = idx
        elif not value and start >= 0:
            if idx - start >= min_len:
                bands.append((start, idx))
            start = -1
    if start >= 0 and len(active_mask) - start >= min_len:
        bands.append((start, len(active_mask)))
    return bands


def _slice_by_whitespace(image, *, row_density: np.ndarray, target_h: int) -> List[np.ndarray]:
    h = image.shape[0]
    pages: List[np.ndarray] = []
    start = 0
    min_h = max(180, int(target_h * 0.58))

    while start < h:
        hard_end = min(h, start + target_h)
        if hard_end >= h:
            pages.append(image[start:h].copy())
            break

        window = int(target_h * 0.22)
        lo = max(start + min_h, hard_end - window)
        hi = min(h - 1, hard_end + window)
        if hi <= lo:
            cut = hard_end
        else:
            local = row_density[lo : hi + 1]
            cut = int(lo + int(np.argmin(local)))
            if cut - start < min_h:
                cut = hard_end

        pages.append(image[start:cut].copy())
        start = max(cut, start + min_h)

    return pages


def _frame_as_printed_page(image, *, page_ratio: float) -> np.ndarray:
    trimmed = _crop_to_content(image)
    h, w = trimmed.shape[:2]
    if h <= 0 or w <= 0:
        return image

    margin_x = max(26, int(w * 0.035))
    margin_y = max(28, int(h * 0.06))

    base_w = w + (margin_x * 2)
    base_h = h + (margin_y * 2)
    target_ratio = max(0.6, float(page_ratio))
    cur_ratio = float(base_w) / float(max(1, base_h))

    extra_left = 0
    extra_top = 0
    canvas_w = base_w
    canvas_h = base_h
    if cur_ratio > target_ratio:
        desired_h = int(round(base_w / target_ratio))
        extra_h = max(0, desired_h - base_h)
        extra_top = extra_h // 2
        canvas_h = base_h + extra_h
    else:
        desired_w = int(round(base_h * target_ratio))
        extra_w = max(0, desired_w - base_w)
        extra_left = extra_w // 2
        canvas_w = base_w + extra_w

    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
    y0 = margin_y + extra_top
    x0 = margin_x + extra_left
    canvas[y0 : y0 + h, x0 : x0 + w] = trimmed
    cv2.rectangle(canvas, (x0 - 1, y0 - 1), (x0 + w, y0 + h), (230, 230, 230), 1)
    return canvas
