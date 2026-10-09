"""System occurrences in display order (clean reflow, output model ``clean_reflow_v1``).

Decision record: docs/reflow/DECISIONS.md. The output order is the order the
video shows the systems. An established replay (repeat, D.S.) of at least three
consecutive whole cleaned displays matching one unique earlier consecutive
block is left unchecked by default only when each line is distinctive, the
blocks were displayed at separate times, and no acquired replay label is lost.
Its strips and minority alternates are kept for review
(``collapse_replay_blocks``). Single, two-line, ambiguous and out-of-order
matches stay placed. Other appearance matches are offered as a "looks similar"
note after the job (``suggest_similar_strips``), never blocking export.
The nonlocal identity gates of score_assembly.py are
not used on this path (that module stays for evaluation and later phases).

Input: an observation manifest (observations.py) and its display episodes
(system_tracking.py). One occurrence is one continuous display of one system:

* Episodes of one screen slot split only by a playhead reset are one display
  (the same system is still on screen; bF69 showed 57 episodes for 26 systems
  because its playhead detector fired on a preview bar).
* Episodes joined by a verified, one-to-one tracker continuity link (a preview
  row promoted to the active row, a row moving with its page by one shared
  offset) are one display. Unverified or competing matches stay separate and
  become "looks similar" notes (``continuity_suggestions``).
* A display shorter than ``MIN_OCCURRENCE_SEC`` (or with fewer than three
  observations) is a short display: a flicker, a page-curl or fade frame, a
  one-frame flash of another system, or a real system shown only briefly.
  Short displays are not placed by default. One is hidden only with positive
  evidence that its content is shown by a kept display around it: every
  non-staff foreground component of every raw member window - of any size,
  including gray and a 1-px dot, after colored pixels are masked - is drawn by one of the
  kept displays shown just before or after it at the same screen position
  (``shown_by_kept_display``), or it has no non-staff ink component at all.
  A tracker "small change" (page_diff ``ambiguous``) never counts as the same
  content here. Every
  other short display - including any first or terminal display - is listed
  as an excluded system with its own strip, so it can be restored in review.
  A view transition on its own is not evidence. Hidden displays keep their
  observation ids and times (decodable again from the source) and the kept
  systems that show their content.
* Rows displayed together (a page view) are ordered top to bottom; displays
  are otherwise ordered by the time they become the shown (active) system.
* Every join rule (tracker continuity, playhead reset, false content split, steady
  page-view row) passes one identity gate on raw polarity-normalized windows
  (``identity_verdict``: paper level, written display, measure-number area). A pair
  with evidence of two written occurrences is vetoed, recorded in ``identity_vetoes``,
  and no later rule may join it, directly or through a third display (``_VetoGuard``;
  Codex H1: a steady second row let a 13/17 pair be joined after its veto). Pixel-only
  rules check every raw member of both episodes; an unresolved member likewise
  keeps the groups apart, while the scan continues to look for a definite veto.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from pathlib import Path
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

import cv2

from app.pipeline import page_diff, system_detect, reflow_ledger as rl
from app.pipeline.system_tracking import (WINDOW_ABOVE_GAPS, clean_content, compare_content, comparable_windows, region_window,
                                          window_extent)

OCCURRENCES_VERSION = "reflow_occurrences-2"  # 2: whole-span identity for split joins
MIN_OCCURRENCE_SEC = 1.5
VIEW_CLUSTER_SEC = 1.5
RESET_JOIN_SEC = 1.0
TRANSITION_PEER_SEC = 0.75
NEIGHBOUR_MATCH_SEC = 3.0
DUPLICATE_GAP_TOL = 0.08
COVER_BLOCK_GAPS = 4.0       # column block width for the "shown by a kept display" test
COVER_MIN_FRACTION = 0.97    # share of a block's non-staff ink that one kept display must draw
COVER_DILATE_GAPS = 0.15     # registration tolerance (about 2 px at a 14 px gap)
SPLIT_JOIN_EXTRA_SEC = 0.5    # a content_change split is joined across at most one sample interval + this
PLAYHEAD_CONTINUE_TOL = 0.05  # b's first playhead reading >= a's last - this: the playhead went on
# 2b collapse needs positive evidence of one written occurrence (audit F1): measure-number area
# compared strictly; a difference is accepted only when it is a playback cursor at the playhead
NUMBER_AREA_LEFT_GAPS = 4.0    # measure-number area starts this far left of the staff start
NUMBER_AREA_RIGHT_GAPS = 8.0   # ... and reaches this far into the staff (above the top line)
NUMBER_AREA_MIN_AREA_GAPS = 0.02
NUMBER_AREA_MIN_PX = 4
CURSOR_MIN_HEIGHT_GAPS = 2.5   # a cursor mark spans most of the staff
CURSOR_X_TOL_GAPS = 1.0        # ... and lies this close to the playhead reading
CURSOR_MAX_WIDTH_GAPS = 0.5    # ... and is narrow (a notehead is wider)
SELF_CHECK_BUDGET_PAIRS = 3000
# written-display sameness (split join, self-checks): light anti-aliased text counts as ink and a
# differing piece of a measure-number digit (~0.06 gap^2) is a difference
WRITTEN_INK_THRESHOLD = 200
WRITTEN_MIN_AREA_GAPS = 0.06
WRITTEN_MIN_AREA_PX = 8
# 2b join identifiers are compared on raw polarity-normalized pixels (audit G1: clean_content
# whitens gray >= CLEAN_INK_MAX, so a gray measure number vanishes before it is compared). The
# comparison is trusted only where the paper is clearly lighter than the written-ink threshold
# and the number area is not hidden under a colored overlay; otherwise the split is kept.
RAW_PAPER_MIN = WRITTEN_INK_THRESHOLD + 20
NUMBER_AREA_MAX_MASKED = 0.25  # share of number-area columns under an overlay that still allows a verdict
NUMBER_AREA_SHIFT_TOL_PX = 1   # registration tolerance around the whole-window shift

ImageLoader = Callable[[Dict[str, Any]], np.ndarray]


class _UF:
    def __init__(self, items: Sequence[str]):
        self.p = {i: i for i in items}

    def find(self, a: str) -> str:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            keep, drop = sorted([ra, rb])
            self.p[drop] = keep


class _VetoGuard:
    """Never merge groups holding a vetoed or unresolved pixel-identity pair."""

    def __init__(self, uf: _UF):
        self.uf = uf
        self.pairs: List[Tuple[str, str]] = []

    def veto(self, a: str, b: str) -> None:
        self.pairs.append((a, b))

    def blocks(self, a: str, b: str) -> bool:
        ra, rb = self.uf.find(a), self.uf.find(b)
        if ra == rb:
            return False
        return any({self.uf.find(x), self.uf.find(y)} == {ra, rb} for x, y in self.pairs)

    def join(self, a: str, b: str) -> bool:
        if self.blocks(a, b):
            return False
        self.uf.union(a, b)
        return True


def _obs_index(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {o["id"]: o for o in manifest["observations"]}


def _region(obs: Dict[str, Any], region_id: str) -> Dict[str, Any]:
    return next(r for r in obs["system_regions"] if r["region_id"] == region_id)


def _order_time(eps: List[Dict[str, Any]]) -> float:
    """When the display became the shown system: the start of its first
    non-preview episode (a preview row is shown early, beside the active one)."""
    shown = [e for e in eps if e.get("role") not in ("preview",)]
    return min(e["t_start"] for e in (shown or eps))


def _window_of(manifest_obs: Dict[str, Dict[str, Any]], load_image: ImageLoader, obs_id: str, region_id: str):
    obs = manifest_obs[obs_id]
    r = _region(obs, region_id)
    crop = clean_content(load_image(obs))
    return region_window(crop, r), window_extent(r), float(r["staff_gap_px"]), r


def _raw_window_of(manifest_obs: Dict[str, Dict[str, Any]], load_image: ImageLoader, obs_id: str, region_id: str):
    """``_window_of`` without the destructive cleaning: polarity-normalized pixels only, so light
    or gray ink (a measure number drawn at gray 120-190) is still there to compare (audit G1)."""
    obs = manifest_obs[obs_id]
    r = _region(obs, region_id)
    norm, _inv = system_detect.normalize_polarity(load_image(obs))
    return region_window(norm, r), window_extent(r), float(r["staff_gap_px"]), r


def raw_paper_level(wt: Tuple) -> float:
    """Paper level of a raw window: the 75th percentile of its gray within the region's band."""
    win, ext, gap, _r = wt
    g = cv2.cvtColor(win, cv2.COLOR_BGR2GRAY) if win.ndim == 3 else win
    top = int(round(WINDOW_ABOVE_GAPS * gap))
    lo, hi = max(0, top - int(ext[0])), min(g.shape[0], int(round(top + 4 * gap)) + int(ext[1]))
    band = g[lo:hi] if hi > lo else g
    return float(system_detect.percentile_u8(np.ascontiguousarray(band), 75))


def _same_display_content(a: Tuple, b: Tuple) -> bool:
    """Tracker-level sameness (page_diff ``same`` or ``ambiguous/small_change``).
    Used only for "looks similar" suggestions, never as a reason to hide or join content."""
    wa, ea, ga, _ra = a
    wb, eb, gb, _rb = b
    if abs(ga - gb) > DUPLICATE_GAP_TOL * max(ga, gb):
        return False
    x, y = comparable_windows(wa, ea, wb, eb, ga)
    return compare_content(x, y, ga).state == "same"


def _strictly_same_image(a: Tuple, b: Tuple) -> bool:
    """page_diff verdict exactly ``same`` (``ambiguous``/``small_change`` is NOT the same)."""
    wa, ea, ga, _ra = a
    wb, eb, gb, _rb = b
    if abs(ga - gb) > DUPLICATE_GAP_TOL * max(ga, gb):
        return False
    x, y = comparable_windows(wa, ea, wb, eb, ga)
    c = compare_content(x, y, ga)
    return c.state == "same" and c.verdict == page_diff.VERDICT_SAME


def _nonstaff_ink(win: np.ndarray, gap: float) -> np.ndarray:
    """Ink of a cleaned window without staff lines (long horizontal runs)."""
    return _ink_split(win, gap)[0]


def _ink_split(win: np.ndarray, gap: float) -> Tuple[np.ndarray, np.ndarray]:
    """(non-staff ink, staff-line ink) of a cleaned window; staff lines are horizontal
    runs of at least four staff gaps."""
    gray = cv2.cvtColor(win, cv2.COLOR_BGR2GRAY) if win.ndim == 3 else win
    ink = (gray < 200).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, int(round(4 * gap))), 1))
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k)
    return (ink & (1 - lines)).astype(bool), lines.astype(bool)


def _overlay_columns_of(win: np.ndarray) -> np.ndarray:
    """Columns covered by a colored playback overlay in a cleaned window (ink that is
    clearly colored); those columns cannot be judged and are skipped."""
    if win.ndim != 3:
        return np.zeros(win.shape[1], bool)
    hsv = cv2.cvtColor(win, cv2.COLOR_BGR2HSV)
    colored = (hsv[..., 1] > 80) & (hsv[..., 2] > 60)
    cols = colored.sum(axis=0) >= 3
    if cols.any():
        cols = cv2.dilate(cols.astype(np.uint8)[None, :], np.ones((1, 7), np.uint8))[0] > 0
    return cols


