"""Measure-boundary candidates, masks, crossing evidence and tri-state classification.

MEASURE_BRIEF milestone 1. Not on the export path: nothing here changes what a job or
an export produces.

A boundary is an exact proposed seam in a cleaned strip, not only a barline centre.
Seams are vertical and half-open: the left unit owns columns ``x < seam_x``, the right
unit owns ``x >= seam_x``, over the full strip height. Coordinates are native strip
pixels unless a name says ``_crop`` (observation ROI crop = strip x + ``box_crop[0]``).

Classes:

* ``UNKNOWN`` (default): missing, contradictory, clipped, low-resolution or unsupported
  evidence; unresolved ownership; uncertain crossing. No cut, no spacing change.
* ``LOCKED``: positive evidence that the seam divides an indivisible object or span
  (tie/slur, beam, lyric word/group, repeat sign, volta, multi-measure rest, text), a
  user ``boundary_lock``, or the seam of a cut preview tail (owned by its destination).
* ``SAFE``: every check passes for this exact seam (registered barline group within
  0.25 gap across >= 3 member observations, clear full-height corridor with clearance
  ``max(1 px, 0.15 gap)``, no crossing or bridged crossing, no text group across, no
  line endpoint or unresolved content near, barline owned by the measure it closes).

Thresholds are the brief's proposals, set conservatively; they are not tuned on the
frozen candidates (see tools/reflow_boundary_review).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import system_detect as sd

BOUNDARIES_VERSION = "reflow_boundaries-4"
MASKS_VERSION = "reflow_masks-1"

SAFE = "SAFE"
LOCKED = "LOCKED"
UNKNOWN = "UNKNOWN"
CLASSES = (SAFE, LOCKED, UNKNOWN)

CONFIG: Dict[str, Any] = {
    "version": BOUNDARIES_VERSION,
    "masks_version": MASKS_VERSION,
    # protected ink: darker than paper by this much (lighter than the detector's 60, so blur
    # fringes and anti-aliased edges are protected), and below this absolute gray level
    "protect_delta": 35,
    "protect_max_gray": 215,
    "clearance_gaps": 0.15,
    "clearance_min_px": 1,
    "bridge_gaps": 0.35,  # analysis-only bridging of broken/blurred strokes
    "text_group_gaps": 0.7,  # horizontal dilation that groups text/lyric components
    "register_tol_gaps": 0.25,
    "register_min_obs": 3,
    "register_min_fraction": 0.5,
    "min_gap_px": 8.0,
    "staff_pad_gaps": 0.5,
    "repeat_reach_gaps": 1.2,
    "dot_max_gaps": 0.7,  # a repeat dot is a whole component at most this wide and high
    "dot_align_gaps": 0.4,  # the two dots of a repeat sign, one above the other
    # ink of the barline group's own components in the middle staff spaces farther than this from the
    # detector's stroke columns (repeat dots fused with a stroke, a note head touching it): UNKNOWN
    "attached_ink_gaps": 0.5,
    "endpoint_margin_gaps": 0.5,
    "long_line_gaps": 2.0,
    "veto_uncertainty_min_px": 1,  # measured residuals always carry at least a one-pixel halo
    "veto_uncertainty_unknown_px": 2,  # no measured registration, including legacy boxes
    "neighbourhood_gaps": 2.0,
    "edge_glyph_max_gaps": 2.0,  # a clipped component at most this wide is glyph-sized
    "edge_glyph_reach_gaps": 1.0,  # ... and must stay this far from the seam
    "prefix_zone_gaps": 6.0,
    "max_corridor_gaps": 4.0,
    "number_skip_gaps": 1.6,  # jump-view strips: a measure number over the barline is skipped within this distance
    "score_layouts": ["bottom_bar", "page", "single", "unknown", None, "jump_view"],  # jump_view: reflow_jump panorama strips
}


def config_hash(config: Optional[Dict[str, Any]] = None) -> str:
    cfg = CONFIG if config is None else config
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()


def mask_sha256(mask: np.ndarray) -> str:
    return hashlib.sha256(np.packbits(np.ascontiguousarray(mask.astype(bool))).tobytes()
                          + str(mask.shape).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Strip analysis: staff geometry and versioned masks
# --------------------------------------------------------------------------- #


@dataclass
class StripAnalysis:
    system_id: str
    image: np.ndarray
    record: Dict[str, Any]
    gray: np.ndarray
    staff: Optional[Dict[str, Any]]
    protected: np.ndarray  # full-strip protection mask (all ink, conservative threshold)
    scaffold: np.ndarray  # staff-line pixels that are regenerable layout material
    nonstaff: np.ndarray  # protected & ~scaffold
    detector_ink: np.ndarray
    bars: List[Dict[str, Any]] = field(default_factory=list)
    band: Tuple[int, int] = (0, 0)  # staff-analysis rows (half-open)
    comps: Optional[np.ndarray] = None  # labels of nonstaff components
    comp_stats: Optional[np.ndarray] = None
    observations: Optional[List[Dict[str, Any]]] = None
    issues: List[str] = field(default_factory=list)
    clef: bool = False

    @property
    def gap(self) -> float:
        return float(self.staff["gap"]) if self.staff else 0.0

    def mask_hashes(self) -> Dict[str, str]:
        return {"version": MASKS_VERSION, "protected": mask_sha256(self.protected), "scaffold": mask_sha256(self.scaffold),
                "nonstaff": mask_sha256(self.nonstaff)}


def source_frame_edges(box: Sequence[float], manifest: Dict[str, Any]) -> Dict[str, bool]:
    """Map the strip's first/last pixel rows back to the source frame (0.5 px).

    Boxes are half-open; the bottom pixel row is y1 - 1, not y1. Both endpoints
    must coincide, so a rotated/skewed edge cannot exempt an entire strip row.
    Missing or invalid geometry never grants an exemption.
    """
    edges = {"top": False, "bottom": False}
    try:
        _fw, fh = (manifest.get("source") or {})["frame_size"]
        inverse = np.linalg.inv(np.asarray(manifest["source_to_crop"], np.float64).reshape(3, 3))
        x0, y0, x1, y1 = map(float, box)
        if fh <= 0 or x1 <= x0 or y1 <= y0:
            return edges
        for side, row, target in (("top", y0, 0.0), ("bottom", y1 - 1.0, fh - 1.0)):
            points = inverse @ np.array([[x0, x1 - 1.0], [row, row], [1.0, 1.0]])
            if np.any(points[2] == 0):
                continue
            ys = points[1] / points[2]
            edges[side] = bool(np.isfinite(ys).all() and np.all(np.abs(ys - target) <= 0.5))
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError):
        pass
    return edges


def strip_frame_edges(record: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, bool]:
    """Frame coincidence for page boxes or every jump panorama owner.

    Jump offsets map display ROI coordinates into the written strip. A global
    exemption requires every owner to share that source edge; mixed-height
    panoramas conservatively retain the veto.
    """
    jump = record.get("jump") or {}
    if not jump:
        return source_frame_edges(record.get("box_crop") or [], manifest)
    owners = jump.get("owners") or []
    size = record.get("size") or []
    if not owners or len(size) != 2:
        return {"top": False, "bottom": False}
    mapped = []
    for owner in owners:
        try:
            a, z = owner["strip_cols"]
            ox, oy = owner["offset_x"], owner["offset_y"]
            mapped.append(source_frame_edges([a - ox, -oy, z - ox, size[1] - oy], manifest))
        except (KeyError, TypeError, ValueError):
            return {"top": False, "bottom": False}
    return {side: all(e[side] for e in mapped) for side in ("top", "bottom")}


def protected_ink(gray: np.ndarray, config: Dict[str, Any] = CONFIG) -> np.ndarray:
    paper = sd.percentile_u8(gray, 75)
    thr = min(float(config["protect_max_gray"]), paper - float(config["protect_delta"]))
    return gray < thr


def _thickness(ink: np.ndarray, lines: Sequence[float], x0: int, x1: int) -> float:
    vals = []
    h = ink.shape[0]
    for c in np.linspace(x0, max(x0, x1 - 1), num=32).astype(int):
        for y in lines:
            yi = int(round(y))
            if not (0 <= yi < h) or not ink[yi, c]:
                continue
            a = yi
            while a > 0 and ink[a - 1, c]:
                a -= 1
            b = yi
            while b < h - 1 and ink[b + 1, c]:
                b += 1
            vals.append(b - a + 1)
    return float(np.median(vals)) if vals else 1.0


def staff_from_record(record: Dict[str, Any], ink: np.ndarray) -> Optional[Dict[str, Any]]:
    lines = record.get("staff_y_strip") or []
    gap = record.get("staff_gap_px")
    sx = record.get("staff_x_strip") or []
    if len(lines) != 5 or not gap or len(sx) != 2:
        return None
    x0, x1 = max(0, int(sx[0])), min(ink.shape[1] - 1, int(sx[1]))
    if x1 - x0 < 3 * float(gap):
        return None
    return {"lines": [float(y) for y in lines], "gap": float(gap), "thick": _thickness(ink, lines, x0, x1), "x": (x0, x1)}


def scaffold_mask(protected: np.ndarray, staff: Dict[str, Any]) -> np.ndarray:
    """Staff-line pixels with paper directly above and below the line (also one column to each side):
    only such pixels are scaffold; a line pixel touched by any other object stays protected."""
    h, w = protected.shape
    out = np.zeros_like(protected, dtype=bool)
    half = staff["thick"] / 2.0 + 1.0
    x0, x1 = staff["x"]
    for y in staff["lines"]:
        r0, r1 = max(0, int(np.floor(y - half))), min(h, int(np.ceil(y + half)) + 1)
        above = protected[r0 - 1] if r0 - 1 >= 0 else np.zeros(w, bool)
        below = protected[r1] if r1 < h else np.zeros(w, bool)
        clean = ~(above | below)
        clean = clean & np.r_[True, clean[:-1]] & np.r_[clean[1:], True]
        cols = np.zeros(w, bool)
        cols[x0:x1 + 1] = True
        out[r0:r1] |= protected[r0:r1] & (clean & cols)[None, :]
    return out


def analyse_strip(image: np.ndarray, record: Dict[str, Any], *, system_id: Optional[str] = None,
                  observations: Optional[List[Dict[str, Any]]] = None, config: Dict[str, Any] = CONFIG) -> StripAnalysis:
    """Masks, staff geometry and barline groups of one cleaned strip.

    ``observations``: the member observations' system regions (``bars`` and ``staff_x`` in ROI-crop
    coordinates, ``staff_gap_px``) used to register barlines; ``None`` means not available."""
    img, _inv = sd.normalize_polarity(image)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    prot = protected_ink(gray, config)
    det = sd.ink_mask(img)
    staff = staff_from_record(record, det)
    an = StripAnalysis(system_id=system_id or str(record.get("system_id") or "system"), image=image, record=record, gray=gray,
                       staff=staff, protected=prot, scaffold=np.zeros_like(prot), nonstaff=prot.copy(), detector_ink=det,
                       observations=observations)
    if staff is None:
        an.issues.append("NO_STAFF_GEOMETRY")
        return an
    g = staff["gap"]
    an.scaffold = scaffold_mask(prot, staff)
    an.nonstaff = prot & ~an.scaffold
    h = img.shape[0]
    an.band = (max(0, int(np.floor(staff["lines"][0] - config["staff_pad_gaps"] * g))),
               min(h, int(np.ceil(staff["lines"][4] + config["staff_pad_gaps"] * g)) + 1))
    det_nonstaff = det.copy()
    half = staff["thick"] / 2 + 1
    for y in staff["lines"]:
        det_nonstaff[max(0, int(y - half)): int(y + half) + 1] = 0
    bars = sd.find_barlines(det, staff, det_nonstaff)
    an.clef = bool(sd.has_percussion_clef(det, staff))
    if an.clef:
        bars = [b for b in bars if b["x0"] - staff["x"][0] >= 6 * g or len(b["strokes"]) > 1]
    n, lab, stats, _c = cv2.connectedComponentsWithStats(an.nonstaff.astype(np.uint8), connectivity=8)
    an.comps, an.comp_stats = lab, stats
    for b in bars:
        b["dots"], b["possible_dots"] = _repeat_dots(an, int(b["x0"]), int(b["x1"]), config)
        b["thick_stroke"] = any((s[1] - s[0] + 1) >= max(3, 0.3 * g) for s in b["strokes"])
        b["registration"] = _register(an, b, config)
    an.bars = bars
    return an


def _repeat_dots(an: StripAnalysis, x0: int, x1: int, config: Dict[str, Any]) -> Tuple[Dict[str, bool], Dict[str, bool]]:
    """Repeat dots next to a barline group: ``(dots, possible_dots)`` per side.

    A dot candidate is a whole non-staff component (full-strip labels, so a note head or rest cut
    by a search window is never mistaken for a dot; a 1-px dot counts) at most ``dot_max_gaps``
    wide and high, centred in one of the two middle staff spaces, within the repeat reach of the
    group. ``dots[side]``: a candidate in each middle space, one above the other (a repeat sign).
    ``possible_dots[side]``: a candidate in only one space (a broken or faded repeat sign, or an
    augmentation/staccato dot) - never proof either way, so a seam on that side stays UNKNOWN."""
    st = an.staff
    g = st["gap"]
    l = st["lines"]
    spaces = [(l[1] + l[2]) / 2, (l[2] + l[3]) / 2]
    reach = config["repeat_reach_gaps"] * g
    dmax = config["dot_max_gaps"] * g
    w = an.nonstaff.shape[1]
    dots, possible = {}, {}
    r0 = max(0, int(np.floor(spaces[0] - 0.5 * g)))
    r1 = int(np.ceil(spaces[1] + 0.5 * g)) + 1
    for side, (a, b) in (("left", (max(0, int(x0 - reach)), x0)), ("right", (x1 + 1, min(w, int(np.ceil(x1 + 1 + reach)))))):
        found: List[List[float]] = [[], []]
        if b > a:
            for k in {int(v) for v in np.unique(an.comps[r0:r1, a:b]) if v != 0}:
                x, y, ww, hh, _area = (int(v) for v in an.comp_stats[k])
                if ww > dmax or hh > dmax:
                    continue
                cx, cy = x + ww / 2.0, y + hh / 2.0
                for i, yc in enumerate(spaces):
                    if abs(cy - yc) <= 0.35 * g:
                        found[i].append(cx)
        dots[side] = any(abs(p - q) <= config["dot_align_gaps"] * g for p in found[0] for q in found[1])
        possible[side] = bool(found[0] or found[1]) and not dots[side]
    return dots, possible


def _register(an: StripAnalysis, bar: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    if an.observations is None:
        return {"available": False, "usable": 0, "agree": 0}
    g = an.gap
    box0 = int((an.record.get("box_crop") or [0])[0])
    cx = (bar["x0"] + bar["x1"]) / 2.0 + box0
    usable = agree = 0
    for reg in an.observations:
        rg = float(reg.get("staff_gap_px") or 0)
        sx = reg.get("staff_x") or [0, 0]
        if rg <= 0 or abs(rg - g) > 0.05 * g or not (sx[0] - g <= cx <= sx[1] + g):
            continue
        usable += 1
        centres = [(b[0] + b[1]) / 2.0 for b in reg.get("bars") or []]
        if any(abs(c - cx) <= config["register_tol_gaps"] * g for c in centres):
            agree += 1
    return {"available": True, "usable": usable, "agree": agree}


# --------------------------------------------------------------------------- #
# Proposals
# --------------------------------------------------------------------------- #


def _number_like(an: StripAnalysis, k: int) -> bool:
    """A small glyph wholly above the top staff line (a measure number over a barline)."""
    x, y, w, h, _a = (int(v) for v in an.comp_stats[k])
    g = an.gap
    return y + h <= an.staff["lines"][0] + 0.5 * an.staff["thick"] + 1 and w <= 1.5 * g and h <= 1.5 * g


def propose(an: StripAnalysis, config: Dict[str, Any] = CONFIG) -> List[Dict[str, Any]]:
    """One proposal per internal barline group: the seam in the middle of the clear staff-band corridor on
    the side away from the measure the group belongs to (right of an ordinary/end-repeat group, left of a
    start-repeat group). The staff-start and staff-end groups are not internal boundaries."""
    if an.staff is None:
        return []
    g = an.gap
    xs, xe = an.staff["x"]
    band = an.comps[an.band[0]:an.band[1]]
    out = []
    limit = int(config["max_corridor_gaps"] * g)
    clear = ~an.nonstaff.any(axis=0)
    stops = np.flatnonzero(~clear)
    jump_numbers = (an.record or {}).get("layout") == "jump_view"
    max_number_px = int(np.ceil(config["number_skip_gaps"] * g))
    for b in an.bars:
        x0, x1 = int(b["x0"]), int(b["x1"])
        if xe - x1 <= g or x0 - xs <= g:
            continue
        own = _group_labels(an, b)

        def col_ids(x: int) -> set:
            return {int(k) for k in np.unique(band[:, x]) if k != 0}

        start_repeat = b["dots"]["right"] and not b["dots"]["left"]
        step = -1 if start_repeat else 1
        x = x0 - 1 if start_repeat else x1 + 1
        # skip the group's own fringe, then take the run of clear columns
        while 0 <= x < band.shape[1] and abs(x - (x0 if start_repeat else x1)) <= limit and col_ids(x) and col_ids(x) <= own:
            x += step
        if jump_numbers and not start_repeat:
            # jump-view panorama: a measure number printed over the barline (small glyphs wholly above
            # the top staff line, starting at the barline) is skipped too; it stays with the left unit
            near = an.comps[:, max(0, x1 - int(0.5 * g)): min(band.shape[1], x1 + 1 + max_number_px)]
            nums = [int(k) for k in np.unique(near) if k != 0 and _number_like(an, int(k))
                    and int(an.comp_stats[int(k), 0]) <= x1 + g]
            if nums:
                end = max(int(an.comp_stats[k, 0] + an.comp_stats[k, 2]) for k in nums)
                allowed = own | set(nums)
                if end - x1 <= max_number_px and all(col_ids(c) <= allowed for c in range(x, min(end, band.shape[1]))):
                    x = max(x, end)
        first = x
        while 0 <= x < band.shape[1] and abs(x - first) <= limit and not col_ids(x):
            x += step
        a, z = (x + 1, first + 1) if start_repeat else (first, x)
        owner = "right" if start_repeat else "left"
        seam = (a + z) // 2 if z > a else (x0 if start_repeat else x1 + 1)
        # Contraction may touch the full-height scaffold run, beyond the
        # staff-band proposal. Match reflow_measure's clear_native/_clear_run.
        ta = tz = seam
        if 0 <= seam < len(clear) and clear[seam]:
            left = stops[stops < seam]
            right = stops[stops > seam]
            ta = int(left[-1]+1) if len(left) else 0
            tz = int(right[0]) if len(right) else len(clear)
        out.append({"seam_x": int(seam), "bar": b, "barline_owner": owner, "corridor": [int(a), int(z)],
                    "trim_ranges": [[ta,tz]] if tz>ta else []})
    return out


# --------------------------------------------------------------------------- #
# Classification of one exact seam
# --------------------------------------------------------------------------- #


def _comp_boxes_in(an: StripAnalysis, x0: int, x1: int, rows: Optional[Tuple[int, int]] = None) -> List[int]:
    rows = rows or (0, an.nonstaff.shape[0])
    sub = an.comps[rows[0]:rows[1], max(0, x0):max(0, x1)]
    ids = np.unique(sub)
    return [int(k) for k in ids if k != 0]


def _box(an: StripAnalysis, k: int) -> List[int]:
    x, y, w, h = (int(v) for v in an.comp_stats[k, :4])
    return [x, y, x + w, y + h]


def _group_labels(an: StripAnalysis, bar: Dict[str, Any]) -> set:
    """Component labels of a barline group's strokes (with their anti-aliased fringe)."""
    sub = an.comps[an.band[0]:an.band[1], int(bar["x0"]):int(bar["x1"]) + 1]
    return {int(k) for k in np.unique(sub) if k != 0}


