"""Measure units: the ``reflow_units.json`` contract, ownership and prefix references.

MEASURE_BRIEF milestone 1 (no new layout yet; not on the export path).

A system's strip is split only at SAFE boundaries. Between two cuts lies one unit:

* ``measure``: no internal barline boundary (``measure_count`` 1, or null when the unit may be
  a multi-measure rest);
* ``locked_group``: internal LOCKED/UNKNOWN boundaries stay inside (``measure_count`` null);
* ``system``: no SAFE boundary at all - the whole cleaned system is kept (the fallback);
* ``preview_tail``: the cut tail of a source strip, owned by its destination occurrence
  (asset = the uncut strip); ``uncut_remainder`` is the rest of that uncut asset, owned by the
  source occurrence and placed through the cut strip's units (never counted as measures).

Coordinates are native asset pixels; boxes are half-open ``[x0, y0, x1, y1]``. IDs include the
occurrence id, so identical-looking returns (D.S.) stay distinct. Alternates and listed
(unchecked) systems are recorded as excluded and get no units.
"""

from __future__ import annotations

import copy

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_accounting as ra
from app.pipeline import reflow_boundaries as rb
from app.pipeline import system_detect as sd

UNITS_SCHEMA_VERSION = 1
UNITS_VERSION = "reflow_units-2"
UNIT_KINDS = ("measure", "locked_group", "system", "preview_tail", "uncut_remainder")
LOCK_TYPES = ("boundary_lock", "keep_together", "forced_line_break")
ROOT_FIELDS = ("schema_version", "kind", "job_id", "revision", "analysis_hash", "algorithm", "config_hash", "sources",
               "included_occurrence_ids", "excluded_occurrence_ids", "measure_units", "boundaries", "lines",
               "justification_slots", "locks", "ragged_exceptions", "audit")


