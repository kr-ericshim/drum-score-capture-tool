"""Local (blob-level) comparison of two score frames.

The previous dedupe checks in this pipeline all reduced a frame pair to a single
whole-image statistic (mean pixel difference, changed-pixel ratio, dHash). Those
statistics dilute small but musically meaningful edits: a drum page whose next
page differs by only a few note heads looks "the same" on average, so the page
was dropped. Conversely, a moving playhead or highlight box changes a lot of
pixels without changing the score.

This module answers a different question: *after aligning the two frames and
ignoring playback overlays, is there at least one note-sized blob of ink that
exists in one frame but not the other?*  Sizes are measured in staff-gap units
so the rules hold for a small bottom strip and a full page alike.

Verdicts:
    "same"       - no note-sized change (only noise, overlays, blur, tone drift)
    "different"  - at least one note-sized change, or the frames cannot be aligned
    "ambiguous"  - only sub-note residue, or the score looks identical while the
                   playhead jumped backwards (repeat / identical next page).
                   Callers should keep ambiguous frames and surface the pair for
                   review instead of silently discarding one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np


MAX_COMPARE_W = 1600
MAX_COMPARE_H = 900

VERDICT_SAME = "same"
VERDICT_DIFFERENT = "different"
VERDICT_AMBIGUOUS = "ambiguous"


@dataclass
class FrameDiffVerdict:
    verdict: str
    reason: str
    shift_x: float = 0.0
    shift_y: float = 0.0
    align_confidence: float = 0.0
    staff_gap: float = 0.0
    significant_blobs: int = 0
    minor_blobs: int = 0
    changed_ink_ratio: float = 0.0
    overlay_blobs: int = 0
    playhead_prev_x: Optional[float] = None
    playhead_cur_x: Optional[float] = None
    # Size of the compared frames; `change_boxes` are pixels in that space.
    frame_width: int = 0
    frame_height: int = 0
    change_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def is_same(self) -> bool:
        return self.verdict == VERDICT_SAME

    @property
    def is_different(self) -> bool:
        return self.verdict == VERDICT_DIFFERENT

    @property
    def is_ambiguous(self) -> bool:
        return self.verdict == VERDICT_AMBIGUOUS

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "shift_x": round(float(self.shift_x), 2),
            "shift_y": round(float(self.shift_y), 2),
            "align_confidence": round(float(self.align_confidence), 3),
            "staff_gap": round(float(self.staff_gap), 2),
            "significant_blobs": int(self.significant_blobs),
            "minor_blobs": int(self.minor_blobs),
            "changed_ink_ratio": round(float(self.changed_ink_ratio), 5),
            "overlay_blobs": int(self.overlay_blobs),
            "playhead_prev_x": None if self.playhead_prev_x is None else round(float(self.playhead_prev_x), 3),
            "playhead_cur_x": None if self.playhead_cur_x is None else round(float(self.playhead_cur_x), 3),
            "frame_size": [int(self.frame_width), int(self.frame_height)],
            "change_boxes": [list(map(int, box)) for box in self.change_boxes],
        }


@dataclass(frozen=True)
class DiffSensitivity:
    """Blob-size rules, in staff-gap units."""

    significant_area: float  # ink area (gap^2) for a single blob to count as a note-sized change
    significant_min_dim: float  # both bbox sides must be at least this (gaps)
    minor_area: float  # smaller residue that still counts when it appears several times
    minor_min_dim: float
    minor_count_for_different: int
    significant_count_for_different: int


def sensitivity_for_level(dedupe_level: str) -> DiffSensitivity:
    # A filled drum note head is roughly 1 gap tall and 1.2 gaps wide (~0.8 gap^2
    # of ink); an x head is thinner (~0.3 gap^2). Video blur and the tolerance
    # dilation shave the edges, so the thresholds sit below those sizes.
    if dedupe_level == "aggressive":
        return DiffSensitivity(
            significant_area=0.55,
            significant_min_dim=0.6,
            minor_area=0.18,
            minor_min_dim=0.45,
            minor_count_for_different=5,
            significant_count_for_different=1,
        )
    if dedupe_level == "sensitive":
        return DiffSensitivity(
            significant_area=0.2,
            significant_min_dim=0.4,
            minor_area=0.08,
            minor_min_dim=0.3,
            minor_count_for_different=2,
            significant_count_for_different=1,
        )
    return DiffSensitivity(
        significant_area=0.28,
        significant_min_dim=0.5,
        minor_area=0.1,
        minor_min_dim=0.35,
        minor_count_for_different=3,
        significant_count_for_different=1,
    )


PLAYHEAD_RESET_FRACTION = 0.3


def playhead_jumped_back(prev_x: Optional[float], cur_x: Optional[float]) -> bool:
    """True when the playhead moved back across a large part of the width.

    Positions are fractions of the frame width (see FrameDiffVerdict). Callers
    compare against the last *seen* frame, not the last kept one: after a page
    turn onto an identical-looking page the playhead restarts on the left while
    the previous frame had it near the right edge.
    """
    if prev_x is None or cur_x is None:
        return False
    return (prev_x - cur_x) >= PLAYHEAD_RESET_FRACTION


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def compare_frames(prev_img: np.ndarray, cur_img: np.ndarray, *, dedupe_level: str = "normal") -> FrameDiffVerdict:
    """Compare two BGR (or gray) frames of the same score region."""
    if prev_img is None or cur_img is None or prev_img.size == 0 or cur_img.size == 0:
        return FrameDiffVerdict(VERDICT_DIFFERENT, "empty_input")

    prev_bgr, cur_bgr = _prepare_pair(prev_img, cur_img)
    h, w = prev_bgr.shape[:2]
    if h < 24 or w < 24:
        return FrameDiffVerdict(VERDICT_DIFFERENT, "too_small")

    sensitivity = sensitivity_for_level(dedupe_level)

    prev_gray = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
    cur_gray = cv2.cvtColor(cur_bgr, cv2.COLOR_BGR2GRAY)

    prev_ink_full = _ink_mask(prev_gray)
    cur_ink_full = _ink_mask(cur_gray)

    prev_ink_ratio = float(cv2.countNonZero(prev_ink_full)) / float(h * w)
    cur_ink_ratio = float(cv2.countNonZero(cur_ink_full)) / float(h * w)
    if prev_ink_ratio < 0.0015 and cur_ink_ratio < 0.0015:
        return FrameDiffVerdict(VERDICT_SAME, "both_blank")

    gap = estimate_staff_gap(prev_ink_full)
    if gap <= 0:
        gap = estimate_staff_gap(cur_ink_full)
    if gap <= 0:
        gap = _fallback_staff_gap(h, w)

    # Staff lines are identical in both frames and only serve to swallow note
    # heads sitting in the spaces once tolerance dilation is applied, so the
    # comparison runs on ink with the long horizontal lines removed.
    prev_ink = _remove_staff_lines(prev_ink_full, gap=gap)
    cur_ink = _remove_staff_lines(cur_ink_full, gap=gap)

    # Overlays (playhead line, highlight box, progress bar) are located per frame
    # so that they can be ignored in the diff and used for playhead tracking.
    prev_overlay, prev_cursor = _overlay_mask(prev_bgr, prev_ink, gap=gap)
    cur_overlay, cur_cursor = _overlay_mask(cur_bgr, cur_ink, gap=gap)

    shift_x, shift_y, align_conf = _estimate_translation(prev_gray, cur_gray, prev_overlay, cur_overlay)
    max_shift_x = 0.35 * w
    max_shift_y = 0.35 * h
    if abs(shift_x) > max_shift_x or abs(shift_y) > max_shift_y:
        return FrameDiffVerdict(
            VERDICT_DIFFERENT,
            "alignment_out_of_range",
            shift_x=shift_x,
            shift_y=shift_y,
            align_confidence=align_conf,
            staff_gap=gap,
        )

    translation = np.array([[1.0, 0.0, -shift_x], [0.0, 1.0, -shift_y]], dtype=np.float32)
    result = _evaluate_alignment(
        prev_ink,
        cur_ink,
        prev_overlay,
        cur_overlay,
        warp=translation,
        gap=gap,
        sensitivity=sensitivity,
    )
    if result is None:
        return FrameDiffVerdict(
            VERDICT_DIFFERENT,
            "alignment_out_of_range",
            shift_x=shift_x,
            shift_y=shift_y,
            align_confidence=align_conf,
            staff_gap=gap,
        )

    # Translation alone leaves residue when the ROI was re-fitted with a tiny
    # rotation or scale change between frames. Before calling that a score
    # change, refine with an affine ECC fit and keep whichever leaves less.
    if result.significant + result.minor > 0 and result.significant + result.minor <= 200:
        refined_warp = _refine_affine(prev_gray, cur_gray, translation)
        if refined_warp is not None:
            refined = _evaluate_alignment(
                prev_ink,
                cur_ink,
                prev_overlay,
                cur_overlay,
                warp=refined_warp,
                gap=gap,
                sensitivity=sensitivity,
            )
            if refined is not None and (refined.significant, refined.minor) < (result.significant, result.minor):
                result = refined

    significant = result.significant
    minor = result.minor
    overlay_like = result.overlay_like
    changed_ink_ratio = result.changed_ink_ratio
    boxes = result.boxes
    x0 = result.crop[2]
    y0 = result.crop[0]

    verdict = FrameDiffVerdict(
        VERDICT_SAME,
        "no_note_change",
        shift_x=shift_x,
        shift_y=shift_y,
        align_confidence=align_conf,
        staff_gap=gap,
        significant_blobs=significant,
        minor_blobs=minor,
        changed_ink_ratio=changed_ink_ratio,
        overlay_blobs=overlay_like,
        playhead_prev_x=None if prev_cursor is None else prev_cursor / float(w),
        playhead_cur_x=None if cur_cursor is None else cur_cursor / float(w),
        frame_width=int(w),
        frame_height=int(h),
        change_boxes=[(bx + x0, by + y0, bw, bh) for (bx, by, bw, bh) in boxes],
    )

    if significant >= sensitivity.significant_count_for_different:
        verdict.verdict = VERDICT_DIFFERENT
        verdict.reason = "note_sized_change"
        return verdict
    if minor + significant >= sensitivity.minor_count_for_different:
        verdict.verdict = VERDICT_DIFFERENT
        verdict.reason = "many_small_changes"
        return verdict
    if significant > 0 or minor > 0:
        verdict.verdict = VERDICT_AMBIGUOUS
        verdict.reason = "small_change"
        return verdict

    # Identical score but the playhead jumped back a long way: either a repeat
    # inside the page or the next page happens to be identical (very common for
    # drum grooves). Never drop this silently.
    if playhead_jumped_back(verdict.playhead_prev_x, verdict.playhead_cur_x):
        verdict.verdict = VERDICT_AMBIGUOUS
        verdict.reason = "playhead_reset"
        return verdict

    if align_conf < 0.12 and changed_ink_ratio > 0.02:
        verdict.verdict = VERDICT_AMBIGUOUS
        verdict.reason = "low_alignment_confidence"
        return verdict

    return verdict


@dataclass
class _AlignmentResult:
    significant: int
    minor: int
    overlay_like: int
    changed_ink_ratio: float
    boxes: List[Tuple[int, int, int, int]]
    crop: Tuple[int, int, int, int]


def _evaluate_alignment(
    prev_ink: np.ndarray,
    cur_ink: np.ndarray,
    prev_overlay: np.ndarray,
    cur_overlay: np.ndarray,
    *,
    warp: np.ndarray,
    gap: float,
    sensitivity: DiffSensitivity,
) -> Optional[_AlignmentResult]:
    aligned_cur_ink, aligned_cur_overlay, crop = _warp_to_prev(cur_ink, cur_overlay, warp)
    y0, y1, x0, x1 = crop
    if (y1 - y0) < max(16, 2 * gap) or (x1 - x0) < max(16, 2 * gap):
        return None
    prev_ink_c = prev_ink[y0:y1, x0:x1]
    cur_ink_c = aligned_cur_ink[y0:y1, x0:x1]
    overlay_c = prev_overlay[y0:y1, x0:x1] | aligned_cur_overlay[y0:y1, x0:x1]

    tolerance = int(np.clip(round(gap * 0.16), 1, 3))
    change = _tolerant_xor(prev_ink_c, cur_ink_c, radius=tolerance)

    # Ignore change inside (slightly grown) overlay regions.
    if cv2.countNonZero(overlay_c) > 0:
        grow = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * tolerance + 3, 2 * tolerance + 3))
        overlay_grown = cv2.dilate(overlay_c, grow)
        change = cv2.bitwise_and(change, cv2.bitwise_not(overlay_grown))

    ink_union = float(cv2.countNonZero(cv2.bitwise_or(prev_ink_c, cur_ink_c)))
    changed_ink_ratio = float(cv2.countNonZero(change)) / max(1.0, ink_union)
    significant, minor, overlay_like, boxes = _classify_change_blobs(change, gap=gap, sensitivity=sensitivity)
    return _AlignmentResult(significant, minor, overlay_like, changed_ink_ratio, boxes, crop)


def _refine_affine(prev_gray: np.ndarray, cur_gray: np.ndarray, init_warp: np.ndarray) -> Optional[np.ndarray]:
    """ECC affine refinement at half resolution; None when it does not converge."""
    h, w = prev_gray.shape[:2]
    scale = 0.5 if min(h, w) >= 200 else 1.0
    if scale != 1.0:
        a = cv2.resize(prev_gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        b = cv2.resize(cur_gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        a, b = prev_gray, cur_gray
    a = cv2.GaussianBlur(a, (0, 0), 1.2).astype(np.float32)
    b = cv2.GaussianBlur(b, (0, 0), 1.2).astype(np.float32)
    warp = init_warp.astype(np.float32).copy()
    warp[:, 2] *= scale
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 1e-4)
    try:
        # findTransformECC maps `b` (input) onto `a` (template): same direction as our warp.
        _cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_AFFINE, criteria, None, 5)
    except cv2.error:
        return None
    if not np.all(np.isfinite(warp)):
        return None
    # Reject wild fits: keep near-identity linear part.
    linear = warp[:, :2]
    if abs(linear[0, 0] - 1.0) > 0.05 or abs(linear[1, 1] - 1.0) > 0.05 or abs(linear[0, 1]) > 0.05 or abs(linear[1, 0]) > 0.05:
        return None
    warp = warp.copy()
    warp[:, 2] /= scale
    return warp


# --------------------------------------------------------------------------- #
# Preparation
# --------------------------------------------------------------------------- #


def _prepare_pair(prev_img: np.ndarray, cur_img: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    prev_bgr = _to_bgr(prev_img)
    cur_bgr = _to_bgr(cur_img)
    h = min(prev_bgr.shape[0], cur_bgr.shape[0], MAX_COMPARE_H)
    w = min(prev_bgr.shape[1], cur_bgr.shape[1], MAX_COMPARE_W)
    if h <= 0 or w <= 0:
        return prev_bgr, cur_bgr
    if prev_bgr.shape[0] != h or prev_bgr.shape[1] != w:
        prev_bgr = cv2.resize(prev_bgr, (w, h), interpolation=cv2.INTER_AREA)
    if cur_bgr.shape[0] != h or cur_bgr.shape[1] != w:
        cur_bgr = cv2.resize(cur_bgr, (w, h), interpolation=cv2.INTER_AREA)
    return prev_bgr, cur_bgr


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    smoothed = cv2.GaussianBlur(gray, (3, 3), 0)
    ink = cv2.adaptiveThreshold(
        smoothed,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        9,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)


def _remove_staff_lines(ink: np.ndarray, *, gap: float) -> np.ndarray:
    """Drop staff lines: rows that are inked across most of the width, plus any
    remaining horizontal run long enough to be a staff line (beams are shorter).
    Both frames lose the same rows, so the comparison is unaffected."""
    h, w = ink.shape[:2]
    if h < 8 or w < 24:
        return ink
    row_density = (ink > 0).sum(axis=1).astype(np.float32) / float(w)
    threshold = max(0.2, float(np.percentile(row_density, 97)) * 0.45)
    line_rows = row_density >= threshold
    cleaned = ink.copy()
    if line_rows.any():
        cleaned[line_rows, :] = 0
    run = int(max(24, round(w * 0.12)))
    if run < w:
        lines = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (run, 1)))
        if cv2.countNonZero(lines) > 0:
            cleaned = cv2.bitwise_and(cleaned, cv2.bitwise_not(lines))
    return cleaned


def _fallback_staff_gap(h: int, w: int) -> float:
    # Full page: ~6 systems of 5 lines -> gap ~ h/48. Strip: one system -> gap ~ h/9.
    if h < w * 0.45:
        return float(np.clip(h / 9.0, 4.0, 40.0))
    return float(np.clip(h / 48.0, 4.0, 30.0))


def estimate_staff_gap(ink: np.ndarray) -> float:
    """Median distance between adjacent staff lines, in pixels (0 when not found)."""
    h, w = ink.shape[:2]
    if h < 16 or w < 16:
        return 0.0
    row_density = (ink > 0).sum(axis=1).astype(np.float32) / float(w)
    if row_density.max() <= 0:
        return 0.0
    # Staff lines run across most of the width; notes/text do not.
    threshold = max(0.25, float(np.percentile(row_density, 97)) * 0.55)
    active = row_density >= threshold
    centers: List[float] = []
    y = 0
    while y < h:
        if active[y]:
            start = y
            while y < h and active[y]:
                y += 1
            centers.append((start + y - 1) / 2.0)
        else:
            y += 1
    if len(centers) < 3:
        return 0.0
    diffs = np.diff(np.asarray(centers, dtype=np.float32))
    plausible = diffs[(diffs >= 3.0) & (diffs <= max(6.0, h / 6.0))]
    if plausible.size < 2:
        return 0.0
    # Staff gaps repeat 4 times per system; take the mode of the rounded diffs.
    rounded = np.round(plausible).astype(np.int32)
    values, counts = np.unique(rounded, return_counts=True)
    best = int(values[int(np.argmax(counts))])
    if counts.max() < 2:
        return float(np.median(plausible))
    near = plausible[np.abs(plausible - best) <= 1.5]
    return float(np.median(near)) if near.size else float(best)


# --------------------------------------------------------------------------- #
# Overlay (playhead / highlight / progress bar) detection
# --------------------------------------------------------------------------- #


def _overlay_mask(bgr: np.ndarray, ink_no_staff: np.ndarray, *, gap: float) -> Tuple[np.ndarray, Optional[float]]:
    """Return (mask of playback overlays, x-centre of the playhead if one is visible).

    Colored structures are analysed on their own so that they never merge with
    the (black) score ink; gray playheads are only accepted when they are clearly
    taller than a staff system, which no bar line or stem is.
    """
    h, w = ink_no_staff.shape[:2]
    overlay = np.zeros((h, w), dtype=np.uint8)
    cursor_x: Optional[float] = None
    cursor_score = 0.0

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    colored = ((hsv[:, :, 1] >= 60) & (hsv[:, :, 2] >= 50)).astype(np.uint8) * 255
    close_h = int(max(3, round(gap * 1.6)))
    vertical_close = cv2.getStructuringElement(cv2.MORPH_RECT, (1, close_h))

    if cv2.countNonZero(colored) > 0:
        closed = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, vertical_close)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
        for idx in range(1, count):
            x, y, bw, bh, _area = stats[idx]
            if bw <= 0 or bh <= 0:
                continue
            comp = labels[y : y + bh, x : x + bw] == idx
            pixels = int(np.count_nonzero(comp))
            tall_band = bh >= 2.5 * gap and bh >= 2.5 * bw
            wide_bar = bw >= 0.3 * w and bh <= max(6.0, 0.8 * gap)
            big_box = (bw * bh) >= 3.0 * gap * gap and pixels >= 0.4 * bw * bh
            if not (tall_band or wide_bar or big_box):
                # Small colored specks: colored note heads or chroma noise, keep as ink.
                continue
            overlay[y : y + bh, x : x + bw][comp] = 255
            if tall_band or big_box:
                score = float(bh) * (2.0 if tall_band else 1.0)
                if score > cursor_score:
                    cursor_score = score
                    cursor_x = x + bw / 2.0

    # Gray playhead: a solid vertical band, thicker than a stem and taller than
    # a stem (bar lines are one system tall, stems about six gaps).
    closed_ink = cv2.morphologyEx(ink_no_staff, cv2.MORPH_CLOSE, vertical_close)
    for x0, x1, y0, y1 in _tall_column_bands(closed_ink, gap=gap):
        band = ink_no_staff[y0:y1, x0:x1]
        fill = float(cv2.countNonZero(band)) / float(max(1, band.size))
        if fill < 0.5:
            continue
        overlay[y0:y1, x0:x1] = 255
        score = float(y1 - y0)
        if score > cursor_score:
            cursor_score = score
            cursor_x = (x0 + x1) / 2.0

    return overlay, cursor_x


def _tall_column_bands(mask: np.ndarray, *, gap: float) -> List[Tuple[int, int, int, int]]:
    """Column ranges whose longest vertical ink run exceeds a staff system height."""
    h, w = mask.shape[:2]
    binary = mask > 0
    rows = np.arange(h, dtype=np.int32)[:, None]
    # Row index of the most recent background pixel above each position.
    last_background = np.maximum.accumulate(np.where(binary, -1, rows), axis=0)
    run_lengths = np.where(binary, rows - last_background, 0)
    best = run_lengths.max(axis=0)
    best_end = run_lengths.argmax(axis=0)
    min_run = 7.0 * gap
    tall = best >= min_run
    min_width = max(4, int(round(gap * 0.35)))
    max_width = max(6.0, 1.6 * gap)
    bands: List[Tuple[int, int, int, int]] = []
    x = 0
    while x < w:
        if not tall[x]:
            x += 1
            continue
        start = x
        while x < w and tall[x]:
            x += 1
        width = x - start
        if width < min_width or width > max_width:
            continue
        y1 = int(best_end[start:x].max()) + 1
        y0 = max(0, y1 - int(best[start:x].max()))
        bands.append((start, x, y0, y1))
    return bands


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #


def _estimate_translation(
    prev_gray: np.ndarray,
    cur_gray: np.ndarray,
    prev_overlay: np.ndarray,
    cur_overlay: np.ndarray,
) -> Tuple[float, float, float]:
    h, w = prev_gray.shape[:2]
    # Half resolution is plenty: the diff tolerates 1-3 px and the DFT is 4x cheaper.
    scale = 0.5 if min(h, w) >= 160 else 1.0
    if scale != 1.0:
        size = (int(w * scale), int(h * scale))
        a = cv2.resize(prev_gray, size, interpolation=cv2.INTER_AREA).astype(np.float32)
        b = cv2.resize(cur_gray, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    else:
        a = prev_gray.astype(np.float32)
        b = cur_gray.astype(np.float32)
    # Overlays are deliberately left in place: painting them out plants
    # artificial structure that phase correlation locks onto. The score ink
    # dominates the spectrum, so a moving playhead barely shifts the peak.
    a -= float(a.mean())
    b -= float(b.mean())
    if float(a.std()) < 1e-4 or float(b.std()) < 1e-4:
        return 0.0, 0.0, 0.0
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    if not (np.isfinite(dx) and np.isfinite(dy)):
        return 0.0, 0.0, 0.0
    confidence = float(np.clip((float(response) - 0.05) / 0.6, 0.0, 1.0))
    return float(dx) / scale, float(dy) / scale, confidence


def _warp_to_prev(
    cur_ink: np.ndarray,
    cur_overlay: np.ndarray,
    warp: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, Tuple[int, int, int, int]]:
    """Warp `cur` onto `prev`'s pixel grid; return the crop window fully covered by `cur`."""
    h, w = cur_ink.shape[:2]
    is_translation = abs(warp[0, 0] - 1.0) < 1e-6 and abs(warp[1, 1] - 1.0) < 1e-6 and abs(warp[0, 1]) < 1e-6 and abs(warp[1, 0]) < 1e-6
    if is_translation:
        dx = int(round(-warp[0, 2]))
        dy = int(round(-warp[1, 2]))
        if dx == 0 and dy == 0:
            return cur_ink, cur_overlay, (0, h, 0, w)
        matrix = np.array([[1.0, 0.0, -dx], [0.0, 1.0, -dy]], dtype=np.float32)
        aligned_ink = cv2.warpAffine(cur_ink, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        aligned_overlay = cv2.warpAffine(cur_overlay, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        return aligned_ink, aligned_overlay, (max(0, -dy), min(h, h - dy), max(0, -dx), min(w, w - dx))

    matrix = warp.astype(np.float32)
    aligned_ink = cv2.warpAffine(cur_ink, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    aligned_overlay = cv2.warpAffine(cur_overlay, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    coverage = cv2.warpAffine(np.full((h, w), 255, dtype=np.uint8), matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    rows = np.where(coverage.min(axis=1) > 0)[0]
    cols = np.where(coverage.min(axis=0) > 0)[0]
    if rows.size == 0 or cols.size == 0:
        return aligned_ink, aligned_overlay, (0, 0, 0, 0)
    # Largest window whose rows and columns are fully covered.
    return aligned_ink, aligned_overlay, (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)


# --------------------------------------------------------------------------- #
# Change extraction
# --------------------------------------------------------------------------- #


def _tolerant_xor(a: np.ndarray, b: np.ndarray, *, radius: int) -> np.ndarray:
    """Ink present in one mask and absent from the other, ignoring `radius` px of jitter/blur."""
    size = 2 * int(radius) + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    a_grown = cv2.dilate(a, kernel)
    b_grown = cv2.dilate(b, kernel)
    only_a = cv2.bitwise_and(a, cv2.bitwise_not(b_grown))
    only_b = cv2.bitwise_and(b, cv2.bitwise_not(a_grown))
    change = cv2.bitwise_or(only_a, only_b)
    # Remove 1px specks left by anti-aliasing.
    return cv2.morphologyEx(change, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))


def _classify_change_blobs(
    change: np.ndarray,
    *,
    gap: float,
    sensitivity: DiffSensitivity,
) -> Tuple[int, int, int, List[Tuple[int, int, int, int]]]:
    if cv2.countNonZero(change) == 0:
        return 0, 0, 0, []

    # Merge the parts of one changed symbol (head + stem, broken beams) and
    # re-join vertical lines that staff-line removal cut into short pieces, so
    # that a playhead/stem residue is seen as one tall sliver, not many blobs.
    merge_w = int(max(2, round(gap * 0.35)))
    merge_h = int(max(3, round(gap * 0.6)))
    merged = cv2.morphologyEx(change, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (merge_w, merge_h)))
    tall_join = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(max(3, round(gap * 1.2)))))
    merged = cv2.morphologyEx(merged, cv2.MORPH_CLOSE, tall_join)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)

    gap_area = float(gap * gap)
    significant = 0
    minor = 0
    overlay_like = 0
    boxes: List[Tuple[int, int, int, int]] = []
    change_bool = change > 0
    for idx in range(1, count):
        x, y, bw, bh, _area = stats[idx]
        comp = labels[y : y + bh, x : x + bw] == idx
        ink_pixels = int(np.count_nonzero(change_bool[y : y + bh, x : x + bw] & comp))
        if ink_pixels <= 0:
            continue
        area_gaps = ink_pixels / gap_area
        min_dim_gaps = min(bw, bh) / gap

        # Thin slivers are not note changes: vertical ones are playheads, stems
        # and bar lines; horizontal ones are residual staff lines and box edges.
        # A short, thick horizontal sliver can be a beam, which is kept as minor.
        aspect = max(bw, bh) / float(max(1, min(bw, bh)))
        if aspect >= 6.0 and min_dim_gaps < 0.6:
            horizontal = bw > bh
            beam_like = horizontal and 1.5 * gap <= bw <= 0.12 * change.shape[1] and bh >= 0.15 * gap
            if not beam_like:
                overlay_like += 1
                continue
            minor += 1
            boxes.append((int(x), int(y), int(bw), int(bh)))
            continue

        if area_gaps >= sensitivity.significant_area and min_dim_gaps >= sensitivity.significant_min_dim:
            significant += 1
            boxes.append((int(x), int(y), int(bw), int(bh)))
        elif area_gaps >= sensitivity.minor_area and min_dim_gaps >= sensitivity.minor_min_dim:
            minor += 1
            boxes.append((int(x), int(y), int(bw), int(bh)))

    return significant, minor, overlay_like, boxes