def _only_labels(an: StripAnalysis, rows: Tuple[int, int], x0: int, x1: int, allowed: set) -> bool:
    if x1 <= x0:
        return True
    sub = an.comps[rows[0]:rows[1], x0:x1]
    ids = {int(k) for k in np.unique(sub) if k != 0}
    return ids <= allowed


def _crossing_kind(an: StripAnalysis, box: Sequence[int], area: int) -> str:
    g = an.gap
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    outside = y1 <= an.band[0] or y0 >= an.band[1]
    fill = area / max(1, w * h)
    if outside and w >= 1.5 * g and fill < 0.35:
        return "TIE_SLUR_OR_LINE_CROSSES"
    if outside:
        return "TEXT_OR_SYMBOL_CROSSES"
    if w >= 1.5 * g and h <= 1.0 * g and fill >= 0.35:
        return "BEAM_OR_REST_CROSSES"
    if w >= 1.5 * g and fill < 0.35:
        return "TIE_SLUR_OR_LINE_CROSSES"
    return "OBJECT_CROSSES"


def _is_text_like(an: StripAnalysis, k: int) -> bool:
    """A component entirely outside the staff-analysis band and at most text-high (lyrics, labels,
    tempo/dynamics text, voltas, hairpins, ties/slurs above or below the staff)."""
    x, y, w, h, _a = (int(v) for v in an.comp_stats[k])
    return (y + h <= an.band[0] or y >= an.band[1]) and h <= 2.5 * an.gap


