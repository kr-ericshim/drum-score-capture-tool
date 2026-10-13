"""Full notation envelope and ROI clipping checks from full source frames.

Design reference: docs/archive/reflow/DESIGN_astra.md section 3 "Full notation
envelope" (steps 1-8) and the ``ENVELOPE_CLIPPED`` state in section 2.

Why: the automatic ROI used a fixed 4.5 staff-gap padding and ROI health only
looked at aggregate edge density in three nearby frames. Open hi-hat circles
above the staff, lyrics below it, tempo marks and boxed section labels were
cut off by the applied ROI (calibration GT: 310 of 450 protected marks lost).

What this module does, per sampled full source frame:

1. Detect five-line staves on the full frame in both polarities (dark ink on
   light paper and light ink on dark paper) with a local (adaptive) ink cut and
   the ported ``system_detect.find_staves``. Candidates are kept when their
   line rows are thin and contrast with the spaces between them.
2. Group staves into screen rows. For each row estimate its paper tone and an
   ink threshold from the staff itself, and find the score panel around it:
   rows/columns stop at a run of pixels that are neither paper nor ink (video
   footage, colored UI). The panel bounds the search so video content beside
   a bottom bar is not taken as notation.
3. Search from ``top - 8g`` to ``bottom + 8g`` (bounded by the panel and halfway
   to neighbouring rows) on a staff-suppressed ink mask. Components that reach
   the staff are seeds; every other component of plausible size fully inside
   the search window is kept as attached notation or score text (marks,
   circles, accents, text lines, lyrics, boxed labels). Components within
   0.75g of a kept one are chained in, also beyond the window (still inside
   the panel), e.g. a tempo mark resting on an accent row.
4. Text-like components beyond the window but inside the panel are kept and
   flagged ``ambiguous_owner`` (step 8: when ownership is unclear, keep more).
   Large blobs, page-wide rules and anything outside the panel are not.
5. The envelope of a source is the union over sampled frames, padded by 0.75g
   top/bottom and 0.5g at the sides, and clamped to panel edges that stopped at
   video/UI content. A panel (or frame) edge within 3g of the padded envelope
   is taken in whole, so content of systems that no sample showed but that sits
   in the same panel is kept.

``check_roi_clipping`` (step 7) reports every content-bearing component of a
row that the applied ROI cuts or that lies within 0.25g of an ROI edge, and
every consistent staff row outside the ROI. It does not use aggregate density.

Coordinates are source-frame pixels; boxes are half-open ``[x0, y0, x1, y1]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import system_detect as sd

ENVELOPE_VERSION = "notation_envelope-1"
MAX_SAMPLES = 12
SEARCH_GAPS = 8.0  # step 3: top-8g .. bottom+8g
EXTENDED_GAPS = 14.0  # chaining / ambiguous-text reach beyond the window
CHAIN_GAPS = 0.75
PAD_VERTICAL_GAPS = 0.75  # step 6
PAD_SIDE_GAPS = 0.5
CLIP_MARGIN_GAPS = 0.25  # step 7
PANEL_SNAP_GAPS = 3.0
ENVELOPE_CLIPPED = "ENVELOPE_CLIPPED"


# --------------------------------------------------------------------------- #
# Sampling
# --------------------------------------------------------------------------- #


def sample_times(duration_sec: float, count: int = MAX_SAMPLES, *, start_sec: float = 0.0,
                 end_sec: Optional[float] = None) -> List[float]:
    """Up to ``count`` evenly spaced times (bin centres) in ``[start, end)``."""
    end = float(duration_sec if end_sec is None else min(end_sec, duration_sec or end_sec))
    start = max(0.0, float(start_sec or 0.0))
    if not np.isfinite(end) or end <= start:
        return [round(start, 3)]
    n = max(1, int(count))
    span = end - start
    return [round(start + span * (i + 0.5) / n, 3) for i in range(n)]


def read_frames_cv2(path: str, times: Sequence[float], should_stop=None) -> List[Tuple[float, np.ndarray]]:
    """Decode frames at ``times`` by seeking (in memory, nothing written). ``should_stop``
    (optional callable) is checked before each frame; decoding stops when it returns True."""
    cap = cv2.VideoCapture(str(path))
    out: List[Tuple[float, np.ndarray]] = []
    if not cap.isOpened():
        return out
    try:
        for t in times:
            if should_stop is not None and should_stop():
                break
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t)) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                out.append((float(t), frame))
    finally:
        cap.release()
    return out


def video_duration_cv2(path: str) -> float:
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return 0.0
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        return count / fps if fps > 0 else 0.0
    finally:
        cap.release()


# --------------------------------------------------------------------------- #
# Step 1: staves on the full frame, both polarities
# --------------------------------------------------------------------------- #


POLARITIES = ("dark_on_light", "light_on_dark")


def _polarity_gray(gray: np.ndarray, polarity: str) -> np.ndarray:
    return gray if polarity == "dark_on_light" else 255 - gray


def _adaptive_ink(g: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(g, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)


def _line_stats(g: np.ndarray, lines: Sequence[float], gap: float, x0: int, x1: int) -> Tuple[float, float, float]:
    """(median line tone, median space tone, contrast) sampled across the staff."""
    h, w = g.shape
    cols = np.linspace(max(0, x0), min(w - 1, x1), num=min(400, max(8, x1 - x0)), dtype=int)
    line_vals = []
    for y in lines:
        r = int(round(y))
        if 0 <= r < h:
            # darkest of the 3 rows around the nominal line row, per column
            lo, hi = max(0, r - 1), min(h, r + 2)
            line_vals.append(g[lo:hi, cols].min(axis=0))
    space_vals = []
    for a, b in zip(lines[:-1], lines[1:]):
        r = int(round((a + b) / 2.0))
        if 0 <= r < h:
            space_vals.append(g[r, cols])
    if not line_vals or not space_vals:
        return 0.0, 0.0, 0.0
    line_tone = float(np.median(np.concatenate(line_vals)))
    space_tone = float(np.median(np.concatenate(space_vals)))
    return line_tone, space_tone, space_tone - line_tone


def detect_staves(frame: np.ndarray, *, min_width_gaps: float = 8.0, min_gap: float = 3.0,
                  max_gap: float = 48.0) -> List[Dict[str, Any]]:
    """Five-line staff segments on a full BGR frame, polarity-tagged.

    Each staff: ``lines`` (5 row positions), ``gap``, ``thick``, ``x`` [x0, x1]
    (inclusive), ``polarity``, ``paper`` and ``line_tone`` (in the polarity's
    gray, where paper is light), ``contrast``.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    found: List[Dict[str, Any]] = []
    for polarity in POLARITIES:
        g = _polarity_gray(gray, polarity)
        ink = _adaptive_ink(g)
        for st in sd.find_staves(ink):
            x0, x1 = int(st["x"][0]), int(st["x"][1])
            gap = float(st["gap"])
            if not (min_gap <= gap <= max_gap):
                continue
            if x1 - x0 < min_width_gaps * gap:
                continue
            # Spaces between real lines are thick; thin "lines" only.
            if float(st["thick"]) > max(3.0, 0.35 * gap):
                continue
            line_tone, paper, contrast = _line_stats(g, st["lines"], gap, x0, x1)
            if contrast < 40.0:
                continue
            found.append({
                "lines": [float(y) for y in st["lines"]],
                "gap": gap,
                "thick": float(st["thick"]),
                "x": [x0, x1],
                "polarity": polarity,
                "paper": paper,
                "line_tone": line_tone,
                "contrast": contrast,
            })
    # The same staff can be found in both polarities (or a polarity can find
    # the spaces of a staff): keep the stronger, thinner-lined candidate.
    found.sort(key=lambda s: (-s["contrast"], s["thick"]))
    kept: List[Dict[str, Any]] = []
    for st in found:
        clash = False
        for k in kept:
            g = max(st["gap"], k["gap"])
            v_overlap = min(st["lines"][4], k["lines"][4]) - max(st["lines"][0], k["lines"][0])
            h_overlap = min(st["x"][1], k["x"][1]) - max(st["x"][0], k["x"][0])
            shorter = max(1, min(st["x"][1] - st["x"][0], k["x"][1] - k["x"][0]))
            if v_overlap > -0.5 * g and h_overlap > 0.3 * shorter:
                clash = True
                break
        if not clash:
            kept.append(st)
    return sorted(kept, key=lambda s: (s["lines"][0], s["x"][0]))


