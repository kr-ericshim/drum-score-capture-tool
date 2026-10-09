"""A4 page plan for the clean reflow chart (output model ``clean_reflow_v1``).

Units in this slice are whole cleaned system strips (reflow_strips.py); a
strip is never split, sliced or stretched. Measure splitting is a later phase.

* Page: A4 portrait at 300 dpi (2480 x 3508 px), margins 15 mm left/right and
  14 mm top/bottom (design section 4 defaults).
* Staff size: every strip is scaled isotropically so its staff gap becomes the
  document staff gap (default 1.5 mm = 17.72 px). The size is never reduced
  automatically. A strip that is wider than the line or taller than a page at
  that size is a layout conflict: the plan lists it (with the largest staff
  size at which it would fit) and is invalid; ``require_valid_plan`` refuses
  to render it. The user resolves it by excluding the system or by choosing a
  smaller staff size for the document (an explicit option). Nothing is cut and
  nothing is stretched in one direction only.
* One system per line, left aligned at the margin. Lines are separated by at
  least ``MIN_SEP_GAPS`` staff gaps of white space beyond the strips' own
  padding; on full pages the leftover height is spread between lines (capped),
  on the last page the spacing is capped at 2.5 gaps.
* Page breaks never divide a line. A last page with a single line takes one
  line from the previous page when that page has at least three and the last
  page has room for it.
* Page 1 carries the header band (title, credits); pages from 2 on carry a
  page number at the bottom left. No footer text.
* ``markers`` (incomplete chart, reflow_render.layout_markers): one-row boxes placed in the
  line flow after a given unit (``after`` None: before the first). They take height and
  separation like a line, across the content width, and are listed per page under
  ``markers``; units never overlap them. Without markers the plan is unchanged.
  A source-clipped local notice has ``keep_with_previous`` and stays with the affected
  line instead of the next line. Its height is reserved by the same flow/overflow checks.
* ``append_trailing_rows`` (incomplete chart with more unresolved intervals than the page-1
  notice holds, reflow_render.attach_incomplete): rows of text after the last line, on the
  last page when they fit there, else on added pages (page numbers continue). They are listed
  per page under ``appendix``, take part in the overflow and overlap checks, and count in the
  page count. A page holding only appendix rows comes after every page with a line.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

LAYOUT_VERSION = "reflow_layout-1"
DPI = 300
PAGE_W, PAGE_H = 2480, 3508
MM = DPI / 25.4
MARGIN_X = int(round(15 * MM))
MARGIN_TOP = int(round(14 * MM))
MARGIN_BOTTOM = int(round(14 * MM))
DEFAULT_STAFF_GAP_MM = 1.5
MIN_SEP_GAPS = 0.5
MAX_EXTRA_SEP_GAPS = 2.0
LAST_PAGE_MAX_SEP_GAPS = 2.5
HEADER_GAP_MM = 5.0
LOW_EFFECTIVE_DPI = 180.0
LOW_SOURCE_GAP_PX = 8.0
MIN_STAFF_GAP_MM = 1.0  # smallest size a user may choose (schemas: JobOptions.staff_gap_mm)


class LayoutConflictError(RuntimeError):
    """The plan cannot be rendered at the chosen staff size (see ``plan["conflicts"]``)."""

    def __init__(self, plan: Dict[str, Any]):
        self.plan = plan
        conflicts = plan.get("conflicts", [])
        names = ", ".join(c["system_id"] for c in conflicts) or "none"
        reason = "; ".join(plan.get("validation", {}).get("errors", [])) or "invalid plan"
        super().__init__(f"layout conflict at {plan.get('staff_gap_mm_requested')} mm staff size "
                         f"(systems: {names}; {reason})")


def _floor_mm(value: float) -> float:
    return math.floor(value * 100.0 + 1e-6) / 100.0


def require_valid_plan(plan: Dict[str, Any]) -> None:
    """Raise LayoutConflictError unless the plan accounts for every unit once, in
    order, inside the printable area, without overlaps or conflicts."""
    v = plan.get("validation") or {}
    if plan.get("conflicts") or not v.get("valid"):
        raise LayoutConflictError(plan)


def plan_pages(units: Sequence[Dict[str, Any]], *, header_height_px: int = 0,
               staff_gap_mm: float = DEFAULT_STAFF_GAP_MM, x_offset_px: int = 0,
               markers: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Page plan for ``units`` (in order): each ``{id, width, height, staff_gap_px}`` in strip pixels.
    ``x_offset_px`` moves every line right of the left margin (measure reflow centres its block of
    justified lines); a unit that would then cross the right margin is a layout conflict."""
    content_w = PAGE_W - 2 * MARGIN_X
    content_h = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
    header_band = int(header_height_px + (HEADER_GAP_MM * MM if header_height_px else 0))
    target_gap = staff_gap_mm * MM
    exceptions: List[Dict[str, Any]] = []
    if not units:
        return {"version": LAYOUT_VERSION, "page_px": [PAGE_W, PAGE_H], "dpi": DPI, "staff_gap_mm": staff_gap_mm,
                "staff_gap_mm_requested": staff_gap_mm, "staff_gap_px": round(target_gap, 3), "pages": [], "exceptions": [],
                "conflicts": [], "header_band_px": header_band, "validation": validate_plan({"pages": []}, [])}
    gap = target_gap
    sized = []
    conflicts: List[Dict[str, Any]] = []
    for u in units:
        s = gap / float(u["staff_gap_px"])
        w = int(round(u["width"] * s))
        h = int(round(u["height"] * s))
        # Never shrink: a strip that does not fit at the chosen size is a conflict.
        too_wide = w > content_w - max(0, int(x_offset_px))
        too_tall = h > content_h
        if too_wide or too_tall:
            fit = min(content_w / (u["width"] / float(u["staff_gap_px"])), content_h / (u["height"] / float(u["staff_gap_px"])))
            fit_mm = _floor_mm(fit / MM)
            conflicts.append({"system_id": u["id"], "kind": "too_wide" if too_wide else "too_tall",
                              "size_px": [w, h], "max_px": [content_w, content_h],
                              "largest_fitting_staff_gap_mm": fit_mm if fit_mm >= MIN_STAFF_GAP_MM else None})
        eff_dpi = DPI / s if s > 0 else 0.0
        issues = []
        if eff_dpi < LOW_EFFECTIVE_DPI or float(u["staff_gap_px"]) < LOW_SOURCE_GAP_PX:
            issues.append("LOW_SOURCE_RESOLUTION")
        if too_wide or too_tall:
            issues.append("LAYOUT_CONFLICT")
        sized.append({"id": u["id"], "w": w, "h": h, "scale": s, "effective_source_dpi": round(eff_dpi, 1), "issues": issues})

    min_sep = MIN_SEP_GAPS * gap
    flow: List[Dict[str, Any]] = list(sized)
    if markers:
        unit_ids = [it["id"] for it in sized]
        for mk in markers:
            at = 0 if mk.get("after") is None else (unit_ids.index(mk["after"]) + 1 if mk["after"] in unit_ids else None)
            if at is None:
                continue
            # after the at-th unit and after any marker already placed there
            pos, seen = 0, 0
            while seen < at:
                seen += 0 if flow[pos].get("marker") else 1
                pos += 1
            while pos < len(flow) and flow[pos].get("marker"):
                pos += 1
            flow.insert(pos, {"id": mk["id"], "marker": dict(mk), "w": content_w, "h": int(mk["h"])})
    # pagination blocks: a marker keeps with the unit after it (the last one with the unit before
    # it), so no page starts or ends with a marker alone and no page holds only a marker
    blocks: List[Dict[str, Any]] = []
    last_unit = max(i for i, x in enumerate(flow) if not x.get("marker"))
    for i, it in enumerate(flow):
        previous_marker = blocks[-1]["items"][-1].get("marker") if blocks else None
        keep_previous = (it.get("marker") or {}).get("keep_with_previous")
        if blocks and (keep_previous or (previous_marker and not previous_marker.get("keep_with_previous")) or i > last_unit):
            blocks[-1]["items"].append(it)
        else:
            blocks.append({"items": [it]})
    for b in list(blocks):
        b["h"] = sum(x["h"] for x in b["items"]) + min_sep * (len(b["items"]) - 1)
        if len(b["items"]) > 1 and b["h"] > content_h:
            k = blocks.index(b)  # too tall together: lay the items out one by one
            blocks[k:k + 1] = [{"items": [x], "h": x["h"]} for x in b["items"]]
    pages: List[List[Dict[str, Any]]] = [[]]
    used = header_band
    avail = content_h
    for bl in blocks:
        need = bl["h"] + (min_sep if pages[-1] else 0)
        if pages[-1] and used + need > avail:
            pages.append([])
            used = 0
            need = bl["h"]
        elif not pages[-1] and len(pages) == 1 and header_band and used + need > avail >= bl["h"]:
            # taller than the room under the header but fits a full page: start on page 2
            pages.append([])
            used = 0
        pages[-1].append(bl)
        used += need
    if len(pages) >= 2 and len(pages[-1]) == 1 and len(pages[-2]) >= 3:
        # widow: move one line down only when the last page has room for both
        moved, last = pages[-2][-1], pages[-1][0]
        if moved["h"] + min_sep + last["h"] <= avail:
            pages[-1].insert(0, pages[-2].pop())
    pages = [[x for bl in pg for x in bl["items"]] for pg in pages]

    out_pages = []
    for pi, items in enumerate(pages):
        top = MARGIN_TOP + (header_band if pi == 0 else 0)
        room = content_h - (header_band if pi == 0 else 0)
        heights = sum(i["h"] for i in items)
        n = len(items)
        last = pi == len(pages) - 1
        sep = min_sep
        if n > 1:
            spread = (room - heights) / float(n - 1)
            cap = LAST_PAGE_MAX_SEP_GAPS * gap if last else (MIN_SEP_GAPS + MAX_EXTRA_SEP_GAPS) * gap
            sep = max(min_sep, min(spread, cap))
        y = float(top)
        placements = []
        page_markers = []
        for it in items:
            if it.get("marker"):
                mk = it["marker"]
                page_markers.append({"id": mk["id"], "x": MARGIN_X, "y": int(round(y)), "w": it["w"], "h": it["h"],
                                     "text": mk.get("text", ""), "start": mk.get("start"), "end": mk.get("end"),
                                     **({"kind": mk["kind"], "system_ids": mk.get("system_ids", [])} if mk.get("kind") else {})})
                y += it["h"] + sep
                continue
            placements.append({"system_id": it["id"], "x": MARGIN_X + max(0, int(x_offset_px)), "y": int(round(y)), "w": it["w"], "h": it["h"],
                               "scale": round(it["scale"], 6), "effective_source_dpi": it["effective_source_dpi"],
                               "issues": it["issues"]})
            y += it["h"] + sep
        out_pages.append({"index": pi + 1, "placements": placements, "page_number": pi + 1 if pi >= 1 else None,
                          "header": pi == 0 and header_band > 0, "line_sep_px": round(sep, 2)})
        if page_markers:
            out_pages[-1]["markers"] = page_markers
    plan = {
        "version": LAYOUT_VERSION,
        "page_px": [PAGE_W, PAGE_H],
        "dpi": DPI,
        "margins_px": {"left": MARGIN_X, "right": MARGIN_X, "top": MARGIN_TOP, "bottom": MARGIN_BOTTOM},
        "staff_gap_mm": round(gap / MM, 4),
        "staff_gap_mm_requested": staff_gap_mm,
        "conflicts": conflicts,
        "staff_gap_px": round(gap, 3),
        "header_band_px": header_band,
        "pages": out_pages,
        "exceptions": exceptions,
        "ragged_lines": "all lines are whole systems at natural width (left aligned); no glyph stretching",
    }
    plan["validation"] = validate_plan(plan, [u["id"] for u in units])
    if conflicts:
        plan["validation"]["valid"] = False
        plan["validation"]["errors"].append(f"{len(conflicts)} system(s) do not fit the page at {staff_gap_mm} mm")
    return plan