def _cover_mask(win: np.ndarray, gap: float) -> np.ndarray:
    """Where a kept display draws ink: its non-staff ink with a small registration
    tolerance (``COVER_DILATE_GAPS``) plus its staff lines widened by 1 px."""
    nonstaff, lines = _ink_split(win, gap)
    r = max(1, int(round(COVER_DILATE_GAPS * gap)))
    m = cv2.dilate(nonstaff.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0
    return m | (cv2.dilate(lines.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)


def _fit(mask: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    """``mask`` cropped/padded (False) to ``shape``; rows/columns a window does not have draw nothing."""
    out = np.zeros(shape, bool)
    h, w = min(shape[0], mask.shape[0]), min(shape[1], mask.shape[1])
    out[:h, :w] = mask[:h, :w]
    return out


def shown_by_kept_display(frag_wins: Sequence[Tuple], neighbour_wins: Iterable[Tuple], *,
                          raw_evidence: bool = False) -> Dict[str, Any]:
    """Positive evidence that a short display's content is drawn by kept displays.

    ``frag_wins`` / ``neighbour_wins``: (window, extent, gap, region) tuples
    windows anchored at the top staff line. With ``raw_evidence=True`` callers
    provide every raw polarity-normalized member, including previews: paper must
    be light, only colored pixels are masked (gray in the same column remains),
    and every foreground pixel must be recovered within registration tolerance.
    The default retains the older column masking/fraction policy for joins.
    For every supplied window of the short display:

    * every non-staff ink component - of any size, a 1-px dot included - must
      have >= ``COVER_MIN_FRACTION`` of its pixels drawn by ONE kept display
      (small registration tolerance); a single unmatched component keeps the
      display listed (``unexplained_component``);
    * every column block (``COVER_BLOCK_GAPS`` staff gaps wide) with notation/text
      ink must likewise be drawn by one kept display (``unexplained_content``).

    ``no_content_beyond_staff_lines`` means all supplied windows hold no non-staff
    ink component at all (not a size threshold).
    """
    if not frag_wins:
        return {"shown": False, "reason": "no_samples"}
    gap = float(frag_wins[0][2])
    if raw_evidence and any(raw_paper_level(w) < RAW_PAPER_MIN for w in frag_wins):
        return {"shown": False, "reason": "paper_not_light"}
    nb_masks = []
    for nw in neighbour_wins:
        if abs(float(nw[2]) - gap) > DUPLICATE_GAP_TOL * max(gap, float(nw[2])):
            continue
        if raw_evidence and raw_paper_level(nw) < RAW_PAPER_MIN:
            continue  # a dark/translucent background cannot prove foreground recovery
        win = nw[0]
        if raw_evidence and win.ndim == 3:
            win = win.copy()
            win[cv2.cvtColor(win, cv2.COLOR_BGR2HSV)[..., 1] > 80] = 255
        nb_masks.append(_cover_mask(win, gap))
    block = max(8, int(round(COVER_BLOCK_GAPS * gap)))
    min_block_ink = max(6, int(round(0.3 * gap * gap)))
    total_components = 0
    worst = 1.0
    for fw in frag_wins:
        if abs(float(fw[2]) - gap) > DUPLICATE_GAP_TOL * max(gap, float(fw[2])):
            return {"shown": False, "reason": "staff_size_differs"}
        win = fw[0]
        if raw_evidence and win.ndim == 3:
            # Mask colored pixels, never their entire columns: a gray stroke beside
            # a cursor is still an obligation. The join/suggestion path is unchanged.
            win = win.copy()
            win[cv2.cvtColor(win, cv2.COLOR_BGR2HSV)[..., 1] > 80] = 255
        f = _nonstaff_ink(win, gap)
        if not raw_evidence:
            f[:, _overlay_columns_of(fw[0])] = False
        n, lab, stats, _c = cv2.connectedComponentsWithStats(f.astype(np.uint8), connectivity=8)
        if n <= 1:
            continue
        total_components += n - 1
        if not nb_masks:
            return {"shown": False, "reason": "no_kept_neighbour", "components": int(n - 1)}
        area = np.bincount(lab.ravel(), minlength=n).astype(np.float64)
        best = np.zeros(n)
        fitted = [_fit(m, f.shape) for m in nb_masks]
        for m in fitted:
            best = np.maximum(best, np.bincount(lab[m].ravel(), minlength=n) / np.maximum(area, 1.0))
        # Even an attached one-pixel gray tip must be recovered before hiding.
        minimum = 1.0 if raw_evidence else COVER_MIN_FRACTION
        bad = [i for i in range(1, n) if best[i] < minimum]
        if bad:
            i = min(bad, key=lambda k: best[k])
            x, y, w, h, a = (int(v) for v in stats[i])
            return {"shown": False, "reason": "unexplained_component", "component_area_px": a,
                    "component_box": [x, y, x + w, y + h], "component_fraction": round(float(best[i]), 3),
                    "unexplained_components": len(bad)}
        worst = min(worst, float(best[1:].min()))
        for x0 in range(0, f.shape[1], block):
            fb = f[:, x0:x0 + block]
            nb_ = int(fb.sum())
            if nb_ < min_block_ink:
                continue  # its components were checked above
            bb = max(float((fb & m[:, x0:x0 + block]).sum()) / nb_ for m in fitted)
            worst = min(worst, bb)
            if bb < minimum:
                return {"shown": False, "reason": "unexplained_content", "worst_block_fraction": round(bb, 3), "block_x": x0}
    if total_components == 0:
        return {"shown": True, "reason": "no_content_beyond_staff_lines"}
    return {"shown": True, "reason": "covered_by_kept_display", "worst_block_fraction": round(worst, 3)}


def _member_observations(episodes: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Every member observation, including previews and non-representative states."""
    return list(dict.fromkeys((o, r) for e in episodes
                             for o, r in zip(e["observation_ids"], e["region_ids"])))


def _ledger_strip_origin(system: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]],
                         load_image: ImageLoader) -> Optional[List[int]]:
    """Exact single-row pre-trim canvas origin; multi-row cuts need the strip hook."""
    from app.pipeline import notation_envelope as ne
    from app.pipeline.overlay_composite import _MAX_MEMBERS
    members = system["observations"]
    widths = [(_region(obs_by[m["obs_id"]], m["region_id"])["staff_x"][1] -
               _region(obs_by[m["obs_id"]], m["region_id"])["staff_x"][0]) for m in members]
    full = [m for m, wd in zip(members, widths) if wd >= .97 * float(np.median(widths))] or members

    def evenly(seq, count):
        return list(seq) if len(seq) <= count else [seq[i] for i in sorted(set(
            np.linspace(0, len(seq) - 1, count).round().astype(int).tolist()))]

    picked = evenly(full, _MAX_MEMBERS)
    mid = picked[len(picked) // 2]
    obs = obs_by[mid["obs_id"]]
    if len(obs.get("system_regions") or []) > 1:
        return None
    region = _region(obs, mid["region_id"])
    g = float(region["staff_gap_px"])
    env = None
    for m in evenly(picked, 3):
        r = _region(obs_by[m["obs_id"]], m["region_id"])
        rows = ne.frame_envelope(load_image(obs_by[m["obs_id"]]))["rows"]
        matching = [row for row in rows if abs(float(row["staff_y"][0]) - float(r["staff_y"][0])) <= 1.5 * float(r["staff_gap_px"])]
        if matching:
            row = min(matching, key=lambda row: abs(float(row["staff_y"][0]) - float(r["staff_y"][0])))
            b = row["envelope_bbox"]
            env = list(b) if env is None else [min(env[0], b[0]), min(env[1], b[1]), max(env[2], b[2]), max(env[3], b[3])]
    env = env if env is not None else region.get("envelope_bbox")
    if env is None:
        return None
    return [min(max(0, int(np.floor(env[0] - .5 * g))), int(region["staff_x"][0])), 0]


def sample_interval(manifest: Dict[str, Any]) -> float:
    """The regular sampling interval of a manifest (its coarse grid; all samples when none is marked)."""
    obs = manifest.get("observations", [])
    coarse = sorted(o["t_sec"] for o in obs if o.get("sample_kind") == "coarse")
    ts = coarse if len(coarse) >= 3 else sorted(o["t_sec"] for o in obs)
    d = np.diff(ts) if len(ts) >= 2 else np.zeros(0)
    d = d[d > 1e-6]
    return float(np.median(d)) if d.size else 0.5


def _window_staff_rows(wt: Tuple) -> np.ndarray:
    """Staff-line rows of a window (``_window_of`` tuple): the region's five lines, placed in the
    window (anchored at its top line), each widened by 1 px plus half a line, joined with the
    lines found in the window's own ink (page_diff.staff_line_rows: tilt, thick lines)."""
    win, _ext, gap, region = wt
    h = win.shape[0]
    rows = np.zeros(h, bool)
    ys = [float(y) for y in region.get("staff_y", [])]
    if ys:
        y0 = int(round(ys[0] - WINDOW_ABOVE_GAPS * gap))
        r = 1 + max(1, int(round(0.08 * gap)))
        for y in ys:
            c = int(round(y)) - y0
            rows[max(0, c - r):max(0, min(h, c + r + 1))] = True
    gray = cv2.cvtColor(win, cv2.COLOR_BGR2GRAY) if win.ndim == 3 else win
    rows |= page_diff.staff_line_rows((gray < 200).astype(np.uint8) * 255, gap=gap)
    return rows


def same_written_display(a: Tuple, b: Tuple) -> Tuple[bool, Dict[str, Any]]:
    """Two windows (``_window_of`` tuples) show the same written display: every ink element
    beyond the staff lines - notation, measure numbers, text - is drawn by both
    (``_same_whole_display``). Staff-line rows are masked (their rendering drift is never
    content) and so are the columns under a colored playback overlay in either window."""
    wa, ea, ga, _ra = a
    wb, eb, gb, _rb = b
    if abs(ga - gb) > DUPLICATE_GAP_TOL * max(ga, gb):
        return False, {"reason": "staff_size_differs"}
    x, y = comparable_windows(wa, ea, wb, eb, ga)
    h = min(x.shape[0], y.shape[0])
    x, y = x[:h].copy(), y[:h].copy()
    w = max(x.shape[1], y.shape[1])
    # the overlay columns of either window are blanked in both: a moving highlight is not content
    cols = _fit(_overlay_columns_of(x)[None, :], (1, w))[0] | _fit(_overlay_columns_of(y)[None, :], (1, w))[0]
    rows = _fit(_window_staff_rows(a)[:, None], (h, 1))[:, 0] | _fit(_window_staff_rows(b)[:, None], (h, 1))[:, 0]
    for im in (x, y):
        im[rows] = 255
        im[:, cols[:im.shape[1]]] = 255
    same, info = _same_whole_display(x, y, ga, ink_threshold=WRITTEN_INK_THRESHOLD, min_area_gaps=WRITTEN_MIN_AREA_GAPS,
                                     min_area_px=WRITTEN_MIN_AREA_PX)
    if not same:
        return same, info
    # every ink component (a digit of a measure number, a radius-2 dot) drawn by the other window;
    # specks below WRITTEN_MIN_AREA_PX (compression noise, a stray pixel of screen chrome) are left out
    x, y = _drop_specks(x, WRITTEN_MIN_AREA_PX), _drop_specks(y, WRITTEN_MIN_AREA_PX)
    for p, q, side in ((x, y, "a"), (y, x, "b")):
        cov = shown_by_kept_display([(p, ea, ga, None)], [(q, eb, gb, None)])
        if not cov.get("shown"):
            return False, {**info, "reason": "component_not_drawn_by_other", "side": side,
                           **{k: v for k, v in cov.items() if k != "shown"}}
    return True, info


def _drop_specks(img: np.ndarray, min_px: int) -> np.ndarray:
    """``img`` with ink components (gray < WRITTEN_INK_THRESHOLD) smaller than ``min_px`` painted white."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    n, lab, stats, _c = cv2.connectedComponentsWithStats((gray < WRITTEN_INK_THRESHOLD).astype(np.uint8), connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] < min_px)[0]
    small = small[small > 0]
    if small.size == 0:
        return img
    out = img.copy()
    out[np.isin(lab, small)] = 255
    return out


def _playhead_end(e: Dict[str, Any], which: str) -> Optional[float]:
    track = (e.get("motion") or {}).get("playhead_track") or []
    if not track:
        return None
    return float(track[0][1] if which == "first" else track[-1][1])


def _staff_start_x(wt: Tuple) -> int:
    """Column where the staff of a window (``_window_of`` tuple) starts: the region's
    ``staff_x``, else the first column of the staff lines found in the window's ink."""
    win, _ext, gap, region = wt
    sx = region.get("staff_x") if isinstance(region, dict) else None
    if sx:
        return int(sx[0])
    _ns, lines = _ink_split(win, gap)
    cols = np.nonzero(lines.any(axis=0))[0]
    return int(cols[0]) if cols.size else 0


def measure_number_area_differs(a: Tuple, b: Tuple, shift: Sequence[float] = (0.0, 0.0)) -> Optional[Dict[str, Any]]:
    """Ink in the measure-number area of two windows that only one draws, or no confident verdict.

    ``a`` / ``b``: raw polarity-normalized windows (``_raw_window_of``; a cleaned window has lost
    gray ink, audit G1). The area is where a system's printed identifier sits: the band above the
    top staff line from a little left of the staff start to ``NUMBER_AREA_RIGHT_GAPS`` gaps into
    the staff, and the margin left of the staff start beside the staff. Ink is gray <
    ``WRITTEN_INK_THRESHOLD`` (a gray-180 digit counts). It is compared far more strictly than the
    whole display (``NUMBER_AREA_MIN_AREA_GAPS``, 1 px tolerance) after registering by ``shift``
    (the whole-window shift) give or take ``NUMBER_AREA_SHIFT_TOL_PX`` (the best of those shifts
    is used: staff drift and re-rendering move a number by a pixel, a changed digit stays).
    Staff-line rows and colored overlay columns are masked.

    Returns ``None`` only when the areas agree with confidence. Evidence of a difference has
    reason ``measure_number_area_differs``; ``number_area_uncertain`` when the area cannot be
    compared (paper not clearly lighter than the ink threshold, or the area mostly under a
    colored overlay) - never a reason to join."""
    wa, ea, ga, _ra = a
    wb, eb, gb, _rb = b
    x, y = comparable_windows(wa, ea, wb, eb, ga)
    h, w = min(x.shape[0], y.shape[0]), max(x.shape[1], y.shape[1])
    cols = _fit(_overlay_columns_of(x)[None, :], (1, w))[0] | _fit(_overlay_columns_of(y)[None, :], (1, w))[0]
    rows = _fit(_window_staff_rows(a)[:, None], (h, 1))[:, 0] | _fit(_window_staff_rows(b)[:, None], (h, 1))[:, 0]
    top = int(round(WINDOW_ABOVE_GAPS * ga))      # the top staff line row of the window
    x0 = min(_staff_start_x(a), _staff_start_x(b))
    xl, xr = max(0, int(x0 - NUMBER_AREA_LEFT_GAPS * ga)), min(w, max(0, int(x0 + NUMBER_AREA_RIGHT_GAPS * ga)))
    area = np.zeros((h, w), bool)
    area[:max(0, top - 1), xl:xr] = True
    area[:min(h, int(top + 4 * ga + ga)), xl:max(xl, x0 - 1)] = True
    # rows only one window can see were blanked by comparable_windows: judge the rest
    visible = np.zeros(h, bool)
    lim_top = int(round(WINDOW_ABOVE_GAPS * ga)) - int(min(ea[0], eb[0], WINDOW_ABOVE_GAPS * ga))
    visible[max(0, lim_top):] = True
    area &= visible[:, None]
    grays = []
    for im in (x, y):
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        gg = np.full((h, w), 255, np.uint8)
        gg[:, :g.shape[1]] = g[:h, :w]
        grays.append(gg)
    if xr > xl:
        masked = float(cols[xl:xr].mean())
        if masked > NUMBER_AREA_MAX_MASKED:
            return {"reason": "number_area_uncertain", "why": "overlay_covers_number_area", "masked_share": round(masked, 3)}
    judged = area & ~rows[:, None] & ~cols[None, :]
    if judged.any():
        papers = [float(np.percentile(gg[judged], 75)) for gg in grays]
        if min(papers) < RAW_PAPER_MIN:
            return {"reason": "number_area_uncertain", "why": "paper_not_light", "paper": [round(p_, 1) for p_ in papers]}
    ink = []
    for gg in grays:
        m = (gg < WRITTEN_INK_THRESHOLD).astype(np.uint8)
        m[rows] = 0
        m[:, cols] = 0
        ink.append(m)
    ia = ink[0]
    bx, by = (int(round(float(v))) for v in (list(shift) + [0.0, 0.0])[:2])
    k = np.ones((3, 3), np.uint8)
    dil_a = cv2.dilate(ia, k)
    r = max(1, int(round(0.15 * ga)))
    min_area = max(NUMBER_AREA_MIN_PX, int(round(NUMBER_AREA_MIN_AREA_GAPS * ga * ga)))
    best: Optional[Dict[str, Any]] = None
    t = NUMBER_AREA_SHIFT_TOL_PX
    for dy in range(by - t, by + t + 1):
        for dx in range(bx - t, bx + t + 1):
            mat = np.float32([[1, 0, -dx], [0, 1, -dy]])
            ib = cv2.warpAffine(ink[1], mat, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
            only_a = ia & (1 - cv2.dilate(ib, k)) & area
            only_b = ib & (1 - dil_a) & area
            residue = (only_a | only_b).astype(np.uint8)
            if not residue.any():
                return None
            n, lab = cv2.connectedComponents(cv2.dilate(residue, np.ones((2 * r + 1, 2 * r + 1), np.uint8)), connectivity=8)
            sizes = np.bincount(lab[residue > 0].ravel(), minlength=n)[1:]
            big = [i + 1 for i, v in enumerate(sizes) if v >= min_area]
            if not big:
                return None
            sel = np.isin(lab, big) & (residue > 0)
            px = int(sel.sum())
            if best is None or px < best["px"]:
                ys, xs = np.nonzero(sel)
                best = {"reason": "measure_number_area_differs", "pieces": len(big), "px": px,
                        "only_a_px": int((sel & (only_a > 0)).sum()), "only_b_px": int((sel & (only_b > 0)).sum()),
                        "box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], "staff_start_x": x0,
                        "shift": [dx, dy]}
    return best


def _playhead_px(wt: Tuple, frac: Optional[float]) -> Optional[float]:
    """A playhead reading (fraction of the region width) as a window column."""
    if frac is None:
        return None
    region = wt[3] if isinstance(wt[3], dict) else {}
    bbox = region.get("bbox")
    if not bbox:
        return None
    return float(bbox[0]) + float(frac) * float(bbox[2] - bbox[0])


def differs_only_by_cursor(info: Dict[str, Any], a: Tuple, b: Tuple, xa: Optional[float], xb: Optional[float]) -> bool:
    """Positive evidence that two windows differ only by a playback cursor: every differing
    piece (``_same_whole_display`` pieces) is a narrow mark (at most ``CURSOR_MAX_WIDTH_GAPS``
    wide) within ``CURSOR_X_TOL_GAPS`` gaps of the playhead reading of the side that draws it
    (a's last reading, b's first), and the pieces of each side together span at least
    ``CURSOR_MIN_HEIGHT_GAPS`` gaps vertically (a cursor broken where notation crosses it is
    still one cursor). Needs both readings; any other piece - a notehead, a digit, a mark away
    from the cursor - is notation that one side does not draw."""
    pieces = info.get("pieces") or []
    if not pieces or info.get("pieces_truncated") or xa is None or xb is None:
        return False
    gap = float(a[2])
    pa, pb = _playhead_px(a, xa), _playhead_px(b, xb)
    if pa is None or pb is None:
        return False
    tol, max_w = CURSOR_X_TOL_GAPS * gap, max(4.0, CURSOR_MAX_WIDTH_GAPS * gap)
    span: Dict[str, List[int]] = {}
    for p in pieces:
        x0, y0, x1, y1 = p["box"]
        if (x1 - x0) > max_w:
            return False
        for side, px in (("a", pa), ("b", pb)):
            if p.get(f"only_{side}_px", 0) > 0:
                if not (x0 >= px - tol and x1 <= px + tol):
                    return False
                lo, hi = span.get(side, [y0, y1])
                span[side] = [min(lo, y0), max(hi, y1)]
    return bool(span) and all((hi - lo) >= CURSOR_MIN_HEIGHT_GAPS * gap for lo, hi in span.values())


# listed like a minority-content alternate ("other moment"), described as another state of its system
CONTENT_STEP_ALTERNATE_ISSUES = ["MINORITY_ALTERNATE", "CONTENT_STEP_STATE"]


def _family_of(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The content-step family (system_tracking) of a candidate: its id and the best score of its parts."""
    if c.get("family"):
        return dict(c["family"])
    fams = [m["content_family"] for m in c["episodes"] if m.get("content_family")]
    if not fams:
        return None
    fid = fams[0]["id"]
    return {"id": fid, "score": max(f["score"] for f in fams if f["id"] == fid)}


def content_step_alternates(occ: Sequence[Dict[str, Any]], listed: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """Candidates that are another state of a placed display split at content steps -> the root of
    the placed state. Per family, the placed state is the kept display (long enough to place) that
    shows the most of the steps' ink (``score``: the steps at which it is the state with the ink, so
    a mark added for good places the later state and one removed for good the earlier); a tie goes
    to the later state. Every other kept or listed state of the family is its alternate. A family
    with no kept display is left alone (its states stay listed short displays)."""
    fam: Dict[str, List[Tuple[Dict[str, Any], bool, int]]] = {}
    for c, kept in [(c, True) for c in occ] + [(c, False) for c in listed]:
        f = _family_of(c)
        if f:
            fam.setdefault(f["id"], []).append((c, kept, f["score"]))
    out: Dict[str, str] = {}
    for parts in fam.values():
        kept = [(c, sc) for c, k, sc in parts if k]
        if len(parts) < 2 or not kept:
            continue
        primary = max(kept, key=lambda x: (x[1], x[0]["t_start"]))[0]
        for c, _k, _sc in parts:
            if c["root"] != primary["root"]:
                out[c["root"]] = primary["root"]
    return out


def build_occurrences(
    tracking: Dict[str, Any],
    manifest: Dict[str, Any],
    load_image: ImageLoader,
    *,
    min_occurrence_sec: float = MIN_OCCURRENCE_SEC,
    logger: Callable[[str], None] = lambda _m: None,
    exclude_episode_ids: Sequence[str] = (),
    evidence_dir: Optional[Path] = None,
    ledger: bool = False,
) -> Dict[str, Any]:
    """Ordered system occurrences (display order) plus listed/hidden fragments.

    ``exclude_episode_ids``: episodes shown by jump-view panorama strips (reflow_jump); they
    are not page systems."""
    all_eps = tracking.get("episodes", [])
    unsupported = [iv for iv in tracking.get("layout_intervals", []) if not iv.get("supported", True)]
    excluded = set(exclude_episode_ids)
    eps = [e for e in all_eps if e.get("layout") != "horizontal_scroll" and e["id"] not in excluded]
    ep_by = {e["id"]: e for e in eps}
    uf = _UF([e["id"] for e in eps])
    guard = _VetoGuard(uf)
    joins: List[Dict[str, Any]] = []
    identity_vetoes: List[Dict[str, Any]] = []
    obs_by = _obs_index(manifest)
    window_cache: Dict[str, Tuple] = {}

    def ep_window(e: Dict[str, Any], where: str) -> Tuple:
        key = f"{e['id']}:{where}"
        if key not in window_cache:
            k = 0 if where == "first" else len(e["observation_ids"]) - 1
            window_cache[key] = _window_of(obs_by, load_image, e["observation_ids"][k], e["region_ids"][k])
        return window_cache[key]

    raw_cache: Dict[str, Tuple] = {}

    def ep_raw_window(e: Dict[str, Any], where) -> Tuple:
        """Cache endpoints only; whole-span member windows are transient."""
        if isinstance(where, int):
            if where == 0:
                where = "first"
            elif where == len(e["observation_ids"]) - 1:
                where = "last"
            else:
                return _raw_window_of(obs_by, load_image, e["observation_ids"][where], e["region_ids"][where])
        key = f"{e['id']}:{where}"
        if key not in raw_cache:
            k = 0 if where == "first" else len(e["observation_ids"]) - 1
            raw_cache[key] = _raw_window_of(obs_by, load_image, e["observation_ids"][k], e["region_ids"][k])
        return raw_cache[key]

    playhead_index: Dict[str, Tuple[List[float], List[Tuple]]] = {}

    def identity_verdict(a: Dict[str, Any], b: Dict[str, Any], *, identifier_veto_only: bool = False,
                         where_a="last", where_b="first") -> Tuple[str, Dict[str, Any]]:
        """One identity gate for every join rule, on raw windows of a's last and b's first view
        (audit G1: cleaning whitens gray measure numbers). ``same``: positive evidence of one
        written occurrence (the same written display, or a difference that is only the playback
        cursor at the playhead readings, and a strictly agreeing measure-number area). ``veto``:
        evidence of two written occurrences (notation or a printed identifier one side does not
        draw). ``uncertain``: no confident comparison (paper not clearly light, staff size
        differs, number area under an overlay, no pixels). The record carries ``kept_apart``."""
        def reading(e, where):
            if not isinstance(where, int):
                return _playhead_end(e, where)
            # Cursor-only evidence must use this member's reading, not the episode endpoint.
            if e["id"] not in playhead_index:
                entries = sorted((float(ts), i, x) for i, (ts, x) in enumerate(
                    (e.get("motion") or {}).get("playhead_track") or []))
                playhead_index[e["id"]] = ([ts for ts, _i, _x in entries], entries)
            times, entries = playhead_index[e["id"]]
            t = obs_by[e["observation_ids"][where]]["t_sec"]
            lo, hi = bisect_left(times, t - 0.0001), bisect_right(times, t + 0.0001)
            matches = [entry for entry in entries[lo:hi] if abs(entry[0] - t) < 0.0001]
            # Preserve the first track reading if timestamps coincide or nearly coincide.
            return float(min(matches, key=lambda entry: entry[1])[2]) if matches else None

        try:
            xa, xb = reading(a, where_a), reading(b, where_b)
            wa_raw, wb_raw = ep_raw_window(a, where_a), ep_raw_window(b, where_b)
            papers = [raw_paper_level(wa_raw), raw_paper_level(wb_raw)]
        except Exception as exc:  # pragma: no cover - defensive: no pixels, no verdict
            logger(f"identity comparison failed: {exc}")
            return "uncertain", {"kept_apart": f"comparison_failed: {exc}"}
        if min(papers) < RAW_PAPER_MIN:
            # the paper is not clearly lighter than the ink threshold (a background showing
            # through): ink cannot be told apart without destructive cleaning
            return "uncertain", {"kept_apart": "identity_uncertain",
                                 "evidence": {"reason": "paper_not_light", "paper": [round(p, 1) for p in papers]},
                                 "playhead": [xa, xb]}
        try:
            same, info = same_written_display(wa_raw, wb_raw)
        except Exception as exc:  # pragma: no cover - defensive
            logger(f"identity comparison failed: {exc}")
            return "uncertain", {"kept_apart": f"comparison_failed: {exc}"}
        # a difference accepted only when it is the playback cursor at each side's playhead reading
        cursor_only = (not same and info.get("reason") == "content_differs"
                       and differs_only_by_cursor(info, wa_raw, wb_raw, xa, xb))
        if not (same or cursor_only):
            kind = "uncertain" if info.get("reason") == "staff_size_differs" else "veto"
            if kind == "veto" and identifier_veto_only:
                # a rule with its own tracker evidence (a verified continuity link, a playhead
                # reset): the whole-display difference may be the moved highlight, a preview's
                # rendering or background showing through, so only a differing printed
                # identifier vetoes it; otherwise the identity is uncertain
                try:
                    number = measure_number_area_differs(wa_raw, wb_raw, info.get("shift") or (0.0, 0.0))
                except Exception:  # pragma: no cover - defensive: no evidence, no veto
                    number = {"reason": "number_area_uncertain"}
                if number is not None and number.get("reason") != "number_area_uncertain":
                    return "veto", {"kept_apart": "measure_number_area_differs", "evidence": number, "playhead": [xa, xb]}
                kind = "uncertain"
            return kind, {"kept_apart": "written_display_differs", "evidence": info, "playhead": [xa, xb]}
        try:
            number = measure_number_area_differs(wa_raw, wb_raw, info.get("shift") or (0.0, 0.0))
        except Exception as exc:  # pragma: no cover - defensive: no evidence, no join
            logger(f"identity number-area comparison failed: {exc}")
            return "uncertain", {"kept_apart": "identity_uncertain", "evidence": {"reason": f"comparison_failed: {exc}"},
                                 "playhead": [xa, xb]}
        if number is not None:
            if number.get("reason") == "number_area_uncertain":
                return "uncertain", {"kept_apart": "identity_uncertain", "evidence": number, "playhead": [xa, xb]}
            return "veto", {"kept_apart": "measure_number_area_differs", "evidence": number, "playhead": [xa, xb]}
        return "same", {"playhead": [xa, xb], "cursor_only": cursor_only}

    def gated_join(a: Dict[str, Any], b: Dict[str, Any], path: str, *, need_same: bool) -> Tuple[bool, str, Dict[str, Any]]:
        """Run the identity gate for a join rule. ``need_same``: the rule has only pixel evidence
        (an uncertain identity keeps the pair apart); otherwise the rule has its own tracker
        evidence and only a veto keeps it apart. Pixel-only rules require whole-span sameness;
        both a veto and uncertainty bind every later rule, including joins through a group."""
        if guard.blocks(a["id"], b["id"]):
            identity_vetoes.append({"a": a["id"], "b": b["id"], "path": path, "verdict": "group_holds_identity_veto"})
            return False, "veto", {"kept_apart": "group_holds_identity_veto"}
        kind, rec = identity_verdict(a, b, identifier_veto_only=not need_same)
        if need_same and kind != "veto":
            # A late tracker boundary may put the new display at both endpoints.
            # Before unioning, every raw member of BOTH episodes must agree with
            # b's first window under the same strict identity gate. Uncertainty
            # keeps the split and binds subsequent rules. Continue after uncertainty
            # so a later definite difference is still recorded as the stronger evidence.
            for e in (a, b):
                for k in range(len(e["observation_ids"])):
                    if (e is a and k == len(a["observation_ids"]) - 1) or (e is b and k == 0):
                        continue  # already compared, or the reference itself
                    member_kind, member_rec = identity_verdict(e, b, where_a=k, where_b=0)
                    if member_kind == "veto" or (member_kind == "uncertain" and kind == "same"):
                        kind = member_kind
                        rec = {**member_rec, "observations": [e["observation_ids"][k], b["observation_ids"][0]]}
                    if kind == "veto":
                        break
                if kind == "veto":
                    break
        if kind == "veto" or (kind == "uncertain" and need_same):
            guard.veto(a["id"], b["id"])
            identity_vetoes.append({"a": a["id"], "b": b["id"], "path": path, "verdict": rec["kept_apart"],
                                    "evidence": rec.get("evidence"), "playhead": rec.get("playhead"),
                                    **({"observations": rec["observations"]} if "observations" in rec else {})})
            return False, kind, rec
        return guard.join(a["id"], b["id"]), kind, rec

    # 1. tracker continuity links: the same displayed content moved to another slot.
    #    Only verified (preview promotion / shared page translation), one-to-one links
    #    join displays; anything else stays separate and becomes a "looks similar" note.
    links = [lk for e in eps for lk in e.get("continuity_links", []) if lk.get("from") in ep_by and lk.get("to") in ep_by]
    n_from: Dict[str, int] = {}
    n_to: Dict[str, int] = {}
    for lk in links:
        n_from[lk["from"]] = n_from.get(lk["from"], 0) + 1
        n_to[lk["to"]] = n_to.get(lk["to"], 0) + 1
    similar_links: List[Dict[str, Any]] = [dict(lk) for e in eps for lk in e.get("continuity_candidates", [])
                                           if lk.get("from") in ep_by and lk.get("to") in ep_by]
    for lk in links:
        if lk.get("kind") not in ("preview_promotion", "page_translation"):
            similar_links.append({**lk, "rejected": "unverified_row_shift"})
            continue
        if n_from[lk["from"]] > 1 or n_to[lk["to"]] > 1:
            similar_links.append({**lk, "rejected": "competing_match"})
            continue
        ok, kind, _rec = gated_join(ep_by[lk["from"]], ep_by[lk["to"]], lk["kind"], need_same=False)
        if not ok:
            similar_links.append({**lk, "rejected": "identity_veto"})
            continue
        joins.append({"a": lk["from"], "b": lk["to"], "basis": lk["kind"],
                      **({"identity_uncertain": True} if kind == "uncertain" else {})})

    # 2. a playhead reset inside one continuous display of a slot
    by_slot: Dict[str, List[Dict[str, Any]]] = {}
    for e in sorted(eps, key=lambda x: x["t_start"]):
        by_slot.setdefault(e["slot_id"], []).append(e)
    for slot, seq in by_slot.items():
        for a, b in zip(seq, seq[1:]):
            if a.get("ended_by") == "playhead_reset" and b.get("started_by") == "playhead_reset" \
                    and 0.0 <= b["t_start"] - a["t_end"] <= RESET_JOIN_SEC:
                ok, kind, _rec = gated_join(a, b, "playhead_reset_same_display", need_same=False)
                if ok:
                    joins.append({"a": a["id"], "b": b["id"], "basis": "playhead_reset_same_display",
                                  **({"identity_uncertain": True} if kind == "uncertain" else {})})

    # 3. a row that stays the same while the rest of its page view stays on screen:
    #    the tracker may split it at a transient overlay or highlight; one display.
    # 2b. a false split inside one display: the tracker closes a display at "content_change"
    #     when its comparison drifts (staff-line rendering, compression) while the same written
    #     line stays on screen. Consecutive displays of one slot are one display when the split
    #     is at most one sample interval (+0.5 s), no other slot changes around it (no view
    #     transition), the playhead goes on (no reset) and the two sides show the same written
    #     display (every ink element beyond the staff lines, measure numbers included). Without
    #     playhead readings only that pixel sameness joins them (``joined_without_motion_evidence``).
    #     A join needs positive evidence of one written occurrence: besides that, the
    #     measure-number area (``measure_number_area_differs``) must agree strictly, and the
    #     only difference the join accepts is the playback cursor at the playhead readings
    #     (``differs_only_by_cursor``). Any notation or printed identifier that one side does
    #     not draw keeps two occurrences (audit F1: identical grooves numbered 13 and 17 with
    #     a continuing playhead are two written lines); no occurrence-level content family is
    #     made here (``split_joins.families`` stays empty). These identity comparisons use raw
    #     polarity-normalized pixels (audit G1: cleaning whitens gray >= CLEAN_INK_MAX, so gray
    #     measure numbers 13/17 vanished and the lines merged); where the paper is not clearly
    #     lighter than the ink threshold, or the number area is under an overlay, the identity
    #     is uncertain and the split is kept (``identity_uncertain``). Every raw member of both
    #     episodes must pass: matching boundary frames alone can both show a new display when
    #     the tracker closes the old episode late (Fzc 77-80 -> 81-84). Done before the short-display cut,
    #     so the parts of a split display are judged together.
    step = sample_interval(manifest)
    family_pairs: List[Dict[str, Any]] = []  # kept for the self-check schema; never filled (F1)
    split_checks: List[Dict[str, Any]] = []
    for slot, seq in by_slot.items():
        for a, b in zip(seq, seq[1:]):
            if a.get("ended_by") != "content_change" or b.get("started_by") != "content_change":
                continue
            if uf.find(a["id"]) == uf.find(b["id"]) or not (0.0 <= b["t_start"] - a["t_end"] <= step + SPLIT_JOIN_EXTRA_SEC):
                continue
            lo, hi = a["t_end"] - TRANSITION_PEER_SEC, b["t_start"] + TRANSITION_PEER_SEC
            peers = [o["id"] for o in eps if o["slot_id"] != slot and (
                (o.get("started_by") != "first_observation" and lo <= o["t_start"] <= hi)
                or (o.get("ended_by") not in (None, "end_of_source") and lo <= o["t_end"] <= hi))]
            rec: Dict[str, Any] = {"a": a["id"], "b": b["id"], "t": [round(a["t_end"], 4), round(b["t_start"], 4)]}
            if peers:
                split_checks.append({**rec, "kept_apart": "other_rows_change_with_it", "rows": peers})
                continue
            xa, xb = _playhead_end(a, "last"), _playhead_end(b, "first")
            motion = None if xa is None or xb is None else bool(xb >= xa - PLAYHEAD_CONTINUE_TOL)
            if motion is False:
                split_checks.append({**rec, "kept_apart": "playhead_went_back", "x": [xa, xb]})
                continue
            # identity is judged on raw polarity-normalized pixels (audit G1): cleaning whitens gray
            # ink, so a gray measure number would vanish on both sides and two lines would merge.
            # Positive evidence of one written occurrence is needed; a changed printed identifier
            # or any notation one side does not draw keeps two occurrences (never a family).
            ok, _kind, res = gated_join(a, b, "content_change_same_written_display", need_same=True)
            if not ok:
                split_checks.append({**rec, **{k: v for k, v in res.items() if k != "cursor_only"},
                                     **({} if "playhead" in res else {"playhead": [xa, xb]})})
                continue
            joins.append({"a": a["id"], "b": b["id"], "basis": "content_change_same_written_display",
                          "playhead": [xa, xb], "joined_without_motion_evidence": motion is None,
                          **({"differs_only_by_cursor": True} if res.get("cursor_only") else {})})

    for slot, seq in by_slot.items():
        long_seq = [e for e in seq if (e["t_end"] - e["t_start"]) >= min_occurrence_sec]
        for a, b in zip(long_seq, long_seq[1:]):
            if uf.find(a["id"]) == uf.find(b["id"]) or not (0.0 <= b["t_start"] - a["t_end"] <= RESET_JOIN_SEC + 0.5):
                continue
            steady = [o for o in eps if o["slot_id"] != slot and o["t_start"] < a["t_end"] and o["t_end"] > b["t_start"]
                      and (o["t_end"] - o["t_start"]) >= min_occurrence_sec]
            if not steady:
                continue
            try:
                # one display only when neither side holds an ink component the other does not draw
                wa, wb = ep_window(a, "last"), ep_window(b, "first")
                same = _strictly_same_image(wa, wb) and shown_by_kept_display([wa], [wb]).get("shown", False) \
                    and shown_by_kept_display([wb], [wa]).get("shown", False)
            except Exception as exc:  # pragma: no cover - defensive
                logger(f"steady-view comparison failed: {exc}")
                same = False
            if not same:
                continue
            # the cleaned windows lost gray ink: the same raw identity gate as every join (Codex H1)
            ok, _kind, _res = gated_join(a, b, "unchanged_page_view_same_row", need_same=True)
            if ok:
                joins.append({"a": a["id"], "b": b["id"], "basis": "unchanged_page_view_same_row",
                              "steady_rows": [o["id"] for o in steady]})

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for e in eps:
        groups.setdefault(uf.find(e["id"]), []).append(e)

    candidates = []
    for root, members in groups.items():
        members.sort(key=lambda x: x["t_start"])
        t0 = min(m["t_start"] for m in members)
        t1 = max(m["t_end"] for m in members)
        n_obs = sum(m["n_obs"] for m in members)
        shown = [m for m in members if m.get("role") != "preview"] or members
        # The occurrence's own slot/row: the shown (non-preview) member that lasted longest.
        main = max(shown, key=lambda m: (m["t_end"] - m["t_start"], m["n_obs"]))
        candidates.append({
            "root": root,
            "episodes": members,
            "t_start": t0,
            "t_end": t1,
            "order_t": _order_time(members),
            "n_obs": n_obs,
            "main": main,
            "duration": t1 - t0,
            "terminal": any(m.get("ended_by") == "end_of_source" for m in members),
            "first": any(m.get("started_by") == "first_observation" for m in members),
        })

    if ledger:
        fragment: Dict[str, Any] = {k: [] for k in ("observations", "displays", "items", "representations", "dispositions",
            "display_dispositions", "generated_origins", "occurrence_remaps", "observation_associations")}
        fragment["source_video"] = str(manifest.get("video_id") or manifest.get("source_video") or "manifest:unknown")
        fragment["version"] = rl.VERSION
        for c in candidates:
            did = f"occ:{c['root']}"
            fragment["displays"].append({"id": did, "occurrence_id": None,
                "observations": [o for o, _r in _member_observations(c["episodes"])], "shape": None,
                "raw_foreground_uninventoried_px": 0, "inventory_only": True})
            fragment["observation_associations"].extend({"obs_id": o, "stage": "occurrence", "display_id": did,
                "occurrence_id": None, "role": "member", "region_id": r} for o, r in _member_observations(c["episodes"]))

    occ = [c for c in candidates if c["duration"] >= min_occurrence_sec and c["n_obs"] >= 3]
    frags = [c for c in candidates if c not in occ]

    # 4. short displays: hidden only with positive evidence that a kept display shows
    #    their content; every other one is listed as an excluded (restorable) system.
    starts_ends = [(e["t_start"], e["slot_id"]) for e in eps] + [(e["t_end"], e["slot_id"]) for e in eps]

    def rep_window(c: Dict[str, Any]) -> Tuple:
        key = c["root"]
        if key not in window_cache:
            m = c["main"]
            k = len(m["observation_ids"]) // 2
            window_cache[key] = _window_of(obs_by, load_image, m["observation_ids"][k], m["region_ids"][k])
        return window_cache[key]

    rep_raw_cache: Dict[str, Tuple] = {}

    def rep_raw_window(c: Dict[str, Any]) -> Tuple:
        key = c["root"]
        if key not in rep_raw_cache:
            m = c["main"]
            k = len(m["observation_ids"]) // 2
            rep_raw_cache[key] = _raw_window_of(obs_by, load_image, m["observation_ids"][k], m["region_ids"][k])
        return rep_raw_cache[key]

    def raw_member_window(o: str, r: str) -> Tuple:
        return _raw_window_of(obs_by, load_image, o, r)

    def member_windows(c: Dict[str, Any], *, kept: bool = False) -> Iterable[Tuple]:
        # Do not retain full RGB crops for all neighbouring displays in memory.
        members = c["episodes"]
        if kept:
            # A preview not passed to this kept system's strip cannot recover ink.
            members = [e for e in members if e.get("role") != "preview"] or members
        return (raw_member_window(o, r) for o, r in _member_observations(members))

    def neighbour_displays(f: Dict[str, Any]) -> List[Tuple[Dict[str, Any], str]]:
        """Kept displays shown just before / after the short one at its screen position."""
        m = f["main"]
        g = float(m.get("staff_gap_px") or 1.0)
        out = []
        for c in occ:
            cm = c["main"]
            same_place = cm["slot_id"] == m["slot_id"] or abs(float(cm["staff_top_y"]) - float(m["staff_top_y"])) <= 1.5 * g
            if not same_place:
                continue
            if 0 <= f["t_start"] - c["t_end"] <= NEIGHBOUR_MATCH_SEC:
                out.append((c, "last"))
            elif 0 <= c["t_start"] - f["t_end"] <= NEIGHBOUR_MATCH_SEC:
                out.append((c, "first"))
            elif c["t_start"] <= f["t_start"] and c["t_end"] >= f["t_end"]:
                out.append((c, "mid"))
        return out

    fragments_out = []
    listed = []
    for f in frags:
        m = f["main"]
        slot = m["slot_id"]
        transition = any(m2.get("started_by") == "view_transition" or m2.get("ended_by") == "view_transition" for m2 in f["episodes"])
        if not transition:
            transition = bool([t for t, s_ in starts_ends if s_ != slot and f["t_start"] - TRANSITION_PEER_SEC <= t <= f["t_end"] + TRANSITION_PEER_SEC])
        reasons: List[str] = []
        evidence: Dict[str, Any] = {}
        represented_by: List[str] = []
        if f["first"] or f["terminal"]:
            evidence = {"shown": False, "reason": "first_or_terminal_display_is_always_listed"}
        else:
            try:
                # Hidden only when every raw member's non-staff foreground (any
                # size, gray included) is drawn by a kept display around it. A tracker "small change"
                # (page_diff ambiguous) is never sameness here.
                near = neighbour_displays(f)
                fw = rep_raw_window(f)
                samples = list(member_windows(f))
                evidence = shown_by_kept_display(samples, (win for c, _w in near for win in member_windows(c, kept=True)),
                                                 raw_evidence=True)
                evidence["basis"] = "all_raw_polarity_normalized_members"
                evidence["observations_checked"] = len(samples)
                if evidence.get("shown"):
                    same = [c for c, _w in near if _strictly_same_image(fw, rep_raw_window(c))
                            and shown_by_kept_display(samples, member_windows(c, kept=True), raw_evidence=True).get("shown")]
                    if same and evidence["reason"] != "no_content_beyond_staff_lines":
                        reasons.append("same_as_neighbour_display")
                        represented_by = [c["root"] for c in same]
                    else:
                        reasons.append(evidence["reason"])
                        represented_by = [c["root"] for c, _w in near]
            except Exception as exc:  # no pixels -> no evidence -> listed
                logger(f"short display comparison failed: {exc}")
                evidence = {"shown": False, "reason": f"comparison_failed: {exc}"}
        record = {"episode_ids": [e["id"] for e in f["episodes"]], "t_start": round(f["t_start"], 4), "t_end": round(f["t_end"], 4),
                  "slot_id": slot, "n_obs": f["n_obs"], "reasons": reasons or ["short_unique_display"],
                  "hidden": bool(reasons), "view_transition": bool(transition),
                  "first_display": f["first"], "terminal_display": f["terminal"],
                  "evidence": {k: v for k, v in evidence.items() if k != "shown"},
                  "_represented_roots": represented_by,
                  # decoding provenance: these observations can be decoded again from the source
                  "observations": [{"obs_id": o, "region_id": r, "t_sec": obs_by[o]["t_sec"] if o in obs_by else None}
                                   for e in f["episodes"] for o, r in zip(e["observation_ids"], e["region_ids"])]}
        fragments_out.append(record)
        if not reasons:
            f["hiding_unproven"] = not (f["first"] or f["terminal"])
            listed.append(f)

    # 4b. parts of one display split at content steps (system_tracking content_family) are one
    #     written system in different states: one is placed, the others are listed unchecked
    #     right after it as alternates ("other moments"), never as a second placed system.
    alt_of = content_step_alternates(occ, listed)
    # the placed state is ordered where its display was first shown (its earliest state), so a
    # later state stays above the rows of its page view that appeared with the earlier one
    for c in occ + listed:
        p = alt_of.get(c["root"])
        if p is None:
            continue
        prim = next(x for x in occ + listed if x["root"] == p)
        prim["order_t"] = min(prim["order_t"], c["order_t"])

    # 5. display order: rows that appear together (a page view) top to bottom
    placed = [(c, True) for c in occ if c["root"] not in alt_of] + [(c, False) for c in listed if c["root"] not in alt_of]
    placed.sort(key=lambda ci: (ci[0]["order_t"], ci[0]["main"]["staff_top_y"]))
    ordered: List[Tuple[Dict[str, Any], bool]] = []
    cluster: List[Tuple[Dict[str, Any], bool]] = []
    for item in placed:
        if cluster and item[0]["order_t"] - cluster[0][0]["order_t"] > VIEW_CLUSTER_SEC:
            ordered.extend(sorted(cluster, key=lambda ci: ci[0]["main"]["staff_top_y"]))
            cluster = []
        cluster.append(item)
    ordered.extend(sorted(cluster, key=lambda ci: ci[0]["main"]["staff_top_y"]))
    alt_cands = sorted([c for c in occ + listed if c["root"] in alt_of], key=lambda c: c["t_start"])
    with_alts: List[Tuple[Dict[str, Any], bool]] = []
    for c, inc in ordered:
        with_alts.append((c, inc))
        with_alts.extend((a, False) for a in alt_cands if alt_of[a["root"]] == c["root"])

    systems = []
    root_to_id: Dict[str, str] = {}
    n_main = 0
    n_alt: Dict[str, int] = {}
    for c, included in with_alts:
        members = c["episodes"]
        shown = [m for m in members if m.get("role") != "preview"] or members
        observations = [{"obs_id": o, "region_id": r, "episode_id": m["id"]}
                        for m in (members if c.get("hiding_unproven") else shown)
                        for o, r in zip(m["observation_ids"], m["region_ids"])]
        layouts = sorted({m.get("layout") or "unknown" for m in members})
        primary = alt_of.get(c["root"])
        if primary is None:
            n_main += 1
            sid, index = f"sys-{n_main:03d}", n_main
        else:
            pid = root_to_id[primary]
            n_alt[pid] = n_alt.get(pid, 0) + 1
            sid, index = f"{pid}-alt{n_alt[pid]}", int(pid.split("-")[1])
        root_to_id[c["root"]] = sid
        issues = list(CONTENT_STEP_ALTERNATE_ISSUES) if primary is not None else ([] if included else ["SHORT_DISPLAY"])
        if c.get("hiding_unproven"):
            issues.append("UNCERTAIN_MARK_KEPT")
        systems.append({
            "id": sid,
            "occurrence_root": c["root"],
            "ledger_observations": [{"obs_id": o, "region_id": r} for o, r in _member_observations(members)],
            "index": index,
            "included": included,
            "t_start": round(c["t_start"], 4),
            "t_end": round(c["t_end"], 4),
            "order_t": round(c["order_t"], 4),
            "slot_id": c["main"]["slot_id"],
            "staff_top_y_crop": c["main"]["staff_top_y"],
            "staff_gap_px": c["main"]["staff_gap_px"],
            "episode_ids": [m["id"] for m in members],
            "main_episode_id": c["main"]["id"],
            "observations": observations,
            "layout": layouts[0] if len(layouts) == 1 else "mixed",
            "first_display": c["first"],
            "terminal_display": c["terminal"],
            "issues": issues,
            **({"alternate_of": root_to_id[primary], "alternate_kind": "content_step_state",
                "content_family": _family_of(c)} if primary is not None else {}),
        })
    sys_of_ep = {e_id: s_["id"] for s_ in systems for e_id in s_["episode_ids"]}
    continuity_suggestions = []
    for lk in similar_links:
        a_sys, b_sys = sys_of_ep.get(lk["from"]), sys_of_ep.get(lk["to"])
        if a_sys and b_sys and a_sys != b_sys and not any(x["system_id"] == b_sys and x["of_system_id"] == a_sys for x in continuity_suggestions):
            continuity_suggestions.append({"system_id": b_sys, "of_system_id": a_sys, "basis": f"continuity_{lk['rejected']}",
                                           "reason": "looks_similar"})
    for rec in fragments_out:
        rec["represented_by"] = [root_to_id[r] for r in rec.pop("_represented_roots") if r in root_to_id]
    if ledger:
        sys_by = {s["id"]: s for s in systems}
        fragment_by = {eid: rec for rec in fragments_out for eid in rec["episode_ids"]}
        for c, display in zip(candidates, fragment["displays"]):
            did, sid = display["id"], root_to_id.get(c["root"])
            system = sys_by.get(sid)
            frag = fragment_by.get(c["main"]["id"])
            exclusion = None if system and system["included"] else (
                "content_step_alternates" if system and system.get("alternate_of") else
                "short_listed_excluded" if system else (frag["reasons"][0] if frag else "excluded"))
            fragment["occurrence_remaps"].append({"root_key": c["root"], "display_id": did,
                "final_system_id": sid, "final_occurrence_id": sid, "included": bool(system and system["included"]),
                "exclusion": exclusion})
            display["occurrence_id"] = sid
            if system:
                if not system["included"]:
                    fragment["display_dispositions"].append({"kind": "display_unresolved", "terminal": "unresolved",
                        "display_id": did, "reason": "excluded_without_equivalence"})
                continue
            raw_members, origins, descriptors = [], [], []
            tolerance = max(1, int(round(COVER_DILATE_GAPS * float(c["main"]["staff_gap_px"]))))
            for o, r in _member_observations(c["episodes"]):
                image = load_image(obs_by[o])
                norm, inverted = system_detect.normalize_polarity(image)
                region = _region(obs_by[o], r)
                gap = float(region["staff_gap_px"])
                win = region_window(norm, region)
                origin = [0, int(round(float(region["staff_y"][0]) - WINDOW_ABOVE_GAPS * gap))]
                origins.append(origin)
                crop_box = [0, origin[1], win.shape[1], origin[1] + win.shape[0]]
                exact = not inverted and crop_box[1] >= max(0, region["bbox"][1]) and crop_box[3] <= min(image.shape[0], region["bbox"][3])
                descriptors.append((o, r, win.shape[:2], crop_box, exact))
            del image, norm, win
            shape = tuple(int(v) for v in np.max([d[2] for d in descriptors], axis=0))
            cached = {"key": None, "image": None}

            def canvas(o, r):
                if cached["key"] != (o, r):
                    cached["image"] = None
                    cached["key"] = (o, r)
                    win = raw_member_window(o, r)[0]
                    if win.shape[:2] != shape:
                        padded = np.full((*shape, 3), 255, np.uint8)
                        padded[:win.shape[0], :win.shape[1]] = win
                        win = padded
                    cached["image"] = win
                return cached["image"]

            for (o, r, member_shape, crop_box, exact), origin in zip(descriptors, origins):
                def usable(member_shape=member_shape):
                    if member_shape == shape:
                        return True
                    mask = np.zeros(shape, bool)
                    mask[:member_shape[0], :member_shape[1]] = True
                    return mask

                member = {"id": o, "timestamp": float(obs_by[o]["t_sec"]), "image": lambda o=o, r=r: canvas(o, r),
                    "roi_origin": origin, "registration_shift": [0, 0], "registration_uncertainty": tolerance,
                    "source_to_native": obs_by[o].get("source_to_crop", manifest.get("source_to_crop")),
                    "usable": usable, "occluded": lambda o=o, r=r: cv2.cvtColor(canvas(o, r), cv2.COLOR_BGR2HSV)[..., 1] > 80,
                    "polarity": "light"}
                if exact and member_shape == shape:
                    member["frame_ref"] = {"observation_id": o, "crop_box": crop_box}
                raw_members.append(member)
            raw = rl.record_obligations(source_video=fragment["source_video"], display_id=did,
                occurrence_id=did, members=raw_members, evidence_dir=evidence_dir)
            if raw.get("evidence_root") is not None:
                fragment["evidence_root"] = raw["evidence_root"]
            display.update(raw["displays"][0])
            display.pop("inventory_only", None)
            fragment["items"].extend(raw["items"])
            equivalent = None
            if frag and frag["hidden"] and len({tuple(p) for p in origins}) == 1:
                for kept_id in frag["represented_by"]:
                    kept = sys_by[kept_id]
                    kc = next(k for k in candidates if k["root"] == kept["occurrence_root"])
                    proof = shown_by_kept_display(list(member_windows(c)), member_windows(kc, kept=True), raw_evidence=True)
                    if not proof.get("shown"):
                        continue
                    origin = _ledger_strip_origin(kept, obs_by, load_image)
                    kr = _region(obs_by[kept["observations"][0]["obs_id"]], kept["observations"][0]["region_id"])
                    ky = int(round(float(kr["staff_y"][0]) - WINDOW_ABOVE_GAPS * float(kr["staff_gap_px"])))
                    # Coverage compares staff-anchored windows without warping.
                    if origin is not None and all(int(round(float(_region(obs_by[m["obs_id"]], m["region_id"])["staff_y"][0]) -
                        WINDOW_ABOVE_GAPS * float(_region(obs_by[m["obs_id"]], m["region_id"])["staff_gap_px"]))) == ky for m in kept["observations"]):
                        equivalent = {"kind": "display_equivalent", "terminal": "equivalent_observation",
                            "display_id": did, "retained_display_id": f"strip:{kept_id}",
                            "equivalence_map": [[1, 0, -origin[0]], [0, 1, ky - origin[1]], [0, 0, 1]],
                            "registration_uncertainty": tolerance,
                            "evidence": {"method": "shown_by_kept_display", **frag["evidence"], **proof}}
                        break
            fragment["display_dispositions"].append(equivalent or {"kind": "display_unresolved", "terminal": "unresolved",
                "display_id": did, "reason": "equivalence_map_unavailable" if frag and frag["hidden"] else "excluded_without_equivalence"})
            del raw_members
    hidden = [r for r in fragments_out if r["hidden"]]
    exclusions = {
        "short_listed_excluded": [s_["id"] for s_ in systems if not s_["included"] and not s_.get("alternate_of")],
        "content_step_alternates": [s_["id"] for s_ in systems if s_.get("alternate_of")],
        "hidden": len(hidden),
        "hidden_by_reason": {k: sum(1 for r in hidden if k in r["reasons"]) for k in sorted({x for r in hidden for x in r["reasons"]})},
        "rule": "hidden only when all raw member observations' non-staff foreground (including gray; colored pixels masked) is drawn by a kept display "
                "around it, or there is no non-staff ink at all; first/terminal never hidden",
    }
    self_checks = _self_checks(with_alts, systems, root_to_id, eps, fragments_out, excluded, all_eps, step,
                               ep_raw_window, rep_raw_window, logger)
    self_checks["split_joins"] = {"joined": [j for j in joins if j["basis"] == "content_change_same_written_display"],
                                  "families": family_pairs, "kept_apart": split_checks}
    exclusions["self_checks"] = {k: v for k, v in self_checks.items() if k != "split_joins"}
    logger(f"self-checks: adjacent_duplicate {self_checks['adjacent_duplicate']}, score_time_uncovered "
           f"{self_checks['score_time_uncovered_sec']} s, revisits {self_checks['revisit_count']}")
    logger(f"occurrences: {sum(s['included'] for s in systems)} placed, {len(listed)} short listed (excluded, restorable), "
           f"{len(hidden)} short displays hidden {exclusions['hidden_by_reason']}, joins {len(joins)}")
    return {
        "schema_version": 1,
        "kind": "reflow_occurrences",
        "version": OCCURRENCES_VERSION,
        "order_policy": "video_order",
        "rules": {"min_occurrence_sec": min_occurrence_sec, "view_cluster_sec": VIEW_CLUSTER_SEC, "reset_join_sec": RESET_JOIN_SEC},
        "systems": systems,
        **({"ledger": fragment} if ledger else {}),
        "fragments": fragments_out,
        "exclusions": exclusions,
        "joins": joins,
        "identity_vetoes": identity_vetoes,
        "continuity_suggestions": continuity_suggestions,
        "self_checks": self_checks,
        "unsupported_intervals": [{"start": iv["start"], "end": iv["end"], "kind": iv["kind"], "issue": iv.get("issue")} for iv in unsupported],
        "layout_intervals": tracking.get("layout_intervals", []),
    }


def _merge_intervals(iv: List[Tuple[float, float]], tol: float = 0.0) -> List[List[float]]:
    out: List[List[float]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + tol + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _self_checks(with_alts, systems, root_to_id, eps, fragments, excluded, all_eps, step, ep_window, rep_window,
                 logger) -> Dict[str, Any]:
    """GT-free checks of the placed systems (recorded, never applied):

    * ``adjacent_duplicate``: two placed systems one after the other at the same screen place,
      shown back to back (at most one sample interval + 0.5 s apart) with no evidence of leaving
      the line between them (no playhead reset or jump back, no view transition) whose written
      displays are the same. Should be 0: one written line placed twice.
    * ``score_time_uncovered_sec`` / ``score_time_uncovered``: per screen place, the time a
      display is on screen that no placed system accounts for (not placed, not another state of
      a placed system, not independently proved covered by a kept display, not a jump-view strip). Intervals
      made only of short displays listed at a view transition (page curl, fade) are counted
      apart (``score_time_uncovered_at_view_transitions_sec``).
    * ``revisit_count``: placed systems whose written display is the same as an earlier placed
      one at the same screen place with other systems shown in between (a repeat / D.S.)."""
    placed = [(c, sys_) for (c, _inc), sys_ in zip(with_alts, systems) if sys_["included"] and not sys_.get("alternate_of")]
    pairs_used = 0
    adjacent: List[Dict[str, Any]] = []
    adjacent_left: List[Dict[str, Any]] = []
    for (p, ps), (q, qs) in zip(placed, placed[1:]):
        if p["main"]["slot_id"] != q["main"]["slot_id"] or not (0.0 <= q["t_start"] - p["t_end"] <= step + SPLIT_JOIN_EXTRA_SEC):
            continue
        pe = max(p["episodes"], key=lambda x: x["t_end"])
        qe = min(q["episodes"], key=lambda x: x["t_start"])
        try:
            pairs_used += 1
            same, _info = same_written_display(ep_window(pe, "last"), ep_window(qe, "first"))
        except Exception as exc:  # pragma: no cover - defensive
            logger(f"adjacent self-check failed: {exc}")
            continue
        if not same:
            continue
        xa, xb = _playhead_end(pe, "last"), _playhead_end(qe, "first")
        left = qe.get("started_by") in ("playhead_reset", "view_transition") or \
            (xa is not None and xb is not None and xb < xa - PLAYHEAD_CONTINUE_TOL)
        entry = {"system_id": qs["id"], "after_system_id": ps["id"], "t": [round(p["t_end"], 4), round(q["t_start"], 4)],
                 "playhead": [xa, xb], "boundary": qe.get("started_by")}
        (adjacent_left if left else adjacent).append(entry)

    # score time no placed system accounts for, per screen place
    covered: set = set(excluded)
    for (c, _inc), sys_ in zip(with_alts, systems):
        if sys_["included"] or (sys_.get("alternate_of") and any(x["id"] == sys_["alternate_of"] and x["included"] for x in systems)):
            covered.update(e["id"] for e in c["episodes"])
    at_transition: set = set()
    hidden_checks = []
    ep_by = {e["id"]: e for e in eps}
    placed_by_id = {s["id"]: c for c, s in placed}
    for f in fragments:
        if f.get("hidden"):
            # Re-read raw source evidence; neither the hidden bit nor the saved
            # coverage verdict is proof. Only actually included neighbours qualify.
            proof = {"shown": False, "reason": "no_raw_evidence"}
            try:
                members = [ep_by[i] for i in f["episode_ids"]]
                neighbours = []
                for sid in f.get("represented_by", []):
                    c = placed_by_id.get(sid)
                    if c is None:
                        continue
                    g = float(c["main"].get("staff_gap_px") or 1.0)
                    same_place = c["main"]["slot_id"] == f["slot_id"] or any(
                        abs(float(e["staff_top_y"]) - float(c["main"]["staff_top_y"])) <= 1.5 * g for e in members)
                    near = (0 <= f["t_start"] - c["t_end"] <= NEIGHBOUR_MATCH_SEC or
                            0 <= c["t_start"] - f["t_end"] <= NEIGHBOUR_MATCH_SEC or
                            c["t_start"] <= f["t_start"] <= f["t_end"] <= c["t_end"])
                    if same_place and near:
                        # Only members used by the included destination strip can
                        # discharge obligations; discarded previews cannot.
                        members_used = [e for e in c["episodes"] if e.get("role") != "preview"] or c["episodes"]
                        neighbours.extend(members_used)
                fw = [ep_window(e, k) for e in members for k in range(len(e["observation_ids"]))]
                nw = (ep_window(e, k) for e in neighbours for k in range(len(e["observation_ids"])))
                proof = shown_by_kept_display(fw, nw, raw_evidence=True)
            except Exception as exc:
                logger(f"hidden coverage self-check failed: {exc}")
                proof = {"shown": False, "reason": f"comparison_failed: {exc}"}
            hidden_checks.append({"episode_ids": f["episode_ids"], "covered": bool(proof.get("shown")),
                                  "evidence": {k: v for k, v in proof.items() if k != "shown"}})
            if proof.get("shown"):
                covered.update(f["episode_ids"])
        elif f.get("view_transition"):
            at_transition.update(f["episode_ids"])
    unsupported = [e["id"] for e in all_eps if e.get("layout") == "horizontal_scroll" and e["id"] not in excluded]
    sys_of_ep = {e_id: s_["id"] for s_ in systems for e_id in s_["episode_ids"]}
    per_slot: Dict[str, List[Tuple[float, float]]] = {}
    who: Dict[str, List[Tuple[float, float, str]]] = {}
    for e in eps:
        if e["id"] in covered:
            continue
        per_slot.setdefault(e["slot_id"], []).append((float(e["t_start"]), float(e["t_end"])))
        who.setdefault(e["slot_id"], []).append((float(e["t_start"]), float(e["t_end"]), e["id"]))
    uncovered = []
    total = 0.0
    total_transition = 0.0
    for slot, iv in sorted(per_slot.items()):
        for a, b in _merge_intervals(iv, step):
            ids = [i for t0, t1, i in who[slot] if t0 >= a - 1e-6 and t1 <= b + 1e-6]
            # a display's last observation is one sample before it leaves the screen
            dur = (b - a) + step
            # short displays listed at a view transition (page curl, cross-fade) are reported apart
            transition = bool(ids) and all(i in at_transition for i in ids)
            if transition:
                total_transition += dur
            else:
                total += dur
            uncovered.append({"slot_id": slot, "start": round(a, 4), "end": round(b, 4), "seconds": round(dur, 3),
                              "at_view_transition": transition, "episode_ids": ids,
                              "listed_system_ids": sorted({sys_of_ep[i] for i in ids if i in sys_of_ep})})

    # revisits: the same written display placed again after other systems were shown
    revisits: List[Dict[str, Any]] = []
    incomplete = False
    for j, (q, qs) in enumerate(placed):
        gq = float(q["main"].get("staff_gap_px") or 1.0)
        for i in range(j - 1, -1, -1):
            p, ps = placed[i]
            if i == j - 1:
                continue  # back to back: the adjacent check above
            if p["main"]["slot_id"] != q["main"]["slot_id"] and abs(float(p["main"]["staff_top_y"]) - float(q["main"]["staff_top_y"])) > 1.5 * gq:
                continue
            if abs(float(p["main"].get("staff_gap_px") or 1.0) - gq) > DUPLICATE_GAP_TOL * gq:
                continue
            if pairs_used >= SELF_CHECK_BUDGET_PAIRS:
                incomplete = True
                break
            pairs_used += 1
            try:
                same = same_written_display(rep_window(p), rep_window(q))[0]
            except Exception as exc:  # pragma: no cover - defensive
                logger(f"revisit self-check failed: {exc}")
                continue
            if same:
                revisits.append({"system_id": qs["id"], "of_system_id": ps["id"]})
                break
        if incomplete:
            break
    return {
        "adjacent_duplicate": len(adjacent),
        "adjacent_duplicates": adjacent,
        "adjacent_same_after_leaving": adjacent_left,
        "score_time_uncovered_sec": round(total, 3),
        "score_time_uncovered_at_view_transitions_sec": round(total_transition, 3),
        "score_time_uncovered": uncovered,
        "hidden_fragment_coverage": hidden_checks,
        "hidden_fragment_uncovered": sum(not p["covered"] for p in hidden_checks),
        "unsupported_episode_ids": unsupported,
        "revisit_count": len(revisits),
        "revisits": revisits,
        "comparisons": pairs_used,
        "incomplete": incomplete,
    }


def _same_whole_display(a: np.ndarray, b: np.ndarray, gap: float, *, ink_threshold: int = 160,
                        min_area_gaps: float = 0.15, min_area_px: int = 10) -> Tuple[bool, Dict[str, Any]]:
    """Two cleaned strips show the same whole display: every ink element -
    notation, measure numbers, lyrics, section boxes, text - is present in both.

    The strips are registered (phase correlation on ink); then any connected
    piece of ink in one strip that the other does not draw (1 px tolerance) and
    that is larger than ~0.15 staff gap squared (a digit, a notehead) makes them
    different. Strips whose sizes differ by more than a few pixels differ."""
    if abs(a.shape[0] - b.shape[0]) > max(4, 0.06 * max(a.shape[0], b.shape[0])) or \
            abs(a.shape[1] - b.shape[1]) > max(4, 0.02 * max(a.shape[1], b.shape[1])):
        return False, {"reason": "size_differs"}
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    ink = []
    for im in (a, b):
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        g = cv2.copyMakeBorder(g, 0, h - g.shape[0], 0, w - g.shape[1], cv2.BORDER_CONSTANT, value=255)
        ink.append((g < ink_threshold).astype(np.uint8))
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), _resp = cv2.phaseCorrelate(ink[0].astype(np.float32), ink[1].astype(np.float32), win)
    if not np.isfinite([dx, dy]).all() or abs(dx) > 0.5 * gap * 4 or abs(dy) > gap:
        return False, {"reason": "unregistered", "shift": [float(dx), float(dy)]}
    m = np.float32([[1, 0, -round(dx)], [0, 1, -round(dy)]])
    b_reg = cv2.warpAffine(ink[1], m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    k = np.ones((3, 3), np.uint8)
    only_a = ink[0] & (1 - cv2.dilate(b_reg, k))
    only_b = b_reg & (1 - cv2.dilate(ink[0], k))
    residue = only_a | only_b
    # nearby residue fragments (the strokes of one different digit) count together
    r = max(2, int(round(0.25 * gap)))
    n, lab = cv2.connectedComponents(cv2.dilate(residue, np.ones((2 * r + 1, 2 * r + 1), np.uint8)), connectivity=8)
    sizes = np.bincount(lab[residue > 0].ravel(), minlength=n)[1:] if n > 1 else np.zeros(0, int)
    min_area = max(int(min_area_px), int(round(min_area_gaps * gap * gap)))
    big = [int(v) for v in sizes if v >= min_area]
    big_ids = [i + 1 for i, v in enumerate(sizes) if v >= min_area]
    in_big = np.isin(lab, big_ids) if big_ids else np.zeros(lab.shape, bool)
    ink_px = int(max(ink[0].sum(), b_reg.sum(), 1))
    pieces = []
    for i in big_ids[:12]:
        sel = (lab == i) & (residue > 0)
        ys, xs = np.nonzero(sel)
        pieces.append({"box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                       "only_a_px": int((sel & (only_a > 0)).sum()), "only_b_px": int((sel & (only_b > 0)).sum())})
    return not big, {"pieces": pieces, "pieces_truncated": len(big_ids) > 12,
                     "reason": "same" if not big else "content_differs", "differing_pieces": len(big),
                     "largest_piece_px": max(big) if big else 0, "shift": [round(float(dx), 2), round(float(dy), 2)],
                     "only_a_px": int((only_a.astype(bool) & in_big).sum()), "only_b_px": int((only_b.astype(bool) & in_big).sum()),
                     "residue_share": round(float(sum(big)) / ink_px, 4)}


def collapse_replay_blocks(
    systems: List[Dict[str, Any]],
    strip_of: Dict[str, str],
    *,
    logger: Callable[[str], None],
    min_block: int = 3,
    budget_pairs: int = 4000,
    label_by: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Find maximal, distinctive temporal replay blocks in the placed order.

    Each replay line must match exactly one earlier included page system; its
    counterpart must match no other line in either block. Same-view rows and
    overlapping display intervals cannot establish a replay. A label acquired
    outside the strip keeps the replay block for review. Jump views, excluded
    systems, alternates and missing strips break runs. The input is not mutated.
    A budget stop discards the current candidate until its maximal length and
    all distinctiveness checks have been established. Strips decode on demand.
    """
    if min_block < 3:
        raise ValueError("min_block must be at least three")
    started = time.perf_counter()
    label_by = label_by or {}
    eligible = {i for i, s in enumerate(systems)
                if s.get("included", True) and not s.get("alternate_of")
                and s.get("layout") != "jump_view"}
    # Use the same first-row-anchored clustering as suggest_similar_strips,
    # including other rows in the input so page-view identity stays consistent.
    view_of: Dict[int, int] = {}
    first_t: Optional[float] = None
    view = -1
    for i in sorted(range(len(systems)), key=lambda i: (
            systems[i]["order_t"], systems[i].get("staff_top_y_crop", 0))):
        t = float(systems[i]["order_t"])
        if first_t is None or abs(t - first_t) > VIEW_CLUSTER_SEC:
            view += 1
            first_t = t
        view_of[i] = view
    imgs: Dict[int, Optional[np.ndarray]] = {}
    cache: Dict[Tuple[int, int], bool] = {}
    pairs = 0
    out: List[Dict[str, Any]] = []

    class BudgetExhausted(Exception):
        pass

    def image(i: int) -> Optional[np.ndarray]:
        if i not in imgs:
            path = strip_of.get(systems[i]["id"])
            imgs[i] = cv2.imread(str(path)) if path else None
        return imgs[i]

    def match(i: int, j: int) -> bool:
        nonlocal pairs
        i, j = sorted((i, j))
        if i not in eligible or j not in eligible:
            return False
        key = (i, j)
        if key not in cache:
            if pairs >= budget_pairs:
                raise BudgetExhausted
            a, b = image(i), image(j)
            if a is None or b is None:
                cache[key] = False
            else:
                pairs += 1
                gap = float(systems[i].get("staff_gap_px") or 12.0)
                cache[key] = _same_whole_display(
                    a, b, gap, min_area_px=4, min_area_gaps=0.04)[0]
        return cache[key]

    def distinctive(i: int, j: int, length: int) -> bool:
        a_block = range(i, i + length)
        b_block = range(j, j + length)
        for a, b in zip(a_block, b_block):
            # Include ALL earlier eligible lines, even rows in the same view
            # and lines returned by an earlier block in this invocation.
            if any(p != a and match(p, b) for p in range(b)):
                return False
            # Also check future lines within both blocks: image matching is
            # tolerant and cannot be assumed to be transitive.
            if any(p not in (a, b) and match(a, p)
                   for p in (*a_block, *b_block)):
                return False
        return True

    blocks = 0
    j = 0
    try:
        while j + min_block <= len(systems):
            if j not in eligible:
                j += 1
                continue
            candidates = []
            for i in range(j):
                length = 0
                while i + length < j and j + length < len(systems):
                    a, b = i + length, j + length
                    if view_of[a] == view_of[b] or not match(a, b):
                        break
                    length += 1
                if length >= min_block:
                    candidates.append((i, length))
            longest = max((length for _i, length in candidates), default=0)
            starts = [i for i, length in candidates if length == longest]
            if len(starts) != 1:
                j += 1
                continue
            i = starts[0]
            a_end = systems[i + longest - 1].get("t_end")
            b_start = systems[j].get("t_start")
            if (a_end is None or b_start is None or not float(b_start) >= float(a_end)
                    or any(systems[b]["id"] in label_by for b in range(j, j + longest))
                    or not distinctive(i, j, longest)):
                j += 1
                continue
            block = [systems[j]["id"], systems[j + longest - 1]["id"]]
            block_of = [systems[i]["id"], systems[i + longest - 1]["id"]]
            out.extend({"system_id": systems[j + t]["id"], "replay_of": systems[i + t]["id"],
                        "block": list(block), "block_of": list(block_of)} for t in range(longest))
            blocks += 1
            j += longest  # one replay system belongs to at most one block
    except BudgetExhausted:
        logger("replay collapse: comparison budget exhausted; keeping only fully established blocks")
    logger(f"replay collapse: {blocks} blocks, {len(out)} systems "
           f"({pairs} comparisons, {time.perf_counter() - started:.3f}s)")
    return out


def suggest_similar_strips(
    systems: List[Dict[str, Any]],
    strip_of: Dict[str, str],
    *,
    logger: Callable[[str], None] = lambda _m: None,
    budget_pairs: int = 4000,
    should_stop: Callable[[], bool] = lambda: False,
) -> List[Dict[str, Any]]:
    """"Looks similar" suggestions from the cleaned strips (appearance only; never applied).

    A later system is suggested as looking like an earlier one only when their
    whole cleaned displays match - notation and every text element (measure
    numbers, lyrics, section boxes, tempo) - with a strict page_diff ``same``
    verdict. Systems of the same page view are not compared with each other; a
    multi-row page view matches only as a whole view. Identical written-out
    passages still look alike; the review shows them side by side.
    """
    imgs: Dict[str, np.ndarray] = {}
    for s in systems:
        if should_stop():
            logger("similar-system suggestions: stopped while loading strips (budget or cancel)")
            return []
        path = strip_of.get(s["id"])
        img = cv2.imread(str(path)) if path else None
        if img is not None:
            imgs[s["id"]] = img
    view_of: Dict[str, int] = {}
    views: List[List[str]] = []
    first_t: List[float] = []
    for s in sorted(systems, key=lambda x: (x["order_t"], x.get("staff_top_y_crop", 0))):
        if views and abs(s["order_t"] - first_t[-1]) <= VIEW_CLUSTER_SEC:
            views[-1].append(s["id"])
        else:
            views.append([s["id"]])
            first_t.append(s["order_t"])
        view_of[s["id"]] = len(views) - 1
    cache: Dict[Tuple[str, str], bool] = {}
    by_id = {s["id"]: s for s in systems}
    pairs = 0

    def match(a: str, b: str) -> bool:
        nonlocal pairs
        if (a, b) not in cache:
            pairs += 1
            gap = float(by_id[a].get("staff_gap_px") or 12.0)
            cache[(a, b)] = _same_whole_display(imgs[a], imgs[b], gap)[0]
        return cache[(a, b)]

    out = []
    for j, b in enumerate(systems):
        if b["id"] not in imgs:
            continue
        for a in systems[:j]:
            if a["id"] not in imgs or view_of[a["id"]] == view_of[b["id"]]:
                continue
            if pairs > budget_pairs or should_stop():
                logger("similar-system suggestions: stopped early (budget or cancel)")
                return out
            if not match(a["id"], b["id"]):
                continue
            va, vb = views[view_of[a["id"]]], views[view_of[b["id"]]]
            if len(vb) > 1:
                if len(va) != len(vb) or va.index(a["id"]) != vb.index(b["id"]):
                    continue
                if not all(x in imgs and y in imgs and match(x, y) for x, y in zip(va, vb)):
                    continue
            basis = "whole_display_strip" if len(vb) == 1 else "whole_page_view_strips"
            out.append({"system_id": b["id"], "of_system_id": a["id"], "basis": basis, "reason": "looks_similar"})
            break
    logger(f"similar-system suggestions: {len(out)} ({pairs} comparisons)")
    return out


def suggest_duplicates(
    systems: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    load_image: ImageLoader,
    *,
    logger: Callable[[str], None] = lambda _m: None,
    budget_pairs: int = 4000,
    should_stop: Callable[[], bool] = lambda: False,
) -> List[Dict[str, Any]]:
    """Likely repeats: a later system whose full display window matches an
    earlier one (appearance only; a suggestion, never applied automatically).

    Each later system points at the earliest matching earlier system. Systems of
    the same page view are not compared with each other.
    """
    obs_by = _obs_index(manifest)
    wins: Dict[str, Tuple] = {}
    for s in systems:
        if should_stop():
            logger("duplicate suggestions: stopped while loading windows (budget or cancel)")
            return []
        if not s.get("observations"):
            continue
        mid = s["observations"][len(s["observations"]) // 2]
        try:
            wins[s["id"]] = _window_of(obs_by, load_image, mid["obs_id"], mid["region_id"])
        except Exception as exc:  # pragma: no cover - defensive
            logger(f"duplicate window for {s['id']} failed: {exc}")
    # page views: systems shown together (same display-order cluster)
    view_of: Dict[str, int] = {}
    views: List[List[str]] = []
    for s in sorted(systems, key=lambda x: (x["order_t"], x.get("staff_top_y_crop", 0))):
        if views and abs(s["order_t"] - next(x for x in systems if x["id"] == views[-1][0])["order_t"]) <= VIEW_CLUSTER_SEC:
            views[-1].append(s["id"])
        else:
            views.append([s["id"]])
        view_of[s["id"]] = len(views) - 1
    out = []
    pairs = 0
    matches: Dict[Tuple[str, str], bool] = {}

    def match(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        nonlocal pairs
        key = (a["id"], b["id"])
        if key not in matches:
            ra, rb = wins[a["id"]][3], wins[b["id"]][3]
            ga = float(ra["staff_gap_px"])
            if abs(ra["staff_x"][0] - rb["staff_x"][0]) > 2 * ga or abs(ra["staff_x"][1] - rb["staff_x"][1]) > 2 * ga:
                matches[key] = False
            else:
                pairs += 1
                matches[key] = _same_display_content(wins[a["id"]], wins[b["id"]])
        return matches[key]

    by_id = {s["id"]: s for s in systems}
    for j, b in enumerate(systems):
        if b["id"] not in wins:
            continue
        for a in systems[:j]:
            if a["id"] not in wins or view_of[a["id"]] == view_of[b["id"]]:
                continue
            if pairs > budget_pairs or should_stop():
                logger("similar-system suggestions: stopped early (budget or cancel)")
                return out
            if not match(a, b):
                continue
            # A multi-row page view repeats only as a whole view: every row of b's view
            # must match the row at the same position of a's view.
            va, vb = views[view_of[a["id"]]], views[view_of[b["id"]]]
            if len(vb) > 1:
                if len(va) != len(vb) or va.index(a["id"]) != vb.index(b["id"]):
                    continue
                if not all(x in wins and y in wins and match(by_id[x], by_id[y]) for x, y in zip(va, vb)):
                    continue
            basis = "full_window_appearance" if len(vb) == 1 else "whole_page_view_appearance"
            out.append({"system_id": b["id"], "of_system_id": a["id"], "basis": basis, "reason": "repeat"})
            break
    logger(f"duplicate suggestions: {len(out)} ({pairs} comparisons)")
    return out
