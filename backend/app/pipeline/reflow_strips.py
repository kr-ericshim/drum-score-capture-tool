"""Clean system strips for the reflow chart (output model ``clean_reflow_v1``).

One strip per system occurrence (reflow_occurrences.py): the system's full
notation envelope (notes, marks, lyrics, section labels, tempo text), cropped
from the observations of that one display and cleaned:

* Envelope: ``notation_envelope.frame_envelope`` on up to three member crops
  (the same component rules that keep circles, accents, text lines and
  lyrics), union, padded 0.75 staff gap top/bottom and 0.5 gap at the sides,
  clamped to the crop. Nothing inside the box is erased.
* Preview tail: when the row ends with the start of the next system (a break
  in all five staff lines followed by a percussion clef in the right third of
  the row), the strip may stop in an empty column of that break. The
  destination must be the next INCLUDED occurrence. The cut is made only when
  every pixel it removes - the full strip height of the cut columns, not just
  the staff band - is verified to be drawn at the start of that occurrence:
  the tail band is registered first, then every removed non-staff ink
  component (any size) must be drawn there (``verify_removed_pixels``), and
  the destination's own strip box must hold the moved ink. The record maps the
  cut columns to the destination and keeps the uncut strip (``uncut``), which
  the composer uses when the destination is no longer the next placed system
  (reflow_pipeline.resolve_dependencies). Otherwise nothing is cut and the
  system is flagged ``PREVIEW_TAIL_UNVERIFIED`` for review.
* Overlay removal (2-D, STRATEGY Step 2B): members of the one display are
  aligned to a reference (phase correlation, < 0.5 px, no resampling); fade or
  transition members (paper >= 10 levels below the display's median) are
  neither the reference nor in the median, and the reference is the member that
  agrees best with the others. Each pixel takes the median of the members whose
  overlay (overlay_composite.overlay_mask_2d: bands as rows, translucent boxes
  as boxes; plus page_diff's overlay mask) does not cover it. Pixels covered in
  every member take the plain median and are counted (``unrecovered_px`` /
  ``unrecovered_columns``, inside the final strip only). The median does not
  register members, so persistent ink drawn +-1 px apart (a thin stroke cycling
  rows 5, 6, 7) can vanish from it: ink a majority of members show within
  +-1 px (outside their overlay masks) that the composite lacks is restored
  from one representative member (``restore_lost_ink``), reported as
  ``ink_restored`` (pixels, boxes, source observations) and its rows are kept.
* Screen-fixed chrome (overlay_composite.screen_fixed_chrome: colored pixels at
  one screen place with one color across displays with different notation, e.g.
  a preview inset's frame band or a player icon) is not an overlay to recover and
  not notation. The detector's mask is never an erase mask: in a display that
  shows the chrome in place, a pixel is paper-filled only where the composite
  and every member show paper or the chrome's own steady colors there
  (``settle_chrome``). Anything else in or touching a chrome area (ink of any
  darkness or tint) is kept with its surroundings, its rows are never trimmed,
  and the strip gets ``OVERLAY_COVERS_NOTATION`` (``screen_chrome`` in the record).
* Minority content: every member's full owned ROI/rows is inventoried before
  cropping. Missing foreground, including outside-crop and rejected fade or
  registration hypotheses, is retained in one lossless review bundle per system
  with raw crops, support, coordinates, times and eligibility dispositions.
  Positive cursor recovery, chrome appearance or transition geometry can explain
  evidence; sampling, proximity, timing and rejection alone cannot delete it.
  Rejected members stay outside the composition and support denominators; local
  re-registration only helps classify their raw evidence.
* Dark themes are inverted to dark ink on light paper (``dark_theme_cleanup``). On opaque
  dark paper, lighter persistent notation (gray dynamics, text) is kept - judged by contrast
  against the local plate and persistence across the members, not by a gray cutoff; what
  cannot be separated is kept and flagged ``LOW_CONTRAST_CONTENT_KEPT``. Video showing
  through a translucent score band is whitened away from the ink. Paper tone is flattened
  with paper_tone.flatten_paper_background, and every kept component is checked to survive
  the finishing (``CONTENT_LOST_IN_FINISHING`` otherwise).

Coordinates: crop pixels of the observation manifest; boxes are half-open.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
import inspect
import os
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import minority_content as mc
from app.pipeline import notation_envelope as ne
from app.pipeline import overlay_composite as oc
from app.pipeline import page_diff
from app.pipeline import reflow_ledger as rl
from app.pipeline import system_detect as sd
from app.pipeline.overlay_composite import _MAX_MEMBERS, _MAX_SHIFT_PX, _alignment_gray, _overlay_columns
from app.pipeline.paper_tone import flatten_paper_background

STRIPS_VERSION = "reflow_strips-1"
PAD_V_GAPS = 0.75
PAD_H_GAPS = 0.5
ENVELOPE_SAMPLES = 3
PREVIEW_MAX_FRACTION = 0.35
DARK_INK_MAX = 110  # system_tracking.CLEAN_INK_MAX: video behind a translucent dark band is lighter than this after inversion

ImageLoader = Callable[[Dict[str, Any]], np.ndarray]


def _evenly(items: Sequence[Any], count: int) -> List[Any]:
    if len(items) <= count:
        return list(items)
    idx = sorted(set(np.linspace(0, len(items) - 1, count).round().astype(int).tolist()))
    return [items[i] for i in idx]


def _region(obs: Dict[str, Any], region_id: str) -> Dict[str, Any]:
    return next(r for r in obs["system_regions"] if r["region_id"] == region_id)


def row_envelope_on_crop(crop: np.ndarray, region: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The notation_envelope row of ``crop`` that matches ``region``'s staff."""
    fr = ne.frame_envelope(crop)
    g = float(region["staff_gap_px"])
    top = float(region["staff_y"][0])
    best = None
    for row in fr["rows"]:
        d = abs(float(row["staff_y"][0]) - top)
        if d <= 1.5 * g and (best is None or d < best[0]):
            best = (d, row)
    return best[1] if best else None


def staff_breaks(ink: np.ndarray, staff_y: Sequence[float], x0: int, x1: int, *, min_len: int = 3) -> List[Tuple[int, int]]:
    """Column runs inside [x0, x1) where all five staff lines are absent (a gap in
    one line - a notehead gap, a worn line - is not a break)."""
    h, w = ink.shape
    any_present = np.zeros(max(0, x1 - x0), dtype=bool)
    for y in staff_y:
        r = int(round(y))
        lo, hi = max(0, r - 1), min(h, r + 2)
        if hi > lo:
            any_present |= ink[lo:hi, x0:x1].any(axis=0)
    runs = []
    start = None
    for i, p in enumerate(any_present):
        if not p and start is None:
            start = i
        elif p and start is not None:
            if i - start >= min_len:
                runs.append((x0 + start, x0 + i))
            start = None
    if start is not None and len(any_present) - start >= min_len:
        runs.append((x0 + start, x0 + len(any_present)))
    return runs


def staff_end(region: Dict[str, Any]) -> int:
    """Right end of the row's staff including every segment (a preview segment of the
    next system after a break is part of the row's content)."""
    ends = [int(region["staff_x"][1])] + [int(seg[1]) for seg in (region.get("segments") or []) if len(seg) >= 2]
    return max(ends)


