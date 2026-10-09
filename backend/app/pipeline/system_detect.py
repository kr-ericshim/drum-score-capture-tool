"""Staff, barline and system-region detection for captured drum scores.

Port of the corpus detector ``tools/measure_detect.py`` (drum-score corpus)
(the "hardened" detector that reproduces the corpus golden set, 67 captures /
367 barlines). The staff and barline primitives keep that file's behavior; the
source line ranges are cited on each function. ``system_regions`` is new: it
groups staff segments into screen rows and estimates each row's notation
envelope for the observation manifest (design section 5).

Coordinates are pixels of the image passed in. Boxes are half-open
``[x0, y0, x1, y1]``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

DETECTOR_VERSION = "measure_detect-port-1"


# --------------------------------------------------------------------------- #
# Ported primitives (behavior-preserving)
# --------------------------------------------------------------------------- #


def percentile_u8(gray: np.ndarray, q: float) -> float:
    """``np.percentile(gray, q)`` (default linear method) of a uint8 image, read from its
    histogram instead of partitioning the whole image. Same value: the two order statistics
    come from the cumulative histogram and are interpolated exactly as numpy's ``_lerp`` does."""
    n = int(gray.size)
    if gray.dtype != np.uint8 or gray.ndim != 2 or n == 0 or n >= (1 << 24):
        return float(np.percentile(gray, q))
    hist = cv2.calcHist([np.ascontiguousarray(gray)], [0], None, [256], [0, 256]).ravel().astype(np.int64)
    cum = np.cumsum(hist)
    virtual = (n - 1) * (float(q) / 100.0)  # numpy "linear"
    if virtual >= n - 1:
        return float(np.searchsorted(cum, n - 1, side="right"))
    lo = max(int(np.floor(virtual)), 0)
    t = virtual - lo
    a = float(np.searchsorted(cum, lo, side="right"))  # the lo-th (0-based) order statistic
    b = float(np.searchsorted(cum, lo + 1, side="right"))
    d = b - a
    return b - d * (1.0 - t) if t >= 0.5 else a + d * t


