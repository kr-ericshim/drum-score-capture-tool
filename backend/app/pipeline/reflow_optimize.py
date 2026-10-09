"""Step 2C-O: SAFE-only, native-pixel bounded spacing and document size search.

This module never changes source pixels. A physical whitespace corridor has one
budget, even when multiple renderer slots describe it. Unknown measure counts
remain unknown; their frozen barline estimate is an explicitly labelled divisor.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_layout as layout
from app.pipeline import reflow_lines as legacy
from app.pipeline import reflow_render as render

VERSION = "reflow_optimize-2"
CONFIGS = {"A1": ("A", 4), "A2": ("A", 8), "B1": ("B", 4), "B2": ("B", 8)}
SIZE_GRID = tuple(round(1.2 + .025 * k, 3) for k in range(17))


def policy_config(policy: str, lambda_u: Optional[float] = None) -> Tuple[str, float]:
    p, lam = CONFIGS.get(policy, (policy, 4))
    if p not in ("A", "B"):
        raise ValueError(f"unknown bounded policy: {policy}")
    lam = float(lam if lambda_u is None else lambda_u)
    if lam not in (4, 8):
        raise ValueError("lambdaU must be 4 or 8")
    return p, lam


def directional_caps(g0: float, s: float, policy: str, *, barline: bool = False,
                     expand_room: float = math.inf, contract_room: float = math.inf,
                     locked: bool = False) -> Tuple[int, int]:
    """Joint min ceilings, in NATIVE pixels, floored only after every clamp.

    ``g0`` for a barline is BOTH sides' combined whitespace, not two budgets.
    No epsilon promotes a cap just below one native pixel to one pixel.
    """
    p, _ = policy_config(policy)
    g, gap = max(0., float(g0)), max(0., float(s))
    if locked or g == 0 or gap == 0:
        return 0, 0
    if barline:
        ef, es, cf, cs = (.40, .75, .15, .25) if p == "A" else (.60, 1., .20, .35)
        room = max(0., contract_room)
    else:
        ef, es, cf, cs = (.35, .40, .12, .15) if p == "A" else (.50, .60, .18, .25)
        room = min(max(0., g - .25 * gap), max(0., contract_room))
    return (math.floor(max(0., min(ef*g, es*gap, max(0., expand_room)))),
            math.floor(max(0., min(cf*g, cs*gap, room))))


def distortion(deltas: Sequence[float], caps: Sequence[float]) -> float:
    zs = []
    for d, c in zip(deltas, caps):
        if c <= 0:
            if d:
                raise ValueError("zero-cap displacement")
            continue
        z = abs(d) / c
        if z > 1 + 1e-10:
            raise ValueError("cap exceeded")
        zs.append(z**3)
    return sum(zs)/len(zs) + .5*max(zs) if zs else 0.


def line_cost(line: Dict[str, Any], lambda_u: float = 4, *, mm_px: float = layout.MM) -> float:
    d = max(0., line["target_width"] - line["achieved_width"])
    m = line.get("measure_count")
    if m is None:
        m = line.get("measure_count_estimate", 4)
    return (1 + 2*line["D_line"] + lambda_u*(d/mm_px > .5) +
            20*(d/line["target_width"])**2 + .05*((m-4)/4)**2)


def objective(lines: Sequence[Dict[str, Any]], pages: int, measures_fixed: int,
              staff_gap_mm: float, lambda_u: float = 4) -> float:
    if measures_fixed <= 0:
        raise ValueError("M must be fixed and positive")
    return ((sum(line_cost(x, lambda_u) for x in lines) + 2*pages)/measures_fixed +
            .5*(max(1.5-staff_gap_mm, 0)/.1)**2)


def _clear_run(mask: np.ndarray, col: int) -> Tuple[int, int]:
    clear = ~mask.any(axis=0)
    if col < 0 or col >= len(clear) or not clear[col]:
        return col, col
    lo, hi = col, col + 1
    while lo > 0 and clear[lo-1]:
        lo -= 1
    while hi < len(clear) and clear[hi]:
        hi += 1
    return lo, hi


def text_runs(regions: Sequence[Dict[str, Any]], staff: Optional[Dict[str, Any]], gap: float) -> List[List[float]]:
    """Conservative outside-staff text runs: adjacent aligned components stay rigid.

    Full-height masks catch crossing ink; this additionally protects whitespace
    between lyric/text glyphs. The 1.5-gap adjacency is global, never per-video.
    """
    if not staff:
        return []
    top, bottom = staff["lines"][0], staff["lines"][-1]
    boxes = [list(r["box"]) for r in regions if r.get("box") and
             (r["box"][3] < top-.5*gap or r["box"][1] > bottom+.5*gap)]
    runs = []
    for box in sorted(boxes):
        hit = next((r for r in runs if box[0]-r[2] <= 1.5*gap and box[0] >= r[0] and
                    min(box[3], r[3])-max(box[1], r[1]) > 0), None)
        if hit is None:
            runs.append(box)
        else:
            hit[:] = [min(hit[0], box[0]), min(hit[1], box[1]), max(hit[2], box[2]), max(hit[3], box[3])]
    return runs


def merge_corridors(slots: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Merge touching/overlapping native intervals only within one source system."""
    groups: List[List[Dict[str, Any]]] = []
    for g in sorted(slots, key=lambda g: (g.get("system_id", ""), g["native_corridor"][0], g["id"])):
        lo, hi = g["native_corridor"]
        if groups and groups[-1][0].get("system_id") == g.get("system_id") and \
                lo <= max(x["native_corridor"][1] for x in groups[-1]):
            groups[-1].append(g)
        else:
            groups.append([g])
    return groups


