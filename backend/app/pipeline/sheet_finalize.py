from __future__ import annotations

from typing import List, Literal, Optional, Tuple

import cv2
import numpy as np


PORTRAIT_PAGE_RATIO = 1.0 / 1.4142  # A-series portrait, width / height ~= 0.707
PageFillMode = Literal["balanced", "performance"]


def finalize_sheet_pages(
    image,
    *,
    page_ratio: float = PORTRAIT_PAGE_RATIO,
    page_fill_mode: PageFillMode = "performance",
) -> List[np.ndarray]:
    if image is None or image.size == 0:
        return []

    prepared = _normalize_score_tone(image)
    pages = _split_long_page(prepared, page_ratio=page_ratio, page_fill_mode=page_fill_mode)
    if not pages:
        pages = [prepared]
    return [_frame_as_printed_page(page, page_ratio=page_ratio) for page in pages]


def finalize_sheet_sequence(
    images: List[np.ndarray],
    *,
    page_ratio: float = PORTRAIT_PAGE_RATIO,
    page_fill_mode: PageFillMode = "performance",
) -> Tuple[List[np.ndarray], Optional[np.ndarray], int]:
    prepared_frames: List[np.ndarray] = []
    for image in images:
        if image is None or image.size == 0:
            continue
        prepared = _normalize_score_tone(image)
        if prepared is None or prepared.size == 0:
            continue
        if prepared_frames and _is_near_same_frame(prepared_frames[-1], prepared):
            continue
        prepared_frames.append(prepared)

    if not prepared_frames:
        return [], None, 0

    merged = prepared_frames[0]
    for frame in prepared_frames[1:]:
        merged = _merge_vertical_sheet(merged, frame)

    pages = _split_long_page(merged, page_ratio=page_ratio, page_fill_mode=page_fill_mode)
    if not pages:
        pages = [merged]
    page_frames = [_frame_as_printed_page(page, page_ratio=page_ratio) for page in pages]
    return page_frames, merged, len(prepared_frames)


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


def _is_near_same_frame(a, b) -> bool:
    h = min(a.shape[0], b.shape[0], 900)
    w = min(a.shape[1], b.shape[1], 1600)
    if h < 24 or w < 24:
        return False
    a_gray = cv2.cvtColor(cv2.resize(a, (w, h)), cv2.COLOR_BGR2GRAY)
    b_gray = cv2.cvtColor(cv2.resize(b, (w, h)), cv2.COLOR_BGR2GRAY)
    diff = float(np.mean(np.abs(a_gray.astype(np.float32) - b_gray.astype(np.float32))))
    return diff < 5.8


def _merge_vertical_sheet(top, bottom) -> np.ndarray:
    if top is None or top.size == 0:
        return bottom
    if bottom is None or bottom.size == 0:
        return top

    top_w = int(top.shape[1])
    bottom_w = int(bottom.shape[1])
    if top_w != bottom_w:
        # Keep original scale and pad narrower frame instead of shrinking to min width.
        # Shrinking all frames to the narrowest width can cause excessive side whitespace in final PDF pages.
        target_w = max(top_w, bottom_w)
        top = _pad_to_width(top, target_w)
        bottom = _pad_to_width(bottom, target_w)

    overlap = _estimate_vertical_overlap(top, bottom)
    if overlap <= 0:
        gap = np.full((12, top.shape[1], 3), 255, dtype=np.uint8)
        return np.vstack((top, gap, bottom))

    keep_top = top[:-overlap] if overlap < top.shape[0] else top[:0]
    a = top[-overlap:].astype(np.float32)
    b = bottom[:overlap].astype(np.float32)
    alpha = np.linspace(1.0, 0.0, overlap, dtype=np.float32).reshape(overlap, 1, 1)
    blended = np.clip((a * alpha) + (b * (1.0 - alpha)), 0, 255).astype(np.uint8)
    rest_bottom = bottom[overlap:] if overlap < bottom.shape[0] else bottom[:0]
    return np.vstack((keep_top, blended, rest_bottom))


