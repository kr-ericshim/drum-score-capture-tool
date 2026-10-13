"""Independent strip-to-plan certificate (docs/archive/reflow/LEDGER_2D_INTERFACE.md §12.4).

Coordinates in transforms are integer pixel centres; a half-open image box has
centre-domain [x0-.5, x1-.5). Only those centres confer ownership, never the
resize kernel halo. No optimiser, measure renderer, or old verifier is called.
Replica records must declare ``replica_role`` and ``source_footprint`` (a native
``{bbox, mask}`` packed mask, or a rectangular native bbox). ``copy_index`` alone
does not authorise duplication. Missing background at the outer strip margins
is independently certified as paper; interior holes require recorded removals.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

import cv2
import numpy as np

from . import reflow_verify_common as vc
from .reflow_ledger import unpack_crop
from .reflow_layout import MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, MM, PAGE_H, PAGE_W


def plan_records(plan: dict, ledger_sink: dict) -> dict:
    """Canonical digest payload, including every record used to render/validate.

    Persist this with certB; C can re-hash it without depending on this module.
    Producer audit/validation assertions and in-memory page images are excluded.
    """
    measure = plan.get("measure_reflow", {})
    payload = {"page_px": plan.get("page_px"), "dpi": plan.get("dpi"),
            "staff_gap_mm": plan.get("staff_gap_mm"), "staff_gap_px": plan.get("staff_gap_px"),
            "margins_px": plan.get("margins_px"), "header_band_px": plan.get("header_band_px", 0),
            "pages": plan.get("pages", []),
            "placements": ledger_sink.get("placements", ledger_sink.get("ledger_placements", [])),
            "removed": ledger_sink.get("removed", ledger_sink.get("ledger_removed", [])),
            "generated_origins": ledger_sink.get("generated_origins", ledger_sink.get("generated", [])),
            "boundaries": measure.get("boundaries", []), "units": measure.get("units", []),
            "lines": [{"id": r["id"], "atom_ids": r.get("atom_ids", [])} for r in measure.get("lines", [])]}
    if measure.get("forced_breaks"):
        payload["forced_breaks"] = measure["forced_breaks"]
    return payload


def _authorized_floor_break(boundary: dict, records: list) -> bool:
    # Independently check the explicit product exception; preserve the ordinary SAFE rule.
    reasons = set(boundary.get("reason_codes") or [])
    allowed = {"TIE_SLUR_OR_LINE_CROSSES", "TEXT_GROUP_CROSSES",
               "LINE_ENDPOINT_NEAR_SEAM", "POSSIBLE_BROKEN_STROKE"}
    evidence = boundary.get("floor_break_evidence") or {}
    if (evidence.get("version") != "floor-strokes-1" or evidence.get("verified") is not True
            or evidence.get("seam_x") != boundary.get("seam_x") or not evidence.get("components")
            or not all(c.get("thin_stroke") is True and c.get("checks")
                       and all(v is True for v in c["checks"].values()) for c in evidence["components"])):
        return False
    # Independently enforce the recorded measurements as well as the flags;
    # an edited 'verified' bit or a relaxed producer threshold is insufficient.
    try:
        gap = float(evidence["staff_gap_px"])
        if not np.isfinite(gap) or gap < 8:
            return False
        for component in evidence["components"]:
            x0, y0, x1, y1 = component["box"]
            width, height = x1 - x0, y1 - y0
            local = component["local_extent_px"]
            vertical = component["max_vertical_run_px"]
            fill = component["max_blob_fill"]
            if (not np.isfinite([width, height, local, vertical, fill]).all()
                    or not (0 < height <= 1.5 * gap and width >= max(2 * gap, 4 * height)
                            and 0 <= local <= .35 * gap and 0 < vertical <= .35 * gap
                            and 0 < fill < .60)):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return (boundary.get("class") in ("LOCKED", "UNKNOWN") and bool(reasons) and reasons <= allowed
            and any(r.get("boundary_id") == boundary.get("id")
                    and r.get("system_id") == boundary.get("system_id")
                    and set(r.get("reasons") or []) == reasons
                    and r.get("evidence") == evidence for r in records))


def _matrix(value: Any) -> np.ndarray:
    m = np.asarray(value, dtype=float)
    if (m.shape != (3, 3) or not np.isfinite(m).all()
            or not np.allclose(m[2], [0, 0, 1], rtol=0, atol=1e-9)
            or abs(m[0, 1]) > 1e-9 or abs(m[1, 0]) > 1e-9 or min(m[0, 0], m[1, 1]) <= 0):
        raise ValueError("mapping must be finite, axis-aligned and monotone")
    return m


def _resize(spec: dict, matrix: np.ndarray, *, origin=(0, 0), offset=(0, 0)) -> tuple[float, float]:
    src, dst = np.asarray(spec["source_size"], float), np.asarray(spec["output_size"], float)
    if (src.shape != (2,) or dst.shape != (2,) or not np.isfinite([src, dst]).all()
            or min(*src, *dst) <= 0 or not np.equal([src, dst], np.floor([src, dst])).all()
            or spec.get("interpolation") not in ("area", "cubic")):
        raise ValueError("invalid resize dimensions or interpolation")
    scale = dst / src
    expected = np.eye(3)
    expected[0, 0], expected[1, 1] = scale
    expected[:2, 2] = np.asarray(offset) + (scale - 1) / 2 - scale * np.asarray(origin)
    if not np.allclose(matrix, expected, rtol=0, atol=1e-9):
        raise ValueError("resize metadata disagrees with centre mapping")
    # Uniform scale before integer canvas rounding: derive the admissible
    # interval from dimensions, rather than a video-dependent anisotropy limit.
    lo, hi = float(np.max((dst - .5) / src)), float(np.min((dst + .5) / src))
    if lo > hi + 1e-9:
        raise ValueError("nonuniform resize (cannot result from one rounded scale)")
    return lo, hi


def _native_box(box: Any, pre: np.ndarray, shape: tuple[int, int]) -> list[int]:
    b = np.asarray(box, float)
    if b.shape != (4,) or not np.isfinite(b).all() or b[0] >= b[2] or b[1] >= b[3]:
        raise ValueError("invalid source footprint")
    s, t = pre.diagonal()[:2], pre[:2, 2]
    # ceil, not floor/ceil kernel coverage. A native centre belongs to exactly
    # one side of a cut even when the cubic/area kernel reads both sides.
    low = np.ceil((b[:2] - .5 - t) / s - 1e-9).astype(int)
    high = np.ceil((b[2:] - .5 - t) / s - 1e-9).astype(int)
    w, h = shape[1], shape[0]
    return [int(np.clip(low[0], 0, w)), int(np.clip(low[1], 0, h)),
            int(np.clip(high[0], 0, w)), int(np.clip(high[1], 0, h))]


def _slice(box):
    x0, y0, x1, y1 = box
    return np.s_[y0:y1, x0:x1]


def _bbox(mask: np.ndarray) -> list[int] | None:
    ys, xs = np.nonzero(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)] if xs.size else None


def _footprint(mask: np.ndarray, **extra) -> dict | None:
    box = _bbox(mask)
    return {"bbox": box, "mask": vc.pack_mask(mask[_slice(box)]), **extra} if box else None


def _staff_model(contrast: np.ndarray) -> tuple[np.ndarray, dict]:
    """Five-row horizontal projection fit; no producer masks/row annotations.

    Maximise the weakest of five equally spaced projection peaks. Half-maximum
    bands measure line thickness; the model admits at most thickness+1. Staff
    attachments are found after subtracting these bands, so a dot does not get
    absorbed into a page-wide connected staff component.
    """
    h, w = contrast.shape
    projection = contrast.astype(np.float32).sum(axis=1)
    if h < 9 or not projection.any():
        return np.zeros((h, w), bool), {"rows": [], "bands": [], "gap_px": None}
    best, rows = None, None
    # Quarter-pixel gap hypotheses represent alternating integer staff rows;
    # insisting on an integer gap would mis-fit an ordinary 20/21 px spacing.
    for gap in np.arange(2., (h-1)/4 + .01, .25):
        starts = np.arange(0,h-1-4*gap+.01,.25)
        if not starts.size:
            continue
        row_indices = np.rint(starts[:, None]+gap*np.arange(5)).astype(int)
        q = projection[row_indices]
        score = q.min(axis=1)
        at = int(np.argmax(score))
        rank = (float(score[at]), float(q[at].sum()))
        if best is None or rank > best:
            best, rows = rank, row_indices[at]
    if rows is None or best[0] <= 0:
        return np.zeros((h, w), bool), {"rows": [], "bands": [], "gap_px": None}
    bands = []
    for y in rows:
        a, b = int(y), int(y)+1
        while a > 0 and projection[a-1] >= projection[y]/2:
            a -= 1
        while b < h and projection[b] >= projection[y]/2:
            b += 1
        if b-a >= (rows[1]-rows[0])/2:
            return np.zeros((h, w), bool), {"rows": [], "bands": [], "gap_px": None}
        bands.append([a, b])
    row_mask = np.zeros(h, bool)
    for a, b in bands:
        row_mask[a:b] = True
    scaffold = np.broadcast_to(row_mask[:, None], (h, w)).copy()
    residual = (contrast >= vc.C_STRONG) & ~scaffold
    _n, labels, stats, _centres = cv2.connectedComponentsWithStats(residual.astype(np.uint8), connectivity=8)
    min_y = stats[:, cv2.CC_STAT_TOP]
    max_y = min_y + stats[:, cv2.CC_STAT_HEIGHT] - 1
    for a, b in bands:
        touched = np.zeros(w, bool)
        if a > 0:
            ids = labels[a-1]
            touched |= (ids > 0) & (min_y[ids] <= a-2)
        if b < h:
            ids = labels[b]
            touched |= (ids > 0) & (max_y[ids] >= b+1)
        # 8-connected attachments may enter a staff row diagonally.
        touched = cv2.dilate(touched.astype(np.uint8)[None], np.ones((1, 3), np.uint8))[0].astype(bool)
        scaffold[a:b, touched] = False
    centres = [(a+b-1)/2 for a, b in bands]
    # A fitted row centre is localised by its raster band, not known at an
    # exact subpixel position. Bound spacing using all ten band pairs. These
    # intervals come from pixel geometry, with no empirical/video tolerance.
    gap_low = max((bands[j][0]-bands[i][1])/(j-i) for i in range(5) for j in range(i+1,5))
    gap_high = min((bands[j][1]-bands[i][0])/(j-i) for i in range(5) for j in range(i+1,5))
    # Average the four measured intervals. A median of alternating 20/21 px
    # gaps can differ by .25 px solely with the rasterisation phase.
    return scaffold, {"rows": centres, "bands": bands, "gap_px": float(np.mean(np.diff(centres))),
                      "gap_range_px": [gap_low,gap_high]}


def _feature_ids(features: list[dict], box: list[int]) -> list[str]:
    a, b, c, d = box
    return [f["id"] for f in features if f["bbox"][0] < c and a < f["bbox"][2]
            and f["bbox"][1] < d and b < f["bbox"][3]]


def _replica_mask(record: dict, shape) -> np.ndarray | None:
    role, fp = record.get("replica_role"), record.get("source_footprint")
    if role not in ("clef", "lead", "scaffold") or fp is None:
        return None
    box = fp.get("bbox") if isinstance(fp, dict) else fp
    a, b, c, d = map(int, box)
    if list(box) != [a, b, c, d] or not (0 <= a < c <= shape[1] and 0 <= b < d <= shape[0]):
        raise ValueError("replica footprint outside native strip")
    m = vc.unpack_mask(fp["mask"]) if isinstance(fp, dict) and "mask" in fp else np.ones((d-b, c-a), bool)
    if m.shape != (d-b, c-a):
        raise ValueError("replica mask disagrees with its bbox")
    out = np.zeros(shape, bool)
    out[b:d, a:c] = m
    return out


def verify_plan(cert_as: dict[str, dict], plan: dict, ledger_sink: dict,
                strip_pngs: dict[str, np.ndarray], *, systems: list[dict]) -> dict:
    """Check native ownership, removal pixels and independent layout invariants.

    A failures are composed by the caller; this checks A's strip commitment and
    packed feature geometry. A certificate is not fabricated for missing strips.
    Malformed input yields fail findings rather than a clean partial certificate.
    """
    payload = deepcopy(plan_records(plan, ledger_sink))
    findings, instances = [], []
    counters = Counter()

    def invalid(reason, *, sid=None, box=None, **detail):
        findings.append(vc.finding("B", "fail", "PLAN_INVALID", strip_id=sid, bbox=box,
                                   feature_ids=[], detail={"reason": reason, **detail}))

    expected = {s["id"] for s in systems if s.get("included", True)}
    excluded = set(ledger_sink.get("excluded_system_ids", []))
    expected -= excluded
    decided = set(ledger_sink.get("decided_system_ids", expected))
    if decided != expected:
        invalid("included/decided systems disagree", missing=sorted(expected-decided), extra=sorted(decided-expected))
    expected |= decided
    if payload["page_px"] != [PAGE_W, PAGE_H] or payload["dpi"] != 300:
        invalid("page geometry is not A4 at 300 dpi")
    if payload["staff_gap_mm"] is not None and payload["staff_gap_mm"] < 1.2:
        invalid("declared staff gap below 1.2 mm floor")
    margins = {"left": MARGIN_X, "right": MARGIN_X, "top": MARGIN_TOP, "bottom": MARGIN_BOTTOM}
    if payload["margins_px"] != margins:
        invalid("page margins disagree with the layout contract", expected=margins)
    page_lines, line_rank, rectangles = {}, {}, defaultdict(list)
    for pi, page in enumerate(payload["pages"]):
        if page.get("index") != pi+1:
            invalid("page indices are not sequential", page_index=pi)
        top = MARGIN_TOP + (payload["header_band_px"] if page.get("header") else 0)
        for pl in page.get("placements", []):
            lid = pl.get("line_id", pl.get("system_id"))
            try:
                x, y, w, h = [int(pl[k]) for k in ("x", "y", "w", "h")]
                if [x,y,w,h] != [pl[k] for k in ("x", "y", "w", "h")]:
                    raise ValueError("non-integer placement")
                if lid in page_lines:
                    invalid("line placed more than once", line_id=lid)
                if w <= 0 or h <= 0 or x < MARGIN_X or y < top or x+w > PAGE_W-MARGIN_X or y+h > PAGE_H-MARGIN_BOTTOM:
                    invalid("line outside bounds/margins", line_id=lid, page_index=pi, bbox_page=[x,y,x+w,y+h])
                page_lines[lid] = (pi, pl)
                line_rank[lid] = len(line_rank)
            except (KeyError, ValueError, TypeError) as exc:
                invalid("invalid page placement", error=str(exc))
        pls = page.get("placements", [])
        for i, pl in enumerate(pls):
            for other in pls[i+1:]:
                if (pl["x"] < other["x"]+other["w"] and other["x"] < pl["x"]+pl["w"]
                        and pl["y"] < other["y"]+other["h"] and other["y"] < pl["y"]+pl["h"]):
                    invalid("page lines overlap", page_index=pi, lines=[pl.get("system_id"), other.get("system_id")])
                if other["y"] < pl["y"]:
                    invalid("page line reading order is reversed", page_index=pi)

    # Validate source-unit cuts against recorded SAFE boundaries and line order.
    bounds = {b["id"]: b for b in payload["boundaries"]}
    units = payload["units"]
    unit_ids = [u["id"] for u in units]
    ordered_units = [uid for ln in payload["lines"] for uid in ln["atom_ids"]]
    if units and ordered_units != unit_ids:
        invalid("units are not placed once in source order")
    for u in units:
        for side, pos in (("left", 0), ("right", 2)):
            bid = u.get(f"{side}_boundary_id")
            if bid:
                boundary = bounds.get(bid, {})
                if ((boundary.get("class") != "SAFE"
                     and not _authorized_floor_break(boundary, payload.get("forced_breaks", [])))
                        or boundary.get("is_cut") is not True
                        or boundary.get("system_id") != u["system_id"] or boundary.get("seam_x") != u["box"][pos]):
                    invalid("unit cut is not at a recorded SAFE boundary", sid=u["system_id"], box=u["box"], boundary_id=bid)
            elif u["system_id"] in strip_pngs:
                edge = 0 if side == "left" else strip_pngs[u["system_id"]].shape[1]
                if u["box"][pos] != edge:
                    invalid("interior unit cut has no SAFE boundary", sid=u["system_id"], box=u["box"])
    unit_by_id = {u["id"]: u for u in units}
    units_by_line = {ln["id"]: [unit_by_id[uid] for uid in ln["atom_ids"] if uid in unit_by_id]
                     for ln in payload["lines"]}

    records_by = defaultdict(list)
    for i, rec in enumerate(payload["placements"]):
        records_by[rec.get("strip_id")].append((i, rec))
    for sid in records_by.keys()-expected:
        invalid("placement of an excluded/unknown system", sid=sid)
    hashes, models, feature_out, contrast_by, scaffold_by = {}, {}, {}, {}, {}
    uniform_ranges = defaultdict(list)
    vertical_mappings = defaultdict(list)
    for sid in sorted(expected):
        image, cert = strip_pngs.get(sid), cert_as.get(sid)
        if image is None or cert is None:
            findings.append(vc.finding("I", "fail", "ARTIFACT_MISMATCH", strip_id=sid, feature_ids=[],
                                       detail={"reason": "missing strip or certA"}))
            continue
        if image.dtype != np.uint8 or image.ndim not in (2,3) or image.ndim == 3 and image.shape[2] not in (3,4):
            findings.append(vc.finding("I","fail","ARTIFACT_MISMATCH",strip_id=sid,feature_ids=[],
                                       detail={"reason":"strip is not decoded 8-bit PNG pixels"}))
            continue
        digest = vc.pixels_sha256(image)
        if digest != cert.get("strip_sha256") or cert.get("strip_id") != sid:
            findings.append(vc.finding("I", "fail", "ARTIFACT_MISMATCH", strip_id=sid, feature_ids=[],
                                       detail={"reason": "strip differs from certA", "actual": digest, "expected": cert.get("strip_sha256")}))
            continue
        hashes[sid] = digest
        shape = image.shape[:2]
        contrast = vc.contrast_map(image)
        features = cert.get("features", [])
        try:
            for f in features:
                a,b,c,d = f["bbox"]
                mask = vc.unpack_mask(f["mask"])
                if (not (0 <= a < c <= shape[1] and 0 <= b < d <= shape[0]) or mask.shape != (d-b,c-a)
                        or c-a > vc.TILE or d-b > vc.TILE or f["kind"] not in ("strong","weak")):
                    raise ValueError("feature mask outside strip")
                values = contrast[b:d,a:c][mask]
                if not values.size or np.any(values < vc.C_WEAK):
                    raise ValueError("feature mask contains background")
                if f["kind"] == "weak" and np.any(values >= vc.C_STRONG):
                    raise ValueError("weak feature mask contains strong pixels")
                if "max_contrast" in f and f["max_contrast"] != int(values.max()):
                    raise ValueError("feature max contrast differs from committed strip")
            # Preserve the complete feature list. The shared helper currently
            # has label/id collisions for some tiled weak regions (lead request:
            # sort lab alongside key/ys/xs); never key masks solely by id here.
            strong_features = vc.paint(shape,[f for f in features if f["kind"]=="strong"])
            if not np.array_equal(strong_features & (contrast >= vc.C_STRONG),contrast >= vc.C_STRONG):
                raise ValueError("certA features omit strong strip pixels")
            feature_out[sid] = deepcopy(features)
        except (ValueError, KeyError, TypeError) as exc:
            findings.append(vc.finding("I", "fail", "ARTIFACT_MISMATCH", strip_id=sid, feature_ids=[],
                                       detail={"reason": "malformed certA feature", "error": str(exc)}))
            continue
        scaffold, model = _staff_model(contrast)
        contrast_by[sid], scaffold_by[sid] = contrast, scaffold
        weak_obligations = vc.paint(shape, [f for f in features if f.get("kind") == "weak"
                                            and len(f.get("supporters", [])) >= 2])
        models[sid] = model
        count = np.zeros(shape, np.uint16)
        canonical = np.zeros(shape, bool)
        replacements = np.zeros(shape, bool)
        specs, prepared, positions = [], [], []
        for index, rec in records_by[sid]:
            try:
                lid, pi = rec["line_id"], rec["page_index"]
                if lid not in page_lines or page_lines[lid][0] != pi:
                    raise ValueError("placement line/page absent from layout")
                if not isinstance(rec.get("copy_index"), int) or rec["copy_index"] < 0:
                    raise ValueError("invalid copy_index")
                stages = rec["stages"]
                if len(stages) != 2 or [s["stage"] for s in stages] != ["strip_to_line", "line_to_page"]:
                    raise ValueError("expected strip_to_line then line_to_page")
                first, last = stages
                page_matrix = _matrix(last["matrix"])
                if last["kind"] != "affine":
                    raise ValueError("line_to_page must be affine")
                _page_pi, pl = page_lines[lid]
                lo_p, hi_p = _resize(last["resample"], page_matrix, offset=[pl["x"], pl["y"]])
                if last["resample"]["output_size"] != [pl["w"], pl["h"]]:
                    raise ValueError("line resize does not match page rectangle")
                if first["kind"] == "piecewise":
                    pre = _matrix(first["pre_matrix"])
                    spec = first["pre_resample"]
                    origin = spec.get("crop_origin", [0,0])
                    sw, sh = spec["source_size"]
                    if (min(origin) < 0 or origin[0]+sw > shape[1] or origin[1]+sh > shape[0]):
                        raise ValueError("resize crop outside native strip")
                    lo_s, hi_s = _resize(spec, pre, origin=origin)
                    pieces = first["pieces"]
                    rshape = [spec["output_size"][1], spec["output_size"][0]]
                elif first["kind"] == "affine":
                    pre = np.eye(3)
                    lo_s = hi_s = 1.
                    first_matrix = _matrix(first["matrix"])
                    if not np.allclose(first_matrix[:2,2],pl.get("strip_offset_px",[0,0]),rtol=0,atol=1e-9):
                        raise ValueError("whole strip offset disagrees with page plan")
                    pieces = [{"src_bbox": [0,0,shape[1],shape[0]], "matrix": first["matrix"]}]
                    rshape = shape
                else:
                    raise ValueError("unsupported strip_to_line mapping")
                owned = np.zeros(shape, np.uint16)
                piece_boxes, transformed = [], []
                for piece in pieces:
                    matrix = _matrix(piece["matrix"])
                    if rec["copy_index"] == 0 and not rec.get("replica_role"):
                        vertical_mappings[(sid,lid)].append((pre[1,1]*matrix[1,1]*page_matrix[1,1],
                            (pre[1,2]*matrix[1,1]+matrix[1,2])*page_matrix[1,1]+page_matrix[1,2]))
                    q = list(piece["src_bbox"])
                    if q != list(map(int, q)) or not (0 <= q[0] < q[2] <= rshape[1] and 0 <= q[1] < q[3] <= rshape[0]):
                        raise ValueError("piece source box outside resampled strip")
                    repeat = piece.get("column_repeat", 1)
                    if not isinstance(repeat, int) or repeat < 1 or (repeat > 1 and q[2]-q[0] != 1):
                        raise ValueError("invalid column_repeat")
                    # Ordinary pieces translate. column_repeat explicitly records
                    # an x-axis replica, which still needs role/footprint authority.
                    if not np.allclose(matrix.diagonal()[:2], [repeat,1], rtol=0, atol=1e-9):
                        raise ValueError("piece stretches glyphs")
                    box = _native_box(q, pre, shape)
                    owned[_slice(box)] += 1
                    piece_boxes.append(box)
                    edges = np.asarray([q[:2], q[2:]], float)-.5
                    line_edges = edges * matrix.diagonal()[:2]+matrix[:2,2]
                    page_edges = line_edges * page_matrix.diagonal()[:2]+page_matrix[:2,2]+.5
                    a,b = page_edges[0]; c,d = page_edges[1]
                    if (a < pl["x"]-1e-9 or b < pl["y"]-1e-9 or c > pl["x"]+pl["w"]+1e-9 or d > pl["y"]+pl["h"]+1e-9):
                        invalid("piece clipped by line canvas", sid=sid, box=box, line_id=lid, piece_bbox_page=[a,b,c,d])
                    rectangles[pi].append((a,b,c,d,index,sid))
                    transformed.append((q, [float(a),float(b),float(c),float(d)]))
                    if rec["copy_index"] == 0:
                        positions.append((box, line_rank[lid], float(a), index))
                # Lists are records of column order. Ignore y-disjoint partitions,
                # but neither source order nor destination order may be reversed.
                for j, (q, dest) in enumerate(transformed):
                    for q2, dest2 in transformed[j+1:]:
                        if q[1] < q2[3] and q2[1] < q[3] and (q[2] <= q2[0] or q2[2] <= q[0]):
                            if q[0] > q2[0] or dest[0] > dest2[0]:
                                invalid("piece column order reversed", sid=sid, line_id=lid, record_index=index)
                                break
                fp = _replica_mask(rec, shape)
                role = rec.get("replica_role")
                authorised = fp is not None and np.array_equal(owned > 0, fp) and not np.any(owned > 1)
                if authorised and role == "scaffold" and np.any(fp & (contrast >= vc.C_STRONG) & ~scaffold):
                    authorised = False
                if role is not None and not authorised:
                    invalid("replica role lacks an exact valid source footprint", sid=sid, record_index=index)
                if authorised:
                    replacements |= fp
                else:
                    count += owned
                if rec["copy_index"] == 0 and not authorised:
                    if units:
                        permitted = np.zeros(shape, bool)
                        for unit in units_by_line.get(lid, []):
                            if unit["system_id"] == sid:
                                permitted[_slice(_native_box(unit["box"], np.eye(3), shape))] = True
                        outside = (owned > 0) & ~permitted
                        if outside.any():
                            invalid("piece ownership disagrees with SAFE unit placement", sid=sid,
                                    box=_bbox(outside), line_id=lid, record_index=index)
                    elif first["kind"] == "piecewise" and len({r["line_id"] for _i,r in records_by[sid] if r.get("copy_index") == 0}) > 1:
                        invalid("multi-line strip cut has no recorded SAFE units", sid=sid)
                    canonical |= owned > 0
                    specs.append((pre, lid, rshape))
                    if model["gap_px"] is None:
                        invalid("five staff rows cannot be measured", sid=sid)
                    else:
                        gap = model["gap_px"]
                        gap_lo,gap_hi = model["gap_range_px"]
                        uniform_ranges[lid].append((gap_lo*lo_s*lo_p, gap_hi*hi_s*hi_p))
                        if gap_hi*hi_s*hi_p < 1.2*MM-1e-9:
                            invalid("staff gap below 1.2 mm floor", sid=sid, line_id=lid, delivered_gap_px=gap*pre[1,1]*page_matrix[1,1])
                prepared.append((rec, owned > 0, bool(authorised), pre, piece_boxes))
            except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
                invalid("malformed placement", sid=sid, record_index=index, error=str(exc))

        removed_union = np.zeros(shape, bool)
        removed_fail = np.zeros(shape, bool)
        removed_review = np.zeros(shape, bool)
        footprints = []
        for rem in payload["removed"]:
            if rem.get("strip_id") != sid:
                continue
            try:
                if "src_bbox_S" in rem:
                    q = rem["src_bbox_S"]
                    if list(q) != list(map(int,q)) or not (0 <= q[0] < q[2] <= shape[1] and 0 <= q[1] < q[3] <= shape[0]):
                        raise ValueError("removal outside native strip")
                    boxes = [_native_box(rem["src_bbox_S"], np.eye(3), shape)]
                else:
                    q = rem["src_bbox_R"]
                    matched = [(m,size) for m,lid,size in specs if lid == rem.get("line_id")]
                    if list(q) != list(map(int,q)) or any(not (0 <= q[0] < q[2] <= size[1] and 0 <= q[1] < q[3] <= size[0]) for _m,size in matched):
                        raise ValueError("removal outside resampled strip")
                    matrices = {vc.json_sha256(m.tolist()): m for m,size in matched}
                    if not matrices:
                        raise ValueError("removal has no matching canonical resample stage")
                    boxes = [_native_box(rem["src_bbox_R"], m, shape) for m in matrices.values()]
                    if len({tuple(b) for b in boxes}) != 1:
                        raise ValueError("ambiguous native removal footprint")
                box = boxes[0]
                region = np.zeros(shape, bool)
                region[_slice(box)] = True
                bad = region & (contrast >= vc.C_STRONG) & ~scaffold
                replica = (rem.get("replica_role") in ("clef", "lead")
                           and np.all(replacements[bad]) and bad.any())
                allowed = region & (scaffold | (contrast < vc.C_WEAK))
                if replica:
                    allowed |= bad
                    removed_review |= bad
                else:
                    removed_fail |= bad
                # Isolated weak features cannot be dismissed as paper either.
                weak = region & weak_obligations & ~scaffold
                removed_review |= weak
                removed_union |= allowed
                fp = _footprint(allowed, op=rem.get("op"), line_id=rem.get("line_id"), replica_role=rem.get("replica_role"))
                if fp:
                    footprints.append(fp)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                invalid("malformed removal", sid=sid, error=str(exc), op=rem.get("op"))
        for mask, severity in ((removed_fail,"fail"), (removed_review & ~removed_fail,"review_required")):
            groups = vc.group_findings(mask, "B", severity, "REMOVED_FEATURE", strip_id=sid,
                                       detail={"reason": "removal intersects non-scaffold ink",
                                               "review_required": severity == "review_required"})
            for f in groups:
                f["feature_ids"] = _feature_ids(features, f["bbox"]) if "bbox" in f else []
            findings.extend(groups)
        groups = vc.group_findings(count > 1, "B", "fail", "DUPLICATED_CONTENT", strip_id=sid,
                                   detail={"reason": "native centre owned more than once in the same canonical occurrence"})
        for f in groups:
            f["feature_ids"] = _feature_ids(features, f["bbox"]) if "bbox" in f else []
        findings.extend(groups)
        # Outer margins are removed paper only when the pixels independently say
        # so. Interior missing columns cannot be explained away by white pixels.
        missing = ~canonical & ~removed_union
        active_cols = np.flatnonzero(canonical.any(axis=0))
        edge_paper = np.zeros(shape, bool)
        if active_cols.size:
            edge_paper[:,:active_cols[0]] = contrast[:,:active_cols[0]] < vc.C_WEAK
            edge_paper[:,active_cols[-1]+1:] = contrast[:,active_cols[-1]+1:] < vc.C_WEAK
        missing &= ~edge_paper
        if missing.any():
            invalid("unowned pixels/gap without authorised removal", sid=sid, box=_bbox(missing),
                    unowned_pixels=int(missing.sum()), nonpaper_pixels=int((missing & (contrast >= vc.C_WEAK)).sum()))
        # Cross-record ordering includes line/page order and partial-y pieces.
        reversed_order = False
        for i, (box, rank, x, _idx) in enumerate(positions):
            for other, rank2, x2, _idx2 in positions[i+1:]:
                if box[1] < other[3] and other[1] < box[3] and (box[2] <= other[0] or other[2] <= box[0]):
                    if (box[0] < other[0]) != ((rank,x) < (rank2,x2)):
                        reversed_order = True
        if reversed_order:
            invalid("source columns reverse output reading order", sid=sid)
        for rec, owned, authorised, _pre, boxes in prepared:
            instances.append({"line_id": rec["line_id"], "page_index": rec["page_index"], "copy_index": rec["copy_index"],
                "strip_id": sid, "owned_strip_bbox": _bbox(owned), "owned_strip_boxes": boxes,
                "transform": deepcopy(rec["stages"]), "removal_footprints": [f for f in footprints if f["line_id"] == rec["line_id"]],
                "replica_role": rec.get("replica_role") if authorised else None})
        # Store outer paper as two small footprints, not a full strip mask.
        for a,b in ((0,int(active_cols[0]) if active_cols.size else 0),
                    (int(active_cols[-1])+1 if active_cols.size else shape[1],shape[1])):
            if a < b:
                footprints.append({"bbox": [a,0,b,shape[0]], "mask": vc.pack_mask(edge_paper[:,a:b]), "op": "verified_paper_margin"})
        counters.update(native_pixels=shape[0]*shape[1], owned_pixels=int(canonical.sum()),
                        duplicated_pixels=int((count > 1).sum()), unowned_pixels=int(missing.sum()),
                        removed_feature_pixels=int(removed_fail.sum()), authorised_replica_pixels=int(replacements.sum()))
        models[sid]["removal_footprints"] = footprints

    for lid, ranges in uniform_ranges.items():
        if max(r[0] for r in ranges) > min(r[1] for r in ranges)+1e-9:
            invalid("staff scales are not uniform within line", line_id=lid, delivered_gap_ranges=ranges)
    for (sid,lid), mappings in vertical_mappings.items():
        if not np.allclose(mappings,mappings[0],rtol=0,atol=1e-9):
            invalid("pieces of one strip have different vertical mappings within line",sid=sid,line_id=lid)
    generated_footprints = []
    for gi, origin in enumerate(payload["generated_origins"]):
        try:
            # This helper verifies the template's stored decoded-pixel hash.
            # Its fidelity is C's responsibility; B also checks draw geometry.
            template = unpack_crop(origin["template"])
            x,y = origin["origin"]
            pi = origin["page_index"]
            h,w = template.shape[:2]
            if (not isinstance(pi,int) or not 0 <= pi < len(payload["pages"])
                    or [int(x),int(y)] != [x,y] or x < 0 or y < 0 or x+w > PAGE_W or y+h > PAGE_H):
                raise ValueError("generated origin outside page")
            rectangles[pi].append((x,y,x+w,y+h,len(payload["placements"])+gi,None))
            if origin.get("kind") == "staff_scaffold":
                sid = origin["strip_id"]
                if sid not in hashes:
                    raise ValueError("generated scaffold has no checked source strip")
                spec = origin["source_resample"]
                sw,sh = spec["source_size"]
                crop = spec.get("crop_origin",[0,0])
                if min(crop) < 0 or crop[0]+sw > strip_pngs[sid].shape[1] or crop[1]+sh > strip_pngs[sid].shape[0]:
                    raise ValueError("generated source crop outside native strip")
                scale = np.asarray(spec["output_size"],float)/np.asarray(spec["source_size"],float)
                pre = np.eye(3)
                pre[0,0],pre[1,1] = scale
                pre[:2,2] = (scale-1)/2-scale*np.asarray(spec.get("crop_origin",[0,0]))
                _resize(spec,pre,origin=spec.get("crop_origin",[0,0]))
                col = origin["source_column_R"]
                if not isinstance(col,int) or not 0 <= col < spec["output_size"][0]:
                    raise ValueError("invalid scaffold source column")
                box = _native_box([col,0,col+1,spec["output_size"][1]],pre,strip_pngs[sid].shape[:2])
                region = np.zeros(strip_pngs[sid].shape[:2],bool)
                region[_slice(box)] = True
                bad = region & (contrast_by[sid] >= vc.C_STRONG) & ~scaffold_by[sid]
                if bad.any():
                    invalid("generated scaffold replicates non-scaffold source", sid=sid, box=_bbox(bad), generated_index=gi)
                fp = _footprint(region & scaffold_by[sid],strip_id=sid,replica_role="scaffold",generated_index=gi)
                if fp:
                    generated_footprints.append(fp)
        except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
            findings.append(vc.finding("I","fail","ARTIFACT_MISMATCH",feature_ids=[],
                                       detail={"reason":"invalid generated origin/template", "generated_index":gi,"error":str(exc)}))
    # Actual draw rectangles, rather than dilated kernel footprints. Any overlap
    # can hide owned source pixels, even if both records have identical imagery.
    for pi, rects in rectangles.items():
        arr = np.asarray([r[:4] for r in rects], float)
        overlaps = []
        for i, r in enumerate(rects):
            hits = np.flatnonzero((arr[i+1:,0] < r[2]-1e-9) & (arr[i+1:,2] > r[0]+1e-9)
                                 & (arr[i+1:,1] < r[3]-1e-9) & (arr[i+1:,3] > r[1]+1e-9))+i+1
            overlaps.extend((r[4],rects[j][4]) for j in hits)
        if overlaps:
            invalid("draw-order overlap can hide owned content", page_index=pi,
                    record_pairs=[list(p) for p in sorted(set(overlaps))], overlapping_piece_pairs=len(overlaps))
    counters["strips"] = len(hashes)
    counters["instances"] = len(instances)
    for f in findings:
        if "bbox" in f and f.get("strip_id") in feature_out and not f.get("feature_ids"):
            f["feature_ids"] = _feature_ids(feature_out[f["strip_id"]],f["bbox"])
    return {"plan_sha256": vc.json_sha256(payload), "plan_records": payload, "strips": hashes,
            "instances": instances, "features": feature_out, "staff_models": models,
            "generated_origins": payload["generated_origins"], "generated_source_footprints": generated_footprints,
            "pages": payload["pages"],
            "findings": findings, "counters": dict(counters)}