def _spans(mask: np.ndarray, seam: int) -> bool:
    return bool(mask[:, :seam].any() and mask[:, seam:].any())


def _veto_uncertainty(event: Dict[str, Any], owner: Dict[str, Any], record: Dict[str, Any],
                      config: Dict[str, Any]) -> Tuple[int, str]:
    obs_id = owner.get("obs_id")
    candidates = []
    for local in event.get("local_registration") or []:
        if local.get("obs_id") == obs_id:
            candidates.append((local.get("attempted_shift_px"),"local_registration.attempted_shift_px"))
    for key in ("attempted_shift_px", "registration_uncertainty", "registration_shift", "shift_px"):
        if key in owner:
            candidates.append((owner[key],"member."+key))
    for member in record.get("member_registration") or []:
        if member.get("obs_id",member.get("id")) == obs_id:
            for key in ("residual_shift_px", "attempted_shift_px", "registration_uncertainty", "shift_px", "registration_shift"):
                if key in member:
                    candidates.append((member[key],"member_registration."+key))
    candidates.append((record.get("max_rel_shift_px"),"max_rel_shift_px"))
    for value,source in candidates:
        if value is None:
            continue
        v = np.asarray(value,dtype=float)
        r = float(np.linalg.norm(v)) if v.ndim else abs(float(v))
        if np.isfinite(r):
            return max(int(config["veto_uncertainty_min_px"]),int(np.ceil(r))),source
    return int(config["veto_uncertainty_unknown_px"]),"unknown"