def _pad_to_width(image, target_w: int) -> np.ndarray:
    h, w = image.shape[:2]
    if target_w <= w:
        return image
    pad_left = (target_w - w) // 2
    pad_right = target_w - w - pad_left
    return cv2.copyMakeBorder(image, 0, 0, pad_left, pad_right, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def _estimate_vertical_overlap(top, bottom) -> int:
    top_h = int(top.shape[0])
    bottom_h = int(bottom.shape[0])
    if top_h < 30 or bottom_h < 30:
        return 0

    top_gray = cv2.cvtColor(top, cv2.COLOR_BGR2GRAY)
    bottom_gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
    top_gray = cv2.GaussianBlur(top_gray, (3, 3), 0)
    bottom_gray = cv2.GaussianBlur(bottom_gray, (3, 3), 0)

    max_overlap = int(min(top_h, bottom_h, max(60, min(top_h, bottom_h) * 0.34)))
    min_overlap = max(18, int(min(top_h, bottom_h) * 0.06))
    if max_overlap <= min_overlap:
        return 0

    best_overlap = 0
    best_score = float("inf")
    step = 3 if max_overlap > 90 else 2
    for overlap in range(min_overlap, max_overlap + 1, step):
        a = top_gray[top_h - overlap : top_h]
        b = bottom_gray[:overlap]
        if a.shape != b.shape or a.size == 0:
            continue
        score = float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))
        if score < best_score:
            best_score = score
            best_overlap = overlap

    if best_overlap <= 0:
        return 0

    # Lower is better (0: perfect match, 255: total mismatch).
    # Tuned for score-capture images to avoid false overlap on unrelated pages.
    if best_score <= 19.5:
        return best_overlap
    return 0


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


def _split_long_page(image, *, page_ratio: float, page_fill_mode: PageFillMode = "performance") -> List[np.ndarray]:
    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        return []

    mode: PageFillMode = "performance" if page_fill_mode == "performance" else "balanced"

    target_h = int(np.clip(round(w / max(0.35, page_ratio)), 900, 2600))
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
        return _slice_by_whitespace(image, row_density=row_density, target_h=target_h, page_fill_mode=mode)

    if mode == "performance":
        # Performance mode: fit more systems per page to reduce page turns.
        gap_pad = max(6, int(target_h * 0.012))
        soft_page_limit = int(target_h * 1.02)
        hard_page_limit = int(target_h * 1.10)
        underfill_floor = int(target_h * 0.90)
    else:
        gap_pad = max(8, int(h * 0.012))
        # Balanced mode keeps conservative breathing room near page bottoms.
        soft_page_limit = int(target_h * 0.93)
        hard_page_limit = soft_page_limit
        underfill_floor = 0
    expanded = [(max(0, s - gap_pad), min(h, e + gap_pad)) for s, e in bands]

    pages: List[Tuple[int, int]] = []
    cur_s, cur_e = expanded[0]
    for s, e in expanded[1:]:
        candidate_h = e - cur_s
        current_h = cur_e - cur_s
        if candidate_h <= soft_page_limit:
            cur_e = e
            continue
        if underfill_floor > 0 and current_h < underfill_floor and candidate_h <= hard_page_limit:
            cur_e = e
            continue
        pages.append((cur_s, cur_e))
        cur_s, cur_e = s, e
    pages.append((cur_s, cur_e))
    pages = _resolve_overlapping_ranges(pages, row_density=row_density)

    normalized_pages: List[np.ndarray] = []
    for s, e in pages:
        if e - s > int(target_h * 1.32):
            oversized = image[s:e]
            sub_density = row_density[s:e]
            normalized_pages.extend(
                _slice_by_whitespace(
                    oversized,
                    row_density=sub_density,
                    target_h=target_h,
                    page_fill_mode=mode,
                )
            )
            continue
        normalized_pages.append(image[s:e].copy())

    return normalized_pages or _slice_by_whitespace(
        image,
        row_density=row_density,
        target_h=target_h,
        page_fill_mode=mode,
    )


