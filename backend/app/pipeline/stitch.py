from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np

from app.pipeline.layout_profiles import LAYOUT_BOTTOM_BAR, LAYOUT_FULL_SCROLL, LAYOUT_PAGE_TURN, resolve_layout_hint
from app.schemas import StitchOptions


def stitch_pages(
    *,
    frame_paths: List[Path],
    options: StitchOptions,
    workspace: Path,
    source_type: Optional[str] = None,
    logger,
) -> List[Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    if not frame_paths:
        return []

    layout_mode = resolve_layout_hint(options.layout_hint, source_type=source_type)
    logger(f"temporal dedupe mode: {options.dedupe_level}")
    filtered_frames = _filter_redundant_frames(
        frame_paths=frame_paths,
        layout_mode=layout_mode,
        dedupe_level=options.dedupe_level,
        logger=logger,
    )
    if not filtered_frames:
        return []

    if layout_mode == LAYOUT_PAGE_TURN:
        logger("page-turn mode: compressing repeated pages")
        return _collect_page_turn_pages(
            frame_paths=filtered_frames,
            options=options,
            workspace=workspace,
            logger=logger,
        )

    if not options.enable:
        logger("stitch disabled, returning filtered frame pages")
        return filtered_frames

    effective_threshold = _effective_overlap_threshold(options.overlap_threshold, layout_mode=layout_mode)
    logger(f"stitch overlap threshold: raw={options.overlap_threshold:.2f} effective={effective_threshold:.2f}")

    merged_paths: List[Path] = []
    buffer = cv2.imread(str(filtered_frames[0]))
    if buffer is None:
        raise RuntimeError("failed to read first rectified frame")

    for path in filtered_frames[1:]:
        next_image = cv2.imread(str(path))
        if next_image is None:
            continue

        score, overlap_px, shift_px = _overlap_score(buffer, next_image)
        if score >= effective_threshold:
            logger(f"overlap detected ({score:.2f}, overlap={overlap_px}px, shift={shift_px:+.1f}px) -> stitching candidate")
            buffer = _stitch_pair(buffer, next_image, overlap_px=overlap_px)
        else:
            out_path = workspace / f"page_{len(merged_paths):04d}.png"
            cv2.imwrite(str(out_path), buffer)
            merged_paths.append(out_path)
            buffer = next_image

    out_path = workspace / f"page_{len(merged_paths):04d}.png"
    cv2.imwrite(str(out_path), buffer)
    merged_paths.append(out_path)
    logger(f"stitched pages generated: {len(merged_paths)}")
    return merged_paths


def _filter_redundant_frames(
    *,
    frame_paths: List[Path],
    layout_mode: str,
    dedupe_level: str = "normal",
    logger,
) -> List[Path]:
    if len(frame_paths) <= 1:
        return frame_paths

    kept_paths: List[Path] = [frame_paths[0]]
    prev = cv2.imread(str(frame_paths[0]))
    if prev is None:
        return frame_paths

    recent_hashes: Deque[int] = deque(maxlen=8)
    first_hash = _frame_dhash(prev)
    if first_hash is not None:
        recent_hashes.append(first_hash)

    removed = 0
    scroll_direction = 0
    for path in frame_paths[1:]:
        current = cv2.imread(str(path))
        if current is None:
            continue
        if _is_near_duplicate(prev, current, layout_mode=layout_mode, dedupe_level=dedupe_level):
            removed += 1
            continue

        current_hash = _frame_dhash(current)
        if layout_mode in {LAYOUT_BOTTOM_BAR, LAYOUT_PAGE_TURN}:
            if current_hash is not None and _looks_like_recent_hash_duplicate(
                current_hash,
                recent_hashes=recent_hashes,
                layout_mode=layout_mode,
                dedupe_level=dedupe_level,
            ):
                removed += 1
                continue

        if layout_mode == LAYOUT_FULL_SCROLL:
            shift_px, shift_conf = _estimate_vertical_shift(prev, current)
            min_scroll_shift = _min_scroll_shift_by_level(dedupe_level)
            if shift_conf >= 0.34 and abs(shift_px) < min_scroll_shift:
                removed += 1
                continue

            if shift_conf >= 0.4 and abs(shift_px) >= 1.0:
                direction = 1 if shift_px > 0 else -1
                # Ignore tiny opposite-direction jitter while scrolling.
                if scroll_direction != 0 and direction != scroll_direction and abs(shift_px) < (min_scroll_shift * 1.8):
                    removed += 1
                    continue
                scroll_direction = direction

        kept_paths.append(path)
        prev = current
        if current_hash is not None:
            recent_hashes.append(current_hash)

    if removed > 0:
        logger(f"temporal dedupe removed {removed} near-duplicate frames")
    return kept_paths


def _is_near_duplicate(prev_img, cur_img, *, layout_mode: str, dedupe_level: str) -> bool:
    h = min(prev_img.shape[0], cur_img.shape[0], 900)
    w = min(prev_img.shape[1], cur_img.shape[1], 1600)
    if h <= 16 or w <= 16:
        return False

    prev_gray = cv2.cvtColor(cv2.resize(prev_img, (w, h)), cv2.COLOR_BGR2GRAY)
    cur_gray = cv2.cvtColor(cv2.resize(cur_img, (w, h)), cv2.COLOR_BGR2GRAY)

    prev_gray = cv2.GaussianBlur(prev_gray, (3, 3), 0)
    cur_gray = cv2.GaussianBlur(cur_gray, (3, 3), 0)

    diff = cv2.absdiff(prev_gray, cur_gray)
    _, mask = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
    changed = float(cv2.countNonZero(mask))
    total = float(max(1, h * w))
    changed_ratio = changed / total

    structure_diff = _structure_diff_ratio(prev_gray, cur_gray)

    if layout_mode == LAYOUT_BOTTOM_BAR:
        static_threshold = _threshold_by_level(dedupe_level, aggressive=0.045, normal=0.028, sensitive=0.016)
        structure_threshold = _threshold_by_level(dedupe_level, aggressive=0.085, normal=0.062, sensitive=0.042)
        playhead_threshold = _threshold_by_level(dedupe_level, aggressive=0.22, normal=0.14, sensitive=0.09)

        if changed_ratio < static_threshold:
            return True
        if structure_diff < structure_threshold:
            return True
        if changed_ratio < playhead_threshold and _looks_like_moving_playhead(mask):
            return True
        return False

    if layout_mode == LAYOUT_PAGE_TURN:
        static_threshold = _threshold_by_level(dedupe_level, aggressive=0.012, normal=0.008, sensitive=0.005)
        structure_threshold = _threshold_by_level(dedupe_level, aggressive=0.032, normal=0.024, sensitive=0.017)
        return changed_ratio < static_threshold or structure_diff < structure_threshold

    static_threshold = _threshold_by_level(dedupe_level, aggressive=0.026, normal=0.018, sensitive=0.012)
    structure_threshold = _threshold_by_level(dedupe_level, aggressive=0.052, normal=0.038, sensitive=0.026)
    return changed_ratio < static_threshold or structure_diff < structure_threshold


def _looks_like_moving_playhead(binary_mask) -> bool:
    h, w = binary_mask.shape[:2]
    if h <= 0 or w <= 0:
        return False

    changed_idx = np.where(binary_mask > 0)
    if changed_idx[0].size > 0:
        x_min = int(changed_idx[1].min())
        x_max = int(changed_idx[1].max())
        y_min = int(changed_idx[0].min())
        y_max = int(changed_idx[0].max())
        box_w_ratio = float(x_max - x_min + 1) / float(max(1, w))
        box_h_ratio = float(y_max - y_min + 1) / float(max(1, h))
        changed_ratio = float(changed_idx[0].size) / float(max(1, w * h))
        if box_w_ratio <= 0.22 and box_h_ratio >= 0.42 and changed_ratio <= 0.25:
            return True

    col_density = (binary_mask > 0).sum(axis=0).astype(np.float32) / float(max(1, h))
    active_cols = np.where(col_density > 0.45)[0]
    if active_cols.size == 0:
        return False

    width = int(active_cols.max() - active_cols.min() + 1)
    max_width = max(6, int(w * 0.16))
    if width > max_width:
        return False

    changed_total = float(np.count_nonzero(binary_mask))
    if changed_total <= 0:
        return False

    concentrated = float(np.count_nonzero(binary_mask[:, active_cols])) / changed_total
    return concentrated > 0.52


def _structure_diff_ratio(prev_gray, cur_gray) -> float:
    prev_inv = cv2.adaptiveThreshold(
        prev_gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    cur_inv = cv2.adaptiveThreshold(
        cur_gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    prev_clean = cv2.morphologyEx(prev_inv, cv2.MORPH_OPEN, kernel)
    cur_clean = cv2.morphologyEx(cur_inv, cv2.MORPH_OPEN, kernel)
    xor = cv2.bitwise_xor(prev_clean, cur_clean)
    return float(cv2.countNonZero(xor)) / float(max(1, prev_gray.shape[0] * prev_gray.shape[1]))


def _threshold_by_level(level: str, *, aggressive: float, normal: float, sensitive: float) -> float:
    if level == "aggressive":
        return aggressive
    if level == "sensitive":
        return sensitive
    return normal


def _min_scroll_shift_by_level(level: str) -> float:
    if level == "aggressive":
        return 5.4
    if level == "sensitive":
        return 1.8
    return 3.2


def _frame_dhash(image: np.ndarray) -> Optional[int]:
    h, w = image.shape[:2]
    if h < 8 or w < 9:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = 0
    for flag in diff.reshape(-1):
        bits = (bits << 1) | int(flag)
    return bits


def _hamming_u64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def _looks_like_recent_hash_duplicate(
    current_hash: int,
    *,
    recent_hashes: Deque[int],
    layout_mode: str,
    dedupe_level: str,
) -> bool:
    if not recent_hashes:
        return False

    if layout_mode == LAYOUT_PAGE_TURN:
        threshold = int(_threshold_by_level(dedupe_level, aggressive=3, normal=2, sensitive=1))
    elif layout_mode == LAYOUT_BOTTOM_BAR:
        threshold = int(_threshold_by_level(dedupe_level, aggressive=8, normal=6, sensitive=4))
    else:
        threshold = int(_threshold_by_level(dedupe_level, aggressive=7, normal=5, sensitive=3))

    min_dist = min(_hamming_u64(current_hash, candidate) for candidate in recent_hashes)
    return min_dist <= threshold


def _effective_overlap_threshold(raw_threshold: float, *, layout_mode: str) -> float:
    raw = float(max(0.0, min(1.0, raw_threshold)))
    if layout_mode == LAYOUT_BOTTOM_BAR:
        return float(max(0.56, min(0.9, 0.5 + (raw * 0.52))))
    if layout_mode == LAYOUT_FULL_SCROLL:
        return float(max(0.62, min(0.94, 0.55 + (raw * 0.58))))
    if layout_mode == LAYOUT_PAGE_TURN:
        return float(max(0.74, min(0.97, 0.68 + (raw * 0.28))))
    return float(max(0.6, min(0.92, 0.54 + (raw * 0.56))))


def _pad_to_width(image: np.ndarray, target_w: int) -> np.ndarray:
    h, w = image.shape[:2]
    if target_w <= w:
        return image
    pad_left = (target_w - w) // 2
    pad_right = target_w - w - pad_left
    return cv2.copyMakeBorder(image, 0, 0, pad_left, pad_right, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def _align_width(img_a: np.ndarray, img_b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    w1 = int(img_a.shape[1])
    w2 = int(img_b.shape[1])
    if w1 == w2:
        return img_a, img_b
    target_w = max(w1, w2)
    return _pad_to_width(img_a, target_w), _pad_to_width(img_b, target_w)


def _estimate_vertical_shift(img_a: np.ndarray, img_b: np.ndarray) -> Tuple[float, float]:
    h = min(img_a.shape[0], img_b.shape[0], 1200)
    w = min(img_a.shape[1], img_b.shape[1], 1400)
    if h < 40 or w < 40:
        return 0.0, 0.0

    a = cv2.cvtColor(cv2.resize(img_a, (w, h)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(img_b, (w, h)), cv2.COLOR_BGR2GRAY)
    a = cv2.GaussianBlur(a, (3, 3), 0)
    b = cv2.GaussianBlur(b, (3, 3), 0)

    # Use central columns to reduce side overlays/watermarks impact.
    x_pad = max(4, int(w * 0.08))
    if w - (x_pad * 2) <= 10:
        return 0.0, 0.0
    a_center = a[:, x_pad : w - x_pad]
    b_center = b[:, x_pad : w - x_pad]

    row_a = a_center.mean(axis=1).astype(np.float32)
    row_b = b_center.mean(axis=1).astype(np.float32)
    row_a -= float(np.mean(row_a))
    row_b -= float(np.mean(row_b))

    std_a = float(np.std(row_a))
    std_b = float(np.std(row_b))
    if std_a < 1e-5 or std_b < 1e-5:
        return 0.0, 0.0

    max_shift = max(20, int(h * 0.22))
    lags = range(-max_shift, max_shift + 1)
    best_lag = 0
    best_score = -1e12
    for lag in lags:
        if lag >= 0:
            a_seg = row_a[lag:]
            b_seg = row_b[: len(a_seg)]
        else:
            b_seg = row_b[-lag:]
            a_seg = row_a[: len(b_seg)]
        if a_seg.size < 24 or b_seg.size < 24:
            continue
        score = float(np.dot(a_seg, b_seg) / float(max(1, a_seg.size)))
        if score > best_score:
            best_score = score
            best_lag = lag

    denom = std_a * std_b
    norm = best_score / max(1e-6, denom)
    # Typical normalized correlation for valid scroll shifts is around 0.9~1.0 on score videos.
    # Rescale confidence so shift gating can reliably reject near-static jitter frames.
    row_confidence = float(max(0.0, min(1.0, (norm - 0.16) / 0.72)))

    phase_shift, phase_confidence = _estimate_vertical_shift_phasecorr(
        a_center,
        b_center,
        max_shift=max_shift,
    )

    if phase_confidence >= max(0.38, row_confidence + 0.12):
        return phase_shift, phase_confidence
    if row_confidence >= 0.24:
        return float(best_lag), row_confidence
    if phase_confidence >= 0.3:
        # Low-confidence case: phase correlation usually gives better magnitude on smooth scroll.
        return phase_shift, phase_confidence
    return float(best_lag), row_confidence


def _estimate_vertical_shift_phasecorr(a_gray: np.ndarray, b_gray: np.ndarray, *, max_shift: int) -> Tuple[float, float]:
    if a_gray.size == 0 or b_gray.size == 0 or a_gray.shape != b_gray.shape:
        return 0.0, 0.0

    a_f = a_gray.astype(np.float32)
    b_f = b_gray.astype(np.float32)
    a_f -= float(np.mean(a_f))
    b_f -= float(np.mean(b_f))

    std_a = float(np.std(a_f))
    std_b = float(np.std(b_f))
    if std_a < 1e-5 or std_b < 1e-5:
        return 0.0, 0.0

    (dx, dy), response = cv2.phaseCorrelate(a_f, b_f)
    if not np.isfinite(dy):
        return 0.0, 0.0

    # Match row-correlation sign convention used in this module.
    # (row method returns +shift for visually upward moved next frame)
    shift = float(-dy)
    shift = float(np.clip(shift, -float(max_shift), float(max_shift)))
    confidence = float(np.clip((float(response) - 0.08) / 0.76, 0.0, 1.0))
    return shift, confidence


def _collect_page_turn_pages(
    *,
    frame_paths: List[Path],
    options: StitchOptions,
    workspace: Path,
    logger,
) -> List[Path]:
    saved_paths: List[Path] = []
    current = cv2.imread(str(frame_paths[0]))
    if current is None:
        raise RuntimeError("failed to read first rectified frame")

    similarity_threshold = max(0.88, min(0.98, 1.0 - (options.overlap_threshold * 0.25)))
    for path in frame_paths[1:]:
        next_image = cv2.imread(str(path))
        if next_image is None:
            continue
        similarity = _frame_similarity(current, next_image)
        if similarity >= similarity_threshold:
            continue

        out_path = workspace / f"page_{len(saved_paths):04d}.png"
        cv2.imwrite(str(out_path), current)
        saved_paths.append(out_path)
        logger(f"page transition detected ({similarity:.2f}) -> new page")
        current = next_image

    out_path = workspace / f"page_{len(saved_paths):04d}.png"
    cv2.imwrite(str(out_path), current)
    saved_paths.append(out_path)
    logger(f"page-turn pages generated: {len(saved_paths)}")
    return saved_paths


def _overlap_score(img_a, img_b) -> Tuple[float, int, float]:
    img_a, img_b = _align_width(img_a, img_b)
    h = min(img_a.shape[0], img_b.shape[0])
    w = min(img_a.shape[1], img_b.shape[1])
    if h <= 2 or w <= 2:
        return 0.0, 0, 0.0
    a = cv2.cvtColor(cv2.resize(img_a, (w, h)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(img_b, (w, h)), cv2.COLOR_BGR2GRAY)
    a = cv2.GaussianBlur(a, (3, 3), 0)
    b = cv2.GaussianBlur(b, (3, 3), 0)

    shift_px, shift_conf = _estimate_vertical_shift(img_a, img_b)
    min_overlap = max(24, int(h * 0.05))
    max_overlap = min(int(h * 0.88), h - 2)
    if max_overlap <= min_overlap:
        return 0.0, min_overlap, shift_px

    expected_overlap = int(np.clip(h - max(1.0, abs(shift_px)), min_overlap, max_overlap))
    search_radius = max(20, int(h * 0.1))
    lo = max(min_overlap, expected_overlap - search_radius)
    hi = min(max_overlap, expected_overlap + search_radius)
    if shift_conf < 0.25 or hi <= lo:
        lo = min_overlap
        hi = max_overlap

    x_pad = max(6, int(w * 0.08))
    if w - (x_pad * 2) > 20:
        a_use = a[:, x_pad : w - x_pad]
        b_use = b[:, x_pad : w - x_pad]
    else:
        a_use = a
        b_use = b

    best_overlap = lo
    best_diff = float("inf")
    step = 2 if (hi - lo) <= 160 else 3
    for overlap in range(lo, hi + 1, step):
        a_strip = a_use[h - overlap : h]
        b_strip = b_use[:overlap]
        if a_strip.size == 0 or b_strip.size == 0 or a_strip.shape != b_strip.shape:
            continue
        diff = float(np.mean(np.abs(a_strip.astype(np.float32) - b_strip.astype(np.float32))))
        if diff < best_diff:
            best_diff = diff
            best_overlap = overlap

    if not np.isfinite(best_diff):
        return 0.0, best_overlap, shift_px

    score = 1.0 - (best_diff / 255.0)
    score = float(max(0.0, min(1.0, score)))
    if shift_conf < 0.15 and score < 0.78:
        score *= 0.9
    return score, int(best_overlap), shift_px


def _frame_similarity(img_a, img_b):
    h = min(img_a.shape[0], img_b.shape[0])
    w = min(img_a.shape[1], img_b.shape[1])
    if h <= 2 or w <= 2:
        return 0.0
    a = cv2.cvtColor(cv2.resize(img_a, (w, h)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(img_b, (w, h)), cv2.COLOR_BGR2GRAY)
    diff = np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() / 255.0
    return float(max(0.0, min(1.0, 1.0 - diff)))


def _stitch_pair(top, bottom, *, overlap_px: Optional[int] = None):
    top, bottom = _align_width(top, bottom)
    overlap = int(overlap_px) if overlap_px is not None else min(int(min(top.shape[0], bottom.shape[0]) * 0.25), 150)
    overlap = max(0, min(overlap, min(top.shape[0], bottom.shape[0]) - 1))
    if overlap <= 0:
        return np.vstack((top, bottom))

    keep_top = top[:-overlap] if overlap < top.shape[0] else top[:0]
    seam = max(10, min(overlap, 42))
    a = top[-seam:].astype(np.float32)
    b = bottom[:seam].astype(np.float32)
    alpha = np.linspace(1.0, 0.0, seam, dtype=np.float32).reshape(seam, 1, 1)
    blended = np.clip((a * alpha) + (b * (1.0 - alpha)), 0, 255).astype(np.uint8)
    rest_bottom = bottom[seam:] if seam < bottom.shape[0] else bottom[:0]
    return np.vstack((keep_top, blended, rest_bottom))