def _veto_connected(an: StripAnalysis, config: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """Full-strip text groups and thin spans, with 8-connected native labels."""
    ids = []
    for k in range(1,len(an.comp_stats)):
        _x,_y,ww,hh,_area = an.comp_stats[k]
        if _is_text_like(an,k) or (ww>=config["long_line_gaps"]*an.gap and hh<=1.5*an.gap):
            ids.append(k)
    text_ids = [k for k in ids if _is_text_like(an,k)]
    selected = np.isin(an.comps,ids)
    if text_ids:
        text = np.isin(an.comps,text_ids).astype(np.uint8)
        tg = max(1,int(round(config["text_group_gaps"]*an.gap)))
        selected |= cv2.dilate(text,np.ones((1,2*tg+1),np.uint8))>0
    _n,labels,stats,_ = cv2.connectedComponentsWithStats(selected.astype(np.uint8),connectivity=8)
    return labels,stats


def _veto_touch(an: StripAnalysis, box: Sequence[int], corridor: Sequence[int], trims: Sequence[Sequence[int]],
                connected: Tuple[np.ndarray, np.ndarray]) -> Optional[str]:
    x0,y0,x1,y1 = box
    h,w = an.nonstaff.shape
    if y0>=h or y1<=0 or x0>=w or x1<=0:
        return None
    if x0<corridor[1] and x1>corridor[0]:
        return "corridor"
    if any(x0<z and x1>a for a,z in trims):
        return "trim"
    labels,stats = connected
    # Adjacent diagonal pixels count as touching the dilated possible mark.
    near = labels[max(0,y0-1):min(h,y1+1),max(0,x0-1):min(w,x1+1)]
    for k in np.unique(near):
        if k==0:
            continue
        a = int(stats[k,cv2.CC_STAT_LEFT])
        z = a+int(stats[k,cv2.CC_STAT_WIDTH])
        if (a<corridor[1] and z>corridor[0]) or any(a<t1 and z>t0 for t0,t1 in trims):
            return "connected_component"
    return None


def classify_seam(an: StripAnalysis, seam_x: int, *, boundary_id: Optional[str] = None, locks: Iterable[Dict[str, Any]] = (),
                  config: Dict[str, Any] = CONFIG,
                  trim_ranges: Optional[Sequence[Sequence[int]]] = None) -> Dict[str, Any]:
    """Classify a strip seam; optional trim_ranges are touched native-strip columns.

    The owning join/cut caller supplies later clef/scaffold removal ranges here;
    the proposal already includes the full-height scaffold run at this seam.
    """
    locked: List[str] = []
    unknown: List[str] = []
    ev: Dict[str, Any] = {"seam_x": int(seam_x)}
    rec = an.record
    h, w = an.protected.shape
    for lk in locks or ():
        if lk.get("type") == "boundary_lock" and lk.get("active", True) and boundary_id in (lk.get("targets") or []):
            locked.append("USER_LOCK")
    if an.staff is None:
        return _result(locked, unknown + ["NO_STAFF_GEOMETRY"], ev)
    g = an.gap
    seam = int(seam_x)
    if g < config["min_gap_px"]:
        unknown.append("LOW_RESOLUTION")
    xs, xe = an.staff["x"]
    if not (xs < seam <= xe):
        unknown.append("OUTSIDE_STAFF")
        return _result(locked, unknown, ev)
    layout = rec.get("layout")
    if layout not in config["score_layouts"]:
        unknown.append("NON_SCORE_LAYOUT")
    flags = [str(f).upper() for f in rec.get("envelope_flags") or []]
    if any("CLIP" in f for f in flags):
        unknown.append("ENVELOPE_CLIPPED")
    tail = rec.get("preview_tail") or {}
    if tail and not tail.get("cut") and tail.get("cut_x") is not None:
        tail_x = int(tail.get("break_x", tail["cut_x"])) - int((rec.get("box_crop") or [0])[0])
        if seam >= tail_x - g:
            unknown.append("UNRESOLVED_PREVIEW_TAIL")
    if seam - xs <= config["prefix_zone_gaps"] * g:
        unknown.append("PREFIX_ZONE")

    # ---- full-height crossing evidence (veto) ----
    c = int(max(config["clearance_min_px"], np.ceil(config["clearance_gaps"] * g)))
    wa, wz = max(0, seam - c), min(w, seam + c)
    window = an.nonstaff[:, wa:wz]
    near_ids = _comp_boxes_in(an, wa, wz)
    bar_labels = set()
    for b in an.bars:
        bar_labels |= _group_labels(an, b)
    crossing = []
    for k in near_ids:
        box = _box(an, k)
        if box[0] < seam < box[2] and _spans(an.comps[:, box[0]:box[2]] == k, seam - box[0]):
            # ink attached to a barline group that reaches across the seam (a slur through the barline,
            # a note touching it) crosses like any other object
            kind = "ATTACHED_TO_BARLINE_CROSSES" if k in bar_labels else _crossing_kind(an, box, int(an.comp_stats[k, 4]))
            crossing.append({"box": box, "kind": kind})
    ev["clearance_px"] = c
    if crossing:
        locked.extend(sorted({cr["kind"] for cr in crossing}))
        ev["crossing"] = crossing[:12]
    elif window.any():
        unknown.append("INSUFFICIENT_CLEARANCE")
        ys, xs_ = np.nonzero(window)
        ev["nearest_ink_px"] = int(np.min(np.abs((xs_ + wa) - seam + 0.5)))

    # ---- barline group adjacency (staff-band evidence) ----
    group = None
    side = None
    for b in an.bars:
        x0, x1 = int(b["x0"]), int(b["x1"])
        reach = config["repeat_reach_gaps"] * g
        # the whole group: strokes plus the repeat dots on either side; never cut inside it
        z0 = x0 - (reach if b["dots"]["left"] else 0)
        z1 = x1 + 1 + (reach if b["dots"]["right"] else 0)
        if z0 < seam < z1:
            locked.append("CUTS_BARLINE_OR_REPEAT_GROUP")
        pd = b.get("possible_dots") or {}
        if (pd.get("left") and x0 - reach < seam <= x0) or (pd.get("right") and x1 + 1 <= seam < x1 + 1 + reach):
            unknown.append("POSSIBLE_REPEAT_DOT")
        own = _group_labels(an, b)
        if (an.record or {}).get("layout") == "jump_view" and x1 < seam:
            # a measure number over the barline (see propose) sits between the barline and the seam
            sub = an.comps[an.band[0]:an.band[1], x1 + 1:seam]
            own = own | {int(k) for k in np.unique(sub) if k != 0 and _number_like(an, int(k))}
        between_right = (x1 < seam) and seam - x1 <= config["max_corridor_gaps"] * g and _only_labels(an, an.band, x1 + 1, seam, own)
        between_left = (seam <= x0) and x0 - seam <= config["max_corridor_gaps"] * g and _only_labels(an, an.band, seam, x0, own)
        if between_right:
            group, side = b, "left"
        elif between_left and group is None:
            group, side = b, "right"
    if group is None:
        unknown.append("NO_ADJACENT_BARLINE")
    else:
        x0, x1 = int(group["x0"]), int(group["x1"])
        ev["barline"] = {"x0": x0, "x1": x1 + 1, "strokes": [[int(a), int(b) + 1] for a, b in group["strokes"]],
                         "dots": group["dots"], "thick_stroke": group["thick_stroke"], "owner": side,
                         "registration": group["registration"]}
        if group["dots"]["left"] or group["dots"]["right"]:
            locked.append("REPEAT_BOUNDARY")
        # repeat dots fused with a stroke are not separate components, so _repeat_dots cannot see them:
        # any ink of the group's own components reaching into the middle staff spaces beyond the strokes
        # leaves the group's extent and direction unresolved
        attached = _attached_ink(an, group, config)
        if attached:
            unknown.append("BARLINE_GROUP_ATTACHED_INK")
            ev["barline"]["attached_ink"] = attached
        # one dot on the seam side of the group (a broken or faded start/end repeat?) is unresolved
        if (group.get("possible_dots") or {}).get("right" if side == "left" else "left"):
            unknown.append("POSSIBLE_REPEAT_DOT")
        ev["barline"]["possible_dots"] = group.get("possible_dots")
        if xe - x1 <= g:
            unknown.append("SYSTEM_EDGE")
        if side != "left":
            # an ordinary (or double/final) barline closes the measure on its left; only a verified
            # start-repeat goes right, and repeats are locked in this slice
            unknown.append("BARLINE_OWNER_UNVERIFIED")
        if len(group["strokes"]) > 1 and not group["thick_stroke"]:
            unknown.append("DOUBLE_BAR_UNVERIFIED")
        reg = group["registration"]
        if not reg["available"]:
            unknown.append("NO_OBSERVATIONS")
        elif reg["agree"] < config["register_min_obs"]:
            unknown.append("INSUFFICIENT_OBSERVATIONS")
        elif reg["agree"] < config["register_min_fraction"] * reg["usable"]:
            unknown.append("BARLINE_REGISTRATION_DISAGREES")

    # ---- bridged (broken / blurred) strokes across the seam, analysis only ----
    # ink approaching the seam from both sides at about the same height (within the bridge
    # distance) is treated as one stroke with a gap: a broken tie or a blurred, faded arc
    if not crossing:
        r = max(2, int(round(config["bridge_gaps"] * g)))
        lab = an.comps
        near_l = lab[:, max(0, seam - c - r):max(0, seam - c)]
        near_r = lab[:, min(w, seam + c):min(w, seam + c + r)]
        if bar_labels:
            near_l = np.where(np.isin(near_l, list(bar_labels)), 0, near_l)
            near_r = np.where(np.isin(near_r, list(bar_labels)), 0, near_r)
        rows_l = (near_l > 0).any(axis=1)
        rows_r = (near_r > 0).any(axis=1)
        if rows_l.any() and rows_r.any():
            dil = cv2.dilate(rows_l.astype(np.uint8)[:, None], np.ones((2 * r + 1, 1), np.uint8))[:, 0] > 0
            if (dil & rows_r).any():
                unknown.append("POSSIBLE_BROKEN_STROKE")

    # ---- text / lyric groups (rows outside the staff-analysis band) ----
    tg = max(1, int(round(config["text_group_gaps"] * g)))
    a, z = max(0, seam - 6 * tg), min(w, seam + 6 * tg)
    sub_lab = an.comps[:, a:z]
    text_ids = [int(k) for k in np.unique(sub_lab) if k != 0 and _is_text_like(an, int(k))]
    text = np.isin(sub_lab, text_ids) if text_ids else np.zeros(sub_lab.shape, bool)
    if text.any():
        # baseline-aligned grouping: horizontal dilation only, so components group only when their rows overlap
        dil = cv2.dilate(text.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_RECT, (2 * tg + 1, 1)))
        n, lab = cv2.connectedComponents(dil, connectivity=8)
        s_rel = seam - a
        for kk in range(1, n):
            orig = (lab == kk) & text
            if orig[:, :s_rel].any() and orig[:, s_rel:].any():
                locked.append("TEXT_GROUP_CROSSES")
                break
        # long thin lines (voltas, hairpins, extenders) ending near the seam: uncertain endpoint
        margin = config["endpoint_margin_gaps"] * g
        nn, _l, st, _cc = cv2.connectedComponentsWithStats(text.astype(np.uint8), connectivity=8)
        for kk in range(1, nn):
            x, y, ww, hh = (int(v) for v in st[kk, :4])
            if ww >= config["long_line_gaps"] * g and hh <= 1.5 * g:
                ends = (x + a, x + ww + a)
                if any(abs(e - seam) <= margin for e in ends):
                    unknown.append("LINE_ENDPOINT_NEAR_SEAM")
                    break

    # Unresolved foreground vetoes its possible location plus registration
    # uncertainty, connected text/spans and every touched cut/trim column.
    corridor_hits = []
    ca, cz = wa, wz
    touched = list(trim_ranges or [])
    if group is not None:
        proposal = next((p for p in propose(an, config) if p["bar"] is group), None)
        if proposal and proposal["corridor"][1] > proposal["corridor"][0]:
            ca, cz = proposal["corridor"]
        if proposal:
            touched.extend(proposal.get("trim_ranges") or [])
    touched = sorted({(max(0,int(a)),min(w,int(z))) for a,z in touched if a<z})
    ev["minority_corridor_px"] = [int(ca), int(cz)]
    ev["minority_trim_ranges_px"] = [list(v) for v in touched]
    ox, oy = (rec.get("box_crop") or [0, 0])[:2]
    connected = None
    for ei, e in enumerate((rec.get("minority_content") or {}).get("events") or []):
        if str(e.get("classification", "")).startswith("EXPLAINED_") or e.get("ink_like") is False:
            continue
        support = e.get("ink_like_foreground_support", e.get("foreground_support"))
        if support is not None:
            if connected is None:
                connected = _veto_connected(an,config)
            ex, ey = (0, 0) if e.get("support_coordinate_space") == "strip" else (ox, oy)
            for owner in support:
                u,source = _veto_uncertainty(e,owner,rec,config)
                for y, a, b in owner.get("spans_crop", []):
                    hit = _veto_touch(an,[a-ex-u,y-ey-u,b-ex+u,y-ey+1+u],[ca,cz],touched,connected)
                    if hit:
                        corridor_hits.append({"event":ei,"obs_id":owner.get("obs_id"),
                                              "span_crop":[y,a,b],"uncertainty_px":u,
                                              "uncertainty_source":source,"touched_by":hit})
                        break
        else:
            # Box-only legacy records carry the unknown two-pixel halo.
            bx = e.get("box_strip")
            u = int(config["veto_uncertainty_unknown_px"])
            if bx and bx[0]-u < cz and bx[2]+u > ca and bx[1]-u < h and bx[3]+u > 0:
                corridor_hits.append({"event":ei,"obs_id":None,"span_crop":None,"legacy_box":bx,
                                      "uncertainty_px":u,"uncertainty_source":"legacy_box_unknown","touched_by":"corridor"})
    if corridor_hits:
        unknown.append("UNRESOLVED_MINORITY_CONTENT")
        ev["unresolved_foreground"] = corridor_hits
    if _clipped_near(an, seam, config, evidence=ev):
        unknown.append("CONTENT_AT_STRIP_EDGE")
    return _result(locked, unknown, ev)