def _resolve_overlapping_ranges(
    ranges: List[Tuple[int, int]],
    *,
    row_density: np.ndarray,
) -> List[Tuple[int, int]]:
    if not ranges:
        return []

    resolved: List[Tuple[int, int]] = []
    total_h = int(row_density.shape[0])
    for raw_s, raw_e in ranges:
        s = max(0, int(raw_s))
        e = min(total_h, int(raw_e))
        if e <= s:
            continue

        if not resolved:
            resolved.append((s, e))
            continue

        prev_s, prev_e = resolved[-1]
        if s < prev_e:
            boundary_lo = max(prev_s + 1, s)
            boundary_hi = min(prev_e - 1, e - 1)
            if boundary_lo <= boundary_hi:
                overlap_slice = row_density[s:prev_e]
                if overlap_slice.size > 0:
                    candidate = s + int(np.argmin(overlap_slice))
                    boundary = int(np.clip(candidate, boundary_lo, boundary_hi))
                else:
                    boundary = (boundary_lo + boundary_hi) // 2
                resolved[-1] = (prev_s, boundary)
                s = boundary

        if e <= s:
            continue
        resolved.append((s, e))

    return resolved


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


def _slice_by_whitespace(
    image,
    *,
    row_density: np.ndarray,
    target_h: int,
    page_fill_mode: PageFillMode = "performance",
) -> List[np.ndarray]:
    mode: PageFillMode = "performance" if page_fill_mode == "performance" else "balanced"
    h = image.shape[0]
    pages: List[np.ndarray] = []
    start = 0
    min_h = max(180, int(target_h * (0.74 if mode == "performance" else 0.58)))
    blank_threshold = float(np.clip(np.percentile(row_density, 28) * 1.35, 0.0025, 0.018))

    while start < h:
        hard_end = min(h, start + target_h)
        if hard_end >= h:
            pages.append(image[start:h].copy())
            break

        # Prefer cutting a little earlier (before hard_end) so the current page
        # keeps bottom breathing room instead of clipping near the edge.
        if mode == "performance":
            back_window = int(target_h * 0.14)
            forward_window = int(target_h * 0.28)
            back_blank_multiplier = 0.82
            back_density_ratio = 0.72
        else:
            back_window = int(target_h * 0.28)
            forward_window = int(target_h * 0.20)
            back_blank_multiplier = 1.0
            back_density_ratio = 0.82
        search_lo = max(start + min_h, hard_end - back_window)
        search_mid = hard_end
        search_hi = min(h - 1, hard_end + forward_window)

        cut = hard_end
        if search_mid > search_lo:
            back_local = row_density[search_lo:search_mid]
            if back_local.size > 0:
                if mode == "performance":
                    # In performance mode, prefer the last whitespace row before hard_end,
                    # not the globally lowest valley that can be much earlier.
                    back_candidates = np.where(back_local <= (blank_threshold * 0.96))[0]
                    back_idx = int(back_candidates[-1]) if back_candidates.size > 0 else int(np.argmin(back_local))
                else:
                    back_idx = int(np.argmin(back_local))
                back_cut = search_lo + back_idx
                back_density = float(row_density[min(h - 1, back_cut)])
                hard_density = float(row_density[min(h - 1, max(0, hard_end - 1))])
                # Prefer earlier cut only if it is clearly less dense than the hard boundary.
                if back_density <= (blank_threshold * back_blank_multiplier) or back_density < (hard_density * back_density_ratio):
                    cut = back_cut

        cut_density = float(row_density[min(h - 1, max(0, cut - 1))])
        # If backward cut is too tight or still too dense, search slightly forward near hard_end.
        if (cut - start < min_h or cut_density > (blank_threshold * 1.25)) and search_hi > search_mid:
            fwd_local = row_density[search_mid : search_hi + 1]
            if fwd_local.size > 0:
                fwd_idx = int(np.argmin(fwd_local))
                fwd_cut = search_mid + fwd_idx
                fwd_density = float(row_density[min(h - 1, fwd_cut)])
                if fwd_density <= cut_density * 0.94:
                    cut = fwd_cut

        cut = max(cut, start + min_h)
        cut = min(cut, h)
        if cut <= start:
            cut = min(h, start + target_h)

        # Prefer clear whitespace rows when possible; avoid cutting through staff lines.
        cut_density = float(row_density[min(h - 1, max(0, cut - 1))])
        if cut_density > (blank_threshold * 1.12):
            nearby = row_density[search_lo : search_hi + 1]
            blank_indices = np.where(nearby <= blank_threshold)[0]
            if blank_indices.size > 0:
                absolute = blank_indices + search_lo
                if mode == "performance":
                    min_pick = max(start + min_h, hard_end - int(target_h * 0.09))
                    tightened = absolute[absolute >= min_pick]
                    if tightened.size > 0:
                        absolute = tightened
                pick = int(absolute[np.argmin(np.abs(absolute - hard_end))])
                if pick - start >= max(96, int(min_h * 0.42)):
                    cut = pick

        pages.append(image[start:cut].copy())
        # Start exactly at the chosen cut to avoid duplicated strips across pages.
        start = cut

    return _merge_short_trailing_page(pages, target_h=target_h, page_fill_mode=mode)


