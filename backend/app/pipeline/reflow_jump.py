"""Jump-view seam registration (docs/archive/reflow/JUMP_PLAN.md, milestone 1).

A jump-view video shows one continuous score line; every few seconds the view
jumps right and consecutive views overlap. The tracker already gives one
episode per stable display. This module

* builds an overlay-free composite per display (``reflow_strips.compose_members``),
* finds screen-fixed content at the left edge (a translucent panel with a clef
  and a measure number, or a sticky clef; 0 when absent),
* registers consecutive displays of one slot by a coarse-to-fine search over
  horizontal offsets of their overlap (staff lines removed), and verifies a
  seam only when the match is good, clearly better than any other offset, and
  wide enough,
* classifies runs of verified jumps as ``jump_view`` (smooth scroll and
  videos without horizontal motion are not jump view).

Milestone 1 only records the result (``reflow/jump.json``); no output changes.
Everything is fail-closed: a seam that is not verified is reported with the
reason and never used to merge content.

Coordinates: crop pixels of the manifest (work-scaled). A seam's ``dx`` means
column ``u`` of display B shows the content of column ``u + dx`` of display A.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import minority_content as mc
from app.pipeline import overlay_composite as oc
from app.pipeline import page_diff
from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_strips as rs
from app.pipeline import system_detect as sd

# reflow_jump-6: a gate pair that fails the coarse overlap check is checked again without the screen-fixed
# left panel (detect_panel), as register_seams leaves it out
# reflow_jump-5: a sparse (low-ink) window offset is dropped when another forward offset over the
# whole feasible range, or one / two local bar widths away, matches comparably (no new offset is picked)
JUMP_VERSION = "reflow_jump-6"
SCHEMA_VERSION = 1

ImageLoader = Callable[[Dict[str, Any]], np.ndarray]

# Thresholds. Frozen 2026-10-07 on the two development videos only (_7gPeY5Lcrk,
# qA-M_f0DMjw) before the held-out run; see docs/reflow/JUMP_FREEZE.md.
CONFIG: Dict[str, Any] = {
    # registration
    "ink_level": 64,  # feature value (255 - gray, staff lines removed) that counts as ink
    "coarse_gap_px": 4.0,  # coarse search resolution: staff space in coarse pixels
    "coarse_candidates": 6,  # coarse local minima refined at full resolution
    "refine_radius_coarse": 2,  # full-resolution refinement window, in coarse pixels
    "distinct_gaps": 0.5,  # a second candidate must lie this far (staff spaces) from the best
    "resid_max": 25.0,  # mean |A-B| over inked overlap pixels (0..255)
    "ratio_min": 2.0,  # (second-best residual + floor) / (best residual + floor)
    "resid_floor": 2.0,  # residual noise floor: two near-perfect offsets are ambiguous, not "infinitely" apart
    "overlap_min_gaps": 2.2,  # overlap width outside the panel (~40 px at an 18 px staff space)
    "min_ink_gaps2": 4.0,  # inked overlap pixels, in staff spaces squared (about four note heads)
    "dy_max_px": 2,  # vertical offset searched at full resolution
    "row_tol_gaps": 0.5,  # staff top of both displays must agree
    "no_shift_gaps": 0.5,  # |dx| below this: the same view (no jump)
    # screen-fixed panel at the left edge
    "panel_static_iou": 0.6,
    "panel_break_gaps": 1.0,
    "panel_max_frac": 0.25,
    "panel_min_static_gaps": 0.5,
    "panel_margin_gaps": 0.8,  # ~15 px bleed margin at an 18 px staff space
    "panel_faded_contrast": 0.6,  # darkest ink below this share of the display's: under a panel
    "panel_min_pairs": 3,
    "fixed_pixel_fraction": 0.5,  # inked at the same screen position in this share of consecutive pairs
    # run classification
    "run_min_seams": 3,
    "jump_min_dx_frac": 0.15,  # of the content width (crop width minus panel)
    "dwell_min_sec": 1.0,
    "transition_max_sec": 1.5,
    "prior_tol_frac": 0.1,  # cursor-motion prior: sanity flag only
    # gate for videos the tracker did not mark as horizontal motion
    "gate_pair_fraction": 0.3,
    "gate_max_pairs": 40,
    "gate_coarse_gap_px": 3.0,
    "max_members": 9,
    # seam resolution (milestone 2): an ambiguous seam (periodic content) is resolved only when
    # exactly one plausible offset fits every applicable constraint and none contradicts it
    "resolve_min_verified": 5,  # verified jumps of the slot needed for a typical jump size
    "resolve_tol_frac": 0.03,  # typical jump size +- this share of the display width
    "resolve_max_spread_frac": 0.5,  # robust spread (MAD) of the verified jumps, as a share of the tolerance
    "prior_fit_sec": 1.5,  # cursor track fitted over this much of each display's end / start
    "prior_min_seams": 5,  # verified jumps with a cursor prior needed to judge the prior
    "prior_reliable_frac": 0.05,  # prior used only when its 90th-percentile error on verified jumps is below this share of the width
    "numbers_min_votes": 3,  # measure-number reads (tesseract) that must agree
    # reflow_jump-4: a seam whose best registration failed only on residual / ambiguity / ink may be
    # resolved too, and the typical-jump window also offers sparse (low-ink) offsets that match almost
    # well (e.g. an overlap of rest bars); either path needs >= 2 constraints besides "forward"
    "resolve_failures": ["ambiguous_offset", "residual_high", "overlap_blank"],
    "low_ink_gaps2": 1.5,  # ink floor (staff spaces squared) for a window offset ...
    "low_ink_ratio_min": 4.0,  # ... that is this much better than every other offset of the window (residual <= resid_max)
    # reflow_jump-5: ... and than every other forward offset with overlap: the whole feasible range plus the
    # offsets one and two local bar widths either side (rest bars repeat: a one-bar shift fits as well)
    "low_ink_rival_gaps2": 0.75,  # a rival offset needs at least this much ink (staff spaces squared) to compare
    "low_ink_rival_win_gaps": 0.5,  # each bar-width rival is searched within +- this (bar widths vary)
    "bar_min_gaps": 3.0,  # barlines closer than this are one barline (double / repeat bars), not a bar
    # panorama strips
    "cut_margin_gaps": 1.0,  # the stitch cut stays this far from each display's usable edge
    "cut_center_weight": 0.25,  # pull of the cut toward the middle of the overlap (times the median column difference)
    "chunk_max_gaps": 650.0,  # a panorama strip is cut into chunks of at most this width (staff spaces) at clear barlines
    "chunk_min_gaps": 60.0,  # ... and no chunk narrower than this unless nothing else is possible
    "chunk_clear_gaps": 0.4,  # the chunk cut sits at least this far right of the barline ...
    "chunk_reach_gaps": 1.0,  # ... and at most this far, in a column clear over the full height
    "clef_lead_gaps": 1.2,  # paper between the copied clef and a chunk's first measure
}


def config_hash(cfg: Optional[Dict[str, Any]] = None) -> str:
    blob = json.dumps(cfg or CONFIG, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


# --------------------------------------------------------------------------- displays


def _evenly(items: Sequence[Any], count: int) -> List[Any]:
    if len(items) <= count:
        return list(items)
    idx = sorted(set(np.linspace(0, len(items) - 1, count).round().astype(int).tolist()))
    return [items[i] for i in idx]


def slot_sequences(tracking: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Confirmed episodes per slot in time order (unconfirmed ones, e.g. a frame in
    the middle of an eased jump, are skipped and listed on the seam)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for ep in sorted(tracking.get("episodes", []), key=lambda e: (e["t_start"], e["id"])):
        out.setdefault(str(ep.get("slot_id")), []).append(ep)
    return out


def _mid_region(ep: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    mid = len(ep["observation_ids"]) // 2
    obs = obs_by[ep["observation_ids"][mid]]
    rid = ep["region_ids"][mid]
    return obs, next((r for r in obs.get("system_regions") or [] if r["region_id"] == rid), None)


def _episode_rows(ep: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]]) -> Tuple[int, int]:
    obs, reg = _mid_region(ep, obs_by)
    h = int(obs.get("crop_size", [0, 0])[1] or 0)
    if reg is None:
        return 0, h
    band = reg.get("row_band") or reg.get("bbox")
    return int(band[1]), int(band[3])


def _episode_staff_y(ep: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]]) -> List[float]:
    _obs, reg = _mid_region(ep, obs_by)
    return [float(y) for y in (reg or {}).get("staff_y") or []]


def features(comp: np.ndarray, gap: float, staff_y: Sequence[float] = ()) -> np.ndarray:
    """Ink darkness (0..255) of the ink outside the staff-line rows: what registration
    compares. The staff rows come from the tracker (the same rows in every display),
    so a long beam is never mistaken for a staff line in one display only."""
    norm, _inv = sd.normalize_polarity(comp)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm
    ink = page_diff._ink_mask(gray)
    keep = cv2.dilate(ink, np.ones((3, 3), np.uint8)) > 0
    f = (255 - gray.astype(np.int16)).clip(0, 255).astype(np.uint8)
    f[~keep] = 0
    half = max(1, int(round(0.12 * gap)))
    for y in staff_y:
        yc = int(round(y))
        f[max(0, yc - half): yc + half + 1] = 0
    return f


def display_record(ep: Dict[str, Any], manifest: Dict[str, Any], load: ImageLoader, obs_by: Dict[str, Dict[str, Any]],
                   cfg: Dict[str, Any], *, keep_composite: bool = False, ledger: bool = False,
                   evidence_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Overlay-free composite of one display, its features and the overlay columns no member clears."""
    gap = float(ep["staff_gap_px"])
    ids = _evenly(list(ep["observation_ids"]), int(cfg["max_members"]))
    imgs = [load(obs_by[i]) for i in ids]
    shape = imgs[len(imgs) // 2].shape
    pairs = [(i, im) for i, im in zip(ids, imgs) if im.shape == shape]
    memo: Dict[Any, np.ndarray] = {}
    keys = [(i, "full") for i, _im in pairs]
    comp, info = rs.compose_members([im for _i, im in pairs], gap, keys=keys, memo=memo)
    covered = np.ones(shape[1], dtype=bool)
    for k, im in zip(keys, [im for _i, im in pairs]):
        covered &= rs._overlay_cols_of(im, gap, k, memo)
    y0, y1 = _episode_rows(ep, obs_by)
    y0, y1 = max(0, y0), min(shape[0], y1 if y1 > y0 else shape[0])
    norm, _inv = sd.normalize_polarity(comp)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm
    contrast = np.percentile(255 - gray[y0:y1].astype(np.int16), 98, axis=0).astype(np.float32)
    rec = {
        "id": ep["id"], "gap": gap, "rows": (y0, y1), "width": int(shape[1]), "contrast": contrast,
        "features": features(comp, gap, _episode_staff_y(ep, obs_by)), "covered": covered,
        "staff_y": _episode_staff_y(ep, obs_by),
        "members_used": int(info.get("members_used", 1)), "unrecovered_columns": int(covered.sum()),
    }
    if ledger:
        rec["ledger"] = _display_ledger(ep, manifest, load, obs_by, pairs, info, gap, evidence_dir=evidence_dir)
    if keep_composite:
        rec["composite"] = comp
    return rec


def _merge_ledger(fragments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"version": rl.VERSION}
    for fragment in fragments:
        if fragment.get("source_video"):
            out.setdefault("source_video", fragment["source_video"])
        if fragment.get("evidence_root"):
            root = str(Path(fragment["evidence_root"]).resolve())
            if out.get("evidence_root", root) != root:
                raise ValueError("jump ledger evidence roots differ")
            out["evidence_root"] = root
        for key, value in fragment.items():
            if isinstance(value, list):
                out.setdefault(key, []).extend(value)
    for key in ("observations", "displays", "items", "representations", "dispositions", "display_dispositions",
                "generated_origins", "occurrence_remaps", "observation_associations"):
        out.setdefault(key, [])
    return out


def _display_ledger(ep: Dict[str, Any], manifest: Dict[str, Any], load: ImageLoader,
                    obs_by: Dict[str, Dict[str, Any]], pairs: Sequence[Tuple[str, np.ndarray]],
                    info: Dict[str, Any], gap: float, *,
                    evidence_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Stream one display's compatible members; shape rejects keep separate raw inventories."""
    did = f"jump:{ep['id']}"
    ref = pairs[int(info["reference_index"])][1]
    ref_gray = rs._alignment_gray(ref)
    used = {oid for oid, _im in pairs}
    source = str((manifest.get("source") or {}).get("path") or manifest.get("video_id") or "unknown_source")
    compatible, rejected, associations = [], [], []
    current: Dict[str, Any] = {}

    def canvas(obs):
        image = load(obs)
        current.clear()
        current.update(id=obs["id"], image=image)
        return image

    def occluded(obs):
        image = current["image"] if current.get("id") == obs["id"] else load(obs)
        mask = rs._overlay_mask2d_of(image, gap, (obs["id"], "full"), None)
        current.clear()
        return mask

    for oid in ep["observation_ids"]:
        obs = obs_by[oid]
        im = load(obs)
        h, w = im.shape[:2]
        rh, rw = min(h, ref.shape[0]), min(w, ref.shape[1])
        # Shape rejects still retain their full crop; only registration uses the common window.
        reference = ref_gray[:rh, :rw]
        window = cv2.createHanningWindow((rw, rh), cv2.CV_32F)
        base, _ = cv2.phaseCorrelate(reference.copy(), reference.copy(), window)
        shift, _ = cv2.phaseCorrelate(reference.copy(), rs._alignment_gray(im)[:rh, :rw].copy(), window)
        rel = np.asarray(shift) - base
        uncertainty = float(np.hypot(*rel)) if np.isfinite(rel).all() else None
        same_shape = im.shape == ref.shape
        member = {"id": oid, "timestamp": obs["t_sec"], "image": lambda obs=obs: canvas(obs), "roi_origin": [0, 0],
                  "registration_shift": [0, 0], "registration_uncertainty": uncertainty,
                  "source_to_native": manifest.get("source_to_crop"), "usable": True,
                  "occluded": lambda obs=obs: occluded(obs),
                  "frame_ref": {"observation_id": oid, "crop_box": [0, 0, w, h]}}
        target = did if same_shape else f"{did}:rejected:{oid}"
        (compatible if same_shape else rejected).append(member)
        assoc = {"obs_id": oid, "stage": "jump", "display_id": target, "occurrence_id": target}
        associations.append(dict(assoc, role="offered", reason=None))
        if oid in used:
            associations.append(dict(assoc, role="used", reason=None))
        elif not same_shape:
            associations.append(dict(assoc, role="rejected_registration", reason="crop_shape_mismatch"))
        else:
            associations.append(dict(assoc, role="offered", reason="not_sampled_for_composite"))
        del im
    fragments = [rl.record_obligations(source_video=source, display_id=did, occurrence_id=did,
                                      members=compatible, evidence_dir=evidence_dir)]
    for member in rejected:
        target = f"{did}:rejected:{member['id']}"
        raw = rl.record_obligations(source_video=source, display_id=target, occurrence_id=target,
                                    members=[member], evidence_dir=evidence_dir)
        raw["display_dispositions"].append({"kind": "display_unresolved", "terminal": "unresolved",
                                             "display_id": target, "reason": "crop_shape_mismatch"})
        fragments.append(raw)
    fragment = _merge_ledger(fragments)
    fragment["observation_associations"] = associations
    return fragment


# --------------------------------------------------------------------------- panel


def detect_panel(displays: Sequence[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Screen-fixed content anchored at the left edge: columns whose non-staff ink is
    the same in consecutive displays (a translucent panel's clef/time signature, a
    sticky clef). Returns {"right": px excluded from x=0, ...}; right=0 when absent."""
    if len(displays) < 2:
        return {"right": 0, "method": "static_ink_iou", "pairs": 0, "reason": "too_few_displays"}
    w = min(d["width"] for d in displays)
    gap = float(np.median([d["gap"] for d in displays]))
    lvl = int(cfg["ink_level"])
    ious = []
    for a, b in zip(displays, displays[1:]):
        if a["features"].shape != b["features"].shape:
            continue
        y0, y1 = max(a["rows"][0], b["rows"][0]), min(a["rows"][1], b["rows"][1])
        ia = a["features"][y0:y1, :w] > lvl
        ib = b["features"][y0:y1, :w] > lvl
        inter = (ia & ib).sum(axis=0).astype(np.float32)
        union = (ia | ib).sum(axis=0).astype(np.float32)
        ious.append(np.where(union > 3, inter / np.maximum(union, 1), np.nan))
    if len(ious) < int(cfg["panel_min_pairs"]):
        return {"right": 0, "method": "static_ink_iou", "pairs": len(ious), "reason": "too_few_pairs"}
    arr = np.array(ious)
    defined = (~np.isnan(arr)).sum(axis=0)
    med = np.full(w, np.nan, dtype=np.float32)
    ok = defined >= max(2, len(ious) // 3)
    with np.errstate(all="ignore"):
        med[ok] = np.nanmedian(arr[:, ok], axis=0)
    limit = int(cfg["panel_max_frac"] * w)
    last, bad, static = -1, 0, 0
    for x in range(limit):
        v = med[x]
        if np.isnan(v):
            continue
        if v >= cfg["panel_static_iou"]:
            last, bad = x, 0
            static += 1
        elif v < cfg["panel_static_iou"] / 2:
            bad += 1
            if bad > cfg["panel_break_gaps"] * gap:
                break
    fixed_edge = last + 1 if (last >= 0 and static >= cfg["panel_min_static_gaps"] * gap) else 0
    tone_edge = _faded_edge(displays, w, gap, limit, cfg)
    info = {"method": "static_ink_iou+faded_columns", "pairs": len(ious), "static_columns": int(static),
            "fixed_ink_edge": int(fixed_edge), "faded_edge": int(tone_edge)}
    if not fixed_edge and not tone_edge:
        return dict(info, right=0, reason="no_fixed_ink_or_faded_columns")
    margin = int(round(cfg["panel_margin_gaps"] * gap))
    return dict(info, right=int(min(limit, max(fixed_edge, tone_edge) + margin)), margin_px=margin)


def _faded_edge(displays: Sequence[Dict[str, Any]], w: int, gap: float, limit: int, cfg: Dict[str, Any]) -> int:
    """Right edge of a translucent (or opaque) panel at the left: columns whose darkest
    ink, staff lines included, stays well below the rest of the display in most
    displays. 0 when the left columns look like the rest."""
    prof = np.median(np.array([d["contrast"][:w] for d in displays]), axis=0)
    ref = float(np.median(prof[int(0.3 * w): int(0.95 * w)]))
    if ref <= 0:
        return 0
    low = prof < cfg["panel_faded_contrast"] * ref
    run = max(2, int(round(gap)))
    x = 0
    while x < limit:
        if not low[x: x + run].any():  # a gap-wide stretch at full contrast: the panel ended
            break
        x += 1
    if x < cfg["panel_min_static_gaps"] * gap or low[:x].mean() < 0.8:
        return 0
    return int(x)


def screen_fixed_pixels(displays: Sequence[Dict[str, Any]], cfg: Dict[str, Any]) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """Ink at the same screen position in most consecutive displays (a label next to
    the panel, a logo, a sticky clef) while the score moves. Such pixels are left out
    of the comparison everywhere (dilated by a pixel or two)."""
    shapes = {d["features"].shape for d in displays}
    if len(displays) < int(cfg["panel_min_pairs"]) + 1 or len(shapes) != 1:
        return None, {"pixels": 0, "reason": "too_few_displays"}
    lvl = int(cfg["ink_level"])
    count = np.zeros(next(iter(shapes)), dtype=np.uint16)
    for a, b in zip(displays, displays[1:]):
        count += ((a["features"] > lvl) & (b["features"] > lvl)).astype(np.uint16)
    fixed = count >= cfg["fixed_pixel_fraction"] * (len(displays) - 1)
    if not fixed.any():
        return None, {"pixels": 0}
    fixed = cv2.dilate(fixed.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    ys, xs = np.nonzero(fixed)
    return fixed, {"pixels": int(fixed.sum()), "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]}


# --------------------------------------------------------------------------- registration


def _residual(fa: np.ndarray, fb: np.ndarray, va: np.ndarray, vb: np.ndarray, dx: int, lvl: float, *,
              dy: int = 0, tolerant: bool = False, strong: Optional[List[int]] = None) -> Tuple[float, int, int]:
    """(mean |A-B| over inked pixels, inked pixels, overlap columns) for offset (dx, dy):
    column u, row y of B shows column u+dx, row y+dy of A. ``tolerant``: a pixel only
    differs by what the other image lacks within one pixel (sub-pixel offsets and
    video scaling do not count as a mismatch)."""
    h, w = fa.shape
    if dx >= 0:
        a, b, v = fa[:, dx:], fb[:, : w - dx], va[dx:] & vb[: w - dx]
    else:
        a, b, v = fa[:, : w + dx], fb[:, -dx:], va[: w + dx] & vb[-dx:]
    if dy > 0:
        a, b = a[dy:], b[: h - dy]
    elif dy < 0:
        a, b = a[: h + dy], b[-dy:]
    ncols = int(v.sum())
    if ncols == 0:
        return float("inf"), 0, 0
    a = a[:, v]
    b = b[:, v]
    union = (a > lvl) | (b > lvl)
    n = int(union.sum())
    if n == 0:
        return float("inf"), 0, ncols
    if tolerant:
        k = np.ones((3, 3), np.uint8)
        a16, b16 = a.astype(np.int16), b.astype(np.int16)
        d = np.maximum(a16 - cv2.dilate(b, k).astype(np.int16), 0) + np.maximum(b16 - cv2.dilate(a, k).astype(np.int16), 0)
    else:
        d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    if strong is not None:
        strong.append(int((d > lvl).sum()))
    return float(d[union].mean()), n, ncols


def _downscale(f: np.ndarray, valid: np.ndarray, s: int) -> Tuple[np.ndarray, np.ndarray]:
    if s <= 1:
        return f, valid
    h, w = f.shape
    wc, hc = w // s, max(1, h // s)
    small = cv2.resize(f[: hc * s, : wc * s], (wc, hc), interpolation=cv2.INTER_AREA)
    vs = valid[: wc * s].reshape(wc, s).all(axis=1)
    return small, vs


def _local_minima(curve: Dict[int, Tuple[float, int, int]], k: int, sep: int, eligible: Callable[[Tuple[float, int, int]], bool]) -> List[int]:
    keys = sorted(curve)
    vals = np.array([curve[x][0] for x in keys])
    mins = []
    for i, x in enumerate(keys):
        v = vals[i]
        if not np.isfinite(v) or not eligible(curve[x]):
            continue
        lo, hi = max(0, i - 1), min(len(keys), i + 2)
        if v <= vals[lo:hi].min():
            mins.append(x)
    mins.sort(key=lambda x: curve[x][0])
    picked: List[int] = []
    for x in mins:
        if all(abs(x - p) >= sep for p in picked):
            picked.append(x)
        if len(picked) >= k:
            break
    return picked


def register_pair(a: Dict[str, Any], b: Dict[str, Any], panel_right: int, cfg: Dict[str, Any], *,
                  coarse_only: bool = False, coarse_gap_px: Optional[float] = None) -> Dict[str, Any]:
    """Horizontal offset of display B against display A (coarse-to-fine residual search)."""
    gap = float(min(a["gap"], b["gap"]))
    y0, y1 = max(a["rows"][0], b["rows"][0]), min(a["rows"][1], b["rows"][1])
    w = min(a["width"], b["width"])
    fa = a["features"][y0:y1, :w]
    fb = b["features"][y0:y1, :w]
    va = ~a["covered"][:w].copy()
    vb = ~b["covered"][:w].copy()
    va[:panel_right] = False
    vb[:panel_right] = False
    lvl = float(cfg["ink_level"])
    min_overlap = cfg["overlap_min_gaps"] * gap
    min_ink = cfg["min_ink_gaps2"] * gap * gap
    s = max(1, int(round(gap / float(coarse_gap_px or cfg["coarse_gap_px"]))))
    ca, cva = _downscale(fa, va, s)
    cb, cvb = _downscale(fb, vb, s)
    lim_c = int((w - panel_right - min_overlap) // s)
    curve_c: Dict[int, Tuple[float, int, int]] = {}
    for dxc in range(-lim_c, lim_c + 1):
        curve_c[dxc] = _residual(ca, cb, cva, cvb, dxc, lvl / 2.0)
    elig_c = lambda r: r[2] * s >= min_overlap and r[1] * s * s >= min_ink  # noqa: E731
    sep_c = max(1, int(np.ceil(cfg["distinct_gaps"] * gap / s)))
    cands = _local_minima(curve_c, int(cfg["coarse_candidates"]), sep_c, elig_c)
    out: Dict[str, Any] = {"scale": s, "rows": [int(y0), int(y1)], "panel_right": int(panel_right)}
    if not cands:
        out.update(dx=None, residual=None, second_dx=None, second_residual=None, ratio=None, overlap_px=0, ink_px=0,
                   reason="no_candidate")
        return out
    if coarse_only:
        best = cands[0]
        second = cands[1] if len(cands) > 1 else None
        r1 = curve_c[best][0]
        r2 = curve_c[second][0] if second is not None else max(v[0] for v in curve_c.values() if np.isfinite(v[0]))
        fl = float(cfg["resid_floor"])
        out.update(dx=best * s, residual=round(r1, 2), second_dx=None if second is None else second * s,
                   second_residual=round(r2, 2), ratio=round((r2 + fl) / (r1 + fl), 3), overlap_px=curve_c[best][2] * s,
                   ink_px=curve_c[best][1] * s * s)
        return out
    rad = int(cfg["refine_radius_coarse"]) * s
    dy_max = int(cfg["dy_max_px"])
    refined: List[Tuple[float, int, int, int, int, int]] = []
    for c in cands:
        best_local: Optional[Tuple[float, int, int, int, int]] = None
        for dx in range(c * s - rad, c * s + rad + 1):
            if abs(dx) > w - 1:
                continue
            r, n, nc = _residual(fa, fb, va, vb, dx, lvl, tolerant=True)
            if nc < min_overlap or n < min_ink:
                continue
            if best_local is None or r < best_local[0]:
                best_local = (r, dx, 0, n, nc)
        if best_local is None:
            continue
        # small vertical offset (video scaling / sub-pixel staff position)
        for dx in (best_local[1] - 1, best_local[1], best_local[1] + 1):
            for dy in range(-dy_max, dy_max + 1):
                if dy == 0 or abs(dx) > w - 1:
                    continue
                r, n, nc = _residual(fa, fb, va, vb, dx, lvl, dy=dy, tolerant=True)
                if nc >= min_overlap and n >= min_ink and r < best_local[0]:
                    best_local = (r, dx, dy, n, nc)
        st: List[int] = []
        _residual(fa, fb, va, vb, best_local[1], lvl, dy=best_local[2], tolerant=True, strong=st)
        refined.append(best_local + (st[0],))
    if not refined:
        out.update(dx=None, residual=None, second_dx=None, second_residual=None, ratio=None, overlap_px=0, ink_px=0,
                   reason="no_candidate")
        return out
    refined.sort()
    r1, dx1, dy1, n1, nc1, m1 = refined[0]
    # the tolerant residual is flat within a pixel: the exact offset is the plain
    # (non-tolerant) minimum next to it
    exact = min((_residual(fa, fb, va, vb, dx1 + ex, lvl, dy=dy1 + ey)[0], abs(ex) + abs(ey), dx1 + ex, dy1 + ey)
                for ex in (-1, 0, 1) for ey in (-1, 0, 1) if abs(dy1 + ey) <= dy_max)
    dx1, dy1 = exact[2], exact[3]
    sep = max(2.0, cfg["distinct_gaps"] * gap)
    others = [t for t in refined[1:] if abs(t[1] - dx1) >= sep]
    if others:
        r2, dx2 = others[0][0], others[0][1]
    else:
        finite = [v[0] for v in curve_c.values() if np.isfinite(v[0])]
        r2, dx2 = (max(finite) if finite else float("inf")), None
    fl = float(cfg["resid_floor"])
    out.update(dx=int(dx1), dy=int(dy1), residual=round(float(r1), 2), second_dx=None if dx2 is None else int(dx2),
               second_residual=round(float(r2), 2), ratio=round((float(r2) + fl) / (float(r1) + fl), 3),
               overlap_px=int(nc1), ink_px=int(n1),
               mismatch_px=int(m1), candidates=[[int(t[1]), round(float(t[0]), 2), int(t[5]), int(t[4])] for t in refined])
    return out


def _prior_dx(ep_a: Dict[str, Any], ep_b: Dict[str, Any], width: int) -> Optional[float]:
    """Cursor-motion prior: the cursor's last position in A and first in B mark the
    same musical moment (sanity flag only)."""
    ta = (ep_a.get("motion") or {}).get("playhead_track") or []
    tb = (ep_b.get("motion") or {}).get("playhead_track") or []
    if not ta or not tb:
        return None
    return float((ta[-1][1] - tb[0][1]) * width)


def verify_seam(reg: Dict[str, Any], gap: float, cfg: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if reg.get("dx") is None:
        return False, [reg.get("reason") or "no_candidate"]
    if reg["residual"] > cfg["resid_max"]:
        reasons.append("residual_high")
    if reg["ratio"] < cfg["ratio_min"]:
        reasons.append("ambiguous_offset")
    if reg["overlap_px"] < cfg["overlap_min_gaps"] * gap:
        reasons.append("overlap_narrow")
    if reg["ink_px"] < cfg["min_ink_gaps2"] * gap * gap:
        reasons.append("overlap_blank")
    return not reasons, reasons


def seam_kind(verified: bool, dx: Optional[int], gap: float, content_w: int, cfg: Dict[str, Any]) -> str:
    if not verified or dx is None:
        return "unverified"
    if abs(dx) < cfg["no_shift_gaps"] * gap:
        return "no_shift"
    if dx < 0:
        return "backward"
    if dx < cfg["jump_min_dx_frac"] * content_w:
        return "small_shift"
    return "jump"


def register_seams(tracking: Dict[str, Any], manifest: Dict[str, Any], load: ImageLoader, *,
                   cfg: Optional[Dict[str, Any]] = None, logger: Callable[[str], None] = lambda _m: None,
                   keep_composites: bool = False, checkpoint: Callable[[], None] = lambda: None,
                   ledger: bool = False, evidence_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Seams between consecutive confirmed displays of each slot."""
    cfg = cfg or CONFIG
    obs_by = {o["id"]: o for o in manifest["observations"]}
    seqs = slot_sequences(tracking)
    slots_out = []
    seams: List[Dict[str, Any]] = []
    composites: Dict[str, np.ndarray] = {}
    covered: Dict[str, np.ndarray] = {}
    fixed_masks: Dict[str, np.ndarray] = {}
    ledger_displays: Dict[str, Dict[str, Any]] = {}
    for slot_id, eps in seqs.items():
        confirmed = [e for e in eps if e.get("confirmed")]
        if len(confirmed) < 2:
            continue
        displays = []
        for e in confirmed:
            checkpoint()
            d = display_record(e, manifest, load, obs_by, cfg, keep_composite=True, ledger=ledger, evidence_dir=evidence_dir)
            if ledger:
                ledger_displays[e["id"]] = d.pop("ledger")
            composites[e["id"]] = d.pop("composite")
            covered[e["id"]] = d["covered"]
            displays.append(d)
        panel = detect_panel(displays, cfg)
        fixed, fixed_info = screen_fixed_pixels(displays, cfg)
        if fixed is not None:
            fixed_masks[slot_id] = fixed
            for d in displays:
                d["features"] = np.where(fixed, 0, d["features"]).astype(np.uint8)
        slots_out.append({"slot_id": slot_id, "displays": len(displays), "panel": panel, "screen_fixed": fixed_info})
        ids = [e["id"] for e in eps]
        for (ea, da), (eb, db) in zip(zip(confirmed, displays), zip(confirmed[1:], displays[1:])):
            gap = float(min(da["gap"], db["gap"]))
            skipped = ids[ids.index(ea["id"]) + 1: ids.index(eb["id"])]
            seam: Dict[str, Any] = {
                "id": f"seam-{ea['id']}-{eb['id']}", "slot_id": slot_id, "a": ea["id"], "b": eb["id"],
                "t_a": [ea["t_start"], ea["t_end"]], "t_b": [eb["t_start"], eb["t_end"]],
                "transition_sec": round(float(eb["t_start"]) - float(ea["t_end"]), 3),
                "skipped_episodes": skipped, "gap_px": gap,
            }
            if abs(float(ea["staff_top_y"]) - float(eb["staff_top_y"])) > cfg["row_tol_gaps"] * gap:
                seam.update(dx=None, verified=False, reasons=["row_change"], kind="unverified")
                seams.append(seam)
                continue
            reg = register_pair(da, db, int(panel["right"]), cfg)
            ok, reasons = verify_seam(reg, gap, cfg)
            content_w = min(da["width"], db["width"]) - int(panel["right"])
            seam.update({k: reg.get(k) for k in ("dx", "dy", "residual", "second_dx", "second_residual", "ratio", "overlap_px", "ink_px", "mismatch_px", "scale", "candidates")})
            seam.update(verified=ok, reasons=reasons, kind=seam_kind(ok, reg.get("dx"), gap, content_w, cfg))
            prior = _prior_dx(ea, eb, min(da["width"], db["width"]))
            seam["prior_dx"] = None if prior is None else round(prior, 1)
            pfit = prior_fit_dx(ea, eb, min(da["width"], db["width"]), cfg)
            seam["prior_fit_dx"] = None if pfit is None else round(pfit, 1)
            seam["prior_agrees"] = None if (prior is None or reg.get("dx") is None) else bool(
                abs(prior - reg["dx"]) <= cfg["prior_tol_frac"] * min(da["width"], db["width"]))
            seam["unrecovered_overlay_columns"] = [da["unrecovered_columns"], db["unrecovered_columns"]]
            seams.append(seam)
        # milestone 2: resolve ambiguous seams of this slot from the slot's own verified jumps
        slot_seams = [s for s in seams if s["slot_id"] == slot_id]
        dis_by = {e["id"]: d for e, d in zip(confirmed, displays)}
        width = int(min(d["width"] for d in displays))
        ev = slot_evidence(slot_seams, width, cfg)
        slots_out[-1]["evidence"] = ev
        last_id = confirmed[-1]["id"]
        num_cache: Dict[str, List[Tuple[int, float]]] = {}
        for s in slot_seams:
            if s["verified"]:
                continue
            checkpoint()
            num = numbers_check(s, dis_by, composites, panel, cfg,
                                staff_of=lambda d: _episode_staff_y(next(e for e in confirmed if e["id"] == d), obs_by),
                                cache=num_cache)
            s["resolution"] = resolve_seam(s, dis_by[s["a"]], dis_by[s["b"]], int(panel["right"]), ev, cfg,
                                           last_display=(s["b"] == last_id), numbers=num)
        for s in slot_seams:
            s["status"] = "verified" if s["verified"] else ("resolved" if (s.get("resolution") or {}).get("status") == "resolved" else "unverified")
        logger(f"jump: slot {slot_id}: {len(displays)} displays, panel {panel['right']} px, "
               f"{sum(1 for s in slot_seams if s['verified'])} verified seams, "
               f"{sum(1 for s in slot_seams if s['status'] == 'resolved')} resolved")
    out = {"slots": slots_out, "seams": seams}
    if ledger:
        out["ledger_displays"] = ledger_displays
    if keep_composites:
        out["_composites"] = composites
        out["_covered"] = covered
        out["_fixed"] = fixed_masks
    return out


# --------------------------------------------------------------------------- seam resolution


def prior_fit_dx(ep_a: Dict[str, Any], ep_b: Dict[str, Any], width: int, cfg: Dict[str, Any]) -> Optional[float]:
    """Cursor-motion prior corrected for the cursor's own motion: the cursor track of A
    (its last ``prior_fit_sec``) and of B (its first) are fitted with lines and compared
    at the same moment, half-way between A's last and B's first sample. The plain prior
    (``_prior_dx``) under-reads the jump by the distance the cursor moves between samples."""
    ta = (ep_a.get("motion") or {}).get("playhead_track") or []
    tb = (ep_b.get("motion") or {}).get("playhead_track") or []
    if len(ta) < 2 or len(tb) < 2:
        return None
    a = np.array(ta, dtype=float)
    b = np.array(tb, dtype=float)
    sa = a[a[:, 0] >= a[-1, 0] - cfg["prior_fit_sec"]]
    sb = b[b[:, 0] <= b[0, 0] + cfg["prior_fit_sec"]]
    if len(sa) < 2 or len(sb) < 2 or np.ptp(sa[:, 0]) <= 0 or np.ptp(sb[:, 0]) <= 0:
        return None
    tm = (a[-1, 0] + b[0, 0]) / 2.0
    pa = np.polyfit(sa[:, 0], sa[:, 1], 1)
    pb = np.polyfit(sb[:, 0], sb[:, 1], 1)
    return float((np.polyval(pa, tm) - np.polyval(pb, tm)) * width)


def window_candidates(a: Dict[str, Any], b: Dict[str, Any], panel_right: int, lo: int, hi: int,
                      cfg: Dict[str, Any], *, min_ink_gaps2: Optional[float] = None) -> List[Dict[str, Any]]:
    """Every local minimum of the full-resolution (tolerant) residual over offsets lo..hi,
    refined in dy and to the exact offset like ``register_pair``. Only offsets with enough
    overlap and ink are kept (``min_ink_gaps2`` overrides the ink floor)."""
    gap = float(min(a["gap"], b["gap"]))
    y0, y1 = max(a["rows"][0], b["rows"][0]), min(a["rows"][1], b["rows"][1])
    w = min(a["width"], b["width"])
    fa = a["features"][y0:y1, :w]
    fb = b["features"][y0:y1, :w]
    va = ~a["covered"][:w].copy()
    vb = ~b["covered"][:w].copy()
    va[:panel_right] = False
    vb[:panel_right] = False
    lvl = float(cfg["ink_level"])
    min_overlap = cfg["overlap_min_gaps"] * gap
    min_ink = (cfg["min_ink_gaps2"] if min_ink_gaps2 is None else float(min_ink_gaps2)) * gap * gap
    curve: Dict[int, Tuple[float, int, int]] = {}
    for dx in range(int(lo), int(hi) + 1):
        if abs(dx) > w - 1:
            continue
        curve[dx] = _residual(fa, fb, va, vb, dx, lvl, tolerant=True)
    ok = lambda r: r[2] >= min_overlap and r[1] >= min_ink  # noqa: E731
    sep = max(2, int(round(cfg["distinct_gaps"] * gap)))
    mins = _local_minima(curve, 50, sep, ok)
    dy_max = int(cfg["dy_max_px"])
    out = []
    for dx0 in mins:
        best = (curve[dx0][0], dx0, 0, curve[dx0][1], curve[dx0][2])
        for dx in (dx0 - 1, dx0, dx0 + 1):
            for dy in range(-dy_max, dy_max + 1):
                if dy == 0 or abs(dx) > w - 1:
                    continue
                r, n, nc = _residual(fa, fb, va, vb, dx, lvl, dy=dy, tolerant=True)
                if nc >= min_overlap and n >= min_ink and r < best[0]:
                    best = (r, dx, dy, n, nc)
        exact = min((_residual(fa, fb, va, vb, best[1] + ex, lvl, dy=best[2] + ey)[0], abs(ex) + abs(ey), best[1] + ex, best[2] + ey)
                    for ex in (-1, 0, 1) for ey in (-1, 0, 1) if abs(best[2] + ey) <= dy_max)
        out.append({"dx": int(exact[2]), "dy": int(exact[3]), "residual": round(float(best[0]), 2), "ink_px": int(best[3]),
                    "overlap_px": int(best[4]), "source": "window_search"})
    return out


def _distinct(cands: Sequence[Dict[str, Any]], sep: float) -> List[Dict[str, Any]]:
    """One candidate per offset cluster (the lowest residual)."""
    out: List[Dict[str, Any]] = []
    for c in sorted(cands, key=lambda c: c["residual"]):
        if all(abs(c["dx"] - o["dx"]) >= sep for o in out):
            out.append(c)
    return out


def slot_evidence(seams: Sequence[Dict[str, Any]], width: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """What the slot's verified jumps say: the typical jump size (robust median and spread)
    and how well the corrected cursor prior predicts the verified offsets."""
    jumps = [s for s in seams if s.get("verified") and s.get("kind") == "jump"]
    tol = float(cfg["resolve_tol_frac"]) * width
    out: Dict[str, Any] = {"verified_jumps": len(jumps), "tol_px": round(tol, 1)}
    if len(jumps) >= int(cfg["resolve_min_verified"]):
        dxs = np.array([float(s["dx"]) for s in jumps])
        med = float(np.median(dxs))
        mad = float(np.median(np.abs(dxs - med)))
        out["typical"] = {"median_dx": round(med, 1), "mad_px": round(mad, 1),
                          "usable": bool(mad <= cfg["resolve_max_spread_frac"] * tol)}
    else:
        out["typical"] = {"usable": False, "reason": "too_few_verified_jumps"}
    errs = [float(s["prior_fit_dx"]) - float(s["dx"]) for s in jumps if s.get("prior_fit_dx") is not None]
    if len(errs) >= int(cfg["prior_min_seams"]):
        p90 = float(np.percentile(np.abs(errs), 90))
        out["prior"] = {"seams": len(errs), "p90_abs_error_px": round(p90, 1), "median_error_px": round(float(np.median(errs)), 1),
                        "usable": bool(p90 <= cfg["prior_reliable_frac"] * width), "tol_px": round(cfg["prior_tol_frac"] * width, 1)}
    else:
        out["prior"] = {"usable": False, "reason": "too_few_priors", "seams": len(errs)}
    return out


def feature_barlines(d: Dict[str, Any], panel_right: int, cfg: Dict[str, Any]) -> List[float]:
    """Barline x centres of a display from its registration features (staff-line rows are zero
    there): a column inked over the staff height between the lines (>= 90 %), with little ink just
    above and below the staff (a stem goes on). Columns under an overlay or the panel are not
    read. Strokes closer than ``bar_min_gaps`` are one barline. Empty without five staff rows."""
    ys = [float(y) for y in d.get("staff_y") or []]
    f = d.get("features")
    if len(ys) != 5 or f is None:
        return []
    gap = float(d["gap"])
    h, w = f.shape
    lvl = float(cfg["ink_level"])
    top, bot = int(round(ys[0])), int(round(ys[4]))
    if bot - top < 2 or top < 0 or bot >= h:
        return []
    half = max(1, int(round(0.12 * gap)))
    rows = np.ones(bot - top + 1, bool)
    for y in ys:
        yc = int(round(y)) - top
        rows[max(0, yc - half - 1): yc + half + 2] = False
    if rows.sum() < 3:
        return []
    ink = f > lvl
    cover = ink[top: bot + 1][rows].mean(axis=0)
    a0, a1 = max(0, int(top - 1.5 * gap)), max(0, int(top - 0.35 * gap))
    b0, b1 = min(h, int(bot + 0.35 * gap)), min(h, int(bot + 1.5 * gap))
    above = ink[a0:a1].mean(axis=0) if a1 > a0 else np.zeros(w)
    below = ink[b0:b1].mean(axis=0) if b1 > b0 else np.zeros(w)
    cand = (cover >= 0.9) & (above < 0.5) & (below < 0.5)
    cand[: max(0, int(panel_right))] = False
    cov = d.get("covered")
    if cov is not None and len(cov) >= w:
        cand &= ~np.asarray(cov[:w], bool)
    groups: List[List[int]] = []
    for x in np.flatnonzero(cand):
        if groups and x - groups[-1][-1] <= cfg["bar_min_gaps"] * gap:
            groups[-1].append(int(x))
        else:
            groups.append([int(x)])
    return [(g[0] + g[-1]) / 2.0 for g in groups]


def local_bar_widths(da: Dict[str, Any], db: Dict[str, Any], dx: int, panel_right: int, cfg: Dict[str, Any]) -> List[float]:
    """Widths of single bars and of two consecutive bars around a seam at offset ``dx``: the
    barlines of A and of B (shifted into A's columns), merged within ``bar_min_gaps``."""
    gap = float(min(da["gap"], db["gap"]))
    xs = sorted(feature_barlines(da, panel_right, cfg) + [x + dx for x in feature_barlines(db, panel_right, cfg)])
    merged: List[float] = []
    for x in xs:
        if merged and x - merged[-1] < cfg["bar_min_gaps"] * gap:
            continue
        merged.append(x)
    one = [b - a for a, b in zip(merged, merged[1:])]
    two = [b - a for a, b in zip(merged, merged[2:])]
    return sorted({round(v, 1) for v in one + two})


def low_ink_rivals(c: Dict[str, Any], da: Dict[str, Any], db: Dict[str, Any], panel_right: int,
                   cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Every other offset a sparse candidate ``c`` must beat (reflow_jump-5): each local minimum over
    the whole geometrically feasible forward range (overlap >= ``overlap_min_gaps``), and the best
    offset within +- ``low_ink_rival_win_gaps`` of ``c.dx`` +- one and two local bar widths. A rival
    needs ``low_ink_rival_gaps2`` of ink. Returns the rivals and the worst ratio
    (rival + floor) / (own + floor); it only ever rejects ``c``, never proposes an offset."""
    width = min(da["width"], db["width"])
    gap = float(min(da["gap"], db["gap"]))
    content_w = width - panel_right
    rival_ink = float(cfg["low_ink_rival_gaps2"])
    fwd_lo = int(np.ceil(cfg["jump_min_dx_frac"] * content_w))
    sep = max(2.0, cfg["distinct_gaps"] * gap)
    rivals = [dict(o, via="range") for o in window_candidates(da, db, panel_right, fwd_lo, width - 1, cfg, min_ink_gaps2=rival_ink)]
    widths = local_bar_widths(da, db, int(c["dx"]), panel_right, cfg)
    if "features" in da and "features" in db:
        y0, y1 = max(da["rows"][0], db["rows"][0]), min(da["rows"][1], db["rows"][1])
        fa, fb = da["features"][y0:y1, :width], db["features"][y0:y1, :width]
        va, vb = ~da["covered"][:width].copy(), ~db["covered"][:width].copy()
        va[:panel_right] = False
        vb[:panel_right] = False
        lvl = float(cfg["ink_level"])
        min_overlap = cfg["overlap_min_gaps"] * gap
        min_ink = rival_ink * gap * gap
        win = max(2, int(round(cfg["low_ink_rival_win_gaps"] * gap)))
        dy_max = int(cfg["dy_max_px"])
        for bw in widths:
            for sign in (-1, 1):
                t = int(round(c["dx"] + sign * bw))
                best = None
                for dx in range(max(fwd_lo, t - win), min(width - 1, t + win) + 1):
                    for dy in range(-dy_max, dy_max + 1):
                        r, n, nc = _residual(fa, fb, va, vb, dx, lvl, dy=dy, tolerant=True)
                        if nc >= min_overlap and n >= min_ink and (best is None or r < best["residual"]):
                            best = {"dx": dx, "dy": dy, "residual": round(float(r), 2), "ink_px": int(n), "overlap_px": int(nc)}
                if best is not None:
                    rivals.append(dict(best, via=f"bar{sign * bw:+.0f}"))
    rivals = [o for o in rivals if abs(o["dx"] - c["dx"]) >= sep]
    fl = float(cfg["resid_floor"])
    worst = min(((o["residual"] + fl) / (c["residual"] + fl) for o in rivals), default=float("inf"))
    best = min(rivals, key=lambda o: o["residual"]) if rivals else None
    return {"bar_widths": widths, "examined": len(rivals),
            "best": None if best is None else [best["dx"], best["residual"], best["ink_px"], best["via"]],
            "ratio": round(worst, 2) if np.isfinite(worst) else None, "_ratio": worst}


def resolve_seam(seam: Dict[str, Any], da: Dict[str, Any], db: Dict[str, Any], panel_right: int, ev: Dict[str, Any],
                 cfg: Dict[str, Any], *, last_display: bool, numbers: Optional[Callable[[int], Optional[bool]]] = None) -> Dict[str, Any]:
    """Resolve one ambiguous seam (fail-closed). Plausible offsets: every candidate of the
    residual search, plus every local minimum in the typical-jump window, whose residual is
    within ``resid_max`` with enough overlap and ink. Constraints, each applied only when it
    can speak: (1) a forward jump, (2) the slot's typical jump size, (3) the corrected
    cursor prior where it is reliable on this slot, (4) the measure-number difference
    where both displays' numbers read (``numbers(dx)`` -> True/False/None). Resolved only
    when exactly one plausible offset passes every applicable constraint; a constraint
    that rejects every offset the others accept is a contradiction (unresolved).

    reflow_jump-4: the seam may also have failed on ``residual_high`` / ``overlap_blank``
    (``resolve_failures``; never ``overlap_narrow``, ``no_candidate`` or a row change), and the
    typical-jump window also offers sparse offsets (ink >= ``low_ink_gaps2`` staff spaces²,
    residual <= ``resid_max``, and (other + floor) / (own + floor) >= ``low_ink_ratio_min``
    against every other local minimum of the window; source ``low_ink_window``). Such a seam, or a chosen
    low-ink offset, needs at least two constraints besides "forward" (the typical jump and the
    cursor prior or the measure numbers).

    reflow_jump-5: a chosen low-ink offset without agreeing measure numbers is also checked against
    every forward offset outside the window (``low_ink_rivals``); a rival less than
    ``low_ink_ratio_min`` times worse leaves the seam unverified (reason ``low_ink_rival``)."""
    width = min(da["width"], db["width"])
    gap = float(min(da["gap"], db["gap"]))
    content_w = width - panel_right
    out: Dict[str, Any] = {"status": "unverified", "evidence": [], "constraints": {}}
    reasons = list(seam.get("reasons") or [])
    allowed = set(cfg.get("resolve_failures") or ["ambiguous_offset"])
    if not reasons or not set(reasons) <= allowed:
        return dict(out, reason="failure_not_resolvable")
    strict = reasons != ["ambiguous_offset"]
    if last_display:
        # the slot's last display may be clamped at the score end (a shorter jump)
        return dict(out, reason="final_display")
    typ = ev.get("typical") or {}
    plaus = [{"dx": int(c[0]), "dy": None, "residual": float(c[1]), "source": "registration"} for c in seam.get("candidates") or []]
    if typ.get("usable"):
        tol = float(ev["tol_px"])
        lo, hi = int(np.floor(typ["median_dx"] - tol)), int(np.ceil(typ["median_dx"] + tol))
        plaus += window_candidates(da, db, panel_right, lo, hi, cfg)
        low_floor = cfg.get("low_ink_gaps2")
        if low_floor is not None and float(low_floor) < float(cfg["min_ink_gaps2"]):
            # sparse offsets the normal ink floor leaves out; only a clear, unique window minimum counts
            full_ink = cfg["min_ink_gaps2"] * gap * gap
            low = window_candidates(da, db, panel_right, lo, hi, cfg, min_ink_gaps2=float(low_floor))
            sep_w = max(2.0, cfg["distinct_gaps"] * gap)
            fl = float(cfg["resid_floor"])
            for c in low:
                if c["ink_px"] >= full_ink or c["residual"] > cfg["resid_max"]:
                    continue
                rivals = [o["residual"] for o in low if abs(o["dx"] - c["dx"]) >= sep_w]
                ratio = (min(rivals) + fl) / (c["residual"] + fl) if rivals else float("inf")
                if ratio >= float(cfg["low_ink_ratio_min"]):
                    plaus.append(dict(c, source="low_ink_window", window_ratio=round(ratio, 2) if np.isfinite(ratio) else None))
    plaus = [c for c in plaus if c["residual"] <= cfg["resid_max"]]
    sep = max(2.0, cfg["distinct_gaps"] * gap)
    plaus = _distinct(plaus, sep)
    out["plausible"] = [[c["dx"], c["residual"]] for c in plaus]
    out["low_ink"] = [[c["dx"], c["residual"], c["ink_px"], c.get("window_ratio")] for c in plaus if c.get("source") == "low_ink_window"]
    if not plaus:
        return dict(out, reason="no_plausible_offset")
    keep = list(plaus)
    # (1) forward jump
    fwd = [c for c in keep if c["dx"] >= cfg["jump_min_dx_frac"] * content_w]
    out["constraints"]["forward"] = [c["dx"] for c in fwd]
    keep = fwd
    used = ["forward"]
    # (2) typical jump size
    if typ.get("usable"):
        tol = float(ev["tol_px"])
        t2 = [c for c in keep if abs(c["dx"] - typ["median_dx"]) <= tol]
        out["constraints"]["typical_jump"] = [c["dx"] for c in t2]
        if keep and not t2:
            return dict(out, reason="typical_jump_rejects_all")
        keep = t2
        used.append("typical_jump")
    else:
        out["constraints"]["typical_jump"] = "not_applicable"
    # (3) cursor prior
    pr = ev.get("prior") or {}
    if pr.get("usable") and seam.get("prior_fit_dx") is not None:
        t3 = [c for c in keep if abs(c["dx"] - float(seam["prior_fit_dx"])) <= pr["tol_px"]]
        out["constraints"]["cursor_prior"] = [c["dx"] for c in t3]
        if keep and not t3:
            return dict(out, reason="cursor_prior_contradicts")
        keep = t3
        used.append("cursor_prior")
    else:
        out["constraints"]["cursor_prior"] = "not_applicable" if not pr.get("usable") else "no_cursor"
    # (4) measure numbers
    if numbers is not None and keep:
        verdicts = {c["dx"]: numbers(c["dx"]) for c in keep}
        if any(v is not None for v in verdicts.values()):
            out["constraints"]["measure_numbers"] = {str(k): v for k, v in verdicts.items()}
            t4 = [c for c in keep if verdicts[c["dx"]] is not False]
            if not t4:
                return dict(out, reason="measure_numbers_contradict")
            if any(verdicts[c["dx"]] is True for c in t4):
                used.append("measure_numbers")
            keep = t4
        else:
            out["constraints"]["measure_numbers"] = "unreadable"
    else:
        out["constraints"]["measure_numbers"] = "not_applicable"
    if len(keep) != 1:
        return dict(out, reason="no_unique_offset" if keep else "no_offset_left", left=[c["dx"] for c in keep])
    if len(used) < 2:
        # the forward rule alone never resolves a seam
        return dict(out, reason="no_independent_constraint")
    c = keep[0]
    if (strict or c.get("source") == "low_ink_window") and len(used) < 3:
        # a seam that failed on more than ambiguity, or a sparse offset: two independent constraints
        return dict(out, reason="needs_two_constraints", left=[c["dx"]])
    if c.get("source") == "low_ink_window" and "measure_numbers" not in used:
        # reflow_jump-5: a sparse offset (rest bars) must also beat every offset outside the window,
        # above all one or two bars away; the typical jump and the cursor prior cannot tell a one-bar
        # shift apart. Agreeing measure numbers identify the bars and may still resolve it.
        riv = low_ink_rivals(c, da, db, panel_right, cfg)
        ratio = riv.pop("_ratio")
        out["low_ink_rivals"] = riv
        if ratio < float(cfg["low_ink_ratio_min"]):
            return dict(out, reason="low_ink_rival", left=[c["dx"]])
    if c.get("dy") is None:  # a registration candidate: refine dy/exact offset in a small window
        ref = window_candidates(da, db, panel_right, c["dx"] - 2, c["dx"] + 2, cfg)
        if ref:
            c = dict(min(ref, key=lambda r: r["residual"]), source=c["source"])
        else:
            c = dict(c, dy=0)
    evidence = used + (["low_ink_window"] if c.get("source") == "low_ink_window" else [])
    return dict(out, status="resolved", dx=int(c["dx"]), dy=int(c["dy"]), residual=c["residual"], evidence=evidence,
                chosen_from=c.get("source"), failures=reasons)


def _tesseract_number(crop: np.ndarray, min_votes: int) -> Optional[int]:
    """A measure number printed over a barline, read by tesseract (digits only) at a few
    scales and thresholds; None unless ``min_votes`` reads agree and no other value ties."""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("tesseract")
    if exe is None or crop.size == 0:
        return None
    gray = _gray(crop)
    votes: Dict[int, int] = {}
    with tempfile.TemporaryDirectory() as td:
        for thr in (200, 170):
            bw = np.where(gray < thr, 0, 255).astype(np.uint8)
            for sc in (3, 4, 5):
                big = cv2.copyMakeBorder(cv2.resize(bw, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC), 20, 20, 20, 20,
                                         cv2.BORDER_CONSTANT, value=255)
                path = Path(td) / "n.png"
                cv2.imwrite(str(path), big)
                try:
                    r = subprocess.run([exe, str(path), "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789"],
                                       capture_output=True, text=True, timeout=10)
                except Exception:  # noqa: BLE001
                    return None
                t = r.stdout.strip()
                if t.isdigit() and 0 < int(t) < 1000:
                    votes[int(t)] = votes.get(int(t), 0) + 1
    if not votes:
        return None
    top = sorted(votes.items(), key=lambda kv: -kv[1])
    if top[0][1] >= min_votes and (len(top) == 1 or top[1][1] < top[0][1]):
        return top[0][0]
    return None


def display_numbers(comp: np.ndarray, staff_y: Sequence[float], gap: float, panel_right: int, cfg: Dict[str, Any]) -> List[Tuple[int, float]]:
    """(number, barline x) for measure numbers printed over the display's barlines (a number
    row above the staff); empty when none read. Within a display the numbers must go up by
    one per barline, else nothing is returned."""
    if len(staff_y) != 5:
        return []
    norm, _inv = sd.normalize_polarity(comp)
    ink = sd.ink_mask(norm)
    st = _staff_of(staff_y, gap, comp.shape[1], ink)
    st["x"] = (int(panel_right), comp.shape[1] - 1)
    bars = sd.find_barlines(ink, st)
    top = float(staff_y[0])
    out = []
    for k, b in enumerate(bars):
        x = (b["x0"] + b["x1"]) / 2.0
        crop = norm[max(0, int(top - 1.7 * gap)): int(top - 0.15 * gap), max(0, int(x - 1.3 * gap)): int(x + 1.3 * gap)]
        v = _tesseract_number(crop, int(cfg["numbers_min_votes"]))
        if v is not None:
            out.append((v, float(x), k))
    if len(out) >= 2:
        base = [v - k for v, _x, k in out]
        if len(set(base)) != 1:
            return []
    return [(v, x) for v, x, _k in out]


def numbers_check(seam: Dict[str, Any], dis_by: Dict[str, Dict[str, Any]], composites: Dict[str, np.ndarray],
                  panel: Dict[str, Any], cfg: Dict[str, Any], staff_of: Optional[Callable[[str], Sequence[float]]] = None,
                  cache: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> Optional[Callable[[int], Optional[bool]]]:
    """Measure-number constraint for a seam: a candidate offset must put every number read over
    a barline of display B on the same number read in display A (within half a staff space).
    Returns ``check(dx) -> True / False / None (no number pair to compare)``, or None when
    numbers cannot be read here (no tesseract, no staff rows)."""
    import shutil
    if shutil.which("tesseract") is None or staff_of is None:
        return None
    a, b = seam["a"], seam["b"]
    gap = float(min(dis_by[a]["gap"], dis_by[b]["gap"]))
    cache = {} if cache is None else cache
    nums = {}
    for d in (a, b):
        if d not in cache:
            cache[d] = display_numbers(composites[d], staff_of(d), gap, int(panel["right"]), cfg)
        nums[d] = cache[d]
    if not nums[a] or not nums[b]:
        return None

    def check(dx: int) -> Optional[bool]:
        pairs = [(va, vb) for vb, xb in nums[b] for va, xa in nums[a] if abs(xb + dx - xa) <= 0.5 * gap]
        if not pairs:
            return None
        return all(va == vb for va, vb in pairs)

    return check


def seam_offset(s: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """(dx, dy) of a verified jump, a verified no-shift seam (one view split by the tracker) or a
    resolved seam; None otherwise."""
    if s.get("user_rejected"):
        return None
    if s.get("verified") and s.get("kind") in ("jump", "no_shift"):
        return int(s["dx"]), int(s.get("dy") or 0)
    res = s.get("resolution") or {}
    if res.get("status") == "resolved":
        return int(res["dx"]), int(res.get("dy") or 0)
    return None


def effective_seam_status(s: Dict[str, Any]) -> str:
    """User decisions never mutate the recorded registration or resolution evidence."""
    if s.get("user_rejected"):
        return "unverified"
    return "verified" if s.get("verified") else "resolved" if (s.get("resolution") or {}).get("status") == "resolved" else "unverified"


def apply_seam_rejections(jump: Dict[str, Any], rejected: Sequence[str]) -> Dict[str, Any]:
    """Recompute chains from immutable run membership, without classifying runs again."""
    import copy
    out = copy.deepcopy(jump)
    rejected = set(rejected)
    for s in out.get("seams", []):
        s["user_rejected"] = s["id"] in rejected
    for run in out.get("runs", []):
        run["panorama_chains"] = panorama_chains(run, out["seams"])
        run["still_unverified_seam_ids"] = [c["break_after"] for c in run["panorama_chains"] if c["break_after"]]
        members = {d for c in run["panorama_chains"] for d in c["displays"]}
        run["resolved_seam_ids"] = [s["id"] for s in out["seams"] if s["a"] in members and s["b"] in members
                                    and effective_seam_status(s) == "resolved"]
    statuses = [effective_seam_status(s) for s in out.get("seams", [])]
    out["effective_summary"] = {k: statuses.count(k) for k in ("verified", "resolved", "unverified")}
    out["rejected_seam_ids"] = sorted(rejected)
    return out


# --------------------------------------------------------------------------- gate and runs


def gate(tracking: Dict[str, Any], manifest: Dict[str, Any], load: ImageLoader, *,
         cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Attempt jump registration only when the tracker saw horizontal motion, or when
    enough consecutive displays overlap horizontally (cheap coarse check on one frame
    per display). A pair that does not overlap over the whole width is checked again
    without the screen-fixed left panel (detect_panel, as register_seams uses it): a
    translucent panel over the start of every display can spoil a narrow overlap. Other
    videos are not touched."""
    cfg = cfg or CONFIG
    if any(iv.get("kind") == "horizontal_scroll" for iv in tracking.get("layout_intervals", [])):
        return {"attempt": True, "reason": "tracking_horizontal_motion"}
    obs_by = {o["id"]: o for o in manifest["observations"]}
    pairs = []
    for slot_id, eps in slot_sequences(tracking).items():
        conf = [e for e in eps if e.get("confirmed")]
        pairs.extend((slot_id, ea, eb) for ea, eb in zip(conf, conf[1:]))
    if not pairs:
        return {"attempt": False, "reason": "no_display_pairs", "pairs_checked": 0}
    pairs = _evenly(pairs, int(cfg["gate_max_pairs"]))
    recs: Dict[str, Dict[str, Any]] = {}

    def rec(e: Dict[str, Any]) -> Dict[str, Any]:
        if e["id"] not in recs:
            mid = e["observation_ids"][len(e["observation_ids"]) // 2]
            img = load(obs_by[mid])
            gap = float(e["staff_gap_px"])
            y0, y1 = _episode_rows(e, obs_by)
            y0, y1 = max(0, y0), min(img.shape[0], y1 if y1 > y0 else img.shape[0])
            norm, _inv = sd.normalize_polarity(img)
            gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm
            recs[e["id"]] = {"gap": gap, "rows": (y0, y1), "width": int(img.shape[1]),
                             "contrast": np.percentile(255 - gray[y0:y1].astype(np.int16), 98, axis=0).astype(np.float32),
                             "features": features(img, gap, _episode_staff_y(e, obs_by)), "covered": np.zeros(img.shape[1], dtype=bool)}
        return recs[e["id"]]

    panels: Dict[str, int] = {}
    for slot_id in dict.fromkeys(s for s, _a, _b in pairs):
        displays = list({e["id"]: rec(e) for s, ea, eb in pairs if s == slot_id for e in (ea, eb)}.values())
        panels[slot_id] = int(detect_panel(displays, cfg)["right"])
    hits = 0
    for slot_id, ea, eb in pairs:
        recs_ab = [rec(ea), rec(eb)]
        if recs_ab[0]["features"].shape != recs_ab[1]["features"].shape:
            continue
        gap = min(recs_ab[0]["gap"], recs_ab[1]["gap"])
        # the whole width first; when that fails, again without the left panel
        for panel_right in dict.fromkeys((0, panels[slot_id])):
            reg = register_pair(recs_ab[0], recs_ab[1], panel_right, cfg, coarse_only=True, coarse_gap_px=cfg["gate_coarse_gap_px"])
            if (reg.get("dx") is not None and abs(reg["dx"]) >= cfg["no_shift_gaps"] * gap
                    and reg["residual"] <= cfg["resid_max"] and reg["ratio"] >= cfg["ratio_min"]):
                hits += 1
                break
    frac = hits / float(len(pairs))
    return {"attempt": frac >= cfg["gate_pair_fraction"], "reason": "overlapping_displays" if frac >= cfg["gate_pair_fraction"] else "no_horizontal_motion",
            "pairs_checked": len(pairs), "pairs_overlapping": hits, "fraction": round(frac, 3), "panel_right": panels}


def _views(ss: Sequence[Dict[str, Any]], cfg: Dict[str, Any]) -> Tuple[List[List[str]], List[Dict[str, Any]]]:
    """Displays of one slot grouped into views: consecutive confirmed episodes joined by a
    verified no-shift seam (the tracker split one view, e.g. when the highlight changed) are
    one view. Returns (views as episode-id lists, the seam between view k and k+1)."""
    if not ss:
        return [], []
    views: List[List[str]] = []
    links: List[Dict[str, Any]] = []
    cur = [ss[0]["a"]]
    for s in ss:
        if (s.get("kind") == "no_shift" and s.get("verified") and float(s.get("transition_sec") or 0.0) <= cfg["transition_max_sec"]
                and cur[-1] == s["a"]):
            cur.append(s["b"])
            continue
        views.append(cur)
        links.append(s)
        cur = [s["b"]]
    views.append(cur)
    return views, links


def classify_runs(seams: Sequence[Dict[str, Any]], tracking: Dict[str, Any], *, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """jump_view runs and a label for every tracker interval.

    Displays joined by a verified no-shift seam form one view (its dwell is the whole view).
    A primary run holds >= ``run_min_seams`` consecutive verified jumps between static views;
    it is joined across jump-like seams that are not verified (fail-closed: the panorama is
    split there and the seam is listed) except a row change, and extended at both ends over
    resolved seams. A secondary run (``secondary``) in a slot that already has a primary run:
    >= ``run_min_seams`` jump-like seams that are all verified jumps or resolved, on the staff
    rows of the slot's primary run."""
    cfg = cfg or CONFIG
    eps = {e["id"]: e for e in tracking.get("episodes", [])}

    def view_dwell(v: Sequence[str]) -> float:
        return float(eps[v[-1]]["t_end"]) - float(eps[v[0]]["t_start"])

    runs: List[Dict[str, Any]] = []
    by_slot: Dict[str, List[Dict[str, Any]]] = {}
    for s in seams:
        by_slot.setdefault(s["slot_id"], []).append(s)
    for slot_id, ss in by_slot.items():
        views, links = _views(ss, cfg)
        n = len(links)
        jl = [view_dwell(views[i]) >= cfg["dwell_min_sec"] and view_dwell(views[i + 1]) >= cfg["dwell_min_sec"]
              and float(links[i]["transition_sec"]) <= cfg["transition_max_sec"] for i in range(n)]
        vjump = [jl[i] and links[i]["kind"] == "jump" and bool(links[i].get("verified")) for i in range(n)]
        known = [jl[i] and seam_offset(links[i]) is not None for i in range(n)]
        breakable = [jl[i] and links[i]["kind"] in ("unverified", "backward") and "row_change" not in (links[i].get("reasons") or [])
                     for i in range(n)]
        # chains: maximal runs of verified jump links (link index ranges, inclusive)
        chains: List[Tuple[int, int]] = []
        i = 0
        while i < n:
            if vjump[i]:
                j = i
                while j + 1 < n and vjump[j + 1]:
                    j += 1
                chains.append((i, j))
                i = j + 1
            else:
                i += 1
        groups: List[Dict[str, Any]] = []
        for c0, c1 in chains:
            if groups:
                g = groups[-1]
                between = range(g["i1"] + 1, c0)
                if len(between) and all(breakable[k] for k in between):
                    g["i1"] = c1
                    g["chains"].append((c0, c1))
                    continue
            groups.append({"i0": c0, "i1": c1, "chains": [(c0, c1)]})
        for g in groups:  # extend over resolved seams at both ends
            while g["i0"] > 0 and known[g["i0"] - 1]:
                g["i0"] -= 1
            while g["i1"] + 1 < n and known[g["i1"] + 1]:
                g["i1"] += 1
        primary = [g for g in groups if max(c1 - c0 + 1 for c0, c1 in g["chains"]) >= cfg["run_min_seams"]]
        ref_top = None
        if primary:
            e0 = eps[views[primary[0]["i0"]][0]]
            ref_top = (float(e0["staff_top_y"]), float(e0["staff_gap_px"]))
        for g in groups:
            g_links = range(g["i0"], g["i1"] + 1)
            if g in primary:
                g["secondary"] = False
            elif (ref_top is not None and len(g_links) >= cfg["run_min_seams"] and all(known[k] for k in g_links)
                  and abs(float(eps[views[g["i0"]][0]]["staff_top_y"]) - ref_top[0]) <= cfg["row_tol_gaps"] * ref_top[1]):
                g["secondary"] = True
            else:
                continue
            g_views = views[g["i0"]: g["i1"] + 2]
            # panorama segments: views joined by known links, split at the fail-closed breaks
            segs: List[List[str]] = [list(g_views[0])]
            for k in g_links:
                if known[k]:
                    segs[-1].extend(views[k + 1])
                else:
                    segs.append(list(views[k + 1]))
            first_ep, last_ep = g_views[0][0], g_views[-1][-1]
            lo = next(x for x, s in enumerate(ss) if s["a"] == first_ep)
            hi = next(x for x, s in enumerate(ss) if s["b"] == last_ep)
            all_seams = ss[lo: hi + 1]
            jumps = [links[k] for k in g_links if vjump[k]]
            runs.append({
                "kind": "jump_view", "slot_id": slot_id, "secondary": bool(g["secondary"]),
                "start": float(eps[first_ep]["t_start"]), "end": float(eps[last_ep]["t_end"]),
                "seams": len(all_seams), "verified_seams": sum(1 for s in all_seams if s["verified"]),
                "unverified_seam_ids": [links[k]["id"] for k in g_links if not vjump[k]],
                "no_shift_seam_ids": [s["id"] for s in all_seams if s.get("kind") == "no_shift"],
                "chains": segs,
                "median_dx": int(np.median([s["dx"] for s in jumps])) if jumps else None,
            })
    runs.sort(key=lambda r: r["start"])
    intervals = _label_intervals(tracking, runs, cfg)
    return {"runs": runs, "intervals": intervals}


def _subtract(span: Tuple[float, float], cover: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out = [span]
    for c0, c1 in cover:
        nxt = []
        for a, b in out:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if c0 > a:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        out = nxt
    return [(a, b) for a, b in out if b - a > 1e-6]


def _label_intervals(tracking: Dict[str, Any], runs: Sequence[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every tracker layout interval, minus the jump-view runs, labelled smooth_scroll /
    horizontal_unclassified (tracker saw horizontal motion) or not_horizontal."""
    cover = [(r["start"], r["end"]) for r in runs]
    out: List[Dict[str, Any]] = [{"start": r["start"], "end": r["end"], "kind": "jump_view", "slot_id": r["slot_id"]} for r in runs]
    eps = [e for e in tracking.get("episodes", []) if e.get("confirmed")]
    for iv in tracking.get("layout_intervals", []):
        for a, b in _subtract((float(iv["start"]), float(iv["end"])), cover):
            if iv.get("kind") == "horizontal_scroll":
                # smooth scroll: no stable display dwells inside the interval
                still = 0.0
                for e in eps:
                    d = float(e["t_end"]) - float(e["t_start"])
                    if d >= cfg["dwell_min_sec"]:
                        still += max(0.0, min(b, float(e["t_end"])) - max(a, float(e["t_start"])))
                kind = "smooth_scroll" if still < 0.5 * (b - a) else "horizontal_unclassified"
                out.append({"start": a, "end": b, "kind": kind, "tracking_kind": iv["kind"], "static_fraction": round(still / max(b - a, 1e-6), 3)})
            else:
                out.append({"start": a, "end": b, "kind": "not_horizontal", "tracking_kind": iv.get("kind")})
    out.sort(key=lambda r: (r["start"], r["end"]))
    return out


# --------------------------------------------------------------------------- panorama strips


JUMP_SEAM_UNVERIFIED = "JUMP_SEAM_UNVERIFIED"
# no loader was given to build_jump_systems: the displays' minority content was not audited
JUMP_MINORITY_UNCHECKED = "JUMP_MINORITY_UNCHECKED"


# Episode boundaries that are not a hand-over from / to another display of the source.
SOURCE_START = (None, "first_observation")
SOURCE_END = (None, "end_of_source")
# a slot that vanished (``slot_empty``) and came back (``slot_appeared``) is a hand-over too
_PAIRED_BOUNDARY = {"slot_empty": "slot_appeared"}


def display_boundaries(ep: Dict[str, Any], eps: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Whether a display starts / ends with an established hand-over: the tracker closed it for
    a change (not the source start / end) and the neighbouring episode of the same slot exists
    and records the same boundary (system_tracking pairs ``ended_by`` of one episode with
    ``started_by`` of the next). Without one, the display's edge is a source boundary (or an
    unexplained one) and short edge runs of minority ink are content, not a transition.
    Returns {"first_display", "terminal_display", "previous", "next"}."""
    same = [e for e in eps.values() if e.get("slot_id") == ep.get("slot_id") and e["id"] != ep["id"]]
    t0, t1 = float(ep["t_start"]), float(ep["t_end"])
    prev = max((e for e in same if float(e["t_end"]) <= t0), key=lambda e: (float(e["t_end"]), e["id"]), default=None)
    nxt = min((e for e in same if float(e["t_start"]) >= t1), key=lambda e: (float(e["t_start"]), e["id"]), default=None)
    sb, eb = ep.get("started_by"), ep.get("ended_by")
    starts = sb not in SOURCE_START and prev is not None and _PAIRED_BOUNDARY.get(prev.get("ended_by"), prev.get("ended_by")) == sb
    ends = eb not in SOURCE_END and nxt is not None and _PAIRED_BOUNDARY.get(eb, eb) == nxt.get("started_by")
    return {"first_display": not starts, "terminal_display": not ends,
            "previous": prev["id"] if starts else None, "next": nxt["id"] if ends else None,
            "started_by": sb, "ended_by": eb}


def audit_display_minority(ep: Dict[str, Any], comp: np.ndarray, obs_by: Dict[str, Dict[str, Any]],
                           load: ImageLoader, eps: Optional[Dict[str, Dict[str, Any]]] = None, *,
                           manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Minority content of one jump display: neutral ink that some of the display's observations
    show (>= 2 consecutive) and its overlay-free composite does not draw. The page-strip check
    (``reflow_strips.check_minority_content``) over every observation of the display, on the whole
    crop (the composite is the display's own, crop coordinates). A short run at an edge is the
    hand-over (on record, not flagged) only where ``display_boundaries`` establishes a
    neighbouring display there; at the source start / end (or without ``eps``) it is content."""
    h, w = comp.shape[:2]
    bounds = display_boundaries(ep, eps) if eps is not None else \
        {"first_display": True, "terminal_display": True, "previous": None, "next": None}
    system = {"observations": [{"obs_id": o, "region_id": r} for o, r in zip(ep["observation_ids"], ep["region_ids"])],
              "first_display": bounds["first_display"], "terminal_display": bounds["terminal_display"]}
    kwargs: Dict[str, Any] = {"memo": {}}
    if "native_scale" in inspect.signature(rs.check_minority_content).parameters:
        scale = (manifest or {}).get("work_scale") or 1.0
        kwargs["native_scale"] = float(scale.get("scale", 1.0) if isinstance(scale, dict) else scale)
    out = rs.check_minority_content(system, comp, [0, 0, int(w), int(h)], obs_by, load, float(ep["staff_gap_px"]), **kwargs)
    out["boundaries"] = bounds
    return out


def audit_jump_minority(jump: Dict[str, Any], eps: Dict[str, Dict[str, Any]], obs_by: Dict[str, Dict[str, Any]],
                        composites: Dict[str, np.ndarray], load: ImageLoader, *,
                        manifest: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """``audit_display_minority`` for every display of every panorama chain, before any panorama is
    built. Specks at one screen position in >= 3 displays (``minority_content.screen_fixed_spots``:
    the score moves between jump displays, the screen does not) are recorded as suspicions;
    position alone never erases their alternate pixels. Returns ({display: audit}, spots)."""
    audits: Dict[str, Dict[str, Any]] = {}
    for run in jump.get("runs") or []:
        for chain in run.get("panorama_chains") or []:
            for d in chain["displays"]:
                if d not in audits:
                    audits[d] = audit_display_minority(eps[d], composites[d], obs_by, load, eps, manifest=manifest)
    items = [{"display": d, "box": e["box_crop"], "area_px": e["area_px"]} for d, a in audits.items() for e in a["events"]]
    if not items:
        return audits, []
    gap = float(np.median([float(eps[d]["staff_gap_px"]) for d in audits]))
    spots = mc.screen_fixed_spots(items, gap)
    if spots:
        for a in audits.values():
            a["screen_fixed_suspicions"] = [dict(e) for e in a["events"]
                                           if mc.in_screen_fixed_spot(e["box_crop"], e["area_px"], spots, gap)]
    return audits, [dict(sp, gap=round(gap, 2), disposition="alternate_kept") for sp in spots]



def _strip_minority(audits: Optional[Dict[str, Dict[str, Any]]], chain_disp: Sequence[str], offset_of: Dict[str, Tuple[int, int]],
                    x0: int, x1: int, first_k: bool, last_k: bool, prefix_w: int, top: int, sid: str, out_dir: Path,
                    eps: Dict[str, Dict[str, Any]], obs_by: Dict[str, Dict[str, Any]], composites: Dict[str, np.ndarray],
                    load: Optional[ImageLoader], *, manifest: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[str]]:
    """The minority content of a panorama chunk [x0, x1): every event of every display of the chain
    whose centre maps (display crop x + the display's panorama offset) into the chunk (the chain's
    first / last chunk also takes events left / right of it), whatever display owns those
    panorama columns. Each event is kept as an alternate strip of its display (the display's
    observations that show it; ``reflow_strips.build_alternates``) and listed with its strip box.
    Returns (``minority_content`` record, issues)."""
    if audits is None:
        return {"checked": False, "reason": "no_loader", "events": [], "alternates": []}, [JUMP_MINORITY_UNCHECKED]
    events: List[Dict[str, Any]] = []
    alternates: List[Dict[str, Any]] = []
    displays: List[Dict[str, Any]] = []
    explained = []
    ineligible = []
    for d in chain_disp:
        a = audits[d]
        ox, oy = offset_of[d]
        for event in a.get("explained_events",[]):
            cx = (event["box_crop"][0]+event["box_crop"][2])/2+ox
            if (x0 <= cx < x1) or (first_k and cx < x0) or (last_k and cx >= x1):
                explained.append(dict(event, display=d))
        ineligible.extend(dict(event, display=d) for event in a.get("ineligible_observations",[]))
        event_base = len(events)
        mine = []
        mine_support = []
        for ei, e in enumerate(a["events"]):
            cx = (e["box_crop"][0] + e["box_crop"][2]) / 2.0 + ox
            if (x0 <= cx < x1) or (first_k and cx < x0) or (last_k and cx >= x1):
                mine.append(dict(e))
                mine_support.append(a["_event_support"][ei])
        displays.append({"display": d, "members": a.get("members"), "checked_members": a.get("checked_members"),
                         "skipped_members": a.get("skipped_members"), "paper_opaque":a.get("paper_opaque"), "events": len(mine),
                         "edge_transitions": len(a.get("edge_transitions") or []), "screen_fixed": len(a.get("screen_fixed") or []),
                         "screen_fixed_suspicions": len(a.get("screen_fixed_suspicions") or []),
                         "boundaries": {k: (a.get("boundaries") or {}).get(k) for k in ("first_display", "terminal_display", "previous", "next")}})
        if not mine:
            continue
        ep = eps[d]
        gap = float(ep["staff_gap_px"])
        comp = composites[d]
        h, w = comp.shape[:2]
        sy = _episode_staff_y(ep, obs_by)
        pad = int(round(rs.PAD_V_GAPS * gap))
        keep = (max(0, int(sy[0] - pad)), min(h, int(np.ceil(sy[-1] + pad)) + 1)) if sy else (0, h)
        sub = {"events": mine, "_members": a["_members"], "_event_support": mine_support,
               "_eligible_masks": a.get("_eligible_masks", {}), "_member_masks": a.get("_member_masks", {})}
        alts = rs.build_alternates(sub, [0, 0, int(w), int(h)], obs_by, load, gap, keep, pad, memo={}) if load is not None else []
        for img, arec in alts:
            n = len(alternates) + 1
            suffix = f"alt{n}"
            (out_dir / "alt").mkdir(parents=True, exist_ok=True)
            apath = out_dir / "alt" / f"strip_{sid}-{suffix}.png"
            if not cv2.imwrite(str(apath), img):
                raise RuntimeError(f"failed to write strip {apath}")
            for j in arec["events"]:
                mine[j]["alternate"] = suffix
                mine[j].setdefault("alternates", []).append(suffix)
            if manifest is not None and load is not None and arec["obs_ids"]:
                oid = arec["obs_ids"][len(arec["obs_ids"]) // 2]
                clipped = rs.source_clipping(load(obs_by[oid]), arec["box_crop"], manifest)
                if clipped:
                    arec["source_clipped"] = clipped
            for patch in arec.get("evidence_patches",[]):
                patch["event_index"] += event_base
            alternates.append(dict(arec, events=[event_base+j for j in arec["events"]],
                                   suffix=suffix, parent_id=sid, display=d, path=str(apath)))
        for e in mine:
            if e.get("foreground_support") is not None:
                e["foreground_support"] = [{"obs_id":v["obs_id"],
                    "spans_crop":[[y+oy-top,a+ox-x0+prefix_w,b+ox-x0+prefix_w]
                                  for y,a,b in v.get("spans_crop",[])]}
                    for v in e["foreground_support"]]
                if e.get("ink_like_foreground_support") is not None:
                    e["ink_like_foreground_support"] = [{"obs_id":v["obs_id"],
                        "spans_crop":[[y+oy-top,a+ox-x0+prefix_w,b+ox-x0+prefix_w]
                                      for y,a,b in v["spans_crop"]]}
                        for v in e["ink_like_foreground_support"]]
                e["support_coordinate_space"] = "strip"
            bx0, by0, bx1, by1 = e["box_crop"]
            e.pop("box", None)
            events.append(dict(e, display=d, box_strip=[int(bx0 + ox - x0 + prefix_w), int(by0 + oy - top),
                                                        int(bx1 + ox - x0 + prefix_w), int(by1 + oy - top)],
                               alternate=e.get("alternate")))
    rec = {"checked": True, "displays": displays, "events": events, "alternates": alternates,
           "explained_events":explained,"ineligible_observations":ineligible}
    return rec, ([rs.MINORITY_ISSUE, rs.UNCERTAIN_MARK_KEPT] if events else [])


def panorama_chains(run: Dict[str, Any], seams: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The run's displays (every display between its first and last, in order) split into
    chains at every seam that is neither verified nor resolved. Each chain:
    {"displays": [...], "break_before": seam id or None, "break_after": seam id or None}."""
    by_a = {s["a"]: s for s in seams if s["slot_id"] == run["slot_id"]}
    first, last = run["chains"][0][0], run["chains"][-1][-1]
    out: List[Dict[str, Any]] = []
    cur = [first]
    brk = None
    d = first
    while d != last and d in by_a:
        s = by_a[d]
        if seam_offset(s) is not None:
            cur.append(s["b"])
        else:
            out.append({"displays": cur, "break_before": brk, "break_after": s["id"]})
            cur, brk = [s["b"]], s["id"]
        d = s["b"]
    out.append({"displays": cur, "break_before": brk, "break_after": None})
    return out


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def stitch_cut(ca: np.ndarray, cb: np.ndarray, pa: Tuple[int, int], pb: Tuple[int, int], cov_a: np.ndarray, cov_b: np.ndarray,
               panel_right: int, gap: float, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Panorama column where display A hands over to display B: inside the usable overlap
    (B's panel excluded), at least ``cut_margin_gaps`` from both usable edges when the overlap
    allows, at the column where the two displays differ least (pulled mildly toward the
    middle of the overlap). ``pa``/``pb``: panorama (x, y) of each display's column/row 0."""
    (xa, ya), (xb, yb) = pa, pb
    lo, hi = xb + int(panel_right), xa + ca.shape[1]
    if hi - lo < 1:
        return None
    m = int(round(cfg["cut_margin_gaps"] * gap))
    a0, a1 = (lo + m, hi - m) if hi - m > lo + m else (lo, hi)
    xs = np.arange(a0, a1)
    r0, r1 = max(ya, yb), min(ya + ca.shape[0], yb + cb.shape[0])
    ga = _gray(ca)[r0 - ya:r1 - ya][:, xs - xa].astype(np.int16)
    gb = _gray(cb)[r0 - yb:r1 - yb][:, xs - xb].astype(np.int16)
    diff = np.abs(ga - gb).mean(axis=0).astype(np.float64)
    if len(diff) >= 5:
        diff = np.convolve(diff, np.ones(5) / 5.0, mode="same")
    bad = cov_a[xs - xa] | cov_b[xs - xb]
    if bad.all():
        bad = np.zeros_like(bad)
    finite = diff[~bad]
    scale = max(1.0, float(np.median(finite))) if finite.size else 1.0
    centre, half = (lo + hi) / 2.0, max(1.0, (hi - lo) / 2.0)
    cost = diff + cfg["cut_center_weight"] * scale * np.abs(xs - centre) / half
    cost[bad] = np.inf
    k = int(np.argmin(cost))
    return {"x": int(xs[k]), "overlap": [int(lo), int(hi)], "diff_at_cut": round(float(diff[k]), 2),
            "diff_median": round(float(np.median(diff)), 2)}


def build_panorama(chain: Sequence[str], seam_of: Dict[Tuple[str, str], Dict[str, Any]], composites: Dict[str, np.ndarray],
                   covered: Dict[str, np.ndarray], panel_right: int, gap: float, cfg: Dict[str, Any], *,
                   left_trim: int = 0) -> Tuple[np.ndarray, Dict[str, Any]]:
    """One long strip for a chain of verified/resolved seams with a per-column owner map:
    every panorama column comes from exactly one display. A display's panel columns are used
    only where no other display shows them (the chain's first display)."""
    if not 0 <= left_trim < composites[chain[0]].shape[1]:
        raise ValueError("invalid panorama left trim")
    X, Y = [-int(left_trim)], [0]
    for a, b in zip(chain, chain[1:]):
        dx, dy = seam_offset(seam_of[(a, b)])
        X.append(X[-1] + dx)
        Y.append(Y[-1] + dy)
    ymin = min(Y)
    hmax = max(composites[d].shape[0] + Y[k] - ymin for k, d in enumerate(chain))
    width = X[-1] + composites[chain[-1]].shape[1]
    cuts: List[Dict[str, Any]] = []
    for k in range(len(chain) - 1):
        c = stitch_cut(composites[chain[k]], composites[chain[k + 1]], (X[k], Y[k] - ymin), (X[k + 1], Y[k + 1] - ymin),
                       covered[chain[k]], covered[chain[k + 1]], panel_right, gap, cfg)
        if c is None:
            raise ValueError(f"no usable overlap between {chain[k]} and {chain[k + 1]}")
        cuts.append(c)
    first = composites[chain[0]]
    paper = np.median(first.reshape(-1, first.shape[-1]) if first.ndim == 3 else first.reshape(-1), axis=0)
    pano = np.empty((hmax, width) + first.shape[2:], dtype=np.uint8)
    pano[...] = np.asarray(paper, dtype=np.uint8)
    starts = [0] + [c["x"] for c in cuts]
    ends = [c["x"] for c in cuts] + [width]
    owners = []
    lo = 0
    for k, d in enumerate(chain):
        comp = composites[d]
        x0 = max(starts[k], lo, X[k])
        x1 = min(ends[k], X[k] + comp.shape[1])
        y = Y[k] - ymin
        rec = {"display": d, "pano_cols": [int(x0), int(max(x0, x1))], "offset_x": int(X[k]), "offset_y": int(y),
               "display_to_panorama": [[1, 0, int(X[k])], [0, 1, int(y)], [0, 0, 1]],
               "owned_cols_display": [int(x0 - X[k]), int(max(x0, x1) - X[k])],
               "panel_columns_used": int(max(0, min(x1, X[k] + panel_right) - x0)) if x1 > x0 else 0,
               "unrecovered_overlay_columns": int(covered[d][max(0, x0 - X[k]):max(0, x1 - X[k])].sum()) if x1 > x0 else 0}
        if x1 > x0:
            pano[y:y + comp.shape[0], x0:x1] = comp[:, x0 - X[k]:x1 - X[k]]
            lo = x1
        owners.append(rec)
    covered_cols = sum(o["pano_cols"][1] - o["pano_cols"][0] for o in owners)
    info = {"width": int(width), "height": int(hmax), "offsets": [[int(x), int(y - ymin)] for x, y in zip(X, Y)],
            "cuts": cuts, "owners": owners, "owner_map_complete": bool(covered_cols == width), "ymin": int(ymin)}
    return pano, info


# Panorama preservation ledger (Codex J1). Kept apart from CONFIG (whose hash is frozen in
# JUMP_FREEZE.md): it never changes what a run, a seam or a strip image becomes, only whether
# the discarded overlap content of a display is shown to exist in the panorama.
PRESERVE_VERSION = "jump_preservation-6"  # 6: recurring faded panel label past the panel edge (pixel mask)
PRESERVE_CONFIG: Dict[str, Any] = {
    # a display component's pixels in columns another display owns are looked up in the
    # panorama ink dilated by this many px (registration and ink-level slack: +-1 px)
    "match_tol_px": 1,
    # ... and the component is matched when at least this fraction of them is found there
    "match_min_frac": 0.5,
    # components (or their part in foreign columns) of at most this many pixels are speckle
    # (JPEG noise, a stroke end crossing the cut): never a conflict
    "min_foreign_px": 6,
    # conflicts listed per chain (evidence)
    "evidence_components": 12,
    # panel label recurring past the panel edge (panel_label_recurring): a faded unmatched
    # component of a later display starting within this many staff gaps right of the panel edge
    "label_reach_gaps": 3.0,
    # ... at least label_mask_cover of whose pixels are screen-fixed faded ink: crop pixels that
    # are faded near-panel ink in at least label_recur_min_others + 1 displays of the chain
    # (dilated 1 px for antialiasing). Pixel-level, so a glyph fragmented differently per display
    # still recurs; a mark at a new position never does.
    "label_recur_min_others": 3,
    "label_mask_cover": 0.8,
}
JUMP_OVERLAP_CONFLICT = "JUMP_OVERLAP_CONTENT_CONFLICT"


def _overlap_registration(ca: np.ndarray, cb: np.ndarray, pa: Tuple[int, int], pb: Tuple[int, int],
                          columns: Tuple[int, int], cov_a: np.ndarray, cov_b: np.ndarray) -> Dict[str, Any]:
    """Masked integer SSD in panorama coordinates, with axis-wise three-point fits."""
    radius = 2
    ax, ay = pa
    bx, by = pb
    x0, x1 = max(columns[0], ax, bx), min(columns[1], ax + ca.shape[1], bx + cb.shape[1])
    y0, y1 = max(ay, by), min(ay + ca.shape[0], by + cb.shape[0])
    result: Dict[str, Any] = {"method": "masked_ssd_parabolic", "search_radius_px": radius,
                              "overlap_pano": [int(x0), int(y0), int(x1), int(y1)], "residual_px": None}
    if x1 - x0 <= 2 * radius or y1 - y0 <= 2 * radius:
        return dict(result, reason="overlap_too_small")
    a = _gray(sd.normalize_polarity(ca)[0])[y0-ay:y1-ay, x0-ax:x1-ax].astype(np.float32)
    b = _gray(sd.normalize_polarity(cb)[0])[y0-by:y1-by, x0-bx:x1-bx].astype(np.float32)
    hidden = np.asarray(cov_a[x0-ax:x1-ax], bool) | np.asarray(cov_b[x0-bx:x1-bx], bool)
    hidden = cv2.dilate(hidden.astype(np.uint8)[None], np.ones((1, 2*radius+1), np.uint8))[0] > 0
    h, w = a.shape
    free = np.broadcast_to(~hidden[radius:w-radius], (h-2*radius, w-2*radius))
    count = int(free.sum())
    if not count:
        return dict(result, reason="overlap_occluded", unmasked_px=0)
    local = a[radius:h-radius, radius:w-radius]
    costs = np.empty((5, 5), np.float64)
    for dy in range(-radius, radius+1):
        for dx in range(-radius, radius+1):
            delta = local - b[radius+dy:h-radius+dy, radius+dx:w-radius+dx]
            costs[dy+radius, dx+radius] = np.sum(np.square(delta), where=free, dtype=np.float64) / count
    # A flat axis has no preferred displacement; choose the closest equal-cost minimum.
    best = np.argwhere(costs == costs.min())
    yy, xx = min(best.tolist(), key=lambda p: ((p[0]-radius)**2 + (p[1]-radius)**2, p))
    shifts, fitted = [], []
    for axis, index in enumerate((xx, yy)):
        offset = 0.0
        valid = 0 < index < 2*radius
        if valid:
            before, center, after = costs[yy, xx-1:xx+2] if axis == 0 else costs[yy-1:yy+2, xx]
            curvature = float(before - 2*center + after)
            valid = curvature > 0 and np.isfinite(curvature)
            if valid and center != 0:
                offset = float(np.clip(.5*(before-after)/curvature, -.5, .5))
        shifts.append(float(index-radius+offset))
        fitted.append(bool(valid))
    return dict(result, residual_px=float(np.hypot(*shifts)), shift_px=shifts, fitted_axes=fitted,
                integer_shift_px=[int(xx-radius), int(yy-radius)], ssd=float(costs[yy, xx]), unmasked_px=count,
                search_boundary=bool(xx in (0, 4) or yy in (0, 4)))


def _overlap_dispositions(chain: Sequence[str], info: Dict[str, Any], composites: Dict[str, np.ndarray],
                          seam_of: Dict[Tuple[str, str], Dict[str, Any]], preservation: Dict[str, Any],
                          covered: Dict[str, np.ndarray]
                          ) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {d: [] for d in chain}
    for k, own in enumerate(info["owners"]):
        d = own["display"]
        ox, oy = own["offset_x"], own["offset_y"]
        h, w = composites[d].shape[:2]
        for j, retained in enumerate(info["owners"]):
            if j == k:
                continue
            x0 = max(ox, retained["pano_cols"][0])
            x1 = min(ox + w, retained["pano_cols"][1])
            if x1 <= x0:
                continue
            seams = [seam_of[(chain[i], chain[i + 1])] for i in range(min(j, k), max(j, k))]
            overlap = (max(ox, retained["offset_x"]),
                       min(ox+w, retained["offset_x"]+composites[retained["display"]].shape[1]))
            measurement = _overlap_registration(composites[d], composites[retained["display"]],
                                                 (ox, oy), (retained["offset_x"], retained["offset_y"]),
                                                 overlap, covered[d], covered[retained["display"]])
            measured = measurement["residual_px"]
            uncertainty = max(float(PRESERVE_CONFIG["match_tol_px"]), measured if measured is not None else 0.0)
            conflicts = [c for c in preservation["conflicts"] if c["display"] == d and
                         c["box_pano"][2] > x0 and c["box_pano"][0] < x1]
            pair = {"version": preservation["version"], "config": dict(preservation["config"]),
                    "displays": [p for p in preservation["displays"] if p["display"] in (d, retained["display"])],
                    "conflicts": conflicts, "content_preserved": not conflicts}
            out[d].append({"kind": "display_equivalent", "terminal": "equivalent_observation",
                           "display_id": f"jump:{d}", "retained_display_id": f"jump:{retained['display']}",
                           "region": [int(x0 - ox), 0, int(x1 - ox), int(h)],
                           "equivalence_map": [[1, 0, int(ox - retained["offset_x"])],
                                               [0, 1, int(oy - retained["offset_y"])], [0, 0, 1]],
                           "registration_uncertainty": uncertainty,
                           "evidence": {"method": "jump_panorama_overlap", "seams": seams,
                                        "geometric_registration": measurement,
                                        "photometric_residuals": [s.get("residual") for s in seams],
                                        "panorama_preservation": pair}})
            if measured is None or measurement.get("search_boundary") and measurement["ssd"] > 0:
                out[d].append({"kind": "display_unresolved", "terminal": "unresolved", "display_id": f"jump:{d}",
                               "region": [int(x0-ox), 0, int(x1-ox), int(h)],
                               "reason": "overlap_registration_unresolved", "evidence": measurement})
    return out


def _jump_display_fragment(d: str, fragments: Dict[str, Dict[str, Any]], equivalences: Dict[str, List[Dict[str, Any]]],
                           eps: Dict[str, Dict[str, Any]], composites: Dict[str, np.ndarray],
                           manifest: Dict[str, Any]) -> Dict[str, Any]:
    fragment = _merge_ledger([fragments[d]]) if d in fragments else _merge_ledger([])
    if d not in fragments:
        did = f"jump:{d}"
        fragment["source_video"] = str((manifest.get("source") or {}).get("path") or manifest.get("video_id") or "unknown_source")
        fragment["displays"].append({"id": did, "occurrence_id": did, "observations": list(eps[d]["observation_ids"]),
                                     "shape": list(composites[d].shape[:2]), "raw_inventory_missing": True})
        fragment["display_dispositions"].append({"kind": "display_unresolved", "terminal": "unresolved",
                                                 "display_id": did, "reason": "raw_members_unavailable"})
    # Missing raw inventory already makes the whole display unresolved.
    fragment["display_dispositions"].extend(e for e in equivalences[d] if d in fragments or e["kind"] != "display_unresolved")
    return fragment


def _panel_label_votes(displays: Sequence[str], composites: Dict[str, np.ndarray], covered: Dict[str, np.ndarray],
                       eps: Dict[str, Dict[str, Any]], obs_by: Dict[str, Dict[str, Any]], panel_right: int,
                       cfg: Dict[str, Any], pcfg: Dict[str, Any], *, include_panel: bool = False) -> np.ndarray:
    """The original comparison scope's faded near-panel pixel votes, never reclassified."""
    h = max(composites[d].shape[0] for d in displays)
    w = max(composites[d].shape[1] for d in displays)
    votes = np.zeros((h, w), np.int32)
    if panel_right <= 0:
        return votes
    for d in displays[1:]:
        comp, ep = composites[d], eps[d]
        dh, dw = comp.shape[:2]
        ink, _ = coverage_ink(comp, float(ep["staff_gap_px"]), _episode_staff_y(ep, obs_by),
                              float(cfg["ink_level"]), COVERAGE_CONFIG)
        if not include_panel:
            ink[:, :min(dw, panel_right)] = False
        if d in covered:
            ink[:, np.asarray(covered[d][:dw], dtype=bool)] = False
        norm, _ = sd.normalize_polarity(comp)
        gray = (cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm).astype(np.float32)
        contrast = np.clip(float(np.percentile(gray, 75)) - gray, 0, None)
        body = contrast[:, panel_right:][ink[:, panel_right:]]
        ref_c = float(np.percentile(body, 90)) if body.size else None
        if ref_c:
            if include_panel:
                edge = min(dw, panel_right)
                votes[:dh, :edge] += ink[:, :edge] & (contrast[:, :edge] < cfg["panel_faded_contrast"] * ref_c)
            reach = panel_right + 1 + float(pcfg["label_reach_gaps"]) * float(ep["staff_gap_px"])
            a, b = panel_right + 2, min(dw, int(np.floor(reach)) + 1)
            if b > a:
                votes[:dh, a:b] += ink[:, a:b] & (contrast[:, a:b] < cfg["panel_faded_contrast"] * ref_c)
    return votes


def panorama_preservation(chain: Sequence[str], info: Dict[str, Any], pano: np.ndarray, composites: Dict[str, np.ndarray],
                          covered: Dict[str, np.ndarray], eps: Dict[str, Dict[str, Any]], obs_by: Dict[str, Dict[str, Any]],
                          panel_right: int, cfg: Dict[str, Any], *, fixed: Optional[np.ndarray] = None,
                          chrome: Optional[np.ndarray] = None, chrome_info: Optional[Dict[str, Any]] = None,
                          pcfg: Optional[Dict[str, Any]] = None,
                          analysis_chain: Optional[Sequence[str]] = None,
                          label_votes: Optional[np.ndarray] = None,
                          start_trim: int = 0,
                          retained_left: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every display of a stitched chain against the panorama actually built from it. A
    complete column owner map says only which display supplies each column; it does not show
    that what the other displays draw in those columns is there. For each display, every ink
    component of its overlay-free composite (``coverage_ink``: measured staff scaffold removed;
    the panel columns of a later display and unrecovered overlay
    columns left out) is mapped by the display's registered panorama offset; its pixels in
    columns another display owns must lie on panorama ink (dilated ``match_tol_px``) for at
    least ``match_min_frac`` of them. A component wholly in the display's own columns is the
    panorama itself (``owned``). The composite is a median of the display's observations, so
    a component is already persistent in most of them (cursor, JPEG noise do not survive it).
    An unmatched component of a later display that starts at its panel edge and is faded (darkest
    ink below ``panel_faded_contrast`` of the 90th-percentile contrast of the display's ink)
    is the panel's label running past it (``panel_overflow``, on record, not a conflict).
    An unmatched faded component starting within ``label_reach_gaps`` right of that edge with at
    least ``label_mask_cover`` of its pixels on screen-fixed faded ink (crop pixels faded near the
    panel in >= ``label_recur_min_others`` + 1 displays, dilated 1 px) is the same label wider
    than the measured panel (``panel_label_recurring``, listed, not a conflict); position alone
    or fadedness alone never exempts.
    Recurrent crop positions and the registration's ``fixed`` mask are suspicions only.
    Only positive, appearance-matched screen chrome can explain discarded pixels;
    the detector's grown mask alone cannot explain notation. Returns the ledger: per-display and total
    counts (components / owned / matched / unmatched / speckle / panel_overflow / screen_fixed) and the unmatched
    components (``conflicts``, crop and panorama boxes)."""
    pcfg = pcfg or PRESERVE_CONFIG
    ccfg = COVERAGE_CONFIG
    lvl = float(cfg["ink_level"])
    offsets = info["offsets"]
    ref = chain[0]
    gap_ref = float(eps[ref]["staff_gap_px"])
    pano_lines = [y + offsets[0][1] for y in _episode_staff_y(eps[ref], obs_by)]
    pink = staff_scaffold(pano, gap_ref, pano_lines, lvl, ccfg)["ink"]
    tol = int(pcfg["match_tol_px"])
    if tol > 0:
        pink = cv2.dilate(pink.astype(np.uint8), np.ones((2 * tol + 1, 2 * tol + 1), np.uint8)) > 0
    ph, pw = pink.shape
    per: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    tot = {"components": 0, "owned": 0, "matched": 0, "unmatched": 0, "speckle": 0, "panel_overflow": 0,
           "panel_label_recurring": 0, "screen_fixed": 0}
    cnt_by: Dict[str, Dict[str, int]] = {}
    # per crop pixel: in how many displays it is faded ink just right of the panel edge; and the
    # unmatched faded components there (with their crop pixels), decided once every display is seen
    comparison = analysis_chain if analysis_chain is not None else chain
    external_votes = label_votes is not None or analysis_chain is not None
    if label_votes is None:
        label_votes = _panel_label_votes(comparison, composites, covered, eps, obs_by, panel_right, cfg, pcfg,
                                         include_panel=bool(start_trim)) \
            if external_votes else np.zeros((max(composites[d].shape[0] for d in chain),
                                             max(composites[d].shape[1] for d in chain)), np.int32)
    label_pending: List[Tuple[Dict[str, Any], np.ndarray, np.ndarray]] = []
    trim_evidence: List[Dict[str, Any]] = []
    recurring = label_votes >= int(pcfg["label_recur_min_others"]) + 1
    if recurring.any():
        recurring = cv2.dilate(recurring.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    items: List[Dict[str, Any]] = []
    # Use the line-switch chrome detector, with its own steady appearance. Direct
    # callers without a raw loader can still obtain positive evidence from the
    # composites; build_jump_systems supplies the job's raw-observation evidence.
    if chrome_info is None:
        shapes = [composites[d].shape for d in comparison]
        shape = max(set(shapes), key=shapes.count)
        same = [d for d in comparison if composites[d].shape == shape]
        # the score rows (audit F10) from the displays' raw observations: a symbol-sized colored
        # object there is score content, never chrome (the composites are full crops)
        zone_obs = [obs_by[eps[d]["observation_ids"][len(eps[d]["observation_ids"]) // 2]] for d in same
                    if eps[d].get("observation_ids") and eps[d]["observation_ids"][len(eps[d]["observation_ids"]) // 2] in obs_by]
        zone, zone_gap = rs.score_row_zone(zone_obs, shape[:2])
        chrome, chrome_info = oc.screen_fixed_chrome([composites[d] for d in same], protect=zone, gap=zone_gap)
    appearance = chrome_info.get("_appearance")
    reference = rs.nearest_appearance(appearance) if appearance is not None else None
    chrome_evidence = {k: v for k, v in chrome_info.items() if not k.startswith("_")}
    fixed_out: List[Dict[str, Any]] = []
    for k, d in enumerate(chain):
        comp = composites[d]
        ep = eps[d]
        h, w = comp.shape[:2]
        ox, oy = int(offsets[k][0]), int(offsets[k][1])
        own0, own1 = info["owners"][k]["pano_cols"]
        ink, _sc = coverage_ink(comp, float(ep["staff_gap_px"]), _episode_staff_y(ep, obs_by), lvl, ccfg)
        identified = np.zeros(ink.shape, bool)
        if chrome is not None and chrome.shape == ink.shape and reference is not None and reference.shape[:2] == ink.shape:
            palette = rs.chrome_palette([comp], chrome)
            identified = rs.chrome_explained(comp, ink & chrome, palette, rs._paper_color(comp, ~chrome), reference)
        later_display = d != comparison[0]
        trimmed_start = k == 0 and start_trim > 0 and later_display
        if later_display and panel_right > 0 and not trimmed_start:
            ink[:, :min(w, int(panel_right))] = False  # the screen-fixed panel: not score content of a later display
        cov = covered.get(d)
        if cov is not None:
            ink[:, np.asarray(cov[:w], dtype=bool)] = False  # unrecovered overlay columns (on record as such)
        n, lab, stats, _c = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
        cnt = {"components": 0, "owned": 0, "matched": 0, "unmatched": 0, "speckle": 0, "panel_overflow": 0,
               "panel_label_recurring": 0}
        cnt_by[d] = cnt
        edge = int(panel_right) if later_display else 0
        label_reach = edge + 1 + float(pcfg["label_reach_gaps"]) * float(ep["staff_gap_px"])
        contrast = ref_c = None
        if edge > 0:
            norm, _inv = sd.normalize_polarity(comp)
            g = (cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm).astype(np.float32)
            contrast = np.clip(float(np.percentile(g, 75)) - g, 0, None)
            body = contrast[:, edge:][ink[:, edge:]]  # the display's own ink right of its panel
            ref_c = float(np.percentile(body, 90)) if body.size else None
            if ref_c and not external_votes:
                b0, b1 = edge + 2, min(w, int(np.floor(label_reach)) + 1)  # edge+1 < x <= label_reach
                if b1 > b0:
                    band = ink[:, b0:b1] & (contrast[:, b0:b1] < cfg["panel_faded_contrast"] * ref_c)
                    label_votes[:h, b0:b1] += band
        panel_pixels = np.zeros(ink.shape, bool)
        if trimmed_start and ref_c:
            # Use the already detected panel and the same faded-ink threshold.
            # Dark ink is not panel merely because it falls left of the trim.
            panel_pixels[:, :edge] = (contrast[:, :edge] < cfg["panel_faded_contrast"] * ref_c) & recurring[:h, :edge]
            # Opaque fixed panel strokes also need their own steady appearance,
            # using the existing chrome appearance and matching tolerances.
            samples = [composites[e][:, :edge] for e in comparison[1:]
                       if composites[e].shape == comp.shape]
            if comp.ndim == 3 and len(samples) >= int(cfg["panel_min_pairs"]):
                values = np.stack(samples).astype(np.float32)
                stable = values.std(axis=0).max(axis=-1) <= oc.CHROME_MAX_STD
                panel_pixels[:, :edge] |= rs.chrome_explained(
                    comp[:, :edge], ink[:, :edge] & stable, np.empty((0, 3), np.float32),
                    rs._paper_color(comp, ~ink), values.mean(axis=0))
            panel_pixels |= identified
            panel_pixels[:, start_trim:] = False
        for i in range(1, n):
            x, y, bw, bh, area = (int(v) for v in stats[i])
            cnt["components"] += 1
            if area <= int(ccfg["speckle_max_px"]):
                cnt["speckle"] += 1
                continue
            items.append({"display": d, "box": [x, y, x + bw, y + bh], "area_px": area})
            # faded ink starting just right of (not at) a later display's panel edge
            near_label = False
            if edge > 0 and ref_c and edge + 1 < x <= label_reach:
                near_label = float(contrast[y:y + bh, x:x + bw][lab[y:y + bh, x:x + bw] == i].max()) < \
                    cfg["panel_faded_contrast"] * ref_c
            ys, xs = np.nonzero(lab[y:y + bh, x:x + bw] == i)
            px, py = xs + x + ox, ys + y + oy
            foreign = (px < own0) | (px >= own1)
            nf = int(foreign.sum())
            if nf == 0:
                cnt["owned"] += 1
                continue
            fx, fy = px[foreign], py[foreign]
            inside = (fx >= 0) & (fx < pw) & (fy >= 0) & (fy < ph)
            hits = np.zeros(nf, bool)
            hits[inside] = pink[fy[inside], fx[inside]]
            prefix_problem = False
            if trimmed_start:
                cy, cx = (ys + y)[foreign], (xs + x)[foreign]
                prefix = cx < start_trim
                if prefix.any():
                    explained_panel = panel_pixels[cy, cx].copy()
                    faded = contrast[cy, cx] < cfg["panel_faded_contrast"] * ref_c if ref_c else np.zeros(nf, bool)
                    faded_panel = prefix & faded & (cx < edge)
                    if faded_panel.any() and float(recurring[cy[faded_panel], cx[faded_panel]].mean()) >= float(pcfg["label_mask_cover"]):
                        explained_panel |= faded_panel
                    # Assess only the discarded pixels: a retained black note can
                    # touch a faded label without turning that label into music.
                    if edge - 1 <= x <= edge + 1 or (x <= edge + 1 and bool((explained_panel & (cx < edge)).any())):
                        explained_panel |= faded & (cx >= edge)
                    explained_panel |= faded & recurring[cy, cx] & (cx <= label_reach)
                    explained_panel &= prefix
                    retained = np.zeros(nf, bool)
                    if retained_left is not None:
                        rx, ry = cx + retained_left["dx"], cy + retained_left["dy"]
                        target = retained_left["ink"]
                        valid = prefix & (rx >= 0) & (rx < target.shape[1]) & (ry >= 0) & (ry < target.shape[0])
                        retained[valid] = target[ry[valid], rx[valid]]
                    hits |= explained_panel | retained
                    unexplained = int((prefix & ~hits).sum())
                    prefix_problem = unexplained > int(pcfg["min_foreign_px"])
                    trim_evidence.append({"display": d, "box_crop": [x, y, x + bw, y + bh],
                                          "trim_native": [0, int(start_trim)], "panel_px": int(explained_panel.sum()),
                                          "retained_overlap_px": int((retained & ~explained_panel).sum()),
                                          "unexplained_px": unexplained,
                                          "retained_display": retained_left["display"] if retained_left else None,
                                          "basis": "original_nonfirst_panel_and_retained_edge"})
                    if bool(explained_panel.all()):
                        cnt["panel_overflow"] += 1
                        continue
            hit = int(hits.sum())
            frac = hit / float(nf)
            if not prefix_problem and (nf <= int(pcfg["min_foreign_px"]) or frac >= float(pcfg["match_min_frac"])):
                cnt["matched"] += 1
                continue
            # All missing foreign pixels need an appearance explanation. A chrome
            # icon adjacent to a neutral note cannot exempt the whole component.
            missing = ~hits
            explained = identified[ys + y, xs + x][foreign]
            if bool(explained[missing].all()):
                fixed_out.append({"display": d, "box_crop": [x, y, x + bw, y + bh],
                                  "box_pano": [x + ox, y + oy, x + bw + ox, y + bh + oy],
                                  "area_px": area, "foreign_px": nf, "explained_px": int(missing.sum()),
                                  "classification": "EXPLAINED_CHROME",
                                  "evidence": {"method": "screen_fixed_chrome_appearance", **chrome_evidence}})
                continue
            if not prefix_problem and edge > 0 and x <= edge + 1 and ref_c and \
                    float(contrast[y:y + bh, x:x + bw][lab[y:y + bh, x:x + bw] == i].max()) < cfg["panel_faded_contrast"] * ref_c:
                # faded ink cut by a later display's panel edge: the panel's own label running past
                # the measured panel (a measure number, an instrument name); the panel is screen
                # chrome, never panorama content of a later display (on record)
                cnt["panel_overflow"] += 1
                continue
            conflict = {"display": d, "box_crop": [x, y, x + bw, y + bh], "box_pano": [x + ox, y + oy, x + bw + ox, y + bh + oy],
                        "area_px": area, "foreign_px": nf, "matched_frac": round(frac, 3),
                        "owner": next((o["display"] for o in info["owners"]
                                       if o["pano_cols"][0] <= int(np.median(fx)) < o["pano_cols"][1]), None)}
            if near_label and not prefix_problem:
                label_pending.append((conflict, ys + y, xs + x))  # decided by recurrence below
                continue
            cnt["unmatched"] += 1
            conflicts.append(conflict)
    # A faded component starting just right of a later display's panel edge whose pixels lie
    # (>= label_mask_cover) on crop pixels that are faded near-panel ink in at least
    # label_recur_min_others + 1 displays is the panel's own label running past the measured
    # panel (an instrument name wider than the panel's static columns): screen chrome, on record
    # as panel_label_recurring. Position alone or fadedness alone never exempts; dark ink there,
    # or faded ink at a position few displays share, stays a conflict.
    label_out: List[Dict[str, Any]] = []
    recurring = label_votes >= int(pcfg["label_recur_min_others"]) + 1
    if recurring.any():
        recurring = cv2.dilate(recurring.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    for c, cy, cx in label_pending:
        cover = float(recurring[cy, cx].mean()) if cy.size else 0.0
        if cover >= float(pcfg["label_mask_cover"]):
            cnt_by[c["display"]]["panel_label_recurring"] += 1
            label_out.append(dict(c, classification="PANEL_LABEL_RECURRING", recurring_cover=round(cover, 3)))
        else:
            cnt_by[c["display"]]["unmatched"] += 1
            conflicts.append(c)
    per = [dict(cnt_by[d], display=d, screen_fixed=0) for d in chain]
    # Position recurrence is suspicion, consistent with audit_jump_minority.
    suspicions: List[Dict[str, Any]] = []
    if conflicts:
        gap = float(np.median([float(eps[d]["staff_gap_px"]) for d in chain]))
        spots = mc.screen_fixed_spots(items, gap)
        if spots:
            suspicions = [dict(c, disposition="review_bundle") for c in conflicts
                          if mc.in_screen_fixed_spot(c["box_crop"], c["area_px"], spots, gap)]
    for rec in per:
        rec["screen_fixed"] = sum(1 for f in fixed_out if f["display"] == rec["display"])
        for key in tot:
            tot[key] += rec[key]
    conflicts.sort(key=lambda c: (c["box_pano"][0], c["display"]))
    return {"version": PRESERVE_VERSION, "checked": True, "config": dict(pcfg), "displays": per, "counts": tot,
            "content_preserved": not conflicts, "conflicts": conflicts,
            "panel_label_recurring": label_out,
            "screen_fixed": fixed_out, "screen_fixed_suspicions": suspicions,
            "chrome_evidence": chrome_evidence,
            **({"start_trim_evidence": trim_evidence} if start_trim else {})}


def _strip_conflicts(ledger: Dict[str, Any], x0: int, x1: int, first_k: bool, last_k: bool, prefix_w: int, top: int, sid: str,
                     out_dir: Path, eps: Dict[str, Dict[str, Any]], obs_by: Dict[str, Dict[str, Any]],
                     composites: Dict[str, np.ndarray], minority: Dict[str, Any], *,
                     manifest: Optional[Dict[str, Any]] = None, load: Optional[ImageLoader] = None) -> List[Dict[str, Any]]:
    """The ledger conflicts of a panorama chunk [x0, x1) (by panorama box centre; the chain's
    first / last chunk also takes conflicts left / right of it). Each display with a conflict
    is kept as an alternate strip of its own composite (the content the panorama discarded is
    drawn there; listed in ``minority`` ``alternates``, numbered after the minority ones), and
    each conflict as a ``minority`` event of kind ``overlap_conflict`` with its strip box.
    Returns the chunk's conflicts."""
    import base64
    mine = []
    for c in ledger.get("conflicts") or []:
        cx = (c["box_pano"][0] + c["box_pano"][2]) / 2.0
        if (x0 <= cx < x1) or (first_k and cx < x0) or (last_k and cx >= x1):
            mine.append(dict(c))
    by_disp: Dict[str, List[Dict[str, Any]]] = {}
    for c in mine:
        by_disp.setdefault(c["display"], []).append(c)
    for d, cs in by_disp.items():
        ep = eps[d]
        comp = composites[d]
        h, w = comp.shape[:2]
        gap = float(ep["staff_gap_px"])
        sy = _episode_staff_y(ep, obs_by)
        pad = int(round(rs.PAD_V_GAPS * gap))
        keep = (max(0, int(sy[0] - pad)), min(h, int(np.ceil(sy[-1] + pad)) + 1)) if sy else (0, h)
        weak_out: Dict[str, Any] = {}
        full, inverted, flattened, finish_info = rs.finish_strip(comp, weak_out=weak_out)
        img, trimmed = rs.trim_blank_rows(full, keep=rs.keep_weak_mark_rows(keep, weak_out.get("mask")), pad=pad)
        rs.audit_weak_marks_cropped(finish_info, weak_out.get("mask"), (trimmed[0], full.shape[0] - trimmed[1]))
        abox = [0, int(trimmed[0]), int(w), int(h - trimmed[1])]
        suffix = f"alt{len(minority['alternates']) + 1}"
        (out_dir / "alt").mkdir(parents=True, exist_ok=True)
        apath = out_dir / "alt" / f"strip_{sid}-{suffix}.png"
        if not cv2.imwrite(str(apath), img):
            raise RuntimeError(f"failed to write strip {apath}")
        first_ev = len(minority["events"])
        patches = []
        for c in cs:
            bx0, by0, bx1, by1 = c["box_pano"]
            c["alternate"] = suffix
            minority["events"].append({"kind": "overlap_conflict", "display": d, "box_crop": list(c["box_crop"]),
                                       "area_px": c["area_px"], "times": [[round(float(ep["t_start"]), 4), round(float(ep["t_end"]), 4)]],
                                       "box_strip": [int(bx0 - x0 + prefix_w), int(by0 - top), int(bx1 - x0 + prefix_w), int(by1 - top)],
                                       "alternate": suffix, "owner": c.get("owner")})
            # Retain the pre-finishing composite and every raw witness. A
            # persistent mark has no minority event, and finishing an alternate
            # is not sufficient evidence that the discarded raw pixels survived.
            a, b, z, q = c["box_crop"]
            r = max(2, int(round(gap)))
            pbox = [max(0, a-r), max(0, b-r), min(w, z+r), min(h, q+r)]
            def add_patch(image, **owner):
                raw = image[pbox[1]:pbox[3], pbox[0]:pbox[2]]
                ok, png = cv2.imencode(".png", raw)
                if not ok:
                    raise RuntimeError("failed to encode jump overlap evidence")
                patches.append({"event_index": len(minority["events"])-1, "display": d,
                                "box_crop": pbox, "event_box_crop": list(c["box_crop"]),
                                "raw_png_base64": base64.b64encode(png.tobytes()).decode("ascii"), **owner})
            add_patch(comp, kind="display_composite", obs_ids=list(ep["observation_ids"]))
            if load is not None:
                for oid, rid in zip(ep["observation_ids"], ep["region_ids"]):
                    add_patch(load(obs_by[oid]), kind="raw_observation", obs_id=oid, region_id=rid,
                              t_sec=float(obs_by[oid]["t_sec"]))
        minority["alternates"].append({
            "suffix": suffix, "parent_id": sid, "display": d, "path": str(apath), "kind": "overlap_conflict",
            "events": list(range(first_ev, len(minority["events"]))),
            "finishing": finish_info,
            "evidence_patches": patches,
            **({"source_clipped": clipped} if manifest is not None and
               (clipped := rs.source_clipping(comp, abox, manifest)) else {}),
            "obs_ids": list(ep["observation_ids"]), "region_ids": list(ep["region_ids"]),
            "t_start": round(float(ep["t_start"]), 4), "t_end": round(float(ep["t_end"]), 4),
            "box_crop": abox, "size": [int(img.shape[1]), int(img.shape[0])], "method": "display_composite",
            "members_used": len(ep["observation_ids"]), "inverted": bool(inverted), "paper_flattened": bool(flattened),
            "event_boxes_strip": [[c["box_crop"][0] - abox[0], c["box_crop"][1] - abox[1], c["box_crop"][2] - abox[0],
                                   c["box_crop"][3] - abox[1]] for c in cs]})
    return mine


def _staff_of(lines: Sequence[float], gap: float, width: int, ink: np.ndarray) -> Dict[str, Any]:
    from app.pipeline import reflow_boundaries as rb
    return {"lines": [float(y) for y in lines], "gap": float(gap), "thick": rb._thickness(ink, lines, 0, width), "x": (0, width - 1)}


def chunk_cuts(pano: np.ndarray, lines: Sequence[float], gap: float, cfg: Dict[str, Any]) -> Tuple[List[int], Dict[str, Any]]:
    """Columns where a long panorama is cut into strips: just right of a barline, in a column with
    no ink besides the staff lines over the full height (and none in the staff band between). Chunks are about equally wide
    and at most ``chunk_max_gaps``; without such a column the chunk stays longer (never a cut
    through ink)."""
    w = pano.shape[1]
    maxw, minw = int(cfg["chunk_max_gaps"] * gap), int(cfg["chunk_min_gaps"] * gap)
    if w <= maxw:
        return [], {"barlines": None, "candidates": 0}
    norm, _inv = sd.normalize_polarity(pano)
    ink = sd.ink_mask(norm)
    st = _staff_of(lines, gap, w, ink)
    gray = _gray(norm)
    paper = float(np.percentile(gray, 75))
    dark = gray < min(215.0, paper - 35.0)
    half = st["thick"] / 2.0 + 1.0
    for y in lines:
        dark[max(0, int(np.floor(y - half))): int(np.ceil(y + half)) + 1] = False
    clear = ~dark.any(axis=0)
    nonstaff = ink.copy()
    for y in lines:
        nonstaff[max(0, int(np.floor(y - half))): int(np.ceil(y + half)) + 1] = 0
    bars = sd.find_barlines(ink, st, nonstaff)
    off = max(1, int(round(cfg["chunk_clear_gaps"] * gap)))
    reach = max(off, int(round(cfg["chunk_reach_gaps"] * gap)))
    b0 = max(0, int(lines[0] - 0.5 * gap))
    b1 = min(dark.shape[0], int(np.ceil(lines[4] + 0.5 * gap)) + 1)
    band_clear = ~dark[b0:b1].any(axis=0)
    cands = []
    for b in bars:
        x1 = int(b["x1"])
        # the first column right of the barline that is clear over the full height (a measure number
        # printed over the barline stays whole on the left), with nothing in the staff band in between
        for x in range(x1 + 1 + off, min(w - minw, x1 + 1 + reach)):
            if not band_clear[x1 + 1: x + 1].all():
                break
            if clear[x]:
                cands.append(x)
                break
    n = int(np.ceil(w / float(maxw)))
    target = w / float(n)
    out: List[int] = []
    start = 0
    while w - start > maxw:
        ok = [x for x in cands if start + minw <= x <= start + maxw and w - x >= minw]
        if not ok:
            later = [x for x in cands if x > start + maxw and w - x >= minw]
            if not later:
                break
            x = later[0]
        else:
            x = min(ok, key=lambda v: abs(v - (start + target)))
        out.append(int(x))
        start = x
    return out, {"barlines": len(bars), "candidates": len(cands), "target_px": int(target)}


def run_episode_ids(run: Dict[str, Any], tracking: Dict[str, Any]) -> List[str]:
    """Every episode of the run's slot from its first to its last display (unconfirmed
    mid-jump frames included): these are shown by the panorama strips, not as page systems."""
    eps = sorted((e for e in tracking.get("episodes", []) if str(e.get("slot_id")) == str(run["slot_id"])),
                 key=lambda e: (e["t_start"], e["id"]))
    ids = [e["id"] for e in eps]
    first, last = run["chains"][0][0], run["chains"][-1][-1]
    return ids[ids.index(first): ids.index(last) + 1]


def remaining_unsupported(tracking: Dict[str, Any], jump: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Tracker intervals that stay unsupported once the jump-view runs are taken out: a leftover
    piece longer than a jump transition, or one that holds a stable display outside every run
    (smooth scroll, or horizontal motion that is not a verified jump view).
    Test/dev only."""
    cfg = cfg or jump.get("config") or CONFIG
    runs = jump.get("runs") or []
    in_run = {i for r in runs for i in run_episode_ids(r, tracking)}
    cover = [(float(r["start"]), float(r["end"])) for r in runs]
    eps = [e for e in tracking.get("episodes", []) if e.get("confirmed") and e["id"] not in in_run
           and float(e["t_end"]) - float(e["t_start"]) >= cfg["dwell_min_sec"]]
    out = []
    for iv in tracking.get("layout_intervals", []):
        if iv.get("supported", True):
            continue
        for a, b in _subtract((float(iv["start"]), float(iv["end"])), cover):
            stable = any(min(b, float(e["t_end"])) - max(a, float(e["t_start"])) > 0 for e in eps)
            if b - a > cfg["transition_max_sec"] or stable:
                out.append(dict(iv, start=a, end=b))
    return out


def _region_of(obs: Dict[str, Any], rid: str) -> Optional[Dict[str, Any]]:
    return next((r for r in obs.get("system_regions") or [] if r["region_id"] == rid), None)


def _clef_prefix(img: np.ndarray, rec: Dict[str, Any]) -> Dict[str, Any]:
    """A verified clef-only patch at the start of a finished strip (reflow_units.clef_patch)."""
    from app.pipeline import reflow_boundaries as rb
    from app.pipeline import reflow_units as ru
    an = rb.analyse_strip(img, rec, system_id=rec.get("system_id"))
    p = ru.clef_patch(an)
    if not p.get("verified"):
        return {"verified": False, "reason": p.get("reason")}
    return {"verified": True, "image": p["_image"], "box": p["box"], "staff_top": float(rec["staff_y_strip"][0]),
            "patch_pixels_sha256": p["patch_pixels_sha256"]}


def _with_prefix(img: np.ndarray, staff_top: float, prefix: Dict[str, Any], lead: int) -> Tuple[np.ndarray, int]:
    """The chunk with the copied clef patch (rows aligned on the top staff line) and ``lead``
    columns of paper and staff lines (the patch's last column: clear of ink by construction)
    in front."""
    patch = prefix["image"]
    h = img.shape[0]
    dy = int(round(staff_top - prefix["staff_top"]))
    aligned = np.full((h, patch.shape[1]) + patch.shape[2:], 255, dtype=np.uint8)
    r0, r1 = max(0, dy), min(h, dy + patch.shape[0])
    if r1 > r0:
        aligned[r0:r1] = patch[r0 - dy:r1 - dy]
    lead_cols = np.repeat(aligned[:, -1:], lead, axis=1)
    out = np.concatenate([aligned, lead_cols, img], axis=1)
    return out, int(aligned.shape[1] + lead)


def finish_panorama_chunk(raw: np.ndarray, lines: Sequence[float], gap: float
                          ) -> Tuple[np.ndarray, bool, bool, Dict[str, Any], List[int]]:
    """One panorama chunk finished (``reflow_strips.finish_strip``) and trimmed to its rows: blank
    paper rows above/below the ink go, the staff with its padding and the rows of weak marks
    (``weak_out``, audit F11: lighter than the trim's ink cutoff) stay, and the weak-mark survival
    check covers the delivered rows. Returns (image, inverted, paper flattened, finish info,
    [rows trimmed at the top, at the bottom])."""
    weak_out: Dict[str, Any] = {}
    img, inverted, flattened, finish_info = rs.finish_strip(raw, gap=gap, staff=(lines, 0, raw.shape[1]),
                                                            weak_out=weak_out)
    if img.shape != raw.shape:
        raise ValueError("jump ledger needs finish_strip crop geometry")
    pad = int(round(rs.PAD_V_GAPS * gap))
    keep = (max(0, int(lines[0] - pad)), min(img.shape[0], int(np.ceil(lines[4] + pad)) + 1))
    weak = weak_out.get("mask")
    out, trimmed = rs.trim_blank_rows(img, keep=rs.keep_weak_mark_rows(keep, weak), pad=pad)
    rs.audit_weak_marks_cropped(finish_info, weak, (trimmed[0], img.shape[0] - trimmed[1]))
    return out, inverted, flattened, finish_info, trimmed


def build_jump_systems(jump: Dict[str, Any], tracking: Dict[str, Any], manifest: Dict[str, Any], out_dir: Path, *,
                       composites: Dict[str, np.ndarray], covered: Dict[str, np.ndarray],
                       load: Optional[ImageLoader] = None,
                       evidence_dir: Optional[Path] = None, ledger: bool = False,
                       logger: Callable[[str], None] = lambda _m: None,
                       checkpoint: Callable[[], None] = lambda: None,
                       run_indices: Optional[Sequence[int]] = None) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Panorama strips of every jump-view run: (occurrence entry, strip record with ``path``) per
    chunk, in video order. The strip record has the keys of ``reflow_strips.build_strip`` plus a
    ``jump`` section (chain, owner map, member offsets, clef prefix, flags). Strip coordinates:
    x = strip column, y = panorama row; a member observation's crop x maps to strip x by + its
    ``offset_x`` (``reflow_boundaries.member_regions``).

    Minority content: every display of every chain is audited against all its observations
    before any panorama is built (``audit_jump_minority``); a chunk's events are listed in its
    ``minority_content`` (with alternates, one per display moment) and flag it
    ``MINORITY_CONTENT_DROPPED``. Without ``load`` nothing is audited and every strip is flagged
    ``JUMP_MINORITY_UNCHECKED``.

    Preservation: every chain's panorama is checked against each of its displays
    (``panorama_preservation``); content a display draws in an overlap column another display
    owns that the panorama lacks is kept as an alternate of that display's composite, listed as a
    ``minority_content`` event of kind ``overlap_conflict`` and flags the chunk
    ``JUMP_OVERLAP_CONTENT_CONFLICT``; the ledger is ``jump.preservation``."""
    cfg = jump.get("config") or CONFIG
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obs_by = {o["id"]: o for o in manifest["observations"]}
    eps = {e["id"]: e for e in tracking.get("episodes", [])}
    seam_of = {(s["a"], s["b"]): s for s in jump.get("seams", [])}
    panel_of = {sl["slot_id"]: int(sl["panel"]["right"]) for sl in jump.get("slots", [])}
    results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    display_ledgers = dict(jump.get("ledger_displays") or {})
    fixed_of = jump.get("_fixed")
    audits: Optional[Dict[str, Dict[str, Any]]] = None
    chrome, chrome_info = None, None
    if load is not None:
        chrome, chrome_info = rs.job_screen_chrome(manifest, load)
        audit_jump = dict(jump, runs=[r for i, r in enumerate(jump.get("runs") or [])
                                     if run_indices is None or i in run_indices])
        audits, spots = audit_jump_minority(audit_jump, eps, obs_by, composites, load, manifest=manifest)
        logger(f"jump: minority audit of {len(audits)} displays: {sum(len(a['events']) for a in audits.values())} events"
               + (f", specks at {len(spots)} screen-fixed spots kept on record" if spots else ""))
    for ri, run in enumerate(jump.get("runs") or []):
        if run_indices is not None and ri not in run_indices:
            continue
        panel_right = panel_of.get(run["slot_id"], 0)
        analysis_context = {}
        original_pairs = {}
        run_members = {d for c in run["panorama_chains"] for d in c["displays"]}
        if any(s.get("user_rejected") and s["a"] in run_members and s["b"] in run_members for s in seam_of.values()):
            # Retain the original panel comparison population. A rejected
            # join's ownership cut cannot authorize discarding its overlap.
            original_seams = [dict(s, user_rejected=False) for s in jump.get("seams", [])]
            original_pairs = {(s["a"], s["b"]): s for s in original_seams}
            for original_chain in panorama_chains(run, original_seams):
                members = original_chain["displays"]
                votes = _panel_label_votes(members, composites, covered, eps, obs_by, panel_right, cfg, PRESERVE_CONFIG,
                                           include_panel=True)
                for d in members:
                    analysis_context[d] = (members, votes)
        clef: Optional[Dict[str, Any]] = None
        clef_source: Optional[Dict[str, Any]] = None
        clef_info: Dict[str, Any] = {"verified": False, "reason": "not_checked"}
        chunk_no = 0
        previous_owner = None
        for ci, chain in enumerate(run["panorama_chains"]):
            checkpoint()
            disp = chain["displays"]
            gap = float(np.median([float(eps[d]["staff_gap_px"]) for d in disp]))
            rejected_start = bool(chain.get("break_before") and
                                  next((s.get("user_rejected") for s in seam_of.values()
                                        if s["id"] == chain["break_before"]), False))
            left_trim = panel_right if rejected_start else 0
            pano, info = build_panorama(disp, seam_of, composites, covered, panel_right, gap, cfg, left_trim=left_trim)
            if not info["owner_map_complete"]:
                raise ValueError(f"panorama owner map incomplete for {disp[0]}..{disp[-1]}")
            for d in disp if ledger else ():
                stale = evidence_dir is not None and (display_ledgers.get(d) or {}).get("evidence_root") != str(Path(evidence_dir).resolve())
                if load is not None and (d not in display_ledgers or stale):
                    display_ledgers[d] = display_record(eps[d], manifest, load, obs_by, cfg, ledger=True,
                                                        evidence_dir=evidence_dir)["ledger"]
            # a complete owner map does not certify preservation: every display's own content is
            # looked up in the panorama actually built (Codex J1)
            comparison, votes = analysis_context.get(disp[0], (None, None))
            retained_left = None
            if left_trim and previous_owner is not None:
                a = previous_owner["display"]
                original_offset = seam_offset(original_pairs.get((a, disp[0]), {}))
                if original_offset is not None:
                    # The preceding chain keeps its full right edge. This is a
                    # pixel witness, not permission to join the rejected seam.
                    target, _ = coverage_ink(composites[a], float(eps[a]["staff_gap_px"]),
                                             _episode_staff_y(eps[a], obs_by), float(cfg["ink_level"]), COVERAGE_CONFIG)
                    lo, hi = previous_owner["owned_cols_display"]
                    target[:, :lo] = False
                    target[:, hi:] = False
                    target[:, np.asarray(covered[a], dtype=bool)] = False
                    tol = int(PRESERVE_CONFIG["match_tol_px"])
                    if tol > 0:
                        target = cv2.dilate(target.astype(np.uint8), np.ones((2 * tol + 1, 2 * tol + 1), np.uint8)) > 0
                    retained_left = {"ink": target, "display": a, "dx": original_offset[0], "dy": original_offset[1]}
            preservation = panorama_preservation(disp, info, pano, composites, covered, eps, obs_by, panel_right, cfg,
                                           fixed=(fixed_of or {}).get(str(run["slot_id"])),
                                           chrome=chrome, chrome_info=chrome_info,
                                           analysis_chain=comparison, label_votes=votes,
                                           start_trim=left_trim, retained_left=retained_left)
            previous_owner = info["owners"][-1]
            equivalences = _overlap_dispositions(disp, info, composites, seam_of, preservation, covered) if ledger else {}
            attached: set[str] = set()
            if preservation["conflicts"]:
                logger(f"jump: run {ri + 1} chain {ci + 1}: {len(preservation['conflicts'])} overlap components of "
                       f"{sorted({c['display'] for c in preservation['conflicts']})} not found in the panorama")
            off = {d: (o[0], o[1]) for d, o in zip(disp, info["offsets"])}
            ref = disp[0]
            lines = [y + off[ref][1] for y in _episode_staff_y(eps[ref], obs_by)]
            if len(lines) != 5:
                raise ValueError(f"no staff rows for {ref}")
            cuts, cinfo = chunk_cuts(pano, lines, gap, cfg)
            edges = [0] + cuts + [pano.shape[1]]
            for k in range(len(edges) - 1):
                x0, x1 = edges[k], edges[k + 1]
                raw = pano[:, x0:x1]
                img, inverted, flattened, finish_info, trimmed = finish_panorama_chunk(raw, lines, gap)
                owned = [o for o in info["owners"] if o["pano_cols"][1] > x0 and o["pano_cols"][0] < x1]
                # staff extent in strip columns: the displays' own staff_x at the chain ends
                o0, o1 = owned[0], owned[-1]
                mid0 = eps[o0["display"]]
                r0 = _region_of(obs_by[mid0["observation_ids"][len(mid0["observation_ids"]) // 2]],
                                mid0["region_ids"][len(mid0["region_ids"]) // 2]) or {}
                mid1 = eps[o1["display"]]
                r1 = _region_of(obs_by[mid1["observation_ids"][len(mid1["observation_ids"]) // 2]],
                                mid1["region_ids"][len(mid1["region_ids"]) // 2]) or {}
                sx0 = max(0, int((r0.get("staff_x") or [0, 0])[0]) + o0["offset_x"] - x0) if x0 == 0 else 0
                sx1 = min(x1 - x0 - 1, int((r1.get("staff_x") or [0, 10 ** 9])[1]) + o1["offset_x"] - x0) \
                    if x1 == pano.shape[1] else x1 - x0 - 1
                top = int(trimmed[0])
                staff_y = [round(float(y) - top, 2) for y in lines]
                sid = f"jmp-{ri + 1:02d}-{chunk_no + 1:03d}"
                rec_base = {"system_id": sid, "staff_gap_px": round(gap, 3), "staff_y_strip": staff_y,
                            "staff_x_strip": [int(sx0), int(sx1)]}
                # clef: the run's first strip shows the score's own clef; every later strip gets a
                # copy of it in front (removed again when the strip continues mid-line)
                prefix_w = 0
                if clef is None and chunk_no == 0:
                    clef_info = _clef_prefix(img, rec_base)
                    clef = clef_info if clef_info.get("verified") else {}
                    own_clef = bool(clef)
                    if own_clef:
                        box = clef["box"]
                        clef_source = {"source_display_id": f"jump:{ref}",
                                       "source_bbox_display": [int(box[0] + x0 - off[ref][0]),
                                                               int(box[1] + top - off[ref][1]),
                                                               int(box[2] + x0 - off[ref][0]),
                                                               int(box[3] + top - off[ref][1])]}
                else:
                    own_clef = False
                prefix_rec = None
                if not own_clef and clef:
                    lead = int(round(cfg["clef_lead_gaps"] * gap))
                    img, prefix_w = _with_prefix(img, staff_y[0], clef, lead)
                    prefix_rec = {"copied_from": f"jmp-{ri + 1:02d}-001", "width_px": prefix_w, "lead_px": lead,
                                  "patch_box": clef["box"], "patch_pixels_sha256": clef["patch_pixels_sha256"]}
                    sx0 = 0
                    sx1 = sx1 + prefix_w
                rec_base["staff_x_strip"] = [int(sx0), int(sx1)]
                members, member_ids, used, offered = [], [], 0, 0
                for o in owned:
                    e = eps[o["display"]]
                    ids = _evenly(list(zip(e["observation_ids"], e["region_ids"])), int(cfg["max_members"]))
                    offered += len(e["observation_ids"])
                    used += len(ids)
                    for oid, rid in ids:
                        members.append({"obs_id": oid, "region_id": rid, "episode_id": e["id"],
                                        "offset_x": int(o["offset_x"] - x0 + prefix_w), "offset_y": int(o["offset_y"] - top)})
                        member_ids.append(oid)
                issues: List[str] = list(finish_info["issues"])
                unrec = sum(int(covered[o["display"]][max(0, max(x0, o["pano_cols"][0]) - o["offset_x"]):
                                                     max(0, min(x1, o["pano_cols"][1]) - o["offset_x"])].sum()) for o in owned)
                first_k, last_k = k == 0, k == len(edges) - 2
                if (first_k and chain["break_before"]) or (last_k and chain["break_after"]):
                    issues.append(JUMP_SEAM_UNVERIFIED)
                minority, m_issues = _strip_minority(audits, disp, off, x0, x1, first_k, last_k, prefix_w, top, sid, out_dir,
                                                     eps, obs_by, composites, load, manifest=manifest)
                issues.extend(m_issues)
                chunk_conf = _strip_conflicts(preservation, x0, x1, first_k, last_k, prefix_w, top, sid, out_dir, eps, obs_by,
                                              composites, minority, manifest=manifest, load=load)
                if chunk_conf:
                    issues.append(JUMP_OVERLAP_CONFLICT)
                path = out_dir / f"strip_{sid}.png"
                if not cv2.imwrite(str(path), img):
                    raise RuntimeError(f"failed to write strip {path}")
                h = img.shape[0]
                jrec = {
                    "run": ri, "chain": ci, "chunk": k, "chunks_in_chain": len(edges) - 1,
                    **({"left_trim_native": left_trim, "left_trim_basis": "detected_panel"} if left_trim else {}),
                    "chain_displays": [disp[0], disp[-1]], "pano_cols": [int(x0), int(x1)],
                    "owners": [{"display": o["display"], "strip_cols": [int(max(x0, o["pano_cols"][0]) - x0 + prefix_w),
                                                                         int(min(x1, o["pano_cols"][1]) - x0 + prefix_w)],
                                "offset_x": int(o["offset_x"] - x0 + prefix_w), "offset_y": int(o["offset_y"] - top),
                                "panel_columns_used": o["panel_columns_used"]} for o in owned],
                    "stitch_cuts": [dict(c, x=int(c["x"] - x0 + prefix_w)) for c in info["cuts"] if x0 <= c["x"] < x1],
                    "members": members, "clef_prefix": prefix_rec, "own_clef": own_clef,
                    "no_clef_copy": not clef and not own_clef,  # no verified clef in this run to copy: lines start bare
                    "unverified_seam_before": chain["break_before"] if first_k else None,
                    "unverified_seam_after": chain["break_after"] if last_k else None,
                    "chunk_cut_info": cinfo if k == 0 else None,
                    # chain ledger (counts on every chunk of the chain; conflicts: this chunk's)
                    "preservation": {"version": preservation["version"], "counts": dict(preservation["counts"]),
                                     "displays": preservation["displays"] if k == 0 else None,
                                     "chain_content_preserved": preservation["content_preserved"],
                                     "chain_conflicts": len(preservation["conflicts"]),
                                     "screen_fixed": preservation["screen_fixed"] if k == 0 else [],
                                     "screen_fixed_suspicions": preservation["screen_fixed_suspicions"] if k == 0 else [],
                                     "panel_label_recurring": preservation["panel_label_recurring"] if k == 0 else [],
                                     **({"start_trim_evidence": preservation["start_trim_evidence"]}
                                        if k == 0 and "start_trim_evidence" in preservation else {}),
                                     "chrome_evidence": preservation["chrome_evidence"],
                                     "conflicts": chunk_conf},
                }
                # Several displays can contribute to one written panorama system.
                # Keep their independent evidence records inside one review bundle.
                if minority.get("alternates"):
                    variants = minority["alternates"]
                    bundle = dict(variants[0], kind="uncertain_mark_bundle", method="review_bundle",
                                  evidence_records=[dict(v) for v in variants],
                                  events=list(range(len(minority["events"]))),
                                  thumbnail_covers_all_hypotheses=False)
                    bundle["obs_ids"] = [oid for v in variants for oid in v["obs_ids"]]
                    bundle["region_ids"] = [rid for v in variants for rid in v["region_ids"]]
                    bundle["t_start"] = min(v["t_start"] for v in variants)
                    bundle["t_end"] = max(v["t_end"] for v in variants)
                    for event in minority["events"]:
                        event["evidence_alternate"] = event.get("alternate")
                        event["alternate"] = bundle["suffix"]
                        event["alternates"] = [bundle["suffix"]]
                    minority["alternates"] = [bundle]
                rec = dict(rec_base, **{
                    "box_crop": [0, int(top), int(img.shape[1]), int(top + h)],
                    "envelope_crop": [0, int(top), int(img.shape[1]), int(top + h)], "envelope_samples": 0,
                    "envelope_flags": ["jump_panorama"],
                    "size": [int(img.shape[1]), int(h)], "reference_obs_id": member_ids[len(member_ids) // 2] if member_ids else None,
                    "member_obs_ids": member_ids, "inverted": bool(inverted), "paper_flattened": bool(flattened),
                    "preview_tail": None, "issues": list(issues), "single_row_full_height": True, "row_cuts": {},
                    "blank_rows_trimmed": [int(trimmed[0]), int(trimmed[1])], "members_offered": offered,
                    "reference_index": 0, "max_rel_shift_px": 0.0, "members_used": used, "unrecovered_columns": int(unrec),
                    "composited": True,
                    "uncut_pixels_sha256": hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest(),
                    "minority_content": minority, "jump": jrec, "path": str(path),
                    "finishing": finish_info,
                    "uncertain_marks": [{"seen": e.get("seen"), "eligible": e.get("eligible"),
                                         "bbox": e["box_strip"], "disposition": "review_bundle"}
                                        for e in minority["events"] if "seen" in e],
                })
                from app.pipeline import reflow_boundaries as rb
                rec["frame_edges"] = rb.strip_frame_edges(rec, manifest)
                fragments, refs, chains = [], [], []
                # Equal-view seams can leave a middle display owning no columns at all.
                if ledger and first_k:
                    for owner in info["owners"]:
                        if owner["pano_cols"][0] == owner["pano_cols"][1]:
                            d = owner["display"]
                            fragments.append(_jump_display_fragment(d, display_ledgers, equivalences, eps, composites, manifest))
                            attached.add(d)
                for owner in owned:
                    if owner["pano_cols"][0] == owner["pano_cols"][1]:
                        continue
                    d = owner["display"]
                    if ledger and d not in attached:
                        fragments.append(_jump_display_fragment(d, display_ledgers, equivalences, eps, composites, manifest))
                        attached.add(d)
                    elif ledger:
                        refs.append({"display_id": f"jump:{d}", "also_in_strip": sid})
                    matrix = [[1, 0, int(owner["offset_x"] - x0 + prefix_w)],
                              [0, 1, int(owner["offset_y"] - top)], [0, 0, 1]]
                    chains.append({"display_id": f"jump:{d}", "strip_id": sid,
                                   "domain_strip": [int(max(x0, owner["pano_cols"][0])-x0+prefix_w),
                                                    int(min(x1, owner["pano_cols"][1])-x0+prefix_w)],
                                   "stages": [{"stage": "display_to_strip", "kind": "affine", "matrix": matrix}]})
                if ledger:
                    rec["ledger"] = _merge_ledger(fragments)
                    rec["ledger_display_refs"] = refs
                rec["ledger_chain"] = chains
                rec["ledger_supersedes"] = None
                if prefix_rec and clef_source:
                    dy = int(round(staff_y[0] - clef["staff_top"]))
                    r0, r1 = max(0, dy), min(h, dy + clef["image"].shape[0])
                    box = clef_source["source_bbox_display"]
                    rec["ledger_strip_generated"] = [{"kind": "replica", "strip_bbox": [0, r0, int(clef["image"].shape[1]), r1],
                                                       **clef_source,
                                                       "source_bbox_display": [box[0], box[1] + r0 - dy, box[2], box[1] + r1 - dy],
                                                       "reason": "jump_clef_prefix"}]
                rs.persist_raw_evidence(rec, out_dir, sid)
                # Diagnose each owner's uncleaned window, then map its affected
                # columns into this chunk. A neighbouring chunk gets no flag.
                if load is not None:
                    clipped_parts = []
                    for owner in owned:
                        ep = eps[owner["display"]]
                        oid = ep["observation_ids"][len(ep["observation_ids"]) // 2]
                        member_raw = load(obs_by[oid])
                        mh, mw = member_raw.shape[:2]
                        owner_box = [max(0, max(x0, owner["pano_cols"][0]) - owner["offset_x"]),
                                     max(0, top - owner["offset_y"]),
                                     min(mw, min(x1, owner["pano_cols"][1]) - owner["offset_x"]),
                                     min(mh, top + h - owner["offset_y"])]
                        clipped = rs.source_clipping(member_raw, owner_box, manifest)
                        if clipped:
                            a, b = clipped["columns"]
                            a += owner_box[0] + owner["offset_x"] - x0 + prefix_w
                            b += owner_box[0] + owner["offset_x"] - x0 + prefix_w
                            if a < img.shape[1] and b > prefix_w:
                                clipped_parts.append(dict(clipped, columns=[max(prefix_w, a), min(img.shape[1], b)]))
                    if clipped_parts:
                        rec["source_clipped"] = {
                            "sides": sorted({side for p in clipped_parts for side in p["sides"]}),
                            "columns": [min(p["columns"][0] for p in clipped_parts), max(p["columns"][1] for p in clipped_parts)]}
                        rec["issues"].append(rs.SOURCE_CLIPPED)
                t0 = min(float(eps[o["display"]]["t_start"]) for o in owned)
                t1 = max(float(eps[o["display"]]["t_end"]) for o in owned)
                occ = {"id": sid, "index": 0, "included": True, "t_start": t0, "t_end": t1, "order_t": t0,
                       "slot_id": run["slot_id"], "staff_top_y_crop": float(eps[ref]["staff_top_y"]), "staff_gap_px": gap,
                       "episode_ids": [o["display"] for o in owned], "main_episode_id": owned[0]["display"],
                       "observations": [{"obs_id": m["obs_id"], "region_id": m["region_id"], "episode_id": m["episode_id"]} for m in members],
                       "layout": "jump_view", "first_display": chunk_no == 0, "terminal_display": False,
                       "issues": ["NUMBER_STEP_UNRESOLVED"] if any(
                           eps[o["display"]].get("number_step_unresolved") for o in owned) else [],
                       "jump": {"run": ri, "chain": ci, "chunk": k}}
                results.append((occ, rec))
                chunk_no += 1
        logger(f"jump: run {ri + 1}: {len(run['panorama_chains'])} chains, {chunk_no} strips, "
               f"clef copy {'yes' if clef else 'no (' + str(clef_info.get('reason')) + ')'}")
    return results


# --------------------------------------------------------------------------- coverage of leftover intervals

COVERAGE_VERSION = "jump_coverage-5"  # 5: panorama overlap conflicts are unresolved (Codex J1)
# Kept apart from CONFIG (whose hash is frozen in JUMP_FREEZE.md): decides only how a leftover
# interval is accounted for, never what a run or a strip becomes.
COVERAGE_CONFIG: Dict[str, Any] = {
    # Every ink component (full display height, original composite; positively identified staff
    # scaffold and screen-fixed pixels removed, coverage_ink) that
    # reaches a column no exported strip shows must be explained, one by one; no aggregate
    # ink allowance. Explanations with positive evidence only:
    # * measured staff-line scaffold (staff_scaffold): rows within this many staff spaces of a
    #   tracker staff row whose long (>= min_len) thin (<= max, at least 2 px) horizontal runs
    #   cover >= staff_line_min_frac of the display width and >= staff_line_rel_frac of the
    #   line's best row; removed before accounting, and a remaining component is a staff-line
    #   remnant only when it lies on those measured rows (or the 1-px fringe of the removed
    #   scaffold in its column) and touches that scaffold (never by proximity or shape alone);
    "staff_remnant_max_gaps": 0.25,
    "staff_remnant_min_len_gaps": 2.0,
    "staff_remnant_tol_gaps": 0.35,
    "staff_line_min_frac": 0.25,
    "staff_line_rel_frac": 0.5,
    # * a speckle: at most this many pixels (no notation symbol is this small)
    "speckle_max_px": 2,
    # evidence listing cap (unexplained components per display)
    "evidence_components": 12,
}
STATUS_RANK = {"non_score": 0, "redundant": 1, "recovered": 2, "unresolved": 3}


def _link_dx(s: Dict[str, Any]) -> Optional[int]:
    """Offset of a registered seam (verified, any shift, or resolved); None when unknown."""
    if s.get("user_rejected"):
        return None
    if s.get("verified") and s.get("dx") is not None:
        return int(s["dx"])
    res = s.get("resolution") or {}
    if res.get("status") == "resolved":
        return int(res["dx"])
    return None


def _worst(statuses: Sequence[str]) -> str:
    return max(statuses, key=lambda x: STATUS_RANK[x]) if statuses else "non_score"


def _display_width(ep: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]], composites: Optional[Dict[str, np.ndarray]]) -> int:
    if composites and ep["id"] in composites:
        return int(composites[ep["id"]].shape[1])
    obs, _reg = _mid_region(ep, obs_by)
    return int((obs.get("crop_size") or [0, 0])[0] or 0)


def exported_reference(systems: Sequence[Dict[str, Any]], strips: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """What the automatic chart actually exports, after occurrence selection and strip building:
    the included systems whose strip was written. ``page``: page display id -> [x0, x1) crop
    columns its system's strip shows (``box_crop``); ``chains``: [run, chain] of every jump-view
    panorama chain with a written strip; ``overlap_conflicts``: display content an exported
    panorama strip discards (``panorama_preservation``; shown only by an unchecked alternate).
    Excluded (short, listed) systems, hidden fragments and unchecked alternates are not exported."""
    page: Dict[str, List[int]] = {}
    chains: List[List[int]] = []
    ids: List[str] = []
    conflicts: List[Dict[str, Any]] = []
    for s in systems:
        rec = strips.get(s["id"])
        if not s.get("included") or rec is None or not rec.get("path") or not Path(rec["path"]).is_file():
            continue
        ids.append(s["id"])
        if s.get("layout") == "jump_view":
            j = s.get("jump") or {}
            key = [int(j.get("run", -1)), int(j.get("chain", -1))]
            if key not in chains:
                chains.append(key)
            for c in ((rec.get("jump") or {}).get("preservation") or {}).get("conflicts") or []:
                conflicts.append({"system": s["id"], "display": c["display"], "box_crop": c["box_crop"],
                                  "alternate": c.get("alternate"), "owner": c.get("owner")})
            continue
        box = rec.get("box_crop") or [0, 0, 0, 0]
        shown = {o["episode_id"] for o in s.get("observations") or []} or set(s.get("episode_ids") or [])
        for e in shown:
            lo, hi = page.get(e, [int(box[0]), int(box[2])])
            page[e] = [min(lo, int(box[0])), max(hi, int(box[2]))]
    return {"systems": ids, "page": page, "chains": sorted(chains), "overlap_conflicts": conflicts}


def _runs_along(mask: np.ndarray, axis: int) -> np.ndarray:
    """Length of the run of True cells (along ``axis``) each True cell belongs to; 0 elsewhere."""
    m = mask if axis == 0 else mask.T
    n = m.shape[0]
    fwd = np.zeros(m.shape, np.int32)
    bwd = np.zeros(m.shape, np.int32)
    run = np.zeros(m.shape[1], np.int32)
    for i in range(n):
        run = np.where(m[i], run + 1, 0)
        fwd[i] = run
    run = np.zeros(m.shape[1], np.int32)
    for i in range(n - 1, -1, -1):
        run = np.where(m[i], run + 1, 0)
        bwd[i] = run
    out = np.where(m, fwd + bwd - 1, 0)
    return out if axis == 0 else out.T


def staff_scaffold(comp: np.ndarray, gap: float, staff_y: Sequence[float], lvl: float, ccfg: Dict[str, Any]
                   ) -> Dict[str, Any]:
    """Measured staff-line scaffold of a display (no proximity excuse). For each tracker staff row,
    the rows within ``staff_remnant_tol_gaps`` of it are searched; a row is a *measured line row*
    when its long horizontal ink runs (>= ``staff_remnant_min_len_gaps``) cover at least
    ``staff_line_min_frac`` of the display width and at least ``staff_line_rel_frac`` of the best
    row of that staff line (a tilted or thick line spreads over a few such rows; a short stroke
    near the line covers a few percent of the width and is never one). A scaffold pixel lies on
    a measured line row, in such a long run, and in a vertical ink run no thicker than the
    measured line (median vertical run of the line's long runs, + 1 px): a symbol that crosses
    or touches a staff line makes the vertical run longer, so its pixels on the line are kept.
    Returns {"ink": composite ink mask, "scaffold": removed pixels, "line_rows": measured rows
    per staff row (provenance)}."""
    norm, _inv = sd.normalize_polarity(comp)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm
    keep = cv2.dilate(page_diff._ink_mask(gray), np.ones((3, 3), np.uint8)) > 0
    ink = keep & ((255 - gray.astype(np.int16)) > lvl)
    scaffold = np.zeros_like(ink)
    line_rows: List[List[int]] = []
    if not staff_y or not ink.any():
        return {"ink": ink, "scaffold": scaffold, "line_rows": line_rows}
    vrun = _runs_along(ink, 0)
    hrun = _runs_along(ink, 1)
    h, w = ink.shape
    reach = max(1, int(np.ceil(ccfg["staff_remnant_tol_gaps"] * gap)))
    min_len = ccfg["staff_remnant_min_len_gaps"] * gap
    cap = max(2.0, ccfg["staff_remnant_max_gaps"] * gap)
    long_all = (hrun >= min_len) & ink
    count = long_all.sum(axis=1)
    for y in staff_y:
        yc = int(round(float(y)))
        r0, r1 = max(0, yc - reach), min(h, yc + reach + 1)
        if r1 <= r0:
            line_rows.append([])
            continue
        best = int(count[r0:r1].max())
        if best < ccfg["staff_line_min_frac"] * w:
            line_rows.append([])
            continue
        rows = [r for r in range(r0, r1) if count[r] >= max(ccfg["staff_line_min_frac"] * w, ccfg["staff_line_rel_frac"] * best)]
        line_rows.append(rows)
        long_ = long_all[rows]
        thick = min(cap, float(np.median(vrun[rows][long_])) + 1.0)
        scaffold[rows] |= long_ & (vrun[rows] <= thick)
    return {"ink": ink, "scaffold": scaffold, "line_rows": line_rows}


def coverage_ink(comp: np.ndarray, gap: float, staff_y: Sequence[float], lvl: float, ccfg: Dict[str, Any]
                 ) -> Tuple[np.ndarray, int]:
    """Ink of a display for preservation accounting: the original normalized composite (no band
    around the staff rows is blanked, unlike ``features``), minus only the measured staff-line
    scaffold (``staff_scaffold``). Returns (bool mask, scaffold pixels removed)."""
    sc = staff_scaffold(comp, gap, staff_y, lvl, ccfg)
    return sc["ink"] & ~sc["scaffold"], int(sc["scaffold"].sum())


def _uncovered_components(ink_mask: np.ndarray, miss: np.ndarray, scaffold: np.ndarray, line_rows: Sequence[Sequence[int]],
                          gap: float, ccfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, Dict[str, int]]:
    """Every ink component (8-connected, full height) of ``ink_mask`` (``coverage_ink``) with a
    pixel in a ``miss`` column, each explained or not. Explanations need positive evidence of
    their own, never proximity or shape alone: a speckle (at most ``speckle_max_px``), or a
    staff-line remnant - no taller than the line thickness cap, every pixel on a measured line
    row (``staff_scaffold``) or directly above / below a removed scaffold pixel of its column
    (the line's partial edge row), and touching that scaffold. An isolated stroke near a staff
    line (not touching it) stays unexplained. Returns (unexplained components, their pixels in missing columns, explained counts
    by reason)."""
    ink = ink_mask.astype(np.uint8)
    if not miss.any() or not ink[:, miss].any():
        return [], 0, {}
    n, lab, stats, _c = cv2.connectedComponentsWithStats(ink, connectivity=8)
    near_scaffold = cv2.dilate(scaffold.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    thin = max(2.0, ccfg["staff_remnant_max_gaps"] * gap)
    bad: List[Dict[str, Any]] = []
    bad_px = 0
    explained: Dict[str, int] = {}
    hit_labels = np.unique(lab[:, miss])
    for i in hit_labels:
        if i == 0:
            continue
        x, y, w, h, area = (int(v) for v in stats[i])
        pix = lab[y:y + h, x:x + w] == i
        in_miss = int(pix[:, miss[x:x + w]].sum())
        if in_miss == 0:
            continue
        reason = None
        if area <= int(ccfg["speckle_max_px"]):
            reason = "speckle"
        else:
            # Proximity / a one-pixel fringe does not explain a thin mark.
            # Only pixels actually drawn by the measured scaffold are exempt.
            on_scaffold_line = scaffold[y:y + h, x:x + w]
            if h <= thin and not (pix & ~on_scaffold_line).any() and (pix & near_scaffold[y:y + h, x:x + w]).any():
                reason = "staff_line_remnant"
        if reason:
            explained[reason] = explained.get(reason, 0) + 1
            continue
        bad_px += in_miss
        bad.append({"bbox": [x, y, x + w, y + h], "area_px": area, "uncovered_px": in_miss})
    bad.sort(key=lambda c: -c["uncovered_px"])
    return bad, bad_px, explained


def account_coverage(tracking: Dict[str, Any], manifest: Dict[str, Any], jump: Dict[str, Any], *,
                     exported: Dict[str, Any],
                     composites: Optional[Dict[str, np.ndarray]] = None, covered: Optional[Dict[str, np.ndarray]] = None,
                     fixed: Optional[Dict[str, np.ndarray]] = None, cfg: Optional[Dict[str, Any]] = None,
                     ccfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every tracker interval the exported jump-view runs leave unsupported, accounted for on
    its own, against what the chart actually exports (``exported``: ``exported_reference``,
    built after occurrence selection and strip building). A display counts as output only
    when an included system's strip shows it (a page display) or its panorama chain was built
    into strips (a run display); an excluded or hidden display is not output.

    * ``non_score``: no display and no score rows in the interval (intro, outro, a cut);
    * ``redundant``: everything it shows is exported, and identity and order follow from the
      source: frames of a jump transition between two displays (tracker), or a display
      registered seam by seam (a verified no-shift seam - the same view - included, never on its
      own) to the next exported display before or after it, against the columns the exported
      strips show; every ink component of the original composite (only positively identified
      staff scaffold and screen-fixed pixels removed, ``coverage_ink``) reaching a column outside
      them must be explained (staff-line remnant, speckle), and no unrecovered overlay may lie there;
    * ``recovered``: unique content made into strips by a supported method (a secondary
      jump-view run whose chains were all exported, listed with its own interval);
    * ``unresolved``: possibly unique content whose identity or order is not established.

    Appearance alone never makes a display redundant (a repeated groove looks the same): only
    a registration to exported content does. ``status`` is ``incomplete`` when any interval is
    unresolved; ``unresolved`` lists, per unresolved interval, the [start, end] seconds its
    unresolved displays occupy (``unresolved_span``)."""
    cfg = cfg or jump.get("config") or CONFIG
    ccfg = ccfg or COVERAGE_CONFIG
    composites = composites if composites is not None else jump.get("_composites")
    covered = covered if covered is not None else jump.get("_covered")
    fixed = fixed if fixed is not None else jump.get("_fixed")
    obs_by = {o["id"]: o for o in manifest.get("observations", [])}
    eps_all = sorted(tracking.get("episodes", []), key=lambda e: (e["t_start"], e["id"]))
    ep_by = {e["id"]: e for e in eps_all}
    runs = jump.get("runs") or []
    seams = jump.get("seams") or []
    panel_of = {sl["slot_id"]: int((sl.get("panel") or {}).get("right") or 0) for sl in jump.get("slots", [])}
    built = {(int(r), int(c)) for r, c in exported.get("chains") or []}
    page_spans = {d: (int(v[0]), int(v[1])) for d, v in (exported.get("page") or {}).items() if d in ep_by}
    # output frames: an exported chain's panorama (display -> x offset in it) or a page display
    # alone (the columns its strip shows)
    seam_of = {(s["a"], s["b"]): s for s in seams}
    frame_of: Dict[str, Tuple[str, int]] = {}
    frame_span: Dict[str, Tuple[int, int]] = {}
    run_chains: Dict[int, List[bool]] = {}
    for ri, r in enumerate(runs):
        for ci, ch in enumerate(r.get("panorama_chains") or [{"displays": c} for c in r["chains"]]):
            run_chains.setdefault(ri, []).append((ri, ci) in built)
            if (ri, ci) not in built:
                continue
            fid = f"run{ri + 1}-chain{ci + 1}"
            x = 0
            disp = ch["displays"]
            w_max = 0
            for k, d in enumerate(disp):
                if k:
                    off = seam_offset(seam_of[(disp[k - 1], d)])
                    x += off[0] if off else 0
                frame_of[d] = (fid, x)
                w_max = max(w_max, x + _display_width(ep_by[d], obs_by, composites))
            frame_span[fid] = (0, w_max)
    for d, (lo, hi) in page_spans.items():
        if d not in frame_of:
            frame_of[d] = (f"page:{d}", 0)
            frame_span[f"page:{d}"] = (lo, hi)
    output = set(frame_of)
    exported_runs = [ri for ri, flags in run_chains.items() if flags and all(flags)]
    by_a = {s["a"]: s for s in seams}
    by_b = {s["b"]: s for s in seams}
    skipped_in = {x: s for s in seams for x in s.get("skipped_episodes") or []}

    def frames_for(d: str) -> List[Dict[str, Any]]:
        """Exported frames that registered seams place display d in (walking over displays that
        are not exported, excluded ones included)."""
        out = []
        for direction in ("back", "fwd"):
            cur, pos, path, seen = d, 0, [], {d}
            while True:
                s = (by_b if direction == "back" else by_a).get(cur)
                if s is None:
                    break
                dx = _link_dx(s)
                if dx is None:
                    break
                nxt = s["a"] if direction == "back" else s["b"]
                if nxt in seen:
                    break
                seen.add(nxt)
                # back: cur col u = nxt col u + dx; fwd: nxt col u = cur col u + dx
                pos = pos + dx if direction == "back" else pos - dx
                path.append(s["id"])
                if nxt in frame_of:
                    fid, x = frame_of[nxt]
                    out.append({"frame": fid, "via": nxt, "x": int(x + pos), "seams": list(path)})
                    break
                cur = nxt
        return out

    def confirmed_status(d: str) -> Tuple[str, Dict[str, Any]]:
        ep = ep_by[d]
        fr = frames_for(d)
        links = [{"seam": s["id"], "status": s.get("status"), "kind": s.get("kind"), "reasons": s.get("reasons")}
                 for s in (by_b.get(d), by_a.get(d)) if s is not None]
        if not fr:
            return "unresolved", {"rule": "no_registered_link_to_output", "links": links}
        comp = (composites or {}).get(d)
        if comp is None:
            return "unresolved", {"rule": "display_not_available", "frames": fr}
        w = int(comp.shape[1])
        panel = panel_of.get(str(ep.get("slot_id")), 0)
        cov = np.zeros(w, dtype=bool)
        cov[:panel] = True  # the screen-fixed panel is not score content of this display
        for f in fr:
            lo, hi = frame_span[f["frame"]]
            u0, u1 = max(0, lo - f["x"]), min(w, hi - f["x"])
            if u1 > u0:
                cov[u0:u1] = True
        gap = float(ep["staff_gap_px"])
        staff_y = _episode_staff_y(ep, obs_by)
        # accounting on the original composite: only positively identified staff scaffold (and the
        # slot's screen-fixed pixels) is left out, never whole staff-row bands (features() does
        # that for registration only)
        sc = staff_scaffold(comp, gap, staff_y, cfg["ink_level"], ccfg)
        ink, scaffold_px = sc["ink"] & ~sc["scaffold"], int(sc["scaffold"].sum())
        fx = (fixed or {}).get(str(ep.get("slot_id")))
        if fx is not None and fx.shape == ink.shape:
            ink = ink & ~fx.astype(bool)
        miss = ~cov
        bad, bad_px, explained = _uncovered_components(ink, miss, sc["scaffold"], sc["line_rows"], gap, ccfg)
        overlay = int(((covered or {}).get(d, np.zeros(w, dtype=bool))[:w] & miss).sum())
        cols = np.flatnonzero(miss)
        ev = {"frames": fr, "uncovered_columns": [int(cols[0]), int(cols[-1]) + 1] if cols.size else None,
              "uncovered_ink_px": int(bad_px), "unexplained_components": len(bad),
              "unexplained": bad[:int(ccfg["evidence_components"])], "explained_components": explained,
              "uncovered_overlay_columns": overlay, "staff_scaffold_px": scaffold_px,
              "staff_line_rows": [list(map(int, r)) for r in sc["line_rows"]]}
        if overlay or bad:
            return "unresolved", dict(ev, rule="unique_columns_not_in_output")
        return "redundant", dict(ev, rule="registered_to_exported_output")

    memo: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    def status_of(d: str, visiting: frozenset = frozenset()) -> Tuple[str, Dict[str, Any]]:
        if d in memo:
            return memo[d]
        if d in visiting:
            return "unresolved", {"rule": "cycle"}
        e = ep_by[d]
        if e.get("confirmed"):
            # A verified no-shift link (the same view) is a registration like any other: it never
            # certifies redundancy by itself. The display is accounted for against the exported
            # crops the registered seams place it in (frames_for walks no-shift links too, also
            # through displays that are not output): exported span and every uncovered component.
            st, ev = confirmed_status(d)
            same = next((s for s in (by_b.get(d), by_a.get(d)) if s is not None and s.get("kind") == "no_shift"
                         and s.get("verified")), None)
            if same is not None:
                other = same["a"] if same["b"] == d else same["b"]
                ev = dict(ev, same_view={"as": other, "seam": same["id"], "as_exported": other in output,
                                         "residual": same.get("residual"), "ratio": same.get("ratio")})
                if st == "redundant":
                    ev = dict(ev, rule="same_view", **{"as": other, "as_exported": other in output, "seam": same["id"]})
            memo[d] = (st, ev)
            return memo[d]
        s = skipped_in.get(d)
        if s is None or float(s.get("transition_sec") or 0.0) > cfg["transition_max_sec"]:
            memo[d] = ("unresolved", {"rule": "unconfirmed_display"})
            return memo[d]
        ends = [x for x in (s["a"], s["b"]) if x not in output]
        worst = _worst([status_of(x, visiting | {d})[0] for x in ends] + ["redundant"])
        memo[d] = (worst, {"rule": "transition_frames", "between": [s["a"], s["b"]], "seam": s["id"],
                           "endpoints_not_in_output": ends})
        return memo[d]

    def piece_kind(a: float, b: float) -> str:
        still = sum(max(0.0, min(b, float(e["t_end"])) - max(a, float(e["t_start"])))
                    for e in eps_all if e.get("confirmed") and float(e["t_end"]) - float(e["t_start"]) >= cfg["dwell_min_sec"])
        return "smooth_scroll" if still < 0.5 * (b - a) else "horizontal_unclassified"

    intervals: List[Dict[str, Any]] = []
    cover = [(float(runs[ri]["start"]), float(runs[ri]["end"])) for ri in exported_runs]
    for iv in tracking.get("layout_intervals", []):
        if iv.get("supported", True):
            continue
        for a, b in _subtract((float(iv["start"]), float(iv["end"])), cover):
            inside = [e for e in eps_all if float(e["t_start"]) < b and float(e["t_end"]) > a]
            left = [e["id"] for e in inside if e["id"] not in output]
            shown = [e["id"] for e in inside if e["id"] in output]
            status = {x: status_of(x) for x in left}
            if left:
                st = _worst([status[x][0] for x in left])
                ev: Dict[str, Any] = {"displays": [{"episode": x, "t": [round(float(ep_by[x]["t_start"]), 3), round(float(ep_by[x]["t_end"]), 3)],
                                                    "status": status[x][0], **status[x][1]} for x in left]}
                if shown:
                    ev["shown_by_output"] = shown
            elif shown:
                st, ev = "redundant", {"rule": "shown_by_output", "episodes": shown}
            else:
                obs = [o for o in manifest.get("observations", []) if a <= float(o.get("t_sec", -1.0)) <= b]
                rows = sum(1 for o in obs if o.get("system_regions"))
                if rows:
                    st, ev = "unresolved", {"rule": "score_rows_without_display", "observations": len(obs), "with_score_rows": rows}
                else:
                    st, ev = "non_score", {"rule": "no_score_rows", "observations": len(obs)}
            entry = {"start": round(a, 3), "end": round(b, 3), "kind": piece_kind(a, b),
                     "tracking_kind": iv.get("kind"), "status": st, "evidence": ev}
            bad = [x for x in left if status[x][0] == "unresolved"]
            if st == "unresolved":
                # the stretch of the interval the unresolved displays occupy (the whole interval
                # when no display is unresolved: score rows without a display)
                entry["unresolved_span"] = [round(max(a, min(float(ep_by[x]["t_start"]) for x in bad)), 3),
                                            round(min(b, max(float(ep_by[x]["t_end"]) for x in bad)), 3)] if bad else [round(a, 3), round(b, 3)]
            intervals.append(entry)
    for ri in exported_runs:
        r = runs[ri]
        if r.get("secondary"):
            intervals.append({"start": round(float(r["start"]), 3), "end": round(float(r["end"]), 3), "kind": "jump_view",
                              "tracking_kind": None, "status": "recovered",
                              "evidence": {"rule": "secondary_jump_view_run", "run": ri, "seams": r["seams"],
                                           "verified_seams": r["verified_seams"], "resolved_seam_ids": r.get("resolved_seam_ids", [])}})
    # display content an exported panorama discards in an overlap (Codex J1): the strips' owner
    # map is complete, but the content is shown only by an unchecked alternate - never certified
    conf_by: Dict[str, List[Dict[str, Any]]] = {}
    for c in exported.get("overlap_conflicts") or []:
        if c["display"] in ep_by:
            conf_by.setdefault(c["display"], []).append(c)
    for d, cs in conf_by.items():
        a, b = round(float(ep_by[d]["t_start"]), 3), round(float(ep_by[d]["t_end"]), 3)
        intervals.append({"start": a, "end": b, "kind": "jump_view", "tracking_kind": None, "status": "unresolved",
                          "evidence": {"rule": "panorama_overlap_content_conflict", "display": d, "components": len(cs),
                                       "conflicts": cs[:int(ccfg["evidence_components"])]},
                          "unresolved_span": [a, b]})
    intervals.sort(key=lambda x: (x["start"], x["end"]))
    unresolved = [list(x["unresolved_span"]) for x in intervals if x["status"] == "unresolved"]
    reference = {"basis": "included_systems_with_written_strips", "systems": len(exported.get("systems") or []),
                 "page_displays": len(page_spans), "chains": sorted([list(k) for k in built]),
                 "runs_exported": exported_runs, "runs_not_exported": [ri for ri in range(len(runs)) if ri not in exported_runs]}
    return {"version": COVERAGE_VERSION, "config": dict(ccfg), "status": "incomplete" if unresolved else "complete",
            "reference": reference, "intervals": intervals, "unresolved": unresolved,
            "counts": {k: sum(1 for x in intervals if x["status"] == k) for k in STATUS_RANK}}


# --------------------------------------------------------------------------- entry point


def analyse_jumps(tracking: Dict[str, Any], manifest: Dict[str, Any], load: ImageLoader, *,
                  out_path: Optional[Path] = None, cfg: Optional[Dict[str, Any]] = None,
                  evidence_dir: Optional[Path] = None, ledger: bool = False,
                  logger: Callable[[str], None] = lambda _m: None, keep_composites: bool = False,
                  checkpoint: Callable[[], None] = lambda: None) -> Dict[str, Any]:
    """Gate -> register_seams (with seam resolution) -> classify_runs -> panorama chains.
    JSON-serialisable result (written to ``out_path`` when given). ``keep_composites``: the
    overlay-free display composites and their unrecovered overlay columns are returned under
    ``_composites`` / ``_covered`` (needed by ``build_jump_systems``)."""
    cfg = cfg or CONFIG
    t0 = time.time()
    g = gate(tracking, manifest, load, cfg=cfg)
    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "version": JUMP_VERSION, "config": dict(cfg), "config_hash": config_hash(cfg),
        "video_id": manifest.get("video_id"), "gate": g, "slots": [], "seams": [], "runs": [], "intervals": [],
    }
    composites = covered = fixed = None
    if g["attempt"]:
        reg = register_seams(tracking, manifest, load, cfg=cfg, logger=logger, keep_composites=True,
                             checkpoint=checkpoint, ledger=ledger, evidence_dir=evidence_dir)
        composites = reg.pop("_composites", None)
        covered = reg.pop("_covered", None)
        fixed = reg.pop("_fixed", None)
        cls = classify_runs(reg["seams"], tracking, cfg=cfg)
        for run in cls["runs"]:
            run["panorama_chains"] = panorama_chains(run, reg["seams"])
            run["resolved_seam_ids"] = [s["id"] for s in reg["seams"] if s.get("status") == "resolved"
                                        and s["id"] in {x for x in run["unverified_seam_ids"]}]
            run["still_unverified_seam_ids"] = [c["break_after"] for c in run["panorama_chains"] if c["break_after"]]
        result.update(slots=reg["slots"], seams=reg["seams"], runs=cls["runs"], intervals=cls["intervals"])
        included = {d for r in cls["runs"] for c in r["panorama_chains"] for d in c["displays"]}
        if ledger:
            result["ledger_displays"] = {d: fragment for d, fragment in reg["ledger_displays"].items() if d in included}
    else:
        result["intervals"] = _label_intervals(tracking, [], cfg)
    seams = result["seams"]
    result["summary"] = {
        "seams": len(seams), "verified": sum(1 for s in seams if s["verified"]),
        "jump_seams": sum(1 for s in seams if s["kind"] == "jump"),
        "unverified": [{"id": s["id"], "reasons": s["reasons"]} for s in seams if not s["verified"]],
        "resolved": [{"id": s["id"], "dx": s["resolution"]["dx"], "evidence": s["resolution"]["evidence"]}
                     for s in seams if s.get("status") == "resolved"],
        "still_unverified": [{"id": s["id"], "reason": (s.get("resolution") or {}).get("reason") or ",".join(s["reasons"])}
                             for s in seams if s.get("status", "unverified") == "unverified"],
        "jump_view_runs": len(result["runs"]),
        "jump_view_seconds": round(sum(r["end"] - r["start"] for r in result["runs"]), 2),
    }
    result["seconds"] = round(time.time() - t0, 2)
    if out_path is not None:
        write_json(result, Path(out_path))
    if keep_composites:
        result["_composites"] = composites
        result["_covered"] = covered
        result["_fixed"] = fixed
    return result


def write_json(result: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, ensure_ascii=False, indent=1,
                              default=lambda o: o.tolist() if hasattr(o, "tolist") else None))
    tmp.replace(path)