def _attached_ink(an: StripAnalysis, bar: Dict[str, Any], config: Dict[str, Any] = CONFIG) -> List[Dict[str, Any]]:
    """Components of a barline group's own ink (``_group_labels``) with pixels in the two middle staff
    spaces (staff-line rows excluded) more than ``attached_ink_gaps`` beyond the detector's stroke
    columns ``[x0, x1]``: repeat dots fused with a stroke, or a note head or other glyph touching it."""
    st = an.staff
    g = st["gap"]
    l = st["lines"]
    h = an.comps.shape[0]
    half = st["thick"] / 2.0 + 1.0
    rows = np.zeros(h, bool)
    rows[max(0, int(np.ceil(l[1] + half))):min(h, int(np.floor(l[3] - half)) + 1)] = True
    rows[max(0, int(np.floor(l[2] - half))):min(h, int(np.ceil(l[2] + half)) + 1)] = False
    m = config["attached_ink_gaps"] * g
    x0, x1 = int(bar["x0"]), int(bar["x1"])
    out = []
    for k in sorted(_group_labels(an, bar)):
        bx, _by, bw, _bh, _a = (int(v) for v in an.comp_stats[k])
        sub = an.comps[rows][:, bx:bx + bw] == k
        cols = np.nonzero(sub.any(axis=0))[0] + bx
        far = cols[(cols < x0 - m) | (cols > x1 + m)]
        if len(far):
            out.append({"box": _box(an, k), "cols_beyond": [int(far.min()), int(far.max()) + 1]})
    return out