def _merge_short_trailing_page(
    pages: List[np.ndarray],
    *,
    target_h: int,
    page_fill_mode: PageFillMode = "performance",
) -> List[np.ndarray]:
    mode: PageFillMode = "performance" if page_fill_mode == "performance" else "balanced"
    if len(pages) < 2:
        return pages

    result = list(pages)
    if mode == "performance":
        min_tail = max(84, int(target_h * 0.42))
        max_prev = int(target_h * 1.18)
        max_prev_soft = int(target_h * 1.24)
    else:
        min_tail = max(84, int(target_h * 0.22))
        max_prev = int(target_h * 1.08)
        max_prev_soft = int(target_h * 1.16)

    while len(result) >= 2:
        tail = result[-1]
        prev = result[-2]
        tail_h = int(tail.shape[0])
        prev_h = int(prev.shape[0])

        if tail_h >= min_tail:
            break

        can_hard_merge = (prev_h + tail_h) <= max_prev
        can_soft_merge = tail_h <= int(min_tail * 0.62) and (prev_h + tail_h) <= max_prev_soft
        if not can_hard_merge and not can_soft_merge:
            break

        result[-2] = np.vstack((prev, tail))
        result.pop()

    return result


def _frame_as_printed_page(image, *, page_ratio: float) -> np.ndarray:
    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        return image

    # Print-safe margins with extra space at bottom to avoid last-staff clipping.
    margin_x = max(10, int(w * 0.015))
    margin_top = max(14, int(h * 0.026))
    margin_bottom = max(24, int(h * 0.056))

    base_w = w + (margin_x * 2)
    base_h = h + margin_top + margin_bottom
    target_ratio = max(0.6, float(page_ratio))
    cur_ratio = float(base_w) / float(max(1, base_h))

    extra_left = 0
    canvas_w = base_w
    canvas_h = base_h
    if cur_ratio > target_ratio:
        desired_h = int(round(base_w / target_ratio))
        extra_h = max(0, desired_h - base_h)
        # Keep top alignment for short captures.
        # Centering vertical slack makes single-strip pages appear "floating" in the middle.
        canvas_h = base_h + extra_h

    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
    y0 = margin_top
    x0 = margin_x + extra_left
    canvas[y0 : y0 + h, x0 : x0 + w] = image
    return canvas
