"""Boundary candidate generation (MEASURE_BRIEF milestone 0, step 1-3).

Per video: 48 baseline barline proposals (existing detector), 16 adversarial
seams near or through symbols, 16 seeded-random seams. Repeated views of the
same written system are collapsed before sampling. A shortfall of baseline
proposals is filled with extra adversarial/random seams and recorded.

No boundary classifier is imported here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

import common as C
from app.pipeline import system_detect as sd


def _symbol_components(img: np.ndarray, st: Dict[str, Any], proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Non-staff ink objects typed by simple geometry (for adversarial seam placement)."""
    g = st["gap"]
    ink = sd.ink_mask(img)
    nonstaff = C.nonstaff_of(ink, st)
    top, bot = st["lines"][0], st["lines"][4]
    bars = [(p["bar_x0"], p["bar_x1"]) for p in proposals]
    out = []
    for x, y, w, h, area in C.components(nonstaff):
        if area < 1:
            continue
        cx = x + w / 2.0
        if any(b0 - 1 <= x and x + w <= b1 + 2 for b0, b1 in bars):
            continue  # the barline stroke itself
        fill = area / max(1, w * h)
        near_bar = any(abs(cx - (b0 + b1) / 2) <= 2.0 * g for b0, b1 in bars)
        if area <= max(4, 0.06 * g * g) and w <= 0.5 * g and h <= 0.5 * g:
            kind = "small_dot"
        elif y >= bot + 1.0 * g and h <= 1.8 * g:
            kind = "text_below"
        elif y + h <= top - 0.8 * g and h >= 0.6 * g and w <= 4 * g:
            kind = "label_or_text_above"
        elif w >= 2.0 * g and fill < 0.3:
            kind = "thin_arc_or_line"
        elif w >= 1.5 * g and h <= 0.8 * g:
            kind = "beam_or_bar"
        else:
            kind = "notehead_or_glyph"
        out.append({"box": [int(x), int(y), int(x + w), int(y + h)], "kind": kind, "near_barline": bool(near_bar)})
    for p in proposals:
        if len(p["strokes"]) > 1 or p["dots"]["left"] or p["dots"]["right"]:
            a = int(p["bar_x0"] - (1.2 * g if p["dots"]["left"] else 0))
            z = int(p["bar_x1"] + 1 + (1.2 * g if p["dots"]["right"] else 0))
            out.append({"box": [a, int(top), z, int(bot) + 1], "kind": "repeat_or_double_bar", "near_barline": True})
    return out


def _neighbours(seams: List[int], x: int, width: int, *, exclude: Optional[int] = None) -> Tuple[int, int]:
    left = max([s for s in seams if s < x and s != exclude], default=0)
    right = min([s for s in seams if s > x and s != exclude], default=width)
    return int(left), int(right)


def collapse_views(run: Dict[str, Any], systems: List[Dict[str, Any]], images: Dict[str, np.ndarray]) -> Dict[str, str]:
    """system id -> canonical system id (first view in video order of the same written system)."""
    canon: Dict[str, str] = {}
    sigs = {s["id"]: C.strip_signature(images[s["id"]], s["strip"]) for s in systems}
    reps: List[str] = []
    for s in systems:
        g = float(s["strip"]["staff_gap_px"])
        match = next((r for r in reps if C.same_written_system(sigs[r], sigs[s["id"]], g)), None)
        if match is None:
            reps.append(s["id"])
            canon[s["id"]] = s["id"]
        else:
            canon[s["id"]] = match
    return canon