def normalize_polarity(img: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Dark-theme scores (light ink on dark paper) are inverted to dark-on-light.

    Source: measure_detect.py:5-10.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if percentile_u8(gray, 50) < 110:
        return 255 - img, True
    return img, False


def ink_mask(img: np.ndarray) -> np.ndarray:
    """Source: measure_detect.py:13-16."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    paper = np.percentile(gray, 75)
    return (gray < min(150, paper - 60)).astype(np.uint8)


def _line_rows(horiz: np.ndarray, min_frac: float) -> List[Tuple[float, int]]:
    """Source: measure_detect.py:19-30."""
    prof = horiz.sum(axis=1).astype(float)
    if prof.max() <= 0:
        return []
    rows = np.flatnonzero(prof >= max(min_frac * horiz.shape[1], 0.5 * prof.max()))
    lines, start = [], None
    for i, r in enumerate(rows):
        if start is None:
            start = r
        if i == len(rows) - 1 or rows[i + 1] != r + 1:
            lines.append(((start + r) / 2.0, r - start + 1))
            start = None
    return lines


def _horizontal_lines(ink: np.ndarray) -> np.ndarray:
    w = ink.shape[1]
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 25), 1)))


def _uniform_window(lines: List[Tuple[float, int]], i: int) -> bool:
    """Five rows from ``i`` with near-equal spacing (measure_detect.py:40-42)."""
    if i + 5 > len(lines):
        return False
    d = np.diff([l[0] for l in lines[i : i + 5]])
    return bool(d.min() >= 4 and d.max() / d.min() < 1.25)


def _line_coverage(horiz: np.ndarray, lines: List[Tuple[float, int]]) -> List[int]:
    """Columns covered by each detected line row (its full thickness band)."""
    out = []
    for y, th in lines:
        a = int(np.floor(y - (th - 1) / 2.0))
        b = int(np.ceil(y + (th - 1) / 2.0)) + 1
        out.append(int(horiz[max(0, a) : b].any(axis=0).sum()))
    return out


# A candidate five-line window replaces the first one only when it is clearly
# more staff-like: its score must exceed the first window's by this factor.
_WINDOW_SWITCH_MARGIN = 1.03


def _window_score(lines: List[Tuple[float, int]], cover: List[int], j: int) -> float:
    """Staff-likeness of the five rows from ``j``.

    Staff lines span the whole system with the same thin stroke; a beam row or
    a line of note heads is shorter (fragmented between groups) and much
    thicker. Score = summed coverage, halved for every row whose thickness is
    an outlier against the window's median (beam/notehead band).
    """
    th = np.array([lines[k][1] for k in range(j, j + 5)], float)
    med = float(np.median(th))
    outliers = int(np.sum(th > 2.0 * med + 1.0))
    return float(sum(cover[j : j + 5])) * (0.5 ** outliers)


def _best_staff_window(lines: List[Tuple[float, int]], cover: List[int], i: int) -> int:
    """Start index of the most staff-like uniform five-row window overlapping ``i..i+4``.

    Only windows reachable through a chain of uniform windows are considered
    (a uniform run of six or more rows); the first window is kept unless an
    alternative scores clearly higher, so plain five-line staves are unchanged.
    """
    best, best_score = i, _window_score(lines, cover, i)
    j = i + 1
    while j <= i + 4 and _uniform_window(lines, j):
        # Same spacing as the first window, so the run is one ladder of rows.
        g0 = (lines[i + 4][0] - lines[i][0]) / 4.0
        gj = (lines[j + 4][0] - lines[j][0]) / 4.0
        if abs(gj - g0) > 0.2 * g0:
            break
        s = _window_score(lines, cover, j)
        if s > best_score * _WINDOW_SWITCH_MARGIN:
            best, best_score = j, s
        j += 1
    return best


def find_staves(ink: np.ndarray) -> List[Dict[str, Any]]:
    """Five-line staves, split into continuous horizontal segments.

    Source: measure_detect.py:33-70, except that a uniform run of six or more
    rows (beams / note heads one gap off the staff) keeps the most staff-like
    five (``_best_staff_window``) instead of the first five.
    """
    h, w = ink.shape
    horiz = _horizontal_lines(ink)
    lines = _line_rows(horiz, 0.2)
    cover = _line_coverage(horiz, lines)
    staves, i = [], 0
    while i + 4 < len(lines):
        if _uniform_window(lines, i):
            # A row of beams / note heads one gap above (or below) the staff can
            # extend a uniform run to six or more "lines"; the original took the
            # first five. Pick the five that look most like staff lines.
            j = _best_staff_window(lines, cover, i)
            ys = [l[0] for l in lines[j : j + 5]]
            d = np.diff(ys)
            staves.append({"lines": ys, "gap": float(d.mean()), "thick": float(np.mean([l[1] for l in lines[j : j + 5]]))})
            i = j + 5
        else:
            i += 1
    segments = []
    for st in staves:
        # A staff can stop and restart on the same rows (e.g. a preview of the
        # next line beside the current one): each continuous run is its own staff.
        rows = [int(round(y)) for y in st["lines"]]
        present = np.zeros(w, bool)
        for r in rows:
            present |= horiz[max(0, r - 1) : r + 2].any(axis=0)
        cols = np.flatnonzero(present)
        if not len(cols):
            continue
        runs, start, prev = [], cols[0], cols[0]
        for c in cols[1:]:
            if c - prev > 0.8 * st["gap"]:
                runs.append((start, prev))
                start = c
            prev = c
        runs.append((start, prev))
        for a, b in runs:
            if b - a < 3 * st["gap"]:
                continue
            seg = dict(st, x=(int(a), int(b)))
            seg["clipped_left"] = a <= 2
            seg["clipped_right"] = b >= w - 3
            segments.append(seg)
    return segments


def _attached_blob(ink: np.ndarray, x0: int, x1: int, st: Dict[str, Any]) -> bool:
    """True when the stroke is a stem or part of a glyph rather than a barline.

    Source: measure_detect.py:73-109. Only the spaces between staff lines are
    inspected. A notehead touching an end of the stroke fills a space beside
    it; a glyph stroke has ink beside it on both sides across most spaces; a
    barline has ink on one side at most.
    """
    top, bot, gap = st["lines"][0], st["lines"][4], st["gap"]
    h, w = ink.shape
    reach = max(2, int(round(0.2 * gap)))
    margin = st["thick"] / 2 + 2
    rows = np.arange(h)
    space = np.ones(h, bool)
    for y in st["lines"]:
        space &= np.abs(rows - y) > margin
    ends = [(int(top - 0.6 * gap), int(top + 1.4 * gap)), (int(bot - 1.4 * gap), int(bot + 0.6 * gap))]
    left, right = ink[:, max(0, x0 - reach) : x0], ink[:, x1 + 1 : min(w, x1 + 1 + reach)]
    left_far, right_far = ink[:, max(0, x0 - reach - 2) : max(0, x0 - 2)], ink[:, x1 + 3 : min(w, x1 + 3 + reach)]
    hits = []
    for near, far in ((left, left_far), (right, right_far)):
        if near.size == 0:
            hits.append(0)
            continue
        filled = near.mean(axis=1) >= 0.6
        if filled[int(top) : int(bot) + 1].mean() > 0.85:
            hits.append(0)
            continue  # neighbouring full-height stroke: thick/thin pair
        for a, b in ends:
            a, b = max(0, a), min(h, b)
            if (filled[a:b] & space[a:b]).sum() >= max(2, 0.3 * gap):
                return True
        touched = far.any(axis=1) if far.size else np.zeros(h, bool)
        hits.append(
            sum(
                bool((touched & space)[int(a) : int(b) + 1].sum() >= max(2, 0.25 * gap))
                for a, b in zip(st["lines"][:-1], st["lines"][1:])
            )
        )
    return max(hits) >= 3 and min(hits) >= 2


def find_barlines(ink: np.ndarray, st: Dict[str, Any], nonstaff: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    """Source: measure_detect.py:112-141."""
    top, bot, gap = st["lines"][0], st["lines"][4], st["gap"]
    t, b = int(round(top)), int(round(bot))
    h, w = ink.shape
    cover = ink[t : b + 1].mean(axis=0)
    a0, a1 = max(0, int(top - 1.5 * gap)), max(0, int(top - 0.35 * gap))
    b0, b1 = min(h, int(bot + 0.35 * gap)), min(h, int(bot + 1.5 * gap))
    above = ink[a0:a1].mean(axis=0) if a1 > a0 else np.zeros(w)
    below = ink[b0:b1].mean(axis=0) if b1 > b0 else np.zeros(w)
    cand = (cover >= 0.95) & (above < 0.5) & (below < 0.5)
    x0, x1 = st["x"]
    cand[: max(0, x0 - 2)] = False
    cand[x1 + 3 :] = False
    groups: List[List[int]] = []
    for x in np.flatnonzero(cand):
        if groups and x - groups[-1][-1] <= 2:
            groups[-1].append(x)
        else:
            groups.append([x])
    if nonstaff is not None:
        groups = [g for g in groups if not _attached_blob(ink, g[0], g[-1], st)]
    bounds: List[Dict[str, Any]] = []
    for g in groups:
        s = (g[0], g[-1])
        if bounds and s[0] - bounds[-1]["x1"] <= gap:
            bounds[-1]["x1"] = s[1]
            bounds[-1]["strokes"].append(s)
        else:
            bounds.append({"x0": s[0], "x1": s[1], "strokes": [s]})
    # The percussion clef's thick bars at the staff start are not a barline.
    return [bd for bd in bounds if bd["x0"] - x0 > 1.5 * gap or len(bounds) == 1]


def has_percussion_clef(ink: np.ndarray, st: Dict[str, Any]) -> bool:
    """Two short bars over the middle staff lines right after the staff start.

    Source: measure_detect.py:144-151 (``_has_percussion_clef``).
    """
    l, gap = st["lines"], st["gap"]
    x0 = st["x"][0]
    zone = slice(x0, x0 + int(2.5 * gap))
    mid = ink[int(l[1]) : int(l[3]) + 1, zone].mean(axis=0)
    full = ink[int(l[0]) : int(l[4]) + 1, zone].mean(axis=0)
    return bool(((mid >= 0.9) & (full < 0.8)).any())


def detect(img: np.ndarray) -> Dict[str, Any]:
    """Staves with barlines. Source: measure_detect.py:154-176 (same output shape)."""
    img, inverted = normalize_polarity(img)
    ink = ink_mask(img)
    return _detect_on_ink(ink, inverted)


def _detect_on_ink(ink: np.ndarray, inverted: bool) -> Dict[str, Any]:
    staves = find_staves(ink)
    out = []
    for st in staves:
        nonstaff = ink.copy()
        half = st["thick"] / 2 + 1
        for y in st["lines"]:
            nonstaff[max(0, int(y - half)) : int(y + half) + 1] = 0
        bars = find_barlines(ink, st, nonstaff)
        if has_percussion_clef(ink, st):
            # Clef and time signature fill the start of the line: a single thin
            # stroke there is a glyph. A repeat start (two strokes) is kept.
            bars = [b for b in bars if b["x0"] - st["x"][0] >= 6 * st["gap"] or len(b["strokes"]) > 1]
        # Reaching the ROI edge is normal for a tight strip; it is clipped only
        # when no barline closes the staff there.
        near = lambda x: any(abs(b["x0"] - x) <= st["gap"] or abs(b["x1"] - x) <= st["gap"] for b in bars)  # noqa: E731
        clipped = [bool(st["clipped_left"]), bool(st["clipped_right"] and not near(st["x"][1]))]
        out.append(
            {
                "lines": [round(y, 1) for y in st["lines"]],
                "gap": round(st["gap"], 2),
                "thick": round(st["thick"], 2),
                "x": list(st["x"]),
                "clipped": clipped,
                "bars": [[int(b["x0"]), int(b["x1"]), len(b["strokes"])] for b in bars],
            }
        )
    return {"inverted": inverted, "staves": out}


def barline_centres(staff: Dict[str, Any]) -> List[float]:
    """Source: corpus tools/golden.py:21-22."""
    return [(b[0] + b[1]) / 2 for b in staff["bars"]]


# --------------------------------------------------------------------------- #
# Golden-set scoring (golden.py:35-54) plus unmatched extra staves
# --------------------------------------------------------------------------- #


def score_against_golden(gold_staves: List[Dict[str, Any]], detected: List[Dict[str, Any]]) -> Dict[str, int]:
    """Score one capture like corpus ``golden.py check`` and also count extras.

    ``golden.py`` (lines 38-52) loops over the labeled staves only, so a
    detected staff that matches no labeled staff is never penalized. Here every
    detected staff that was not the chosen match of some labeled staff is
    counted in ``extra_staves`` (its barlines are not added to ``fp`` so the
    legacy numbers stay comparable).
    """
    tp = fp = fn = missing = 0
    used_staves = set()
    for g in gold_staves:
        overlap = lambda s: min(s["x"][1], g["x"][1]) - max(s["x"][0], g["x"][0])  # noqa: E731
        match = sorted(
            (i for i, s in enumerate(detected) if abs(s["lines"][0] - g["top"]) < g["gap"] and overlap(s) > 0),
            key=lambda i: overlap(detected[i]),
            reverse=True,
        )
        if not match:
            missing += 1
            fn += len(g["bars"])
            continue
        used_staves.add(match[0])
        got = barline_centres(detected[match[0]])
        used = set()
        for x in g["bars"]:
            hit = next((j for j, y in enumerate(got) if j not in used and abs(x - y) <= g["gap"] / 2), None)
            if hit is None:
                fn += 1
            else:
                used.add(hit)
                tp += 1
        fp += len(got) - len(used)
    extra = len([i for i in range(len(detected)) if i not in used_staves])
    return {"tp": tp, "fp": fp, "fn": fn, "missing_staves": missing, "extra_staves": extra}


# --------------------------------------------------------------------------- #
# System regions (new)
# --------------------------------------------------------------------------- #


ENVELOPE_METHOD = "attached_ink_chain_v1"


def attached_envelope(stats: np.ndarray, count: int, *, top: float, bot: float, gap: float, x_lo: int, x_hi: int,
                      band_top: float, band_bot: float, width: int, base: List[int]) -> List[int]:
    """Notation envelope of one staff row: union of the ink components chained to it.

    Seeds are components that reach the staff rows (notes, stems, beams, bar
    lines are connected to the staff or cross it). A component joins when its
    box comes within 0.75 gap (vertically and horizontally) of an included one,
    repeated until stable, so marks above beams, articulation, dynamics and
    lyric lines that sit close to the notation are included, while unrelated
    ink further away (another row's text, video background) is not. Only
    components inside the row band and within one gap of the staff's x extent
    are considered. Frame-wide thin lines are ignored.
    """
    cand = []
    for idx in range(1, count):
        x, y, bw, bh, area = stats[idx]
        if area < 2:
            continue
        if y + bh <= band_top or y >= band_bot:
            continue
        if x + bw <= x_lo - gap or x >= x_hi + gap:
            continue
        if bw > 0.9 * width and bh <= 2:
            continue
        cand.append((int(x), int(y), int(x + bw), int(y + bh)))
    if not cand:
        return base
    boxes = np.array(cand, dtype=np.float64)
    inc = (boxes[:, 3] >= top - 0.5 * gap) & (boxes[:, 1] <= bot + 0.5 * gap)
    reach = 0.75 * gap
    for _ in range(12):
        if not inc.any():
            break
        cur = boxes[inc]
        new = inc.copy()
        for k in np.flatnonzero(~inc):
            b = boxes[k]
            dy = np.maximum(0.0, np.maximum(cur[:, 1] - b[3], b[1] - cur[:, 3]))
            dx = np.maximum(0.0, np.maximum(cur[:, 0] - b[2], b[0] - cur[:, 2]))
            if np.any((dy <= reach) & (dx <= reach)):
                new[k] = True
        if (new == inc).all():
            break
        inc = new
    env = list(base)
    for b in boxes[inc]:
        env[0] = min(env[0], int(b[0]))
        env[1] = min(env[1], int(max(b[1], band_top)))
        env[2] = max(env[2], int(b[2]))
        env[3] = max(env[3], int(min(b[3], band_bot)))
    return env


def system_regions(img: np.ndarray, *, min_width_gaps: float = 8.0) -> Dict[str, Any]:
    """Group staff segments into rows and estimate each row's notation envelope.

    Returns ``{"inverted", "regions": [...]}``; each region has
    ``staff_y`` (5 line rows), ``staff_gap_px``, ``staff_x`` (segment extent),
    ``segments`` (all staff segments on the row, e.g. a current line and a
    preview beside it), ``bars`` (barlines of the widest segment),
    ``bbox`` / ``row_band`` (vertical band owned by this row, halfway to
    neighbours; 8 gaps when there is no neighbour), ``envelope_bbox``
    (``attached_envelope``: ink components chained to the staff, within the
    row band) and
    ``issues`` (``envelope_at_top_edge`` / ``envelope_at_bottom_edge`` when a
    content component comes within 0.25 gap of the image border,
    ``staff_clipped_left`` / ``staff_clipped_right``).
    Rows narrower than ``min_width_gaps`` staff gaps are ignored.
    """
    norm, inverted = normalize_polarity(img)
    h, w = norm.shape[:2]
    ink = ink_mask(norm)
    det = _detect_on_ink(ink, inverted)
    if not det["staves"]:
        # Fallback for thin, light (anti-aliased) staff lines that the ported
        # threshold misses: a lighter ink cut. Only used when no staff is found,
        # so detect() and the golden regression are unaffected.
        gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
        paper = np.percentile(gray, 75)
        light = (gray < min(200, paper - 35)).astype(np.uint8)
        det_l = _detect_on_ink(light, inverted)
        if det_l["staves"]:
            ink, det = light, det_l
    staves = sorted(det["staves"], key=lambda s: (s["lines"][0], s["x"][0]))
    rows: List[List[Dict[str, Any]]] = []
    for st in staves:
        if rows and abs(rows[-1][0]["lines"][0] - st["lines"][0]) < 1.5 * st["gap"]:
            rows[-1].append(st)
        else:
            rows.append([st])
    picked = []
    for segs in rows:
        main = max(segs, key=lambda s: s["x"][1] - s["x"][0])
        if main["x"][1] - main["x"][0] < min_width_gaps * main["gap"]:
            continue
        picked.append((main, segs))

    regions = []
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    for i, (st, segs) in enumerate(picked):
        gap = float(st["gap"])
        top, bot = st["lines"][0], st["lines"][4]
        prev_bot = picked[i - 1][0]["lines"][4] if i else None
        next_top = picked[i + 1][0]["lines"][0] if i + 1 < len(picked) else None
        band_top = (prev_bot + top) / 2.0 if prev_bot is not None else max(0.0, top - 8 * gap)
        band_bot = (bot + next_top) / 2.0 if next_top is not None else min(float(h), bot + 8 * gap)
        x_lo = min(s["x"][0] for s in segs)
        x_hi = max(s["x"][1] for s in segs) + 1
        env = attached_envelope(stats, count, top=top, bot=bot, gap=gap, x_lo=x_lo, x_hi=x_hi,
                                band_top=band_top, band_bot=band_bot, width=w,
                                base=[x_lo, int(np.floor(top - st.get("thick", 1))), x_hi, int(np.ceil(bot + st.get("thick", 1))) + 1])
        env = [max(0, env[0]), max(0, env[1]), min(w, env[2]), min(h, env[3])]
        issues = []
        edge = max(1, int(round(0.25 * gap)))
        if env[1] <= edge:
            issues.append("envelope_at_top_edge")
        if env[3] >= h - edge:
            issues.append("envelope_at_bottom_edge")
        if st["clipped"][0]:
            issues.append("staff_clipped_left")
        if st["clipped"][1]:
            issues.append("staff_clipped_right")
        regions.append(
            {
                "staff_y": [float(y) for y in st["lines"]],
                "staff_gap_px": gap,
                "staff_x": [int(st["x"][0]), int(st["x"][1]) + 1],
                "segments": [[int(s["x"][0]), int(s["x"][1]) + 1] for s in segs],
                "bars": [[int(b[0]), int(b[1]), int(b[2])] for b in st["bars"]],
                "clef": has_percussion_clef(ink, {"lines": st["lines"], "gap": gap, "x": st["x"]}),
                "bbox": [0, int(max(0, np.floor(band_top))), w, int(min(h, np.ceil(band_bot)))],
                "row_band": [0, int(max(0, np.floor(band_top))), w, int(min(h, np.ceil(band_bot)))],
                "envelope_bbox": [int(v) for v in env],
                "issues": issues,
            }
        )
    return {"inverted": inverted, "regions": regions, "size": [w, h]}
