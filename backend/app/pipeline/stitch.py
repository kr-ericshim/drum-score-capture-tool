from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from app.pipeline.layout_profiles import LAYOUT_BOTTOM_BAR, LAYOUT_PAGE_TURN, resolve_layout_hint
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

    merged_paths: List[Path] = []
    buffer = cv2.imread(str(filtered_frames[0]))
    if buffer is None:
        raise RuntimeError("failed to read first rectified frame")

    for path in filtered_frames[1:]:
        next_image = cv2.imread(str(path))
        if next_image is None:
            continue

        score = _overlap_score(buffer, next_image)
        if score >= options.overlap_threshold:
            logger(f"overlap detected ({score:.2f}) -> stitching candidate")
            buffer = _stitch_pair(buffer, next_image)
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

    removed = 0
    for path in frame_paths[1:]:
        current = cv2.imread(str(path))
        if current is None:
            continue
        if _is_near_duplicate(prev, current, layout_mode=layout_mode, dedupe_level=dedupe_level):
            removed += 1
            continue
        kept_paths.append(path)
        prev = current

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


def _overlap_score(img_a, img_b):
    h = min(img_a.shape[0], img_b.shape[0])
    w = min(img_a.shape[1], img_b.shape[1])
    if h <= 2 or w <= 2:
        return 0.0
    a = cv2.cvtColor(cv2.resize(img_a, (w, h)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(img_b, (w, h)), cv2.COLOR_BGR2GRAY)
    strip_h = max(40, h // 4)
    a_strip = a[h - strip_h :]
    b_strip = b[:strip_h]
    score = 1.0 - (np.abs(a_strip.astype(float) - b_strip.astype(float)).mean() / 255.0)
    return float(max(0.0, min(1.0, score)))


def _frame_similarity(img_a, img_b):
    h = min(img_a.shape[0], img_b.shape[0])
    w = min(img_a.shape[1], img_b.shape[1])
    if h <= 2 or w <= 2:
        return 0.0
    a = cv2.cvtColor(cv2.resize(img_a, (w, h)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(img_b, (w, h)), cv2.COLOR_BGR2GRAY)
    diff = np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() / 255.0
    return float(max(0.0, min(1.0, 1.0 - diff)))


def _stitch_pair(top, bottom):
    h1, w1 = top.shape[:2]
    h2, w2 = bottom.shape[:2]
    if w1 != w2:
        target_w = min(w1, w2)
        top = cv2.resize(top, (target_w, int(h1 * target_w / w1)))
        bottom = cv2.resize(bottom, (target_w, int(h2 * target_w / w2)))
    overlap = min(int(min(top.shape[0], bottom.shape[0]) * 0.25), 150)
    if overlap <= 0:
        return np.vstack((top, bottom))
    merged = np.vstack((top[:-overlap], bottom))
    return merged