def generate(run: Dict[str, Any], video: str) -> Dict[str, Any]:
    systems = C.included_systems(run)
    images = {s["id"]: cv2.imread(str(C.strip_path(run["dir"], s))) for s in systems}
    canon = collapse_views(run, systems, images)
    analysed: Dict[str, Dict[str, Any]] = {}
    for s in systems:
        img = images[s["id"]]
        st, props = C.barline_proposals(img, s["strip"])
        analysed[s["id"]] = {"system": s, "img": img, "staff": st, "proposals": props or []}

    # repeated views: proposals of non-canonical systems are collapsed onto the canonical one
    view_members: Dict[str, List[str]] = {}
    for sid, cid in canon.items():
        view_members.setdefault(cid, []).append(sid)
    canonical_ids = [s["id"] for s in systems if canon[s["id"]] == s["id"] and analysed[s["id"]]["staff"] is not None]

    def collapsed_views(sid: str, seam: int) -> List[Dict[str, Any]]:
        out = []
        g = analysed[sid]["staff"]["gap"]
        for other in view_members.get(sid, []):
            if other == sid:
                continue
            props = analysed[other]["proposals"]
            seams = [p["seam_x"] for p in props] or [seam]
            near = min(seams, key=lambda v: abs(v - seam))
            out.append({"system_id": other, "seam_x_strip": int(near if abs(near - seam) <= 0.5 * g else seam)})
        return out

    # ---- baseline pool
    pool = []
    for sid in canonical_ids:
        a = analysed[sid]
        st = a["staff"]
        comps = C.components(C.nonstaff_of(sd.ink_mask(a["img"]), st))
        for p in a["proposals"]:
            tags = C.strata_tags(a["img"], st, p["seam_x"], proposal=p, comps=comps)
            pool.append({"system_id": sid, "seam_x_strip": p["seam_x"], "proposal": p, "strata": tags,
                         "stratum": C.primary_stratum(tags)})
    rng = C.seeded_rng(video, "baseline")
    by_stratum: Dict[str, List[Dict[str, Any]]] = {}
    for c in pool:
        by_stratum.setdefault(c["stratum"], []).append(c)
    for k in by_stratum:
        idx = rng.permutation(len(by_stratum[k]))
        by_stratum[k] = [by_stratum[k][i] for i in idx]
    order = sorted(by_stratum, key=lambda k: (len(by_stratum[k]), k))  # rarest first
    chosen: List[Dict[str, Any]] = []
    while len(chosen) < C.PER_VIDEO["baseline"] and any(by_stratum[k] for k in order):
        for k in order:
            if by_stratum[k] and len(chosen) < C.PER_VIDEO["baseline"]:
                chosen.append(by_stratum[k].pop(0))
    baseline = [dict(c, origin="baseline") for c in chosen]
    shortfall = C.PER_VIDEO["baseline"] - len(baseline)
    n_adv = C.PER_VIDEO["adversarial"] + (shortfall + 1) // 2
    n_rand = C.PER_VIDEO["random"] + shortfall // 2

    taken: Dict[str, List[int]] = {}
    for c in baseline:
        taken.setdefault(c["system_id"], []).append(c["seam_x_strip"])

    def free(sid: str, x: int) -> bool:
        g = analysed[sid]["staff"]["gap"]
        return all(abs(x - t) > 0.5 * g for t in taken.get(sid, []))

    # ---- adversarial: seams near or through symbols
    rng = C.seeded_rng(video, "adversarial")
    syms: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for sid in canonical_ids:
        a = analysed[sid]
        for comp in _symbol_components(a["img"], a["staff"], a["proposals"]):
            if a["staff"]["x"][0] <= (comp["box"][0] + comp["box"][2]) / 2 <= a["staff"]["x"][1]:
                syms.setdefault(comp["kind"], []).append((sid, comp))
    kinds = sorted(syms)
    for k in kinds:
        idx = rng.permutation(len(syms[k]))
        # symbols near a barline first: realistic near-misses of a barline seam
        lst = [syms[k][i] for i in idx]
        syms[k] = [s for s in lst if s[1]["near_barline"]] + [s for s in lst if not s[1]["near_barline"]]
    adversarial: List[Dict[str, Any]] = []
    guard = 0
    while len(adversarial) < n_adv and any(syms[k] for k in kinds) and guard < 10000:
        guard += 1
        for k in kinds:
            if not syms[k] or len(adversarial) >= n_adv:
                continue
            sid, comp = syms[k].pop(0)
            g = analysed[sid]["staff"]["gap"]
            x0, _y0, x1, _y1 = comp["box"]
            mode = ["through_centre", "inside_left_edge", "inside_right_edge", "outside_left_near", "outside_right_near"][int(rng.integers(5))]
            near = max(1, int(round(0.1 * g)))
            x = {"through_centre": (x0 + x1) // 2, "inside_left_edge": x0 + min(1, x1 - x0 - 1),
                 "inside_right_edge": x1 - 1, "outside_left_near": x0 - near, "outside_right_near": x1 + near}[mode]
            x = int(np.clip(x, 1, analysed[sid]["img"].shape[1] - 1))
            if not free(sid, x):
                continue
            taken.setdefault(sid, []).append(x)
            adversarial.append({"system_id": sid, "seam_x_strip": x, "origin": "adversarial",
                                "adversarial": {"symbol_kind": k, "symbol_box_strip": comp["box"], "placement": mode}})

    # ---- seeded random x (also covers any adversarial shortfall)
    n_rand = sum(C.PER_VIDEO.values()) - len(baseline) - len(adversarial)
    rng = C.seeded_rng(video, "random")
    widths = np.array([analysed[s]["staff"]["x"][1] - analysed[s]["staff"]["x"][0] for s in canonical_ids], float)
    randoms: List[Dict[str, Any]] = []
    guard = 0
    while len(randoms) < n_rand and guard < 10000 and len(canonical_ids):
        guard += 1
        sid = canonical_ids[int(rng.choice(len(canonical_ids), p=widths / widths.sum()))]
        x0, x1 = analysed[sid]["staff"]["x"]
        x = int(rng.integers(x0 + 1, x1))
        if not free(sid, x):
            continue
        taken.setdefault(sid, []).append(x)
        randoms.append({"system_id": sid, "seam_x_strip": x, "origin": "random"})

    cands = []
    for c in baseline + adversarial + randoms:
        a = analysed[c["system_id"]]
        s = a["system"]
        st = a["staff"]
        width = a["img"].shape[1]
        seams = [p["seam_x"] for p in a["proposals"]]
        if c["origin"] == "baseline":
            left, right = _neighbours(seams, c["seam_x_strip"], width, exclude=c["seam_x_strip"])
            owner = c["proposal"]["barline_owner"]
        else:
            left, right = _neighbours(seams, c["seam_x_strip"], width)
            owner = None
        if "strata" not in c:
            c["strata"] = C.strata_tags(a["img"], st, c["seam_x_strip"])
            c["stratum"] = C.primary_stratum(c["strata"])
        box = s["strip"]["box_crop"]
        x = int(c["seam_x_strip"])
        rec = {
            "video": video,
            "split": C.SPLIT[video],
            "system_id": s["id"],
            "occurrence_id": s["id"],
            "origin": c["origin"],
            "strata": c["strata"],
            "stratum": c["stratum"],
            "seam": {"x_strip": x, "x_crop": x + int(box[0]), "half_open": "left owns x < seam, right owns x >= seam",
                     "full_height_rows_strip": [0, int(a["img"].shape[0])]},
            "ownership_proposal": {
                "left_unit_cols_strip": [left, x], "right_unit_cols_strip": [x, right],
                "barline_group_strip": ([c["proposal"]["bar_x0"], c["proposal"]["bar_x1"] + 1] if c["origin"] == "baseline" else None),
                "barline_owner": owner,
                "rows": "full strip height; every pixel of a column belongs to the unit owning the column",
            },
            "staff": {"gap_px": st["gap"], "lines_y_strip": st["lines"], "x_strip": list(st["x"]), "thick_px": st["thick"]},
            "collapsed_views": collapsed_views(s["id"], x),
        }
        if c["origin"] == "baseline":
            rec["detector"] = {"strokes": c["proposal"]["strokes"], "corridor_strip": c["proposal"]["corridor"],
                               "dots": c["proposal"]["dots"]}
        if c["origin"] == "adversarial":
            rec["adversarial"] = c["adversarial"]
        cands.append(rec)
    absent = [k for k in C.STRATA if not any(k in c["strata"] for c in cands)]
    return {
        "candidates": cands,
        "view_groups": {cid: m for cid, m in view_members.items() if len(m) > 1},
        "pool": {"baseline_proposals_after_collapse": len(pool),
                 "baseline_by_stratum": {k: sum(1 for c in pool if c["stratum"] == k) for k in C.STRATA},
                 "systems_included": len(systems), "systems_canonical": len(canonical_ids)},
        "shortfall": {"baseline": shortfall, "filled_adversarial": len(adversarial) - C.PER_VIDEO["adversarial"],
                      "filled_random": len(randoms) - C.PER_VIDEO["random"]},
        "absent_strata": absent,
        "images": images,
        "analysed": analysed,
    }
