"""Measure-level reflow composition (MEASURE_BRIEF milestone 2), behind an option that is off by default.

Runs after dependency resolution (``reflow_pipeline.resolve_dependencies``) and before label
placement and page layout:

1. every placed system's cleaned strip (the variant the dependencies chose) is analysed and split
   at SAFE boundaries, or explicitly recorded crossing-only barlines to meet the printed size floor
   (``reflow_units.build_document``: measure / locked-group / whole-system
   units, native pixel ledger with exact split-and-reassemble);
2. units become line atoms in placed order, at the output scale (one isotropic resampling per
   strip to the document staff gap); paper margins outside the staff and ink are trimmed;
3. ``reflow_lines.plan_document`` breaks lines (a source-system start keeps its printed prefix
   when it starts a line; a cut inside a system starts a line only with a verified clef-only
   replica; a system may continue the previous line after endpoint checks when it is prefix-free
   or its repeated drum clef can be removed cleanly - ``reflow_units.declef_patch``: verified
   clef-only patch, no time signature or other prefix ink after it, only paper and staff lines
   left, every change inside the clef's mask, recorded in ``audit.clef_removals``) and justifies
   them by whitespace only;
4. each line is rendered: atoms keep their glyph pixels exactly (the resampled strip's pixels);
   justification is spread over the barline corridors and every eligible gap between note/rest
   columns inside the measures (``spread_gaps``: columns whose ink continues unchanged 2 px to each
   side - staff lines, and beams only where level from stem to stem); expansion repeats such a
   column, contraction removes such columns, each recorded (``reconstruct_atom`` undoes them); section-label patches go in outlined boxes
   above the measure where their section starts (mid-line when that measure is mid-line);
5. lines are paginated by ``reflow_layout.plan_pages`` (scale 1) and rendered by ``reflow_render``.

When the measure plan is not feasible (an atom wider than the line, an unusable record) the
caller falls back to whole-system composition and reports why. Nothing is clipped, stretched or
shrunk; time signatures are never synthesized or duplicated.

Ledger frames
-------------
S is the final written strip PNG (the chunk PNG for jump chunks); R is the
resampled strip in strips[_sk(a)], after pre_crop; L is images[line_id]; P is
the A4 300 dpi raster returned by rr.render_pages. Boxes are half-open and
matrices map pixel centres. Margin/row cuts select R domains, not S origins.
A clef replica has its own resampled patch R; its native source-box origin is
the pre_crop, and its separate copy_index never copies the system's other ink.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_ledger as ledger_api
from app.pipeline import reflow_lines as rlines
from app.pipeline import reflow_render as rr
from app.pipeline import reflow_units as ru
from app.pipeline import system_detect as sd
from app.pipeline.process_control import report_progress

MEASURE_VERSION = "reflow_measure-3"  # 2: staff-size floor, forced breaks at stroke-only barlines; 3: a line whose overhang ink would cross the page margin is not justified to the edge (reflow_lines-5)
LABEL_PAD_GAPS = 0.3  # padding inside a drawn outline box
LABEL_SEP_GAPS = 0.4  # space between the label box and the line content below it
OUTLINE_PX = 3  # ~0.25 mm at 300 dpi


class MeasurePlanUnavailable(RuntimeError):
    """The measure plan cannot be made; the caller composes whole systems instead."""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(reason)


def load_context(workspace: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Manifest + occurrences of a job workspace (read-only), for barline registration."""
    if workspace is None:
        return None
    try:
        manifest = json.loads((Path(workspace) / "manifest.json").read_text(encoding="utf-8"))
        occ = json.loads((Path(workspace) / "occurrences.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    return {"manifest": manifest, "occurrences": occ}


def _analysis_record(s: Dict[str, Any], variant: str) -> Dict[str, Any]:
    """The strip record in the coordinates of the image actually placed. For the uncut variant
    (a preview tail restored on its source strip) the record moves to the uncut box and its tail
    becomes an unresolved (not cut) tail, so seams near it stay UNKNOWN."""
    rec = dict(s.get("strip") or {}, layout=s.get("layout"))
    if variant != "uncut":
        return rec
    unc = rec.get("uncut") or {}
    box, ubox = rec.get("box_crop") or [0, 0, 0, 0], unc.get("box_crop") or rec.get("box_crop") or [0, 0, 0, 0]
    dy, dx = int(box[1]) - int(ubox[1]), int(box[0]) - int(ubox[0])
    out = dict(rec, box_crop=list(ubox), size=list(unc.get("size") or rec.get("size") or []))
    if rec.get("staff_y_strip"):
        out["staff_y_strip"] = [float(y) + dy for y in rec["staff_y_strip"]]
    if rec.get("staff_x_strip"):
        out["staff_x_strip"] = [int(x) + dx for x in rec["staff_x_strip"]]
    if rec.get("uncertain_marks"):
        out["uncertain_marks"] = [dict(m, bbox=[m["bbox"][0]+dx, m["bbox"][1]+dy,
                                                m["bbox"][2]+dx, m["bbox"][3]+dy])
                                  if m.get("bbox") else dict(m) for m in rec["uncertain_marks"]]
    tail = dict(rec.get("preview_tail") or {})
    if tail:
        tail["cut"] = False
        out["preview_tail"] = tail
    out["uncut"] = None
    return out


def _clear_run(cols_clear: np.ndarray, x: int) -> Tuple[int, int]:
    """Half-open run of clear columns containing column ``x`` (empty when ``x`` is not clear)."""
    w = len(cols_clear)
    if not (0 <= x < w) or not cols_clear[x]:
        return x, x
    a = x
    while a > 0 and cols_clear[a - 1]:
        a -= 1
    b = x
    while b < w and cols_clear[b]:
        b += 1
    return a, b


def _resampled(img: np.ndarray, scale: float) -> np.ndarray:
    w = max(1, int(round(img.shape[1] * scale)))
    h = max(1, int(round(img.shape[0] * scale)))
    return rr.resize_strip(rr._to_page_paper(img), w, h)


def _influence(mask: np.ndarray, w: int, h: int) -> np.ndarray:
    """Output pixels reached by any native ``mask`` pixel (area resampling, then any > 0), dilated by 1."""
    m = cv2.resize(mask.astype(np.uint8) * 255, (w, h), interpolation=cv2.INTER_AREA if w < mask.shape[1] else cv2.INTER_LINEAR)
    return cv2.dilate((m > 0).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)


def _has_frame(patch: np.ndarray) -> bool:
    """A source label patch that already draws its own box (a frame component around the text)."""
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.ndim == 3 else patch
    ink = gray < 128
    if not ink.any():
        return False
    ys, xs = np.nonzero(ink)
    bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    n, lab, stats, _c = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    for k in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[k])
        if w >= 0.9 * (bx1 - bx0) and h >= 0.9 * (by1 - by0) and w >= 6 and h >= 6:
            comp = lab[y:y + h, x:x + w] == k
            border = np.zeros_like(comp)
            t = max(2, int(round(0.12 * min(w, h))))
            border[:t], border[-t:], border[:, :t], border[:, -t:] = True, True, True, True
            if (comp & border).sum() >= 0.8 * comp.sum():
                return True
    return False


def boxed_label(patch: np.ndarray, scale: float, gap_out: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The label patch at the output scale in an outlined box. A patch with its own source box is
    kept as it is; otherwise only an outline is added around it (the text is never retyped)."""
    w = max(1, int(round(patch.shape[1] * scale)))
    h = max(1, int(round(patch.shape[0] * scale)))
    p = rr.resize_strip(patch, w, h)
    if _has_frame(patch):
        return p, {"outline": "source_box"}
    pad = max(2, int(round(LABEL_PAD_GAPS * gap_out)))
    out = np.full((h + 2 * (pad + OUTLINE_PX), w + 2 * (pad + OUTLINE_PX), 3), 255, np.uint8)
    out[pad + OUTLINE_PX:pad + OUTLINE_PX + h, pad + OUTLINE_PX:pad + OUTLINE_PX + w] = p
    cv2.rectangle(out, (0, 0), (out.shape[1] - 1, out.shape[0] - 1), (25, 25, 25), OUTLINE_PX)
    return out, {"outline": "drawn", "pad_px": pad, "outline_px": OUTLINE_PX}


def _prefix_free(an: rb.StripAnalysis) -> bool:
    """Positive evidence of no printed prefix: no clef and no non-staff ink in the first 2 gaps of the staff band."""
    if an.staff is None or an.clef:
        return False
    if ((an.record or {}).get("jump") or {}).get("no_clef_copy"):
        # a jump-view panorama strip of a run without a verified clef to copy: its lines start bare
        return True
    xs = int(an.staff["x"][0])
    return not an.nonstaff[an.band[0]:an.band[1], xs:int(xs + 2 * an.gap)].any()


def _ends_at_barline(an: rb.StripAnalysis) -> bool:
    if an.staff is None or not an.bars:
        return False
    xe = int(an.staff["x"][1])
    return any(abs(int(b["x1"]) - xe) <= an.gap for b in an.bars)


OVERSIZE_FILL = 0.97  # an oversize unit is scaled to this share of the printable line (justification fills the rest)
JOIN_LEAD_DEFAULT_GAPS = 1.2  # barline-to-first-ink space after a removed clef, when the source shows none
JOIN_LEAD_MIN_GAPS, JOIN_LEAD_MAX_GAPS = 0.8, 2.0
JOIN_LEAD_SEARCH_GAPS = 2.5  # the lead after a removed clef ends at the first ink within this distance of the clef end


def number_over_barline(an: rb.StripAnalysis, seam: int) -> Optional[Dict[str, Any]]:
    """Jump-view strips: the measure number printed over the barline left of ``seam`` (the seam proposal
    keeps it with the left unit; reflow_boundaries.propose). It labels the measure right of the barline,
    so when a line starts at this seam the number moves to that line's start (``render_lines``).
    Returns its native box when it is only number glyphs and paper, clear of the staff; else a reason."""
    if an.staff is None or an.comps is None:
        return None
    g = an.gap
    bars = [b for b in an.bars if int(b["x1"]) < seam and seam - int(b["x1"]) <= rb.CONFIG["max_corridor_gaps"] * g]
    if not bars:
        return None
    b = max(bars, key=lambda bb: int(bb["x1"]))
    x1 = int(b["x1"])
    st = an.comp_stats
    lo = max(0, x1 - int(np.ceil(rb.CONFIG["number_skip_gaps"] * g)))
    cands = [int(k) for k in np.unique(an.comps[:, lo:seam]) if k != 0 and rb._number_like(an, int(k))
             and int(st[int(k), 0]) >= lo and int(st[int(k), 0] + st[int(k), 2]) <= seam]
    # the digits next to the barline (as in propose), then the digits adjoining them (a number centred
    # over the barline has digits on both sides of it)
    nums = [k for k in cands if x1 - 0.5 * g <= int(st[k, 0]) <= x1 + g or int(st[k, 0]) <= x1 < int(st[k, 0] + st[k, 2])]
    grown = True
    while nums and grown:
        grown = False
        a0 = min(int(st[k, 0]) for k in nums)
        a1 = max(int(st[k, 0] + st[k, 2]) for k in nums)
        r0 = min(int(st[k, 1]) for k in nums)
        r1 = max(int(st[k, 1] + st[k, 3]) for k in nums)
        for k in cands:
            if k in nums:
                continue
            kx0, kx1 = int(st[k, 0]), int(st[k, 0] + st[k, 2])
            ky0, ky1 = int(st[k, 1]), int(st[k, 1] + st[k, 3])
            if kx1 >= a0 - 0.5 * g and kx0 <= a1 + 0.5 * g and ky0 < r1 and ky1 > r0:
                nums.append(k)
                grown = True
    if not nums:
        return None
    bx0 = min(int(st[k, 0]) for k in nums) - 1
    by0 = min(int(st[k, 1]) for k in nums) - 1
    bx1 = max(int(st[k, 0] + st[k, 2]) for k in nums) + 1
    by1 = max(int(st[k, 1] + st[k, 3]) for k in nums) + 1
    staff_top = float(an.staff["lines"][0]) - 0.5 * float(an.staff["thick"])
    if by1 > staff_top - 1:
        return {"refused": "NUMBER_TOUCHES_STAFF"}
    bx0, by0 = max(0, bx0), max(0, by0)
    bx1 = min(an.comps.shape[1], bx1, seam)
    others = set(int(k) for k in np.unique(an.comps[by0:by1, bx0:bx1])) - {0} - set(nums)
    if others or an.scaffold[by0:by1, bx0:bx1].any():
        return {"refused": "OTHER_INK_NEAR_NUMBER"}
    return {"native_box": [bx0, by0, bx1, by1], "components": len(nums)}


def _measure_lead_native(an: rb.StripAnalysis) -> float:
    """Typical space from an internal barline to the first ink of its measure (median, native px),
    so a joined system starts like any other measure."""
    g = an.gap
    xs, xe = an.staff["x"]
    b0, b1 = an.band
    band = an.comps[b0:b1]
    vals = []
    for b in an.bars:
        x0, x1 = int(b["x0"]), int(b["x1"])
        if x0 - xs <= 6 * g or xe - x1 <= g:
            continue
        own = rb._group_labels(an, b)
        x = x1 + 1
        while x < min(band.shape[1], x1 + 4 * g):
            ids = {int(k) for k in np.unique(band[:, x]) if k != 0}
            if ids and not ids <= own:
                break
            x += 1
        vals.append(x - x1 - 1)
    lead = float(np.median(vals)) if vals else JOIN_LEAD_DEFAULT_GAPS * g
    return float(np.clip(lead, JOIN_LEAD_MIN_GAPS * g, JOIN_LEAD_MAX_GAPS * g))


FRAME_EDGE_DELTA = 8  # a strip's outermost column this much darker than paper (outside ink) is the source frame's edge


def frame_edge_cleanup(img: np.ndarray, an: rb.StripAnalysis) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Set the unprotected pixels of a strip's first/last column to paper when that column is a faint
    full-height line (the edge of the video frame or ROI, e.g. where the final barline meets the frame
    edge). Protected ink (staff lines, the barline itself, anti-aliased fringes) is never touched; a
    mid-line join would otherwise show the edge as a faint barline extension."""
    h, w = img.shape[:2]
    paper_g = float(sd.percentile_u8(an.gray, 75))
    unprot = ~an.protected
    if not unprot.any():
        return img, []
    paper = np.median(img[unprot].reshape(-1, img.shape[2]), axis=0).round().astype(img.dtype)
    out, ops = img, []
    for c in sorted({0, w - 1}):
        rows = unprot[:, c]
        if rows.sum() < 0.5 * h or float(np.median(an.gray[rows, c])) >= paper_g - FRAME_EDGE_DELTA:
            continue
        if out is img:
            out = img.copy()
        out[rows, c] = paper
        ops.append({"op": "frame_edge_to_paper", "system_id": an.system_id, "native_col": int(c), "pixels": int(rows.sum()),
                    "protected_px": 0, "column_median_gray": float(np.median(an.gray[rows, c])), "paper_gray": paper_g})
    return out, ops


def _declef_join(an: rb.StripAnalysis, R: np.ndarray, scale: float, X0: int, X1: int) -> Dict[str, Any]:
    """Join data for a system whose clef may be removed when it continues mid-line (DECISIONS
    "Joining systems"): the declef strip at the output scale, and the lead columns that may be
    dropped (output columns no non-staff ink reaches, between the removed clef and the first
    ink after it) so the joined measure starts like any other. Anything doubtful: no join."""
    dc = ru.declef_patch(an)
    if not dc.get("verified"):
        det = {k: v for k, v in dc.items() if k in ("component_boxes", "other_components", "clef_components", "clear_px", "runs",
                                                    "residue_px", "prefix_ink")}
        return {"ok": False, "reason": dc.get("reason"), "detail": det or None}
    H, W = R.shape[:2]
    RD = _resampled(frame_edge_cleanup(dc["_image"], an)[0], scale)
    if RD.shape != R.shape:
        return {"ok": False, "reason": "DECLEF_SHAPE"}
    changed = np.any(RD != R, axis=-1)
    outside = changed & ~_influence(dc["_mask"], W, H)
    if outside.any():
        return {"ok": False, "reason": "RESAMPLED_CHANGE_OUTSIDE_CLEF", "px": int(outside.sum())}
    ns_out = _influence(an.nonstaff & ~dc["_clef"], W, H)
    clear = ~ns_out.any(axis=0)
    g_out = an.gap * scale
    c1 = int(np.ceil(dc["_clef_end"] * scale))
    cap = min(X1, c1 + int(np.ceil(JOIN_LEAD_SEARCH_GAPS * g_out)))
    xn = c1
    while xn < cap and clear[xn]:
        xn += 1
    if xn <= X0:
        return {"ok": False, "reason": "NO_LEAD"}
    lead = int(round(_measure_lead_native(an) * scale))
    cols = [c for c in range(X0, xn) if clear[c]]
    visual = xn - X0
    trim = int(min(len(cols), max(0, visual - lead)))
    natural = visual - trim
    e_cap, c_cap = rlines.slot_caps(natural, g_out)
    slot = {"natural": float(natural), "max_expand": float(min(e_cap, trim)), "max_contract": float(min(c_cap, len(cols) - trim)),
            "max_expand_wide": float(min(max(e_cap, rlines.wide_grow_cap(natural, g_out)), trim)),
            "max_expand_free": float(min(max(e_cap, rlines.wide_grow_cap(natural, g_out)), trim)),  # only dropped columns come back
            "evidence": "lead columns after a removed clef that no non-staff ink reaches"}
    return {"ok": True, "image": RD, "nonstaff_out": ns_out, "trim": trim, "clear_cols": sorted(cols),
            "lead_out": [int(X0), int(xn)], "lead_target_px": lead, "slot": slot, "ledger": dc["ledger"],
            "ledger_changed_boxes": _mask_rectangles(changed),
            "resampled_changed_px": int(changed.sum()), "resampled_changed_outside_clef_px": 0}


# Spread justification (DECISIONS "Spread justification"): whitespace is inserted into / removed from
# every eligible gap between note/rest columns, not only at barlines. A column is eligible when its
# ink (any pixel darker than SPREAD_INK_GRAY) is exactly the same on the SPREAD_MARGIN_PX columns to
# each side: only horizontal runs that continue unchanged (staff lines; a beam only when it runs
# straight and level from stem to stem). Noteheads, stems, flags, dots, text glyphs, slurs and ties
# all change the column within 2 px, so they are never touched.
SPREAD_INK_GRAY = 200  # output-scale binarisation for column signatures (catches anti-aliased fringes)
SPREAD_MARGIN_PX = 2  # ink may not start, end or change thickness within this many px of an eligible column
SPREAD_MIN_GAP_GAPS = 0.6  # narrower gaps (notehead to dot, grace notes, letter spacing) are left alone
SPREAD_STEM_GAPS = 1.5  # a vertical run at least this long (stem, barline, bracket hook) ends a beam
SPREAD_BEAM_SCAN_GAPS = 4.0  # a beam must reach such a run on both sides within this distance
SPREAD_BEAM_MAX_GAPS = 0.9  # each band of non-staff ink in a beam column is at most this thick (a beam, not a blob)
SPREAD_PREFIX_GUARD_GAPS = 6.0  # no spread gaps in the printed prefix (clef, time signature) of a system start


def _ink_signature(img: np.ndarray) -> np.ndarray:
    gray = img.min(axis=2) if img.ndim == 3 else img
    return gray < SPREAD_INK_GRAY


def _has_vertical_run(col: np.ndarray, rows: np.ndarray, min_len: float) -> bool:
    """A contiguous ink run of at least ``min_len`` px in ``col`` that touches one of ``rows`` (±1)."""
    if not col.any():
        return False
    d = np.diff(np.r_[0, col.astype(np.int8), 0])
    starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    ys = np.nonzero(rows)[0]
    for a, b in zip(starts, ends):
        if b - a >= min_len and ((ys >= a - 1) & (ys <= b)).any():
            return True
    return False


def _beam_reaches_stems(ink: np.ndarray, rows: np.ndarray, a: int, b: int, gap_out: float) -> bool:
    """The non-staff rows ``rows`` of an eligible run [a, b) (a beam) continue unchanged, level, on
    both sides until a stem-like vertical run crosses them (within SPREAD_BEAM_SCAN_GAPS)."""
    scan = int(np.ceil(SPREAD_BEAM_SCAN_GAPS * gap_out))
    min_len = SPREAD_STEM_GAPS * gap_out
    d = np.diff(np.r_[0, rows.astype(np.int8), 0])
    bands = np.nonzero(d == -1)[0] - np.nonzero(d == 1)[0]
    if bands.max() > SPREAD_BEAM_MAX_GAPS * gap_out:
        return False  # a solid block (a streak, a smear) is not a beam
    # the crossing run must be longer than the beam bands it crosses (a stem, not the block's own edge)
    min_len = max(min_len, float(rows.sum()) + gap_out)
    w = ink.shape[1]
    for step, x in ((-1, a - 1), (1, b)):
        ok = False
        for _k in range(scan):
            if not (0 <= x < w) or not ink[rows, x].all():
                break
            if _has_vertical_run(ink[:, x], rows, min_len):
                ok = True
                break
            x += step
        if not ok:
            return False
    return True


def column_eligible(img: np.ndarray, c: int) -> bool:
    """Ink of column ``c`` is the same on SPREAD_MARGIN_PX columns to each side (a recheck at render time)."""
    m = SPREAD_MARGIN_PX
    if c - m < 0 or c + m >= img.shape[1]:
        return False
    ink = _ink_signature(img[:, c - m:c + m + 1])
    return bool(np.all(ink == ink[:, m:m + 1]))


def spread_gaps(img: np.ndarray, staff_rows: np.ndarray, gap_out: float, x0: int, x1: int, *, guard_x: Optional[int] = None,
                id_prefix: str = "gap") -> List[Dict[str, Any]]:
    """Eligible spread gaps of the output-scale strip ``img`` between columns [x0, x1).

    A gap is a maximal run of eligible columns (see SPREAD_*) that does not touch [x0, x1)'s ends
    (those are barline corridors or line ends), lies right of ``guard_x`` and is at least
    SPREAD_MIN_GAP_GAPS wide counting its 2-px margins (the natural width). A run that carries
    non-staff ink is a gap only when that ink is a level beam reaching stems on both sides. Caps
    follow ``reflow_lines.slot_caps``; contraction removes only the run's own columns."""
    x0, x1 = max(0, int(x0)), min(img.shape[1], int(x1))
    m = SPREAD_MARGIN_PX
    if x1 - x0 <= 2 * m + 2:
        return []
    ink = _ink_signature(img[:, x0:x1])
    w = ink.shape[1]
    same = np.all(ink[:, 1:] == ink[:, :-1], axis=0)  # same[c]: column c equals column c + 1
    win = np.convolve(same.astype(np.int32), np.ones(2 * m, np.int32), mode="valid")  # same[c-m .. c+m-1]
    elig = np.zeros(w, bool)
    elig[m:m + len(win)] = win == 2 * m
    d = np.diff(np.r_[0, elig.astype(np.int8), 0])
    out: List[Dict[str, Any]] = []
    for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
        a, b = int(a), int(b)
        if a - m <= 0 or b + m >= w:
            continue  # touches the atom's end: a corridor or line end, not a gap between columns
        natural = (b - a) + 2 * m
        if natural < SPREAD_MIN_GAP_GAPS * gap_out:
            continue
        if guard_x is not None and x0 + a - m < guard_x:
            continue
        nonstaff_rows = ink[:, a] & ~staff_rows
        kind = "staff_only"
        if nonstaff_rows.any():
            if not _beam_reaches_stems(ink, nonstaff_rows, a, b, gap_out):
                continue
            kind = "level_beam"
        e, c = rlines.slot_caps(natural, gap_out)
        out.append({"id": f"{id_prefix}-{len(out)}", "kind": "spread", "column_kind": kind, "natural": float(natural),
                    "max_expand": float(e), "max_contract": float(min(c, b - a)), "run_out": [x0 + a, x0 + b],
                    "max_expand_wide": float(max(e, rlines.wide_grow_cap(natural, gap_out))),
                    "max_contract_wide": float(min(max(c, rlines.wide_shrink_cap(natural, gap_out)), b - a)),
                    "col_out": x0 + (a + b) // 2})
    return out


def _staff_rows_out(an: rb.StripAnalysis, rec: Dict[str, Any], scale: float, h: int) -> np.ndarray:
    rows = np.zeros(h, bool)
    if an.staff is None:
        return rows
    ys = rec.get("staff_y_strip") or an.staff["lines"]
    half = an.staff["thick"] * scale / 2.0 + 1.5
    r = np.arange(h)
    for y in ys:
        rows |= np.abs(r - float(y) * scale) <= half
    return rows


def _tail_clear_columns(img: np.ndarray, nonstaff: np.ndarray, x0: int, x1: int) -> int:
    """Trailing scaffold, including paper reached only by a dilated ink mask."""
    a = max(0, x0)
    clear = ~nonstaff[:, a:x1].any(axis=0)
    # The page paper mapping makes these columns completely white. A barline's
    # influence halo can reach them after fractional-scale edge resampling.
    clear |= np.all(img[:, a:x1] >= 252, axis=(0, 2))
    blocked = np.flatnonzero(~clear)
    n = len(clear) - int(blocked[-1]) - 1 if len(blocked) else len(clear)
    return int(min(n, max(0, x1 - x0 - 1)))


def _unit_rows(ink_rows: np.ndarray, nonstaff_out: np.ndarray, staff_rows: np.ndarray, X0: int, X1: int) -> List[int]:
    """Output rows [r0, r1) a unit needs on its line: the rows its own ink (and the staff) reaches, plus
    the strip's own paper padding above its highest and below its lowest ink. Rows outside hold only
    paper in the unit's columns, so a measure without the system's tallest mark does not make every
    line it shares as tall as that mark (a system split over two lines is not counted twice)."""
    H = len(ink_rows)
    ys = np.nonzero(ink_rows)[0]
    if len(ys) == 0:
        return [0, H]
    pad_top, pad_bot = int(ys[0]), int(H - 1 - ys[-1])
    X0, X1 = max(0, int(X0)), min(nonstaff_out.shape[1], int(X1))
    own = (nonstaff_out[:, X0:X1].any(axis=1) if X1 > X0 else np.zeros(H, bool)) | staff_rows
    ya = np.nonzero(own)[0]
    if len(ya) == 0:
        return [0, H]
    return [max(0, int(ya[0]) - pad_top), min(H, int(ya[-1]) + 1 + pad_bot)]


def build_atoms(decided: Sequence[Dict[str, Any]], *, target_gap_px: float, context: Optional[Dict[str, Any]],
                locks: Iterable[Dict[str, Any]] = (), job_id: str = "job", revision: int = 0,
                line_width: Optional[int] = None, doc_cache: Optional[Dict[Any, Any]] = None,
                floor_break_ids: Sequence[str] = ()) -> Dict[str, Any]:
    """Units of the placed systems (``decided`` from resolve_dependencies) as line atoms at the output scale.

    ``line_width`` (the printable line): in a jump-view panorama strip, a unit that does not fit it even
    fully contracted (a measure wider than the page line) gets a line of its own at a smaller scale
    (``OVERSIZE_FILL`` of the line, recorded as ``oversize``). If that would fall below the staff-size
    floor, eligible crossing-only barlines split it with exact pixel accounting; remaining small
    output gets a review finding. Page strips keep
    the layout-conflict rule (the user chooses a staff size or excludes the system).

    ``doc_cache`` (the staff-size search in ``compose``): the units document does not depend on the
    output scale, so it is analysed once and reused across sizes."""
    obs_by = {o["id"]: o for o in ((context or {}).get("manifest") or {}).get("observations", [])}
    occ_by = {s["id"]: s for s in ((context or {}).get("occurrences") or {}).get("systems", [])}
    systems = []
    images: Dict[str, np.ndarray] = {}
    recs: Dict[str, Dict[str, Any]] = {}
    for d in decided:
        s = d["system"]
        img = cv2.imread(str(d["strip_path"]))
        if img is None:
            raise MeasurePlanUnavailable("STRIP_UNREADABLE", {"system_id": s["id"], "path": str(d["strip_path"])})
        rec = _analysis_record(s, d["variant"])
        manifest = (context or {}).get("manifest")
        if manifest:
            rec["frame_edges"] = rb.strip_frame_edges(rec, manifest)
        obs = rb.member_regions(rec, occ_by.get(s["id"]), obs_by) if context else None
        images[s["id"]] = img
        recs[s["id"]] = rec
        # units split only at SAFE boundaries; a span wider than the page line becomes an oversize unit below
        systems.append({"system_id": s["id"], "included": True, "placed": True, "image": img, "record": rec,
                        "observations": obs, "layout": s.get("layout"), "strip_path": str(d["strip_path"])})
    locks = list(locks)
    key = (job_id, revision, tuple(x["system_id"] for x in systems))
    if floor_break_ids:
        key += (tuple(sorted(floor_break_ids)),)
    if doc_cache is not None and key in doc_cache:
        doc, analyses = doc_cache[key]
    else:
        doc, analyses = ru.build_document(job_id=job_id, revision=revision, systems=systems, locks=locks,
                                          analysis_cache=doc_cache.setdefault("analyses", {}) if doc_cache is not None else None,
                                          floor_break_ids=floor_break_ids)
        if doc_cache is not None:
            doc_cache[key] = (doc, analyses)
    units_by: Dict[str, List[Dict[str, Any]]] = {}
    for u in doc["measure_units"]:
        if u["kind"] in ("measure", "locked_group", "system"):
            units_by.setdefault(u["occurrence_id"], []).append(u)
    bound_by = {b["id"]: b for b in doc["boundaries"]}
    atoms: List[Dict[str, Any]] = []
    strips: Dict[str, Dict[str, Any]] = {}
    trims: List[Dict[str, Any]] = []
    refusals: List[Dict[str, Any]] = []
    prev_an: Optional[rb.StripAnalysis] = None
    prev_jump: Dict[str, Any] = {}
    for d in decided:
        sid = d["system"]["id"]
        img, rec, an = images[sid], recs[sid], analyses[sid]
        gap_src = float(rec.get("staff_gap_px") or (an.gap if an.staff else 0) or 0)
        if gap_src <= 0:
            raise MeasurePlanUnavailable("NO_STAFF_GAP", {"system_id": sid})
        scale = target_gap_px / gap_src
        edge_cache = doc_cache.setdefault("frame_edges", {}) if doc_cache is not None else {}
        if sid not in edge_cache:
            edge_cache[sid] = frame_edge_cleanup(img, an)
        img_c, edge_ops = edge_cache[sid][0], [dict(op) for op in edge_cache[sid][1]]
        trims.extend(edge_ops)
        R = _resampled(img_c, scale)
        H, W = R.shape[:2]
        nonstaff_out = _influence(an.nonstaff, W, H)
        clear_native = ~an.nonstaff.any(axis=0)
        ys = rec.get("staff_y_strip") or ([an.staff["lines"][0]] if an.staff else [0.0])
        top_out = float(ys[0]) * scale
        # paper margins outside the staff and every protected pixel are trimmed (paper only)
        prot_cols = np.nonzero(an.protected.any(axis=0))[0]
        w_native = img.shape[1]
        if an.staff is not None:
            left = min(int(an.staff["x"][0]), int(prot_cols[0]) if len(prot_cols) else w_native)
            right = max(int(an.staff["x"][1]) + 1, int(prot_cols[-1]) + 1 if len(prot_cols) else 0)
        else:
            left, right = (int(prot_cols[0]), int(prot_cols[-1]) + 1) if len(prot_cols) else (0, w_native)
        left, right = max(0, left), min(w_native, right)
        XL, XR = int(np.floor(left * scale)), min(W, int(np.ceil(right * scale)))
        trims.append({"system_id": sid, "op": "margin_trim", "native_cols": [[0, left], [right, w_native]],
                      "output_cols": [[0, XL], [XR, W]], "protected_px": int(an.protected[:, :left].sum() + an.protected[:, right:].sum())})
        prefix = ru.clef_patch(an)
        replica = None
        if prefix.get("verified"):
            pimg = prefix["_image"]
            px0 = int(prefix["box"][0])
            for op in edge_ops:  # the replica patch is cut from the same strip: same frame-edge cleanup
                c = op["native_col"] - px0
                if 0 <= c < pimg.shape[1]:
                    rows = np.any(img_c[:, op["native_col"]] != img[:, op["native_col"]], axis=-1)
                    pimg = pimg.copy()
                    pimg[rows, c] = img_c[rows, op["native_col"]]
                    op["also_in_clef_replica"] = True
            rp = _resampled(pimg, scale)
            replica = {"image": rp, "width": int(rp.shape[1]), "source_box": prefix["box"],
                       "patch_pixels_sha256": prefix["patch_pixels_sha256"], "mask_sha256": prefix["mask_sha256"],
                       "source_pixels_sha256": prefix["source_pixels_sha256"], "masked_protected_px": prefix["masked_protected_px"],
                       "ledger_omitted_boxes": _mask_rectangles(np.any(rp != _resampled(img[:, prefix["box"][0]:prefix["box"][2]], scale), axis=-1))}
        pfree = _prefix_free(an)
        # a jump-view run without a verified clef to copy: lines inside its strips start bare (recorded)
        bare_ok = bool((rec.get("jump") or {}).get("no_clef_copy"))
        staff_rows = _staff_rows_out(an, rec, scale, H)
        ink_rows = nonstaff_out.any(axis=1) | staff_rows
        strips[sid] = {"image": R, "scale": scale, "top_out": top_out, "nonstaff_out": nonstaff_out, "replica": replica,
                       "source_strip_id": sid, "pre_crop": [0, 0], "native_shape": list(img.shape[:2]),
                       "resample_source_size": [img_c.shape[1], img_c.shape[0]],
                       "staff_rows_R": [float(y) * scale + (scale - 1) / 2 for y in (rec.get("staff_y_strip") or (an.staff or {}).get("lines", []))],
                       "ledger_changed_boxes": _mask_rectangles(np.any(R != _resampled(img, scale), axis=-1)) if edge_ops else [],
                       "record": rec,
                       "prefix_free": pfree, "prefix": {k: v for k, v in prefix.items() if not k.startswith("_")},
                       "variant": d["variant"], "label": d.get("label"), "label_section": d.get("label_section"),
                       "trim_out": [XL, XR], "gap_src": gap_src}
        us = sorted(units_by.get(sid, []), key=lambda u: u["box"][0])
        current_jump = rec.get("jump") or {}
        chain_break = bool(prev_jump.get("unverified_seam_after") or current_jump.get("unverified_seam_before")
                           or (prev_jump and current_jump and
                               (prev_jump.get("run"), prev_jump.get("chain")) !=
                               (current_jump.get("run"), current_jump.get("chain"))))
        join_ctx = bool(not chain_break and prev_an is not None and _ends_at_barline(prev_an) and atoms and not atoms[-1].get("overhang")
                        and abs(prev_an.gap - an.gap) <= 0.03 * max(prev_an.gap, an.gap))
        ctx_why = None
        if chain_break:
            ctx_why = "JUMP_CHAIN_BREAK"
        elif prev_an is None:
            ctx_why = "FIRST_SYSTEM"
        elif not _ends_at_barline(prev_an):
            ctx_why = "PREVIOUS_SYSTEM_NOT_ENDING_AT_BARLINE"
        elif not atoms or atoms[-1].get("overhang"):
            ctx_why = "PREVIOUS_SYSTEM_OVERHANG"
        elif not join_ctx:
            ctx_why = "STAFF_GAP_MISMATCH"
        join: Dict[str, Any] = {"mode": None}
        if pfree:
            join = {"mode": "prefix_free", "trim": 0, "slot": None}
        elif an.staff is not None and an.clef and us:
            x0u, x1u = int(us[0]["box"][0]), int(us[0]["box"][2])
            X0u = max(int(round(x0u * scale)), XL)
            X1u = min(int(round(x1u * scale)), XR) if len(us) == 1 else int(round(x1u * scale))
            dj = _declef_join(an, R, scale, X0u, X1u)
            if dj["ok"]:
                strips[sid]["declef"] = {k: dj[k] for k in ("image", "nonstaff_out", "ledger_changed_boxes")}
                join = {"mode": "declef", "trim": dj["trim"], "clear_cols": dj["clear_cols"], "lead_out": dj["lead_out"],
                        "lead_target_px": dj["lead_target_px"], "ledger": dj["ledger"],
                        "resampled_changed_px": dj["resampled_changed_px"],
                        "slot": dict(dj["slot"], id=f"{us[0]['id']}/join-slot", kind="join_lead", system_id=sid, boundary_id=None)}
            else:
                join = {"mode": None, "refused": dj["reason"], "detail": dj.get("detail")}
        elif an.staff is None:
            join = {"mode": None, "refused": "NO_STAFF_GEOMETRY"}
        elif not an.clef:
            join = {"mode": None, "refused": "PRINTED_PREFIX_WITHOUT_CLEF"}
        if not join_ctx and join.get("mode"):
            join = {"mode": None, "refused": ctx_why or "PREVIOUS_END_NOT_JOINABLE"}
        if not (join_ctx and join.get("mode")) and prev_an is not None:
            refusals.append({"system_id": sid, "reason": join.get("refused") or ctx_why or "NOT_JOINABLE",
                             **({"previous_end": ctx_why} if ctx_why and ctx_why != join.get("refused") else {}),
                             **({"detail": join["detail"]} if join.get("detail") else {})})
        join_legal = bool(join_ctx and join.get("mode"))
        if join_legal:
            # the previous system's columns after its final barline that no ink reaches (staff stubs, the
            # faint edge of the source frame) are dropped when this system continues on its line
            join["prev_tail_trim"] = int(atoms[-1].get("tail_clear_out") or 0)
            join["trim"] = int(join.get("trim") or 0) + join["prev_tail_trim"]
            join["lead_trim"] = join["trim"] - join["prev_tail_trim"]
        strips[sid]["join"] = {k: v for k, v in join.items() if k not in ("clear_cols",)}
        for k, u in enumerate(us):
            x0, x1 = int(u["box"][0]), int(u["box"][2])
            X0, X1 = int(round(x0 * scale)), int(round(x1 * scale))
            if k == 0:
                X0 = max(X0, XL)
            if k == len(us) - 1:
                X1 = min(X1, XR)
            overhang = 0
            if k == len(us) - 1 and an.staff is not None:
                # ink past the staff end (a "Fine" box) hangs out of the justified width; so does a kept
                # (uncut, unverified) preview tail: the next system's start shown after the staff break,
                # even where the record's staff runs on through it (a scrolling sheet)
                staff_end = int(an.staff["x"][1]) + 1
                tail = rec.get("preview_tail") or {}
                if tail and not tail.get("cut") and tail.get("break_x", tail.get("cut_x")) is not None:
                    brk = int(tail.get("break_x", tail.get("cut_x"))) - int((rec.get("box_crop") or [0])[0])
                    if x0 < brk < staff_end:
                        staff_end = brk
                overhang = max(0, min(X1, XR) - max(X0, int(np.ceil(staff_end * scale))))
                if overhang < 0.5 * target_gap_px:
                    overhang = 0  # the final barline's own stroke/fringe past the recorded staff end
            a = {"id": u["id"], "unit_id": u["id"], "system_id": sid, "kind": u["kind"], "measure_count": u["measure_count"],
                 "measure_estimate": len(u["internal_boundary_ids"]) + 1,
                 "cols_out": [X0, X1], "width": max(0, X1 - X0 - overhang), "overhang": overhang, "native_box": list(u["box"]),
                 "rows_out": _unit_rows(ink_rows, nonstaff_out, staff_rows, X0, X1)}
            if k == 0:
                a.update(break_before="system_start", join_legal=join_legal, slot_before=None, boundary_id=None,
                         section_start=bool((d.get("label") or {}).get("path")),
                         join=join if join_legal else None, join_trim=int(join.get("trim") or 0) if join_legal else 0)
            else:
                b = bound_by.get(u.get("left_boundary_id"))
                seam = int(b["seam_x"]) if b else x0
                c = int(max(rb.CONFIG["clearance_min_px"], np.ceil(rb.CONFIG["clearance_gaps"] * an.gap))) if an.staff else 1
                ca, cb = _clear_run(clear_native, seam)
                nat = max(0, cb - ca)
                g_slot = an.gap * scale if an.staff else gap_src * scale
                e_cap, c_cap = rlines.slot_caps(nat * scale, g_slot)
                e_wide = max(e_cap, rlines.wide_grow_cap(nat * scale, g_slot))
                Xs = int(round(seam * scale))
                # contraction removes only output columns that no non-staff ink reaches, keeping the clearance
                ua, ub = int(np.ceil((ca + c) * scale)), int(np.floor((cb - c) * scale))
                col_clear = ~nonstaff_out.any(axis=0)
                room_l = 0
                while Xs - room_l - 1 >= max(ua, 0) and col_clear[Xs - room_l - 1]:
                    room_l += 1
                room_r = 0
                while Xs + room_r < min(ub, W) and col_clear[Xs + room_r]:
                    room_r += 1
                insert_ok = 0 <= Xs < W and bool(col_clear[Xs])
                slot = {"id": f"{u['id']}/slot", "kind": "barline_corridor", "boundary_id": b["id"] if b else None, "system_id": sid,
                        "natural": round(nat * scale, 3), "native_corridor": [int(ca), int(cb)], "seam_out": Xs,
                        "max_expand": e_cap if insert_ok else 0.0, "max_contract": min(c_cap, float(room_l + room_r)),
                        "max_expand_wide": e_wide if insert_ok else 0.0,
                        "room_out": [room_l, room_r], "evidence": "full-height clear columns (nonstaff mask), clearance kept"}
                a.update(break_before="safe_cut", join_legal=False, slot_before=slot, boundary_id=b["id"] if b else None,
                         replica_width=(replica["width"] if replica else (0 if (pfree or bare_ok) else None)))
            if an.staff is not None:
                # a double barline (or repeat) at the unit's end closes a section: a short line may end there
                a["ends_section"] = any(len(bb.get("strokes") or []) > 1 and x1 - 3 * an.gap <= int(bb["x1"]) <= x1 + an.gap
                                        for bb in an.bars)
                guard = None
                if k == 0:
                    guard = int(round((int(an.staff["x"][0]) + SPREAD_PREFIX_GUARD_GAPS * an.gap) * scale))
                    if join.get("lead_out"):
                        guard = max(guard, int(join["lead_out"][1]))
                a["gaps"] = spread_gaps(R, staff_rows, an.gap * scale, X0, X1 - overhang, guard_x=guard, id_prefix=f"{u['id']}/gap")
            if k == len(us) - 1 and _ends_at_barline(an) and not overhang:
                a["tail_clear_out"] = _tail_clear_columns(R, nonstaff_out, X0, X1)
            if line_width and d["system"].get("layout") == "jump_view":
                rep_w = int(replica["width"]) if (replica is not None and k > 0) else 0
                probe = dict(a, width=int(a["width"]) + rep_w, break_before="system_start")
                if rlines._line_eval([probe], 0, 1, int(line_width), final=True) is None:
                    f = OVERSIZE_FILL * float(line_width) / float(int(a["width"]) + rep_w + int(overhang))
                    s2 = scale * f
                    nl = left if k == 0 else x0
                    nr = right if k == len(us) - 1 else x1
                    R2 = _resampled(img_c[:, nl:nr], s2)
                    H2, W2 = R2.shape[:2]
                    ns2 = _influence(an.nonstaff[:, nl:nr], W2, H2)
                    sr2 = _staff_rows_out(an, rec, s2, H2)
                    rep2 = None
                    if replica is not None:
                        rp2 = _resampled(pimg, s2)
                        rep2 = dict(replica, image=rp2, width=int(rp2.shape[1]),
                                    ledger_omitted_boxes=_mask_rectangles(np.any(rp2 != _resampled(img[:, prefix["box"][0]:prefix["box"][2]], s2), axis=-1)))
                    key = f"{sid}#{u['id']}"
                    base = {kk: vv for kk, vv in strips[sid].items() if kk not in ("declef",)}
                    strips[key] = dict(base, image=R2, scale=s2, top_out=float(ys[0]) * s2, nonstaff_out=ns2, replica=rep2,
                                       pre_crop=[int(nl), 0],
                                       resample_source_size=[int(nr - nl), img_c.shape[0]],
                                       staff_rows_R=[float(y) * s2 + (s2 - 1) / 2 for y in (rec.get("staff_y_strip") or (an.staff or {}).get("lines", []))],
                                       ledger_changed_boxes=_mask_rectangles(np.any(R2 != _resampled(img[:, nl:nr], s2), axis=-1)) if edge_ops else [],
                                       trim_out=[0, W2], label=(d.get("label") if k == 0 else None),
                                       join={"mode": None, "refused": "OVERSIZE_UNIT_SCALED"}, oversize_of=sid, oversize_factor=f)
                    ov2 = int(round(overhang * f))
                    guard2 = None
                    if k == 0 and an.staff is not None:
                        guard2 = int(round((int(an.staff["x"][0]) - nl + SPREAD_PREFIX_GUARD_GAPS * an.gap) * s2))
                    a.update(strip_key=key, cols_out=[0, W2], width=max(0, W2 - ov2), overhang=ov2, alone=True,
                             rows_out=_unit_rows(ns2.any(axis=1) | sr2, ns2, sr2, 0, W2),
                             oversize={"factor": round(f, 4), "scale_out": round(s2, 5), "native_cols": [int(nl), int(nr)],
                                       "width_at_page_scale": int(probe["width"]) + int(overhang)})
                    if an.staff is not None:
                        a["gaps"] = spread_gaps(R2, sr2, an.gap * s2, 0, W2 - ov2, guard_x=guard2, id_prefix=f"{u['id']}/gap")
                    if k == 0:
                        a.update(join_legal=False, join=None, join_trim=0)
                    else:
                        a["replica_width"] = rep2["width"] if rep2 is not None else (0 if (pfree or bare_ok) else None)
                    a.pop("tail_clear_out", None)
            if k > 0 and d["system"].get("layout") == "jump_view" and not a.get("oversize") \
                    and not (atoms and atoms[-1].get("oversize")):
                num = number_over_barline(an, int(b["seam_x"]) if b else x0)
                if num and num.get("native_box"):
                    nb = num["native_box"]
                    staff_top_out = int(np.floor((float(an.staff["lines"][0]) - 0.5 * float(an.staff["thick"]) - 1) * scale))
                    a["carried_number"] = dict(num, box_out=[int(np.floor(nb[0] * scale)), int(np.floor(nb[1] * scale)),
                                                             int(np.ceil(nb[2] * scale)), min(int(np.ceil(nb[3] * scale)), staff_top_out)])
                elif num:
                    a["carried_number"] = num
            atoms.append(a)
        prev_an = an
        prev_jump = current_jump
    built = {"atoms": atoms, "strips": strips, "doc": doc, "trims": trims, "join_refusals": refusals,
             "analyses": analyses}
    if line_width and not floor_break_ids:
        forced = _floor_breaks(built, target_gap_px / rl.MM, line_width, locks)
        if forced:
            return build_atoms(decided, target_gap_px=target_gap_px, context=context, locks=locks,
                               job_id=job_id, revision=revision, line_width=line_width, doc_cache=doc_cache,
                               floor_break_ids=forced)
    return built


def _floor_breaks(built: Dict[str, Any], mm: float, line_width: int,
                  locks: Sequence[Dict[str, Any]]) -> List[str]:
    """Fewest crossing-only cuts that meet the floor; prefer pieces fitting at full size.

    If no complete solution exists, minimize the native span still below the floor before
    minimizing cuts. This also improves a partly splittable unit without hiding its remainder.
    """
    doc, strips = built["doc"], built["strips"]
    units = doc["measure_units"]
    order = {u["id"]: i for i, u in enumerate(units)}
    kept = set()
    for lk in locks:
        targets = lk.get("targets") or []
        if lk.get("active", True) and lk.get("type") == "keep_together" and len(targets) == 2 \
                and all(t in order for t in targets):
            kept.update(u["id"] for u in units[order[targets[0]]:order[targets[1]] + 1])
    chosen = []
    for a in built["atoms"]:
        if not a.get("oversize") or a["unit_id"] in kept:
            continue
        st = strips[a["system_id"]]
        factor = strips[_sk(a)]["scale"] / st["scale"]
        if mm * factor >= AUTO_MIN_STAFF_GAP_MM - 1e-9:
            continue
        # A continuation must have the same verified prefix support as an ordinary SAFE cut.
        rep = st.get("replica")
        bare = st["prefix_free"] or bool((st["record"].get("jump") or {}).get("no_clef_copy"))
        if rep is None and not bare:
            continue
        lo, hi = a["oversize"]["native_cols"]
        candidates = sorted((b for b in doc["boundaries"] if b["system_id"] == a["system_id"]
                             and lo < b["seam_x"] < hi
                             and ru.floor_break_eligible(b, built.get("analyses", {}).get(a["system_id"]))),
                            key=lambda b: b["seam_x"])
        points = [lo] + [b["seam_x"] for b in candidates] + [hi]
        # cost: unfixable native width, number of cuts, number of scaled pieces.
        best = {0: ((0, 0, 0), [])}
        for j in range(1, len(points)):
            options = []
            for i in range(j):
                rep_w = int(rep["width"]) if rep is not None and (i > 0 or a["break_before"] != "system_start") else 0
                width = int(round(points[j] * st["scale"])) - int(round(points[i] * st["scale"])) + rep_w
                fits = width <= line_width
                eff = mm if fits else mm * OVERSIZE_FILL * line_width / max(1, width)
                bad = points[j] - points[i] if eff < AUTO_MIN_STAFF_GAP_MM - 1e-9 else 0
                cost, path = best[i]
                options.append(((cost[0] + bad, cost[1] + (j < len(points) - 1),
                                 cost[2] + (not fits)), path + ([candidates[j - 1]["id"]] if j < len(points) - 1 else [])))
            best[j] = min(options, key=lambda item: item[0])
        chosen.extend(best[len(points) - 1][1])
    return chosen


def _sk(a: Dict[str, Any]) -> str:
    """The strip entry an atom is cut from (an oversize unit has its own, smaller-scale entry)."""
    return a.get("strip_key") or a["system_id"]


def _place(canvas: np.ndarray, img: np.ndarray, x: int, y: int) -> None:
    canvas[y:y + img.shape[0], x:x + img.shape[1]] = img


def _spread_columns(src: np.ndarray, cols: Sequence[int], a: Dict[str, Any], slots: Dict[str, Dict[str, Any]], line_id: str,
                    x: int, ops: List[Dict[str, Any]]) -> Tuple[List[int], List[int], List[int]]:
    """The atom's source columns after its spread gaps' deltas: (column index list, offsets of the
    inserted columns in it, removed source columns). An expansion repeats the gap's middle column
    (identical to its neighbours by eligibility) right after it; a contraction removes columns of the
    gap's own eligible run around its middle. Every operation is recorded in ``ops``."""
    ins: Dict[int, Tuple[int, Dict[str, Any]]] = {}
    removed: set = set()
    colset = set(cols)
    for g in a.get("gaps") or ():
        dd = int((slots.get(g["id"]) or {}).get("applied_delta") or 0)
        if dd == 0:
            continue
        c = int(g["col_out"])
        if c not in colset:
            raise MeasurePlanUnavailable("SPREAD_GAP_OUTSIDE_ATOM", {"line_id": line_id, "gap_id": g["id"]})
        if dd > 0:
            ins[c] = (dd, g)
        else:
            n = -dd
            ra, rb_ = g["run_out"]
            s0 = min(max(ra, c - n // 2), rb_ - n)
            rem = list(range(s0, s0 + n))
            if s0 < ra or any(r not in colset for r in rem):
                raise MeasurePlanUnavailable("SPREAD_REMOVAL_OUT_OF_RUN", {"line_id": line_id, "gap_id": g["id"]})
            removed.update(rem)
            ops.append({"op": "remove_spread_columns", "gap_id": g["id"], "line_id": line_id, "atom_id": a["id"],
                        "column_kind": g.get("column_kind"), "cols_out": [s0, s0 + n], "columns": n,
                        "eligible": all(column_eligible(src, r) for r in rem)})
    idx: List[int] = []
    offs: List[int] = []
    for c in cols:
        if c in removed:
            continue
        idx.append(c)
        if c in ins:
            n, g = ins[c]
            ops.append({"op": "insert_spread_columns", "gap_id": g["id"], "line_id": line_id, "atom_id": a["id"],
                        "column_kind": g.get("column_kind"), "source_column_out": c, "columns": n, "x_out": x + len(idx),
                        "dark_px_per_column": int((src[:, c].min(axis=-1) < 200).sum()), "eligible": column_eligible(src, c)})
            offs.extend(range(len(idx), len(idx) + n))
            idx.extend([c] * n)
    return idx, offs, sorted(removed)


def reconstruct_atom(line_img: np.ndarray, placement: Dict[str, Any]) -> np.ndarray:
    """The atom's source columns from a rendered line: its placed columns with every inserted
    column removed (the pixel ledger; equals the resampled strip's columns ``cols_src_out`` minus
    ``removed_cols_out``)."""
    x, y = int(placement["x_out"]), int(placement["y_out"])
    h, w = placement["rows_src_out"][1] - placement["rows_src_out"][0], int(placement["width_out"])
    seg = line_img[y:y + h, x:x + w]
    drop = set(int(o) for o in placement.get("inserted_offsets") or [])
    return seg[:, [p for p in range(w) if p not in drop]]


def _mask_rectangles(mask: np.ndarray) -> List[List[int]]:
    """Disjoint rectangles for changed pixels; vectorised row-run discovery."""
    edges = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    ys, starts = np.nonzero(edges == 1)
    _ys, ends = np.nonzero(edges == -1)
    boxes: List[List[int]] = []
    active: Dict[Tuple[int, int], List[int]] = {}
    for y, a, b in zip(ys.tolist(), starts.tolist(), ends.tolist()):
        key = (a, b)
        prev = active.get(key)
        if prev is not None and prev[3] == y:
            prev[3] = y + 1
        else:
            box = [a, y, b, y + 1]
            boxes.append(box)
            active[key] = box
    return boxes


def _column_runs(cols: Sequence[int]) -> List[List[int]]:
    if not len(cols):
        return []
    a = np.asarray(cols, dtype=int)
    cuts = np.r_[0, np.nonzero(np.diff(a) != 1)[0] + 1, len(a)]
    return [[int(a[i]), int(a[j - 1]) + 1] for i, j in zip(cuts[:-1], cuts[1:])]


def _subtract_box(piece: dict, box: Sequence[int]) -> Tuple[List[dict], Optional[dict]]:
    a, b, c, d = piece["src_bbox"]
    x0, y0, x1, y1 = max(a, box[0]), max(b, box[1]), min(c, box[2]), min(d, box[3])
    if x0 >= x1 or y0 >= y1:
        return [piece], None
    boxes = [[a, b, c, y0], [a, y1, c, d], [a, y0, x0, y1], [x1, y0, c, y1]]
    rest = [dict(piece, src_bbox=q) for q in boxes if q[0] < q[2] and q[1] < q[3]]
    return rest, dict(piece, src_bbox=[x0, y0, x1, y1])


def _exclude_boxes(stage: dict, boxes: Sequence[Sequence[int]]) -> None:
    for box in boxes:
        stage["pieces"] = [p for old in stage["pieces"] for p in _subtract_box(old, box)[0]]


def _placement_stage(pl: dict) -> dict:
    """Use the v1 adapter when sufficient; otherwise retain the exact column order."""
    scale = float(pl["scale"])
    cols = pl["source_col_index"]
    a, b = pl["cols_src_out"]
    removed, inserted = set(pl.get("removed_cols_out", [])), set(pl.get("inserted_offsets", []))
    src = iter(c for c in range(a, b) if c not in removed)
    compressed = [None if j in inserted else next(src, None) for j in range(pl["width_out"])]
    if compressed == cols and next(src, None) is None:
        stage = ledger_api.measure_placement_transform(pl, native_scale=scale)
    else:
        pieces = []
        start = 0
        while start < len(cols):
            if cols[start] is None:
                start += 1
                continue
            end = start + 1
            while end < len(cols) and cols[end] is not None and cols[end] == cols[end - 1] + 1:
                end += 1
            c = int(cols[start])
            pieces.append({"src_bbox": [c, pl["rows_src_out"][0], int(cols[end - 1]) + 1, pl["rows_src_out"][1]],
                           "matrix": [[1, 0, float(pl["x_out"]) + start - c],
                                      [0, 1, float(pl["y_out"]) - pl["rows_src_out"][0]], [0, 0, 1]]})
            start = end
        stage = {"stage": "strip_to_line", "kind": "piecewise", "pieces": pieces,
                 "inserted_offsets": sorted(inserted), "line_id": pl["line_id"]}
    dx, dy = pl["pre_crop"]
    sx = sy = scale
    if pl.get("resample"):
        spec = pl["resample"]
        sx, sy = spec["output_size"][0] / spec["source_size"][0], spec["output_size"][1] / spec["source_size"][1]
        stage["pre_resample"] = dict(spec, crop_origin=[dx, dy])
    stage["pre_matrix"] = [[sx, 0, (sx - 1) / 2 - sx * dx],
                           [0, sy, (sy - 1) / 2 - sy * dy], [0, 0, 1]]
    return stage


def _resample_record(st: dict) -> dict:
    H, W = st["image"].shape[:2]
    source = st.get("resample_source_size") or [int(round(W / st.get("scale", 1))), int(round(H / st.get("scale", 1)))]
    return {"source_size": list(source), "output_size": [W, H], "interpolation": "area" if W < source[0] else "cubic"}


def _ledger_line_records(ledger: dict, strips: dict, placement_keys: list,
                         replica_placements: list, generated: list, removed: list) -> None:
    records = []
    pending = {"stage": "line_to_page", "kind": "affine", "matrix": None}
    for pl, key in zip(ledger["placements"], placement_keys):
        st = strips[key]
        stage = _placement_stage(pl)
        changed = list(st.get("ledger_changed_boxes", []))
        if pl.get("source") == "declef":
            changed += st["declef"].get("ledger_changed_boxes", [])
        _exclude_boxes(stage, changed)
        for box in changed:
            domain = {"src_bbox": [pl["cols_src_out"][0], pl["rows_src_out"][0], pl["cols_src_out"][1], pl["rows_src_out"][1]]}
            _rest, part = _subtract_box(domain, box)
            if part is not None:
                removed.append({"strip_id": pl["strip_id"], "src_bbox_R": part["src_bbox"], "line_id": pl["line_id"],
                                "op": "remove_clef" if pl.get("source") == "declef" else "frame_edge_to_paper",
                                "reason": "source pixels replaced before placement"})
        records.append({"strip_id": pl["strip_id"], "copy_index": 0, "page_index": None,
                        "line_id": pl["line_id"], "stages": [stage, dict(pending)]})
    # Number moves translate the source pieces actually copied from the old line,
    # retaining spread/cut geometry; their old domains are removed before assembly.
    for move in ledger["moved_measure_numbers"]:
        if not move.get("moved"):
            continue
        x0, y0, x1, y1 = move["from_box_out"]
        tx, ty = move["to_box_out"][0] - x0, move["to_box_out"][1] - y0
        for rec in list(records):
            if rec["line_id"] != move["from_line_id"] or rec["strip_id"] != move["strip_id"]:
                continue
            stage = rec["stages"][0]
            kept, moved = [], []
            for piece in stage["pieces"]:
                mat = np.asarray(piece["matrix"], dtype=float)
                dx, dy = mat[:2, 2]
                rest, part = _subtract_box(piece, [int(x0 - dx), int(y0 - dy), int(x1 - dx), int(y1 - dy)])
                kept.extend(rest)
                if part is not None:
                    mat[0, 2] += tx
                    mat[1, 2] += ty
                    moved.append(dict(part, matrix=mat.tolist()))
            stage["pieces"] = kept
            if moved:
                records.append({"strip_id": rec["strip_id"], "copy_index": rec["copy_index"], "page_index": None,
                                "line_id": move["line_id"], "stages": [dict(stage, pieces=moved, line_id=move["line_id"]), dict(pending)]})
    copies: Dict[str, int] = {}
    for pl, omitted in replica_placements:
        sid = pl["strip_id"]
        copies[sid] = copies.get(sid, 0) + 1
        stage = _placement_stage(pl)
        _exclude_boxes(stage, omitted)
        records.append({"strip_id": sid, "copy_index": copies[sid], "page_index": None, "line_id": pl["line_id"],
                        "stages": [stage, dict(pending)]})
    ledger.update(ledger_placements=records, ledger_removed=removed, generated_origins=generated)


def _scaffold_origin(st: dict, line_id: str, x0: int, x1: int, height: int, col: int, y: int, op: str) -> dict:
    s = float(st.get("scale", 1))
    dx, dy = st.get("pre_crop", [0, 0])
    spec = _resample_record(st)
    sx, sy = spec["output_size"][0] / spec["source_size"][0], spec["output_size"][1] / spec["source_size"][1]
    native_rows = (st.get("record") or {}).get("staff_y_strip", [])
    rows = [float(r) * sy + (sy - 1) / 2 for r in native_rows]
    centre = (col + .5) / sx - .5
    a, b = max(0, int(np.floor(centre))-4), min(spec["source_size"][0], int(np.floor(centre))+5)
    return {"kind": "staff_scaffold", "line_id": line_id, "page_index": None, "box_L": [x0, 0, x1, height],
            "strip_id": st.get("source_strip_id"), "source_bbox_S": [dx + a, dy, dx + b, dy + spec["source_size"][1]],
            "source_resample": dict(spec, crop_origin=[dx, dy]), "source_column_R": int(col),
            "staff_rows_S": list(native_rows), "source_y_L": y,
            "staff_rows_local": [float(r) + y for r in rows], "generator": f"render_lines:{MEASURE_VERSION}/{rr.RENDER_VERSION}",
            "inputs": {"op": op, "columns": x1 - x0, "source_column_R": int(col), "scale": s, "pre_crop": [dx, dy]}}


def _ledger_beam_copies(ledger: dict, strips: dict) -> None:
    """Copied beam columns are explicit source replicas, never staff exemptions."""
    retained = []
    ci = max((r["copy_index"] for r in ledger["ledger_placements"]), default=0)
    by_id = {st.get("source_strip_id", key): st for key, st in strips.items()}
    for rec in ledger["generated_origins"]:
        if rec["kind"] != "staff_scaffold":
            retained.append(rec)
            continue
        template = ledger_api.unpack_crop(rec["template"])
        active = np.flatnonzero((template.min(axis=-1) < 255-ledger_api.MIN_CONTRAST).any(axis=1))
        bands = np.split(active, np.flatnonzero(np.diff(active) > 1)+1)
        if len([b for b in bands if len(b)]) == 5:
            retained.append(rec)
            continue
        # A source column with extra ink cannot acquire the staff-only kind.
        st = by_id[rec["strip_id"]]
        spec = rec["source_resample"]
        col, y = rec["source_column_R"], rec["source_y_L"]
        x0, _y0, x1, height = rec["box_L"]
        r0, r1 = max(0, -y), min(spec["output_size"][1], height-y)
        n = x1-x0
        pl = {"scale": st["scale"], "pre_crop": spec["crop_origin"], "resample": spec,
              "cols_src_out": [col, col+1], "rows_src_out": [r0, r1], "width_out": 1,
              "source_col_index": [col], "x_out": x0, "y_out": y+r0, "line_id": rec["line_id"]}
        stage = _placement_stage(pl)
        stage["pieces"] = [{"src_bbox": [col, r0, col+1, r1], "column_repeat": n,
                            "matrix": [[n,0,x0+(n-1)/2-n*col],[0,1,y],[0,0,1]]}]
        ci += 1
        ledger["ledger_placements"].append({"strip_id": rec["strip_id"], "copy_index": ci, "page_index": None,
            "line_id": rec["line_id"], "stages": [stage, {"stage":"line_to_page","kind":"affine","matrix":None}]})
    ledger["generated_origins"] = retained


def render_lines(atoms: Sequence[Dict[str, Any]], strips: Dict[str, Dict[str, Any]], lines_plan: Dict[str, Any],
                 *, target_gap_px: float) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """Line images (white paper, output scale) and the line-level ledger."""
    slots = {s["id"]: s for s in lines_plan["slots"]}
    images: Dict[str, np.ndarray] = {}
    placements: List[Dict[str, Any]] = []
    scaffold_ops: List[Dict[str, Any]] = []
    replicas: List[Dict[str, Any]] = []
    labels: List[Dict[str, Any]] = []
    clef_removals: List[Dict[str, Any]] = []
    ledger_removed: List[Dict[str, Any]] = []
    generated: List[Dict[str, Any]] = []
    placement_keys: List[str] = []
    replica_placements: List[Tuple[dict, list]] = []
    mismatched = 0
    by_id = {a["id"]: a for a in atoms}
    placed_at: Dict[str, Tuple[int, List[int], int, int]] = {}
    for line in lines_plan["lines"]:
        seg = [by_id[i] for i in line["atom_ids"]]
        # the line is as tall as its units' own rows (ink + the strip's paper padding), staff tops aligned
        rows = {a["id"]: a.get("rows_out") or [0, strips[_sk(a)]["image"].shape[0]] for a in seg}
        cn = seg[0].get("carried_number") or {}
        if cn.get("box_out") and seg[0].get("break_before") == "safe_cut":
            # the measure number moved to this line's start needs its rows (jump-view strips)
            r0_, r1_ = rows[seg[0]["id"]]
            rows[seg[0]["id"]] = [min(int(r0_), int(cn["box_out"][1])), max(int(r1_), int(cn["box_out"][3]))]
        ty = {a["id"]: int(round(strips[_sk(a)]["top_out"])) for a in seg}
        up = max(ty[a["id"]] - rows[a["id"]][0] for a in seg)
        down = max(rows[a["id"]][1] - ty[a["id"]] for a in seg)
        # contraction split: which output columns each atom gives up at its seam
        cut_l: Dict[str, int] = {}
        cut_r: Dict[str, int] = {}
        insert: Dict[str, int] = {}
        for k, a in enumerate(seg):
            sl = a.get("slot_before")
            if k == 0 or not sl:
                continue
            delta = int(slots[sl["id"]]["applied_delta"]) if sl["id"] in slots else 0
            if delta > 0:
                insert[a["id"]] = delta
            elif delta < 0:
                need = -delta
                rl_, rr_ = sl["room_out"]
                take_l = min(rl_, (need + 1) // 2)
                take_r = min(rr_, need - take_l)
                take_l = min(rl_, need - take_r)
                cut_l[seg[k - 1]["id"]] = take_l
                cut_r[a["id"]] = take_r
        # labels anchored to the first atom of their system on this line (the section start measure)
        lab_imgs: List[Tuple[Dict[str, Any], np.ndarray, Dict[str, Any]]] = []
        for a in seg:
            st = strips[_sk(a)]
            lab = st.get("label") or {}
            if lab.get("path") and a["id"] == next(x["id"] for x in seg if x["system_id"] == a["system_id"]) \
                    and a.get("break_before") == "system_start":
                patch = cv2.imread(str(lab["path"]))
                if patch is None:
                    raise MeasurePlanUnavailable("LABEL_PATCH_UNREADABLE", {"system_id": a["system_id"], "path": lab["path"]})
                bimg, meta = boxed_label(patch, st["scale"], target_gap_px)
                lab_imgs.append((a, bimg, meta))
        band = 0
        if lab_imgs:
            band = max(b.shape[0] for _a, b, _m in lab_imgs) + int(round(LABEL_SEP_GAPS * target_gap_px))
        top = band + int(up)
        height = top + int(down)

        def crop(st: Dict[str, Any], img: np.ndarray, y: int, what: str) -> Tuple[np.ndarray, int, int]:
            """The rows of a strip-framed image (row 0 at canvas row ``y``) that fall on the line; the rows
            left off must hold no non-staff ink in these columns (checked on the strip's ink mask)."""
            r0, r1 = max(0, -y), min(img.shape[0], height - y)
            return img[r0:r1], y + r0, r0

        def crop_checked(st: Dict[str, Any], img: np.ndarray, y: int, cols: Sequence[int], ns: np.ndarray, what: str):
            piece, yy, r0 = crop(st, img, y, what)
            r1 = r0 + piece.shape[0]
            cols = np.asarray(cols, dtype=int)
            if len(cols) and (ns[:r0][:, cols].any() or ns[r1:][:, cols].any()):
                raise MeasurePlanUnavailable("ROW_CROP_WOULD_DROP_INK", {"line_id": line["id"], "what": what})
            return piece, yy, r0
        width = int(line["achieved_width"]) + int(line.get("overhang_px") or 0)
        canvas = np.full((height, width, 3), 255, np.uint8)
        x = 0
        atom_x: Dict[str, int] = {}
        checks: List[Tuple[np.ndarray, int, int]] = []
        first = seg[0]
        if line["replica_width"]:
            st = strips[_sk(first)]
            rep = st["replica"]
            y = top - int(round(st["top_out"]))
            rimg = rep["image"]
            rpiece, ry, rr0 = crop(st, rimg, y, "clef replica")
            if np.any(rimg[:rr0].min(axis=-1) < 200) or np.any(rimg[rr0 + rpiece.shape[0]:].min(axis=-1) < 200):
                raise MeasurePlanUnavailable("ROW_CROP_WOULD_DROP_INK", {"line_id": line["id"], "what": "clef replica"})
            _place(canvas, rpiece, x, ry)
            replicas.append({"id": f"{line['id']}/clef-replica", "line_id": line["id"], "kind": "clef", "replica_of_system_id": first["system_id"],
                             "source_box_native": rep["source_box"], "patch_pixels_sha256": rep["patch_pixels_sha256"],
                             "mask_sha256": rep["mask_sha256"], "source_pixels_sha256": rep["source_pixels_sha256"],
                             "masked_protected_px": rep["masked_protected_px"], "x_out": x, "width_out": rep["width"],
                             "time_signature": "not replicated"})
            replica_placements.append(({"strip_id": st.get("source_strip_id", first["system_id"]), "line_id": line["id"],
                                        "scale": float(st.get("scale", 1)), "pre_crop": list(rep["source_box"][:2]),
                                        "cols_src_out": [0, rep["width"]], "rows_src_out": [rr0, rr0 + rpiece.shape[0]],
                                        "width_out": rep["width"], "x_out": x, "y_out": ry,
                                        "resample": {"source_size": [rep["source_box"][2] - rep["source_box"][0], rep["source_box"][3] - rep["source_box"][1]],
                                                     "output_size": [rimg.shape[1], rimg.shape[0]],
                                                     "interpolation": "area" if rimg.shape[1] < rep["source_box"][2] - rep["source_box"][0] else "cubic"},
                                        "source_col_index": list(range(rep["width"]))}, rep.get("ledger_omitted_boxes", [])))
            x += rep["width"]
        for k, a in enumerate(seg):
            st = strips[_sk(a)]
            strip_id = st.get("source_strip_id", a["system_id"])
            R = st["image"]
            y = top - int(round(st["top_out"]))
            if a["id"] in insert:
                n = insert[a["id"]]
                col = a["slot_before"]["seam_out"]
                src, sy, _r0 = crop_checked(st, R[:, col:col + 1], y, [col], st["nonstaff_out"], "corridor")
                src = src[:, :1]
                canvas[sy:sy + src.shape[0], x:x + n] = np.repeat(src, n, axis=1)
                scaffold_ops.append({"op": "insert_scaffold_columns", "slot_id": a["slot_before"]["id"], "line_id": line["id"],
                                     "columns": n, "source_column_out": int(col), "x_out": x,
                                     "dark_px_per_column": int((src.min(axis=2) < 200).sum()),
                                     "nonstaff_ink_in_source_column": bool(st["nonstaff_out"][:, col].any())})
                origin = _scaffold_origin(st, line["id"], x, x + n, height, col, y, "insert_scaffold_columns")
                origin["strip_id"] = strip_id
                generated.append(origin)
                x += n
            X0, X1 = a["cols_out"]
            X0 += cut_r.get(a["id"], 0)
            X1 -= cut_l.get(a["id"], 0)
            nxt_join = (seg[k + 1].get("join") or {}) if k + 1 < len(seg) and seg[k + 1].get("break_before") == "system_start" else {}
            if nxt_join.get("prev_tail_trim"):
                t = int(nxt_join["prev_tail_trim"])
                nso = (st.get("declef") or {}).get("nonstaff_out") if k > 0 and a.get("break_before") == "system_start" \
                    and (a.get("join") or {}).get("mode") == "declef" else st["nonstaff_out"]
                scaffold_ops.append({"op": "remove_scaffold_columns", "slot_id": None, "line_id": line["id"], "side": "join_tail",
                                     "system_id": a["system_id"], "cols_out": [X1 - t, X1],
                                     "nonstaff_ink_removed": bool((nso[:, X1 - t:X1] & np.any(R[:, X1 - t:X1] < 252, axis=-1)).any())})
                X1 -= t
                ledger_removed.append({"strip_id": strip_id, "src_bbox_R": [X1, 0, X1 + t, R.shape[0]],
                                       "op": "remove_scaffold_columns", "line_id": line["id"], "reason": "join_tail"})
            joined = k > 0 and a.get("break_before") == "system_start"
            jn = a.get("join") or {}
            if joined and jn.get("mode") == "declef":
                # the system continues mid-line: its repeated clef is removed (verified clean, recorded) and
                # lead columns no ink reaches are dropped so the measure starts like any other
                dsrc = st["declef"]
                jslot = slots.get(jn["slot"]["id"], {})
                r = int(jn.get("lead_trim", jn["trim"])) - int(jslot.get("applied_delta", 0))
                if not (0 <= r <= len(jn["clear_cols"])):
                    raise MeasurePlanUnavailable("JOIN_LEAD_OUT_OF_RANGE", {"line_id": line["id"], "atom_id": a["id"]})
                drop = set(jn["clear_cols"][:r])
                dropped = sorted(c for c in drop if X0 <= c < X1)
                keep = [c for c in range(X0, X1) if c not in drop]
                idx, offs, sremoved = _spread_columns(dsrc["image"], keep, a, slots, line["id"], x, scaffold_ops)
                piece, py, pr0 = crop_checked(st, dsrc["image"][:, idx], y, idx, dsrc["nonstaff_out"], a["id"])
                scaffold_ops.append({"op": "remove_scaffold_columns", "slot_id": jn["slot"]["id"], "line_id": line["id"],
                                     "side": "join_lead", "columns": len(dropped), "cols_out": [dropped[0], dropped[-1] + 1] if dropped else [],
                                     "nonstaff_ink_removed": bool(dsrc["nonstaff_out"][:, dropped].any()) if dropped else False})
                clef_removals.append(dict(jn["ledger"], line_id=line["id"], atom_id=a["id"],
                                          resampled_changed_px=jn.get("resampled_changed_px"), resampled_changed_outside_clef_px=0))
                scaffold_ops.append({"op": "remove_clef", "line_id": line["id"], "system_id": a["system_id"],
                                     "clef_component_px": jn["ledger"]["clef_component_px"],
                                     "removed_nonstaff_not_clef_px": jn["ledger"]["removed_nonstaff_not_clef_px"],
                                     "changed_outside_mask_px": jn["ledger"]["changed_outside_mask_px"]})
                _place(canvas, piece, x, py)
                checks.append((piece, x, py))
                atom_x[a["id"]] = x
                placements.append({"unit_id": a["unit_id"], "system_id": a["system_id"], "line_id": line["id"], "x_out": x,
                                   "y_out": py, "cols_src_out": [X0, X1], "rows_src_out": [pr0, pr0 + piece.shape[0]], "kind": a["kind"],
                                   "source": "declef", "joined": True, "dropped_cols_out": len(dropped), "width_out": int(piece.shape[1]),
                                   "inserted_offsets": offs, "removed_cols_out": sorted(set(dropped) | set(sremoved)),
                                   "strip_id": strip_id, "scale": float(st.get("scale", 1)), "pre_crop": list(st.get("pre_crop", [0, 0])),
                                   "resample": _resample_record(st),
                                   "source_col_index": [int(c) for c in idx]})
                for j in offs:
                    placements[-1]["source_col_index"][j] = None
                placement_keys.append(_sk(a))
                for c0, c1, reason in ((a["cols_out"][0], X0, "right_unit_start"),
                                       (X1, a["cols_out"][1], "left_unit_end")):
                    if c0 < c1:
                        ledger_removed.append({"strip_id": strip_id, "src_bbox_R": [c0, 0, c1, R.shape[0]],
                                               "op": "remove_scaffold_columns", "line_id": line["id"], "reason": reason})
                for cols, op, reason in ((dropped, "remove_scaffold_columns", "join_lead"), (sremoved, "remove_spread_columns", "spread contraction")):
                    ledger_removed.extend({"strip_id": strip_id, "src_bbox_R": [c0, 0, c1, R.shape[0]], "op": op,
                                           "line_id": line["id"], "reason": reason} for c0, c1 in _column_runs(cols))
                for j0, j1 in _column_runs(offs):
                    origin = _scaffold_origin(st, line["id"], x + j0, x + j1, height, idx[j0], y, "insert_spread_columns")
                    origin["strip_id"] = strip_id
                    generated.append(origin)
                x += piece.shape[1]
                continue
            if a["id"] in cut_r and cut_r[a["id"]]:
                rem = (a["cols_out"][0], a["cols_out"][0] + cut_r[a["id"]])
                scaffold_ops.append({"op": "remove_scaffold_columns", "slot_id": a["slot_before"]["id"], "line_id": line["id"],
                                     "side": "right_unit_start", "cols_out": list(rem),
                                     "nonstaff_ink_removed": bool(st["nonstaff_out"][:, rem[0]:rem[1]].any())})
                ledger_removed.append({"strip_id": strip_id, "src_bbox_R": [rem[0], 0, rem[1], R.shape[0]],
                                       "op": "remove_scaffold_columns", "line_id": line["id"], "reason": "right_unit_start"})
            if a["id"] in cut_l and cut_l[a["id"]]:
                nxt = seg[k + 1]
                rem = (a["cols_out"][1] - cut_l[a["id"]], a["cols_out"][1])
                scaffold_ops.append({"op": "remove_scaffold_columns", "slot_id": nxt["slot_before"]["id"], "line_id": line["id"],
                                     "side": "left_unit_end", "cols_out": list(rem),
                                     "nonstaff_ink_removed": bool(st["nonstaff_out"][:, rem[0]:rem[1]].any())})
                ledger_removed.append({"strip_id": strip_id, "src_bbox_R": [rem[0], 0, rem[1], R.shape[0]],
                                       "op": "remove_scaffold_columns", "line_id": line["id"], "reason": "left_unit_end"})
            idx, offs, sremoved = _spread_columns(R, list(range(X0, X1)), a, slots, line["id"], x, scaffold_ops)
            piece, py, pr0 = crop_checked(st, R[:, idx], y, idx, st["nonstaff_out"], a["id"])
            placed_at[a["id"]] = (x, list(idx), py, pr0)
            _place(canvas, piece, x, py)
            checks.append((piece, x, py))
            atom_x[a["id"]] = x
            placements.append({"unit_id": a["unit_id"], "system_id": a["system_id"], "line_id": line["id"], "x_out": x,
                               "y_out": py, "cols_src_out": [X0, X1], "rows_src_out": [pr0, pr0 + piece.shape[0]], "kind": a["kind"],
                               "width_out": int(piece.shape[1]), "inserted_offsets": offs, "removed_cols_out": sremoved,
                               "strip_id": strip_id, "scale": float(st.get("scale", 1)), "pre_crop": list(st.get("pre_crop", [0, 0])),
                               "resample": _resample_record(st),
                               "source_col_index": [int(c) for c in idx],
                               **({"joined": True} if joined else {})})
            for j in offs:
                placements[-1]["source_col_index"][j] = None
            placement_keys.append(_sk(a))
            ledger_removed.extend({"strip_id": strip_id, "src_bbox_R": [c0, 0, c1, R.shape[0]], "op": "remove_spread_columns",
                                   "line_id": line["id"], "reason": "spread contraction"} for c0, c1 in _column_runs(sremoved))
            for j0, j1 in _column_runs(offs):
                origin = _scaffold_origin(st, line["id"], x + j0, x + j1, height, idx[j0], y, "insert_spread_columns")
                origin["strip_id"] = strip_id
                generated.append(origin)
            x += piece.shape[1]
        if x != width:
            raise MeasurePlanUnavailable("LINE_WIDTH_MISMATCH", {"line_id": line["id"], "rendered": x, "planned": width})
        # section labels: outlined box above the section-start measure; never over the content
        lx_min = 0
        for a, bimg, meta in lab_imgs:
            bx = max(atom_x[a["id"]], lx_min)
            if bx + bimg.shape[1] > width:
                bx = max(lx_min, width - bimg.shape[1])
            if bx + bimg.shape[1] > width or bx < lx_min:
                raise MeasurePlanUnavailable("LABEL_COLLISION", {"line_id": line["id"], "system_id": a["system_id"]})
            by = band - int(round(LABEL_SEP_GAPS * target_gap_px)) - bimg.shape[0]
            canvas[by:by + bimg.shape[0], bx:bx + bimg.shape[1]] = np.minimum(canvas[by:by + bimg.shape[0], bx:bx + bimg.shape[1]], bimg)
            st = strips[_sk(a)]
            labels.append({"line_id": line["id"], "system_id": a["system_id"], "section": st.get("label_section"),
                           "anchor_unit_id": a["unit_id"], "mid_line": a["id"] != seg[0]["id"],
                           "box_out": [bx, by, bx + bimg.shape[1], by + bimg.shape[0]], **meta})
            generated.append({"kind": "section_label", "line_id": line["id"], "page_index": None,
                              "box_L": [bx, by, bx + bimg.shape[1], by + bimg.shape[0]], "template": ledger_api.pack_crop(bimg),
                              "generator": f"boxed_label:{MEASURE_VERSION}/{rr.RENDER_VERSION}",
                              "inputs": {"system_id": a["system_id"], "section": st.get("label_section"), "source": dict(st.get("label") or {}, **meta)}})
            lx_min = bx + bimg.shape[1] + int(round(0.5 * target_gap_px))
        # every atom's pixels on the finished line are exactly the resampled strip's pixels (rigid translation)
        for piece, px, py in checks:
            mismatched += int(np.any(canvas[py:py + piece.shape[0], px:px + piece.shape[1]] != piece, axis=-1).sum())
        line["height_px"] = height
        line["label_band_px"] = band
        line["staff_top_px"] = top
        images[line["id"]] = canvas
    moved = _move_line_start_numbers(lines_plan["lines"], by_id, strips, images, placed_at, target_gap_px)
    ledger = {"placements": placements, "scaffold_operations": scaffold_ops, "replicas": replicas, "labels": labels,
              "clef_removals": clef_removals, "render_mismatched_px": mismatched, "moved_measure_numbers": moved}
    _ledger_line_records(ledger, strips, placement_keys, replica_placements, generated, ledger_removed)
    for rec in generated:
        if rec["kind"] == "staff_scaffold":
            x0, y0, x1, y1 = rec["box_L"]
            rec["template"] = ledger_api.pack_crop(images[rec["line_id"]][y0:y1, x0:x1])
    return images, ledger


def _move_line_start_numbers(lines: Sequence[Dict[str, Any]], by_id: Dict[str, Dict[str, Any]], strips: Dict[str, Dict[str, Any]],
                             images: Dict[str, np.ndarray], placed_at: Dict[str, Tuple[int, List[int], int, int]],
                             target_gap_px: float) -> List[Dict[str, Any]]:
    """Jump-view strips: a line that starts at a barline whose measure number was printed over that
    barline gets the number at its start, above the staff (the first free spot within 2 staff gaps of
    the left edge); the number's pixels at the end of the previous line become paper. Runs after the
    per-line pixel checks; every move (or why a number stayed) is recorded."""
    out: List[Dict[str, Any]] = []
    for li in range(1, len(lines)):
        line, prev = lines[li], lines[li - 1]
        first = by_id[line["atom_ids"][0]]
        cn = first.get("carried_number")
        if not cn or first.get("break_before") != "safe_cut":
            continue
        rec: Dict[str, Any] = {"line_id": line["id"], "from_line_id": prev["id"], "unit_id": first["unit_id"],
                               "system_id": first["system_id"], "native_box": cn.get("native_box")}
        out.append(rec)
        if not cn.get("box_out"):
            rec.update(moved=False, reason=cn.get("refused"))
            continue
        last = prev["atom_ids"][-1]
        if last not in placed_at or _sk(by_id[last]) != _sk(first):
            rec.update(moved=False, reason="PREVIOUS_UNIT_NOT_PLAIN")
            continue
        X0n, Y0n, X1n, Y1n = cn["box_out"]
        x, idx, py, pr0 = placed_at[last]
        js = [j for j, c in enumerate(idx) if X0n <= c < X1n]
        old = images[prev["id"]]
        cy0, cy1 = py + Y0n - pr0, py + Y1n - pr0
        if not js or Y1n <= Y0n or cy0 < 0 or cy1 > old.shape[0]:
            rec.update(moved=False, reason="NUMBER_NOT_ON_PREVIOUS_LINE")
            continue
        cx0, cx1 = x + js[0], x + js[-1] + 1
        patch = old[cy0:cy1, cx0:cx1].copy()
        new = images[line["id"]]
        st = strips[_sk(first)]
        ny0 = int(line["staff_top_px"]) - int(round(st["top_out"])) + Y0n
        h, w = patch.shape[:2]
        if ny0 < 0 or ny0 + h > new.shape[0]:
            rec.update(moved=False, reason="NO_ROWS_AT_LINE_START")
            continue
        m = 2
        spot = None
        # at the number's own height if there is room, else raised by up to 2 staff gaps
        for ny in range(ny0, max(-1, ny0 - int(round(2 * target_gap_px)) - 1), -1):
            for nx in range(0, int(round(2 * target_gap_px)) + 1):
                if nx + w + m > new.shape[1]:
                    break
                if new[max(0, ny - m):ny + h, max(0, nx - m):nx + w + m].min() >= 245:
                    spot = (nx, ny)
                    break
            if spot is not None:
                break
        if spot is None:
            rec.update(moved=False, reason="NO_ROOM_AT_LINE_START")
            continue
        nx, ny = spot
        old[cy0:cy1, cx0:cx1] = 255
        new[ny:ny + h, nx:nx + w] = np.minimum(new[ny:ny + h, nx:nx + w], patch)
        rec.update(moved=True, from_box_out=[int(cx0), int(cy0), int(cx1), int(cy1)],
                   to_box_out=[int(nx), int(ny), int(nx + w), int(ny + h)], raised_px=int(ny0 - ny),
                   ink_px=int((patch.min(axis=-1) < 200).sum()))
        rec.update(strip_id=st.get("source_strip_id", first["system_id"]), src_bbox_R=[X0n, Y0n, X1n, Y1n])
    return out


AUTO_MIN_STAFF_GAP_MM = 1.2  # the automatic staff size never goes below this (DECISIONS "Automatic staff size")
AUTO_STEP_MM = 0.05  # sizes tried, on this grid, below the chosen size
# the search runs only for a dense chart: at least this many short lines and this share of all lines
# (one unavoidable short line, e.g. a multi-measure rest, never shrinks the whole chart)
AUTO_TRIGGER_MIN_SHORT = 2
AUTO_TRIGGER_MIN_SHARE = 0.05


def _plan_at(decided: Sequence[Dict[str, Any]], staff_gap_mm: float, *, context: Optional[Dict[str, Any]],
             locks: Sequence[Dict[str, Any]], job_id: str, revision: int, doc_cache: Dict[Any, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Atoms and line plan (no rendering) at one staff size."""
    content_w = rl.PAGE_W - 2 * rl.MARGIN_X
    built = build_atoms(decided, target_gap_px=staff_gap_mm * rl.MM, context=context, locks=locks, job_id=job_id,
                        revision=revision, line_width=content_w, doc_cache=doc_cache)
    doc = built["doc"]
    if doc["audit"]["validation"]["status"] != "valid":
        raise MeasurePlanUnavailable("UNITS_INVALID", {"errors": doc["audit"]["validation"]["errors"][:10]})
    forced = [{"type": "forced_line_break", "targets": [b["id"]], "id": f"floor/{b['id']}"}
              for b in doc["boundaries"] if b.get("floor_forced_break")]
    lines_plan = rlines.plan_document(built["atoms"], content_w, locks=list(locks) + forced)
    if not lines_plan["valid"]:
        raise MeasurePlanUnavailable("NO_FEASIBLE_LINE_BREAKS", {"conflicts": lines_plan["conflicts"]})
    return built, lines_plan


def staff_size_candidates(requested_mm: float) -> List[float]:
    """Sizes below ``requested_mm`` on the AUTO_STEP_MM grid, largest first, down to AUTO_MIN_STAFF_GAP_MM."""
    k = int(np.floor(round(requested_mm / AUTO_STEP_MM, 6)))
    out = []
    while True:
        mm = round(k * AUTO_STEP_MM, 2)
        if mm < AUTO_MIN_STAFF_GAP_MM - 1e-9:
            break
        if mm < requested_mm - 1e-9:
            out.append(mm)
        k -= 1
    return out


def choose_staff_size(requested_mm: float, short_at: Callable[[float], Optional[int]], short_requested: int) -> Tuple[float, List[Dict[str, Any]]]:
    """DECISIONS "Automatic staff size": the largest size on the grid that fills every line; if none does,
    the size with the fewest short lines, the larger on a tie (the requested size included).
    ``short_at(mm)`` is the number of short lines at a size (None: no plan there). Sizes are tried
    largest first and the search stops at the first size that fills every line."""
    tried = [{"staff_gap_mm": requested_mm, "short_lines": short_requested}]
    best = (short_requested, requested_mm)
    for mm in staff_size_candidates(requested_mm):
        n = short_at(mm)
        tried.append({"staff_gap_mm": mm, "short_lines": n})
        if n is None:
            continue
        if n < best[0]:
            best = (n, mm)
        if n == 0:
            break
    return best[1], tried


def compose(decided: Sequence[Dict[str, Any]], *, header: Optional[Dict[str, Any]], staff_gap_mm: float,
            context: Optional[Dict[str, Any]], locks: Iterable[Dict[str, Any]] = (), job_id: str = "job",
            revision: int = 0, auto_staff_size: bool = False, policy: str = "legacy",
            ledger_requested: bool = False) -> Tuple[Dict[str, Any], List[np.ndarray]]:
    """Measure-level plan and page rasters for the decided systems (see module doc).

    ``auto_staff_size`` (DECISIONS "Automatic staff size for dense charts"): when some line at
    ``staff_gap_mm`` stays short, smaller sizes down to AUTO_MIN_STAFF_GAP_MM are planned (atoms and
    line breaks only) and the chart is rendered once, at the size ``choose_staff_size`` picks. A
    chart whose lines are all full is planned and rendered exactly as without it. When no line plan
    exists at ``staff_gap_mm`` (a unit without a SAFE cut is wider than the line), the largest size
    on the same grid with a plan is used instead (reason ``UNITS_DO_NOT_FIT``, STRATEGY Step 2A),
    never below AUTO_MIN_STAFF_GAP_MM; the dense search then starts from that size.
    ``plan["staff_size"]`` records the size used and why."""
    if policy != "legacy":
        return _compose_bounded(decided, header=header, staff_gap_mm=staff_gap_mm, context=context,
                                locks=list(locks), job_id=job_id, revision=revision,
                                auto_staff_size=auto_staff_size, policy=policy, ledger_requested=ledger_requested)
    locks = list(locks)
    content_w = rl.PAGE_W - 2 * rl.MARGIN_X
    cache: Dict[Any, Any] = {}
    kw = dict(context=context, locks=locks, job_id=job_id, revision=revision, doc_cache=cache)
    requested = float(staff_gap_mm)
    # the size the plan starts from: the requested one, or (auto, STRATEGY Step 2A) the largest size on
    # the grid, not below AUTO_MIN_STAFF_GAP_MM, with a line plan when a unit that cannot be split (no
    # SAFE cut) is wider than the line at the requested size
    base = requested
    unfit: Optional[Dict[str, Any]] = None
    try:
        built, lines_plan = _plan_at(decided, requested, **kw)
    except MeasurePlanUnavailable as exc:
        if not auto_staff_size or exc.reason != "NO_FEASIBLE_LINE_BREAKS":
            raise
        unfit = {"reason": exc.reason, "detail": exc.detail or {}, "tried": [requested]}
        found = None
        for mm in staff_size_candidates(requested):
            unfit["tried"].append(mm)
            try:
                found = (mm, _plan_at(decided, mm, **kw))
            except MeasurePlanUnavailable as exc2:
                if exc2.reason != "NO_FEASIBLE_LINE_BREAKS":
                    raise
                continue
            break
        if found is None:
            raise MeasurePlanUnavailable(exc.reason, dict(unfit["detail"], sizes_tried=unfit["tried"],
                                                          auto_min_staff_gap_mm=AUTO_MIN_STAFF_GAP_MM))
        base, (built, lines_plan) = found
    short_req = len(lines_plan["ragged_exceptions"])
    size: Dict[str, Any] = {"staff_gap_mm": base, "staff_gap_mm_requested": requested, "auto_reduced": base < requested,
                            "short_lines_at_requested": None if unfit else short_req}
    if unfit:
        size["unfit_at_requested"] = {"reason": unfit["reason"], "conflicts": list(unfit["detail"].get("conflicts", []))[:10],
                                      "sizes_tried": unfit["tried"]}
        size["reason"] = "UNITS_DO_NOT_FIT"
        size["short_lines"] = short_req
    if not auto_staff_size:
        size["reason"] = "AUTO_OFF"
    elif not short_req:
        size.setdefault("reason", "LINES_FULL")
    elif short_req < AUTO_TRIGGER_MIN_SHORT or short_req < AUTO_TRIGGER_MIN_SHARE * len(lines_plan["lines"]):
        size.setdefault("reason", "FEW_SHORT_LINES")
    elif base <= AUTO_MIN_STAFF_GAP_MM + 1e-9:
        size.setdefault("reason", "AT_MINIMUM")
    else:
        plans: Dict[float, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
        fewest = [short_req]
        n_candidates = max(1, len(staff_size_candidates(base)))
        tried_sizes = [0]
        report_progress("sizing", 0.0)

        def short_at(mm: float) -> Optional[int]:
            # a background review export shows how far the search got and can stop between sizes
            report_progress("sizing", min(1.0, tried_sizes[0] / n_candidates))
            tried_sizes[0] += 1
            try:
                planned = _plan_at(decided, mm, **kw)
            except MeasurePlanUnavailable:
                return None
            n = len(planned[1]["ragged_exceptions"])
            if n < fewest[0]:  # only the best plan so far is kept (choose_staff_size's rule)
                plans.clear()
                plans[mm] = planned
                fewest[0] = n
            return n

        chosen, tried = choose_staff_size(base, short_at, short_req)
        size["candidates"] = tried
        if chosen == base:
            size.setdefault("reason", "NO_SMALLER_SIZE_HELPS")
        else:
            built, lines_plan = plans[chosen]
            size.update(staff_gap_mm=chosen, auto_reduced=True, reason="DENSE_LINES_NOT_FULL",
                        short_lines=len(lines_plan["ragged_exceptions"]))
    staff_gap_mm = float(size["staff_gap_mm"])
    report_progress("rendering")
    render_kw = {"ledger_requested": True} if ledger_requested else {}
    try:
        plan, pages = _render(built, lines_plan, header=header, staff_gap_mm=staff_gap_mm, content_w=content_w,
                              **render_kw)
    except MeasurePlanUnavailable as exc:
        if staff_gap_mm == base:
            raise
        # the smaller size could not be rendered: the size the search started from, as without it
        built, lines_plan = _plan_at(decided, base, **kw)
        plan, pages = _render(built, lines_plan, header=header, staff_gap_mm=base, content_w=content_w,
                              **render_kw)
        size.update(staff_gap_mm=base, auto_reduced=base < requested, reason="RENDER_FAILED_AT_REDUCED_SIZE",
                    render_error=exc.reason)
    plan["staff_gap_mm_requested"] = requested
    plan["staff_size"] = size
    plan["measure_reflow"]["staff_size"] = size
    return plan, pages


def _compose_bounded(decided: Sequence[Dict[str, Any]], *, header: Optional[Dict[str, Any]], staff_gap_mm: float,
                     context: Optional[Dict[str, Any]], locks: Sequence[Dict[str, Any]], job_id: str,
                     revision: int, auto_staff_size: bool, policy: str,
                     ledger_requested: bool = False) -> Tuple[Dict[str, Any], List[np.ndarray]]:
    from app.pipeline import reflow_optimize as opt
    cache: Dict[Any, Any] = {}
    native: Dict[str, Any] = {}

    def build_at(mm: float) -> Dict[str, Any]:
        report_progress("sizing", (mm - 1.2) / .4 if auto_staff_size else 0.)
        # Uniform staff size is a hard rule. Never invoke legacy per-unit OVERSIZE_FILL.
        built = build_atoms(decided, target_gap_px=mm * rl.MM, context=context, locks=locks,
                            job_id=job_id, revision=revision, line_width=None, doc_cache=cache)
        if built["doc"]["audit"]["validation"]["status"] != "valid":
            raise MeasurePlanUnavailable("UNITS_INVALID", {"errors": built["doc"]["audit"]["validation"]["errors"][:10]})
        if not native:
            key = (job_id, revision, tuple(d["system"]["id"] for d in decided))
            for sid, an in cache[key][1].items():
                regions = ([{"box": [int(x), int(y), int(x+w), int(y+h)], "pixels": int(area)}
                            for x, y, w, h, area in an.comp_stats[1:]] if an.comp_stats is not None else [])
                native[sid] = {"nonstaff": an.nonstaff, "regions": regions, "staff": an.staff}
        return built

    result = opt.optimize_document(build_at, requested_mm=staff_gap_mm, auto_size=auto_staff_size,
                                   header=header, policy=policy, locks=locks, native_protection=native)
    if not result["valid"]:
        raise MeasurePlanUnavailable("BOUNDED_CAPACITY_LIMIT", {k: v for k, v in result.items() if k != "built"})
    chosen = result["staff_gap_mm"]
    plan, pages = _render(result["built"], result["lines_plan"], header=header, staff_gap_mm=chosen,
                          content_w=rl.PAGE_W-2*rl.MARGIN_X, ledger_requested=ledger_requested)
    size = {"staff_gap_mm": chosen, "staff_gap_mm_requested": staff_gap_mm,
            "auto_reduced": chosen < staff_gap_mm, "auto_enlarged": chosen > staff_gap_mm,
            "reason": "BOUNDED_DOCUMENT_OBJECTIVE" if auto_staff_size else "EXPLICIT_SIZE_FIXED",
            "candidates": result["candidates"]}
    plan.update(staff_gap_mm_requested=staff_gap_mm, staff_size=size)
    plan["measure_reflow"].update(staff_size=size, optimizer=result["lines_plan"]["optimizer"])
    return plan, pages


def _bind_ledger_pages(plan: dict, images: dict, ledger: dict, *, ledger_requested: bool) -> None:
    placed = {pl["system_id"]: (pi, pl) for pi, p in enumerate(plan["pages"]) for pl in p["placements"]}
    for rec in ledger["ledger_placements"]:
        pi, pl = placed[rec["line_id"]]
        h, w = images[rec["line_id"]].shape[:2]
        sx, sy = float(pl["w"]) / w, float(pl["h"]) / h
        if ledger_requested and abs(sx - sy) > .002:
            raise MeasurePlanUnavailable("NONUNIFORM_PAGE_SCALE", {"line_id": rec["line_id"], "scale_xy": [sx, sy]})
        rec["page_index"] = pi
        rec["stages"][1] = rr.page_placement_transform(pl, (h, w))
    resized: Dict[str, np.ndarray] = {}
    for rec in ledger["generated_origins"]:
        lid = rec["line_id"]
        pi, pl = placed[lid]
        if lid not in resized:
            resized[lid] = rr.resize_strip(rr._to_page_paper(images[lid]), pl["w"], pl["h"])
        h, w = images[lid].shape[:2]
        sx, sy = float(pl["w"]) / w, float(pl["h"]) / h
        x0, y0, x1, y1 = rec["box_L"]
        # Project pixel boundaries, rather than rounding transformed centres.
        a, b = max(0, int(np.floor(x0 * sx))), max(0, int(np.floor(y0 * sy)))
        c, d = min(pl["w"], int(np.ceil(x1 * sx))), min(pl["h"], int(np.ceil(y1 * sy)))
        if rec["kind"] == "section_label":
            rec["template_L"] = rec["template"]
        rec.update(page_index=pi, origin=[pl["x"] + a, pl["y"] + b],
                   template=ledger_api.pack_crop(resized[lid][b:d, a:c]))
        if rec["kind"] == "staff_scaffold":
            rec["staff_rows_local"] = [float(r) * sy + (sy - 1) / 2 - b for r in rec["staff_rows_local"]]
        rec["inputs"]["line_to_page"] = rr.page_placement_transform(pl, (h, w))["matrix"]
        rec["line_resample"] = rr.page_placement_transform(pl, (h, w))["resample"]


def _render(built: Dict[str, Any], lines_plan: Dict[str, Any], *,
            header: Optional[Dict[str, Any]], staff_gap_mm: float, content_w: int,
            ledger_requested: bool = False) -> Tuple[Dict[str, Any], List[np.ndarray]]:
    """Records are returned in built and plan['measure_reflow'] under ledger_placements,
    ledger_removed and generated_origins. Set ledger_requested to enforce page uniformity.
    """
    target_gap = staff_gap_mm * rl.MM
    atoms, strips, doc = built["atoms"], built["strips"], built["doc"]
    edge = dict(lines_plan["edge"])
    images, ledger = render_lines(atoms, strips, lines_plan, target_gap_px=target_gap)
    _ledger_beam_copies(ledger, strips)
    if lines_plan.get("policy") in ("A", "B"):
        from app.pipeline import reflow_optimize as opt
        opt.finalize_endpoint_flags(lines_plan, built, images, staff_gap_mm, lines_plan.get("alternative_groupings", []))
    widest = max(int(im.shape[1]) for im in images.values())
    # the block of lines is centred between the margins (the teacher reference has equal margins)
    x_offset = (0 if lines_plan.get("policy") in ("A", "B") else
                max(0, min((content_w - int(edge["width"])) // 2, content_w - widest)))
    edge["x_offset_px"] = x_offset
    units = [{"id": ln["id"], "width": int(images[ln["id"]].shape[1]), "height": int(images[ln["id"]].shape[0]),
              "staff_gap_px": target_gap} for ln in lines_plan["lines"]]
    # incomplete chart: a missing-interval marker goes only at a line break between the systems
    # placed before and after the interval (reflow_render.layout_markers)
    sys_of_atom = {a["id"]: a["system_id"] for a in atoms}
    markers, missing = rr.layout_markers(header, [(ln["id"], list(dict.fromkeys(sys_of_atom[x] for x in ln["atom_ids"] if x in sys_of_atom)))
                                                  for ln in lines_plan["lines"]])
    plan = rl.plan_pages(units, header_height_px=rr.header_height(header), staff_gap_mm=staff_gap_mm, x_offset_px=x_offset,
                         markers=markers)
    title, credits = rr.header_lines(header)
    plan["header"] = {"title": title, "credits": credits}
    rr.attach_incomplete(plan, header, missing)
    plan["render_version"] = rr.RENDER_VERSION
    generated = []
    pages = rr.render_pages(plan, images, header=header, generated=generated)
    line_by = {ln["id"]: ln for ln in lines_plan["lines"]}
    for p in plan["pages"]:
        for pl in p["placements"]:
            ln = line_by[pl["system_id"]]
            pl["line_id"] = ln["id"]
            pl["unit_ids"] = list(ln["atom_ids"])
            pl["system_ids"] = list(dict.fromkeys(by["system_id"] for by in atoms if by["id"] in set(ln["atom_ids"])))
    _bind_ledger_pages(plan, images, ledger, ledger_requested=ledger_requested)
    ledger["generated_origins"].extend(generated)
    for key in ("ledger_placements", "ledger_removed", "generated_origins"):
        built[key] = ledger[key]
    plan["ragged_lines"] = "measure reflow: see measure_reflow.ragged_exceptions"
    plan["measure_reflow"] = report(doc, atoms, lines_plan, ledger, built["trims"], strips)
    for key in ("ledger_placements", "ledger_removed", "generated_origins"):
        plan["measure_reflow"][key] = ledger[key]
    # why a source system could not continue mid-line (its line start is then forced)
    plan["measure_reflow"]["audit"]["join_refusals"] = built.get("join_refusals", [])
    plan["measure_reflow"]["justified_edge"] = edge
    forced = [{"boundary_id": b["id"], "system_id": b["system_id"], "reasons": list(b["reason_codes"]),
               "evidence": b["floor_break_evidence"]}
              for b in doc["boundaries"] if b.get("floor_forced_break")]
    if forced:
        plan["measure_reflow"]["forced_breaks"] = forced
    flag_line_sizes(plan, atoms=atoms, strips=strips)
    return plan, pages


def flag_line_sizes(plan: Dict[str, Any], *, atoms: Sequence[Dict[str, Any]] = (),
                    strips: Optional[Dict[str, Dict[str, Any]]] = None,
                    systems: Sequence[Dict[str, Any]] = ()) -> None:
    """Attach review findings after rendering, so retained small output stays exportable.

    No keys are added for ordinary documents. Use actual resampling scales, not rounded
    oversize factors. Whole-system/fallback output is checked against its source gap.
    """
    by_atom = {a["id"]: a for a in atoms}
    by_system = {s["id"]: s for s in systems}
    measured = plan.get("measure_reflow") or {}
    forced = measured.get("forced_breaks") or []
    findings = []
    for page in plan.get("pages", []):
        for pl in page["placements"]:
            if atoms:
                placed = [by_atom[uid] for uid in pl.get("unit_ids", [])]
                mm = min((strips[_sk(a)]["gap_src"] * strips[_sk(a)]["scale"] / rl.MM
                          for a in placed), default=float(plan["staff_gap_mm"])) * float(pl["scale"])
                sids = list(pl.get("system_ids", []))
            else:
                sids = [pl["system_id"]]
                source = by_system.get(pl["system_id"])
                mm = (float(source["strip"]["staff_gap_px"]) * float(pl["scale"]) / rl.MM
                      if source else float(plan["staff_gap_mm"]))
            codes = []
            if any(f["system_id"] in sids for f in forced):
                codes.append("FORCED_LINE_BREAK")
            if mm < AUTO_MIN_STAFF_GAP_MM - 1e-9:
                codes.append("LINE_BELOW_MIN_SIZE")
                findings.append({"code": "LINE_BELOW_MIN_SIZE", "line_id": pl["system_id"],
                                 "system_ids": sids, "effective_staff_gap_mm": round(mm, 6),
                                 "minimum_staff_gap_mm": AUTO_MIN_STAFF_GAP_MM})
            if codes:
                pl["effective_staff_gap_mm"] = round(mm, 6)
                pl["issues"] = list(dict.fromkeys(pl.get("issues", []) + codes))
                for sid in sids:
                    if sid in by_system:
                        s = by_system[sid]
                        s["issues"] = list(dict.fromkeys(s.get("issues", []) + codes))
                        if "LINE_BELOW_MIN_SIZE" in codes:
                            s["effective_staff_gap_mm"] = min(mm, s.get("effective_staff_gap_mm", mm))
    if findings:
        validation = plan["validation"]
        validation.setdefault("issues", []).extend(findings)
        validation["review_required"] = True
        if measured.get("audit"):
            v = measured["audit"]["validation"]
            v.setdefault("issues", []).extend(findings)
            v["review_required"] = True


def _justification_summary(lines: Sequence[Dict[str, Any]], slots: Sequence[Dict[str, Any]],
                           ops: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-document justification figures: how many lines reach the edge and how much any gap grew."""
    grown = sorted(s["growth_ratio"] for s in slots if s["applied_delta"] > 0)
    shrunk = sorted(s["growth_ratio"] for s in slots if s["applied_delta"] < 0)
    adj = [ln["adjustment_fraction"] for ln in lines]
    ins = [op for op in ops if op["op"] == "insert_spread_columns"]
    wide = [ln for ln in lines if ln.get("justify_tier") == 2]
    free = [ln for ln in lines if ln.get("justify_tier") == 3]
    widths = [ln["achieved_width"] for ln in lines]
    edge = lines[0]["target_width"] if lines else 0
    return {"lines": len(lines), "lines_justified": sum(1 for ln in lines if ln["justified"]),
            "lines_wider_caps": [ln["id"] for ln in wide],
            "max_gap_growth_wider_caps": max((ln["max_gap_growth"] for ln in wide), default=0.0),
            # Every line full: lines that needed the even spread beyond the wider caps, and how far it went
            "lines_tier3_spread": [{"line_id": ln["id"], "adjustment_fraction": ln["adjustment_fraction"],
                                    "max_gap_growth": ln["max_gap_growth"]} for ln in free],
            "lines_below_98pct": sum(1 for w in widths if edge and w < 0.98 * edge),
            "min_fill": round(min(widths) / float(edge), 4) if widths and edge else None,
            "max_gap_growth": grown[-1] if grown else 0.0, "median_gap_growth": grown[len(grown) // 2] if grown else 0.0,
            "max_gap_shrink": shrunk[0] if shrunk else 0.0,
            "max_line_expansion": max(adj) if adj else 0.0, "max_line_contraction": min(adj) if adj else 0.0,
            "spread_insertions": len(ins), "spread_inserted_px": sum(op["columns"] for op in ins),
            "level_beam_insertions": sum(1 for op in ins if op.get("column_kind") == "level_beam"),
            "spread_removals": sum(1 for op in ops if op["op"] == "remove_spread_columns")}


def report(doc: Dict[str, Any], atoms: Sequence[Dict[str, Any]], lines_plan: Dict[str, Any], ledger: Dict[str, Any],
           trims: Sequence[Dict[str, Any]], strips: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The measure-reflow record kept in the page plan (units, boundaries, lines, slots, ledgers)."""
    placed = [p["unit_id"] for p in ledger["placements"]]
    expected = [a["unit_id"] for a in atoms]
    lines = lines_plan["lines"]
    known = [ln["measure_count"] for ln in lines if ln["measure_count"] is not None]
    dist: Dict[str, int] = {}
    bounded = lines_plan.get("policy") in ("A", "B")
    for ln in lines:
        key = str(ln["measure_count"]) if ln["measure_count"] is not None else "unknown"
        dist[key] = dist.get(key, 0) + 1
    # barline-group estimate (internal boundaries + 1 per unit); a report figure, never a measure count
    ub = {u["id"]: u for u in doc["measure_units"]}
    est: Dict[str, int] = {}
    for ln in lines:
        e = sum(len(ub[a]["internal_boundary_ids"]) + 1 for a in ln["atom_ids"] if a in ub)
        ln["measure_count_estimate"] = e
        est[str(e)] = est.get(str(e), 0) + 1
    slots = lines_plan["slots"]
    validation_errors = []
    if placed != expected:
        validation_errors.append("units not placed exactly once in order")
    if ledger["render_mismatched_px"]:
        validation_errors.append(f"{ledger['render_mismatched_px']} rendered pixel(s) differ from the resampled strip")
    if any(op.get("nonstaff_ink_removed") or op.get("nonstaff_ink_in_source_column") for op in ledger["scaffold_operations"]):
        validation_errors.append("a scaffold operation touched non-staff ink")
    if any(op["op"] in ("insert_spread_columns", "remove_spread_columns") and not op.get("eligible")
           for op in ledger["scaffold_operations"]):
        validation_errors.append("a spread operation used a column that is not verified whitespace")
    if any(t["protected_px"] for t in trims):
        validation_errors.append("a margin trim removed protected ink")
    for cr in ledger.get("clef_removals", []):
        if cr.get("changed_outside_mask_px") or cr.get("removed_nonstaff_not_clef_px") or cr.get("resampled_changed_outside_clef_px") \
                or cr.get("residue_px") or not cr.get("verified"):
            validation_errors.append(f"{cr.get('line_id')}: clef removal changed more than the clef")
    if not all(s["within_caps"] for s in slots):
        validation_errors.append("a slot delta exceeds its cap")
    if bounded:
        packages: Dict[str, Dict[str, Any]] = {}
        for slot in slots:
            key = slot.get("cap_unit_id") or slot["id"]
            caps = slot.get("package_caps_out") or [slot["max_expand"], slot["max_contract"]]
            group = packages.setdefault(key, {"expand": 0, "contract": 0, "caps": caps})
            group["expand"] += max(0, slot["applied_delta"])
            group["contract"] += max(0, -slot["applied_delta"])
        for key, group in packages.items():
            if group["expand"] > group["caps"][0] or group["contract"] > group["caps"][1]:
                validation_errors.append(f"{key}: joint corridor package cap exceeded")
    for ln in lines:
        lim = float("inf") if ln.get("justify_tier") == 3 else rlines.WIDE_MAX_EXPAND_FRACTION if ln.get("justify_tier") == 2 \
            else rlines.MAX_EXPAND_FRACTION
        if not bounded and ln["natural_width"] and (ln["adjustment_fraction"] > lim + 1e-9
                                    or ln["adjustment_fraction"] < -rlines.MAX_CONTRACT_FRACTION - 1e-9):
            validation_errors.append(f"{ln['id']}: adjustment outside {lim:.0%}/{rlines.MAX_CONTRACT_FRACTION:.0%}")
        if ln["justified"] and abs(ln["achieved_width"] - ln["target_width"]) > 1:
            validation_errors.append(f"{ln['id']}: justified edge residual > 1 px")
    tot = doc["audit"]["accounting"]["totals"]
    return {
        "version": MEASURE_VERSION,
        "lines_version": lines_plan.get("version", rlines.LINES_VERSION),
        "units_schema_version": doc["schema_version"],
        "analysis_hash": doc["analysis_hash"],
        "config_hash": doc["config_hash"],
        "algorithm": doc["algorithm"],
        "included_occurrence_ids": doc["included_occurrence_ids"],
        "units": [{k: u[k] for k in ("id", "kind", "occurrence_id", "system_id", "measure_count", "box", "left_boundary_id",
                                      "right_boundary_id", "internal_boundary_ids", "flags")} for u in doc["measure_units"]
                  if u["kind"] in ("measure", "locked_group", "system")],
        "boundaries": [{"id": b["id"], "system_id": b["system_id"], "seam_x": b["seam_x"], "class": b["class"],
                        "reason_codes": b["reason_codes"], "is_cut": b.get("is_cut"),
                        **({"floor_break_evidence": b["floor_break_evidence"]} if "floor_break_evidence" in b else {})}
                       for b in doc["boundaries"] if b["kind"] == "barline"],
        "boundary_counts": doc["stats"]["boundaries"],
        "lines": lines,
        "justification_slots": slots,
        "ragged_exceptions": lines_plan["ragged_exceptions"],
        "conflicts": lines_plan["conflicts"] + doc["audit"]["conflicts"],
        "justification": _justification_summary(lines, slots, ledger["scaffold_operations"]),
        "measures_per_line": dist,
        "measures_per_line_estimated": est,
        "measures_known_lines": len(known),
        "oversize_units": [{"atom_id": a["id"], "system_id": a["system_id"], **a["oversize"]} for a in atoms if a.get("oversize")],
        "prefixes": {sid: {"verified_clef_replica": bool(st["replica"]), "prefix_free": st["prefix_free"],
                           "reason": st["prefix"].get("reason")} for sid, st in strips.items()},
        "variants": {sid: st["variant"] for sid, st in strips.items()},
        "labels": ledger["labels"],
        "joins": {"lines": len(lines), "joined_systems": sum(len(ln.get("joined_system_ids") or []) for ln in lines),
                  "lines_starting_inside_a_system": sum(1 for ln in lines if ln.get("starts_inside_system")),
                  "clefs_removed": len(ledger.get("clef_removals", [])),
                  "refused": {sid: (st.get("join") or {}).get("refused") for sid, st in strips.items()
                              if (st.get("join") or {}).get("refused")},
                  "page_fill": [ln.get("page_fill") for ln in lines]},
        "audit": {
            "native_accounting": {k: tot[k] for k in ("assets", "pixels", "lost_px", "duplicated_px", "mismatched_px",
                                                       "protected_px", "protected_lost_px", "protected_duplicated_px",
                                                       "exact_reconstruction")},
            "placements": ledger["placements"],
            "replicas": ledger["replicas"],
            "clef_removals": ledger.get("clef_removals", []),
            "scaffold_operations": ledger["scaffold_operations"] + list(trims),
            "render_mismatched_px": ledger["render_mismatched_px"],
            # jump-view strips: measure numbers moved from a line end to the next line's start
            "moved_measure_numbers": ledger.get("moved_measure_numbers", []),
            "units_placed_once_in_order": placed == expected,
            "validation": {"valid": not validation_errors, "errors": validation_errors},
        },
    }
