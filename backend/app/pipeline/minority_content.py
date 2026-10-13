"""Raw minority foreground and evidence-based transient identification.

Strip observations retain every credible >=3-pixel component, including a
single-member one-pixel-wide stroke. Duration, repeated screen position and
staff proximity alone never explain foreground. The tracker still uses its
stable-state grouping; strip audits use ``single_observation=True``.

Playback explanations need a monotonic colored marker/connected achromatic
continuation AND clear same-occurrence recovery of the notation underneath.
Page transitions need positive curl/shadow/warped geometry with stable
witnesses. Chrome needs the caller's positive screen-chrome mask and an
appearance check excluding notation. Other hypotheses remain review evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

MIN_COMPONENT_PX = 3      # a radius-1 dot; single noisy pixels are not content
MIN_EXTENT_PX = 2         # and at least 2 px wide and tall: 1-px slivers at ink edges are registration residue
PERSIST_FRACTION = 0.5    # share of a component the neighbouring observation must also show (same place)
TOL_GAPS = 0.15           # registration tolerance against the reference (about 2 px at a 14 px gap)
CLUSTER_GAPS = 0.5        # components closer than this are one event
TRACK_MIN_POSITIONS = 3   # a cursor track: tall thin strokes at >= 3 distinct positions
TRACK_MIN_HEIGHT_GAPS = 3.0
TRACK_MAX_WIDTH_GAPS = 0.6
CURSOR_APPEARANCE_TOL = 30.0  # existing chrome appearance tolerance; distinguish real ink from a cursor template
MISREGISTERED_FRACTION = 0.02  # above this share of unexplained ink a member is re-registered (+-3 px)
REGISTER_PX = 3
INK_DARK_MARGIN = 45.0     # a minority component must be about as dark as the score's ink
INK_DARK_CAP = 110.0       # system_tracking.CLEAN_INK_MAX
VIDEO_BACKGROUND_MIN = 0.15  # a component on video seen through the band, not on paper


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def colored_mask(clean: np.ndarray) -> np.ndarray:
    if clean.ndim != 3:
        return np.zeros(clean.shape[:2], bool)
    hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)
    return (hsv[..., 1] > 80) & (hsv[..., 2] > 60)


def ink_mask(clean: np.ndarray) -> np.ndarray:
    """All ink (neutral and colored) of a cleaned image (system_tracking.clean_content output)."""
    return _gray(clean) < 200


def ink_dark_max(clean: np.ndarray) -> float:
    """Gray level up to which a pixel is as dark as the score's ink: the median gray of the
    image's ink plus ``INK_DARK_MARGIN`` (at most system_tracking.CLEAN_INK_MAX). Video seen
    through a translucent score band stays lighter than the opaque ink after cleaning
    (bF69: band 79-109, ink 0-10)."""
    g = _gray(clean)
    ink = g[g < 200]
    if ink.size == 0:
        return float(INK_DARK_CAP)
    return float(min(INK_DARK_CAP, float(np.median(ink)) + INK_DARK_MARGIN))


def neutral_ink(clean: np.ndarray, dark_max: Optional[float] = None) -> np.ndarray:
    """Ink-like pixels of a cleaned image: as dark as the score's ink (``ink_dark_max``), not
    colored and not on the anti-aliased rim of a colored object (2 px)."""
    g = _gray(clean)
    dm = ink_dark_max(clean) if dark_max is None else float(dark_max)
    colored = colored_mask(clean) & (g < 200)
    if colored.any():
        colored = _dilate(colored, 2)
    return (g <= dm) & ~colored


def background_texture(norm: np.ndarray, gap: float) -> np.ndarray:
    """Per pixel: the share of the non-ink pixels around it (a box of about one staff gap,
    the ink's 2-px anti-aliased edge left out) that are visibly not paper. ``norm`` is the
    polarity-normalized (dark ink on light) image before cleaning. Near 0 on a printed score
    (below 0.09 on the degraded test fixture); high where textured video shows through a
    translucent score band. A glint on a dark, flat part of the video has paper around it
    after inversion and is judged like ink (bF69 false alarms)."""
    g = _gray(norm)
    if g.dtype != np.uint8:
        g = np.clip(g, 0, 255).astype(np.uint8)
    # 75th percentile of the gray levels from the histogram (no sort of the whole image)
    hist = cv2.calcHist([np.ascontiguousarray(g)], [0], None, [256], [0, 256]).ravel()
    paper = float(np.searchsorted(np.cumsum(hist), 0.75 * (g.size - 1), side="right"))
    ink = g < min(INK_DARK_CAP, paper - 60)
    # the anti-aliased edge of the ink (2 px) is neither paper nor video: left out of both counts,
    # so dense notation does not read as video background
    near_ink = _dilate(ink, 2)
    free_m = ~near_ink
    textured = free_m & (g < paper - 25)
    r = max(3, int(round(0.5 * float(gap))))
    k = (2 * r + 1, 2 * r + 1)
    dens = cv2.boxFilter(textured.view(np.uint8), cv2.CV_32F, k, normalize=False, borderType=cv2.BORDER_REPLICATE)
    free = cv2.boxFilter(free_m.view(np.uint8), cv2.CV_32F, k, normalize=False, borderType=cv2.BORDER_REPLICATE)
    # where (almost) everything around is ink there is nothing to judge the background by
    out = cv2.divide(dens, cv2.max(free, 1.0))
    out[free < 0.1 * k[0] * k[1]] = 0.0
    return out


def drop_on_video_background(mask: np.ndarray, texture: np.ndarray) -> Tuple[np.ndarray, int]:
    """Remove components whose surroundings are mostly not paper (mean ``background_texture``
    over the component >= ``VIDEO_BACKGROUND_MIN``): video showing through a translucent band
    (a bright glint inverts to ink-dark). Returns (mask, components removed)."""
    if not mask.any():
        return mask, 0
    n, lab = cv2.connectedComponents(mask.view(np.uint8) if mask.dtype == bool else mask.astype(np.uint8), connectivity=8)
    # the mean texture per component, from the component pixels only
    lab_in = lab[mask]
    area = np.bincount(lab_in, minlength=n).astype(np.float64)
    tex = np.bincount(lab_in, weights=texture[mask].astype(np.float64), minlength=n) / np.maximum(area, 1.0)
    drop = np.zeros(n, bool)
    drop[1:] = tex[1:] >= VIDEO_BACKGROUND_MIN
    if not drop.any():
        return mask, 0
    return mask & ~drop[lab], int(drop.sum())


def colored_columns(clean: np.ndarray) -> np.ndarray:
    """Columns holding a colored playback overlay (>= 3 clearly colored ink pixels), widened by 3 px."""
    col = colored_mask(clean) & ink_mask(clean)
    cols = col.sum(axis=0) >= 3
    if cols.any():
        cols = cv2.dilate(cols.astype(np.uint8)[None, :], np.ones((1, 7), np.uint8))[0] > 0
    return cols


def playhead_columns(width: int, region: Optional[Dict[str, Any]], gap: float, x_offset: int = 0) -> np.ndarray:
    """Columns at the playhead the observation's overlay detector found in ``region``
    (``playhead_x``: fraction of the region bbox width), in an image whose column 0 is crop
    column ``x_offset``."""
    out = np.zeros(int(width), bool)
    if not region or region.get("playhead_x") is None:
        return out
    x0, _y0, x1, _y1 = region["bbox"]
    x = float(x0) + float(region["playhead_x"]) * float(x1 - x0) - float(x_offset)
    half = max(3.0, 0.75 * float(gap))
    a, b = int(np.floor(x - half)), int(np.ceil(x + half)) + 1
    a, b = max(0, a), min(int(width), b)
    if b > a:
        out[a:b] = True
    return out


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return mask.copy()
    return cv2.dilate(mask.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0


def _drop_small(mask: np.ndarray, min_px: int = MIN_COMPONENT_PX, *, min_extent: int = MIN_EXTENT_PX) -> np.ndarray:
    """Components with minimum area and extent. Raw registered strip evidence may
    set ``min_extent=1`` for thin strokes; the tracker keeps its existing default."""
    if not mask.any():
        return mask
    n, lab, stats, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = (stats[1:, cv2.CC_STAT_AREA] >= min_px) & (stats[1:, cv2.CC_STAT_WIDTH] >= min_extent) \
        & (stats[1:, cv2.CC_STAT_HEIGHT] >= min_extent)
    return keep[lab]


def tolerance_px(gap: float) -> int:
    return max(1, int(round(TOL_GAPS * float(gap))))


def _shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(mask)
    h, w = mask.shape
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def rejected_foreground(gray: np.ndarray, reference: np.ndarray, paper: float,
                        shift: Sequence[float], gap: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Audit in raw coordinates without admitting a rejected member to support.

    A bounded integer translation is tried first. It explains reference-matched
    foreground only when the printed scaffold agrees after registration; failed
    registration retains all foreground. Brightness normalization affects this
    comparison only, never the stored source pixels or the primary composite.
    """
    foreground = gray.astype(float) <= paper - 60
    comparison = np.clip(gray.astype(float) * (float(np.percentile(reference, 75)) /
                                               max(1., paper)), 0, 255)
    finite = bool(np.isfinite(shift).all())
    dx, dy = (-int(round(shift[0])), -int(round(shift[1]))) if finite else (0, 0)
    bounded = finite and max(abs(dx), abs(dy)) <= REGISTER_PX
    ref_dark = reference < float(np.percentile(reference, 75)) - 60
    scaffold = _shift(foreground, dx, dy)
    # Require substantial scaffold agreement in both directions, so a different
    # display cannot win a local shift by matching one isolated dot.
    tol = _dilate(ref_dark, 1)
    recall = float((ref_dark & _dilate(scaffold, 1)).sum()) / max(1, int(ref_dark.sum()))
    precision = float((scaffold & tol).sum()) / max(1, int(scaffold.sum()))
    registered = bounded and recall >= .9 and precision >= .9
    proof = {"attempted_shift_px": [dx, dy], "registered": registered,
             "scaffold_recall": round(recall, 4), "scaffold_precision": round(precision, 4),
             "raw_foreground_px": int(foreground.sum())}
    if registered:
        # Query the reference in the member's coordinates. No source resampling,
        # no clipped translated edge: unsupported border foreground stays raw.
        matrix = np.array([[1, 0, -dx], [0, 1, -dy]], np.float32)
        # Match exact registered pixels. A dilated/eroded scaffold would silently
        # explain a novel one-pixel stroke merely because it touches a staff line.
        recovered = cv2.warpAffine(reference, matrix, (gray.shape[1], gray.shape[0]),
                                   flags=cv2.INTER_NEAREST, borderValue=255)
        foreground &= comparison < recovered.astype(float) - 50
    kept = _drop_small(foreground, min_extent=1)
    proof["speckle_dropped"] = int(cv2.connectedComponents((foreground & ~kept).astype(np.uint8))[0] - 1)
    return kept, proof


def unexplained(mask: np.ndarray, reference_ink: np.ndarray, explained_cols: np.ndarray, gap: float,
                *, reference_dilated: Optional[np.ndarray] = None) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Neutral ink of ``mask`` the reference does not draw (registration tolerance
    ``TOL_GAPS``), outside the explained (overlay) columns, components >= ``MIN_COMPONENT_PX``.
    A member whose unexplained share is large is re-registered by up to +-``REGISTER_PX`` px
    first (the tracker accepts registration shifts below half a staff gap).
    Returns (mask, (dx, dy) applied to the member)."""
    ref_d = reference_dilated if reference_dilated is not None else _dilate(reference_ink, tolerance_px(gap))
    m = mask.copy()
    m[:, explained_cols] = False
    u = m & ~ref_d
    total = int(m.sum())
    best = (int(u.sum()), (0, 0), u)
    if total and best[0] > MISREGISTERED_FRACTION * total:
        for dy in range(-REGISTER_PX, REGISTER_PX + 1):
            for dx in range(-REGISTER_PX, REGISTER_PX + 1):
                if dx == 0 and dy == 0:
                    continue
                sm = _shift(mask, dx, dy)
                sm[:, explained_cols] = False
                su = sm & ~ref_d
                c = int(su.sum())
                if c < best[0]:
                    best = (c, (dx, dy), su)
    return _drop_small(best[2]), best[1]


def remove_cursor_track(masks: Dict[int, np.ndarray], gap: float) -> Tuple[Dict[int, np.ndarray], Dict[str, Any]]:
    """A cursor track explains tall thin strokes: when the display shows such strokes at
    >= ``TRACK_MIN_POSITIONS`` distinct positions (more than one staff gap apart), every tall
    thin stroke of every member is a cursor (moving or parked) and is removed."""
    strokes: List[Tuple[int, int, float]] = []  # (member, label, x centre)
    labelled: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    # staff lines (drawn by the reference) cut a stroke into pieces: bridge them vertically
    close = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(round(1.6 * gap)))))
    for i, u in masks.items():
        if not u.any():
            continue
        closed = cv2.morphologyEx(u.astype(np.uint8), cv2.MORPH_CLOSE, close)
        n, lab, stats, cent = cv2.connectedComponentsWithStats(closed, connectivity=8)
        labelled[i] = (lab, stats)
        for k in range(1, n):
            w, h = int(stats[k, cv2.CC_STAT_WIDTH]), int(stats[k, cv2.CC_STAT_HEIGHT])
            if h >= TRACK_MIN_HEIGHT_GAPS * gap and w <= max(3.0, TRACK_MAX_WIDTH_GAPS * gap):
                strokes.append((i, k, float(cent[k][0])))
    xs = sorted(x for _i, _k, x in strokes)
    positions = 0
    last = None
    for x in xs:
        if last is None or x - last > gap:
            positions += 1
        last = x
    info = {"tall_thin_strokes": len(strokes), "positions": positions, "track": positions >= TRACK_MIN_POSITIONS}
    if not info["track"]:
        return masks, info
    out = dict(masks)
    for i, k, _x in strokes:
        lab, stats = labelled[i]
        # the whole column span of the stroke: its end caps can be cut off by notation the reference draws
        x0 = max(0, int(stats[k, cv2.CC_STAT_LEFT]) - 1)
        x1 = int(stats[k, cv2.CC_STAT_LEFT] + stats[k, cv2.CC_STAT_WIDTH]) + 1
        m = out[i].copy()
        m[:, x0:x1] = False
        out[i] = m
    return out, info


def minority_events(masks: Dict[int, np.ndarray], gap: float, *, single_observation: bool = False) -> List[Dict[str, Any]]:
    """Group unexplained ink (``masks``: member index -> unexplained mask; indices are the
    members' positions in time order, missing indices were not checked) into events.

    A component counts only when the next or previous member (consecutive index) shows
    >= ``PERSIST_FRACTION`` of it at the same place. Events: components closer than
    ``CLUSTER_GAPS`` gaps; each event lists its member indices, the runs of consecutive
    indices (length >= 2), its box (x0, y0, x1, y1, half-open) and its largest area."""
    r = tolerance_px(gap)
    dil = {i: _dilate(m, r) for i, m in masks.items() if m.any()}
    persistent: Dict[int, np.ndarray] = {}
    for i, u in masks.items():
        if not u.any():
            continue
        if single_observation:
            persistent[i] = _drop_small(u, min_extent=1)
            continue
        nb = [dil[j] for j in (i - 1, i + 1) if j in dil]
        if not nb:
            continue
        nbm = nb[0] | nb[1] if len(nb) == 2 else nb[0]
        n, lab, stats, _c = cv2.connectedComponentsWithStats(u.astype(np.uint8), connectivity=8)
        area = stats[:, cv2.CC_STAT_AREA].astype(np.float64)
        hit = np.bincount(lab[nbm].ravel(), minlength=n).astype(np.float64) / np.maximum(area, 1.0)
        keep = np.zeros(n, bool)
        keep[1:] = hit[1:] >= PERSIST_FRACTION
        if keep.any():
            persistent[i] = keep[lab]
    if not persistent:
        return []
    union = np.zeros(next(iter(persistent.values())).shape, bool)
    for p in persistent.values():
        union |= p
    cl = _dilate(union, max(1, int(round(CLUSTER_GAPS * gap))))
    n, clab, _s, _c = cv2.connectedComponentsWithStats(cl.astype(np.uint8), connectivity=8)
    events = []
    for c in range(1, n):
        region = clab == c
        members = []
        acc = np.zeros_like(union)
        largest = 0
        for i in sorted(persistent):
            part = persistent[i] & region
            if part.any():
                members.append(i)
                acc |= part
                largest = max(largest, int(part.sum()))
        runs, start = [], None
        for k, i in enumerate(members):
            if start is None:
                start = i
            if k + 1 == len(members) or members[k + 1] != i + 1:
                if i > start or single_observation:
                    runs.append((start, i))
                start = None
        if not runs:
            continue
        ys, xs = np.nonzero(acc)
        events.append({"members": members, "runs": runs, "box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                       "area_px": largest,
                       "support_by_member": [{"member":i,"spans":support_runs(persistent[i] & region)} for i in members]})
    events.sort(key=lambda e: (e["runs"][0][0], e["box"][0]))
    return events


# --------------------------------------------------------------------------- #
# Round 5: stable steps, display-edge transitions, marks fixed to the screen
# --------------------------------------------------------------------------- #

STABLE_RUN_MIN_OBS = 3      # a state that lasts: as many observations as a confirmed display (system_tracking.CONFIRM_MIN_OBS)
STABLE_RUN_MIN_SEC = 0.5    # ... and as long (system_tracking.CONFIRM_MIN_SEC)
RECUR_MIN_DISPLAYS = 3      # a speck at one screen position in >= 3 different displays belongs to the screen
RECUR_TOL_GAPS = 0.5        # same position: centres within half a staff gap
RECUR_MAX_AREA_GAPS2 = 0.25  # only specks: at most a quarter of a staff gap squared (a 16 px gap: 64 px) ...
RECUR_MAX_EXTENT_GAPS = 0.75  # ... and at most 0.75 gap wide and tall (a lyric glyph or notehead is larger)


def stable_run(times: Sequence[float], i0: int, i1: int) -> bool:
    """A run of observations ``i0..i1`` (inclusive) that lasts like a confirmed display."""
    return (i1 - i0 + 1) >= STABLE_RUN_MIN_OBS and (float(times[i1]) - float(times[i0])) >= STABLE_RUN_MIN_SEC - 1e-6


def is_speck(box: Sequence[int], area_px: float, gap: float) -> bool:
    w, h = int(box[2]) - int(box[0]), int(box[3]) - int(box[1])
    lim = RECUR_MAX_EXTENT_GAPS * float(gap)
    return float(area_px) <= RECUR_MAX_AREA_GAPS2 * float(gap) ** 2 and w <= max(3.0, lim) and h <= max(3.0, lim)


def screen_fixed_spots(items: Sequence[Dict[str, Any]], gap: float) -> List[Dict[str, Any]]:
    """Specks of minority content (``is_speck``) at one screen position (crop coordinates,
    centres within ``RECUR_TOL_GAPS``) in >= ``RECUR_MIN_DISPLAYS`` different displays.

    A mark the score shows for a moment belongs to one display; a speck that comes and goes at
    the same screen place in three or more displays belongs to the screen: video seen through a
    translucent band (bF69: glints of the drum kit behind the staff) or a player UI. Limit: a real
    speck-sized mark shown for a moment at one screen place in three displays is not flagged
    (the caller keeps it on record). ``items``: [{"display": key, "box": [x0, y0, x1, y1] (crop), "area_px"}].
    Returns [{"box", "displays", "n"}]."""
    sm = [it for it in items if is_speck(it["box"], it.get("area_px", 0), gap)]
    if not sm:
        return []
    tol = max(2.0, RECUR_TOL_GAPS * float(gap))
    cen = np.array([[(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0] for b in (it["box"] for it in sm)], np.float64)
    parent = list(range(len(sm)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(len(sm)):
        d = np.abs(cen[a + 1:] - cen[a]).max(axis=1) if a + 1 < len(sm) else np.zeros(0)
        for b in np.nonzero(d <= tol)[0]:
            parent[find(a)] = find(int(a + 1 + b))
    groups: Dict[int, List[int]] = {}
    for a in range(len(sm)):
        groups.setdefault(find(a), []).append(a)
    spots = []
    for idx in groups.values():
        displays = sorted({str(sm[k]["display"]) for k in idx})
        if len(displays) < RECUR_MIN_DISPLAYS:
            continue
        bx = np.array([sm[k]["box"] for k in idx])
        spots.append({"box": [int(bx[:, 0].min()), int(bx[:, 1].min()), int(bx[:, 2].max()), int(bx[:, 3].max())],
                      "displays": displays, "n": len(idx)})
    spots.sort(key=lambda s: (s["box"][1], s["box"][0]))
    return spots


def in_screen_fixed_spot(box: Sequence[int], area_px: float, spots: Sequence[Dict[str, Any]], gap: float) -> bool:
    """A speck whose centre lies in a screen-fixed spot (widened by the position tolerance)."""
    if not spots or not is_speck(box, area_px, gap):
        return False
    tol = max(2.0, RECUR_TOL_GAPS * float(gap))
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    return any(s["box"][0] - tol <= cx <= s["box"][2] + tol and s["box"][1] - tol <= cy <= s["box"][3] + tol for s in spots)


def support_runs(mask: np.ndarray, origin=(0, 0)) -> List[List[int]]:
    """Lossless row spans [y, x0, x1) for residual foreground, never its box."""
    out = []
    for y in np.flatnonzero(mask.any(axis=1)):
        xs = np.flatnonzero(mask[y])
        starts = np.r_[0, np.flatnonzero(np.diff(xs) > 1) + 1]
        ends = np.r_[starts[1:] - 1, len(xs) - 1]
        out.extend([[int(y + origin[1]), int(xs[a] + origin[0]), int(xs[b] + origin[0] + 1)]
                    for a, b in zip(starts, ends)])
    return out


def transition_reference(reference: np.ndarray, gap: float) -> Dict[str, Any]:
    """The reference-only products of ``transition_evidence`` (paper level, dilated
    reference ink, horizontal scaffold), computed once for many members compared
    against the same reference and gap."""
    w = reference.shape[1]
    paper = float(np.percentile(reference, 75))
    dark = reference < paper - 60
    scaffold = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN,
        np.ones((1, max(3, int(max(4*gap, .12*w)))), np.uint8)) > 0
    return {"shape": reference.shape, "gap": float(gap), "reference_i16": reference.astype(np.int16),
            "paper": paper, "reference_ink": _dilate(dark, 1), "scaffold": scaffold,
            "scaffold_px": int(scaffold.sum()), "reference_light": reference > paper - 12}


def transition_evidence(gray: np.ndarray, reference: np.ndarray, gap: float, *,
                        prepared: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Positive page geometry: long tilted staff segments or a diagonal shadow edge.

    A small local mark, timing at a hand-over, or a registration failure alone
    is insufficient. Callers additionally require stable same-occurrence witnesses.
    Inputs are polarity-normalized, in the same observation coordinates.
    ``prepared``: ``transition_reference(reference, gap)``, shared by callers that
    compare many members against one reference (same result).
    """
    h, w = gray.shape
    if prepared is None or prepared["shape"] != reference.shape or prepared["gap"] != float(gap):
        prepared = transition_reference(reference, gap)
    if float((np.abs(gray.astype(np.int16)-prepared["reference_i16"]) > 20).mean()) < .005:
        return None
    paper = prepared["paper"]
    ink = gray < paper - 60
    reference_ink = prepared["reference_ink"]
    # New long beams cannot make an intact horizontal staff a warped page.
    scaffold = prepared["scaffold"]
    scaffold_px = prepared["scaffold_px"]
    lost_scaffold=int((scaffold & (gray >= paper-60)).sum())
    geometry_changed=scaffold_px>0 and lost_scaffold>=.1*scaffold_px
    # The tilted segments only matter with displaced scaffold: the line search runs
    # only then (the same result as searching first).
    lines = cv2.HoughLinesP(ink.astype(np.uint8), 1, np.pi / 720, threshold=max(20, int(2 * gap)),
                            minLineLength=max(4 * gap, .12 * w), maxLineGap=gap) if geometry_changed else None
    tilted = []
    for x0, y0, x1, y1 in (lines[:, 0] if lines is not None else []):
        dx, dy = int(x1 - x0), int(y1 - y0)
        if abs(dx) > 4 * gap and .008 < abs(dy / dx) < .35:
            xx = np.linspace(x0,x1,40).astype(int)
            yy = np.rint(y0+(xx-x0)*dy/dx).astype(int)
            r = max(2,int(.35*gap))
            valid=(yy>=r)&(yy<h-r)&(xx>=0)&(xx<w)
            if (valid.any() and float(reference_ink[yy[valid],xx[valid]].mean()) < .6
                    and float((~ink[yy[valid]-r,xx[valid]] & ~ink[yy[valid]+r,xx[valid]]).mean()) > .7):
                tilted.append([int(x0), int(y0), int(x1), int(y1)])
    # At least three long, similarly sloping lines plus displaced reference scaffold.
    if geometry_changed and len(tilted) >= 3 and np.ptp([(p[1]+p[3])/2 for p in tilted]) >= 2 * gap:
        slopes = [(p[3] - p[1]) / (p[2] - p[0]) for p in tilted]
        if abs(float(np.median(slopes))) > .008 and float(np.std(slopes)) < .04:
            return {"kind": "warped_staff_geometry", "tilted_segments": tilted[:20],
                    "reference_scaffold_px":scaffold_px,"displaced_scaffold_px":lost_scaffold}
    shadow = prepared["reference_light"] & (gray < paper - 12) & (gray > paper - 145)
    # Broad smooth paper change plus a long diagonal edge is curl/shadow evidence.
    broad = cv2.morphologyEx(shadow.astype(np.uint8), cv2.MORPH_OPEN,
                            np.ones((max(3, int(gap)), max(3, int(gap))), np.uint8))
    if int(broad.sum()) < max(6 * gap * gap, .01 * h * w):
        return None
    edge = cv2.Canny((broad * 255).astype(np.uint8), 40, 100)
    lines = cv2.HoughLinesP(edge, 1, np.pi / 360, threshold=max(20, int(2 * gap)),
                            minLineLength=4 * gap, maxLineGap=gap)
    diagonals = []
    for p in (lines[:, 0] if lines is not None else []):
        dx, dy = int(p[2] - p[0]), int(p[3] - p[1])
        if dx and .15 < abs(dy / dx) < 6:
            diagonals.append([int(v) for v in p])
    if diagonals:
        return {"kind": "diagonal_page_shadow", "shadow_px": int(broad.sum()), "edges": diagonals[:12]}
    return None


class CursorPositions(dict):
    """Internal trajectory plus the detected marker's physical half-width."""
    def __init__(self, positions, half_widths):
        super().__init__(positions)
        self.half_widths = half_widths


def cursor_positions(images: Sequence[np.ndarray], gap: float, *, reference: Optional[np.ndarray] = None,
                     allow_tinted_boxes: bool = True) -> Dict[int, float]:
    """A coherent colored cursor trajectory, excluding wide background texture.

    Use thin/tall components of a consistent hue, then a monotonic track over
    most observations. A bright unrelated object is not the marker simply
    because its column contains more colored pixels. Pale highlights use the
    same geometry at the fallback saturation threshold.
    """
    if len(images) < 3:
        return {}
    hsvs = [cv2.cvtColor(im,cv2.COLOR_BGR2HSV) for im in images]
    if reference is None:
        selected = sorted({0,len(images)//2,len(images)-1})
        grays = [_gray(images[i]) for i in selected]
        grays = [255-g if float(np.median(g))<110 else g for g in grays]
        reference = np.median(np.stack(grays),axis=0).astype(np.int16)
    best = None
    # per image, computed once and only when needed (the same values for both saturations)
    norm_grays: Dict[int, np.ndarray] = {}
    tinted: Dict[int, list] = {}

    def norm_gray(i: int) -> np.ndarray:
        if i not in norm_grays:
            gray=_gray(images[i])
            norm_grays[i]=(255-gray if float(np.median(gray))<110 else gray).astype(np.int16)
        return norm_grays[i]
    for saturation in (80,30):
        colored=[(hsv[...,1]>=saturation)&(hsv[...,2]>60) for hsv in hsvs]
        # np.mean(np.stack(colored),axis=0): an exact integer count over the images, then the same division
        count=np.zeros(colored[0].shape,np.int64)
        for col in colored:
            count+=col
        static=count/len(colored)>=.8
        candidates=[]
        for i,col in enumerate(colored):
            n,lab,stats,cent=cv2.connectedComponentsWithStats((col & ~static).astype(np.uint8),connectivity=8)
            for k in range(1,n):
                x,y,w,h,area=map(int,stats[k])
                if area<3 or w>max(4,2.5*gap):
                    continue
                effective_height=h
                if h<.7*gap or h<.45*w:
                    xc=int(round(cent[k,0]));radius=max(4,int(.4*gap))
                    if not radius<=xc<images[i].shape[1]-radius:
                        continue
                    gray=norm_gray(i)
                    core=(np.abs(gray[:,max(0,xc-1):xc+2]-reference[:,max(0,xc-1):xc+2])>30).any(axis=1)
                    sides=(np.abs(gray[:,xc-radius]-reference[:,xc-radius])>30)&(np.abs(gray[:,xc+radius]-reference[:,xc+radius])>30)
                    thin=core & ~sides
                    bridged=cv2.morphologyEx(thin.astype(np.uint8)[:,None],cv2.MORPH_CLOSE,
                                            np.ones((max(3,int(1.6*gap)),1),np.uint8))
                    _,_,st,_=cv2.connectedComponentsWithStats(bridged,connectivity=8)
                    effective_height=max(st[1:,cv2.CC_STAT_HEIGHT],default=0)
                    if effective_height<3*gap:
                        continue
                hue=float(np.median(hsvs[i][y:y+h,x:x+w][lab[y:y+h,x:x+w]==k,0]))  # the component's pixels
                candidates.append((i,float(cent[k,0]),effective_height,hue,
                                   max(float(cent[k,0])-x,x+w-1-float(cent[k,0]))))
        if allow_tinted_boxes:
            # Reuse the existing pale-highlight detector, which requires a
            # filled tall box tinted relative to its own paper, not a bright
            # background-video column. Conditional plates use narrow markers.
            from app.pipeline.page_diff import _tinted_highlight_boxes
            for i,hsv in enumerate(hsvs):
                if i not in tinted:
                    tinted[i]=_tinted_highlight_boxes(hsv,gap=gap)
                for x,y,w,h in tinted[i]:
                    region=hsv[y:y+h,x:x+w]
                    paper_sat=float(np.median(hsv[...,1]))
                    valid=(region[...,1]>=paper_sat+18)&(region[...,1]<=130)&(region[...,2]>=110)
                    if valid.any():
                        hue=float(np.median(region[...,0][valid]))
                        candidates.append((i,x+(w-1)/2,h,hue,w/2))
        for seed in range(0,180,15):
            chosen={}
            for i,x,h,hue,half_width in candidates:
                distance=min(abs(hue-seed),180-abs(hue-seed))
                if distance<=15 and (i not in chosen or h>chosen[i][1]):
                    chosen[i]=(x,h,half_width)
            seq=sorted(chosen)
            if len(seq)<3:
                continue
            for direction in (1,-1):
                length={};prior={}
                for i in seq:
                    prev=[j for j in seq if j<i and direction*(chosen[i][0]-chosen[j][0])>=-.25*gap]
                    j=max(prev,key=lambda j:length[j],default=None)
                    length[i]=1+(length[j] if j is not None else 0);prior[i]=j
                end=max(seq,key=lambda i:length[i]);track=[]
                while end is not None:
                    track.append(end);end=prior[end]
                track=sorted(track)
                if len(track)<max(3,int(np.ceil(.6*len(seq)))):
                    continue
                xs=[chosen[i][0] for i in track];span=float(np.ptp(xs))
                if span<=gap:
                    continue
                score=len(track)*np.sqrt(span/gap)
                if best is None or score>best[0]:
                    best=(score,CursorPositions({i:chosen[i][0] for i in track},{i:chosen[i][2] for i in track}))
        if best is not None:
            break
    return best[1] if best is not None else {}


def co_moving_cursor_masks(masks: Dict[int,np.ndarray], positions: Dict[int,float], gap: float, *,
                           witness_masks: Optional[Dict[int,np.ndarray]] = None) -> Dict[int,np.ndarray]:
    """Raw support that follows the marker at different x positions in >=80% of witnesses."""
    out={}
    near_masks={j:_dilate(mask,1) for j,mask in (witness_masks or masks).items() if j in positions}
    for i,mask in masks.items():
        if i not in positions:
            continue
        radius=max(2*gap+3,getattr(positions,"half_widths",{}).get(i,0)+2)
        ys,xs=np.nonzero(mask & (np.abs(np.arange(mask.shape[1])-positions[i])<=radius)[None,:])
        if not len(xs):
            continue
        votes=np.zeros(len(xs),int);eligible=np.zeros(len(xs),int);groups=0
        for j,other in masks.items():
            if j==i or j not in positions or abs(positions[j]-positions[i])<=gap:
                continue
            qx=np.rint(xs+positions[j]-positions[i]).astype(int)
            valid=(qx>=0)&(qx<mask.shape[1])
            if not valid.any():
                continue
            groups+=1
            eligible[valid]+=1;votes[valid]+=near_masks[j][ys[valid],qx[valid]]
        if groups<2:
            continue
        recurring=(eligible>=2)&(votes>=np.ceil(.8*eligible))
        result=np.zeros_like(mask);result[ys[recurring],xs[recurring]]=True
        result=_drop_small(result,min_extent=1)
        if result.any():out[i]=result
    return out


def _cursor_residual_registration(source: np.ndarray, other: np.ndarray, source_mask: np.ndarray,
                                  other_mask: np.ndarray, box: Sequence[int], gap: float) -> Optional[float]:
    """Masked 25-shift SSD and axis parabola fits, in work pixels; None is unknown.

    Use the full height and at least max(8*gap,64) columns around the footprint.
    A common mask keeps both cursor footprints and the image border out of
    every candidate's SSD. Texture is measured after smoothing out gray noise.
    """
    h,w = source.shape
    radius = 2
    width = max(64,int(np.ceil(8*gap)),int(box[2]-box[0]))
    start = int(np.floor((box[0]+box[2]-width)/2))
    a,b = max(radius+1,start),min(w-radius-1,start+width)
    c,d = radius+1,h-radius-1
    if a>=b or c>=d:
        return None
    margin = radius+1
    hidden = _dilate(source_mask[:,a-margin:b+margin] | other_mask[:,a-margin:b+margin],margin)
    free = ~hidden[c:d,margin:margin+b-a]
    src = source[:,a-margin:b+margin].astype(np.float32)
    dst = other[:,a-margin:b+margin].astype(np.float32)
    smooth = cv2.GaussianBlur(src,(5,5),1.0)
    gx = cv2.Sobel(smooth,cv2.CV_32F,1,0,ksize=3,scale=1/8)
    gy = cv2.Sobel(smooth,cv2.CV_32F,0,1,ksize=3,scale=1/8)
    textured = np.hypot(gx[c:d,margin:margin+b-a],gy[c:d,margin:margin+b-a])>8
    if np.count_nonzero(textured & free)<200:
        return None
    local = src[c:d,margin:margin+b-a]
    costs = np.empty((5,5),np.float64)
    for dy in range(-radius,radius+1):
        for dx in range(-radius,radius+1):
            delta = local-dst[c+dy:d+dy,margin+dx:margin+b-a+dx]
            costs[dy+radius,dx+radius] = np.sum(np.square(delta),where=free,dtype=np.float64)
    # An exact zero-shift match needs no biased finite-window interpolation.
    if costs[radius,radius]==0:
        return 0.0
    yy,xx = np.unravel_index(np.argmin(costs),costs.shape)
    if yy in (0,4) or xx in (0,4):
        return None
    shifts = []
    for before,center,after,index in ((costs[yy,xx-1],costs[yy,xx],costs[yy,xx+1],xx),
                                      (costs[yy-1,xx],costs[yy,xx],costs[yy+1,xx],yy)):
        curvature = before-2*center+after
        if not np.isfinite(curvature) or curvature<=0:
            return None
        shifts.append(index-radius+0.5*(before-after)/curvature)
    return float(np.hypot(*shifts))


def recovered_cursor_event(event: Dict[str, Any], masks: Dict[int, np.ndarray], grays: Dict[int, np.ndarray],
                           reference: np.ndarray, positions: Dict[int, float], gap: float, *,
                           ink_ceiling: Optional[float] = None,
                           colors: Optional[Dict[int,np.ndarray]] = None,
                           witness_masks: Optional[Dict[int,np.ndarray]] = None,
                           allow_partial: bool = False, max_residual_px: float = 0.5,
                           native_scale: float = 1.0,
                           member_shifts: Optional[Dict[int, Tuple[float, float]]] = None) -> Optional[Dict[str, Any]]:
    """Recover tracked footprints from two clear, locally registered witnesses.

    ``native_scale`` is the manifest's work_scale (work pixels / native pixels),
    so measured work residuals are divided by it. The caller pops the sole
    numpy evidence value, ``_recovered_mask``, before JSON persistence.
    ``member_shifts`` may be passed by reflow_strips: global subpixel shifts in
    work pixels against one common reference; a pair uses their difference.
    """
    if not np.isfinite(native_scale) or native_scale <= 0 or not np.isfinite(max_residual_px) or max_residual_px < 0:
        raise ValueError('invalid cursor recovery scale or residual limit')
    witnesses = []
    witness_residuals = {}
    covered = []
    h, w = reference.shape
    recovered = np.zeros((h,w),bool)
    offered = np.zeros((h,w),bool)
    for i in event['members']:
        x0, y0, x1, y1 = event['box']
        part = event_member_mask(event,i,masks[i])[y0:y1, x0:x1]
        py, px = np.nonzero(part)
        offered[py+y0,px+x0] = True
        if i not in positions or not len(px) or np.max(np.abs(px + x0 - positions[i])) > max(2.0*gap+3,getattr(positions,"half_widths",{}).get(i,0)+2):
            if allow_partial:
                continue
            return None
        # The event box can merge many cursor positions. Recovery belongs to
        # this member's actual footprint, not to the temporal union rectangle.
        mx0,mx1 = int(px.min()+x0),int(px.max()+x0+1)
        my0,my1 = int(py.min()+y0),int(py.max()+y0+1)
        a, b = max(0, mx0 - int(gap)), min(w, mx1 + int(gap))
        c, d = max(0, my0 - int(gap)), min(h, my1 + int(gap))
        templates=[]
        color_templates=[]
        reference_templates=[]
        source_rgb=colors[i][py+y0,px+x0].astype(np.int16) if colors is not None else None
        for j in grays:
            if j==i or j not in positions:
                continue
            qx=np.rint(px+x0+positions[j]-positions[i]).astype(int)
            if np.all((qx>=0)&(qx<w)):
                templates.append(np.minimum.reduce([grays[j][py+y0,np.clip(qx+dx,0,w-1)] for dx in (-1,0,1)]))
                reference_templates.append(reference[py+y0,qx])
                if colors is not None:
                    samples=np.stack([colors[j][py+y0,np.clip(qx+dx,0,w-1)] for dx in (-1,0,1)],axis=1).astype(np.int16)
                    current_chroma=source_rgb-source_rgb.mean(axis=1,keepdims=True)
                    sample_chroma=samples-samples.mean(axis=2,keepdims=True)
                    if np.max(np.abs(current_chroma))<5:
                        distances=np.abs(samples-source_rgb[:,None,:]).max(axis=2)
                    else:
                        distances=np.abs(sample_chroma-current_chroma[:,None,:]).max(axis=2)
                    if witness_masks is not None:
                        changed=np.stack([witness_masks[j][py+y0,np.clip(qx+dx,0,w-1)] for dx in (-1,0,1)],axis=1)
                        distances=np.where(changed,distances,np.inf)
                    # One registration offset for the whole component. Do not
                    # warp isolated novel dots into a neighbouring cursor edge.
                    # Missing template support must count against an offset;
                    # a nearby isolated dot cannot beat the whole cursor by
                    # matching only its few pixels and ignoring the rest.
                    score=np.mean(np.where(np.isfinite(distances),distances,255),axis=0)
                    choice=int(np.argmin(score))
                    color_templates.append(sample_chroma[:,choice])
                    matched_x=np.clip(qx+choice-1,0,w-1)
                    templates[-1]=grays[j][py+y0,matched_x]
                    reference_templates[-1]=reference[py+y0,matched_x]
        if len(templates)<2:
            if allow_partial:
                continue
            return None
        template=np.median(np.stack(templates),axis=0)
        source_values=grays[i][py+y0,px+x0].astype(float)
        reference_values=reference[py+y0,px+x0].astype(float)
        source_lost=source_values<reference_values-50
        # A lighter cursor edge over paper is expected when donor locations
        # contain black notation. Chroma is invariant to that gray backdrop.
        donor_reference=np.median(np.stack(reference_templates),axis=0)
        darkest=template-np.maximum(0,donor_reference-reference_values)
        lightest=template+np.maximum(0,reference_values-donor_reference)
        novel=((source_values<darkest-15) | (source_values>lightest+15))&source_lost
        if color_templates:
            palette=np.stack(color_templates)
            center=np.median(palette,axis=0)
            mad=np.median(np.abs(palette-center),axis=0)
            tolerance=np.minimum(CURSOR_APPEARANCE_TOL,np.maximum(15,3*mad))
            current_chroma=source_rgb-source_rgb.mean(axis=1,keepdims=True)
            color_novel=(np.abs(current_chroma-center)>tolerance).any(axis=1)
            achromatic=np.max(np.abs(center),axis=1)<5
            novel |= color_novel&source_lost
            novel |= achromatic&(np.abs(source_values-template)>15)&source_lost
        novelty=np.zeros_like(part)
        novelty[py[novel],px[novel]]=True
        if not allow_partial and _drop_small(novelty,min_extent=1).any():
            return None
        clear = [j for j in grays if j != i and j in positions and abs(positions[j] - positions[i]) > 2 * gap
                 and not a - gap <= positions[j] <= b + gap]
        if len(clear) < 2:
            if allow_partial:
                continue
            return None
        # Every clear witness must agree with recovered notation locally, including a dot
        # hidden underneath the cursor. Pixel tolerance is the existing 1-px registration.
        ref = reference[c:d, a:b]
        paper = float(np.percentile(ref, 75))
        threshold = ink_ceiling if ink_ceiling is not None else paper - 60
        ref_ink = ref < threshold
        ref_dark = _dilate(ref_ink, 1)
        footprint = np.zeros(ref.shape,bool)
        footprint[py+y0-c,px+x0-a] = True
        near_footprint = _dilate(footprint,1)
        supports = []
        qualifying = []
        for j in clear:
            raw = grays[j][c:d, a:b]
            raw_ink = raw < threshold
            lost = raw_ink & ~ref_dark & near_footprint
            missing = ref_ink & ~_dilate(raw_ink,1) & near_footprint
            lost_ink = _drop_small(lost, min_extent=1)
            if not allow_partial and lost_ink.any():
                return None
            # A missing donor mask uses this member's footprint at the donor x.
            if j in masks:
                donor_mask = masks[j]
            else:
                donor_mask = np.zeros((h,w),bool)
                sy,sx = np.nonzero(masks[i])
                qx = np.rint(sx+positions[j]-positions[i]).astype(int)
                valid = (qx>=0)&(qx<w)
                donor_mask[sy[valid],qx[valid]] = True
            donor = donor_mask[c:d,a:b]
            if member_shifts is not None and i in member_shifts and j in member_shifts:
                residual = float(np.linalg.norm(np.asarray(member_shifts[i],float)-np.asarray(member_shifts[j],float)))
            else:
                residual = _cursor_residual_registration(grays[i],grays[j],masks[i],donor_mask,
                                                         [mx0,my0,mx1,my1],gap)
            if residual is None or not np.isfinite(residual) or residual/native_scale > max_residual_px:
                continue
            residual /= native_scale
            free = ~donor
            # A reference dot shown by only one donor is still an open
            # obligation, even when that donor already reached the composite.
            agreeing = free & ~_dilate(lost | missing,1) if allow_partial else free & ~_dilate(missing,1)
            support = agreeing[py+y0-c,px+x0-a] & ~novel if allow_partial else agreeing[py+y0-c,px+x0-a]
            if support.any():
                supports.append(support)
                qualifying.append((j,residual))
        if len(qualifying)<2 or np.ptp([positions[j] for j,_ in qualifying])<=1:
            if allow_partial:
                continue
            return None
        votes = np.stack(supports)
        cursor_x = np.array([positions[j] for j,_ in qualifying])[:,None]
        distinct = (np.max(np.where(votes,cursor_x,-np.inf),axis=0)
                    - np.min(np.where(votes,cursor_x,np.inf),axis=0))>1
        kept = (votes.sum(axis=0)>=2)&distinct
        if not allow_partial and not kept.all():
            return None
        recovered[py[kept]+y0,px[kept]+x0] = True
        if kept.any():
            covered.append(i)
            for (j,r),support in zip(qualifying,supports):
                if (support & kept).any():
                    witnesses.append(j)
                    witness_residuals[j] = max(r,witness_residuals.get(j,0.0))
    if not recovered.any():
        return None
    evidence = {"kind": "monotonic_colored_cursor_with_clear_score_recovery", "covered_members": covered,
            "clear_members": sorted(set(witnesses)),
            "template_members": sorted(set(grays) & set(positions)),
            "template_outlier_drop": CURSOR_APPEARANCE_TOL, "source_ink_contrast": 60, "ink_ceiling":ink_ceiling,
            "color_template_checked":colors is not None,"color_feature":"RGB_minus_mean",
            "color_noise_floor":15,"color_mad_multiple":3,"gray_backdrop_adjusted":True,
            "score_registration_tolerance_px": 1, "recovery_scope":"own_component_footprint",
            "positions": [[i, round(x, 3)] for i, x in positions.items()],
            "witnesses": [{"member":int(j),"cursor_x":float(positions[j]),
                           "residual_registration_px":round(witness_residuals[j],3)} for j in sorted(set(witnesses))],
            "_recovered_mask":recovered}
    if allow_partial and np.any(offered & ~recovered):
        evidence["partial"] = True
    return evidence


def event_member_mask(event: Dict[str, Any], member: int, fallback: np.ndarray) -> np.ndarray:
    """Exact event-cluster pixels of one owning observation (boxes may overlap)."""
    support = event.get("support_by_member")
    if support is None:
        return fallback
    out = np.zeros_like(fallback)
    for owner in support:
        if owner["member"] == member:
            for y,a,b in owner["spans"]:
                out[y,a:b] = True
    return out


def ink_like_support(owners: Sequence[Dict[str, Any]], gray_of, dark_max: float) -> List[Dict[str, Any]]:
    """Ink-like subset of each owner's raw support, for conditional plate cuts.

    ``gray_of(owner)`` returns (normalized gray evidence, its crop-coordinate
    origin). The same resolver serves live observations and saved PNG replay.
    A small black dot inside broad gray background must not be averaged away.
    """
    result = []
    for owner in owners:
        gray, origin = gray_of(owner)
        ox, oy = origin
        mask = np.zeros(gray.shape, bool)
        for y,a,b in owner.get("spans_crop", []):
            yy=max(0,int(y)-int(oy));x0=max(0,int(a)-int(ox));x1=min(gray.shape[1],int(b)-int(ox))
            if 0 <= int(y)-int(oy) < gray.shape[0] and x0 < x1:
                mask[yy,x0:x1] = gray[yy,x0:x1] <= dark_max
        mask = _drop_small(mask,min_extent=1)
        spans = support_runs(mask,origin)
        if spans:
            result.append({"obs_id":owner.get("obs_id"),"spans_crop":spans})
    return result