def _clipped_near(an: StripAnalysis, seam: int, config: Dict[str, Any], *,
                  evidence: Optional[Dict[str, Any]] = None) -> bool:
    """Ink cut off by the strip's top or bottom edge whose hidden part could reach the seam.

    A glyph-sized clipped component (at most ``edge_glyph_max_gaps`` wide: a lyric syllable or
    a symbol cut by the strip envelope) continues beyond the edge roughly within its own columns,
    so it must stay ``edge_glyph_reach_gaps`` away from the seam. Anything larger (an arc, a line,
    a merged group) or unlabelled may bend toward the seam out of view: it vetoes within the whole
    neighbourhood (``neighbourhood_gaps``)."""
    g = an.gap
    h, w = an.protected.shape
    nb = config["neighbourhood_gaps"] * g
    a, z = max(0, int(seam - nb)), min(w, int(seam + nb))
    edges = an.record.get("frame_edges")
    if edges is None:
        # Page producers already positively diagnose source clipping. Jump
        # diagnostics aggregate owners and cannot prove the whole edge coincides.
        sides = (an.record.get("source_clipped") or {}).get("sides") or []
        edges = {side: side in sides and not an.record.get("jump") for side in ("top", "bottom")}
    veto = False
    skipped = []
    for side, row in (("top", 0), ("bottom", h - 1)):
        cols = np.nonzero(an.protected[row, a:z])[0] + a
        if not len(cols):
            continue
        row_veto = False
        for k in {int(v) for v in an.comps[row, cols]} if an.comps is not None else {0}:
            if k == 0:
                row_veto = True
                break
            x, _y, ww, _hh, _area = (int(v) for v in an.comp_stats[k])
            dist = max(x - seam, seam - (x + ww), 0)
            if ww > config["edge_glyph_max_gaps"] * g or dist < config["edge_glyph_reach_gaps"] * g:
                row_veto = True
                break
        if row_veto:
            if edges.get(side) is True:
                skipped.append(side)
            else:
                veto = True
    if skipped and evidence is not None:
        evidence["edge_veto_skipped"] = "source_frame_edge"
        evidence["edge_veto_skipped_sides"] = skipped
    return veto