def validate_plan(plan: Dict[str, Any], unit_ids: Sequence[str]) -> Dict[str, Any]:
    """Every unit placed exactly once, inside the content area, without overlaps."""
    placed: List[str] = []
    overflow = 0
    overlaps = 0
    for p in plan.get("pages", []):
        top = MARGIN_TOP + (plan.get("header_band_px", 0) if p.get("header") else 0)
        prev_bottom: Optional[int] = None
        extra = [(mk, True) for mk in p.get("markers", [])] + [(row, True) for row in p.get("appendix", [])]
        boxes = sorted([(pl, False) for pl in p["placements"]] + extra,
                       key=lambda b: b[0]["y"]) if extra else [(pl, False) for pl in p["placements"]]
        for pl, is_marker in boxes:
            if not is_marker:
                placed.append(pl["system_id"])
            if pl["x"] < MARGIN_X or pl["x"] + pl["w"] > PAGE_W - MARGIN_X or pl["y"] < top or pl["y"] + pl["h"] > PAGE_H - MARGIN_BOTTOM:
                overflow += 1
            if prev_bottom is not None and pl["y"] < prev_bottom:
                overlaps += 1
            prev_bottom = pl["y"] + pl["h"]
    missing = [u for u in unit_ids if u not in placed]
    dup = sorted({u for u in placed if placed.count(u) > 1})
    accounted = not missing and not dup and placed == list(unit_ids)
    errors = []
    if not accounted:
        errors.append(f"units not placed exactly once in order (missing {len(missing)}, duplicated {len(dup)})")
    if overflow:
        errors.append(f"{overflow} placement(s) outside the printable area")
    if overlaps:
        errors.append(f"{overlaps} overlapping placement(s)")
    return {"content_accounted_for": accounted, "missing": missing, "duplicated": dup,
            "overflow_count": overflow, "overlap_count": overlaps, "order_preserved": placed == list(unit_ids),
            "valid": not errors, "errors": errors}