def _canon_sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _pixels_sha(img: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest()


CLEF_MAX_START_GAPS = 2.5  # a clef component starts within this distance of the staff start
CLEF_ZONE_GAPS = 3.5  # ... and ends within this distance
CLEF_MIN_CLEAR_GAPS = 0.3  # clear staff-band columns needed right after the clef (else a glyph touches it)


def clef_patch(an: rb.StripAnalysis) -> Dict[str, Any]:
    """Verified clef-only source patch at the system start (for a replica at a new line start).

    Verified only for a percussion clef: exactly two short thick bars wholly inside the staff band,
    starting within ``CLEF_MAX_START_GAPS`` of the staff start, no other component starting in that
    zone, and at least ``CLEF_MIN_CLEAR_GAPS`` of clear staff-band columns after the bars. The patch
    spans the staff start to the middle of that clear run, full strip height; it keeps the clef
    bars, the staff-line scaffold and the paper, and sets every other ink pixel (a measure number
    or label above the clef, a lyric below; with a one-pixel fringe) to paper. Ink glued to the
    clef or touching it (a time signature, a note) leaves it unverified. Ink wholly above the top
    staff line or below the bottom one (a section box, "h.h open", a lyric) that stays
    ``CLEF_OUTSIDE_INK_CLEARANCE_PX`` clear of the clef does not block it (user feedback
    2026-10-07); it is kept in place in the source and left out of the replica. A time signature is
    never part of a replica."""
    out: Dict[str, Any] = {"verified": False}
    if an.staff is None or an.comps is None:
        return dict(out, reason="NO_STAFF_GEOMETRY")
    if not an.clef:
        return dict(out, reason="NO_PERCUSSION_CLEF")
    g = an.gap
    xs = int(an.staff["x"][0])
    b0, b1 = an.band
    zone = an.comps[b0:b1, xs:min(an.comps.shape[1], int(xs + CLEF_ZONE_GAPS * g))]
    ids = {int(k) for k in np.unique(zone) if k != 0}
    clef_ids, foreign = [], []
    for k in ids:
        x, y, w, h, _a = (int(v) for v in an.comp_stats[k])
        if _outside_staff_lines(an, k):
            continue  # a section box / text above the staff, a lyric below it: kept in place (checked below)
        if x - xs > CLEF_MAX_START_GAPS * g:
            continue  # starts after the clef zone (time signature, first note): handled by the clear-run check
        inside_band = y >= b0 and y + h <= b1
        if inside_band and x + w <= xs + CLEF_ZONE_GAPS * g and 1.0 * g <= h <= 3.2 * g and w <= 0.9 * g:
            clef_ids.append(k)
        else:
            foreign.append(k)
    if foreign:
        return dict(out, reason="CLEF_PATCH_CONTAMINATED", other_components=len(foreign),
                    component_boxes=[_box_of(an, k) for k in sorted(foreign)])
    if len(clef_ids) != 2:
        # the percussion clef is two short thick bars; anything else is not a verified clef-only patch
        return dict(out, reason="CLEF_NOT_ISOLATED", clef_components=len(clef_ids))
    kept = _kept_outside_ids(an, clef_ids)
    if kept:
        near = cv2.dilate(np.isin(an.comps, clef_ids).astype(np.uint8), np.ones((3, 3), np.uint8),
                          iterations=CLEF_OUTSIDE_INK_CLEARANCE_PX).astype(bool)
        touching = [k for k in kept if (near & (an.comps == k)).any()]
        if touching:
            return dict(out, reason="CLEF_TOUCHES_OUTSIDE_INK", component_boxes=[_box_of(an, k) for k in touching])
    cx1 = max(int(an.comp_stats[k, 0] + an.comp_stats[k, 2]) for k in clef_ids)
    band = an.nonstaff[b0:b1] & ~np.isin(an.comps[b0:b1], kept) if kept else an.nonstaff[b0:b1]
    clear = 0
    x = cx1
    while x < band.shape[1] and not band[:, x].any() and clear < int(np.ceil(2 * g)):
        clear += 1
        x += 1
    if clear < CLEF_MIN_CLEAR_GAPS * g:
        return dict(out, reason="CLEF_TOUCHES_NEXT_GLYPH", clear_px=clear)
    end = cx1 + max(1, clear // 2)
    sub = an.comps[b0:b1, xs:end]
    others = {int(k) for k in np.unique(sub) if k != 0} - set(clef_ids) - set(kept)
    if others:
        return dict(out, reason="CLEF_PATCH_CONTAMINATED", other_components=len(others),
                    component_boxes=[_box_of(an, k) for k in sorted(others)], where="clear_run_after_clef")
    img = an.image
    keep = np.isin(an.comps[:, xs:end], clef_ids) | an.scaffold[:, xs:end]
    paper_vals = img[:, xs:end][~an.protected[:, xs:end]]
    paper = np.median(paper_vals.reshape(-1, img.shape[2]) if img.ndim == 3 else paper_vals, axis=0) if paper_vals.size \
        else np.full(img.shape[2:] or (), 255)
    patch = img[:, xs:end].copy()
    # other ink (and its one-pixel anti-aliased fringe) becomes paper; paper and the staff
    # scaffold keep their source pixels
    masked = an.protected[:, xs:end] & ~keep
    blank = cv2.dilate(masked.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~keep
    patch[blank] = np.asarray(paper, dtype=img.dtype)
    return {
        "verified": True,
        "kind": "percussion_clef",
        "box": [xs, 0, end, img.shape[0]],
        "coords": "native_strip",
        "clef_boxes": [[int(an.comp_stats[k, 0]), int(an.comp_stats[k, 1]), int(an.comp_stats[k, 0] + an.comp_stats[k, 2]),
                        int(an.comp_stats[k, 1] + an.comp_stats[k, 3])] for k in sorted(clef_ids)],
        "source_pixels_sha256": _pixels_sha(img),
        "patch_pixels_sha256": _pixels_sha(patch),
        "mask_sha256": hashlib.sha256(np.packbits(keep).tobytes() + str(keep.shape).encode()).hexdigest(),
        "masked_protected_px": int(masked.sum()),
        "time_signature": "never replicated",
        "kept_outside_staff_boxes": [_box_of(an, k) for k in kept],
        "_image": patch,
        "_clef_ids": sorted(clef_ids),
        "_kept_ids": kept,
        "_clef_end": cx1,
    }


# Ink wholly above the top staff line or below the bottom one (a section box such as [C], text like
# "h.h open", a lyric) that does not come within this many px of the clef's own pixels never blocks a
# clef replica or removal (user feedback 2026-10-07): it is not part of the clef, so it stays where it
# is and moves with its measure. Only the clef's own pixels are ever removed.
CLEF_OUTSIDE_INK_CLEARANCE_PX = 4  # DECLEF_DILATE_PX + 2


def _box_of(an: rb.StripAnalysis, k: int) -> List[int]:
    x, y, w, h, _a = (int(v) for v in an.comp_stats[k])
    return [x, y, x + w, y + h]


def _outside_staff_lines(an: rb.StripAnalysis, k: int) -> bool:
    """Component ``k`` lies wholly above the top staff line or wholly below the bottom one (it does not
    reach the line's own pixel rows)."""
    l = an.staff["lines"]
    half = an.staff["thick"] / 2.0 + 1.0
    _x, y, _w, h, _a = (int(v) for v in an.comp_stats[k])
    return y + h - 1 < l[0] - half or y > l[4] + half


def _kept_outside_ids(an: rb.StripAnalysis, clef_ids: Sequence[int]) -> List[int]:
    """Components outside the staff lines that reach the clef zone rows/columns (the analysis band at
    the system start) and are kept in place; checked not to touch the clef by ``clef_patch``."""
    g = an.gap
    xs = int(an.staff["x"][0])
    b0, b1 = an.band
    c1 = max(int(an.comp_stats[k, 0] + an.comp_stats[k, 2]) for k in clef_ids)
    x1 = min(an.comps.shape[1], int(np.ceil(c1 + 2.5 * g)))
    ids = {int(k) for k in np.unique(an.comps[b0:b1, xs:x1]) if k != 0} - set(clef_ids)
    return sorted(k for k in ids if _outside_staff_lines(an, k))


def prefix_ref(an: rb.StripAnalysis) -> Optional[Dict[str, Any]]:
    """Printed prefix at the system start: the clef box (detected geometric hint) and whether a
    verified clef-only patch can be replicated at a new line start (``clef_patch``)."""
    if an.staff is None:
        return None
    g = an.gap
    x0 = int(an.staff["x"][0])
    l = an.staff["lines"]
    clef_box = [x0, int(np.floor(l[1] - 1)), int(np.ceil(x0 + 2.5 * g)), int(np.ceil(l[3] + 2))] if an.clef else None
    cp = clef_patch(an)
    return {"clef_detected": bool(an.clef), "clef_box": clef_box, "time_signature_box": None, "verified": bool(cp["verified"]),
            "replicable": bool(cp["verified"]), "replica": {k: v for k, v in cp.items() if not k.startswith("_")},
            "note": "only a verified clef-only patch is replicated; time signatures are never synthesized or duplicated"}


DECLEF_DILATE_PX = 2  # the clef's anti-aliased fringe goes with it
DECLEF_RESIDUE_DELTA = 25  # a pixel this much darker than paper near the removed clef is residue
PREFIX_INK_REACH_GAPS = 1.0  # prefix ink (time signature, start repeat) starts this close to the first ink after the clef
PREFIX_INK_MIN_H_GAPS = 0.8
PREFIX_MAX_DIST_GAPS = 2.0  # printed prefix ink starts within this distance of the clef's end
PREFIX_INK_STAFF_TOL_GAPS = 0.3


def prefix_ink_after_clef(an: rb.StripAnalysis, clef_end: int, kept_ids: Sequence[int] = ()) -> Optional[Dict[str, Any]]:
    """Printed prefix ink right after the clef: a time signature (two stacked glyphs), a common-time
    sign or start repeat, anything glyph-high that stays within the staff lines and starts at the
    first ink after the clef. A note there has a stem or ledger outside the staff; a rest wholly
    inside the staff is reported too (doubtful, so no join). None when nothing prefix-like follows.
    ``kept_ids``: components outside the staff lines (``clef_patch``) that are not prefix ink."""
    g = an.gap
    l = an.staff["lines"]
    b0, b1 = an.band
    band = an.nonstaff[b0:b1] & ~np.isin(an.comps[b0:b1], list(kept_ids)) if len(kept_ids) else an.nonstaff[b0:b1]
    xe = int(an.staff["x"][1])
    x = int(clef_end)
    while x < min(band.shape[1], xe) and not band[:, x].any():
        x += 1
    if x >= min(band.shape[1], xe):
        return {"code": "NO_INK_AFTER_CLEF", "x": int(x)}
    if x - clef_end > PREFIX_MAX_DIST_GAPS * g:
        return None  # a time signature or start repeat follows the clef closely; ink this far is measure content
    reach = x + PREFIX_INK_REACH_GAPS * g
    lo, hi = l[0] - PREFIX_INK_STAFF_TOL_GAPS * g, l[4] + PREFIX_INK_STAFF_TOL_GAPS * g
    found = []
    for k in {int(v) for v in np.unique(an.comps[b0:b1, x:int(np.ceil(reach)) + 1]) if v != 0}:
        cx, cy, w, h, _a = (int(v) for v in an.comp_stats[k])
        if cx > reach or cx + w <= x:
            continue
        if cy >= lo and cy + h <= hi and h >= PREFIX_INK_MIN_H_GAPS * g:
            found.append([cx, cy, cx + w, cy + h])
    if not found:
        return None
    mid = l[2]
    upper = [b for b in found if b[3] <= mid + 0.3 * g]
    lower = [b for b in found if b[1] >= mid - 0.3 * g]
    # two stacked digits, or digits merged through the middle staff line into one wide glyph
    merged = [b for b in found if b[1] <= mid - 0.5 * g and b[3] >= mid + 0.5 * g and b[2] - b[0] >= 0.8 * g]
    code = "TIME_SIGNATURE" if (upper and lower) or merged else "PREFIX_INK_AFTER_CLEF"
    return {"code": code, "x": int(x), "boxes": found}


def declef_patch(an: rb.StripAnalysis) -> Dict[str, Any]:
    """Remove the system-start drum clef for a mid-line continuation, cleanly or not at all.

    Allowed only for a verified clef-only patch (``clef_patch``) with no prefix ink after it (no
    time signature, no start repeat). The clef components plus a ``DECLEF_DILATE_PX`` fringe are
    replaced by a staff reference column (the median of the clean staff-only columns next to the
    clef: paper and the five staff lines), so only paper and staff lines remain there. Checks:
    the fringe touches no other non-staff ink; the reference column is exactly five staff-line
    runs on paper; every changed pixel lies in the removal mask; every changed non-staff pixel
    belongs to the clef components; afterwards no protected ink and no residue darker than paper
    remains near the clef outside the staff lines. Returns ``{verified, reason?, ledger, _image}``."""
    out: Dict[str, Any] = {"verified": False}
    cp = clef_patch(an)
    if not cp.get("verified"):
        return dict(out, reason=cp.get("reason") or "CLEF_NOT_VERIFIED")
    g = an.gap
    l = an.staff["lines"]
    b0, b1 = an.band
    clef_ids = cp["_clef_ids"]
    kept_ids = list(cp.get("_kept_ids") or [])
    cx1 = int(cp["_clef_end"])
    pre = prefix_ink_after_clef(an, cx1, kept_ids)
    if pre is not None:
        return dict(out, reason=pre["code"], prefix_ink=pre)
    img = an.image
    h, w = img.shape[:2]
    clef = np.isin(an.comps, clef_ids)
    mask = cv2.dilate(clef.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=DECLEF_DILATE_PX).astype(bool)
    if (mask & an.nonstaff & ~clef).any():
        return dict(out, reason="CLEF_NEAR_INK")
    ys, xs_ = np.nonzero(mask)
    if ys.min() < b0 or ys.max() >= b1:
        return dict(out, reason="CLEF_OUTSIDE_STAFF_BAND")
    mx0, mx1 = int(xs_.min()), int(xs_.max()) + 1
    # staff reference: clean columns (no non-staff ink in the band, outside the removal mask) left of
    # the clef and in the clear run after it
    xs = int(an.staff["x"][0])
    nxt = cx1
    kept = np.isin(an.comps, kept_ids) if kept_ids else np.zeros_like(an.nonstaff)
    # kept ink outside the staff lines (a section box over the clef) is neither the next glyph nor a
    # reason to reject a staff reference column: those columns are taken in the staff rows only
    bandns = an.nonstaff[b0:b1] & ~kept[b0:b1]
    while nxt < w and not bandns[:, nxt].any():
        nxt += 1
    cand = list(range(xs, mx0)) + list(range(mx1, nxt))
    ref_cols = [c for c in cand if not bandns[:, c].any() and not mask[:, c].any()]
    if len(ref_cols) < 2:
        return dict(out, reason="NO_STAFF_REFERENCE")
    if img.ndim != 3:
        return dict(out, reason="UNSUPPORTED_IMAGE")
    ref = np.median(img[:, ref_cols].astype(np.float32), axis=1).round().astype(img.dtype)  # (h, 3)
    if kept_ids:
        # rows with kept outside ink in a reference column take the paper of the clean rows instead
        # (only rows inside the clef's removal mask are ever written, and those hold no kept ink)
        kept_rows = kept[:, ref_cols].any(axis=1)
        if kept_rows.any():
            clean = [c for c in ref_cols if not kept[:, c].any()]
            if len(clean) >= 2:
                ref[kept_rows] = np.median(img[:, clean].astype(np.float32), axis=1).round().astype(img.dtype)[kept_rows]
    inverted = bool(sd.normalize_polarity(img)[1])
    ref_gray = cv2.cvtColor(np.ascontiguousarray(ref[:, None, :]), cv2.COLOR_BGR2GRAY)[:, 0]
    if inverted:
        ref_gray = 255 - ref_gray
    paper = sd.percentile_u8(an.gray, 75)
    thr = min(float(rb.CONFIG["protect_max_gray"]), paper - float(rb.CONFIG["protect_delta"]))
    half = an.staff["thick"] / 2.0 + 1.5
    rows = np.arange(h)
    staff_rows = np.zeros(h, bool)
    for y in l:
        staff_rows |= np.abs(rows - y) <= half
    ink_rows = ref_gray < thr
    band_ink = ink_rows[b0:b1]
    runs = int(np.count_nonzero(band_ink[1:] & ~band_ink[:-1]) + int(band_ink[0]))
    if runs != 5 or (ink_rows & ~staff_rows)[b0:b1].any():
        return dict(out, reason="STAFF_REFERENCE_UNCLEAN", runs=runs)
    new = img.copy()
    my, mx = np.nonzero(mask)
    new[my, mx] = ref[my]
    changed = np.any(new != img, axis=-1)
    foreign = changed & ~mask
    removed_nonstaff = changed & an.nonstaff
    foreign_nonstaff = removed_nonstaff & ~clef
    gray_new = cv2.cvtColor(new, cv2.COLOR_BGR2GRAY)
    if inverted:
        gray_new = 255 - gray_new
    win = (slice(max(0, b0), b1), slice(max(0, mx0 - 2), min(w, mx1 + 2)))
    # kept outside ink (and its one-pixel fringe) is not residue: it is unchanged source ink
    kept_fringe = cv2.dilate(kept.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    off_staff = ~staff_rows[win[0]][:, None] & ~kept_fringe[win]
    residue_ink = (gray_new[win] < thr) & off_staff
    residue_faint = (gray_new[win].astype(np.int32) < int(paper) - DECLEF_RESIDUE_DELTA) & off_staff
    if foreign.any() or foreign_nonstaff.any():
        return dict(out, reason="CHANGE_OUTSIDE_CLEF")
    if residue_ink.any() or residue_faint.any():
        return dict(out, reason="CLEF_RESIDUE", residue_px=int(residue_faint.sum()))
    ledger = {
        "op": "remove_clef", "verified": True, "system_id": an.system_id, "coords": "native_strip",
        "clef_boxes": cp["clef_boxes"], "removal_box": [mx0, int(my.min()), mx1, int(my.max()) + 1],
        "clef_component_px": int(clef.sum()), "removal_mask_px": int(mask.sum()), "changed_px": int(changed.sum()),
        "removed_nonstaff_px": int(removed_nonstaff.sum()), "removed_nonstaff_not_clef_px": int(foreign_nonstaff.sum()),
        "changed_outside_mask_px": int(foreign.sum()), "residue_px": 0,
        "redrawn_staff_rows": int(np.count_nonzero(ink_rows[b0:b1])), "reference_columns": [int(ref_cols[0]), int(ref_cols[-1]) + 1],
        "reference_column_count": len(ref_cols), "next_ink_x": int(nxt),
        "mask_sha256": rb.mask_sha256(mask), "source_pixels_sha256": _pixels_sha(img), "declef_pixels_sha256": _pixels_sha(new),
        "kept": "every other pixel (time signature, tempo, labels, measure numbers, notes) is unchanged",
        "kept_outside_staff_boxes": cp.get("kept_outside_staff_boxes") or [],
    }
    return {"verified": True, "ledger": ledger, "_image": new, "_mask": mask, "_clef": clef, "_clef_end": cx1, "_next_ink": int(nxt)}


def _text_refs(an: rb.StripAnalysis, x0: int, x1: int) -> List[List[int]]:
    """Boxes of non-staff components entirely outside the staff-analysis band, owned by [x0, x1)."""
    if an.comp_stats is None:
        return []
    out = []
    for k in range(1, an.comp_stats.shape[0]):
        x, y, w, h, _a = (int(v) for v in an.comp_stats[k])
        if (y + h <= an.band[0] or y >= an.band[1]) and x0 <= x and x + w <= x1:
            out.append([x, y, x + w, y + h])
    return out


def _possible_multirest(an: rb.StripAnalysis, x0: int, x1: int) -> bool:
    if an.comp_stats is None or an.staff is None:
        return False
    g = an.gap
    mid = an.staff["lines"][2]
    for k in range(1, an.comp_stats.shape[0]):
        x, y, w, h, area = (int(v) for v in an.comp_stats[k])
        if x0 <= x and x + w <= x1 and w >= 2.0 * g and h >= 0.4 * g and y <= mid <= y + h and area >= 0.6 * w * h:
            return True
    return False


def _is_cut(b: Dict[str, Any]) -> bool:
    """Only SAFE boundaries are cuts. A boundary that a line, slur, hairpin or text crosses (LOCKED) or that
    could not be verified (UNKNOWN) is never cut and never a line break (the jump-only OVERSIZE_SPAN forced
    cut was reverted in STRATEGY Step 2A; a span wider than the page line becomes an oversize unit)."""
    return b["class"] == rb.SAFE


def system_units(an: rb.StripAnalysis, boundaries: List[Dict[str, Any]], *, occurrence_id: str,
                 asset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Split one strip at its SAFE boundaries; fills each boundary's unit adjacency in place."""
    h, w = an.image.shape[:2]
    cuts = sorted(b["seam_x"] for b in boundaries if _is_cut(b))
    edges = [0] + cuts + [w]
    units: List[Dict[str, Any]] = []
    staff = {"lines_y": an.staff["lines"], "gap": an.gap, "x": list(an.staff["x"])} if an.staff else None
    for i in range(len(edges) - 1):
        x0, x1 = int(edges[i]), int(edges[i + 1])
        inside = [b for b in boundaries if x0 < b["seam_x"] < x1 and not _is_cut(b)]
        if not cuts:
            kind = "system"
        elif inside:
            kind = "locked_group"
        else:
            kind = "measure"
        count: Optional[int] = None
        if kind == "measure" and not _possible_multirest(an, x0, x1):
            count = 1
        uid = f"{occurrence_id}/u{x0}"
        units.append({
            "id": uid,
            "kind": kind,
            "occurrence_id": occurrence_id,
            "owner_occurrence_id": occurrence_id,
            "system_id": an.system_id,
            "measure_count": count,
            "asset": asset,
            "box": [x0, 0, x1, h],
            "coords": "native_strip",
            "mask": {"type": "columns"},
            "staff": staff,
            "prefix": prefix_ref(an) if i == 0 else None,
            "text_refs": _text_refs(an, x0, x1),
            "label_refs": [],
            "left_boundary_id": next((b["id"] for b in boundaries if _is_cut(b) and b["seam_x"] == x0), None),
            "right_boundary_id": next((b["id"] for b in boundaries if _is_cut(b) and b["seam_x"] == x1), None),
            "internal_boundary_ids": [b["id"] for b in inside],
            "flags": (["POSSIBLE_MULTI_MEASURE_REST"] if kind == "measure" and count is None else []),
        })
    for b in boundaries:
        left = next(u for u in units if u["box"][0] < b["seam_x"] <= u["box"][2]) if b["seam_x"] > 0 else units[0]
        if _is_cut(b):
            right = next(u for u in units if u["box"][0] == b["seam_x"])
            b["left_unit_id"], b["right_unit_id"], b["is_cut"] = left["id"], right["id"], True
        else:
            b["left_unit_id"] = b["right_unit_id"] = left["id"]
            b["is_cut"] = False
    return units


def tail_units(system_id: str, occurrence_id: str, record: Dict[str, Any], uncut: np.ndarray,
               asset: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """A cut preview tail: the uncut asset splits at the LOCKED tail seam; the tail is owned by its destination."""
    b = rb.preview_tail_boundary(system_id, record, int(uncut.shape[1]))
    if b is None:
        return [], None
    h, w = uncut.shape[:2]
    s = int(np.clip(b["seam_x"], 0, w))
    rem = {"id": f"{occurrence_id}/uncut-rem", "kind": "uncut_remainder", "occurrence_id": occurrence_id,
           "owner_occurrence_id": occurrence_id, "system_id": system_id, "measure_count": None, "asset": asset,
           "box": [0, 0, s, h], "coords": "native_uncut_strip", "mask": {"type": "columns"}, "placed_via": "cut strip units",
           "staff": None, "prefix": None, "text_refs": [], "label_refs": [], "left_boundary_id": None,
           "right_boundary_id": b["id"], "internal_boundary_ids": [], "flags": []}
    tail = {"id": f"{occurrence_id}/tail", "kind": "preview_tail", "occurrence_id": occurrence_id,
            "owner_occurrence_id": b["owned_by"], "system_id": system_id, "measure_count": None, "asset": asset,
            "box": [s, 0, w, h], "coords": "native_uncut_strip", "mask": {"type": "columns"},
            "staff": None, "prefix": None, "text_refs": [], "label_refs": [], "left_boundary_id": b["id"],
            "right_boundary_id": None, "internal_boundary_ids": [], "flags": []}
    b["left_unit_id"], b["right_unit_id"], b["is_cut"] = rem["id"], tail["id"], True
    return [rem, tail], b


# --------------------------------------------------------------------------- #
# Locks
# --------------------------------------------------------------------------- #


def lock_conflicts(locks: Sequence[Dict[str, Any]], boundaries: Sequence[Dict[str, Any]],
                   units: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Structured conflicts; no precedence rule silently removes a user choice."""
    bmap = {b["id"]: b for b in boundaries}
    uorder = {u["id"]: i for i, u in enumerate(units)}
    out = []
    active = [l for l in locks if l.get("active", True)]
    for l in active:
        t = l.get("type")
        targets = list(l.get("targets") or [])
        if t not in LOCK_TYPES:
            out.append({"code": "UNKNOWN_LOCK_TYPE", "lock_ids": [l.get("id")], "target_ids": targets})
            continue
        if t in ("boundary_lock", "forced_line_break"):
            missing = [x for x in targets if x not in bmap]
            if missing or len(targets) != 1:
                out.append({"code": "STALE_LOCK_TARGET", "lock_ids": [l.get("id")], "target_ids": missing or targets})
                continue
            if t == "forced_line_break" and bmap[targets[0]]["class"] != rb.SAFE:
                out.append({"code": "UNSAFE_FORCED_BREAK", "lock_ids": [l.get("id")], "target_ids": targets,
                            "reason": bmap[targets[0]]["class"]})
        if t == "keep_together":
            missing = [x for x in targets if x not in uorder]
            if missing or len(targets) != 2:
                out.append({"code": "STALE_LOCK_TARGET", "lock_ids": [l.get("id")], "target_ids": missing or targets})
            elif uorder[targets[0]] > uorder[targets[1]]:
                out.append({"code": "KEEP_TOGETHER_ORDER", "lock_ids": [l.get("id")], "target_ids": targets})
    # a forced break on a boundary that a lock prohibits, or inside a keep_together range
    forced = {l["targets"][0]: l for l in active if l.get("type") == "forced_line_break" and l.get("targets")}
    for l in active:
        if l.get("type") == "boundary_lock" and l.get("targets") and l["targets"][0] in forced:
            out.append({"code": "CONTRADICTORY_LOCKS", "lock_ids": [l.get("id"), forced[l["targets"][0]].get("id")],
                        "target_ids": [l["targets"][0]]})
        if l.get("type") == "keep_together" and len(l.get("targets") or []) == 2 and all(x in uorder for x in l["targets"]):
            lo, hi = uorder[l["targets"][0]], uorder[l["targets"][1]]
            for bid, f in forced.items():
                b = bmap.get(bid)
                if b and b.get("right_unit_id") in uorder and lo < uorder[b["right_unit_id"]] <= hi:
                    out.append({"code": "CONTRADICTORY_LOCKS", "lock_ids": [l.get("id"), f.get("id")], "target_ids": [bid]})
    return out


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #


def build_document(*, job_id: str, revision: int, systems: Sequence[Dict[str, Any]], locks: Iterable[Dict[str, Any]] = (),
                   sources: Optional[Dict[str, Any]] = None, parent_revision: Optional[int] = None,
                   config: Dict[str, Any] = rb.CONFIG, analysis_cache: Optional[Dict[str, Any]] = None
                   ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``reflow_units.json`` for the given systems (video order).

    Each system: ``{system_id, included, image, record, observations?, uncut_image?, strip_path?}``.
    Returns (document, analyses by system id). ``analysis_cache`` (one compose call, same strips and
    locks): each strip's analysis and boundaries are computed once and reused."""
    locks = [dict(l) for l in locks or ()]
    included, excluded = [], []
    units: List[Dict[str, Any]] = []
    bounds: List[Dict[str, Any]] = []
    accounts: List[Dict[str, Any]] = []
    ownership: List[Dict[str, Any]] = []
    analyses: Dict[str, Any] = {}
    strip_hashes: Dict[str, str] = {}
    for s in systems:
        sid = s["system_id"]
        if not s.get("included", True) or ("-alt" in sid and not s.get("placed")):
            excluded.append(sid)
            continue
        included.append(sid)
        img = s["image"]
        rec = dict(s["record"], layout=s.get("layout", s["record"].get("layout")))
        if analysis_cache is not None and sid in analysis_cache:
            an, bl = analysis_cache[sid][0], copy.deepcopy(analysis_cache[sid][1])
        else:
            an = rb.analyse_strip(img, rec, system_id=sid, observations=s.get("observations"), config=config)
            bl = rb.strip_boundaries(an, locks=locks, config=config)
            if analysis_cache is not None:
                analysis_cache[sid] = (an, copy.deepcopy(bl))
        analyses[sid] = an
        asset = {"role": "strip", "path": s.get("strip_path"), "pixels_sha256": _pixels_sha(img), "size": [img.shape[1], img.shape[0]]}
        strip_hashes[sid] = asset["pixels_sha256"]
        us = system_units(an, bl, occurrence_id=sid, asset=asset)
        acc = ra.account_asset(img, us, an.protected, asset_sha256=asset["pixels_sha256"])
        acc["asset_role"], acc["system_id"] = "strip", sid
        accounts.append(acc)
        ownership.append({"system_id": sid, "asset": "strip", "owner_map_sha256": acc["owner_map_sha256"],
                          "unit_ids": [u["id"] for u in us]})
        units.extend(us)
        bounds.extend(bl)
        unc = s.get("uncut_image")
        if unc is not None and (rec.get("preview_tail") or {}).get("cut"):
            uasset = {"role": "uncut", "path": s.get("uncut_path"), "pixels_sha256": _pixels_sha(unc), "size": [unc.shape[1], unc.shape[0]]}
            tus, tb = tail_units(sid, sid, rec, unc, uasset)
            if tb is not None:
                ugray = cv2.cvtColor(sd.normalize_polarity(unc)[0], cv2.COLOR_BGR2GRAY)
                uacc = ra.account_asset(unc, tus, rb.protected_ink(ugray, config), asset_sha256=uasset["pixels_sha256"])
                uacc["asset_role"], uacc["system_id"] = "uncut", sid
                uacc["cut_strip_consistency"] = ra.cut_strip_consistency(img, unc, rec)
                accounts.append(uacc)
                ownership.append({"system_id": sid, "asset": "uncut", "owner_map_sha256": uacc["owner_map_sha256"],
                                  "unit_ids": [u["id"] for u in tus]})
                units.extend(tus)
                bounds.append(tb)
    conflicts = lock_conflicts(locks, bounds, [u for u in units if u["kind"] not in ("preview_tail", "uncut_remainder")])
    for l in locks:
        l.setdefault("active", True)
        l.setdefault("created_revision", revision)
    stats = {
        "boundaries": {c: sum(1 for b in bounds if b["class"] == c and b["kind"] == "barline") for c in rb.CLASSES},
        "units": {k: sum(1 for u in units if u["kind"] == k) for k in UNIT_KINDS},
        "measures_known": sum(u["measure_count"] or 0 for u in units if u["kind"] == "measure"),
        "units_with_unknown_count": sum(1 for u in units if u["kind"] in ("measure", "locked_group", "system") and u["measure_count"] is None),
    }
    content = {"boundaries": bounds, "units": [{k: v for k, v in u.items() if not k.startswith("_")} for u in units],
               "config_hash": rb.config_hash(config), "strips": strip_hashes, "sources": sources or {}, "locks": locks}
    doc = {
        "schema_version": UNITS_SCHEMA_VERSION,
        "kind": "reflow_units",
        "job_id": job_id,
        "revision": int(revision),
        "analysis_hash": _canon_sha(content),
        "algorithm": {"units": UNITS_VERSION, "boundaries": rb.BOUNDARIES_VERSION, "masks": rb.MASKS_VERSION,
                      "accounting": ra.ACCOUNTING_VERSION},
        "config_hash": rb.config_hash(config),
        "sources": dict(sources or {}, strips=strip_hashes),
        "included_occurrence_ids": included,
        "excluded_occurrence_ids": excluded,
        "measure_units": content["units"],
        "boundaries": bounds,
        "lines": [],
        "justification_slots": [],
        "locks": locks,
        "ragged_exceptions": [],
        "stats": stats,
        "audit": {
            "ownership": ownership,
            "replicas": [],
            "scaffold_operations": [],
            "accounting": {"totals": ra.totals(accounts), "assets": [{k: v for k, v in a.items() if k != "entries"} for a in accounts],
                           "ledger": [e for a in accounts for e in a["entries"]]},
            "conflicts": conflicts,
            "validation": {},
            "parent_revision": parent_revision,
        },
    }
    errors = validate_document(doc)
    doc["audit"]["validation"] = {"status": "valid" if not errors else "invalid", "errors": errors}
    return doc, analyses


def validate_document(doc: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    for f in ROOT_FIELDS:
        if f not in doc:
            errs.append(f"missing root field {f}")
    if errs:
        return errs
    if doc["schema_version"] != UNITS_SCHEMA_VERSION:
        errs.append("schema_version")
    units = doc["measure_units"]
    ids = [u["id"] for u in units]
    if len(ids) != len(set(ids)):
        errs.append("duplicate unit ids")
    bids = [b["id"] for b in doc["boundaries"]]
    if len(bids) != len(set(bids)):
        errs.append("duplicate boundary ids")
    umap = {u["id"]: u for u in units}
    excluded = set(doc["excluded_occurrence_ids"])
    for u in units:
        if u["kind"] not in UNIT_KINDS:
            errs.append(f"{u['id']}: kind {u['kind']}")
        mc = u.get("measure_count")
        if mc is not None and (not isinstance(mc, int) or mc < 1):
            errs.append(f"{u['id']}: measure_count")
        x0, y0, x1, y1 = u["box"]
        sw, sh = u["asset"]["size"]
        if not (0 <= x0 < x1 <= sw and 0 <= y0 < y1 <= sh):
            errs.append(f"{u['id']}: box outside asset")
        if u["occurrence_id"] in excluded:
            errs.append(f"{u['id']}: unit of an excluded occurrence")
    # per asset: units partition the columns exactly (column masks)
    by_asset: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for u in units:
        by_asset.setdefault((u["occurrence_id"], u["asset"]["pixels_sha256"]), []).append(u)
    for key, us in by_asset.items():
        us = sorted(us, key=lambda u: u["box"][0])
        sw, sh = us[0]["asset"]["size"]
        if us[0]["box"][0] != 0 or us[-1]["box"][2] != sw:
            errs.append(f"{key[0]}: units do not cover the asset")
        for a, b in zip(us, us[1:]):
            if a["box"][2] != b["box"][0]:
                errs.append(f"{a['id']}|{b['id']}: gap or overlap")
        if any(u["box"][1] != 0 or u["box"][3] != sh for u in us):
            errs.append(f"{key[0]}: column units must span the asset height")
    for b in doc["boundaries"]:
        if b["class"] not in rb.CLASSES:
            errs.append(f"{b['id']}: class")
        lu, ru = umap.get(b.get("left_unit_id")), umap.get(b.get("right_unit_id"))
        if lu is None or ru is None:
            errs.append(f"{b['id']}: adjacent units missing")
            continue
        if b.get("is_cut"):
            if b["class"] == rb.UNKNOWN or (b["class"] == rb.LOCKED and b["kind"] != "preview_tail"):
                errs.append(f"{b['id']}: cut at a non-SAFE boundary")
            if lu["box"][2] != b["seam_x"] or ru["box"][0] != b["seam_x"]:
                errs.append(f"{b['id']}: seam is not the unit edge")
        else:
            if b["class"] == rb.SAFE:
                errs.append(f"{b['id']}: SAFE boundary not cut")
            if lu is not ru:
                errs.append(f"{b['id']}: uncut boundary between two units")
    tot = doc["audit"]["accounting"]["totals"]
    if tot.get("lost_px") or tot.get("duplicated_px") or not tot.get("exact_reconstruction", False):
        errs.append("pixel accounting failed")
    for k in ("lines", "justification_slots", "ragged_exceptions", "locks"):
        if not isinstance(doc[k], list):
            errs.append(f"{k} must be a list")
    return errs
