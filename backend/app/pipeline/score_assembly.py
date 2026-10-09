"""Score locations from display episodes, with stored evidence for every merge.

Design reference: docs/reflow/DESIGN_astra.md section 1 (entities, evidence
families, contradictions, decision procedure, candidate ranking, printed-number
matching without OCR, written order) and section 5 (assembly JSON shape).

Two policies (Phase 0 "first experiment"):

* ``conservative`` - every display episode is a provisional location except
  continuous-geometry identities: a consistent multi-row page translation, a
  preview row promoted to the active row, or a row split only by a playhead
  reset while the other rows of its page view stayed on screen unchanged. Appearance-matched pairs are only
  nominated (``POSSIBLE_REVISIT``); nothing nonlocal is merged.
* ``evidence`` - additionally applies the section-1 gates:
  - a reliable *different* printed number/text patch on both sides is a hard
    contradiction -> the pair is resolved as different locations;
  - a nonlocal revisit is merged only with identifier match + independently
    anchored context (both neighbouring relations already joined by geometry /
    motion / user evidence, never by patch similarity) + compatible appearance;
    two page views whose >= 3 rows all match at the same coordinates are only a
    ranked review suggestion (appearance, not a verified page map);
  - an unexplained local slot transition (row moved to another slot within
    1.5 s, same full window) is merged as local continuity;
  - everything else stays ``POSSIBLE_REVISIT``.
  Candidate ranking ``6G + 4I + 3C + A + M`` (>= 8, margin >= 3) orders
  competing automatic choices.

Number patches are matched visually (``number_value`` is always null; no OCR).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import system_detect
from app.pipeline.system_tracking import ImageLoader, clean_content, comparable_windows, compare_content, region_window, window_extent

ASSEMBLY_VERSION = "score_assembly-2"
POLICIES = ("conservative", "evidence")
# Merge bases that anchor a relation without appearance or identifier-patch similarity;
# only these can supply context (C) for an identifier-supported revisit.
INDEPENDENT_ANCHOR_BASES = ("page_translation", "preview_promotion", "unchanged_page_view_across_reset", "local_slot_transition", "user_decision")

PATCH_H = 24
PATCH_MATCH = 0.97
PATCH_DIFFERENT = 0.85
PATCH_MARGIN = 0.05
PATCH_MIN_OBS = 3


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _UF:
    def __init__(self, items: Sequence[str]):
        self.p = {i: i for i in items}

    def find(self, a: str) -> str:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: str, b: str) -> str:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        # keep the earlier root (ids sort by time)
        keep, drop = sorted([ra, rb])
        self.p[drop] = keep
        return keep


def _obs_index(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {o["id"]: o for o in manifest["observations"]}


def _region(obs: Dict[str, Any], region_id: str) -> Dict[str, Any]:
    return next(r for r in obs["system_regions"] if r["region_id"] == region_id)


def number_patch(crop_norm: np.ndarray, region: Dict[str, Any]) -> Optional[np.ndarray]:
    """A compact printed-number-like cluster at the start of the staff, normalized to PATCH_H rows.

    Only a measure-number style label qualifies (no OCR, the value stays unknown):
    * search box x in [staff_x0 - 1g, staff_x0 + 3g], y in [top - 3g, top - 0.4g];
      components are found on a taller window so anything that continues
      down to the staff (a notehead with its stem, a clef) is rejected;
    * 1-3 components, each 0.45-1.6 gaps tall and at most 1.1 gaps wide,
      tops aligned within 0.35 gap, heights within 35% of each other,
      cluster at most 3.5 gaps wide, starting within 1.5 gaps of the staff start;
    * nothing may touch the crop top (a clipped label is not reliable).
    Anything else (cymbal heads, accents, open-hat circles, boxed section
    letters, text words) returns None. ``crop_norm`` is the polarity-normalized
    observation crop (not the cleaned one: thin label strokes must survive).
    """
    g = float(region["staff_gap_px"])
    top = float(region["staff_y"][0])
    sx0 = float(region["staff_x"][0])
    x0 = int(max(0, sx0 - 1.0 * g))
    x1 = int(min(crop_norm.shape[1], sx0 + 3.0 * g))
    y0 = int(max(0, top - 3.0 * g))
    y1 = int(max(0, top - 0.4 * g))
    y1_ext = int(min(crop_norm.shape[0], top + 0.5 * g))
    if y1 - y0 < 4 or x1 - x0 < 4:
        return None
    gray_ext = cv2.cvtColor(crop_norm[y0:y1_ext, x0:x1], cv2.COLOR_BGR2GRAY)
    ink = (gray_ext < 150).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    comps = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 3:
            continue
        if y >= (y1 - y0) or (y0 + y + h) > top - 0.3 * g:
            continue  # below the label window or reaching toward the staff: notation, not a label
        if y0 + y <= 0:
            return None
        comps.append((int(x), int(y), int(w), int(h)))
    if not comps or len(comps) > 3:
        return None
    for x, y, w, h in comps:
        if not (0.45 * g <= h <= 1.6 * g) or w > 1.1 * g:
            return None
    tops = [c[1] for c in comps]
    hs = [c[3] for c in comps]
    if max(tops) - min(tops) > 0.35 * g or max(hs) > 1.35 * min(hs):
        return None
    cx0 = min(c[0] for c in comps)
    cx1 = max(c[0] + c[2] for c in comps)
    if cx1 - cx0 > 3.5 * g or (x0 + cx0) > sx0 + 1.5 * g:
        return None
    cy0 = min(tops)
    cy1 = max(c[1] + c[3] for c in comps)
    pa = gray_ext[cy0:cy1, cx0:cx1]
    if pa.shape[0] < 3 or pa.shape[1] < 2:
        return None
    s = PATCH_H / float(pa.shape[0])
    w = max(2, int(round(pa.shape[1] * s)))
    return cv2.resize(pa, (w, PATCH_H), interpolation=cv2.INTER_AREA).astype(np.float32)


def patch_similarity(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[float]:
    """Normalized correlation of two patches (best over +-2 px shifts); None if either is missing.
    Patches whose widths differ by more than 25% score 0."""
    if a is None or b is None:
        return None
    if abs(a.shape[1] - b.shape[1]) > 0.25 * max(a.shape[1], b.shape[1]):
        return 0.0
    w = max(a.shape[1], b.shape[1])
    A = cv2.copyMakeBorder(a, 2, 2, 2, 2 + w - a.shape[1], cv2.BORDER_CONSTANT, value=255)
    B = cv2.copyMakeBorder(b, 0, 0, 0, w - b.shape[1], cv2.BORDER_CONSTANT, value=255)
    if float(B.std()) < 1e-3 or float(A.std()) < 1e-3:
        return 0.0
    r = cv2.matchTemplate(A, B, cv2.TM_CCOEFF_NORMED)
    return float(r.max())


# --------------------------------------------------------------------------- #
# Episode descriptors
# --------------------------------------------------------------------------- #


def describe_episodes(tracking: Dict[str, Any], manifest: Dict[str, Any], load_image: ImageLoader,
                      *, max_patch_obs: int = 5) -> Dict[str, Dict[str, Any]]:
    obs_by = _obs_index(manifest)
    out = {}
    for ep in tracking["episodes"]:
        n = ep["n_obs"]
        k = n // 2
        o = obs_by[ep["observation_ids"][k]]
        r = _region(o, ep["region_ids"][k])
        clean = clean_content(load_image(o))
        window = region_window(clean, r)
        idx = sorted(set(np.linspace(0, n - 1, min(n, max_patch_obs)).round().astype(int).tolist()))
        patches = []
        for i in idx:
            oi = obs_by[ep["observation_ids"][i]]
            ri = _region(oi, ep["region_ids"][i])
            patches.append(number_patch(system_detect.normalize_polarity(load_image(oi))[0], ri))
        valid = [p for p in patches if p is not None]
        reliable = None
        if len(valid) >= min(PATCH_MIN_OBS, len(patches)) and len(valid) >= 1:
            ref = valid[len(valid) // 2]
            agree = [p for p in valid if (patch_similarity(ref, p) or 0) >= 0.9]
            if len(agree) >= PATCH_MIN_OBS:
                reliable = ref
        tops = bots = 0
        for oid, rid in zip(ep["observation_ids"], ep["region_ids"]):
            iss = _region(obs_by[oid], rid).get("issues", [])
            tops += "envelope_at_top_edge" in iss
            bots += "envelope_at_bottom_edge" in iss
        env = r["envelope_bbox"]
        g = float(r["staff_gap_px"])
        h, w = clean.shape[:2]
        rect = [int(max(0, env[0] - 0.5 * g)), int(max(r["bbox"][1], env[1] - 0.75 * g)),
                int(min(w, env[2] + 0.5 * g)), int(min(r["bbox"][3], env[3] + 0.75 * g))]
        out[ep["id"]] = {
            "episode": ep,
            "rep_obs_id": o["id"],
            "rep_region_id": r["region_id"],
            "rep_t": o["t_sec"],
            "window": window,
            "extent": window_extent(r),
            "gap": g,
            "staff_x": r["staff_x"],
            "staff_top": float(r["staff_y"][0]),
            "patch": reliable,
            "patch_obs": len(valid),
            "output_rect_crop": rect,
            "edge_clipped": {"top": round(tops / max(1, n), 3), "bottom": round(bots / max(1, n), 3)},
        }
    return out


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def assemble_locations(
    tracking: Dict[str, Any],
    manifest: Dict[str, Any],
    load_image: ImageLoader,
    *,
    policy: str = "evidence",
    descriptors: Optional[Dict[str, Dict[str, Any]]] = None,
    logger: Callable[[str], None] = lambda _m: None,
) -> Dict[str, Any]:
    if policy not in POLICIES:
        raise ValueError(policy)
    eps = [e for e in tracking["episodes"] if e.get("layout") != "horizontal_scroll"]
    unsupported = [iv for iv in tracking.get("layout_intervals", []) if not iv.get("supported", True)]
    desc = descriptors if descriptors is not None else describe_episodes({"episodes": eps}, manifest, load_image)
    ep_by = {e["id"]: e for e in eps}
    order_time = sorted(eps, key=lambda e: (e["t_start"], e["staff_top_y"]))
    uf = _UF([e["id"] for e in order_time])
    evidence: List[Dict[str, Any]] = []
    merges: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    def add_ev(family: str, kind: str, episodes: Sequence[str], **metrics) -> str:
        eid = f"ev-{len(evidence) + 1:04d}"
        evidence.append({"id": eid, "family": family, "kind": kind, "episodes": list(episodes), "metrics": metrics,
                         "rule_version": ASSEMBLY_VERSION})
        return eid

    uf_geo = _UF([e["id"] for e in order_time])  # joins made by geometry / motion / user evidence only

    def merge(a: str, b: str, basis: str, ev_ids: List[str]) -> None:
        if basis in INDEPENDENT_ANCHOR_BASES:
            uf_geo.union(a, b)
        if uf.find(a) == uf.find(b):
            return
        uf.union(a, b)
        merges.append({"a": a, "b": b, "basis": basis, "evidence_ids": ev_ids, "automatic": True})

    # 1. continuity links (local geometry / slot transitions)
    for e in eps:
        for lk in e.get("continuity_links", []):
            if lk["from"] not in ep_by:
                continue
            ev = add_ev("G" if lk["kind"] == "page_translation" else "M", lk["kind"], [lk["from"], lk["to"]],
                        dy_px=lk["dy_px"], peer_links=lk.get("peer_links", 0), from_role=lk.get("from_role"), to_role=lk.get("to_role"))
            ev_a = add_ev("A", "full_window_match", [lk["from"], lk["to"]], window="staff-4g..staff+8g")
            if lk["kind"] in ("page_translation", "preview_promotion"):
                merge(lk["from"], lk["to"], lk["kind"], [ev, ev_a])
            elif policy == "evidence":
                merge(lk["from"], lk["to"], "local_slot_transition", [ev, ev_a])
            else:
                candidates.append({"a": lk["from"], "b": lk["to"], "kind": "local_slot_transition", "state": "unresolved",
                                   "issue": "IDENTITY_UNRESOLVED", "evidence_ids": [ev, ev_a]})

    # 1b. a row split only by a playhead reset while other rows of the same page view stayed
    #     on screen unchanged is the same page coordinate (continuous page geometry)
    for e in eps:
        if e["started_by"] != "playhead_reset":
            continue
        prev = [p for p in eps if p["slot_id"] == e["slot_id"] and p["ended_by"] == "playhead_reset"
                and 0 <= e["t_start"] - p["t_end"] <= 1.0]
        if not prev:
            continue
        p = max(prev, key=lambda x: x["t_end"])
        t_reset = (p["t_end"] + e["t_start"]) / 2.0
        steady = [o for o in eps if o["slot_id"] != e["slot_id"] and o["t_start"] < p["t_end"] and o["t_end"] > e["t_start"]]
        if not steady:
            continue
        ev = add_ev("G", "unchanged_page_view_across_reset", [p["id"], e["id"]], t_reset=round(t_reset, 3),
                    steady_rows=[o["id"] for o in steady])
        merge(p["id"], e["id"], "unchanged_page_view_across_reset", [ev])

    # 2. appearance nominations between episodes not already joined
    pair_same: Dict[Tuple[str, str], bool] = {}
    ids = [e["id"] for e in order_time if e["confirmed"]]  # SHORT episodes are not nominated (they are excluded, see below)
    for i, a in enumerate(ids):
        da = desc[a]
        for b in ids[i + 1 :]:
            db = desc[b]
            if abs(da["gap"] - db["gap"]) > 0.08 * da["gap"]:
                continue
            if abs(da["staff_x"][0] - db["staff_x"][0]) > 2 * da["gap"] or abs(da["staff_x"][1] - db["staff_x"][1]) > 2 * da["gap"]:
                continue
            wa, wb = comparable_windows(da["window"], da["extent"], db["window"], db["extent"], da["gap"])
            c = compare_content(wa, wb, da["gap"])
            pair_same[(a, b)] = c.state == "same"
    same_pairs = [(a, b) for (a, b), s in pair_same.items() if s]

    # 2b. short fragments next to another episode of the same slot (partly covered by a page
    #     curl or other transition) that the appearance check does not match: nominate them so
    #     a duplicate can never be silent. Never merged automatically.
    for e in order_time:
        if not e["confirmed"] or (e["t_end"] - e["t_start"]) >= 2.0:
            continue
        for o in order_time:
            if o["id"] == e["id"] or o["slot_id"] != e["slot_id"] or not o["confirmed"]:
                continue
            if 0 <= e["t_start"] - o["t_end"] <= 0.75 or 0 <= o["t_start"] - e["t_end"] <= 0.75:
                a_, b_ = (o["id"], e["id"]) if o["t_start"] < e["t_start"] else (e["id"], o["id"])
                key = (a_, b_)
                if pair_same.get(key):
                    continue  # handled by the appearance nomination below
                ev = add_ev("M", "adjacent_short_fragment", [a_, b_], fragment=e["id"], seconds=round(e["t_end"] - e["t_start"], 3))
                candidates.append({"a": a_, "b": b_, "kind": "adjacent_fragment", "state": "unresolved",
                                   "issue": "IDENTITY_UNRESOLVED", "evidence_ids": [ev]})

    def neighbours(e_id: str) -> Tuple[Optional[str], Optional[str]]:
        e = ep_by[e_id]
        seq = [x for x in order_time if x["slot_id"] == e["slot_id"] and x["confirmed"]] or order_time
        ids_ = [x["id"] for x in seq]
        if e_id not in ids_:
            return None, None
        k = ids_.index(e_id)
        return (ids_[k - 1] if k > 0 else None), (ids_[k + 1] if k + 1 < len(ids_) else None)

    def ident(a: Optional[str], b: Optional[str]) -> Optional[float]:
        if a is None or b is None:
            return None
        return patch_similarity(desc[a]["patch"], desc[b]["patch"])

    all_patches = [(k, d["patch"]) for k, d in desc.items() if d["patch"] is not None]

    def distinctive(a: str, b: str, sim: float) -> bool:
        """No other episode's patch (outside a/b's matching group) comes within PATCH_MARGIN of sim."""
        others = []
        for k, p in all_patches:
            if k in (a, b):
                continue
            s = patch_similarity(desc[a]["patch"], p) or 0.0
            if s < PATCH_MATCH:
                others.append(s)
        return not others or sim - max(others) >= PATCH_MARGIN

    page_views = _page_views(order_time) if policy == "evidence" else []
    page_map_pairs = _page_map_identities(page_views, pair_same) if policy == "evidence" else {}

    for a, b in same_pairs:
        if uf.find(a) == uf.find(b):
            continue
        ev_a = add_ev("A", "full_window_match", [a, b])
        temporal_gap = ep_by[b]["t_start"] - ep_by[a]["t_end"]
        local = ep_by[a]["slot_id"] == ep_by[b]["slot_id"] and temporal_gap <= 1.0
        if local and ep_by[b]["started_by"] == "playhead_reset":
            kind = "playhead_reset_same_display"
        elif local and ep_by[b]["started_by"] == "view_transition":
            kind = "across_view_transition"
        else:
            kind = "local" if local else "nonlocal_revisit"
        cand = {"a": a, "b": b, "kind": kind, "state": "unresolved", "issue": "POSSIBLE_REVISIT", "evidence_ids": [ev_a]}
        if policy == "evidence":
            sim = ident(a, b)
            if sim is not None and sim < PATCH_DIFFERENT:
                ev = add_ev("I", "different_identifier_patch", [a, b], similarity=round(sim, 3))
                cand.update(state="resolved_different", issue=None, evidence_ids=[ev_a, ev])
                candidates.append(cand)
                continue
            if (a, b) in page_map_pairs:
                # All rows of two page views match at the same coordinates. This is
                # appearance + layout context, not a geometrically verified page map
                # (no continuous registration links the two views), and identical
                # page views of different written pages exist (Q8XtphO6Xz0). It ranks
                # the review suggestion but does not merge automatically.
                pm = page_map_pairs[(a, b)]
                ev = add_ev("A", "page_view_appearance_match", [a, b], rows=pm["rows"], page_views=pm["views"])
                cand.update(evidence_ids=[ev_a, ev], score=3 + 1, suggestion="same_location_likely")
                candidates.append(cand)
                continue
            if sim is not None and sim >= PATCH_MATCH and distinctive(a, b, sim):
                ev_i = add_ev("I", "identifier_patch_match", [a, b], similarity=round(sim, 3),
                              obs_a=desc[a]["patch_obs"], obs_b=desc[b]["patch_obs"])
                pa, na = neighbours(a)
                pb, nb = neighbours(b)
                # context must be anchored independently of the identifier patch: both
                # neighbouring relations already joined by geometry / motion / user evidence
                ctx_ok = (pa is not None and pb is not None and na is not None and nb is not None
                          and uf_geo.find(pa) == uf_geo.find(pb) and uf_geo.find(na) == uf_geo.find(nb))
                if ctx_ok:
                    ev_c = add_ev("C", "independently_anchored_neighbours", [a, b], prev=[pa, pb], next=[na, nb],
                                  anchor_bases=list(INDEPENDENT_ANCHOR_BASES))
                    score = 4 + 3 + 1
                    cand.update(state="resolved_same", issue=None, evidence_ids=[ev_a, ev_i, ev_c], score=score)
                    candidates.append(cand)
                    continue  # merged after ranking below
                cand["evidence_ids"].append(ev_i)
                cand["score"] = 4 + 1
        candidates.append(cand)

    # ranking: an episode may be proposed for several locations; accept only a clear winner
    if policy == "evidence":
        proposals: Dict[str, List[Dict[str, Any]]] = {}
        for c in candidates:
            if c["state"] == "resolved_same" and c["kind"] != "local_slot_transition" and "page_map_identity" not in _kinds(evidence, c):
                proposals.setdefault(c["b"], []).append(c)
        for b, cs in proposals.items():
            cs.sort(key=lambda c: c.get("score", 0), reverse=True)
            best = cs[0]
            runner = cs[1].get("score", 0) if len(cs) > 1 else 0
            if best.get("score", 0) >= 8 and best["score"] - runner >= 3:
                merge(best["a"], b, "identifier+context", best["evidence_ids"])
                for c in cs[1:]:
                    c.update(state="unresolved", issue="POSSIBLE_REVISIT", note="lost ranking")
            else:
                for c in cs:
                    c.update(state="unresolved", issue="POSSIBLE_REVISIT", note="no clear ranking winner")

    # 3. locations
    groups: Dict[str, List[str]] = {}
    for e in order_time:
        groups.setdefault(uf.find(e["id"]), []).append(e["id"])
    unresolved_eps = set()
    for c in candidates:
        if c["state"] == "unresolved":
            unresolved_eps.update([c["a"], c["b"]])
    locations = []
    loc_of = {}
    for k, (root, members) in enumerate(sorted(groups.items(), key=lambda kv: (ep_by[kv[0]]["t_start"], ep_by[kv[0]]["staff_top_y"]))):
        lid = f"loc-{k + 1:03d}"
        for m in members:
            loc_of[m] = lid
        best = max(members, key=lambda m: (ep_by[m]["confirmed"], ep_by[m]["n_obs"]))
        d = desc[best]
        issues = []
        if any(m in unresolved_eps for m in members):
            issues.append("POSSIBLE_REVISIT")
        short_only = all(not ep_by[m]["confirmed"] for m in members)
        if short_only:
            issues.append("SHORT_EPISODE")
            issues.append("NON_SCORE_UNCERTAIN")
        clip = desc[best]["edge_clipped"]
        if clip["top"] >= 0.5 or clip["bottom"] >= 0.5:
            issues.append("ENVELOPE_CLIPPED")
        locations.append({
            "id": lid,
            "page_map_id": None,
            "document_bbox": None,
            "number_patch_id": None,
            "number_value": None,
            "numbering_scope_id": None,
            "episode_ids": members,
            "observation_region_ids": [r for m in members for r in ep_by[m]["region_ids"]],
            "representative": {"episode_id": best, "obs_id": d["rep_obs_id"], "region_id": d["rep_region_id"], "t": d["rep_t"],
                               "staff_top_y_crop": d["staff_top"], "staff_x_crop": d["staff_x"], "output_rect_crop": d["output_rect_crop"]},
            "identity_state": "unresolved" if issues and "POSSIBLE_REVISIT" in issues else "resolved",
            "included": not short_only,
            "envelope_clipped": clip,
            "issues": issues,
        })
    _assign_patch_ids(locations, desc)
    for c in candidates:
        c["location_a"] = loc_of.get(c["a"])
        c["location_b"] = loc_of.get(c["b"])

    # 4. order: first occurrence; rows of one page view top-to-bottom are a confirmed geometric edge
    included = [l for l in locations if l["included"]]
    first_t = {l["id"]: min((ep_by[m]["t_start"], ep_by[m]["staff_top_y"]) for m in l["episode_ids"]) for l in included}
    ordered = sorted(first_t, key=lambda k: first_t[k])
    excluded_ids = [l["id"] for l in locations if not l["included"]]
    edges = []
    for a, b in zip(ordered, ordered[1:]):
        ea = [ep_by[m] for m in next(l for l in locations if l["id"] == a)["episode_ids"]]
        eb = [ep_by[m] for m in next(l for l in locations if l["id"] == b)["episode_ids"]]
        same_view = any(x["t_start"] < y["t_end"] and y["t_start"] < x["t_end"] and x["slot_id"] != y["slot_id"] and x["staff_top_y"] < y["staff_top_y"]
                        for x in ea for y in eb)
        if same_view:
            ev = add_ev("G", "page_row_order", [ea[0]["id"], eb[0]["id"]])
            edges.append({"before": a, "after": b, "basis": "page_geometry", "evidence_ids": [ev], "state": "confirmed"})
        else:
            edges.append({"before": a, "after": b, "basis": "temporal_first_occurrence", "evidence_ids": [], "state": "provisional"})
    occurrences = [{"id": f"visit-{i + 1:03d}", "episode_id": e["id"], "location_id": loc_of[e["id"]], "t_start": e["t_start"],
                    "t_end": e["t_end"], "role": "performed" if e.get("role") in ("active", None) else e.get("role")}
                   for i, e in enumerate(order_time)]
    issues = [{"kind": c["issue"], "episodes": [c["a"], c["b"]], "locations": [c["location_a"], c["location_b"]]}
              for c in candidates if c["state"] == "unresolved"]
    for iv in unsupported:
        issues.append({"kind": "UNSUPPORTED_LAYOUT", "interval": [iv["start"], iv["end"]], "layout": iv["kind"]})
    issues.extend(content_beyond_roi_issues(manifest))
    for l in locations:
        if "ENVELOPE_CLIPPED" in l["issues"]:
            eps_l = [ep_by[m] for m in l["episode_ids"]]
            issues.append({"kind": "ENVELOPE_CLIPPED", "locations": [l["id"]], "edge": l["envelope_clipped"],
                           "interval": [min(e["t_start"] for e in eps_l), max(e["t_end"] for e in eps_l)]})
        if not l["included"]:
            issues.append({"kind": "NON_SCORE_UNCERTAIN", "locations": [l["id"]], "episodes": l["episode_ids"]})
    completion = "blocked_unsupported_layout" if unsupported else ("needs_review" if issues else "resolved")
    logger(f"{policy}: locations {len(locations)}, merges {len(merges)}, unresolved {len(issues)}")
    return {
        "schema_version": 1,
        "kind": "score_assembly",
        "assembly_version": ASSEMBLY_VERSION,
        "policy": policy,
        "video_id": tracking.get("video_id"),
        "assembly_revision": 1,
        "locations": locations,
        "occurrences": occurrences,
        "order_edges": edges,
        "identity_candidates": candidates,
        "merges": merges,
        "evidence": evidence,
        "ordered_location_ids": ordered,
        "excluded_location_ids": excluded_ids,
        "review_decisions": [],
        "issues": issues,
        "completion": completion,
    }


def content_beyond_roi_issues(manifest: Dict[str, Any], *, min_sec: float = 2.0, max_gap_sec: float = 1.0) -> List[Dict[str, Any]]:
    """CONTENT_BEYOND_ROI: notation/text cut by the applied ROI edge that belongs to no detected
    row (observations.edge_content), persisting >= min_sec. It means part of the score is outside
    the applied ROI; finalization must wait for an ROI decision."""
    out = []
    for side in ("top", "bottom"):
        run = None
        for o in manifest["observations"]:
            ec = o.get("edge_content") or {}
            regs = o.get("system_regions") or []
            gap = float(np.median([r["staff_gap_px"] for r in regs])) if regs else 10.0
            hit = bool(regs) and ec.get(side, 0) > 0 and ec.get(side + "_px", 0) >= 2 * gap
            t = o["t_sec"]
            if hit:
                if run and t - run[1] <= max_gap_sec:
                    run[1] = t
                    run[2] += 1
                else:
                    if run and run[1] - run[0] >= min_sec:
                        out.append(run)
                    run = [t, t, 1]
        if run and run[1] - run[0] >= min_sec:
            out.append(run)
        out = [r if len(r) == 4 else r + [side] for r in out]
    return [{"kind": "CONTENT_BEYOND_ROI", "edge": r[3], "interval": [r[0], r[1]], "observations": r[2]} for r in out]


def _kinds(evidence: List[Dict[str, Any]], cand: Dict[str, Any]) -> List[str]:
    ids = set(cand.get("evidence_ids", []))
    return [e["kind"] for e in evidence if e["id"] in ids]


def _page_views(order_time: List[Dict[str, Any]]) -> List[List[str]]:
    """Groups of >= 3 confirmed episodes in distinct slots that are displayed together."""
    views = []
    seen = set()
    for e in order_time:
        if e["id"] in seen or not e["confirmed"]:
            continue
        group = [x for x in order_time if x["confirmed"] and x["slot_id"] != e["slot_id"]
                 and min(x["t_end"], e["t_end"]) - max(x["t_start"], e["t_start"]) >= 0.5 * min(x["t_end"] - x["t_start"], e["t_end"] - e["t_start"])]
        group = [e] + group
        slots = {}
        for g in group:
            slots.setdefault(g["slot_id"], g)
        members = list(slots.values())
        if len(members) >= 3:
            views.append([m["id"] for m in sorted(members, key=lambda m: m["staff_top_y"])])
            seen.update(m["id"] for m in members)
    return views


def _page_map_identities(views: List[List[str]], pair_same: Dict[Tuple[str, str], bool]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Two page views are the same page when every row matches the row at the same position (>= 3 rows)."""
    out = {}

    def same(a: str, b: str) -> bool:
        return pair_same.get((a, b)) or pair_same.get((b, a)) or False

    for i, v in enumerate(views):
        for w in views[i + 1 :]:
            if len(v) != len(w) or len(v) < 3:
                continue
            if all(same(a, b) for a, b in zip(v, w)):
                for a, b in zip(v, w):
                    key = (a, b) if a < b else (b, a)
                    out[key] = {"rows": len(v), "views": [v, w]}
    return out


def _assign_patch_ids(locations: List[Dict[str, Any]], desc: Dict[str, Dict[str, Any]]) -> None:
    clusters: List[Tuple[str, np.ndarray]] = []
    for loc in locations:
        p = desc[loc["representative"]["episode_id"]]["patch"]
        if p is None:
            continue
        for cid, ref in clusters:
            if (patch_similarity(ref, p) or 0) >= PATCH_MATCH:
                loc["number_patch_id"] = cid
                break
        else:
            cid = f"patch-{len(clusters) + 1}"
            clusters.append((cid, p))
            loc["number_patch_id"] = cid
        loc["numbering_scope_id"] = "scope-1"