def recorded_regions(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Positive strip evidence in native strip coordinates (half-open boxes).

    Crop coordinates are rebased using the *selected* strip, including an uncut
    variant. An issue name alone is not a spatial foreground observation.
    """
    origin = record.get("box_crop") or [0, 0, 0, 0]
    regions = []

    def add(box, reason, crop=False):
        if box is None or len(box) != 4:
            return
        x0, y0, x1, y1 = map(float, box)
        if crop:
            x0, x1 = x0-origin[0], x1-origin[0]
            y0, y1 = y0-origin[1], y1-origin[1]
        if x1 > x0 and y1 > y0:
            item = {"box": [x0, y0, x1, y1], "reason": reason}
            if item not in regions:
                regions.append(item)

    events = (record.get("minority_content") or {}).get("events", [])
    for event in events:
        if event.get("box_crop") is not None:
            add(event["box_crop"], "UNCERTAIN_MARK_KEPT", True)
        else:
            add(event.get("box_strip") or event.get("box"), "UNCERTAIN_MARK_KEPT")
    for mark in record.get("uncertain_marks", []):
        add(mark.get("box_crop") or mark.get("bbox") or mark.get("box_strip"),
            "UNCERTAIN_MARK_KEPT", mark.get("box_crop") is not None)
    cleanup = (record.get("finishing") or {}).get("dark_cleanup") or {}
    for key in ("kept_boxes_crop", "flagged_boxes_crop"):
        for box in cleanup.get(key, []):
            add(box, "LOW_CONTRAST_CONTENT_KEPT", True)
    for box in (record.get("screen_chrome") or {}).get("touched_box_crop", []):
        add(box, "OVERLAY_COVERS_NOTATION", True)
    for region in record.get("protected_regions", []):
        add(region.get("box_crop") or region.get("box") or region.get("bbox"),
            "PROTECTED_REGION", region.get("box_crop") is not None)
    return regions


def _uncertain_columns(st: Dict[str, Any], *, declef: bool = False,
                       native: Optional[Dict[str, Any]] = None) -> Optional[np.ndarray]:
    """Lock foreground proved by the legacy nonstaff test or a recorded box.

    The mask already excludes measured staff scaffold and paper, and includes
    the influence of even a single native ink pixel. Do not reclassify JPEG or
    resampling tone as foreground. The declef mask excludes only the verified
    clef removal; recorded uncertainty remains protected in either variant.
    """
    view = (st.get("declef") or {}) if declef else st
    mask = view.get("nonstaff_out")
    if mask is None:
        return None
    cols = mask.any(axis=0).copy()
    native = native or {}
    regions = recorded_regions(st.get("record") or native.get("record") or {})
    regions += native.get("protected_regions", [])
    for region in regions:
        box = region.get("box")
        if box and box[3] > 0 and box[1]*st["scale"] < mask.shape[0]:
            lo = max(0, math.floor(box[0]*st["scale"]))
            hi = max(0, min(len(cols), math.ceil(box[2]*st["scale"])))
            if hi > lo:
                cols[lo:hi] = True
    return cols


def prepare_built(built: Dict[str, Any], policy: str, *, native_protection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Copy planning metadata; renderer arrays and frozen source arrays are read-only.

    The native mask is supplied by the extraction snapshot / build_document cache.
    A representative slot edits a merged corridor; aliases get zero budgets, so
    renderer removals cannot overlap and splitting never creates extra capacity.
    """
    p, _ = policy_config(policy)
    atoms = copy.deepcopy(built["atoms"])
    bound_by = {b["id"]: b for b in built["doc"].get("boundaries", [])}
    all_slots = []
    uncertain_by = {sid: _uncertain_columns(st, native=(native_protection or {}).get(sid))
                    for sid, st in built["strips"].items()}
    for ai, a in enumerate(atoms):
        st = built["strips"][a.get("strip_key", a["system_id"])]
        scale, gap = float(st["scale"]), float(st["gap_src"])
        a.update(native_scale=scale, staff_gap_native=gap)
        if a.get("boundary_id"):
            a["boundary_class"] = bound_by.get(a["boundary_id"], {}).get("class", "UNKNOWN")
        native = (native_protection or {}).get(a["system_id"], {})
        runs = text_runs(native.get("regions", []), native.get("staff"), gap)
        if a.get("join_legal") and (a.get("join") or {}).get("mode") == "declef":
            jn = a["join"]
            un = _uncertain_columns(st, declef=True, native=native)
            dropped = jn["clear_cols"][:int(jn.get("lead_trim", jn["trim"]))]
            unsafe = bool(un is not None and dropped and un[dropped].any())
            if ai and jn.get("prev_tail_trim"):
                prev = atoms[ai-1]
                pu = uncertain_by[prev.get("strip_key", prev["system_id"])]
                x1 = prev["cols_out"][1]
                unsafe |= bool(pu is not None and pu[x1-int(jn["prev_tail_trim"]):x1].any())
            if unsafe:
                a.update(join_legal=False, join_refused_bounded="UNCERTAIN_JOIN_WHITESPACE")
        gs = list(a.get("gaps") or [])
        if a.get("slot_before"):
            gs.append(a["slot_before"])
        if (a.get("join") or {}).get("slot"):
            gs.append(a["join"]["slot"])
        for g in gs:
            g.update(system_id=a["system_id"], native_scale=scale, staff_gap_native=gap,
                     saved_caps={k: g.get(k) for k in ("max_expand", "max_contract", "max_expand_wide", "max_contract_wide")})
            reasons = []
            if g.get("column_kind") not in (None, "staff_only"):
                reasons.append("CROSSING_BEAM")
            if g.get("uncertain_foreground") or g.get("locked"):
                reasons.append("UNCERTAIN_FOREGROUND")
            if g.get("kind") == "spread":
                col = int(round(g["col_out"]/scale))
                corridor = _clear_run(native["nonstaff"], col) if "nonstaff" in native else (
                    math.ceil((g["run_out"][0]-2)/scale), math.floor((g["run_out"][1]+2)/scale))
                if corridor[1] <= corridor[0] or st["nonstaff_out"][:, g["col_out"]].any():
                    reasons.append("PROTECTED_OR_UNCERTAIN_FOREGROUND")
                room_c = max(0, g["run_out"][1]-g["run_out"][0])/scale
                room_e = math.inf
                check_cols = slice(*g["run_out"])
            elif g.get("kind") == "join_lead":
                jn = a["join"]
                corridor = tuple(x/scale for x in jn["lead_out"])
                col = sum(corridor)/2
                room_e = max(0, jn.get("lead_trim", jn["trim"]))/scale
                room_c = max(0, len(jn["clear_cols"])-jn.get("lead_trim", jn["trim"]))/scale
                # Preferred lead after clef removal, not the discarded prefix.
                corridor = (corridor[1]-float(g["natural"])/scale, corridor[1])
                check_cols = [c for c in a["join"]["clear_cols"]]
            else:
                corridor = tuple(g.get("native_corridor") or (0, float(g["natural"])/scale))
                col = float(g.get("seam_out", sum(corridor)*scale/2))/scale
                room_e = math.inf
                room_c = sum(g.get("room_out") or [0, 0])/scale
                left_room, right_room = g.get("room_out") or [0, 0]
                seam = int(g.get("seam_out", col*scale))
                check_cols = slice(max(0, seam-left_room), min(st["nonstaff_out"].shape[1], seam+max(1, right_room)))
            unknown = (_uncertain_columns(st, declef=True, native=native) if g.get("kind") == "join_lead" else
                       uncertain_by[a.get("strip_key", a["system_id"])])
            if unknown is not None and unknown[check_cols].any():
                reasons.append("EVIDENCED_FOREGROUND")
            blocked = [r for r in runs if r[0] < col < r[2]]
            if blocked:
                reasons.append("LYRICS_OR_TEXT_RUN")
            if g.get("max_expand", 0) <= 0:
                room_e = 0.
            g.update(native_corridor=list(corridor), blocked_by=reasons, blocking_regions=blocked,
                     expand_room_native=room_e, contract_room_native=room_c)
            all_slots.append(g)
        a.pop("_gap_sums", None)
    physical = []
    for members in merge_corridors(all_slots):
        lo = min(g["native_corridor"][0] for g in members)
        hi = max(g["native_corridor"][1] for g in members)
        rep = max(members, key=lambda g: (g.get("kind") in ("barline_corridor", "join_lead"),
                                         g["contract_room_native"], g["natural"], g["id"]))
        physical.append({"members": members, "rep": rep, "lo": lo, "hi": hi, "g0": max(0., hi-lo)})
    parents = list(range(len(physical)))
    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i
    # A barline's ink separates two whitespace corridors. They are still ONE
    # package: joint absolute ceiling, excluding the protected stroke's width.
    linked = set()
    for boundary in built["doc"].get("boundaries", []):
        box = boundary.get("barline_box")
        if boundary.get("kind") != "barline" or not box:
            continue
        sid = boundary["system_id"]
        nearby = [(i, x) for i, x in enumerate(physical) if x["rep"]["system_id"] == sid and x["g0"] > 0]
        margin = max(2., .15*nearby[0][1]["rep"]["staff_gap_native"]) if nearby else 2.
        left = [(box[0]-x["hi"], i) for i, x in nearby if 0 <= box[0]-x["hi"] <= margin]
        right = [(x["lo"]-box[2], i) for i, x in nearby if 0 <= x["lo"]-box[2] <= margin]
        if left and right:
            li, ri = min(left)[1], min(right)[1]
            parents[root(ri)] = root(li)
            linked.update((li, ri))
    packages = {}
    for i, part in enumerate(physical):
        packages.setdefault(root(i), []).append((i, part))
    for parts in packages.values():
        reps = [part["rep"] for _, part in parts]
        widths = [part["g0"] for _, part in parts]
        bar = any(i in linked or r.get("kind") in ("barline_corridor", "join_lead") for (i, _), r in zip(parts, reps))
        rooms_e, rooms_c = [], []
        for (_, part), rep in zip(parts, reps):
            members, g0 = part["members"], part["g0"]
            locked = any(g["blocked_by"] for g in members)
            if not bar and g0 < .6*rep["staff_gap_native"]:
                locked = True
                for g in members:
                    g["blocked_by"].append("CORRIDOR_BELOW_0_6_STAFF_GAP")
            # Fixed native shares keep the joint budget valid even when a SAFE
            # line break puts the two physical halves on separate output lines.
            e_room = rep["expand_room_native"]
            c_room = rep["contract_room_native"]
            rooms_e.append(0 if locked else min(e_room, max(0, math.ceil(3*g0)-1)))
            rooms_c.append(0 if locked else min(c_room, (.15 if p == "A" else .20)*g0) if bar else c_room)
        G0 = sum(widths)
        e_global, c_global = directional_caps(G0, reps[0]["staff_gap_native"], p, barline=bar,
                                              expand_room=sum(rooms_e), contract_room=sum(rooms_c))
        es = legacy.spread_fill(e_global, widths, rooms_e)
        cs = legacy.spread_fill(c_global, widths, rooms_c)
        package_id = reps[0]["system_id"] + "/package/" + ";".join(str(r["id"]) for r in reps)
        package_native_caps = [sum(es), sum(cs)]
        scale = reps[0]["native_scale"]
        package_out_caps = [math.floor(x*scale) for x in package_native_caps]
        for (_, part), rep, e, c in zip(parts, reps, es, cs):
            lo, hi, g0 = part["lo"], part["hi"], part["g0"]
            group_id = rep["system_id"] + "/corridor/" + ":".join(map(str, (lo, hi)))
            eo, co = math.floor(e*scale), math.floor(c*scale)
            for g in part["members"]:
                representative = g is rep
                # JSON has no Infinity. Unbounded insertion room is disclosed
                # as null; the finite style/allocated budgets below govern it.
                if math.isinf(g["expand_room_native"]):
                    g["expand_room_native"] = None
                g.update(physical_corridor_id=group_id, corridor_native_width=g0, corridor_natural_out=g0*scale,
                         corridor_kind="barline" if bar else "interior", native_caps=[e, c],
                         cap_unit_id=package_id, package_native_width=G0, package_native_caps=package_native_caps,
                         package_style_native_caps=[e_global, c_global], package_caps_out=package_out_caps,
                         corridor_members=[x["id"] for x in part["members"]], representative=representative,
                         max_expand=eo if representative else 0, max_contract=co if representative else 0,
                         max_expand_wide=eo if representative else 0, max_expand_free=eo if representative else 0,
                         max_contract_wide=co if representative else 0)
    return dict(built, atoms=atoms, policy=p)


def _allocation(total: int, caps: Sequence[int]) -> List[int]:
    """Bounded cap-proportional integer water filling; constant cap use before rounding.

    This deterministic allocation is scored by D, with no hidden legacy tiers.
    The break DP is exact for these evaluated line candidates.
    """
    return legacy.spread_fill(total, caps, caps)


def package_distortion(deltas, gaps, expanding):
    totals, caps = {}, {}
    for dd, g in zip(deltas, gaps):
        key = g.get("cap_unit_id", g.get("physical_corridor_id", g["id"]))
        totals[key] = totals.get(key, 0) + dd
        caps[key] = caps.get(key, 0) + (g["max_expand"] if expanding else g["max_contract"])
    return distortion(list(totals.values()), [caps[k] for k in totals])


def evaluate_line(atoms: Sequence[Dict[str, Any]], i: int, j: int, width: int, *, lambda_u: float = 4) -> Optional[Dict[str, Any]]:
    first = atoms[i]
    rep = int(first.get("replica_width") or 0) if i and first["break_before"] == "safe_cut" else 0
    natural = rep + sum(int(a["width"]) for a in atoms[i:j]) - sum(legacy._joined_trim(a) for a in atoms[i+1:j])
    gaps = legacy._line_gaps(atoms, i, j)
    ce, cc = [int(g["max_expand"]) for g in gaps], [int(g["max_contract"]) for g in gaps]
    overhang = int(atoms[j-1].get("overhang") or 0)
    if natural - sum(cc) + overhang > width:
        return None
    # An overhang reserves actual page room, even if the staff could otherwise reach the margin.
    wanted = width - overhang - natural
    target_delta = max(-sum(cc), min(sum(ce), wanted))
    known = all(a.get("measure_count") is not None for a in atoms[i:j])
    count = sum(a["measure_count"] for a in atoms[i:j]) if known else None
    estimate = sum(a.get("measure_count") if a.get("measure_count") is not None else a.get("measure_estimate", 1)
                   for a in atoms[i:j])

    def at(delta):
        cs = ce if delta >= 0 else cc
        ds = _allocation(abs(delta), cs)
        if delta < 0:
            ds = [-x for x in ds]
        ln = {"start": i, "end": j, "replica_width": rep, "natural_width": natural,
              "overhang_px": overhang, "target_width": width, "achieved_width": natural+sum(ds),
              "measure_count": count, "measure_count_estimate": estimate,
              "D_line": package_distortion(ds, gaps, delta >= 0), "_gaps": gaps, "_deltas": ds,
              "expand_cap": sum(ce), "contract_cap": sum(cc)}
        ln["cost"] = line_cost(ln, lambda_u)
        return ln

    # Full-width candidate always evaluated at the target. If infeasible, optimise
    # the short line's amount of expansion instead of needlessly saturating every gap.
    candidates = [at(target_delta)]
    if target_delta > 0 and wanted > sum(ce):
        lo, hi = 0, target_delta
        while hi-lo > 6:
            a, b = (2*lo+hi)//3, (lo+2*hi)//3
            if at(a)["cost"] <= at(b)["cost"]:
                hi = b-1
            else:
                lo = a+1
        candidates += [at(x) for x in range(lo, hi+1)] + [at(0)]
    return min(candidates, key=lambda x: (x["cost"], -x["achieved_width"]))


def feasibility(line: Dict[str, Any], atoms: Sequence[Dict[str, Any]], width: int) -> Dict[str, Any]:
    gs = line.get("_gaps") or legacy._line_gaps(atoms, line["start"], line["end"])
    unique = {g.get("physical_corridor_id", g["id"]): g for g in gs if g.get("representative", True)}
    bar = sum(g["max_expand"] for g in gs if g.get("corridor_kind") == "barline")
    interior = sum(g["max_expand"] for g in gs if g.get("corridor_kind") != "barline")
    return {"required_width_px": width, "required_expansion_px": max(0, width-line["natural_width"]),
            "W_min_px": line["natural_width"]-line["contract_cap"],
            "W_max_px": line["natural_width"]+line["expand_cap"], "overhang_px": line["overhang_px"],
            "barline_capacity_px": bar, "interior_capacity_px": interior,
            "number_of_corridors": len(unique), "elastic_corridors": sum(bool(g["max_expand"] or g["max_contract"]) for g in unique.values()),
            "blocking_protected_regions": [{"slot_id": g["id"], "native_corridor": g.get("native_corridor"),
                                              "reasons": g.get("blocked_by", []), "regions": g.get("blocking_regions", [])}
                                             for g in gs if g.get("blocked_by")],
            "locked_units": [{"id": a["id"], "kind": a.get("kind"), "native_box": a.get("native_box")}
                             for a in atoms[line["start"]:line["end"]] if a.get("kind") in ("locked_group", "system")],
            "best_alternative_grouping_and_size": None}


def staff_endpoints(image: np.ndarray, line: Dict[str, Any], gap: float) -> Optional[Tuple[int, int]]:
    """Staff ends, not arbitrary rightmost ink; three long staff rows must agree."""
    votes = np.zeros(image.shape[1], np.int32)
    gray = image.min(axis=2)
    for k in range(5):
        y = round(line["staff_top_px"]+k*gap)
        if 0 <= y < len(gray):
            band = (gray[max(0, y-1):min(len(gray), y+2)].min(axis=0) < 210).astype(np.uint8)
            votes += cv2.morphologyEx(band.reshape(1, -1), cv2.MORPH_OPEN,
                                      np.ones((1, max(3, round(.8*gap)) | 1), np.uint8)).ravel()
    cols = np.flatnonzero(votes >= 3)
    return (int(cols[0]), int(cols[-1])+1) if len(cols) else None


def finalize_endpoint_flags(plan: Dict[str, Any], built: Dict[str, Any], images: Dict[str, np.ndarray],
                            staff_gap_mm: float, alternatives: Sequence[Dict[str, Any]] = ()) -> None:
    """A protected prefix can start left of the staff. Never advertise that as full.

    Keep all pixels at the left margin and disclose numerical feasibility; do not
    shift content off-page or silently count canvas width as staff width.
    """
    width = plan["max_width"]
    ragged_by = {r["line_id"]: r for r in plan["ragged_exceptions"]}
    for line in plan["lines"]:
        ends = staff_endpoints(images[line["id"]], line, staff_gap_mm*layout.MM)
        full = ends is not None and abs(ends[0]) <= .5*layout.MM and abs(width-ends[1]) <= .5*layout.MM
        line["staff_endpoints_px"] = list(ends) if ends else None
        line["full_target_achieved"] = full
        if line["justified"] and not full:
            line["justified"] = False
            line["short_reason"] = "PROTECTED_PREFIX_OR_STAFF_ENDPOINT"
        if not full:
            evidence = line.get("feasibility") or feasibility(line, built["atoms"], width)
            evidence.update(rendered_staff_left_px=ends[0] if ends else None,
                            rendered_staff_right_px=ends[1] if ends else None,
                            required_staff_span_px=width,
                            required_width_with_prefix_px=width+ends[0] if ends else None)
            if evidence.get("best_alternative_grouping_and_size") is None:
                candidates = [a for a in alternatives if a["start"] <= line["start"] < a["end"]]
                evidence["best_alternative_grouping_and_size"] = (min(candidates, key=lambda a:
                    (max(a["right_deficit_px"], 0), a["D_line"], -a["staff_gap_mm"])) if candidates else
                    {"atom_ids": line["atom_ids"], "staff_gap_mm": staff_gap_mm,
                     "W_min_px": evidence["W_min_px"], "W_max_px": evidence["W_max_px"],
                     "right_deficit_px": width-ends[1] if ends else None, "scope": "provided fixed grouping"})
            line["feasibility"] = evidence
            if line["id"] not in ragged_by:
                entry = {"line_id": line["id"], "reason": line.get("short_reason", "BOUNDED_CAPACITY"),
                         "final_line": line is plan["lines"][-1], "unresolved_residual_px": width-line["achieved_width"],
                         "feasibility": evidence}
                plan["ragged_exceptions"].append(entry)
                ragged_by[line["id"]] = entry


def plan_candidates(atoms: Sequence[Dict[str, Any]], width: int, *, locks: Iterable[Dict[str, Any]] = (),
                    lambda_u: float = 4, k: int = 3) -> List[Dict[str, Any]]:
    """Three shortest legal break paths; LOCKED/UNKNOWN boundaries are never cuts."""
    n = len(atoms)
    if not n:
        return []
    idx = {a["id"]: i for i, a in enumerate(atoms)}
    boundaries = {a.get("boundary_id"): i for i, a in enumerate(atoms) if a.get("boundary_id")}
    forced, forbidden = set(), set()
    for lock in locks:
        if not lock.get("active", True):
            continue
        targets = lock.get("targets") or []
        if lock.get("type") == "forced_line_break":
            if not targets or targets[0] not in boundaries:
                return []
            forced.add(boundaries[targets[0]])
        elif lock.get("type") == "keep_together":
            if len(targets) != 2 or any(t not in idx for t in targets) or idx[targets[0]] > idx[targets[1]]:
                return []
            forbidden.update(range(idx[targets[0]]+1, idx[targets[1]]+1))
    if forced & forbidden:
        return []

    def can_break(i):
        if i in (0, n):
            return True
        a = atoms[i]
        return i not in forbidden and (a["break_before"] == "system_start" or
                (a["break_before"] == "safe_cut" and a.get("boundary_class", "UNKNOWN") == "SAFE" and a.get("replica_width") is not None))

    def must_break(i):
        return i in forced or legacy._must_break_static(atoms[i]) or atoms[i].get("alone") or atoms[i-1].get("alone")

    if any(not can_break(i) for i in forced) or any(must_break(i) for i in forbidden):
        return []
    best: List[List[Tuple[float, List[Dict[str, Any]]]]] = [[] for _ in range(n+1)]
    best[0] = [(0., [])]
    edges = []
    for i in range(n):
        if not best[i] or not can_break(i):
            continue
        for j in range(i+1, n+1):
            if j > i+1 and must_break(j-1):
                break
            if not can_break(j):
                continue
            ev = evaluate_line(atoms, i, j, width, lambda_u=lambda_u)
            if ev is None:
                continue
            edges.append(ev)
            best[j] += [(cost+ev["cost"], path+[ev]) for cost, path in best[i]]
            best[j].sort(key=lambda x: (x[0], tuple(e["end"] for e in x[1])))
            best[j] = best[j][:k]
    suffix = {n}
    for i in range(n-1, -1, -1):
        if any(e["start"] == i and e["end"] in suffix for e in edges):
            suffix.add(i)
    feasible_groupings = [{"start": e["start"], "end": e["end"],
                           "atom_ids": [a["id"] for a in atoms[e["start"]:e["end"]]],
                           "right_deficit_px": width-e["achieved_width"],
                           "W_min_px": e["natural_width"]-e["contract_cap"],
                           "W_max_px": e["natural_width"]+e["expand_cap"], "D_line": e["D_line"]}
                          for e in edges if best[e["start"]] and e["end"] in suffix]
    out = []
    for cost, evs in best[n]:
        lines, slots, ragged = [], [], []
        for number, ev in enumerate(evs, 1):
            lid = f"line-{number:03d}"
            line = {key: val for key, val in ev.items() if not key.startswith("_")}
            line.update(id=lid, atom_ids=[a["id"] for a in atoms[ev["start"]:ev["end"]]],
                        adjustment_px=ev["achieved_width"]-ev["natural_width"],
                        adjustment_fraction=(ev["achieved_width"]-ev["natural_width"])/max(1, ev["natural_width"]),
                        justified=ev["achieved_width"] == width, justify_tier=1,
                        stretch_ratio=0., ragged_cost=0., tier3_stretch_cost=0., section_end=False,
                        slot_ids=[g["id"] for g in ev["_gaps"]], gap_count=len(ev["_gaps"]),
                        spread_gap_count=sum(g.get("kind") == "spread" for g in ev["_gaps"]),
                        joined_system_ids=[a["system_id"] for a in atoms[ev["start"]+1:ev["end"]] if a["break_before"] == "system_start"],
                        starts_inside_system=bool(ev["start"] and atoms[ev["start"]]["break_before"] == "safe_cut"),
                        page_fill=ev["achieved_width"]/width, expand_cap_wide=ev["expand_cap"])
            growth = []
            for g, dd in zip(ev["_gaps"], ev["_deltas"]):
                natural = g.get("corridor_natural_out", g["natural"])
                gr = dd/natural if natural else 0.
                growth.append(gr)
                side_cap = g["max_expand"] if dd >= 0 else g["max_contract"]
                slots.append({"id": g["id"], "line_id": lid, "kind": g.get("kind"), "natural": natural,
                              "max_expand": g["max_expand"], "max_contract": g["max_contract"],
                              "cap_tier": 1, "policy": atoms[0].get("policy"), "applied_delta": dd,
                              "growth_ratio": gr, "z": dd/side_cap if side_cap else 0.,
                              "within_caps": -g["max_contract"] <= dd <= g["max_expand"],
                              "physical_corridor_id": g.get("physical_corridor_id", g["id"]),
                              "native_caps": g.get("native_caps"), "cap_unit_id": g.get("cap_unit_id"),
                              "package_native_caps": g.get("package_native_caps"), "package_caps_out": g.get("package_caps_out"),
                              "package_native_width": g.get("package_native_width"), "representative": g.get("representative", True)})
            line.update(max_gap_growth=max(growth, default=0.), min_gap_growth=min(growth, default=0.))
            if not line["justified"]:
                evidence = feasibility(ev, atoms, width)
                line["feasibility"] = evidence
                ragged.append(dict(line_id=lid, reason="BOUNDED_CAPACITY", final_line=number == len(evs),
                                   unresolved_residual_px=width-line["achieved_width"], feasibility=evidence))
            lines.append(line)
        out.append({"version": VERSION, "policy": atoms[0].get("policy", "bounded"), "width": width, "max_width": width,
                    "lines": lines, "slots": slots, "ragged_exceptions": ragged, "conflicts": [], "valid": True,
                    "cost": cost, "edge": {"width": width, "page_line_width": width, "x_offset_px": 0,
                                             "reason": "LEFT_MARGIN_BOUNDED"}, "feasible_groupings": feasible_groupings})
    return out


def paginate(built: Dict[str, Any], plan: Dict[str, Any], staff_gap_mm: float, header: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Use the real paginator, with exactly the renderer's staff alignment and label band."""
    from app.pipeline import reflow_measure as measure
    atoms = {a["id"]: a for a in built["atoms"]}
    gap = staff_gap_mm*layout.MM
    units, unit_systems = [], []
    for line in plan["lines"]:
        seg = [atoms[x] for x in line["atom_ids"]]
        up = down = band = 0
        label_widths = []
        for pos, a in enumerate(seg):
            st = built["strips"][measure._sk(a)]
            r0, r1 = a.get("rows_out") or [0, st["image"].shape[0]]
            cn = a.get("carried_number") or {}
            if pos == 0 and a["break_before"] == "safe_cut" and cn.get("box_out"):
                r0, r1 = min(r0, cn["box_out"][1]), max(r1, cn["box_out"][3])
            top = round(st["top_out"])
            up, down = max(up, top-r0), max(down, r1-top)
            if (st.get("label") or {}).get("path") and a["break_before"] == "system_start":
                patch = cv2.imread(st["label"]["path"])
                if patch is None:
                    raise ValueError("frozen label patch unreadable")
                label, _ = measure.boxed_label(patch, st["scale"], gap)
                band = max(band, label.shape[0]+round(measure.LABEL_SEP_GAPS*gap))
                label_widths.append(label.shape[1])
        if sum(label_widths)+max(0, len(label_widths)-1)*round(.5*gap) > line["achieved_width"]+line["overhang_px"]:
            return {"validation": {"valid": False, "errors": ["LABEL_COLLISION"]}, "pages": []}
        height = int(up+down+band)
        line.update(height_px=height, label_band_px=band, staff_top_px=band+int(up))
        units.append({"id": line["id"], "width": line["achieved_width"]+line["overhang_px"], "height": height, "staff_gap_px": gap})
        unit_systems.append((line["id"], list(dict.fromkeys(a["system_id"] for a in seg))))
    markers, missing = render.layout_markers(header, unit_systems)
    pages = layout.plan_pages(units, header_height_px=render.header_height(header), staff_gap_mm=staff_gap_mm,
                              x_offset_px=0, markers=markers)
    title, credits = render.header_lines(header)
    pages["header"] = {"title": title, "credits": credits}
    render.attach_incomplete(pages, header, missing)
    return pages


def optimize_document(build_at: Callable[[float], Dict[str, Any]], *, requested_mm: float = 1.5, auto_size: bool = True,
                      header: Optional[Dict[str, Any]] = None, policy: str = "A1", locks: Iterable[Dict[str, Any]] = (),
                      native_protection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p, lam = policy_config(policy)
    sizes = SIZE_GRID if auto_size else (float(requested_mm),)
    width = layout.PAGE_W-2*layout.MARGIN_X
    best = None
    records, alternatives, limits = [], [], []
    fixed_m = None
    for mm in sizes:
        built = prepare_built(build_at(mm), p, native_protection=native_protection)
        for a in built["atoms"]:
            a["policy"] = p
        m = sum(a.get("measure_count") if a.get("measure_count") is not None else a.get("measure_estimate", 1) for a in built["atoms"])
        if fixed_m is None:
            fixed_m = m
        if m != fixed_m:
            raise ValueError("fixed measure divisor changed across sizes")
        plans = plan_candidates(built["atoms"], width, locks=locks, lambda_u=lam)
        if plans:
            alternatives.extend(dict(a, staff_gap_mm=mm) for a in plans[0]["feasible_groupings"])
        trial = {"staff_gap_mm": mm, "near_best_plans": len(plans), "scores": []}
        for rank, plan in enumerate(plans):
            pages = paginate(built, plan, mm, header)
            if not pages["validation"]["valid"]:
                trial["scores"].append({"rank": rank, "valid": False, "errors": pages["validation"]["errors"]})
                continue
            j = objective(plan["lines"], len(pages["pages"]), fixed_m, mm, lam)
            trial["scores"].append({"rank": rank, "valid": True, "J": j, "pages": len(pages["pages"])})
            if best is None or (j, -mm, rank) < (best["J"], -best["staff_gap_mm"], best["break_rank"]):
                best = {"built": built, "lines_plan": plan, "page_plan": pages, "J": j,
                        "staff_gap_mm": mm, "break_rank": rank}
        if not plans:
            for i, atom in enumerate(built["atoms"]):
                gs = atom.get("gaps") or []
                n = int(atom["width"])+int(atom.get("replica_width") or 0)
                wmin = n-sum(int(g["max_contract"]) for g in gs)+int(atom.get("overhang") or 0)
                if wmin > width:
                    limits.append({"atom_id": atom["id"], "staff_gap_mm": mm, "required_width_px": width,
                                   "natural_plus_replica_px": n, "W_min_with_overhang_px": wmin,
                                   "excess_px": wmin-width, "native_box": atom.get("native_box"),
                                   "kind": atom.get("kind"), "replica_width": atom.get("replica_width")})
        records.append(trial)
    if best is None:
        return {"valid": False, "version": VERSION, "policy": p, "lambdaU": lam, "candidates": records,
                "capacity_limits": limits, "M_fixed": fixed_m, "reason": "BOUNDED_CAPACITY_LIMIT"}
    plan = best["lines_plan"]
    for line in plan["lines"]:
        if "feasibility" not in line:
            continue
        alts = [a for a in alternatives if a["start"] <= line["start"] < a["end"]]
        alt = min(alts, key=lambda a: (max(a["right_deficit_px"], 0), a["D_line"], -a["staff_gap_mm"])) if alts else None
        line["feasibility"]["best_alternative_grouping_and_size"] = alt
        line["feasibility"]["search_scope"] = "all prefix/suffix-reachable SAFE groupings; top three document paths paginated per size"
    best.update(valid=True, version=VERSION, policy=p, lambdaU=lam, M_fixed=fixed_m,
                M_basis="known counts plus frozen internal-barline estimate for unknown units",
                candidates=records, capacity_limits=limits, alternative_groupings=alternatives)
    plan["optimizer"] = {key: best[key] for key in ("version", "policy", "lambdaU", "M_fixed", "M_basis", "J", "candidates", "capacity_limits")}
    plan["alternative_groupings"] = alternatives
    return best