def find_preview_tail(norm: np.ndarray, region: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Start of the next system shown at the right end of this row, or None.

    Requires a break in all five staff lines in the right ``PREVIEW_MAX_FRACTION``
    of the staff, followed by a percussion clef. A staff line that simply
    continues (no break) is never cut.
    """
    ink = sd.ink_mask(norm)
    g = float(region["staff_gap_px"])
    sx0, sx1 = int(region["staff_x"][0]), staff_end(region)
    width = sx1 - sx0
    if width < 10 * g:
        return None
    lo = int(sx1 - PREVIEW_MAX_FRACTION * width)
    for b0, b1 in staff_breaks(ink, region["staff_y"], lo, int(sx1 - 2 * g)):
        st = {"lines": list(region["staff_y"]), "gap": g, "x": [b1, sx1]}
        if sd.has_percussion_clef(ink, st):
            return {"cut_x": int(b0), "next_staff_x": int(b1), "kind": "next_system_start"}
    return None


PREVIEW_MIN_COVER = 0.95  # non-matching dense grooves reach 0.82-0.88 in the fixtures


def _staff_band(img: np.ndarray, region: Dict[str, Any], x0: int, x1: int, gap: float) -> Tuple[np.ndarray, int]:
    """Cleaned rows top-3g .. bottom+3g of ``img`` (crop) between columns x0..x1, and the band's top row."""
    from app.pipeline.system_tracking import clean_content
    top = int(round(float(region["staff_y"][0]) - 3 * gap))
    bot = int(round(float(region["staff_y"][4]) + 3 * gap))
    h, w = img.shape[:2]
    band = np.full((bot - top, max(0, x1 - x0), 3), 255, np.uint8)
    lo, hi = max(0, top), min(h, bot)
    a, b = max(0, x0), min(w, x1)
    if hi > lo and b > a:
        band[lo - top:hi - top, a - x0:b - x0] = clean_content(img[lo:hi, a:b]) if img.ndim == 3 else img[lo:hi, a:b]
    return band, top


def verify_preview_destination(crop: np.ndarray, region: Dict[str, Any], preview: Dict[str, Any],
                               next_crop: np.ndarray, next_region: Dict[str, Any]) -> Dict[str, Any]:
    """Is the preview tail (columns ``next_staff_x`` .. staff end of ``crop``) drawn at the
    start of the next occurrence (``next_crop``/``next_region``)?

    Both bands are cleaned, staff lines removed; the tail's non-staff ink must be
    covered (>= ``PREVIEW_MIN_COVER``, 0.15-gap tolerance) by the next occurrence's
    ink at one registration offset (+-2 gaps horizontally, +-0.3 gap vertically,
    anchored at each row's first staff line and staff start). Returns the coverage
    and the mapping from tail columns to the next occurrence's crop columns."""
    from app.pipeline.reflow_occurrences import _nonstaff_ink, _overlay_columns_of
    g = float(region["staff_gap_px"])
    ng = float(next_region["staff_gap_px"])
    if abs(g - ng) > 0.08 * max(g, ng):
        return {"verified": False, "reason": "staff_size_differs"}
    tx0, tx1 = int(preview["next_staff_x"]), staff_end(region)
    tail, _ = _staff_band(crop, region, tx0, tx1, g)
    t_ink = _nonstaff_ink(tail, g)
    t_ink[:, _overlay_columns_of(tail)] = False
    n_t = int(t_ink.sum())
    if n_t < max(6, int(round(0.5 * g * g))):
        return {"verified": False, "reason": "no_content_in_tail"}
    nx0 = int(next_region["staff_x"][0])
    pad = int(round(2 * g))
    dest, _ = _staff_band(next_crop, next_region, nx0 - pad, nx0 + (tx1 - tx0) + pad, g)
    d_ink = _nonstaff_ink(dest, g).astype(np.uint8)
    r = max(1, int(round(0.15 * g)))
    d_ink = cv2.dilate(d_ink, np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0
    th, tw = t_ink.shape
    best = (0.0, 0, 0)
    vy = max(1, int(round(0.3 * g)))
    for dy in range(-vy, vy + 1):
        for dx in range(0, 2 * pad + 1):
            win = np.zeros_like(t_ink)
            ys0, ys1 = max(0, dy), min(th, d_ink.shape[0] + dy)
            if ys1 <= ys0:
                continue
            seg = d_ink[ys0 - dy:ys1 - dy, dx:dx + tw]
            win[ys0:ys1, :seg.shape[1]] = seg
            cov = float((t_ink & win).sum()) / n_t
            if cov > best[0]:
                best = (cov, dx - pad, dy)
    cov, dx, dy = best
    out = {"verified": cov >= PREVIEW_MIN_COVER, "coverage": round(cov, 3), "tail_ink_px": n_t,
           # tail crop column x  ->  destination crop column x - next_staff_x + dest_x0
           "dest_x0": nx0 + dx, "dest_dy_px": dy}
    if not out["verified"]:
        out["reason"] = "tail_not_found_at_next_start"
    return out


PREVIEW_COMPONENT_MIN = 0.9  # share of each removed ink component the destination must draw
REFINE_PX = 2  # registration refinement of the removed pixels around the band offset


def _colored(img: np.ndarray) -> np.ndarray:
    if img.ndim != 3:
        return np.zeros(img.shape[:2], bool)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return (hsv[..., 1] > 80) & (hsv[..., 2] > 60)


def _empty_cut_column(comp: np.ndarray, lo: int, hi: int) -> Optional[int]:
    """Middle of the widest run of columns in [lo, hi) with no ink in any row of ``comp``
    (colored overlay pixels are not ink), or None."""
    from app.pipeline.system_tracking import clean_content
    lo, hi = max(0, lo), min(comp.shape[1], hi)
    if hi <= lo:
        return None
    seg = clean_content(comp[:, lo:hi])
    gray = cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY)
    ink = (gray < 200) & ~_colored(seg)
    empty = ~ink.any(axis=0)
    best, start = None, None
    for i, e in enumerate(list(empty) + [False]):
        if e and start is None:
            start = i
        elif not e and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return None if best is None else lo + (best[0] + best[1]) // 2


def verify_removed_pixels(removed: np.ndarray, origin: Tuple[int, int], region: Dict[str, Any], preview: Dict[str, Any],
                          band_check: Dict[str, Any], next_crop: np.ndarray, next_region: Dict[str, Any]) -> Dict[str, Any]:
    """Are ALL the pixels a preview-tail cut removes drawn by the destination?

    ``removed``: the composited strip pixels that the cut would remove (every row of the
    strip box, columns ``cut_x`` .. box right end), ``origin`` their top-left crop
    coordinate. They are cleaned, staff lines removed, colored overlay columns skipped;
    every remaining ink component (any size) must have >= ``PREVIEW_COMPONENT_MIN`` of its
    pixels drawn by the destination crop at the registration of ``band_check``
    (``verify_preview_destination``) refined by up to ``REFINE_PX``, and all of them together
    >= ``PREVIEW_MIN_COVER``. Pixels that map outside the destination crop count as not drawn,
    except within the registration tolerance of the crop edge, where the destination's edge
    column is taken to continue (a staff start line cut by the region edge)."""
    from app.pipeline.reflow_occurrences import _cover_mask, _nonstaff_ink, _overlay_columns_of
    from app.pipeline.system_tracking import clean_content
    g = float(region["staff_gap_px"])
    clean = clean_content(removed) if removed.size else removed
    f = _nonstaff_ink(clean, g) if removed.size else np.zeros(removed.shape[:2], bool)
    if f.size:
        f[:, _overlay_columns_of(clean)] = False
    n, lab, stats, _c = cv2.connectedComponentsWithStats(f.astype(np.uint8), connectivity=8)
    if n <= 1:
        return {"verified": True, "removed_components": 0, "removed_ink_px": 0}
    off_x = int(band_check["dest_x0"]) - int(preview["next_staff_x"])
    off_y = int(round(float(next_region["staff_y"][0]) - float(region["staff_y"][0]))) + int(band_check.get("dest_dy_px", 0))
    h, w = f.shape
    dest_clean = clean_content(next_crop)
    dest_clean[_colored(dest_clean)] = 255  # a playhead over the destination draws nothing
    H, W = dest_clean.shape[:2]
    area = np.bincount(lab.ravel(), minlength=n).astype(np.float64)
    best = None
    # one registration for all removed pixels: the band's offset refined by up to REFINE_PX
    # (the band was matched with a dilated mask; slivers and beams need the exact offset)
    for ry in range(-REFINE_PX, REFINE_PX + 1):
        for rx in range(-REFINE_PX, REFINE_PX + 1):
            X0, Y0 = int(origin[0]) + off_x + rx, int(origin[1]) + off_y + ry
            win = np.full((h, w, 3), 255, np.uint8)
            a0, b0, a1, b1 = max(0, Y0), max(0, X0), min(H, Y0 + h), min(W, X0 + w)
            inside = np.zeros((h, w), bool)
            if a1 > a0 and b1 > b0:
                win[a0 - Y0:a1 - Y0, b0 - X0:b1 - X0] = dest_clean[a0:a1, b0:b1]
                inside[a0 - Y0:a1 - Y0, b0 - X0:b1 - X0] = True
            # the destination crop edge: ink touching it continues for the registration tolerance
            r = max(1, int(round(0.15 * g)))
            if b0 - X0 > 0 and b1 > b0:
                inside[:, max(0, b0 - X0 - r):b0 - X0] = True
                win[:, max(0, b0 - X0 - r):b0 - X0] = win[:, b0 - X0:b0 - X0 + 1]
            cover = _cover_mask(win, g) & inside
            drawn = np.bincount(lab[cover].ravel(), minlength=n).astype(np.float64)
            frac = drawn / np.maximum(area, 1.0)
            n_bad = int((frac[1:] < PREVIEW_COMPONENT_MIN).sum())
            key = (-n_bad, float(drawn[1:].sum()), -abs(rx) - abs(ry))
            if best is None or key > best[0]:
                best = (key, frac, drawn, X0, Y0, rx, ry)
    _key, frac, drawn, X0, Y0, rx, ry = best
    bad = [i for i in range(1, n) if frac[i] < PREVIEW_COMPONENT_MIN]
    total = float(drawn[1:].sum()) / max(1.0, float(area[1:].sum()))
    ys, xs = np.nonzero(f)
    out = {"verified": not bad and total >= PREVIEW_MIN_COVER, "removed_components": int(n - 1), "removed_ink_px": int(area[1:].sum()),
           "removed_coverage": round(total, 3), "min_component_fraction": round(float(frac[1:].min()), 3), "refined_px": [rx, ry],
           # the removed ink, mapped into destination crop pixels (clamped to the crop: ink
           # within the edge tolerance is drawn by the destination's edge column)
           "dest_ink_box_crop": [max(0, int(xs.min()) + X0), max(0, int(ys.min()) + Y0),
                                 min(W, int(xs.max()) + 1 + X0), min(H, int(ys.max()) + 1 + Y0)]}
    if bad:
        i = min(bad, key=lambda k: frac[k])
        x, y, ww, hh, a = (int(v) for v in stats[i])
        out.update(reason="removed_ink_not_at_destination", unexplained_components=len(bad),
                   component_box_crop=[x + int(origin[0]), y + int(origin[1]), x + ww + int(origin[0]), y + hh + int(origin[1])],
                   component_area_px=a)
    elif not out["verified"]:
        out["reason"] = "removed_ink_coverage_low"
    return out


def _overlay_cols(img: np.ndarray, gap: float) -> np.ndarray:
    """Columns covered by a playback overlay (colored band/box or gray playhead)."""
    cols = _overlay_columns(img)
    norm, _ = sd.normalize_polarity(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    ink = page_diff._ink_mask(gray)
    no_staff = page_diff._remove_staff_lines(ink, gap=gap)
    mask, _cursor = page_diff._overlay_mask(norm, no_staff, gap=gap)
    if mask.any():
        mcols = mask.any(axis=0)
        k = np.ones(2 * max(2, int(round(0.15 * gap))) + 1, dtype=np.uint8)
        mcols = cv2.dilate(mcols.astype(np.uint8)[None, :], k[None, :])[0] > 0
        cols = cols | mcols
    return cols


def _overlay_cols_of(img: np.ndarray, gap: float, key: Optional[Any], memo: Optional[Dict[Any, np.ndarray]]) -> np.ndarray:
    """``_overlay_cols`` remembered under ``key`` (an observation id and crop box: the same pixels)."""
    if memo is None or key is None:
        return _overlay_cols(img, gap)
    k = (key, float(gap))
    if k not in memo:
        memo[k] = _overlay_cols(img, gap)
    return memo[k].copy()


def _overlay_mask2d(img: np.ndarray, gap: float, *, normalized: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> np.ndarray:
    """2-D mask of a playback overlay in one crop: colored overlays (overlay_composite.overlay_mask_2d:
    bands as their rows, translucent boxes as their box) plus page_diff's overlay mask (gray
    playheads, tinted highlight boxes), dilated by about 0.15 gap. Pixels to recover from other
    members, never pixels to erase. ``normalized``: (normalize_polarity(img)[0], its gray) when
    the caller already has them for exactly these pixels."""
    mask = oc.overlay_mask_2d(img)
    if normalized is None:
        norm, _ = sd.normalize_polarity(img)
        gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    else:
        norm, gray = normalized
    ink = page_diff._ink_mask(gray)
    no_staff = page_diff._remove_staff_lines(ink, gap=gap)
    pmask, _cursor = page_diff._overlay_mask(norm, no_staff, gap=gap)
    if pmask.any():
        r = max(2, int(round(0.15 * gap)))
        mask = mask | (cv2.dilate((pmask > 0).astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0)
    return mask


def _without_chrome(img: np.ndarray, chrome: Optional[np.ndarray]) -> np.ndarray:
    """``img`` with its chrome pixels painted as the surrounding paper, so overlay detection
    sees only what moves (an icon does not merge with a passing cursor into one box)."""
    if chrome is None:
        return img
    out = img.copy()
    free = ~mc._dilate(chrome, 2)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if free.any():
        lvl = float(np.percentile(gray[free], 75 if float(np.median(gray[free])) >= 110 else 25))
        sel = free & (np.abs(gray.astype(np.int16) - int(lvl)) <= 10)
        paper = np.median(img[sel], axis=0) if sel.any() else img[free].mean(axis=0)
        out[chrome] = np.rint(paper).astype(np.uint8)
    return out


def _overlay_mask2d_of(img: np.ndarray, gap: float, key: Optional[Any], memo: Optional[Dict[Any, np.ndarray]],
                       chrome: Optional[np.ndarray] = None, *, over_chrome: bool = False,
                       normalized: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> np.ndarray:
    """``_overlay_mask2d`` of ``img`` without its chrome, remembered in ``memo`` (kept apart from the
    column masks of ``_overlay_cols_of``). The result never covers a chrome pixel unless
    ``over_chrome`` (where a transient overlay passes over the chrome). ``normalized``: the
    polarity-normalized ``img`` and its gray, used only without chrome (the same pixels)."""
    ck = None if chrome is None else (int(chrome.sum()), chrome.shape)
    nz = normalized if chrome is None else None
    if memo is None or key is None:
        m = _overlay_mask2d(_without_chrome(img, chrome), gap, normalized=nz)
    else:
        k = ("mask2d", key, float(gap), ck)
        if k not in memo:
            memo[k] = _overlay_mask2d(_without_chrome(img, chrome), gap, normalized=nz)
        m = memo[k]
    return m & ~chrome if chrome is not None and not over_chrome else m


# Registration prediction in check_minority_content (an unambiguous prediction skips one full-resolution
# phase correlation; anything else is registered exactly).
PREDICT_MIN_RESPONSE = 0.8        # both phase correlations must respond at least this strongly
PREDICT_GEOMETRY_PX = 1.0         # predicted vertical shift vs the member's staff rows (track geometry)
PREDICT_MAX_SHIFT_FRACTION = 0.5  # predicted shift below this share of _MAX_SHIFT_PX

FADE_PAPER_DROP = 10.0  # a member whose paper is this much darker than the display's median is a fade/transition frame


def paper_levels(images: Sequence[np.ndarray]) -> List[float]:
    """Paper level (75th percentile gray after polarity normalisation) of each image."""
    out = []
    for im in images:
        norm, _ = sd.normalize_polarity(im)
        out.append(float(np.percentile(cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY), 75)))
    return out


def compose_members(images: List[np.ndarray], gap: float, *, keys: Optional[Sequence[Any]] = None,
                    memo: Optional[Dict[Any, np.ndarray]] = None,
                    chrome: Optional[np.ndarray] = None, ledger_members: bool = False) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Overlay-free composite of aligned crops of one display (same shape).

    * Fade/transition members (paper ``FADE_PAPER_DROP`` below the members' median) are
      neither the pixel reference nor in the median.
    * Overlays are masked per pixel (``_overlay_mask2d``), not as whole columns: each pixel
      takes the median of the members that do not cover it; a pixel no member clears keeps
      the plain median of all members (``unrecovered_px`` / ``unrecovered_columns``).
    * ``chrome`` (screen-fixed chrome in this crop, overlay_composite.screen_fixed_chrome) is
      not a transient overlay: no member can clear it, so it takes the plain median and is
      settled by ``settle_chrome`` (never counted as unrecovered).
    ``keys``/``memo``: see ``_overlay_cols_of``."""
    n = len(images)
    h, w = images[0].shape[:2]
    chrome = chrome if chrome is not None and chrome.shape == (h, w) and chrome.any() else None
    masks = [_overlay_mask2d_of(im, gap, keys[i] if keys is not None else None, memo, chrome) for i, im in enumerate(images)]
    papers = paper_levels(images)
    med_paper = float(np.median(papers)) if papers else 0.0
    faded = [p < med_paper - FADE_PAPER_DROP for p in papers]
    # the pixel reference: a member that agrees best with the others where it is not covered (an
    # outlier frame - a transition, another line shown for a moment - is never the reference)
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in images]
    pool = [i for i in range(n) if not faded[i]] or list(range(n))
    med_gray = np.median(np.stack([grays[i] for i in pool]), axis=0)
    disagree = []
    for i in range(n):
        free = ~masks[i]
        d = np.abs(grays[i].astype(np.float32) - med_gray)
        disagree.append(float(d[free].mean()) if free.any() else 255.0)
    order = sorted(range(n), key=lambda i: (faded[i], round(disagree[i], 1), int(masks[i].sum()), abs(i - n // 2)))
    ref_i = order[0]
    ref = images[ref_i]
    info: Dict[str, Any] = {"members_offered": n, "reference_index": ref_i,
                            "faded_members": int(sum(faded)),
                            "paper_levels": [round(p, 1) for p in papers]}
    if chrome is not None:
        info["chrome_px"] = int(chrome.sum())
    if n < 2:
        unrec = masks[ref_i]
        info.update(members_used=1, unrecovered_px=int(unrec.sum()), unrecovered_columns=int(unrec.any(axis=0).sum()),
                    composited=False, _unrecovered_mask=unrec)
        info["ink_restored"] = {"px": 0, "components": 0, "boxes": [], "member_indices": []}
        if ledger_members:
            info["_ledger_members"] = [{"index": 0, "key": keys[0] if keys is not None else None,
                "phase_shift": [0.0, 0.0], "faded": faded[0], "used": True,
                "overlay_mask": masks[0], "chrome_mask": chrome}]
        return ref.copy(), info
    ref_gray = _alignment_gray(ref)
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    # OpenCV's phaseCorrelate reports a constant sub-pixel offset (about 0.5 px on
    # some sizes) even for an image against itself; measure shifts relative to it.
    base, _r = cv2.phaseCorrelate(ref_gray.copy(), ref_gray.copy(), window)
    usable = [ref_i]
    shifts = []
    phase_shifts = {ref_i: [0.0, 0.0]}
    phase_responses = {ref_i: float(_r)}
    for i, im in enumerate(images):
        if i == ref_i or (faded[i] and not ledger_members):
            continue
        shift, _resp = cv2.phaseCorrelate(ref_gray.copy(), _alignment_gray(im), window)
        rel = (shift[0] - base[0], shift[1] - base[1])
        phase_shifts[i] = [float(v) for v in rel]
        phase_responses[i] = float(_resp)
        if faded[i]:
            continue
        shifts.append(round(float(np.hypot(*rel)), 3))
        if np.isfinite(rel).all() and np.hypot(*rel) < _MAX_SHIFT_PX:
            usable.append(i)
    info["max_rel_shift_px"] = max(shifts) if shifts else 0.0
    stack = np.stack([images[i] for i in usable])
    m = np.stack([masks[i] for i in usable])
    out = np.rint(np.median(stack, axis=0)).astype(np.uint8) if len(usable) > 1 else ref.copy()
    all_cov = m.all(axis=0)
    some = m.any(axis=0) & ~all_cov
    if some.any():
        ys, xs = np.nonzero(some)
        vals = stack[:, ys, xs].astype(np.float32)  # members x pixels x 3
        vals[m[:, ys, xs]] = np.nan
        out[ys, xs] = np.rint(np.nanmedian(vals, axis=0)).astype(np.uint8)
    unrec = all_cov
    if all_cov.any():
        # every member covers it: the plain median of the members stays (static content is kept,
        # an overlay shown by a minority of them drops out); counted below
        if chrome is not None:
            # the overlay masks fill a solid object's box and grow (page_diff pads tinted boxes by
            # 0.3 gap, then 0.15 gap): around a chrome object they cover the chrome's own steady
            # surroundings in every member. Steady pixels there are not a covered overlay.
            _n, _lab, stats = chrome_objects(chrome)
            zone = np.zeros_like(chrome)
            for k in range(1, _n):
                x, y, bw, bh, _a = (int(v) for v in stats[k])
                zone[y:y + bh, x:x + bw] = True
            zone = mc._dilate(zone, int(round(0.45 * gap)) + oc.OVERLAY_MASK_DILATE_PX + 1)
            span = (stack.max(axis=0).astype(np.int16) - stack.min(axis=0).astype(np.int16)).max(axis=-1)
            steady = all_cov & zone & (span <= CHROME_STEADY_SPAN)
            unrec = all_cov & ~steady
            info["chrome_steady_px"] = int(steady.sum())
    restored = restore_lost_ink(out, [images[i] for i in usable], [masks[i] for i in usable],
                                ref_index=0) if len(usable) > 1 else _no_restore()
    info.update(members_used=len(usable), unrecovered_px=int(unrec.sum()),
                unrecovered_columns=int(unrec.any(axis=0).sum()), recovered_px=int(some.sum()),
                composited=len(usable) > 1, _unrecovered_mask=unrec)
    info["ink_restored"] = {"px": restored["px"], "components": restored["components"], "boxes": restored["boxes"],
                            "member_indices": [usable[j] for j in restored["members"]]}
    if ledger_members:
        info["_ledger_members"] = [{"index": i, "key": keys[i] if keys is not None else None,
            "phase_shift": phase_shifts[i], "phase_response": phase_responses.get(i),
            "faded": faded[i], "used": i in usable,
            "overlay_mask": masks[i], "chrome_mask": chrome} for i in range(n)]
    return out, info


LOST_INK_DROP = 50  # a member pixel this much darker than anything the composite shows within +-1 px is ink the median lost


def _no_restore() -> Dict[str, Any]:
    return {"px": 0, "components": 0, "boxes": [], "members": []}


def restore_lost_ink(out: np.ndarray, images: Sequence[np.ndarray], masks: Sequence[np.ndarray], *,
                     ref_index: int = 0) -> Dict[str, Any]:
    """Persistent ink the per-pixel median erased, put back in place (``out`` is modified).

    The median does not register members: a thin stroke or small mark drawn one pixel apart in
    each member (+-1 px jitter, e.g. rows 5, 6 and 7) is in no pixel's majority, so the median
    shows paper there. A member pixel is *lost ink* when it is ``LOST_INK_DROP`` darker (after
    polarity normalisation) than the darkest composite pixel within +-1 px, outside that member's
    overlay mask, and lost ink is shown at the same place (+-1 px) by a majority of the members
    that are evidence there (not covered by their overlay). A transient overlay (a cursor, a
    playhead) moves between members and is masked, so it is never restored. Each connected
    component (at least ``minority_content.MIN_COMPONENT_PX`` px over the members) takes the lost
    pixels of ONE representative member - the one whose lost pixels lie best on the majority
    (highest mean vote; ties: the most pixels, then ``ref_index``) - never a blend. Returns the
    diagnostic: restored pixel count, components, their boxes [x0, y0, x1, y1] (half-open, crop
    of ``out``) and the representative member of each (index into ``images``)."""
    res = _no_restore()
    n = len(images)
    if n < 2:
        return res
    _norm, inv = sd.normalize_polarity(images[ref_index])

    def gray_of(img: np.ndarray) -> np.ndarray:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.int16)
        return 255 - g if inv else g

    out_min = cv2.erode(gray_of(out).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.int16)
    lost = []
    for im, m in zip(images, masks):
        lost.append((gray_of(im) < out_min - LOST_INK_DROP) & ~m)
    if not any(l.any() for l in lost):
        return res
    votes = np.zeros(out.shape[:2], np.int32)
    evid = np.zeros(out.shape[:2], np.int32)
    for l, m in zip(lost, masks):
        votes += mc._dilate(l, 1) & ~m
        evid += ~m
    persistent = (votes * 2 > evid) & (evid > 0)
    lost = [l & persistent for l in lost]
    union = np.zeros(out.shape[:2], bool)
    for l in lost:
        union |= l
    if not union.any():
        return res
    n_c, lab, st, _c = cv2.connectedComponentsWithStats(mc._dilate(union, 1).astype(np.uint8), connectivity=8)
    for c in range(1, n_c):
        x, y, bw, bh, _a = (int(v) for v in st[c])
        zone = lab[y:y + bh, x:x + bw] == c
        if int((union[y:y + bh, x:x + bw] & zone).sum()) < mc.MIN_COMPONENT_PX:
            continue
        best = None
        for j, l in enumerate(lost):
            sel = l[y:y + bh, x:x + bw] & zone
            cnt = int(sel.sum())
            if cnt == 0:
                continue
            score = (round(float(votes[y:y + bh, x:x + bw][sel].mean()), 3), cnt, j == ref_index)
            if best is None or score > best[0]:
                best = (score, j, sel)
        if best is None or best[0][1] < mc.MIN_COMPONENT_PX:
            continue
        _s, j, sel = best
        sub = out[y:y + bh, x:x + bw]
        sub[sel] = images[j][y:y + bh, x:x + bw][sel]
        ys, xs = np.nonzero(sel)
        res["px"] += int(sel.sum())
        res["components"] += 1
        res["boxes"].append([x + int(xs.min()), y + int(ys.min()), x + int(xs.max()) + 1, y + int(ys.max()) + 1])
        res["members"].append(j)
    return res


OVERLAY_COVERS_NOTATION = "OVERLAY_COVERS_NOTATION"
CHROME_STEADY_SPAN = 30       # max-min over the members: the pixel did not change
CHROME_PRESENT_SHARE = 0.5    # chrome counts in a display where at least half of its members show it
CHROME_IN_PLACE = 0.9         # ... and what the display shows around it lies on the chrome


CHROME_GROUP_PX = 4  # chrome pieces this close are one object (a dashed frame with its glyph)


def chrome_objects(chrome: np.ndarray) -> Tuple[int, np.ndarray, np.ndarray]:
    """Connected chrome objects (pieces within ``CHROME_GROUP_PX`` joined); labels only on chrome pixels."""
    r = CHROME_GROUP_PX
    grown = cv2.dilate(chrome.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8))
    n, lab, stats, _c = cv2.connectedComponentsWithStats(grown, connectivity=8)
    lab = np.where(chrome, lab, 0)
    # boxes of the chrome pixels themselves (not of the grown mask)
    for k in range(1, n):
        ys, xs = np.nonzero(lab == k)
        if len(xs):
            stats[k] = [xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, len(xs)]
        else:
            stats[k] = [0, 0, 0, 0, 0]
    return n, lab, stats


def display_chrome(crops: Sequence[np.ndarray], chrome: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """The part of the job's chrome mask this display actually shows: chrome pixels near
    (``oc.CHROME_DILATE_PX`` + 1) pixels colored in at least ``CHROME_PRESENT_SHARE`` of the
    members. A chrome place where this display shows notation instead (an editor icon that
    sits elsewhere on this line) is not chrome here."""
    if chrome is None or not chrome.any():
        return None
    same = [c for c in crops if c.shape[:2] == chrome.shape]
    if not same:
        return None
    shown = np.mean(np.stack([oc.colored_pixels(c) for c in same]), axis=0) >= CHROME_PRESENT_SHARE
    near_chrome = mc._dilate(chrome, 1)
    n, lab, stats = chrome_objects(chrome)
    H, W = chrome.shape
    eff = np.zeros_like(chrome)
    for k in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[k])
        if area == 0:
            continue
        obj = lab == k
        m = 2 * CHROME_GROUP_PX
        wy0, wy1, wx0, wx1 = max(0, y - m), min(H, y + bh + m), max(0, x - m), min(W, x + bw + m)
        win = shown[wy0:wy1, wx0:wx1]
        total = int(win.sum())
        if total == 0:
            continue  # not shown in this display
        inside = int((win & near_chrome[wy0:wy1, wx0:wx1]).sum())
        covered = int((obj & mc._dilate(shown, oc.CHROME_DILATE_PX + 1)).sum())
        # shown in place: what this display shows there lies on the chrome, and covers most of it
        # (an object drawn a little elsewhere in this display is left alone, not cut in half)
        if inside >= CHROME_IN_PLACE * total and covered >= 0.5 * area:
            eff |= obj
    return eff if eff.any() else None


CHROME_PALETTE_SHARE = 0.15   # a chrome object's own colors: each covers this share of its colored pixels
CHROME_PALETTE_BIN = 24       # color quantization for the palette
CHROME_MATCH_TOL = 30.0       # BGR distance from the paper-to-chrome-color blend line: chrome or paper here
CHROME_KEEP_GAPS = 0.5        # around unexplained content in a chrome area nothing is filled


def _paper_color(img: np.ndarray, free: np.ndarray) -> np.ndarray:
    """Paper color of ``img`` (BGR, as shown: light or dark theme) from the pixels in ``free``."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sel = free if free.any() else np.ones(gray.shape, bool)
    lvl = float(np.percentile(gray[sel], 75 if float(np.median(gray[sel])) >= 110 else 25))
    near = sel & (np.abs(gray.astype(np.int16) - int(round(lvl))) <= 10)
    return (np.median(img[near], axis=0) if near.any() else img[sel].mean(axis=0)).astype(np.float32)


def chrome_palette(images: Sequence[np.ndarray], obj: np.ndarray) -> np.ndarray:
    """The chrome object's own steady colors (k x 3 BGR): of the members' per-pixel median inside
    ``obj``, the colored pixels (overlay_composite.colored_pixels) grouped by quantized color; each
    color covering at least ``CHROME_PALETTE_SHARE`` of them. A mark of another tint inside the
    object (a minority of its colored pixels) is not part of its appearance."""
    med = np.median(np.stack(images), axis=0).astype(np.uint8) if len(images) > 1 else images[0]
    col = oc.colored_pixels(med) & obj
    if not col.any():
        return np.zeros((0, 3), np.float32)
    vals = med[col].astype(np.int32)
    q = vals // CHROME_PALETTE_BIN
    keys = (q[:, 0] * 64 + q[:, 1]) * 64 + q[:, 2]
    uniq, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    keep = np.flatnonzero(counts >= CHROME_PALETTE_SHARE * len(keys))
    return np.array([vals[inv.reshape(-1) == k].mean(axis=0) for k in keep], np.float32).reshape(-1, 3)


def _blend_distance(p: np.ndarray, paper: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Distance of colors ``p`` (k x 3) from the line paper -> ``c`` (3 or k x 3)."""
    d = c - paper
    dd = np.maximum((d * d).sum(axis=-1), 1e-6)
    a = np.clip(((p - paper) * d).sum(axis=-1) / dd, 0.0, 1.0)
    return np.linalg.norm(p - (paper + a[..., None] * d), axis=-1)


def nearest_appearance(appearance: np.ndarray) -> np.ndarray:
    """Per pixel: the chrome appearance (``screen_fixed_chrome``'s mean color) of the nearest pixel
    where it is known (the colored core); NaN when nothing is known."""
    known = np.isfinite(appearance).all(axis=-1)
    if not known.any():
        return np.full(appearance.shape, np.nan, np.float32)
    _d, lab = cv2.distanceTransformWithLabels((~known).astype(np.uint8), cv2.DIST_L2, 3,
                                              labelType=cv2.DIST_LABEL_PIXEL)
    ky, kx = np.nonzero(known)
    # labels number the zero (known) pixels in row-major scan order, from 1
    return appearance[ky, kx][lab - 1]


def chrome_explained(img: np.ndarray, sel: np.ndarray, palette: np.ndarray, paper: np.ndarray,
                     reference: Optional[np.ndarray] = None) -> np.ndarray:
    """Per pixel of ``sel``: the pixel shows only paper or the chrome's own appearance - within
    ``CHROME_MATCH_TOL`` of the line from the paper color to the chrome's color there (an
    anti-aliased edge is a blend of the two). The chrome's color is the job-level appearance of
    the nearest chrome core pixel (``reference``, H x W x 3, from ``nearest_appearance``) where
    known, else any ``palette`` color. Ink of any darkness or tint (a faint gray mark, a colored
    mark of another hue) is off the line."""
    out = np.zeros(sel.shape, bool)
    ys, xs = np.nonzero(sel)
    if not len(ys):
        return out
    p = img[ys, xs].astype(np.float32)
    best = np.linalg.norm(p - paper[None], axis=1)
    if reference is not None:
        ref = reference[ys, xs].astype(np.float32)
        ok = np.isfinite(ref).all(axis=1)
        if ok.any():
            best[ok] = np.minimum(best[ok], _blend_distance(p[ok], paper[None], ref[ok]))
        use_palette = ~ok
    else:
        use_palette = np.ones(len(ys), bool)
    if use_palette.any():
        for c in palette:
            best[use_palette] = np.minimum(best[use_palette], _blend_distance(p[use_palette], paper[None], c[None]))
    out[ys, xs] = best <= CHROME_MATCH_TOL
    return out


CHROME_NEIGHBOUR_PX = 3      # a chrome-area pixel may blend the chrome colors this close to it (anti-aliasing, JPEG)
CHROME_LUMA_TOL = 15.0
CHROME_NEUTRAL_CHROMA = 20.0  # a pixel this close to gray has no hue of its own to compare
CHROME_HUE_COS = 0.7


def _luma(c: np.ndarray) -> np.ndarray:
    return c[..., 0] * 0.114 + c[..., 1] * 0.587 + c[..., 2] * 0.299


def chrome_neighbourhood(appearance: np.ndarray, zone: np.ndarray) -> Optional[Dict[str, Any]]:
    """Per pixel of ``zone``'s bounding box: the luma range and the colors of the chrome
    appearance known within ``CHROME_NEIGHBOUR_PX`` (see ``chrome_blend_explained``)."""
    ys, xs = np.nonzero(zone)
    if not len(ys):
        return None
    r = CHROME_NEIGHBOUR_PX
    H, W = zone.shape
    y0, y1, x0, x1 = max(0, ys.min() - r), min(H, ys.max() + 1 + r), max(0, xs.min() - r), min(W, xs.max() + 1 + r)
    a = appearance[y0:y1, x0:x1].astype(np.float32)
    known = np.isfinite(a).all(axis=-1)
    lum = _luma(np.nan_to_num(a))
    k = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    lmin = cv2.erode(np.where(known, lum, 1e4).astype(np.float32), k, borderType=cv2.BORDER_CONSTANT, borderValue=1e4)
    lmax = cv2.dilate(np.where(known, lum, -1e4).astype(np.float32), k, borderType=cv2.BORDER_CONSTANT, borderValue=-1e4)
    chroma = np.where(known[..., None], a - a.mean(axis=-1, keepdims=True), np.nan)
    return {"box": (y0, y1, x0, x1), "lmin": lmin, "lmax": lmax, "chroma": chroma, "known": known}


def chrome_blend_explained(img: np.ndarray, sel: np.ndarray, nb: Optional[Dict[str, Any]], paper: np.ndarray) -> np.ndarray:
    """Per pixel of ``sel``: a blend of paper and the chrome colors known within
    ``CHROME_NEIGHBOUR_PX`` (``chrome_neighbourhood``) - an anti-aliased or JPEG-smeared chrome
    edge, whose hue is lost or shifted. Its luma lies within the range of those colors and paper
    (+-``CHROME_LUMA_TOL``), and a pixel with a hue (chroma above ``CHROME_NEUTRAL_CHROMA``)
    has the hue of one of them (cosine >= ``CHROME_HUE_COS``) and no more chroma than it.
    Darker ink (a gray-150 mark in a light band) and ink of another hue are not explained. A
    neutral mark whose luma lies within that range is indistinguishable from a smeared edge."""
    out = np.zeros(sel.shape, bool)
    if nb is None:
        return out
    y0, y1, x0, x1 = nb["box"]
    s = sel[y0:y1, x0:x1]
    if not s.any():
        return out
    p = img[y0:y1, x0:x1].astype(np.float32)
    lp = _luma(p)
    pl = float(_luma(paper.astype(np.float32)))
    lo = np.minimum(nb["lmin"], pl) - CHROME_LUMA_TOL
    hi = np.maximum(nb["lmax"], pl) + CHROME_LUMA_TOL
    ok = s & (lp >= lo) & (lp <= hi)
    cp = p - p.mean(axis=-1, keepdims=True)
    mag = np.linalg.norm(cp, axis=-1)
    hued = ok & (mag > CHROME_NEUTRAL_CHROMA)
    if hued.any():
        r = CHROME_NEIGHBOUR_PX
        chroma, known = nb["chroma"], nb["known"]
        h, w = known.shape
        match = np.zeros(hued.shape, bool)
        hy, hx = np.nonzero(hued)
        cv_ = cp[hy, hx]
        mv = mag[hy, hx]
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                yy, xx = hy + dy, hx + dx
                inside = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
                yy, xx = np.clip(yy, 0, h - 1), np.clip(xx, 0, w - 1)
                kn = inside & known[yy, xx]
                if not kn.any():
                    continue
                cn = chroma[yy, xx]
                mn = np.linalg.norm(np.nan_to_num(cn), axis=-1)
                cos = (np.nan_to_num(cn) * cv_).sum(axis=-1) / np.maximum(mn * mv, 1e-6)
                good = kn & (cos >= CHROME_HUE_COS) & (mv <= mn + CHROME_NEUTRAL_CHROMA)
                match[hy[good], hx[good]] = True
        ok &= ~hued | match
    out[y0:y1, x0:x1] = ok
    return out


def _components_of_area(mask: np.ndarray, min_px: int = mc.MIN_COMPONENT_PX) -> np.ndarray:
    """Components of at least ``min_px`` pixels, of any width or height (a 1-px stroke counts)."""
    if not mask.any():
        return mask
    n, lab, stats, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_px
    return keep[lab]


def settle_chrome(comp: np.ndarray, crops: Sequence[np.ndarray], chrome: Optional[np.ndarray],
                  gap: float, appearance: Optional[np.ndarray] = None,
                  overlays: Optional[Sequence[Optional[np.ndarray]]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Screen-fixed chrome (a preview frame band, a player icon) never enters the primary score,
    and the chrome detector's mask is never an erase mask.

    A pixel of a chrome area (the area and a 1-px touch ring around it) is *explained* when the
    composite and every member show there only paper or the chrome's own steady appearance
    (``appearance``: the job-level mean color of the chrome's colored core, crop-aligned with
    ``comp``; without it, the object's dominant colors, ``chrome_palette``; ``chrome_explained``). Anything else - ink of any darkness or tint,
    components of at least ``minority_content.MIN_COMPONENT_PX`` pixels - is unexplained content:
    a component at least 2 px in both directions shown in any member, and a component only 1 px
    wide or tall (a thin stroke) shown at the same place (+-1 px) in a majority of the members
    that are evidence there. Size alone is never evidence of noise; a thin component that a
    majority does not show is registration/JPEG residue. Only
    explained area pixels farther than ``CHROME_KEEP_GAPS`` gap from unexplained content are
    paper-filled; the rest of the area is kept as it is and its box is reported in ``touched``
    (the caller flags ``OVERLAY_COVERS_NOTATION``). ``overlays`` (aligned with ``crops``): each
    member's transient overlay mask (a cursor box passing over the chrome); a member is no
    evidence where its overlay covers the pixel (the composite, their median, still is). ``_kept_mask`` marks the kept pixels of
    touched areas (the caller keeps their rows when trimming). Returns (image, info)."""
    info: Dict[str, Any] = {"chrome_px": 0, "filled_px": 0, "kept_px": 0, "areas": 0, "touched": []}
    if chrome is None or chrome.shape != comp.shape[:2] or not chrome.any():
        return comp, info
    info["chrome_px"] = int(chrome.sum())
    n_lab, lab, _stats = chrome_objects(chrome)
    info["areas"] = int(n_lab - 1)
    pairs_ = [(c, overlays[i] if overlays is not None and i < len(overlays) else None)
              for i, c in enumerate(crops) if c.shape == comp.shape]
    imgs = [comp] + [c for c, _o in pairs_]
    covers = [None] + [o if o is not None and o.shape == chrome.shape else None for _c, o in pairs_]
    free = ~mc._dilate(chrome, 2)
    papers = [_paper_color(im, free) for im in imgs]
    r_keep = max(2, int(round(CHROME_KEEP_GAPS * float(gap))))
    reference = nearest_appearance(appearance) if appearance is not None and appearance.shape[:2] == chrome.shape else None
    norm, inv = sd.normalize_polarity(comp)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    paper_lvl = float(np.percentile(gray[free], 75)) if free.any() else float(np.percentile(gray, 75))
    paper_px = free & (gray >= paper_lvl - 10)
    paper = np.median(norm[paper_px], axis=0) if paper_px.any() else np.array([255, 255, 255], np.float64)
    fill = np.rint(255 - paper if inv else paper).astype(np.uint8)
    out = comp.copy()
    filled = np.zeros(chrome.shape, bool)
    kept = np.zeros(chrome.shape, bool)
    for a in range(1, n_lab):
        area = lab == a
        if not area.any():
            continue
        zone = mc._dilate(area, 1)  # the area and its 1-px touch ring
        palette = chrome_palette(imgs[1:] or imgs, area)
        nb = chrome_neighbourhood(appearance, zone) if reference is not None else None
        unexplained = np.zeros(chrome.shape, bool)
        thin = np.zeros(chrome.shape, bool)
        per_member: List[Tuple[np.ndarray, np.ndarray]] = []  # (unexplained components, evidence area)
        for j, (im, pp, cov) in enumerate(zip(imgs, papers, covers)):
            sel = zone & ~cov if cov is not None else zone
            u = sel & ~chrome_explained(im, sel, palette, pp, reference)
            if u.any() and nb is not None:
                u &= ~chrome_blend_explained(im, u, nb, pp)
            u_all = _components_of_area(u)
            if j > 0 or len(imgs) == 1:
                per_member.append((u_all, sel))
            if u_all.any():
                solid = mc._drop_small(u_all)
                unexplained |= solid
                thin |= u_all & ~solid
        if thin.any():
            # A component one pixel wide or tall (a thin stem, a staff line, a gray stroke) is
            # content like any other; size is no evidence of noise. It is noise (JPEG ringing,
            # registration residue) only when it is not shown at the same place (+-1 px) in a
            # majority of the members that are evidence there.
            votes = np.zeros(chrome.shape, np.int32)
            evid = np.zeros(chrome.shape, np.int32)
            for u_all, sel in per_member:
                votes += mc._dilate(u_all, 1) & sel
                evid += sel
            persistent = (votes * 2 > evid) & (evid > 0)
            n_t, lab_t, st_t, _c = cv2.connectedComponentsWithStats(thin.astype(np.uint8), connectivity=8)
            ok = np.zeros(n_t, bool)
            for t in range(1, n_t):
                comp_t = lab_t == t
                ok[t] = int((comp_t & persistent).sum()) * 2 >= int(st_t[t, cv2.CC_STAT_AREA])
            unexplained |= ok[lab_t]
        if unexplained.any():
            keep = area & mc._dilate(unexplained, r_keep)
            keep |= unexplained  # content in the touch ring keeps its rows too
            kept |= keep
            ys, xs = np.nonzero(keep | (unexplained & area))
            if len(ys):
                info["touched"].append([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])
            else:  # content only in the touch ring, nothing of the area near it: still reported
                ys, xs = np.nonzero(unexplained)
                info["touched"].append([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])
            filled |= area & ~keep
        else:
            filled |= area
    out[filled] = fill
    info["filled_px"] = int(filled.sum())
    info["kept_px"] = int(kept.sum())
    info["_kept_mask"] = kept
    return out, info


LOW_CONTRAST_KEPT = "LOW_CONTRAST_CONTENT_KEPT"
CONTENT_LOST_IN_FINISHING = "CONTENT_LOST_IN_FINISHING"
FAINT_PAPER_DROP = 60      # a pixel this much darker than the paper level is a content candidate
FAINT_CONTRAST_MIN = 25    # a faint component less than this darker than its local plate is plate tone
FAINT_CONTRAST_KEEP = 45   # ... at least this much darker is clearly separated from the plate
FAINT_RING_GAPS = 0.5      # the local plate: a ring this wide around the component
FAINT_MAX_STROKE_GAPS = 1.2  # thicker than this (a filled area, not a stroke or notehead) is not a glyph
FAINT_PRESENT_SHARE = 0.5  # persistent: shown at the same place (+-1 px) by more than this share of the members
PLATE_HALFTONE_MAX = 0.01  # opaque plate: at most this share of the strip lies between paper and content
PLATE_HALFTONE_BAND = 15   # ... (lighter than paper - FAINT_PAPER_DROP, darker than paper - this), away from ink
GLYPH_STROKE_GAPS = 0.6    # translucent plate diagnostics: a thin, glyph-like stroke
GLYPH_RING_CLEAN = 0.9     # ... on clean plate (ring share within PLATE_HALFTONE_BAND of paper)
SURVIVE_SHARE = 0.6        # survival after finishing: share of a component's pixels still darker than paper
_DEFAULT_GAP = 12.0


def _member_grays(members: Optional[Sequence[np.ndarray]], shape: Tuple[int, int], inverted: bool) -> List[np.ndarray]:
    """Members in the composite's polarity, darkest value within +-1 px (registration tolerance)."""
    out = []
    for m in members or ():
        if m is None or m.shape[:2] != shape:
            continue
        g = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY) if m.ndim == 3 else m
        g = (255 - g) if inverted else g
        out.append(cv2.erode(g, np.ones((3, 3), np.uint8)))
    return out


def dark_theme_cleanup(norm: np.ndarray, *, members: Optional[Sequence[np.ndarray]] = None, gap: Optional[float] = None,
                       inverted: bool = True, force_opaque: bool = False) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Cleanup of an inverted dark theme (``norm``: dark ink on light paper). Returns (image, info).

    Dark ink (gray < min(``DARK_INK_MAX``, paper - 60)) and its 2-px anti-aliased edge are always
    kept. Lighter content (darker than paper - ``FAINT_PAPER_DROP``, in connected components) is
    judged by what the plate is:

    * **Opaque dark paper** (at most ``PLATE_HALFTONE_MAX`` of the strip lies in the half-tone band
      between content and paper, away from ink): nothing shows through the paper, so a lighter
      component is notation (gray dynamics, text) unless the evidence says otherwise - its
      contrast against the local plate (median of a ring ``FAINT_RING_GAPS`` gap wide) is below
      ``FAINT_CONTRAST_MIN`` or it is a filled area thicker than ``FAINT_MAX_STROKE_GAPS`` gaps
      (plate tone), or the composite's ``members`` (crops of the same box) show it at the same
      place (+-1 px, same contrast against their own plate) in no more than ``FAINT_PRESENT_SHARE``
      of them (unstable). Persistent with contrast >= ``FAINT_CONTRAST_KEEP``: kept. Otherwise
      (no member evidence, or contrast between the limits): kept and flagged
      (``LOW_CONTRAST_CONTENT_KEPT``), never whitened silently.
    * **Translucent plate** (more half-tone: video shows through): static video behind the plate
      (a drum stand, a rim) is as persistent and as separated as gray text on the plate, so no
      member evidence separates them; lighter content is whitened as before (calibrated on
      bF69tpnUk5w: video at gray 110-150 after inversion). Glyph-like components among them
      (persistent, thin, on clean plate, contrast >= ``FAINT_CONTRAST_KEEP``) are counted in
      ``translucent_glyphlike`` with their boxes, for review.

    info ``_notation_mask`` marks the kept content (dark ink and kept lighter components), for
    the survival check after finishing (``finishing_survival``)."""
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    paper = float(np.percentile(gray, 75))
    ink = gray < min(DARK_INK_MAX, paper - 60)
    keep = cv2.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    g = float(gap) if gap and gap > 0 else _DEFAULT_GAP
    mgs = _member_grays(members, (h, w), inverted)
    evidence = len(mgs) >= 3
    halftone = float(((gray >= paper - FAINT_PAPER_DROP) & (gray < paper - PLATE_HALFTONE_BAND) & ~keep).mean())
    opaque = halftone <= PLATE_HALFTONE_MAX or force_opaque
    info: Dict[str, Any] = {"paper": round(paper, 1), "plate": "opaque" if opaque else "translucent",
                            "forced_opaque": bool(force_opaque),
                            "halftone_share": round(halftone, 5), "members": len(mgs), "faint_components": 0,
                            "kept": 0, "kept_flagged": 0, "whitened_plate": 0, "whitened_unstable": 0,
                            "whitened_translucent": 0, "translucent_glyphlike": 0,
                            "kept_boxes": [], "flagged_boxes": [], "glyphlike_boxes": []}
    faint = (gray < paper - FAINT_PAPER_DROP) & ~ink
    notation = ink.copy()
    if faint.any():
        # filled areas thicker than a stroke (video shading, a plate gradient) are plate tone;
        # strokes attached to them are judged on their own
        k = max(3, int(round(FAINT_MAX_STROKE_GAPS * g)) | 1)
        filled = cv2.morphologyEx(faint.astype(np.uint8), cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
        if filled.any():
            info["whitened_plate"] += int(cv2.connectedComponents(filled.astype(np.uint8))[0] - 1)
            faint &= ~mc._dilate(filled, 1)
    if faint.any():
        cand_any = mc._dilate(faint | ink, 1)
        n_c, lab, st, _c = cv2.connectedComponentsWithStats(faint.astype(np.uint8), connectivity=8)
        r = max(3, int(round(FAINT_RING_GAPS * g)))
        for c in range(1, n_c):
            x, y, bw, bh, area = (int(v) for v in st[c])
            if area < mc.MIN_COMPONENT_PX:
                continue
            x0, y0, x1, y1 = max(0, x - r), max(0, y - r), min(w, x + bw + r), min(h, y + bh + r)
            comp = lab[y0:y1, x0:x1] == c
            if (keep[y0:y1, x0:x1] & comp).sum() >= 0.9 * area:
                continue  # the anti-aliased edge of dark ink, kept with it
            info["faint_components"] += 1
            ring = mc._dilate(comp, r) & ~mc._dilate(comp, 1)
            clear_ring = ring & ~cand_any[y0:y1, x0:x1]
            if clear_ring.sum() >= 0.25 * max(1, int(ring.sum())):
                ring = clear_ring
            sub = gray[y0:y1, x0:x1]
            level = float(np.median(sub[comp]))
            plate = float(np.median(sub[ring])) if ring.any() else paper
            contrast = plate - level
            stroke = 2.0 * float(cv2.distanceTransform(comp.astype(np.uint8), cv2.DIST_L2, 3).max())
            box = [x, y, x + bw, y + bh]
            if contrast < FAINT_CONTRAST_MIN or stroke > FAINT_MAX_STROKE_GAPS * g:
                info["whitened_plate"] += 1
                continue
            persistent = None
            if evidence:
                shown = 0
                for mg in mgs:
                    ms = mg[y0:y1, x0:x1]
                    m_level = float(np.median(ms[comp]))
                    m_plate = float(np.median(ms[ring])) if ring.any() else paper
                    if m_plate - m_level >= FAINT_CONTRAST_MIN and abs(m_level - level) <= contrast:
                        shown += 1
                persistent = shown > FAINT_PRESENT_SHARE * len(mgs)
                if not persistent:
                    info["whitened_unstable"] += 1
                    continue
            if not opaque:
                info["whitened_translucent"] += 1
                if (persistent is not False and contrast >= FAINT_CONTRAST_KEEP and stroke <= GLYPH_STROKE_GAPS * g
                        and ring.any() and float((sub[ring] >= paper - PLATE_HALFTONE_BAND).mean()) >= GLYPH_RING_CLEAN):
                    info["translucent_glyphlike"] += 1
                    info["glyphlike_boxes"].append(box)
                continue
            keep[y0:y1, x0:x1] |= mc._dilate(comp, 2)
            notation[y0:y1, x0:x1] |= comp
            if persistent and contrast >= FAINT_CONTRAST_KEEP:
                info["kept"] += 1
                info["kept_boxes"].append(box)
            else:
                info["kept_flagged"] += 1
                info["flagged_boxes"].append(box)
    out = norm.copy()
    out[~keep] = 255
    info["_notation_mask"] = notation
    return out, info


STAFF_SURVIVE_LINES = 3      # a staff survives when at least this many of its lines ...
STAFF_SURVIVE_COVER = 0.5    # ... stay darker than paper over this share of the staff's columns


def staff_survives(img: np.ndarray, staff_y: Sequence[float], x0: int, x1: int) -> bool:
    """The row's staff lines (strip pixels) are still drawn in ``img``."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    if x1 - x0 < 8:
        return True
    paper = float(np.percentile(gray, 75))
    lines = 0
    for y in staff_y:
        yi = int(round(float(y)))
        if not 0 <= yi < h:
            continue
        band = gray[max(0, yi - 1):yi + 2, x0:x1].min(axis=0)
        lines += int(float((band < paper - 40).mean()) >= STAFF_SURVIVE_COVER)
    return lines >= min(STAFF_SURVIVE_LINES, len(staff_y))


def whiten_dark_theme_background(norm: np.ndarray, *, members: Optional[Sequence[np.ndarray]] = None,
                                 gap: Optional[float] = None) -> np.ndarray:
    """``dark_theme_cleanup`` image only."""
    return dark_theme_cleanup(norm, members=members, gap=gap)[0]


def finishing_survival(before: np.ndarray, after: np.ndarray, notation: np.ndarray) -> Dict[str, Any]:
    """Component survival after finishing: every notation component (``notation`` mask on the
    pre-finishing image ``before``) must still be darker than the finished paper in ``after``
    for at least ``SURVIVE_SHARE`` of its pixels. Returns counts and the boxes of lost ones."""
    res: Dict[str, Any] = {"components": 0, "lost": 0, "lost_boxes": []}
    if notation is None or not notation.any() or after.shape[:2] != notation.shape:
        return res
    ga = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY) if after.ndim == 3 else after
    gb = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY) if before.ndim == 3 else before
    paper_a = float(np.percentile(ga, 75))
    paper_b = float(np.percentile(gb, 75))
    n_c, lab, st, _c = cv2.connectedComponentsWithStats(notation.astype(np.uint8), connectivity=8)
    for c in range(1, n_c):
        x, y, bw, bh, area = (int(v) for v in st[c])
        if area < mc.MIN_COMPONENT_PX:
            continue
        comp = lab[y:y + bh, x:x + bw] == c
        res["components"] += 1
        # the component's contrast before finishing, half of it at least after
        need = 0.5 * max(1.0, paper_b - float(np.median(gb[y:y + bh, x:x + bw][comp])))
        dark = ga[y:y + bh, x:x + bw][comp] < paper_a - need
        if dark.mean() < SURVIVE_SHARE:
            res["lost"] += 1
            res["lost_boxes"].append([x, y, x + bw, y + bh])
    return res


def row_cut_lines(norms: Sequence[np.ndarray], region: Dict[str, Any], others: Sequence[Dict[str, Any]], gap: float) -> Tuple[int, int, Dict[str, Any]]:
    """Top and bottom cut rows for a row in a multi-row view (``norms``: polarity-normalized member crops).

    Between this staff and a neighbouring staff the cut is the pixel row with
    the least ink (light anti-aliased text counted), so a label, tempo mark or
    lyric line stays whole with the row it sits next to; among equally empty
    rows the middle of the longest empty run is used. Without a neighbour on a
    side the crop edge is the limit.
    """
    profiles = []
    for norm in norms:  # sampled members; the median ignores a transition frame at a display's edge
        gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
        paper = float(np.percentile(gray, 75))
        profiles.append((gray < paper - 40).sum(axis=1))
    ink_rows = np.median(np.stack(profiles), axis=0).astype(np.int64)
    h = norms[0].shape[0]
    top_staff, bot_staff = float(region["staff_y"][0]), float(region["staff_y"][4])
    above = [o for o in others if float(o["staff_y"][4]) < top_staff]
    below = [o for o in others if float(o["staff_y"][0]) > bot_staff]
    info: Dict[str, Any] = {}

    def cut_between(a: float, b: float) -> Tuple[int, int]:
        lo, hi = int(np.ceil(a + gap)), int(np.floor(b - gap))
        if hi <= lo:
            return int(round((a + b) / 2.0)), -1
        seg = ink_rows[lo:hi]
        m = int(seg.min())
        idx = np.flatnonzero(seg == m)
        runs, start = [], idx[0]
        for p_, q_ in zip(idx, idx[1:]):
            if q_ != p_ + 1:
                runs.append((start, p_))
                start = q_
        runs.append((start, idx[-1]))
        r0, r1 = max(runs, key=lambda r: r[1] - r[0])
        return int(lo + (int(r0) + int(r1)) // 2), int(m)

    top_cut, bottom_cut = 0, h
    if above:
        nb = max(above, key=lambda o: float(o["staff_y"][4]))
        top_cut, info["top_cut_ink"] = cut_between(float(nb["staff_y"][4]), top_staff)
    if below:
        nb = min(below, key=lambda o: float(o["staff_y"][0]))
        bottom_cut, info["bottom_cut_ink"] = cut_between(bot_staff, float(nb["staff_y"][0]))
    return max(0, top_cut), min(h, bottom_cut), info


def trim_blank_rows(strip: np.ndarray, *, keep: Tuple[int, int], pad: int) -> Tuple[np.ndarray, List[int]]:
    """Remove paper-only rows above and below the ink, keeping ``pad`` rows of
    paper and never entering the ``keep`` row range (the notation envelope)."""
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    paper = float(np.percentile(gray, 75))
    ink_rows = np.flatnonzero((gray < min(200, paper - 40)).any(axis=1))
    h = strip.shape[0]
    if not ink_rows.size:
        return strip, [0, 0]
    top = max(0, min(int(ink_rows[0]) - pad, int(keep[0])))
    bot = min(h, max(int(ink_rows[-1]) + 1 + pad, int(keep[1])))
    return strip[top:bot].copy(), [top, h - bot]


MINORITY_ISSUE = "MINORITY_CONTENT_DROPPED"
UNCERTAIN_MARK_KEPT = "UNCERTAIN_MARK_KEPT"
TRANSLUCENT_PLATE_GRAY = "TRANSLUCENT_PLATE_GRAY"
SOURCE_CLIPPED = "SOURCE_CLIPPED"
COLORED_EXPLAINS_GAPS = 0.5  # colored ink explains neutral ink this close to it (strip minority check)


def finish_strip(comp: np.ndarray, *, members: Optional[Sequence[np.ndarray]] = None,
                 gap: Optional[float] = None,
                 staff: Optional[Tuple[Sequence[float], int, int]] = None) -> Tuple[np.ndarray, bool, bool, Dict[str, Any]]:
    """Polarity-normalized, dark-theme-cleaned (``dark_theme_cleanup``), paper-flattened strip
    of a composite, with the component survival check after finishing (``finishing_survival``).
    ``members``: the composite's member crops (same box), the persistence evidence of the dark
    theme cleanup. ``staff``: (staff_y, x0, x1) of the row in composite pixels - when the dark
    theme cleanup of a translucent plate would erase the staff itself (notation lighter than the
    video cutoff: a dimmed or fading display), its lighter content is kept as on opaque paper and
    flagged instead. Returns (image, inverted, paper flattened, info); info ``issues`` lists
    ``LOW_CONTRAST_CONTENT_KEPT`` / ``CONTENT_LOST_IN_FINISHING``."""
    norm, inv = sd.normalize_polarity(comp)
    info: Dict[str, Any] = {"issues": []}
    staff_drawn = staff is not None and staff_survives(norm, *staff)
    if inv:
        cleaned, dinfo = dark_theme_cleanup(norm, members=members, gap=gap)
        if dinfo["plate"] == "translucent" and dinfo["translucent_glyphlike"]:
            info["issues"].append(TRANSLUCENT_PLATE_GRAY)
        if staff_drawn and dinfo["plate"] == "translucent" and not staff_survives(cleaned, *staff):
            cleaned, dinfo = dark_theme_cleanup(norm, members=members, gap=gap, force_opaque=True)
            dinfo["kept_flagged"] += dinfo["kept"]
            dinfo["flagged_boxes"] += dinfo["kept_boxes"]
            dinfo["kept"], dinfo["kept_boxes"] = 0, []
            dinfo["reason"] = "staff_lighter_than_video_cutoff"
        norm = cleaned
        notation = dinfo.pop("_notation_mask")
        info["dark_cleanup"] = dinfo
        if dinfo["kept_flagged"] or dinfo.get("reason"):
            info["issues"].append(LOW_CONTRAST_KEPT)
    else:
        gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
        notation = gray < min(DARK_INK_MAX, float(np.percentile(gray, 75)) - FAINT_PAPER_DROP)
    flat = flatten_paper_background(norm)
    out = flat if flat is not None else norm
    surv = finishing_survival(norm, out, notation)
    if staff_drawn:
        surv["staff"] = staff_survives(out, *staff)
        if not surv["staff"]:
            surv["lost"] += 1
    info["survival"] = surv
    if surv["lost"]:
        info["issues"].append(CONTENT_LOST_IN_FINISHING)
    return out, bool(inv), flat is not None, info


def _finishing_boxes_to_crop(info: Dict[str, Any], origin: Sequence[int]) -> None:
    """``finish_strip`` boxes (composite pixels) -> crop coordinates (``*_boxes_crop``), in place."""
    ox, oy = int(origin[0]), int(origin[1])
    for part, keys in (("dark_cleanup", ("kept_boxes", "flagged_boxes", "glyphlike_boxes")), ("survival", ("lost_boxes",))):
        d = info.get(part) or {}
        for k in keys:
            if k in d:
                d[k + "_crop"] = [[b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy] for b in d.pop(k)]


def source_clipping(raw: np.ndarray, box: Sequence[int], manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ink cut by the video edge, in this strip's columns (before any cleanup).

    Use the frame-edge test's >=6 px / >=2 glyph rule, excluding long thin
    horizontal scaffold. Map pixels back to the frame so an ROI boundary inside
    the frame is never mistaken for a source boundary, including work scaling.
    """
    size = (manifest.get("source") or {}).get("frame_size")
    transform = manifest.get("source_to_crop")
    if not size or not transform:
        return None
    try:
        inverse = np.linalg.inv(np.array(transform, np.float64).reshape(3, 3))
    except (ValueError, np.linalg.LinAlgError):
        return None
    x0, y0, x1, y1 = map(int, box)
    crop = raw[y0:y1, x0:x1]
    if not crop.size:
        return None
    norm, _ = sd.normalize_polarity(crop)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    ink = gray < float(np.percentile(gray, 75)) - 60
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    hits: Dict[str, List[List[int]]] = {s: [] for s in ("top", "bottom", "left", "right")}
    # One crop pixel may represent several source pixels after work downscaling.
    scale = float((manifest.get("work_scale") or {}).get("scale", 1.0) or 1.0)
    tolerance = max(1.0, 1.0 / scale)
    axis_aligned = np.allclose(inverse[[0, 1, 2, 2], [1, 0, 0, 1]], 0.0)
    fw, fh = map(int, size)
    for k in range(1, n):
        x, y, bw, bh, area = map(int, stats[k])
        if area < 6 or (bw > 0.5 * crop.shape[1] and bh <= 4):
            continue
        ys, xs = np.nonzero(lab[y:y + bh, x:x + bw] == k)
        points = np.stack((xs + x + x0, ys + y + y0, np.ones(len(xs))), axis=0)
        src = inverse @ points
        src = src[:2] / src[2:3]
        for side, axis, edge in (("top", 1, 0), ("bottom", 1, fh - 1),
                                 ("left", 0, 0), ("right", 0, fw - 1)):
            # Native paper even one row below a glyph disproves a source cut.
            # A downscaled pixel represents a wider source footprint. Warped
            # crops retain the frame-health interpolation tolerance.
            tol = max(0.01, (abs(float(inverse[axis, axis])) - 1.0) / 2.0) if axis_aligned else tolerance
            if np.any(np.abs(src[axis] - edge) <= tol):
                hits[side].append([x, x + bw])
    sides = [s for s, h in hits.items() if len(h) >= 2]
    if not sides:
        return None
    columns = [b for s in sides for b in hits[s]]
    return {"sides": sides, "columns": [min(b[0] for b in columns), max(b[1] for b in columns)]}


def _finish_strip(comp: np.ndarray, *, members: Optional[Sequence[np.ndarray]] = None,
                  gap: Optional[float] = None) -> Tuple[np.ndarray, bool, bool]:
    """``finish_strip`` without its info. Returns (image, inverted, paper flattened)."""
    out, inv, flat, _info = finish_strip(comp, members=members, gap=gap)
    return out, inv, flat


def inventory_before_crop(system: Dict[str, Any], box: Sequence[int], obs_by: Dict[str, Dict[str, Any]],
                          load_image: ImageLoader, gap: float, *,
                          expected_size: Optional[Tuple[int, int]] = None,
                          frame_foreground: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, Any]:
    """Inventory every full ROI before sampling or the proposed envelope crop.

    Every component in this row's allocation is inventoried; its outside-crop
    support is bundled. Components crossing a neighbouring row's allocation
    boundary are retained whole with unresolved ownership. The primary crop is
    unchanged; outside hypotheses go into the same system review bundle.
    ``frame_foreground``: observation id -> its full frame's foreground (a function of the
    frame alone), shared by the systems of one screen; filled here.
    """
    members = sorted(system.get("observations") or [], key=lambda m: float(obs_by[m["obs_id"]]["t_sec"]))
    result = {"members": len(members), "checked_members": 0, "foreground_px": 0,
              "speckle_dropped": 0, "events": [], "member_inventory": []}
    for i, member in enumerate(members):
        obs = obs_by[member["obs_id"]]
        raw = load_image(obs)
        foreground = None if frame_foreground is None else frame_foreground.get(member["obs_id"])
        if foreground is None:
            norm, _ = sd.normalize_polarity(raw)
            gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
            foreground = gray <= float(np.percentile(gray, 75)) - FAINT_PAPER_DROP
            if frame_foreground is not None:
                frame_foreground[member["obs_id"]] = foreground
        region = _region(obs, member["region_id"])
        top, bottom = float(region["staff_y"][0]), float(region["staff_y"][-1])
        others = [r for r in obs.get("system_regions", []) if r["region_id"] != member["region_id"]]
        above = [float(r["staff_y"][-1]) for r in others if float(r["staff_y"][-1]) < top]
        below = [float(r["staff_y"][0]) for r in others if float(r["staff_y"][0]) > bottom]
        lo = (max(above) + top) / 2 if above else 0
        hi = (bottom + min(below)) / 2 if below else raw.shape[0]
        size_unresolved = expected_size is not None and raw.shape[:2] != expected_size
        n, labels, stats, _ = cv2.connectedComponentsWithStats(foreground.astype(np.uint8), connectivity=8)
        result["checked_members"] += 1
        owned_px = 0
        for k in range(1, n):
            x, y, w, h, area = map(int, stats[k])
            if y + h <= lo or y >= hi:
                continue
            owned_px += area
            if not size_unresolved and x >= box[0] and y >= box[1] and x + w <= box[2] and y + h <= box[3]:
                continue
            ambiguous = y < lo or y + h > hi
            mask = labels[y:y+h, x:x+w] == k
            if not ambiguous and not size_unresolved:
                # Inventory the pixels the crop would actually discard. A
                # connected chrome band can also touch foreground already kept
                # inside the crop; that foreground does not invalidate a positive
                # appearance explanation of the band's outside pixels.
                yy, xx = np.indices(mask.shape)
                mask &= (xx+x < box[0]) | (xx+x >= box[2]) | (yy+y < box[1]) | (yy+y >= box[3])
                area = int(mask.sum())
            if area < mc.MIN_COMPONENT_PX:
                result["speckle_dropped"] += 1
                continue
            ys, xs = np.nonzero(mask)
            a,b,c,d = int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1
            mask = mask[b:d,a:c]
            x,y,w,h = x+a,y+b,c-a,d-b
            result["events"].append({"box_crop": [x, y, x+w, y+h], "area_px": area,
                "members": [i], "runs": [[i, i]], "seen": 1, "obs_ids": [member["obs_id"]],
                "times": [[float(obs["t_sec"]), float(obs["t_sec"])]],
                "classification": UNCERTAIN_MARK_KEPT, "ink_like": True,
                "disposition": "MEMBER_GEOMETRY_UNRESOLVED" if size_unresolved else
                    ("ROW_OWNERSHIP_UNRESOLVED" if ambiguous else "OUTSIDE_PROPOSED_CROP_KEPT"),
                "foreground_support": [{"obs_id": member["obs_id"], "spans_crop": mc.support_runs(mask, (x, y))}]})
        result["foreground_px"] += owned_px
        result["member_inventory"].append({"obs_id": member["obs_id"], "t_sec": float(obs["t_sec"]),
            "owned_rows": [lo, hi], "raw_size": [raw.shape[1], raw.shape[0]], "foreground_px": owned_px})
    return result


class _LazyMasks(Mapping):
    """Read-only mapping whose values are computed on first access, in insertion order of keys."""

    def __init__(self) -> None:
        self._make: Dict[Any, Callable[[], np.ndarray]] = {}
        self._done: Dict[Any, np.ndarray] = {}

    def add(self, key: Any, make: Callable[[], np.ndarray]) -> None:
        self._make[key] = make
        self._done.pop(key, None)

    def __getitem__(self, key: Any) -> np.ndarray:
        if key not in self._done:
            self._done[key] = self._make[key]()
        return self._done[key]

    def __iter__(self):
        return iter(self._make)

    def __len__(self) -> int:
        return len(self._make)


def check_minority_content(system: Dict[str, Any], comp: np.ndarray, box: Sequence[int], obs_by: Dict[str, Dict[str, Any]],
                           load_image: ImageLoader, gap: float, *, memo: Optional[Dict[Any, np.ndarray]] = None,
                           chrome: Optional[np.ndarray] = None, native_scale: float = 1.0,
                           member_shifts: Optional[Dict[str, Sequence[float]]] = None,
                           registration_responses: Optional[Dict[str, Optional[float]]] = None,
                           registration_reference: Optional[str] = None) -> Dict[str, Any]:
    """Credible neutral ink in any clear registered member that the composite
    ``comp`` (crop box ``box``) does not draw and no overlay explains (minority_content.py).

    Every member is checked, including ones omitted by median sampling. Size,
    fade and registration exclusions are counted; <=2 px speckles are counted.
    Returns the events with crop boxes, times,
    observation ids and member runs (indices into the time-ordered members).
    ``member_shifts``: common-reference work-pixel shifts keyed by observation id;
    absent entries use this audit's measurement against the composite.
    ``registration_responses`` / ``registration_reference``: the phase-correlation responses
    of ``member_shifts`` and the observation they are measured against. With both, a
    member's shift against the composite may be taken from its full-resolution shift against
    that reference (see ``predicted_rel``); without them every member is registered here."""
    from app.pipeline.system_tracking import clean_content, clean_normalized
    members = sorted(system.get("observations") or [], key=lambda m: float(obs_by[m["obs_id"]]["t_sec"]))
    n = len(members)
    out: Dict[str, Any] = {"observation_order": [m["obs_id"] for m in members], "members": n, "checked_members": 0, "skipped_members": 0, "events": [],
                           "speckle_dropped": 0}
    H, W = comp.shape[:2]
    comp_clean = clean_content(comp)
    ref_ink = mc.ink_mask(comp_clean)
    ref_d = mc._dilate(ref_ink, mc.tolerance_px(gap))
    dark_max = mc.ink_dark_max(comp_clean)
    out["ink_dark_max"] = round(dark_max, 1)
    # Overlays explain only the pixels they occupy (2-D masks, never whole columns): a static band
    # does not hide a mark below it in its columns. Screen-fixed chrome explains only its own colored
    # pixels (neutral_ink leaves colored pixels and their 2-px rim out); neutral ink inside a chrome
    # area is content like any other (settle_chrome keeps such pixels in the composite).
    chrome = chrome if chrome is not None and chrome.shape == (H, W) and chrome.any() else None
    cache: Dict[int, Optional[np.ndarray]] = {}
    rejected_masks: Dict[int, np.ndarray] = {}
    rejected_by: Dict[int, Dict[str, Any]] = {}
    # Eligibility masks (not overlay, not playhead columns) of the checked members. They are
    # read only to count the eligible witnesses of an uncertain event (and passed on), so each
    # is computed when first read: a system without events never needs them.
    eligible_masks = _LazyMasks()

    def _member_overlay(crop, key, normalized):
        done: List[np.ndarray] = []

        def get() -> np.ndarray:
            if not done:
                done.append(_overlay_mask2d_of(crop, gap, key, memo, chrome, normalized=normalized))
            return done[0]
        return get
    background = [0]
    raw_grays = {}
    cursor_shifts = {}
    transition_by = {}
    levels = []
    # Every member crop is normalized once (polarity, gray, paper level) and reused by
    # every step below: the same pixels give the same products (paper_levels, clean_content).
    all_crops = [load_image(obs_by[m["obs_id"]])[box[1]:box[3], box[0]:box[2]] for m in members]
    norms: Dict[int, np.ndarray] = {}
    for i, im in enumerate(all_crops):
        if im.shape[:2] != (H, W):
            levels.append(0.0)
            continue
        norms[i], _ = sd.normalize_polarity(im)
        raw_grays[i] = cv2.cvtColor(norms[i], cv2.COLOR_BGR2GRAY)
        levels.append(float(np.percentile(raw_grays[i], 75)))  # paper_levels([im])[0]
    paper = float(np.median(levels))
    ref_gray = _alignment_gray(comp)
    window = cv2.createHanningWindow((W, H), cv2.CV_32F)
    base, _ = cv2.phaseCorrelate(ref_gray.copy(), ref_gray.copy(), window)
    comp_norm, comp_inverted = sd.normalize_polarity(comp)
    comp_gray = cv2.cvtColor(comp_norm, cv2.COLOR_BGR2GRAY).astype(np.int16)
    comp_paper = float(np.percentile(comp_gray, 75))
    dark = comp_gray < min(DARK_INK_MAX, comp_paper - FAINT_PAPER_DROP)
    near_dark = cv2.dilate(dark.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    halftone = float(((comp_gray >= comp_paper - FAINT_PAPER_DROP) &
                      (comp_gray < comp_paper - PLATE_HALFTONE_BAND) & ~near_dark).mean())
    opaque = not comp_inverted or halftone <= PLATE_HALFTONE_MAX
    out["paper_opaque"] = opaque
    # Detection only changes evidence eligibility, never the canonical strip pixels.
    valid_indices = [i for i, crop in enumerate(all_crops) if crop.shape[:2] == (H, W)]
    valid_crops = [all_crops[i] for i in valid_indices]
    positions = mc.cursor_positions(valid_crops, gap, reference=comp_gray, allow_tinted_boxes=opaque)
    if len(valid_indices) != len(all_crops):
        positions = mc.CursorPositions({valid_indices[i]: x for i, x in positions.items()},
            {valid_indices[i]: width for i, width in getattr(positions, "half_widths", {}).items()})
    chrome_masks = {}
    palette = chrome_palette(valid_crops, chrome) if chrome is not None else None
    stable = []
    for i, crop in enumerate(all_crops):
        if crop.shape[:2] != (H, W):
            continue
        gray = raw_grays[i]
        supplied = (member_shifts or {}).get(members[i]["obs_id"])
        if supplied is not None:
            cursor_shifts[i] = tuple(float(v) for v in supplied)
        if levels[i] >= paper - FADE_PAPER_DROP and float(np.mean(np.abs(gray.astype(float)-comp_gray))) < 8:
            stable.append(i)
    if opaque and len(stable) >= 3:
        transition_ref = comp_gray.astype(np.uint8)
        prepared = mc.transition_reference(transition_ref, gap)
        for i, gray in raw_grays.items():
            evidence = mc.transition_evidence(gray, transition_ref, gap, prepared=prepared)
            if evidence:
                transition_by[i] = dict(evidence, stable_witness_members=stable,
                                        obs_id=members[i]["obs_id"], t_sec=float(obs_by[members[i]["obs_id"]]["t_sec"]))
    import base64
    for i, evidence in transition_by.items():
        ok, encoded = cv2.imencode('.png', all_crops[i])
        if not ok:
            raise RuntimeError('failed to encode transition evidence')
        evidence.update(classification="EXPLAINED_TRANSITION", box_crop=list(box),
                        stable_witness_obs_ids=[members[j]["obs_id"] for j in evidence["stable_witness_members"]],
                        raw_png_base64=base64.b64encode(encoded.tobytes()).decode('ascii'))
    out["ineligible_observations"] = list(transition_by.values())

    # Registration against the composite, predicted from the strip registration.
    # The registration below only decides whether a member is misregistered (shift >= _MAX_SHIFT_PX);
    # a registered member's shift is not used further (its cursor shift is the supplied one).
    # Shifts compose: (composite -> member) = (composite -> reference) + (reference -> member),
    # where (reference -> member) is the full-resolution strip registration and (composite ->
    # reference) is measured here once. The prediction is used only when it is unambiguous: both
    # registrations respond strongly (>= PREDICT_MIN_RESPONSE), the member's staff rows moved as
    # the predicted vertical shift says (within PREDICT_GEOMETRY_PX), and the predicted shift is
    # at most half the rejection threshold. Every other member - and every faded member, whose
    # exact shift feeds its rejected-foreground audit - is registered exactly as before.
    # Measured on S1nl and 01Mr (2,204 members): |predicted - exact| <= 0.01 px, 25x below the
    # remaining margin. A member the old check could reject (exact shift >= _MAX_SHIFT_PX) is
    # therefore registered exactly; a wrongly accepted one would still be checked in full.
    exact_rel: Dict[int, np.ndarray] = {}
    predict_from = None
    if member_shifts and registration_responses is not None and registration_reference is not None:
        ref_idx = next((i for i, m in enumerate(members)
                        if m["obs_id"] == registration_reference and i in raw_grays), None)
        if ref_idx is not None:
            shift, response = cv2.phaseCorrelate(ref_gray.copy(), _alignment_gray(all_crops[ref_idx]), window)
            exact_rel[ref_idx] = np.array(shift) - np.array(base)
            ref_region = _region(obs_by[members[ref_idx]["obs_id"]], members[ref_idx]["region_id"])
            if (float(response) >= PREDICT_MIN_RESPONSE and np.isfinite(exact_rel[ref_idx]).all()
                    and ref_region.get("staff_y")):
                predict_from = (exact_rel[ref_idx], float(np.mean(ref_region["staff_y"])))

    def predicted_rel(i: int, region: Dict[str, Any]) -> Optional[np.ndarray]:
        if predict_from is None or i in exact_rel:
            return None
        oid = members[i]["obs_id"]
        supplied, response = (member_shifts or {}).get(oid), registration_responses.get(oid)
        if supplied is None or response is None or response < PREDICT_MIN_RESPONSE or not region.get("staff_y"):
            return None
        supplied = np.asarray(supplied, float)
        if supplied.shape != (2,) or not np.isfinite(supplied).all():
            return None
        if abs(float(supplied[1]) - (float(np.mean(region["staff_y"])) - predict_from[1])) > PREDICT_GEOMETRY_PX:
            return None
        rel = predict_from[0] + supplied
        return rel if float(np.hypot(*rel)) < PREDICT_MAX_SHIFT_FRACTION * _MAX_SHIFT_PX else None

    def unexplained_of(i: int) -> Optional[np.ndarray]:
        if i in cache:
            return cache[i]
        m = members[i]
        obs = obs_by[m["obs_id"]]
        region = _region(obs, m["region_id"])
        img = load_image(obs)
        crop = img[box[1]:box[3], box[0]:box[2]]
        if crop.shape[:2] != (H, W):
            cache[i] = None
            return None
        if i in transition_by:
            cache[i] = None
            return None
        faded = opaque and levels[i] < paper - FADE_PAPER_DROP
        rel = None if faded else predicted_rel(i, region)
        if rel is None:
            if i in exact_rel:
                rel = exact_rel[i]
            else:
                shift, _ = cv2.phaseCorrelate(ref_gray.copy(), _alignment_gray(crop), window)
                rel = np.array(shift) - np.array(base)
        if i not in cursor_shifts:
            cursor_shifts[i] = tuple(float(v) for v in rel)
        misregistered = not np.isfinite(rel).all() or np.linalg.norm(rel) >= _MAX_SHIFT_PX
        if faded or misregistered:
            residual, proof = mc.rejected_foreground(raw_grays[i], comp_gray.astype(np.uint8), levels[i], rel, gap)
            rejected_masks[i] = residual
            ok, encoded = cv2.imencode('.png', crop)
            if not ok:
                raise RuntimeError('failed to encode rejected-member evidence')
            rejected_by[i] = dict(proof, obs_id=m["obs_id"], t_sec=float(obs["t_sec"]), box_crop=list(box),
                classification="INELIGIBLE_FADE" if faded else "INELIGIBLE_REGISTRATION",
                disposition="RAW_FOREGROUND_KEPT", raw_png_base64=base64.b64encode(encoded.tobytes()).decode('ascii'))
            out["speckle_dropped"] += proof["speckle_dropped"]
            cache[i] = None
            return None
        clean = clean_normalized(norms[i], raw_grays[i])  # clean_content(crop)
        cols = mc.playhead_columns(W, region, gap, x_offset=int(box[0]))
        overlay_of = _member_overlay(crop, (m["obs_id"], tuple(int(v) for v in box)), (norms[i], raw_grays[i]))
        eligible_masks.add(i, lambda overlay_of=overlay_of, cols=cols: ~overlay_of() & ~cols[None, :])
        neutral = mc.neutral_ink(clean, dark_max)
        colored = mc.colored_mask(clean) & mc.ink_mask(clean)
        if colored.any():
            # colored ink (a colored playhead, notes recolored under it) explains its own pixels and
            # their anti-aliased surroundings, not its whole columns
            neutral &= ~mc._dilate(colored, max(2, int(round(COLORED_EXPLAINS_GAPS * gap))))
        u, (dx, _dy) = mc.unexplained(neutral, ref_ink, cols, gap, reference_dilated=ref_d)
        if u.any():
            # only a member with unexplained ink needs the video-background test (the same result:
            # removing components cannot add unexplained ink, so an empty result stays empty)
            neutral, dropped = mc.drop_on_video_background(neutral, mc.background_texture(norms[i], gap))
            background[0] += dropped
            if dropped:
                u, (dx, _dy) = mc.unexplained(neutral, ref_ink, cols, gap, reference_dilated=ref_d)
        if u.any():
            # the member's own 2-D overlay mask (bands as their rows, boxes as boxes, gray playheads;
            # chrome left out) explains the pixels it covers. It is computed here, only for a
            # member with unexplained ink: with u empty the old step left u empty whatever the
            # mask (u & ~ov of an empty u), so every member it could change still gets its mask.
            ov = overlay_of()
            if ov.any():
                if dx or _dy:
                    ov = mc._shift(ov, dx, _dy)
                u = mc._drop_small(u & ~ov)
        # A one-pixel stroke beside a staff line is not explained by the staff's
        # proximity. Compare raw, normalized pixels after a registration check;
        # do not run this evidence through clean_content or a dilated staff mask.
        gray = raw_grays[i].astype(np.int16)  # normalized gray of this crop, computed above
        # Opaque paper also carries gray notation. A fixed black-ink cutoff
        # cannot silently dismiss a credible gray minority stroke there.
        ceiling = levels[i] - FAINT_PAPER_DROP
        raw_lost = (gray <= ceiling) & (gray < comp_gray - LOST_INK_DROP)
        if raw_lost.any():
            if chrome is not None and palette is not None:
                identified = chrome_explained(crop, raw_lost & chrome, palette,
                                               _paper_color(crop, ~chrome))
                if identified.any():
                    chrome_masks[i] = identified
                    raw_lost &= ~identified
            kept = mc._drop_small(raw_lost, min_extent=1)
            out["speckle_dropped"] += int(cv2.connectedComponents((raw_lost & ~kept).astype(np.uint8))[0] - 1)
            u |= kept
        cache[i] = u
        return u

    for i in range(n):
        unexplained_of(i)
    masks = {i: u for i, u in cache.items() if u is not None}
    out["checked_members"] = len(masks)
    out["skipped_members"] = sum(1 for u in cache.values() if u is None)
    out["video_background_components"] = background[0]
    out["cursor_track"] = {"track": bool(positions), "positions": [[i, round(x,3)] for i,x in positions.items()],
        "half_widths":[[i,round(w,3)] for i,w in getattr(positions,"half_widths",{}).items()]}
    # Recoloring a printed note is cursor evidence too: reference ink must not
    # create artificial holes in its moving template. Half the lost-ink contrast
    # tolerates antialias/JPEG edges; actual obligations still require 50 levels.
    variations = {i:np.abs(raw_grays[i].astype(np.int16)-comp_gray)>=LOST_INK_DROP/2 for i in masks}
    candidates = mc.co_moving_cursor_masks(masks, positions, gap, witness_masks=variations)
    accepted = {}
    cursor_proofs = {}
    cursor_records = []
    cursor_colors = {i:norms[i] for i in masks}
    partial_kw = {"allow_partial": True} if "allow_partial" in inspect.signature(mc.recovered_cursor_event).parameters else {}
    parameters = inspect.signature(mc.recovered_cursor_event).parameters
    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    if "native_scale" in parameters or has_kwargs:
        partial_kw["native_scale"] = native_scale
    if "member_shifts" in parameters or has_kwargs:
        partial_kw["member_shifts"] = cursor_shifts
    for i,candidate in candidates.items():
        for piece in mc.minority_events({i:candidate},gap,single_observation=True):
            evidence = mc.recovered_cursor_event(piece,{i:candidate},
                {j:raw_grays[j] for j in masks},comp_gray,positions,gap,
                ink_ceiling=dark_max if not opaque else None, colors=cursor_colors, witness_masks=variations, **partial_kw)
            if evidence:
                part = mc.event_member_mask(piece,i,candidate)
                recovered = evidence.pop("_recovered_mask", None)
                if recovered is not None:
                    recovered = np.asarray(recovered, bool)
                    if recovered.shape != candidate.shape:
                        raise ValueError("cursor recovered mask frame mismatch")
                    part &= recovered
                if not part.any():
                    continue
                accepted[i] = accepted.get(i,np.zeros_like(candidate)) | part
                cursor_proofs.setdefault(i,[]).append(dict(evidence,box=piece["box"]))
                cursor_records.append({"member": i, "mask": part, "proof": evidence})
    for i,mask in accepted.items():
        masks[i] = masks[i] & ~mask
    cursor_events = mc.minority_events(accepted,gap,single_observation=True)
    for event in cursor_events:
        event.update(classification="EXPLAINED_CURSOR",evidence={
            "kind":"co_moving_colored_cursor_with_clear_score_recovery",
            "template_support_fraction":.8,"template_min_distinct_positions":3,"template_contrast":LOST_INK_DROP/2,
            "positions":[[i,round(x,3)] for i,x in positions.items()],
            "components":[{"member":i,"proofs":cursor_proofs[i]} for i in event["members"]]})
    # Eligibility controls denominators, never whether raw hypotheses exist.
    # Rejected members cannot be cursor/recovery witnesses, or contribute to
    # composition. Their residual support remains in their original coordinates.
    events = mc.minority_events(masks, gap, single_observation=True)
    rejected_events = mc.minority_events(rejected_masks, gap, single_observation=True)
    for e in rejected_events:
        e["disposition"] = "REJECTED_MEMBER_RAW_FOREGROUND_KEPT"
        e["eligibility"] = [rejected_by[i]["classification"] for i in e["members"]]
        e["local_registration"] = [{"obs_id": members[i]["obs_id"],
            **{k:v for k,v in rejected_by[i].items() if k in ("attempted_shift_px", "registered", "scaffold_recall", "scaffold_precision")}}
            for i in e["members"]]
    events += rejected_events
    masks.update(rejected_masks)
    out["rejected_observations"] = list(rejected_by.values())
    t_of = [float(obs_by[m["obs_id"]]["t_sec"]) for m in members]
    # Timing at a hand-over does not explain foreground. Fades and
    # registration failures have already left the eligible observations.
    out["edge_transitions"] = []
    for e in events + cursor_events:
        x0, y0, x1, y1 = e["box"]
        e["box_crop"] = [x0 + int(box[0]), y0 + int(box[1]), x1 + int(box[0]), y1 + int(box[1])]
        e["times"] = [[round(t_of[a], 4), round(t_of[b], 4)] for a, b in e["runs"]]
        e["obs_ids"] = [members[i]["obs_id"] for i in e["members"]]
        e["runs"] = [[int(a), int(b)] for a, b in e["runs"]]
        e["seen"] = len(e["members"])
    out["explained_events"] = cursor_events
    for e in mc.minority_events(chrome_masks, gap, single_observation=True):
        e.update(classification="EXPLAINED_CHROME", evidence={"kind":"positive_screen_chrome_palette",
                 "notation_excluded":True}, obs_ids=[members[i]["obs_id"] for i in e["members"]],
                 box_crop=[e["box"][0]+box[0],e["box"][1]+box[1],e["box"][2]+box[0],e["box"][3]+box[1]])
        out["explained_events"].append(e)
    uncertain = []
    for e in events:
        e["classification"] = UNCERTAIN_MARK_KEPT
        e["ink_like"] = True
        uncertain.append(e)
    for e in out["explained_events"]:
        e["seen"] = len(e["members"])
        ex0,ey0,ex1,ey1 = e["box"]
        e["foreground_support"] = [{"obs_id":members[i]["obs_id"],
            "spans_crop":mc.support_runs(mc.event_member_mask(e,i,
                (chrome_masks if e["classification"] == "EXPLAINED_CHROME" else accepted)[i])
                                          [ey0:ey1,ex0:ex1], (box[0]+ex0,box[1]+ey0))}
            for i in e["members"]]
        if e["classification"] == "EXPLAINED_CURSOR":
            clear = {j for i in e["members"] for proof in cursor_proofs[i] for j in proof["clear_members"]}
            e["evidence"]["clear_observations"] = [{"obs_id":members[j]["obs_id"],
                "t_sec":float(obs_by[members[j]["obs_id"]]["t_sec"])} for j in sorted(clear)]
        e["raw_evidence"] = []
        x0,y0,x1,y1 = e["box"]
        for i in e["members"]:
            ok, encoded = cv2.imencode('.png', all_crops[i][y0:y1,x0:x1])
            if not ok:
                raise RuntimeError('failed to encode explained-event evidence')
            e["raw_evidence"].append({"obs_id":members[i]["obs_id"],
                "t_sec":float(obs_by[members[i]["obs_id"]]["t_sec"]),"box_crop":e["box_crop"],
                "raw_png_base64":base64.b64encode(encoded.tobytes()).decode('ascii')})
    events = uncertain
    out["events"] = events
    out["_members"] = members
    out["_cursor_accepted"] = accepted
    out["_cursor_proofs"] = cursor_proofs
    out["_cursor_records"] = cursor_records
    out["_eligible_masks"] = eligible_masks
    out["_member_masks"] = masks
    out["_event_support"] = []
    for e in events:
        x0, y0, x1, y1 = e["box"]
        support = np.zeros((y1 - y0, x1 - x0), bool)
        for i in e["members"]:
            support |= mc.event_member_mask(e,i,masks[i])[y0:y1, x0:x1]
        out["_event_support"].append(support)
        e["eligible"] = sum(int((em[y0:y1, x0:x1] & support).sum()) >= mc.MIN_COMPONENT_PX
                            for em in eligible_masks.values())
        e["foreground_support"] = [{"obs_id": members[i]["obs_id"],
            "spans_crop": mc.support_runs(masks[i][y0:y1,x0:x1], (x0+int(box[0]),y0+int(box[1])))}
            for i in e["members"]]
        if not opaque:
            by_id = {members[i]["obs_id"]:raw_grays[i] for i in e["members"]}
            e["ink_like_foreground_support"] = mc.ink_like_support(e["foreground_support"],
                lambda owner:(by_id[owner["obs_id"]],box[:2]), dark_max)
            e["ink_like"] = bool(e["ink_like_foreground_support"])
            if e["ink_like"]:
                e.pop("cause",None)
    return out


def build_alternates(minority: Dict[str, Any], box: Sequence[int], obs_by: Dict[str, Dict[str, Any]], load_image: ImageLoader,
                     gap: float, keep_rows: Tuple[int, int], pad: int, *,
                     memo: Optional[Dict[Any, np.ndarray]] = None,
                     chrome: Optional[np.ndarray] = None,
                     chrome_appearance: Optional[np.ndarray] = None,
                     source_manifest: Optional[Dict[str, Any]] = None) -> List[Tuple[np.ndarray, Dict[str, Any]]]:
    """One review record per written system; every raw hypothesis is losslessly bundled.

    The thumbnail is ONE observation, not a union. The embedded PNG patches,
    with observation ownership and lossless foreground spans, are the evidence.
    Selecting the thumbnail alone does not render all bundled hypotheses.
    """
    import base64
    members, events = minority["_members"], minority["events"]
    if not events:
        return []
    used = sorted({i for e in events for i in e["members"]})
    variants = []
    masks = minority.get("_member_masks", {})
    votes = np.zeros((box[3]-box[1],box[2]-box[0]),np.int32)
    for mask in masks.values():
        votes += mask
    def representative_score(i):
        mask = masks.get(i)
        if mask is None or not mask.any():
            return (0.0,0)
        # A large unresolved cursor fragment must not hide a small dot shown
        # in several members. This chooses one witness; patches still keep all.
        return (float(votes[mask].mean()),int(mask.sum()))
    best = max(used, key=representative_score)
    crop = load_image(obs_by[members[best]["obs_id"]])[box[1]:box[3],box[0]:box[2]]
    norm, _ = sd.normalize_polarity(crop)
    full, inv, flat, finfo = finish_strip(crop.copy(), members=[crop], gap=gap)
    required = minority.get("_member_masks", {}).get(best)
    if required is not None:
        full[required] = norm[required]
    _finishing_boxes_to_crop(finfo, box)
    img, trimmed = trim_blank_rows(full, keep=keep_rows, pad=pad)
    abox = [int(box[0]),int(box[1])+trimmed[0],int(box[2]),int(box[3])-trimmed[1]]
    for ei, e in enumerate(events):
        r = max(2, int(round(gap)))
        for i in e["members"]:
            oid = members[i]["obs_id"]
            image = load_image(obs_by[oid])
            x0,y0,x1,y1 = e["box_crop"]
            a,c,b,d = max(0,x0-r),max(0,y0-r),min(image.shape[1],x1+r),min(image.shape[0],y1+r)
            raw = image[c:d,a:b]
            ok, png = cv2.imencode('.png', raw)
            if not ok:
                raise RuntimeError('failed to encode uncertainty evidence')
            variants.append({"event_index":ei,"obs_id":oid,"region_id":members[i]["region_id"],
                "t_sec":float(obs_by[oid]["t_sec"]),"box_crop":[a,c,b,d],
                "event_box_crop":e["box_crop"],"seen":e.get("seen"),"eligible":e.get("eligible"),
                "disposition":e.get("disposition", "UNRESOLVED_FOREGROUND_KEPT"),
                "foreground_support":next((v for v in e.get("foreground_support",[]) if v["obs_id"]==oid),None),
                "raw_png_base64":base64.b64encode(png.tobytes()).decode('ascii')})
    times = [float(obs_by[members[i]["obs_id"]]["t_sec"]) for i in used]
    clipped = source_clipping(load_image(obs_by[members[best]["obs_id"]]),abox,source_manifest) if source_manifest else None
    return [(img, {"suffix":"alt1","kind":"uncertain_mark_bundle","method":"review_bundle",
        "pixel_reference_obs_id":members[best]["obs_id"],"events":list(range(len(events))),
        "run_members":[min(used),max(used)],"obs_ids":[members[i]["obs_id"] for i in used],
        "region_ids":[members[i]["region_id"] for i in used],"t_start":round(min(times),4),"t_end":round(max(times),4),
        "box_crop":abox,"size":[int(img.shape[1]),int(img.shape[0])],"members_used":1,
        "inverted":inv,"paper_flattened":flat,"finishing":finfo,"evidence_patches":variants,
        "thumbnail_covers_all_hypotheses":False,
        **({"source_clipped":clipped} if clipped else {}),
        "event_boxes_strip":[[e["box_crop"][0]-abox[0],e["box_crop"][1]-abox[1],
                              e["box_crop"][2]-abox[0],e["box_crop"][3]-abox[1]] for e in events]})]


def job_screen_chrome(manifest: Dict[str, Any], load_image: ImageLoader) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """Screen-fixed chrome of the job in crop coordinates (overlay_composite.screen_fixed_chrome) from
    ``CHROME_SAMPLES`` observations spread evenly over the video (those showing a score row).
    Deterministic for a manifest, so a strip rebuilt later gets the same mask."""
    obs = sorted([o for o in manifest.get("observations") or [] if o.get("system_regions")], key=lambda o: float(o["t_sec"]))
    if not obs:
        return None, {"samples": 0}
    picks = [obs[i] for i in sorted(set(np.linspace(0, len(obs) - 1, min(len(obs), oc.CHROME_SAMPLES)).round().astype(int).tolist()))]
    images = [load_image(o) for o in picks]
    shapes = [im.shape for im in images]
    shape = max(set(shapes), key=shapes.count)
    mask, info = oc.screen_fixed_chrome([im for im in images if im.shape == shape])
    info = dict(info, shape=[int(shape[1]), int(shape[0])])
    return (mask if mask.any() else None), info


def _reference_member(system: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    members = system["observations"]
    widths = [(_region(obs_by[m["obs_id"]], m["region_id"])["staff_x"][1] - _region(obs_by[m["obs_id"]], m["region_id"])["staff_x"][0]) for m in members]
    med_w = float(np.median(widths))
    full = [m for m, wd in zip(members, widths) if wd >= 0.97 * med_w] or members
    picked = _evenly(full, _MAX_MEMBERS)
    mid = picked[len(picked) // 2]
    return mid, _region(obs_by[mid["obs_id"]], mid["region_id"])


def _strip_registration(system: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]], load_image: ImageLoader,
                        box: Sequence[int], crops: Sequence[np.ndarray], cinfo: Dict[str, Any], *,
                        responses: Optional[Dict[str, Optional[float]]] = None) -> Dict[str, Sequence[float]]:
    """Registration used by minority preservation and Stage A, without raw obligations.
    ``responses`` (filled when given): each registered member's phase-correlation response."""
    offered = cinfo.pop("_ledger_members")
    offered_by = {entry["key"][0]: entry for entry in offered}
    ref_gray = _alignment_gray(crops[int(cinfo["reference_index"])])
    shape = crops[int(cinfo["reference_index"])].shape[:2]
    window = cv2.createHanningWindow((shape[1], shape[0]), cv2.CV_32F)
    base, _ = cv2.phaseCorrelate(ref_gray.copy(), ref_gray.copy(), window)
    registration, shifts = [], {}
    for m in system.get("ledger_observations") or system["observations"]:
        oid = m["obs_id"]
        entry = offered_by.get(oid)
        if entry is None:
            image = load_image(obs_by[oid])[box[1]:box[3], box[0]:box[2]]
            if image.shape[:2] != shape:
                registration.append({"obs_id": oid, "residual_shift_px": None, "registration_uncertainty": None})
                continue
            shift, response = cv2.phaseCorrelate(ref_gray.copy(), _alignment_gray(image), window)
            rel = [float(shift[k] - base[k]) for k in (0, 1)]
        else:
            rel = entry["phase_shift"]
            response = entry.get("phase_response")
        uncertainty = float(np.hypot(*rel)) if np.isfinite(rel).all() else None
        registration.append({"obs_id": oid, "residual_shift_px": uncertainty, "registration_uncertainty": uncertainty})
        shifts[oid] = rel
        if responses is not None:
            responses[oid] = None if response is None else float(response)
    cinfo["member_registration"] = registration
    return shifts


def _strip_ledger(system: Dict[str, Any], manifest: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]],
                  load_image: ImageLoader, box: Sequence[int], crops: Sequence[np.ndarray], pairs: Sequence[Tuple],
                  cinfo: Dict[str, Any], gap: float, chrome: Optional[np.ndarray], memo: Dict, *,
                  sampled_ids: Optional[Sequence[str]] = None, evidence_dir: Optional[Path] = None) -> Dict[str, Any]:
    """All raw canvas members; sampling/eligibility never deletes hypotheses."""
    offered = cinfo.pop("_ledger_members")
    offered_by = {entry["key"][0]: entry for entry in offered}
    sampled = set(sampled_ids) if sampled_ids is not None else set(offered_by)
    ref_index = int(cinfo["reference_index"])
    ref_gray = _alignment_gray(crops[ref_index])
    shape = crops[ref_index].shape[:2]
    window = cv2.createHanningWindow((shape[1], shape[0]), cv2.CV_32F)
    base, _ = cv2.phaseCorrelate(ref_gray.copy(), ref_gray.copy(), window)
    papers = paper_levels(list(crops))
    med_paper = float(np.median(papers))
    did = f"strip:{system['id']}"
    members, associations, observation_ids = [], [], []
    registration, shifts = [], {}
    cached = {"id": None, "image": None}

    def canvas(oid):
        if cached["id"] != oid:
            cached["image"] = None
            cached["id"] = oid
            cached["image"] = load_image(obs_by[oid])[box[1]:box[3], box[0]:box[2]]
        return cached["image"]

    raw_members = system.get("ledger_observations") or system["observations"]
    for m in raw_members:
        oid = m["obs_id"]
        obs = obs_by[oid]
        observation_ids.append(oid)
        image = load_image(obs)[box[1]:box[3], box[0]:box[2]]
        association = {"obs_id": oid, "region_id": m["region_id"], "stage": "composition",
            "display_id": did, "occurrence_id": system["id"]}
        entry = offered_by.get(oid)
        associations.append(dict(association, role="offered",
            reason=None if oid in sampled else "not_sampled_for_composite"))
        if image.shape[:2] != shape:
            associations.append(dict(association, role="rejected_registration", reason="crop_shape_mismatch"))
            registration.append({"obs_id": oid, "residual_shift_px": None, "registration_uncertainty": None})
            continue
        paper = paper_levels([image])[0]
        if entry is None:
            shift, _ = cv2.phaseCorrelate(ref_gray.copy(), _alignment_gray(image), window)
            rel = [float(shift[k] - base[k]) for k in (0, 1)]
            faded, used = paper < med_paper - FADE_PAPER_DROP, False
        else:
            rel = entry["phase_shift"]
            faded, used = entry["faded"], entry["used"]
        uncertainty = float(np.hypot(*rel)) if np.isfinite(rel).all() else None
        registration.append({"obs_id": oid, "residual_shift_px": uncertainty, "registration_uncertainty": uncertainty})
        shifts[oid] = rel
        if used:
            associations.append(dict(association, role="used", reason=None))
        elif faded:
            associations.append(dict(association, role="rejected_fade", reason="fade_transition", paper_drop=med_paper - paper))
        elif uncertainty is None or uncertainty >= _MAX_SHIFT_PX:
            associations.append(dict(association, role="rejected_registration", reason="registration_out_of_range", shift_px=uncertainty))
        overlay = (lambda entry=entry: entry["overlay_mask"]) if entry is not None else (
            lambda oid=oid: _overlay_mask2d_of(canvas(oid), gap, None, None, chrome))
        members.append({"id": oid, "timestamp": float(obs["t_sec"]), "image": lambda oid=oid: canvas(oid),
            "frame_ref": {"observation_id": oid, "crop_box": list(box)}, "roi_origin": list(box[:2]),
            "source_to_native": obs.get("source_to_crop", manifest.get("source_to_crop")),
            "registration_shift": [0, 0], "registration_uncertainty": uncertainty,
            "usable": (lambda: ~chrome) if chrome is not None else (lambda: True), "occluded": overlay})
    del image
    cinfo["member_registration"], cinfo["_ledger_shifts"] = registration, shifts
    ledger = rl.record_obligations(source_video=str(manifest.get("video_id") or manifest.get("source_video") or "manifest:unknown"),
        display_id=did, occurrence_id=system["id"], members=members, expected_multiplicity=1, evidence_dir=evidence_dir)
    ledger["displays"][0]["observations"] = observation_ids
    ledger["observation_associations"] = associations
    for key in ("observations", "display_dispositions", "occurrence_remaps"):
        ledger.setdefault(key, [])
    return ledger


def _cursor_ledger_dispositions(ledger: Dict[str, Any], minority: Dict[str, Any], *,
                                obs_by: Optional[Dict[str, Dict[str, Any]]] = None,
                                load_image: Optional[ImageLoader] = None, box: Optional[Sequence[int]] = None) -> None:
    if not minority.get("_cursor_records"):
        return
    members = minority["_members"]
    display_members = {m["observation_id"]: m for m in ledger["displays"][0].get("members", [])}
    paper_by = {}
    for item in ledger["items"]:
        x0, y0, x1, y1 = item["display_bbox"]
        hypothesis = rl.unpack_crop(item["foreground_hypothesis"]) > 0
        recovered = np.zeros_like(hypothesis)
        witnesses = []
        if "evidence" in item:
            evidence_by = {e["observation_id"]: e for e in item["evidence"]}
        else:
            relevant = [r for r in minority["_cursor_records"] if (hypothesis & r["mask"][y0:y1, x0:x1]).any()]
            if not relevant:
                continue
            needed = {members[r["member"]]["obs_id"] for r in relevant}
            needed.update(members[w["member"]]["obs_id"] for r in relevant for w in r["proof"].get("witnesses", []))
            evidence_by = {}
            eligible = int(item["evidence_bits"]["eligible"], 16)
            for oid in needed:
                member = display_members.get(oid)
                if member is None:
                    continue
                raw = load_image(obs_by[oid])[box[1]:box[3], box[0]:box[2]]
                if rl.pixels_hash(raw) != member["canvas_pixels_sha256"]:
                    raise ValueError("cursor ledger canvas changed after inventory")
                polarity = member["polarity"]
                if oid not in paper_by:
                    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
                    paper_by[oid] = float(np.percentile(gray, 90 if polarity == "light" else 10))
                patch = raw[y0:y1, x0:x1]
                gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
                contrast = np.clip(paper_by[oid] - gray if polarity == "light" else gray - paper_by[oid], 0, 255).astype(np.uint8)
                evidence_by[oid] = {"eligible": bool(eligible & (1 << member["index"])),
                    "raw_patch": rl.pack_crop(patch), "contrast": rl.pack_crop(contrast)}
        for record in minority.get("_cursor_records", []):
            oid = members[record["member"]]["obs_id"]
            ev = evidence_by.get(oid)
            if ev is None:
                continue
            overlap = hypothesis & record["mask"][y0:y1, x0:x1] & (rl.unpack_crop(ev["contrast"]) >= rl.MIN_CONTRAST)
            proof_witnesses = record["proof"].get("witnesses") or []
            if not overlap.any() or len(proof_witnesses) < 2:
                continue
            mapped = [{"observation_id": members[w["member"]]["obs_id"], "cursor_x": w["cursor_x"],
                "residual_registration_px": w["residual_registration_px"]} for w in proof_witnesses]
            mapped = [w for w in mapped if evidence_by.get(w["observation_id"], {}).get("eligible")
                and np.isfinite(w["residual_registration_px"]) and 0 <= w["residual_registration_px"] <= .5]
            if len({w["observation_id"] for w in mapped}) < 2 or np.ptp([w["cursor_x"] for w in mapped]) <= 1:
                continue
            recovered |= overlap
            for w in mapped:
                if w not in witnesses:
                    witnesses.append(w)
        if recovered.any():
            clear_id = witnesses[0]["observation_id"]
            ledger["dispositions"].append({"item_id": item["id"], "kind": "cursor_recovery",
                "terminal": "recovered_beneath_overlay", "clear_observation_id": clear_id,
                "raw_patch_sha256": evidence_by[clear_id]["raw_patch"]["sha256"],
                "recovery": {"witnesses": witnesses, "recovered_mask": rl.pack_crop(recovered.astype(np.uint8) * 255)}})


def _ledger_chain(record: Dict[str, Any]) -> None:
    origin, final = record["ledger_canvas_box_crop"], record["box_crop"]
    record["ledger_chain"] = {"display_id": f"strip:{record['system_id']}", "strip_id": record["system_id"],
        "stages": [{"stage": "display_to_strip", "kind": "affine",
            "matrix": [[1, 0, origin[0] - final[0]], [0, 1, origin[1] - final[1]], [0, 0, 1]]}]}


def build_strip(system: Dict[str, Any], manifest: Dict[str, Any], load_image: ImageLoader, *,
                obs_by: Optional[Dict[str, Dict[str, Any]]] = None,
                next_systems: Sequence[Dict[str, Any]] = (),
                chrome: Any = None, chrome_appearance: Optional[np.ndarray] = None,
                evidence_dir: Optional[Path] = None, ledger: bool = False,
                frame_foreground: Optional[Dict[str, np.ndarray]] = None,
                evidence_lock: Any = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Cleaned strip image (BGR, dark on light) and its provenance record.

    ``chrome``: the job's screen-fixed chrome mask in crop coordinates (``job_screen_chrome``);
    None computes it from the manifest, False means none. ``chrome_appearance``: its steady colors
    (``job_screen_chrome`` info ``_appearance``), what settle_chrome may paper-fill.

    ``next_systems``: the occurrences that follow in display order (nearest first);
    a preview tail is cut only when one of them is verified to start with it."""
    obs_by = obs_by or {o["id"]: o for o in manifest["observations"]}
    members = system["observations"]
    if not members:
        raise ValueError(f"{system['id']}: no observations")
    # Prefer members whose staff spans the usual width (no clipped/partial views).
    widths = [(_region(obs_by[m["obs_id"]], m["region_id"])["staff_x"][1] - _region(obs_by[m["obs_id"]], m["region_id"])["staff_x"][0]) for m in members]
    med_w = float(np.median(widths))
    full = [m for m, wd in zip(members, widths) if wd >= 0.97 * med_w] or members
    picked = _evenly(full, _MAX_MEMBERS)
    mid = picked[len(picked) // 2]
    ref_obs = obs_by[mid["obs_id"]]
    ref_region = _region(ref_obs, mid["region_id"])
    g = float(ref_region["staff_gap_px"])
    ref_crop = load_image(ref_obs)
    h, w = ref_crop.shape[:2]
    if chrome is None:
        chrome, _cinfo = job_screen_chrome(manifest, load_image)
        chrome_appearance = _cinfo.get("_appearance")
    if chrome is False or chrome is None or chrome.shape != (h, w):
        chrome = None
    if chrome is None or chrome_appearance is None or chrome_appearance.shape[:2] != (h, w):
        chrome_appearance = None

    # envelope from up to three members
    env = None
    env_flags: List[str] = []
    env_found = 0
    for m in _evenly(picked, ENVELOPE_SAMPLES):
        crop = load_image(obs_by[m["obs_id"]])
        row = row_envelope_on_crop(crop, _region(obs_by[m["obs_id"]], m["region_id"]))
        if row is None:
            continue
        env_found += 1
        env_flags.extend(row.get("flags", []))
        b = row["envelope_bbox"]
        env = list(b) if env is None else [min(env[0], b[0]), min(env[1], b[1]), max(env[2], b[2]), max(env[3], b[3])]
    if env is None:
        env = list(ref_region["envelope_bbox"])
        env_flags.append("envelope_fallback_region")
    box = [int(np.floor(env[0] - PAD_H_GAPS * g)), int(np.floor(env[1] - PAD_V_GAPS * g)),
           int(np.ceil(env[2] + PAD_H_GAPS * g)), int(np.ceil(env[3] + PAD_V_GAPS * g))]
    box = [max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])]
    single_row = len(ref_obs.get("system_regions") or []) <= 1
    if single_row:
        # One row on screen: the applied ROI is this system's area. Keep its full
        # height (blank paper rows are trimmed after cleaning), so a mark the
        # envelope rules did not attach (a tempo mark over video) is not cut.
        box[1], box[3] = 0, h
    # The box must never be smaller than the row's own staff extent (all segments,
    # including a preview segment after a break: it is cut below only when verified).
    box[0] = min(box[0], int(ref_region["staff_x"][0]))
    box[2] = min(w, max(box[2], staff_end(ref_region) + int(np.ceil(PAD_H_GAPS * g))))

    norm_ref, inverted = sd.normalize_polarity(ref_crop)
    cut_info: Dict[str, Any] = {}
    others = [r for r in ref_obs.get("system_regions") or [] if r["region_id"] != ref_region["region_id"]]
    if not single_row and others:
        # Several rows on screen: the strip runs from the emptiest line above to the
        # emptiest line below (blank rows trimmed after cleaning), so text between
        # rows stays whole with its row. The envelope stays inside.
        norms = [sd.normalize_polarity(load_image(obs_by[m["obs_id"]]))[0] for m in _evenly(picked, 5)]
        norms = [n for n in norms if n.shape == norm_ref.shape] or [norm_ref]
        top_cut, bottom_cut, cut_info = row_cut_lines(norms, ref_region, others, g)
        # An empty cut row separates the rows cleanly (nothing is sliced), even when
        # the halfway-band envelope reached past it. Without an empty row, keep the
        # envelope (keeping beats cutting).
        box[1] = top_cut if cut_info.get("top_cut_ink") == 0 else min(top_cut, int(env[1]))
        box[3] = bottom_cut if cut_info.get("bottom_cut_ink") == 0 else max(bottom_cut, int(env[3]))

    # Run on every member's full ROI before loading any envelope-cropped member.
    # The inventory is independent of sampling and composition eligibility.
    inventory = inventory_before_crop(system, box, obs_by, load_image, g, expected_size=(h, w),
                                      frame_foreground=frame_foreground)
    bkey = tuple(int(v) for v in box)
    pairs = [((m["obs_id"], bkey), load_image(obs_by[m["obs_id"]])[box[1]:box[3], box[0]:box[2]]) for m in picked]
    pairs = [(k_, c) for k_, c in pairs if c.shape[:2] == (box[3] - box[1], box[2] - box[0])]
    crops = [c for _k, c in pairs]
    ov_memo: Dict[Any, np.ndarray] = {}  # overlay columns per (observation, crop box), shared by the steps below
    chrome_box = display_chrome(crops, chrome[box[1]:box[3], box[0]:box[2]]) if chrome is not None else None
    comp, cinfo = compose_members(crops, g, keys=[k_ for k_, _c in pairs], memo=ov_memo, chrome=chrome_box, ledger_members=True)
    if ledger:
        # Content-addressed ledger files can have the same path for several systems.
        # Serialize their check/write/hash sequence; all other cleaning stays parallel.
        with evidence_lock if evidence_lock is not None else nullcontext():
            fragment = _strip_ledger(system, manifest, obs_by, load_image, box, crops, pairs, cinfo, g, chrome_box, ov_memo,
                sampled_ids=[m["obs_id"] for m in picked], evidence_dir=evidence_dir)
        ledger_shifts = cinfo.pop("_ledger_shifts")
    else:
        fragment = None
        ledger_responses: Dict[str, Optional[float]] = {}
        ledger_shifts = _strip_registration(system, obs_by, load_image, box, crops, cinfo, responses=ledger_responses)
    unrec_mask = cinfo.pop("_unrecovered_mask", None)
    if crops:
        cinfo["pixel_reference_obs_id"] = pairs[int(cinfo["reference_index"])][0][0]
    # persistent ink the median lost (restore_lost_ink): reported in crop coordinates with the
    # observation each component was taken from, and its rows are never trimmed as blank paper
    ink_rest = cinfo.pop("ink_restored", None) or {"px": 0, "components": 0, "boxes": [], "member_indices": []}
    restored_boxes = [list(b_) for b_ in ink_rest["boxes"]]
    cinfo["ink_restored"] = {"px": int(ink_rest["px"]), "components": int(ink_rest["components"]),
                             "boxes_crop": [[b_[0] + box[0], b_[1] + box[1], b_[2] + box[0], b_[3] + box[1]] for b_ in restored_boxes],
                             "from_obs_ids": [pairs[j][0][0] for j in ink_rest["member_indices"]]}
    app_box = chrome_appearance[box[1]:box[3], box[0]:box[2]] if chrome_appearance is not None else None
    # Faded members cannot contribute to chrome composition. Their raw
    # foreground is audited independently below and retained for review.
    lv = cinfo.get("paper_levels") or []
    med_lv = float(np.median(lv)) if lv else 0.0
    settle_idx = [i for i, p_ in enumerate(lv) if p_ >= med_lv - FADE_PAPER_DROP] or list(range(len(crops)))
    settle_ov = [_overlay_mask2d_of(crops[i], g, pairs[i][0], ov_memo, chrome_box, over_chrome=True) for i in settle_idx] \
        if chrome_box is not None else None
    comp, chrome_info = settle_chrome(comp, [crops[i] for i in settle_idx], chrome_box, g, app_box, settle_ov)
    chrome_kept = chrome_info.pop("_kept_mask", None)
    chrome_info["touched_box_crop"] = [[b[0] + box[0], b[1] + box[1], b[2] + box[0], b[3] + box[1]] for b in chrome_info.pop("touched")]
    chrome_issue = OVERLAY_COVERS_NOTATION if chrome_info["touched_box_crop"] else None
    comp_box = list(box)
    minority = check_minority_content(system, comp, comp_box, obs_by, load_image, g, memo=ov_memo, chrome=chrome_box,
        native_scale=float((manifest.get("work_scale") or {}).get("scale", 1.0)), member_shifts=ledger_shifts,
        **({} if ledger or not crops else {"registration_responses": ledger_responses,
                                           "registration_reference": cinfo.get("pixel_reference_obs_id")}))
    if ledger:
        _cursor_ledger_dispositions(fragment, minority, obs_by=obs_by, load_image=load_image, box=comp_box)
    minority["full_roi_inventory"] = {k:v for k,v in inventory.items() if k != "events"}
    minority["speckle_dropped"] += inventory["speckle_dropped"]
    rejected = {v["obs_id"]:v for v in minority.get("rejected_observations", [])}
    transitions = {v["obs_id"]:v for v in minority.get("ineligible_observations", [])}
    ineligible = set(rejected) | set(transitions)
    full_palette = None
    if inventory["events"] and chrome is not None:
        full_palette = chrome_palette([load_image(obs_by[m["obs_id"]]) for m in picked], chrome)
    gray_of_obs: Dict[str, np.ndarray] = {}   # per observation: its full frame's normalized gray
    paper_of_obs: Dict[str, np.ndarray] = {}  # per observation: its paper color outside the chrome
    for event in inventory["events"]:
        oid = event["obs_ids"][0]
        raw = load_image(obs_by[oid])
        x0,y0,x1,y1 = event["box_crop"]
        event["box"] = [x0-comp_box[0], y0-comp_box[1], x1-comp_box[0], y1-comp_box[1]]
        event["eligible"] = minority["checked_members"]
        if oid in rejected:
            event["eligibility"] = [rejected[oid]["classification"]]
        owner = event["foreground_support"][0]
        if not minority["paper_opaque"]:
            if oid not in gray_of_obs:
                gray_of_obs[oid] = cv2.cvtColor(sd.normalize_polarity(raw)[0], cv2.COLOR_BGR2GRAY)
            gray = gray_of_obs[oid]
            event["ink_like_foreground_support"] = mc.ink_like_support([owner],
                lambda _owner:(gray,(0,0)), minority["ink_dark_max"])
            event["ink_like"] = bool(event["ink_like_foreground_support"])
        explained = oid in transitions
        if not explained and full_palette is not None:
            sel = np.zeros(raw.shape[:2], bool)
            for y,a,b in owner["spans_crop"]:
                sel[y,a:b] = True
            if oid not in paper_of_obs:
                paper_of_obs[oid] = _paper_color(raw, ~chrome)
            positive = chrome_explained(raw, sel & chrome, full_palette, paper_of_obs[oid])
            explained = bool((positive & sel).sum() == sel.sum())
        if explained:
            import base64
            ok, encoded = cv2.imencode('.png', raw[y0:y1,x0:x1])
            if not ok:
                raise RuntimeError('failed to encode outside-crop explanation')
            event.update(classification="EXPLAINED_TRANSITION" if oid in transitions else "EXPLAINED_CHROME",
                evidence={"kind":transitions[oid]["kind"] if oid in transitions else "positive_screen_chrome_palette"},
                raw_evidence=[{"obs_id":oid,"t_sec":float(obs_by[oid]["t_sec"]),"box_crop":[x0,y0,x1,y1],
                    "raw_png_base64":base64.b64encode(encoded.tobytes()).decode('ascii')}])
            minority.setdefault("explained_events", []).append(event)
        else:
            minority["events"].append(event)

    preview = find_preview_tail(norm_ref, ref_region)
    preview_issue = None
    cut_x = None
    if preview is not None and system.get("alternate_of"):
        # another state of the system before it: listed unchecked, its tail is never cut
        preview = dict(preview, verified=False, cut=False, reason="alternate_keeps_the_tail")
        preview_issue = "PREVIEW_TAIL_UNVERIFIED"
    elif preview is not None and preview["cut_x"] > box[0] + 10 * g:
        # The destination must be the next system in the final order: the next INCLUDED one.
        dest_sys = next((n for n in next_systems if n.get("included", True) and n.get("observations")), None)
        checks = []
        # cut in an empty column of the staff break (full strip height), never through the
        # current system's last marks (a flag or beam reaching past its staff end)
        empty_cut = _empty_cut_column(comp, int(preview["cut_x"]) - box[0], int(preview["next_staff_x"]) - box[0])
        if empty_cut is None:
            preview = dict(preview, reason="no_empty_column_between_systems")
            dest_sys = None
        else:
            preview = dict(preview, break_x=int(preview["cut_x"]), cut_x=box[0] + empty_cut)
        if dest_sys is not None:
            try:
                n_mid, n_region = _reference_member(dest_sys, obs_by)
                n_crop = load_image(obs_by[n_mid["obs_id"]])
                v = verify_preview_destination(ref_crop, ref_region, preview, n_crop, n_region)
                if v["verified"]:
                    # verify exactly the pixels the cut removes: every row of the strip box
                    x_rel = int(preview["cut_x"]) - box[0]
                    removed = verify_removed_pixels(comp[:, x_rel:], (int(preview["cut_x"]), box[1]), ref_region, preview, v,
                                                    n_crop, n_region)
                    v["removed_pixels"] = removed
                    if not removed["verified"]:
                        v["verified"] = False
                        v["reason"] = removed.get("reason", "removed_ink_not_at_destination")
            except Exception as exc:  # pragma: no cover - defensive
                v = {"verified": False, "reason": f"check_failed: {exc}"}
            v["system_id"] = dest_sys["id"]
            checks.append(v)
        dest = checks[0] if checks and checks[0]["verified"] else None
        preview = dict(preview, checks=checks, removed_box_crop=[int(preview["cut_x"]), box[1], box[2], box[3]])
        if dest_sys is None and "reason" not in preview:
            preview["reason"] = "no_next_included_system"
        if dest is not None:
            cut_x = int(preview["cut_x"])
            preview.update(verified=True, cut=True, destination_system_id=dest["system_id"],
                           destination_crop_x0=dest["dest_x0"], destination_dy_px=dest["dest_dy_px"],
                           coverage=dest["coverage"], removed_coverage=dest["removed_pixels"].get("removed_coverage"),
                           dest_ink_box_crop=dest["removed_pixels"].get("dest_ink_box_crop"),
                           mapping="tail crop x in [next_staff_x, staff end) -> destination crop x = x - next_staff_x + destination_crop_x0")
        else:
            preview.update(verified=False, cut=False)
            preview_issue = "PREVIEW_TAIL_UNVERIFIED"
    elif preview is not None:
        preview = dict(preview, verified=False, cut=False, reason="too_close_to_the_strip_start")
        preview_issue = "PREVIEW_TAIL_UNVERIFIED"

    staff_c = ([float(y) - comp_box[1] for y in ref_region["staff_y"]],
               int(ref_region["staff_x"][0]) - comp_box[0], min(comp_box[2], int(ref_region["staff_x"][1])) - comp_box[0])
    full_strip, inv2, flattened, finish_info = finish_strip(comp, members=crops, gap=g, staff=staff_c)
    _finishing_boxes_to_crop(finish_info, comp_box)
    inverted = inverted or inv2
    keep_rows = (max(0, env[1] - box[1]), max(0, min(box[3], env[3]) - box[1]))
    # rows holding content kept in a chrome area (any tint or darkness) or a minority event are never
    # trimmed away as blank paper
    extra_rows = []
    if chrome_kept is not None and chrome_kept.any():
        rows = np.flatnonzero(chrome_kept.any(axis=1))
        extra_rows += [int(rows[0]), int(rows[-1]) + 1]
    for b_ in restored_boxes:
        extra_rows += [int(b_[1]), int(b_[3])]
    dc = finish_info.get("dark_cleanup") or {}
    for b_ in dc.get("kept_boxes_crop", []) + dc.get("flagged_boxes_crop", []):  # faint notation kept by the cleanup
        extra_rows += [int(b_[1]) - comp_box[1], int(b_[3]) - comp_box[1]]
    if extra_rows:
        keep_rows = (min(int(keep_rows[0]), min(extra_rows)), max(int(keep_rows[1]), max(extra_rows)))
    alternate_keep = keep_rows
    for e in minority["events"]:
        alternate_keep = (min(alternate_keep[0], int(e["box"][1])), max(alternate_keep[1], int(e["box"][3])))
    pad = int(round(PAD_V_GAPS * g))
    alternates = build_alternates(minority, comp_box, obs_by, load_image, g, alternate_keep, pad, memo=ov_memo,
                                  chrome=chrome_box, chrome_appearance=app_box,
                                  source_manifest=manifest) if minority["events"] else []
    full_box = list(box)
    strip = full_strip
    full_trimmed = None
    if cut_x is not None:
        # the uncut strip is kept: a later order/selection change may restore the tail
        uncut, full_trimmed = trim_blank_rows(full_strip, keep=keep_rows, pad=pad)
        full_box = [box[0], box[1] + full_trimmed[0], box[2], box[3] - full_trimmed[1]]
        strip = full_strip[:, :cut_x - box[0]]
        box[2] = cut_x
    # blank paper rows at the top/bottom carry nothing
    strip, trimmed = trim_blank_rows(strip, keep=keep_rows, pad=pad)
    box = [box[0], box[1] + trimmed[0], box[2], box[3] - trimmed[1]]
    box = [int(v) for v in box]
    if unrec_mask is not None:
        # only what stays in the strip counts: a covered row trimmed away as blank paper does not
        kept_unrec = unrec_mask[box[1] - comp_box[1]:box[3] - comp_box[1], box[0] - comp_box[0]:box[2] - comp_box[0]]
        cinfo["unrecovered_px_before_trim"] = cinfo.get("unrecovered_px", 0)
        cinfo["unrecovered_px"] = int(kept_unrec.sum())
        cinfo["unrecovered_columns"] = int(kept_unrec.any(axis=0).sum())
    record = {
        "system_id": system["id"],
        **({"ledger": fragment} if ledger else {}),
        "ledger_canvas_box_crop": list(comp_box),
        "ledger_supersedes": f"occ:{system['occurrence_root']}" if system.get("occurrence_root") is not None else None,
        "box_crop": box,
        "envelope_crop": [int(v) for v in env],
        "envelope_samples": env_found,
        "envelope_flags": sorted(set(env_flags)),
        "staff_gap_px": round(g, 3),
        "staff_y_strip": [round(float(y) - box[1], 2) for y in ref_region["staff_y"]],
        "staff_x_strip": [int(ref_region["staff_x"][0]) - box[0], min(box[2], int(ref_region["staff_x"][1])) - box[0]],
        "size": [int(strip.shape[1]), int(strip.shape[0])],
        "reference_obs_id": mid["obs_id"],
        "member_obs_ids": [m["obs_id"] for m in picked],
        "inverted": bool(inverted),
        "paper_flattened": flattened,
        "preview_tail": preview,
        "issues": ([preview_issue] if preview_issue else []) + ([MINORITY_ISSUE] if minority["events"] else [])
        + ([UNCERTAIN_MARK_KEPT] if minority["events"] else [])
        + ([chrome_issue] if chrome_issue else []) + list(finish_info["issues"]),
        "finishing": finish_info,
        "screen_chrome": chrome_info,
        "single_row_full_height": bool(single_row),
        "row_cuts": cut_info,
        "blank_rows_trimmed": trimmed,
        **{k: v for k, v in cinfo.items()},
    }
    if cut_x is not None:
        record["uncut"] = {"box_crop": [int(v) for v in full_box], "size": [int(uncut.shape[1]), int(uncut.shape[0])],
                           "staff_y_strip": [round(float(y) - full_box[1], 2) for y in ref_region["staff_y"]]}
        record["_uncut_image"] = uncut
    # the uncut strip's pixels, so a missing/damaged uncut file can be regenerated and verified
    import hashlib
    record["uncut_pixels_sha256"] = hashlib.sha256(np.ascontiguousarray(uncut if cut_x is not None else strip).tobytes()).hexdigest()
    mrec = {k: v for k, v in minority.items() if not k.startswith("_")}
    for e in mrec["events"]:
        e["box_strip"] = [e["box_crop"][0] - box[0], e["box_crop"][1] - box[1], e["box_crop"][2] - box[0], e["box_crop"][3] - box[1]]
    for j, (_img, arec) in enumerate(alternates):
        for ei in arec["events"]:
            mrec["events"][ei]["alternate"] = j  # index; build_strips numbers the alternates
            mrec["events"][ei].setdefault("alternates", []).append(j)
    mrec["alternates"] = [a for _i, a in alternates]
    record["minority_content"] = mrec
    record["uncertain_marks"] = [{"seen": e["seen"], "eligible": e["eligible"], "bbox": e["box_strip"],
                                  "disposition": "review_bundle"} for e in mrec["events"]]
    clipped = source_clipping(ref_crop, box, manifest)
    if clipped:
        record["source_clipped"] = clipped
        record["issues"].append(SOURCE_CLIPPED)
    record["_alternate_images"] = [img for img, _a in alternates]
    _ledger_chain(record)
    if ledger and preview and preview.get("cut"):
        check = preview["checks"][0]
        rx, ry = check["removed_pixels"].get("refined_px", [0, 0])
        off_x = int(check["dest_x0"]) - int(preview["next_staff_x"]) + rx
        off_y = int(round(float(n_region["staff_y"][0]) - float(ref_region["staff_y"][0]))) + int(check.get("dest_dy_px", 0)) + ry
        fragment["display_dispositions"].append({"kind": "display_equivalent", "terminal": "equivalent_observation",
            "display_id": f"strip:{system['id']}", "retained_display_id": f"strip:{preview['destination_system_id']}",
            "region": [cut_x - comp_box[0], 0, comp_box[2] - comp_box[0], comp_box[3] - comp_box[1]],
            "equivalence_map": [[1, 0, comp_box[0] + off_x], [0, 1, comp_box[1] + off_y], [0, 0, 1]],
            "frame": "observation_crop", "registration_uncertainty": max(1, int(round(.15 * g))),
            "evidence": {"method": "verify_removed_pixels", **check}})
    return strip, record


def restore_uncut(rec: Dict[str, Any], *, reason: str) -> None:
    """Turn a cut strip record back into the uncut one (the tail stays on the source strip)."""
    unc = rec.pop("uncut")
    rec["box_crop"], rec["size"], rec["staff_y_strip"] = unc["box_crop"], unc["size"], unc["staff_y_strip"]
    rec["preview_tail"] = dict(rec["preview_tail"], cut=False, verified=False, reason=reason)
    rec["issues"] = sorted(set(rec.get("issues", [])) | {"PREVIEW_TAIL_UNVERIFIED"})
    if rec.get("ledger") is not None:
        rec["ledger"]["display_dispositions"] = [d for d in rec["ledger"].get("display_dispositions", [])
            if (d.get("evidence") or {}).get("method") != "verify_removed_pixels"]
    if rec.get("ledger_canvas_box_crop"):
        _ledger_chain(rec)


def check_destination_strips(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A cut stays only when the destination's own strip box holds the moved ink;
    otherwise the record is restored to the uncut strip. Returns the restored records."""
    by_id = {r["system_id"]: r for r in records}
    restored = []
    for rec in records:
        tail = rec.get("preview_tail") or {}
        if not tail.get("cut"):
            continue
        dbox = (by_id.get(tail.get("destination_system_id")) or {}).get("box_crop")
        ib = tail.get("dest_ink_box_crop")
        if not dbox or not ib or not (ib[0] >= dbox[0] and ib[1] >= dbox[1] and ib[2] <= dbox[2] and ib[3] <= dbox[3]):
            restore_uncut(rec, reason="destination_strip_does_not_hold_the_tail")
            restored.append(rec)
    return restored


def drop_screen_fixed_minority(records: List[Dict[str, Any]], alt_images_of: Dict[str, List[np.ndarray]]) -> List[Dict[str, Any]]:
    """Record screen-fixed suspicions without erasing credible foreground.

    Repeated position across displays is not positive cursor/chrome evidence:
    a real brief dot or thin stroke can recur there. Keep its events, flags and
    alternate pixels. The <=2 px speckle rule has already removed raw noise.
    The historical function name is retained for callers.
    """
    items = [{"display": r["system_id"], "box": e["box_crop"], "area_px": e["area_px"]}
             for r in records for e in (r.get("minority_content") or {}).get("events", [])]
    if not items:
        return []
    gap = float(np.median([r["staff_gap_px"] for r in records]))
    spots = mc.screen_fixed_spots(items, gap)
    for r in records:
        m = r.get("minority_content") or {}
        m["screen_fixed_suspicions"] = [dict(e) for e in m.get("events", [])
                                       if mc.in_screen_fixed_spot(e["box_crop"], e["area_px"], spots, gap)]
    return [dict(sp, gap=round(gap, 2), disposition="alternate_kept") for sp in spots]



def persist_raw_evidence(record: Dict[str, Any], out_dir: Path, system_id: str) -> None:
    """Persist lossless evidence once; small manifests can reference it repeatedly.

    Direct build_strip callers retain inline PNGs. Written jobs use native PNG
    crops with byte hashes, never a lossy thumbnail as the evidence artifact.
    """
    import base64
    import hashlib
    import re
    folder = Path(out_dir) / "evidence" / re.sub(r"[^a-zA-Z0-9_-]", "_", str(system_id))
    counter = 0

    def visit(value):
        nonlocal counter
        if isinstance(value, dict):
            encoded = value.pop("raw_png_base64", None)
            if encoded is not None:
                counter += 1
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"patch_{counter:06d}.png"
                payload = base64.b64decode(encoded, validate=True)
                path.write_bytes(payload)
                value.update(raw_path=str(path), raw_png_sha256=hashlib.sha256(payload).hexdigest())
            for child in list(value.values()):
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(record)


class _SystemWindowCache(dict):
    """Publish complete arrays atomically and retain only the active system window."""

    def __init__(self):
        super().__init__()
        self._lock = Lock()

    def get(self, key, default=None):
        with self._lock:
            return super().get(key, default)

    def __setitem__(self, key, value):
        with self._lock:
            super().__setitem__(key, value)

    def retain(self, keys):
        with self._lock:
            for key in list(self):
                if key not in keys:
                    super().__delitem__(key)


def _strip_threads() -> int:
    value = os.environ.get("REFLOW_STRIP_THREADS")
    if value is None:
        # 01Mr strips: 1 thread 76 s / 2.1 GiB, 2: 41 s / 2.7, 4: 29 s / 3.8, 10: 22 s / 4.8.
        # Four is the knee; each thread adds ~0.5 GiB, so small-memory machines get fewer.
        count = min(4, max(1, (os.cpu_count() or 2) - 1))
        try:
            ram_gib = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        except (AttributeError, ValueError, OSError):  # Windows has no sysconf
            ram_gib = None
        if ram_gib:
            count = min(count, max(1, int(ram_gib // 4)))
        return count
    try:
        count = int(value)
    except ValueError:
        raise ValueError("REFLOW_STRIP_THREADS must be an integer >= 1") from None
    if count < 1:
        raise ValueError("REFLOW_STRIP_THREADS must be an integer >= 1")
    return count


def build_strips(occurrences: Dict[str, Any], manifest: Dict[str, Any], load_image: ImageLoader, out_dir: Path, *,
                 logger: Callable[[str], None] = lambda _m: None, checkpoint: Callable[[], None] = lambda: None,
                 progress: Optional[Callable[[float], None]] = None, ledger: bool = False) -> List[Dict[str, Any]]:
    """Write ``strip_<system id>.png`` for every system; returns strip records with ``path``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obs_by = {o["id"]: o for o in manifest["observations"]}
    records = []
    systems = occurrences["systems"]
    images: Dict[str, np.ndarray] = {}
    alt_images_of: Dict[str, List[np.ndarray]] = {}
    chrome, chrome_info = job_screen_chrome(manifest, load_image)
    if chrome is not None:
        logger(f"strips: screen-fixed chrome {chrome_info.get('chrome_px')} px in {chrome_info.get('box')} "
               f"({chrome_info.get('displays')} distinct displays sampled)")
    workers = _strip_threads()
    foreground = _SystemWindowCache()
    # Keep members shared with adjacent systems even if the loader LRU evicts
    # them. Both caches cover only the bounded active window, not the whole job.
    held = _SystemWindowCache()
    evidence_lock = Lock()

    def uses(system):
        return {m["obs_id"] for key in ("observations", "ledger_observations") for m in (system.get(key) or [])}

    def clean_system(i):
        s = systems[i]
        own_ids = uses(s)
        def load_held(obs):
            img = held.get(obs["id"])
            if img is None:
                img = load_image(obs)
                if obs["id"] in own_ids:
                    held[obs["id"]] = img
            return img

        return build_strip(s, manifest, load_held, obs_by=obs_by, next_systems=systems[i + 1:], frame_foreground=foreground,
                           chrome=chrome if chrome is not None else False,
                           chrome_appearance=chrome_info.get("_appearance"), ledger=ledger,
                           evidence_dir=out_dir.parent / "ledger_evidence" if ledger else None,
                           evidence_lock=evidence_lock)

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="strips") if workers > 1 and systems else None
    pending = {}
    try:
        if executor is not None:
            for i in range(min(workers, len(systems))):
                checkpoint()
                pending[i] = executor.submit(clean_system, i)
        for i, s in enumerate(systems):
            checkpoint()
            if executor is None:
                own_ids = uses(s)
                held.retain(own_ids)
                foreground.retain(own_ids)
                strip, rec = clean_system(i)
            else:
                # Read futures strictly in display order, including failures.
                strip, rec = pending.pop(i).result()
            uncut = rec.pop("_uncut_image", None)
            alt_images_of[s["id"]] = rec.pop("_alternate_images", [])
            persist_raw_evidence(rec, out_dir, s["id"])
            path = out_dir / f"strip_{s['id']}.png"
            if not cv2.imwrite(str(path), strip):
                raise RuntimeError(f"failed to write strip {path}")
            rec["path"] = str(path)
            if uncut is not None:
                (out_dir / "uncut").mkdir(exist_ok=True)
                upath = out_dir / "uncut" / f"strip_{s['id']}.png"
                if not cv2.imwrite(str(upath), uncut):
                    raise RuntimeError(f"failed to write strip {upath}")
                rec["uncut"]["path"] = str(upath)
                images[s["id"]] = uncut
            records.append(rec)
            if progress is not None:
                progress((i + 1) / float(max(1, len(systems))))
            if executor is not None and i + workers < len(systems):
                checkpoint()
                pending[i + workers] = executor.submit(clean_system, i + workers)
            if executor is not None:
                active_ids = set()
                for j in pending:
                    active_ids.update(uses(systems[j]))
                held.retain(active_ids)
                foreground.retain(active_ids)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    for rec in check_destination_strips(records):
        cv2.imwrite(rec["path"], images[rec["system_id"]])
    by_id = {r["system_id"]: r for r in records}
    for rec in records:
        for disposition in (rec.get("ledger") or {}).get("display_dispositions", []):
            if disposition.get("frame") == "observation_crop":
                dest = by_id.get(disposition["retained_display_id"].removeprefix("strip:"))
                if dest is not None:
                    origin = dest["ledger_canvas_box_crop"]
                    disposition["equivalence_map"][0][2] -= origin[0]
                    disposition["equivalence_map"][1][2] -= origin[1]
                    disposition.pop("frame")
    spots = drop_screen_fixed_minority(records, alt_images_of)
    # alternate strips: numbered per placed system ("sys-005-alt2"); an alternate of an alternate
    # (a content-step state, reflow_occurrences) is numbered as another moment of the placed system
    parent_of = {s["id"]: s.get("alternate_of") or s["id"] for s in systems}
    counter: Dict[str, int] = {}
    for s in systems:
        if s.get("alternate_of"):
            counter[s["alternate_of"]] = counter.get(s["alternate_of"], 0) + 1
    for s, rec in zip(systems, records):
        parent = parent_of[s["id"]]
        for aimg, arec in zip(alt_images_of[s["id"]], rec["minority_content"]["alternates"]):
            counter[parent] = counter.get(parent, 0) + 1
            arec["suffix"] = f"alt{counter[parent]}"
            arec["parent_id"] = parent
            (out_dir / "alt").mkdir(exist_ok=True)
            apath = out_dir / "alt" / f"strip_{parent}-{arec['suffix']}.png"
            if not cv2.imwrite(str(apath), aimg):
                raise RuntimeError(f"failed to write strip {apath}")
            arec["path"] = str(apath)
        for e in rec["minority_content"]["events"]:
            if e.get("alternate") is not None:
                e["alternate"] = rec["minority_content"]["alternates"][e["alternate"]]["suffix"]
            if e.get("alternates"):
                e["alternates"] = [rec["minority_content"]["alternates"][j]["suffix"] for j in e["alternates"]]
    if spots:
        logger(f"strips: minority specks at {len(spots)} screen-fixed spots recorded as suspicions; alternates kept")
    logger(f"strips: {len(records)} written, {sum(1 for r in records if (r['preview_tail'] or {}).get('cut'))} preview tails cut "
           f"(verified), {sum(1 for r in records if r['issues'])} kept and flagged, "
           f"{sum(r['unrecovered_columns'] > 0 for r in records)} with unrecovered overlay columns, "
           f"{sum(1 for r in records if OVERLAY_COVERS_NOTATION in r['issues'])} with chrome touching notation, "
           f"{sum(1 for r in records if MINORITY_ISSUE in r['issues'])} with minority content kept as an alternate "
           f"({sum(len(r['minority_content']['alternates']) for r in records)} alternates), "
           f"{sum(1 for r in records if (r.get('ink_restored') or {}).get('px'))} with persistent ink restored after the median "
           f"({sum((r.get('ink_restored') or {}).get('components', 0) for r in records)} components, "
           f"{sum((r.get('ink_restored') or {}).get('px', 0) for r in records)} px)")
    return records