def group_rows(staves: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    rows: List[List[Dict[str, Any]]] = []
    for st in sorted(staves, key=lambda s: (s["lines"][0], s["x"][0])):
        if rows and abs(rows[-1][0]["lines"][0] - st["lines"][0]) < 1.5 * st["gap"] \
                and rows[-1][0]["polarity"] == st["polarity"]:
            rows[-1].append(st)
        else:
            rows.append([st])
    return rows


# --------------------------------------------------------------------------- #
# Step 2: score panel around a row
# --------------------------------------------------------------------------- #


@dataclass
class _Tones:
    paper: float
    ink_thr: float
    paper_tol: float


def _row_tones(main: Dict[str, Any]) -> _Tones:
    paper = float(main["paper"])
    line = float(main["line_tone"])
    spread = max(1.0, paper - line)
    return _Tones(paper=paper, ink_thr=line + 0.55 * spread, paper_tol=max(22.0, 0.22 * spread))


def _score_like(values: np.ndarray, tones: _Tones, axis: int) -> np.ndarray:
    """Per-row (axis=1) or per-column (axis=0) "paper or ink" verdict."""
    paper = np.abs(values.astype(np.float32) - tones.paper) <= tones.paper_tol
    ink = values <= tones.ink_thr
    pf = paper.mean(axis=axis)
    inf = ink.mean(axis=axis)
    return (pf + inf >= 0.8) & (pf >= 0.3)


def _scan_extent(flags: np.ndarray, start: int, step: int, limit: int, run: int) -> Tuple[int, bool]:
    """Walk from ``start`` by ``step`` until ``run`` consecutive False flags.

    Returns (last score-like index reached, stopped_by_content) where the
    second value is True when a non-score run stopped the walk (a panel edge)
    and False when the walk hit ``limit`` (frame edge or search limit).
    """
    last = start
    misses = 0
    i = start
    while (step > 0 and i < limit) or (step < 0 and i > limit):
        if flags[i]:
            last = i
            misses = 0
        else:
            misses += 1
            if misses >= run:
                return last, True
        i += step
    return last, False


def row_panel(g: np.ndarray, row: Sequence[Dict[str, Any]], tones: _Tones, *, reach_gaps: float = EXTENDED_GAPS) -> Dict[str, Any]:
    """Vertical and horizontal extent of the paper/score panel around a row."""
    h, w = g.shape
    gap = float(np.median([s["gap"] for s in row]))
    top = min(s["lines"][0] for s in row)
    bot = max(s["lines"][4] for s in row)
    x_lo = min(s["x"][0] for s in row)
    x_hi = max(s["x"][1] for s in row) + 1
    run = max(2, int(round(0.25 * gap)))
    cols = g[:, x_lo:x_hi]
    row_flags = _score_like(cols, tones, axis=1)
    y_top_lim = max(-1, int(np.floor(top - reach_gaps * gap)) - 1)
    y_bot_lim = min(h, int(np.ceil(bot + reach_gaps * gap)) + 1)
    p_top, top_edge = _scan_extent(row_flags, int(np.floor(top)), -1, y_top_lim, run)
    p_bot, bot_edge = _scan_extent(row_flags, int(np.ceil(bot)), 1, y_bot_lim, run)
    # Columns: judged on the staff band itself (+-2g), where a panel edge is
    # clearest.
    yb0 = max(p_top, int(np.floor(top - 2 * gap)))
    yb1 = min(p_bot + 1, int(np.ceil(bot + 2 * gap)) + 1)
    col_flags = _score_like(g[yb0:yb1, :], tones, axis=0)
    x_left_lim = max(-1, int(np.floor(x_lo - reach_gaps * gap)) - 1)
    x_right_lim = min(w, int(np.ceil(x_hi + reach_gaps * gap)) + 1)
    p_left, left_edge = _scan_extent(col_flags, x_lo, -1, x_left_lim, run)
    p_right, right_edge = _scan_extent(col_flags, x_hi - 1, 1, x_right_lim, run)
    return {
        "bbox": [int(p_left), int(p_top), int(p_right) + 1, int(p_bot) + 1],
        "bounded": {"top": top_edge, "bottom": bot_edge, "left": left_edge, "right": right_edge},
    }


# --------------------------------------------------------------------------- #
# Steps 3-5, 8: attached notation and score text of one row
# --------------------------------------------------------------------------- #


def _chain(boxes: np.ndarray, inc: np.ndarray, allowed: np.ndarray, reach: float, max_iter: int = 30) -> np.ndarray:
    inc = inc.copy()
    for _ in range(max_iter):
        cand = np.flatnonzero(allowed & ~inc)
        if not cand.size or not inc.any():
            break
        cur = boxes[inc]
        b = boxes[cand]
        dy = np.maximum(0.0, np.maximum(cur[None, :, 1] - b[:, None, 3], b[:, None, 1] - cur[None, :, 3]))
        dx = np.maximum(0.0, np.maximum(cur[None, :, 0] - b[:, None, 2], b[:, None, 0] - cur[None, :, 2]))
        hit = np.any((dy <= reach) & (dx <= reach), axis=1)
        if not hit.any():
            break
        inc[cand[hit]] = True
    return inc


def _text_lines(boxes: np.ndarray, cand: np.ndarray) -> np.ndarray:
    """Candidates that sit on a horizontal line with at least one similar neighbour."""
    out = np.zeros(len(boxes), dtype=bool)
    idx = np.flatnonzero(cand)
    if idx.size < 2:
        return out
    b = boxes[idx]
    hgt = b[:, 3] - b[:, 1]
    for i in range(len(idx)):
        ov = np.minimum(b[i, 3], b[:, 3]) - np.maximum(b[i, 1], b[:, 1])
        small = np.minimum(hgt[i], hgt)
        dx = np.maximum(0.0, np.maximum(b[:, 0] - b[i, 2], b[i, 0] - b[:, 2]))
        ratio = np.maximum(hgt[i], hgt) / np.maximum(1.0, small)
        ok = (ov >= 0.5 * small) & (dx <= 2.0 * np.maximum(hgt[i], hgt)) & (ratio <= 2.5)
        ok[i] = False
        if ok.any():
            out[idx[i]] = True
    return out


def row_envelope(gray: np.ndarray, row: Sequence[Dict[str, Any]], *, band: Tuple[float, float],
                 all_staves: Sequence[Dict[str, Any]] = (), sat: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Envelope of one staff row on a full frame.

    ``band`` is the vertical range this row owns (halfway to neighbouring rows,
    or the frame). Returns staff geometry, ``panel``, ``envelope_bbox``,
    ``components`` (kept content boxes with a ``kind``), ``flags``.
    """
    main = max(row, key=lambda s: s["x"][1] - s["x"][0])
    polarity = main["polarity"]
    g = _polarity_gray(gray, polarity)
    h, w = g.shape
    gap = float(np.median([s["gap"] for s in row]))
    top = min(s["lines"][0] for s in row)
    bot = max(s["lines"][4] for s in row)
    x_lo = min(s["x"][0] for s in row)
    x_hi = max(s["x"][1] for s in row) + 1
    tones = _row_tones(main)
    panel = row_panel(g, row, tones)
    px0, py0, px1, py1 = panel["bbox"]

    # Extended region: the panel within EXTENDED_GAPS, inside the owned band.
    ey0 = int(max(py0, band[0], np.floor(top - EXTENDED_GAPS * gap), 0))
    ey1 = int(min(py1, band[1], np.ceil(bot + EXTENDED_GAPS * gap), h))
    ex0 = int(max(px0, np.floor(x_lo - EXTENDED_GAPS * gap), 0))
    ex1 = int(min(px1, np.ceil(x_hi + EXTENDED_GAPS * gap), w))
    # Search window (step 3).
    wy0 = max(ey0, int(np.floor(top - SEARCH_GAPS * gap)))
    wy1 = min(ey1, int(np.ceil(bot + SEARCH_GAPS * gap)))
    wx0 = max(ex0, int(np.floor(x_lo - SEARCH_GAPS * gap)))
    wx1 = min(ex1, int(np.ceil(x_hi + SEARCH_GAPS * gap)))

    base = [int(x_lo), int(np.floor(top - main["thick"])), int(x_hi), int(np.ceil(bot + main["thick"])) + 1]
    result: Dict[str, Any] = {
        "polarity": polarity,
        "staff_gap_px": round(gap, 3),
        "staff_y": [round(y, 2) for y in main["lines"]],
        "staff_x": [int(x_lo), int(x_hi)],
        "segments": [[int(s["x"][0]), int(s["x"][1]) + 1] for s in row],
        "panel": panel["bbox"],
        "panel_bounded": panel["bounded"],
        "search_window": [wx0, wy0, wx1, wy1],
        "components": [],
        "flags": [],
    }
    if ey1 - ey0 < 3 or ex1 - ex0 < 3:
        result["envelope_bbox"] = base
        return result

    sub = g[ey0:ey1, ex0:ex1]
    ink = (sub <= tones.ink_thr).astype(np.uint8)
    # Analysis-only staff suppression (step 4), for every staff in the region.
    for st in all_staves:
        if st["polarity"] != polarity:
            continue
        half = st["thick"] / 2.0 + 1.0
        sx0 = max(0, st["x"][0] - ex0 - 1)
        sx1 = min(ex1 - ex0, st["x"][1] - ex0 + 2)
        if sx1 <= 0 or sx0 >= ex1 - ex0:
            continue
        for y in st["lines"]:
            r0 = int(np.floor(y - half)) - ey0
            r1 = int(np.ceil(y + half)) + 1 - ey0
            r0, r1 = max(0, r0), min(ey1 - ey0, r1)
            if r1 > r0:
                ink[r0:r1, sx0:sx1] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if count <= 1:
        result["envelope_bbox"] = base
        return result
    st_ = stats[1:]
    boxes = np.stack([st_[:, 0] + ex0, st_[:, 1] + ey0, st_[:, 0] + st_[:, 2] + ex0, st_[:, 1] + st_[:, 3] + ey0], axis=1).astype(np.float64)
    bw = st_[:, 2].astype(np.float64)
    bh = st_[:, 3].astype(np.float64)
    area = st_[:, 4].astype(np.float64)
    min_area = max(4.0, 0.012 * gap * gap)
    noise = area < min_area
    staff_w = float(x_hi - x_lo)
    rule = (bw >= 0.85 * staff_w) & (bh <= max(3.0, 0.3 * gap))
    # Blobs that cannot be a glyph, word or notation group: video/UI.
    foreign = (bh > 6.5 * gap) | ((bh > 3.0 * gap) & (bw > 12.0 * gap) & (area > 0.45 * bw * bh))
    seed = (boxes[:, 3] >= top - 0.5 * gap) & (boxes[:, 1] <= bot + 0.5 * gap) \
        & (boxes[:, 2] >= x_lo - gap) & (boxes[:, 0] <= x_hi + gap)
    inside = (boxes[:, 0] >= wx0) & (boxes[:, 2] <= wx1) & (boxes[:, 1] >= wy0) & (boxes[:, 3] <= wy1)
    # Components touching a panel edge that stopped at video content belong to
    # that content, not to the score.
    touches_video = np.zeros(len(boxes), dtype=bool)
    if panel["bounded"]["top"]:
        touches_video |= boxes[:, 1] <= py0
    if panel["bounded"]["bottom"]:
        touches_video |= boxes[:, 3] >= py1
    # Printed glyphs reach full ink somewhere and are neutral in color; video
    # texture over a dark or light background (drum heads, skin, shirts) mostly
    # stays mid-tone or colored. Both are measured per component.
    spread = max(1.0, tones.paper - float(main["line_tone"]))
    strong = sub <= float(main["line_tone"]) + 0.3 * spread
    flat = labels.ravel()
    strong_count = np.bincount(flat[strong.ravel()], minlength=count)[1:].astype(np.float64)
    crisp = strong_count >= np.maximum(2.0, 0.1 * area)
    if sat is not None:
        sat_sub = sat[ey0:ey1, ex0:ex1].astype(np.float64).ravel()
        mean_sat = np.bincount(flat, weights=sat_sub, minlength=count)[1:] / np.maximum(1.0, stats[1:, 4])
        neutral = mean_sat <= 70.0
    else:
        neutral = np.ones(len(boxes), dtype=bool)
    # Pieces cut by the extended-region border (not the frame edge) are parts
    # of something larger beyond the search (a logo box, video), not glyphs.
    cut = ((boxes[:, 1] <= ey0) & (ey0 > 0)) | ((boxes[:, 3] >= ey1) & (ey1 < h)) \
        | ((boxes[:, 0] <= ex0) & (ex0 > 0)) | ((boxes[:, 2] >= ex1) & (ex1 < w))
    allowed = ~noise & ~rule & ~foreign & ~(touches_video & ~seed) & (seed | (crisp & neutral & ~cut))
    inc = allowed & (seed | inside)
    inc = _chain(boxes, inc, allowed, CHAIN_GAPS * gap)
    # Step 8: text lines beyond the window but inside the panel and the owned
    # band: ownership unclear, keep and flag. A lone speck is not a text line.
    text_like = allowed & ~inc & ~cut & (bh >= 0.35 * gap) & (bh <= 3.5 * gap) & (bw <= 6.0 * bh)
    ambiguous = _text_lines(boxes, text_like)
    if ambiguous.any():
        inc = _chain(boxes, inc | ambiguous, allowed, CHAIN_GAPS * gap)
        result["flags"].append("ambiguous_owner")

    env = list(base)
    comps = []
    for k in np.flatnonzero(inc):
        b = [int(v) for v in boxes[k]]
        env = [min(env[0], b[0]), min(env[1], b[1]), max(env[2], b[2]), max(env[3], b[3])]
        if seed[k]:
            kind = "staff_attached"
        elif ambiguous[k]:
            kind = "ambiguous"
        elif inside[k]:
            kind = "mark_or_text"
        else:
            kind = "chained"
        comps.append({"bbox": b, "kind": kind, "area": int(area[k])})
    env = [max(0, env[0]), max(0, env[1]), min(w, env[2]), min(h, env[3])]
    result["envelope_bbox"] = env
    result["components"] = comps
    if env[1] <= int(round(CLIP_MARGIN_GAPS * gap)):
        result["flags"].append("frame_edge_top")
    if env[3] >= h - int(round(CLIP_MARGIN_GAPS * gap)):
        result["flags"].append("frame_edge_bottom")
    if any(c["kind"] == "chained" for c in comps):
        result["flags"].append("beyond_search_window")
    return result


def frame_envelope(frame: np.ndarray, *, staves: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Rows, envelopes and panels of one full source frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    sat = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 1] if frame.ndim == 3 else None
    h, w = gray.shape
    staves = detect_staves(frame) if staves is None else staves
    rows = group_rows(staves)
    out_rows = []
    for i, row in enumerate(rows):
        top = min(s["lines"][0] for s in row)
        bot = max(s["lines"][4] for s in row)
        prev_bot = max(s["lines"][4] for s in rows[i - 1]) if i else None
        next_top = min(s["lines"][0] for s in rows[i + 1]) if i + 1 < len(rows) else None
        band = ((prev_bot + top) / 2.0 if prev_bot is not None else 0.0,
                (bot + next_top) / 2.0 if next_top is not None else float(h))
        out_rows.append(row_envelope(gray, row, band=band, all_staves=staves, sat=sat))
    return {"size": [int(w), int(h)], "rows": out_rows}


# --------------------------------------------------------------------------- #
# Source-level envelope (union over sampled frames)
# --------------------------------------------------------------------------- #


def _consistent_rows(frames: Sequence[Dict[str, Any]]) -> Tuple[List[Tuple[int, Dict[str, Any]]], float, str]:
    """Rows whose staff gap and polarity agree with the source majority.

    A non-score frame (end card, title) can produce a stray "staff"; a
    preview box can show a smaller staff. Rows whose gap differs from the
    median gap by more than 20% or whose polarity is the minority are dropped.
    """
    items = [(fi, r) for fi, fr in enumerate(frames) for r in fr["rows"]]
    if not items:
        return [], 0.0, ""
    polarities = [r["polarity"] for _, r in items]
    polarity = max(set(polarities), key=polarities.count)
    gaps = np.array([r["staff_gap_px"] for _, r in items if r["polarity"] == polarity], dtype=np.float64)
    gap = float(np.median(gaps)) if gaps.size else 0.0
    keep = [(fi, r) for fi, r in items
            if r["polarity"] == polarity and gap > 0 and abs(r["staff_gap_px"] - gap) <= 0.2 * gap]
    return keep, gap, polarity


def _union(boxes: Iterable[Sequence[int]]) -> Optional[List[int]]:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def build_envelope(samples: Sequence[Tuple[float, np.ndarray]]) -> Dict[str, Any]:
    """Union notation envelope of a source from ``(t_sec, frame)`` samples.

    Returns ``status`` ("found" / "no_staff"), ``envelope_bbox`` (unpadded),
    ``suggested_bbox`` (padded, clamped to the panels and frame), ``gap``,
    ``polarity``, ``sampled_times``, ``score_times`` (frames with a consistent
    staff), ``skipped_times`` (non-score frames), per-frame ``frames`` evidence
    (row envelopes, panels, flags; components omitted) and ``flags``.
    """
    analysed: List[Dict[str, Any]] = []
    times: List[float] = []
    size = None
    for t, frame in samples:
        if frame is None or not getattr(frame, "size", 0):
            continue
        fr = frame_envelope(frame)
        fr["t_sec"] = round(float(t), 3)
        analysed.append(fr)
        times.append(round(float(t), 3))
        size = fr["size"]
    base = {
        "version": ENVELOPE_VERSION,
        "sampled_times": times,
        "score_times": [],
        "skipped_times": list(times),
        "frames": [],
        "flags": [],
    }
    if not analysed:
        return {**base, "status": "no_frames", "envelope_bbox": None, "suggested_bbox": None, "gap": 0.0, "polarity": ""}
    rows, gap, polarity = _consistent_rows(analysed)
    if not rows:
        return {**base, "status": "no_staff", "envelope_bbox": None, "suggested_bbox": None, "gap": 0.0, "polarity": "",
                "size": size}
    w, h = size
    by_frame: Dict[int, List[Dict[str, Any]]] = {}
    for fi, r in rows:
        by_frame.setdefault(fi, []).append(r)
    env = _union(r["envelope_bbox"] for _, r in rows)
    panel = _union(r["panel"] for _, r in rows)
    # Padding may extend to the frame where the paper simply continues; it is
    # limited only by panel edges that stopped at video/UI content.
    limit = [
        min((r["panel"][0] if r["panel_bounded"]["left"] else 0) for _, r in rows),
        min((r["panel"][1] if r["panel_bounded"]["top"] else 0) for _, r in rows),
        max((r["panel"][2] if r["panel_bounded"]["right"] else w) for _, r in rows),
        max((r["panel"][3] if r["panel_bounded"]["bottom"] else h) for _, r in rows),
    ]
    pad_v = PAD_VERTICAL_GAPS * gap
    pad_h = PAD_SIDE_GAPS * gap
    sug = [env[0] - pad_h, env[1] - pad_v, env[2] + pad_h, env[3] + pad_v]
    # Padding must not reach into neighbouring video/UI content: clamp to the
    # panel union where a panel edge was found, and to the frame.
    sug = [max(sug[0], limit[0]), max(sug[1], limit[1]), min(sug[2], limit[2]), min(sug[3], limit[3])]
    sug = [max(0.0, sug[0]), max(0.0, sug[1]), min(float(w), sug[2]), min(float(h), sug[3])]
    # Keep more (step 8): when the score panel (or the frame) ends within
    # PANEL_SNAP_GAPS of the padded envelope, take the rest of the panel too.
    # Twelve samples do not show every system; a label or mark seen only in
    # an unsampled system usually still sits inside the same panel.
    snap = PANEL_SNAP_GAPS * gap
    snapped = False
    for i in range(4):
        if abs(limit[i] - sug[i]) <= snap and limit[i] != sug[i]:
            sug[i] = float(limit[i])
            snapped = True
    # The envelope itself always stays inside the suggestion.
    sug = [min(sug[0], env[0]), min(sug[1], env[1]), max(sug[2], env[2]), max(sug[3], env[3])]
    flags = sorted({f for _, r in rows for f in r["flags"]} | ({"snapped_to_panel"} if snapped else set()))
    score_times = [analysed[fi]["t_sec"] for fi in sorted(by_frame)]
    frames_ev = []
    for fi in sorted(by_frame):
        frames_ev.append({
            "t_sec": analysed[fi]["t_sec"],
            "rows": [{k: v for k, v in r.items() if k != "components"} for r in by_frame[fi]],
        })
    return {
        **base,
        "status": "found",
        "size": size,
        "gap": round(gap, 3),
        "polarity": polarity,
        "envelope_bbox": [int(v) for v in env],
        "panel_bbox": [int(v) for v in panel],
        "suggested_bbox": [round(float(v), 2) for v in sug],
        "score_times": score_times,
        "skipped_times": [t for t in times if t not in score_times],
        "frames": frames_ev,
        "flags": flags,
        "_rows": rows,  # internal: full rows with components (stripped by public helpers)
    }


def public(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Envelope evidence without internal fields (JSON-safe)."""
    return {k: v for k, v in envelope.items() if not k.startswith("_")}


def bbox_to_roi(b: Sequence[float]) -> List[List[float]]:
    x0, y0, x1, y1 = [float(round(v, 2)) for v in b]
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def roi_to_bbox(roi: Sequence[Sequence[float]]) -> List[float]:
    xs = [float(p[0]) for p in roi]
    ys = [float(p[1]) for p in roi]
    return [min(xs), min(ys), max(xs), max(ys)]


# --------------------------------------------------------------------------- #
# Step 7: clipping check against an applied ROI
# --------------------------------------------------------------------------- #


def check_roi_clipping(envelope: Dict[str, Any], roi: Sequence[Sequence[float]], *,
                       max_locations: int = 40) -> Dict[str, Any]:
    """Content-bearing components cut by (or within 0.25g of) the ROI edges.

    Only rows that are consistent across the source are considered. A row
    whose staff lies outside the ROI is reported as ``staff_outside``; for
    rows that overlap the ROI every kept component is checked individually,
    so a single small circle is enough. Returns ``clipped`` (bool),
    ``locations`` (``t_sec``, ``edge``, ``bbox``, ``kind``), per-edge counts
    and the suggested ROI (the ROI grown to the envelope) when clipped.
    """
    rows = envelope.get("_rows") or []
    x0, y0, x1, y1 = roi_to_bbox(roi)
    gap = float(envelope.get("gap") or 0.0)
    fw, fh = (envelope.get("size") or [0, 0])[:2]
    # An ROI edge on the frame border cannot be moved further out; content cut
    # by the frame itself is reported by the envelope flags instead.
    open_edge = {"left": x0 > 0.5, "top": y0 > 0.5, "right": not fw or x1 < fw - 0.5, "bottom": not fh or y1 < fh - 0.5}
    locations: List[Dict[str, Any]] = []
    counts = {"top": 0, "bottom": 0, "left": 0, "right": 0, "staff_outside": 0}
    cut_counts = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    times_hit = set()
    for _fi, r in rows:
        t = r.get("_t_sec")
        g = float(r["staff_gap_px"]) or gap
        m = CLIP_MARGIN_GAPS * g
        sy0, sy1 = r["staff_y"][0], r["staff_y"][4]
        sx0, sx1 = r["staff_x"]
        h_overlap = min(sx1, x1) - max(sx0, x0)
        if h_overlap <= 0.25 * (sx1 - sx0):
            # A staff mostly beside the ROI (e.g. a separate box) is not this ROI's row.
            continue
        if sy1 < y0 or sy0 > y1:
            edge = "top" if sy1 < y0 else "bottom"
            if not open_edge[edge]:
                continue
            counts["staff_outside"] += 1
            times_hit.add(t)
            if len(locations) < max_locations:
                locations.append({"t_sec": t, "edge": edge, "kind": "staff_outside", "cut": True,
                                  "bbox": [int(sx0), int(np.floor(sy0)), int(sx1), int(np.ceil(sy1))]})
            continue
        # An ROI edge at (or beyond) a panel edge that stopped at video content
        # cannot be moved out further without taking in that content.
        pb = r["panel"]
        bounded = r["panel_bounded"]
        row_open = dict(open_edge)
        row_open["top"] = open_edge["top"] and not (bounded["top"] and y0 <= pb[1] + 1)
        row_open["bottom"] = open_edge["bottom"] and not (bounded["bottom"] and y1 >= pb[3] - 1)
        row_open["left"] = open_edge["left"] and not (bounded["left"] and x0 <= pb[0] + 1)
        row_open["right"] = open_edge["right"] and not (bounded["right"] and x1 >= pb[2] - 1)
        for c in r["components"]:
            bx0, by0, bx1, by1 = c["bbox"]
            edges = []
            if by0 < y0 + m:
                edges.append("top")
            if by1 > y1 - m:
                edges.append("bottom")
            if bx0 < x0 + m:
                edges.append("left")
            if bx1 > x1 - m:
                edges.append("right")
            # "cut": the component crosses or lies beyond the edge (lost
            # pixels), as opposed to sitting inside within the 0.25g margin.
            cut_by = {"top": by0 < y0, "bottom": by1 > y1, "left": bx0 < x0, "right": bx1 > x1}
            for edge in edges:
                if not row_open[edge]:
                    continue
                counts[edge] += 1
                if cut_by[edge]:
                    cut_counts[edge] += 1
                times_hit.add(t)
                if len(locations) < max_locations:
                    locations.append({"t_sec": t, "edge": edge, "kind": c["kind"], "bbox": list(c["bbox"]),
                                      "cut": bool(cut_by[edge])})
    clipped = any(counts[k] for k in counts)
    suggested = None
    if clipped and envelope.get("suggested_bbox"):
        s = envelope["suggested_bbox"]
        # Grow the applied ROI to cover the envelope; never shrink it.
        grown = [min(x0, s[0]), min(y0, s[1]), max(x1, s[2]), max(y1, s[3])]
        suggested = bbox_to_roi(grown)
    return {
        "code": ENVELOPE_CLIPPED if clipped else "",
        "clipped": clipped,
        "counts": counts,
        "cut_counts": cut_counts,
        "frames_with_clipping": sorted(t for t in times_hit if t is not None),
        "locations": locations,
        "suggested_roi": suggested,
    }


def analyze_samples(samples: Sequence[Tuple[float, np.ndarray]]) -> Dict[str, Any]:
    """``build_envelope`` plus per-row sample times kept for the clip check."""
    env = build_envelope(samples)
    for fi, r in env.get("_rows") or []:
        r["_t_sec"] = env["sampled_times"][fi] if fi < len(env["sampled_times"]) else None
    return env


def analyze_video(path: str, *, count: int = MAX_SAMPLES, start_sec: float = 0.0, end_sec: Optional[float] = None,
                  duration_sec: Optional[float] = None,
                  frame_reader: Optional[Callable[[Sequence[float]], List[Tuple[float, np.ndarray]]]] = None) -> Dict[str, Any]:
    """Sample up to ``count`` evenly spaced frames of a video and build its envelope."""
    duration = float(duration_sec if duration_sec else video_duration_cv2(path))
    times = sample_times(duration, count, start_sec=start_sec, end_sec=end_sec)
    reader = frame_reader or (lambda ts: read_frames_cv2(path, ts))
    samples = reader(times)
    env = analyze_samples(samples)
    env["duration_sec"] = round(duration, 3)
    return env


def analyze_source(*, source_type: str, file_path: Optional[str], youtube_url: Optional[str], workspace,
                   logger: Callable[[str], None] = lambda _m: None, count: int = MAX_SAMPLES) -> Dict[str, Any]:
    """Envelope of a prepared source, sampled over its whole duration.

    Frames are decoded in memory with OpenCV; if that fails, each sample is
    extracted with the app's FFmpeg preview path (temporary PNGs inside
    ``workspace``, which the caller removes). A YouTube URL that was not
    resolved to a local file is not downloaded here.
    """
    from pathlib import Path

    if source_type != "file" or not file_path:
        return {"version": ENVELOPE_VERSION, "status": "unavailable", "reason": "no_local_file", "sampled_times": [],
                "score_times": [], "skipped_times": [], "frames": [], "flags": [], "envelope_bbox": None,
                "suggested_bbox": None, "gap": 0.0, "polarity": ""}
    duration = video_duration_cv2(file_path)
    if duration <= 0:
        try:
            from app.pipeline.extract import _probe_video_duration_seconds

            duration = _probe_video_duration_seconds(Path(file_path))
        except Exception as exc:  # pragma: no cover - defensive
            logger(f"notation envelope: duration probe failed: {exc}")
            duration = 0.0
    times = sample_times(duration, count)
    samples = read_frames_cv2(file_path, times)
    reader = "opencv"
    if not samples:
        from app.pipeline.extract import extract_preview_frame

        reader = "ffmpeg"
        for i, t in enumerate(times):
            try:
                image_path = extract_preview_frame(source_type="file", file_path=file_path, youtube_url=None, start_sec=t,
                                                   workspace=Path(workspace) / f"envelope_{i}", logger=logger)
                img = cv2.imread(str(image_path))
                if img is not None:
                    samples.append((t, img))
            except Exception as exc:
                logger(f"notation envelope sample at {t:.2f}s failed: {exc}")
    env = analyze_samples(samples)
    env["duration_sec"] = round(float(duration), 3)
    env["reader"] = reader
    return env