def append_trailing_rows(plan: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> List[int]:
    """Place ``rows`` (each ``{id, h, ...}``, in order) after the last line of a valid ``plan``.

    Rows go under the last page's content (``HEADER_GAP_MM`` of separation)
    while they fit above the bottom margin; the rest go on added pages from the top margin.
    Each row is recorded on its page under ``appendix`` as a box across the content width
    (``x``, ``y``, ``w``, ``h`` plus the row's own fields). The validation is run again. An
    invalid plan, or one without pages, is left as it is (it is refused before rendering).
    Returns the indices of the pages that hold rows."""
    pages = plan.get("pages") or []
    if not rows or not pages or plan.get("conflicts") or not (plan.get("validation") or {}).get("valid"):
        return []
    unit_ids = [pl["system_id"] for p in pages for pl in p["placements"]]
    content_w = PAGE_W - 2 * MARGIN_X
    bottom = PAGE_H - MARGIN_BOTTOM
    sep = MIN_SEP_GAPS * float(plan.get("staff_gap_px") or DEFAULT_STAFF_GAP_MM * MM)
    last = pages[-1]
    boxes = list(last["placements"]) + list(last.get("markers", [])) + list(last.get("appendix", []))
    if boxes:
        # set off from the last line like the header band from the first (HEADER_GAP_MM)
        y = max(b["y"] + b["h"] for b in boxes) + int(math.ceil(max(sep, HEADER_GAP_MM * MM)))
    else:
        y = MARGIN_TOP + (int(plan.get("header_band_px", 0)) if last.get("header") else 0)
    page = last
    used: List[int] = []
    for row in rows:
        h = int(row["h"])
        if y + h > bottom:
            index = len(pages) + 1
            page = {"index": index, "placements": [], "page_number": index if index >= 2 else None,
                    "header": False, "line_sep_px": round(sep, 2)}
            pages.append(page)
            y = MARGIN_TOP
        page.setdefault("appendix", []).append(dict(row, x=MARGIN_X, y=int(y), w=content_w, h=h))
        if page["index"] not in used:
            used.append(page["index"])
        y += h
    plan["validation"] = validate_plan(plan, unit_ids)
    return used