def _result(locked: List[str], unknown: List[str], ev: Dict[str, Any]) -> Dict[str, Any]:
    locked = list(dict.fromkeys(locked))
    unknown = list(dict.fromkeys(unknown))
    cls = LOCKED if locked else (UNKNOWN if unknown else SAFE)
    return {"class": cls, "reasons": locked + unknown, "locked_reasons": locked, "unknown_reasons": unknown, "evidence": ev}


# --------------------------------------------------------------------------- #
# Boundary records of one strip
# --------------------------------------------------------------------------- #


def boundary_id(system_id: str, *, bar_centre_crop: Optional[float] = None, seam_x_crop: Optional[int] = None) -> str:
    if bar_centre_crop is not None:
        return f"{system_id}/bar@{int(round(bar_centre_crop))}"
    return f"{system_id}/seam@{int(seam_x_crop)}"


def strip_boundaries(an: StripAnalysis, *, locks: Iterable[Dict[str, Any]] = (), config: Dict[str, Any] = CONFIG) -> List[Dict[str, Any]]:
    """Boundary records (unsorted adjacency filled in by reflow_units) for every internal barline proposal."""
    locks = list(locks or ())
    box0 = int((an.record.get("box_crop") or [0])[0])
    out = []
    hashes = an.mask_hashes() if an.staff is not None else {}
    for p in propose(an, config):
        b = p["bar"]
        bid = boundary_id(an.system_id, bar_centre_crop=(b["x0"] + b["x1"]) / 2.0 + box0)
        res = classify_seam(an, p["seam_x"], boundary_id=bid, locks=locks, config=config)
        out.append({
            "id": bid,
            "system_id": an.system_id,
            "kind": "barline",
            "seam_x": int(p["seam_x"]),
            "seam_x_crop": int(p["seam_x"]) + box0,
            "barline_box": [int(b["x0"]), 0, int(b["x1"]) + 1, an.image.shape[0]],
            "stroke_boxes": [[int(s0), int(s1) + 1] for s0, s1 in b["strokes"]],
            "corridor": p["corridor"],
            "barline_owner": p["barline_owner"],
            "class": res["class"],
            "reason_codes": res["reasons"],
            "evidence": dict(res["evidence"], masks=hashes, config_hash=config_hash(config)),
            "span_ids": [],
            "owned_by": None,
        })
    out.sort(key=lambda r: r["seam_x"])
    return out


def preview_tail_boundary(system_id: str, record: Dict[str, Any], uncut_width: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """A cut preview tail: its seam on the source (uncut) strip is LOCKED and owned by the destination."""
    tail = record.get("preview_tail") or {}
    unc = record.get("uncut") or {}
    if not tail.get("cut") or not unc:
        return None
    x0 = int(unc["box_crop"][0])
    seam = int(tail["cut_x"]) - x0
    return {
        "id": f"{system_id}/tail@{int(tail['cut_x'])}",
        "system_id": system_id,
        "kind": "preview_tail",
        "asset": "uncut",
        "seam_x": seam,
        "seam_x_crop": int(tail["cut_x"]),
        "barline_box": None,
        "stroke_boxes": [],
        "corridor": None,
        "barline_owner": None,
        "class": LOCKED,
        "reason_codes": ["PREVIEW_TAIL_SEAM"],
        "evidence": {"destination_system_id": tail.get("destination_system_id"), "verified": bool(tail.get("verified")),
                     "uncut_width": uncut_width},
        "span_ids": [],
        "owned_by": tail.get("destination_system_id"),
    }


def member_regions(record: Dict[str, Any], occurrence: Optional[Dict[str, Any]], obs_by: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The system regions of the strip's member observations (for barline registration).

    A jump-view panorama strip (``record["jump"]``) lists its members with the offset of their
    display: a member's crop x shows strip x = crop x + ``offset_x`` (the strip's ``box_crop`` starts
    at 0), so its barlines and staff extent are shifted by that offset."""
    jump = record.get("jump")
    if jump:
        shifted = []
        for m in jump.get("members") or []:
            o = obs_by.get(m["obs_id"])
            reg = next((r for r in (o or {}).get("system_regions") or [] if r.get("region_id") == m.get("region_id")), None)
            if reg is None:
                continue
            dx = int(m.get("offset_x") or 0)
            reg = dict(reg, bars=[[b[0] + dx, b[1] + dx] + list(b[2:]) for b in reg.get("bars") or []],
                       staff_x=[int(reg["staff_x"][0]) + dx, int(reg["staff_x"][1]) + dx] if reg.get("staff_x") else reg.get("staff_x"))
            shifted.append(reg)
        return shifted
    region_of = {}
    for m in (occurrence or {}).get("observations") or []:
        region_of[m["obs_id"]] = m.get("region_id")
    out = []
    for oid in record.get("member_obs_ids") or []:
        o = obs_by.get(oid)
        if not o:
            continue
        rid = region_of.get(oid)
        regs = o.get("system_regions") or []
        reg = next((r for r in regs if r.get("region_id") == rid), None)
        if reg is None and len(regs) == 1:
            reg = regs[0]
        if reg is not None:
            out.append(reg)
    return out
