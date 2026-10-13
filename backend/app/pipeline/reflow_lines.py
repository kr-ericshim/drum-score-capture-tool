"""Line breaking and bounded justification for measure-level reflow (MEASURE_BRIEF milestone 2).

Pure planning on output-pixel widths; no images. ``reflow_measure`` builds the atoms from the
measure units of the placed systems and renders the lines this module plans.

Atoms are the ordered measure units / locked groups / whole systems of the placed systems. A
line is a contiguous run of atoms. Where a line may start:

* at a source-system start (``break_before == "system_start"``): always; the system keeps its own
  printed prefix. Not breaking there (a *join*) is allowed only when the atom says so
  (``join_legal``: a prefix-free system, or a system whose repeated drum clef is removed cleanly,
  after endpoint checks; ``join_trim`` px of lead/tail columns are then dropped and the join's
  lead is a slot, ``join["slot"]``);
* at a SAFE cut inside a system (``break_before == "safe_cut"``): only with a verified clef-only
  replica (``replica_width``) or a positively prefix-free system (``replica_width == 0``); otherwise
  the cut is not a legal line start (``replica_width is None``);
* never inside an atom: UNKNOWN/LOCKED boundaries are inside atoms already.

The justified edge ``width`` may be inside the printable line ``max_width`` (``common_edge``); a
line that cannot reach it keeps its natural spacing (a recorded ragged line) as long as it fits.

Line cost (deterministic DP over legal contiguous ranges, Knuth-Plass style)::

    N = natural width incl. a replica prefix
    gaps = the line's barline corridors, join leads and spread gaps (every eligible gap between
           note/rest columns inside the measures, ``atom["gaps"]``, found by reflow_measure)
    E = min(sum gap expansion caps, 0.15 N);  C = min(sum gap contraction caps, 0.05 N)
    E2 = min(sum of the wider gap caps, 0.25 N)  (Fill every line: max(60% natural, 1.0 staff gap) per gap)
    justified when W in [N - C, N + E]; else justified with the wider caps when W <= N + E2 or
    W >= N - C2 (+COST_WIDE; C2: gaps keep >= max(60%, 0.4 staff gap), still <= 0.05 N); else (Every line
    full, 2026-10-07) an even tier-3 spread when W <= N + E3 (each gap <= TIER3_MAX_GAP_RATIO x its natural
    width; +COST_WIDE + COST_TIER3); otherwise a recorded ragged line at natural width if it fits;
    otherwise the range is rejected.
    r = (W - N) / (natural width of the gaps that can take it): the per-gap stretch ratio
    cost = COST_STRETCH r^2 + 4 (count - 4)^2 [every count known; else 0.5x that on the barline estimate]
           + 40 single-measure orphan
           + 300 max(0, 0.85 - natural / page line width)^2 [half for the last line]
           + COST_RAGGED + 1000 (unfilled page line width / page line width)^2 for ANY ragged line,
             the final line and lines at section ends included (+COST_RAGGED_MIDDLE when not final)
           + 3 per line starting inside a source system + 1 per joined system
    A line never runs past the justified edge (only overhang ink may). A section start does not force
    a break: a joinable system continues mid-line and its section label sits above it.

Minimising the sum of squared stretch ratios balances the lines: they need similar stretch, so no
line looks much looser than the others (the way engravers break lines).

(DECISIONS "Joining systems": four measures is a soft preference; lines should fill the page
width reasonably. The original brief costs were 3 (count-4)^2 and a flat 25 per ragged line.)

Justification changes whitespace only (DECISIONS "Spread justification", a user-requested change
of the brief's 8%/3% line caps): the line's extra width is spread over all its gaps
proportionally to each gap's natural width (like proportional engraving spacing), each gap
capped: growth <= max(35% of its natural width, 0.6 staff gap), never below 85% of its natural
width nor below 0.5 staff gap of clear space. Whole pixels by largest remainder. Glyphs are never
stretched: the renderer only repeats or removes columns that are verified whitespace (staff lines
and straight horizontal beams continuing on both sides).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LINES_VERSION = "reflow_lines-5"  # 5: a line whose overhang would cross the page margin at the edge is not justified there
# Spread justification: a user-requested change of the brief's 8%/3% per-line default (2026-10-06:
# the user disliked both ragged right edges and a few visibly wide gaps). The extra width goes
# into many gaps proportionally to their natural width; the caps below are per gap.
GAP_GROW_FRACTION = 0.35  # one gap grows by at most max(35% of its natural width, ...
GAP_GROW_MIN_GAPS = 0.6  # ... 0.6 staff gap)
GAP_SHRINK_FLOOR = 0.85  # one gap keeps at least 85% of its natural width ...
GAP_CLEAR_MIN_GAPS = 0.5  # ... and at least 0.5 staff gap of clear space
MAX_EXPAND_FRACTION = 0.15  # whole line: at most 15% wider than natural (brief: 8%)
MAX_CONTRACT_FRACTION = 0.05  # whole line: at most 5% narrower (brief: 3%)
# Fill every line (user request 2026-10-06): a line that cannot reach the edge within the caps above
# may use wider caps, for that line only: a gap grows by at most max(60% of its natural width, 1.0
# staff gap) and the line by at most 25%.
WIDE_GAP_GROW_FRACTION = 0.60
WIDE_GAP_GROW_MIN_GAPS = 1.0
WIDE_MAX_EXPAND_FRACTION = 0.25
COST_WIDE = 25.0  # a line that needs the wider caps (on top of its larger stretch cost)
# Every line full (user 2026-10-07, like the teacher PDF): a line that still cannot reach the edge after
# joins and rebalancing spreads more whitespace over all its eligible gaps, beyond the wider caps, for
# that line only (tier 3). Every gap grows by the same fraction of its natural width (an even spread;
# glyphs are never scaled), at most TIER3_MAX_GAP_RATIO; no per-line limit. A join lead keeps its own
# cap (``max_expand_free``: it can only give back the columns it dropped).
# Every line full: a source system only slightly wider than the edge (e.g. 2160 px on a 2122 px edge)
# may tighten its gaps further instead of being split into short pieces: a gap keeps at least
# max(60% of its natural width, 0.4 staff gap) (``max_contract_wide``, set by reflow_measure; barline
# corridors keep their clear-column limit). The line limit stays MAX_CONTRACT_FRACTION.
WIDE_GAP_SHRINK_FLOOR = 0.60
WIDE_GAP_CLEAR_MIN_GAPS = 0.4
TIER3_MAX_GAP_RATIO = 3.0  # one gap grows to at most 4x its natural width
COST_TIER3 = 100.0  # a line that needs tier 3 (on top of its stretch cost): joins and rebalancing come first
COST_STRETCH = 200.0  # times the line's squared per-gap stretch ratio (Knuth-Plass style balancing)
PREFERRED_MEASURES = 4
COST_COUNT = 4.0  # mild: four measures per line is a soft preference (DECISIONS "Joining systems")
COST_ORPHAN = 40.0
COST_COUNT_ESTIMATE = 0.5  # weight of the count penalty when a count is unknown and only a barline estimate exists
# Fill every line: a line that cannot reach the edge even with the wider caps (the final line and lines
# at section ends included) is a last resort; breaks that let every line reach the edge always win.
COST_RAGGED = 5000.0  # every ragged line, plus
COST_RAGGED_RESIDUAL = 1000.0  # ... times (unfilled part of the page line width / page line width)^2
COST_RAGGED_MIDDLE = 500.0  # ... plus this when it is not the last line (a short line mid-page looks worse)
FILL_TARGET = 0.85  # a non-final line filling less of the page line width pays COST_UNDERFILL * shortfall^2
COST_UNDERFILL = 300.0
COST_SPLIT = 3.0  # a line starting inside a source system (clef replica): mild, keeps source systems whole when equal
COST_JOIN = 1.0  # a source system continuing mid-line (its repeated clef removed, or prefix-free)
FULL_LINE_FRACTION = 0.75
FINAL_RAGGED_EDGE_COST = 5.0  # edge choice only (plan_document)

# Why a line stays ragged (only when no choice of breaks lets it reach the edge within the wider caps)
RAGGED_INSUFFICIENT_SLACK = "INSUFFICIENT_SLACK"  # no break choice between two forced breaks lets every line reach it
RAGGED_LOCKED_SPAN = "LOCKED_SPAN"  # unsplittable content (locked group, whole system, one long measure) with too little whitespace
RAGGED_SEGMENT_TOO_SHORT = "SEGMENT_TOO_SHORT"  # all content between two forced breaks is shorter than a line can stretch
RAGGED_OVERHANG_AT_MARGIN = "OVERHANG_AT_MARGIN"  # at this edge the line's overhang ink (a "Fine" box) would cross the page margin


def slot_caps(natural_px: float, gap_px: float) -> Tuple[float, float]:
    """(max expansion, max contraction) of one gap of ``natural_px`` clear columns (same units):
    growth <= max(35% natural, 0.6 staff gap); the gap keeps >= max(85% natural, 0.5 staff gap)."""
    w = max(0.0, float(natural_px))
    if w <= 0:
        return 0.0, 0.0
    expand = max(GAP_GROW_FRACTION * w, GAP_GROW_MIN_GAPS * gap_px)
    contract = max(0.0, w - max(GAP_SHRINK_FLOOR * w, GAP_CLEAR_MIN_GAPS * gap_px))
    return expand, contract


def wide_grow_cap(natural_px: float, gap_px: float) -> float:
    """The wider growth cap of one gap (Fill every line): max(60% of its natural width, 1.0 staff gap)."""
    w = max(0.0, float(natural_px))
    if w <= 0:
        return 0.0
    return max(WIDE_GAP_GROW_FRACTION * w, WIDE_GAP_GROW_MIN_GAPS * gap_px)


def spread_fill(total: int, naturals: Sequence[float], caps: Sequence[float]) -> List[int]:
    """Split ``total`` whole pixels over gaps proportionally to their natural widths, each capped:
    share_k = min(cap_k, lam * natural_k) with one ratio ``lam`` for all (bounded proportional
    water-filling), then whole pixels by largest remainder within the floored caps. The sum is
    exact as long as ``total <= sum(floor(caps))``; otherwise every gap gets its floored cap."""
    n = len(caps)
    if n == 0 or total <= 0:
        return [0] * n
    icaps = [int(math.floor(c + 1e-9)) for c in caps]
    if total >= sum(icaps):
        return icaps
    ws = [max(0.0, float(w)) if icaps[k] > 0 else 0.0 for k, w in enumerate(naturals)]
    if sum(ws) <= 0:
        return water_fill(total, icaps)
    # lam: sum min(icap, lam w) = total; breakpoints at icap / w
    order = sorted((icaps[k] / ws[k], k) for k in range(n) if ws[k] > 0)
    fixed, wrest = 0.0, sum(ws)
    lam = 0.0
    for bp, k in order:
        if fixed + bp * wrest >= total:
            break
        fixed += icaps[k]
        wrest -= ws[k]
    lam = (total - fixed) / wrest if wrest > 0 else 0.0
    share = [min(float(icaps[k]), lam * ws[k]) for k in range(n)]
    out = [int(math.floor(x + 1e-9)) for x in share]
    rem = total - sum(out)
    for k in sorted(range(n), key=lambda k: (-(share[k] - out[k]), -ws[k], k)):
        if rem <= 0:
            break
        if out[k] < icaps[k]:
            out[k] += 1
            rem -= 1
    if rem > 0:  # rounding left room only in other gaps
        for k in sorted(range(n), key=lambda k: (-(icaps[k] - out[k]), k)):
            take = min(rem, icaps[k] - out[k])
            out[k] += take
            rem -= take
    return out


def water_fill(total: int, caps: Sequence[float]) -> List[int]:
    """Split ``total`` whole pixels over slots with the given caps: equal shares, capped, the rest
    poured into the slots with room left; whole pixels by largest remainder (sum is exact as long
    as ``total <= sum(floor(caps))``; otherwise every slot gets its floored cap)."""
    n = len(caps)
    if n == 0 or total <= 0:
        return [0] * n
    icaps = [int(math.floor(c + 1e-9)) for c in caps]
    if total >= sum(icaps):
        return icaps
    share = [0.0] * n
    left = float(total)
    open_ = [i for i in range(n) if icaps[i] > 0]
    while left > 1e-9 and open_:
        each = left / len(open_)
        nxt = []
        for i in open_:
            room = icaps[i] - share[i]
            take = min(room, each)
            share[i] += take
            left -= take
            if icaps[i] - share[i] > 1e-9:
                nxt.append(i)
        open_ = nxt
    out = [int(math.floor(s)) for s in share]
    rem = total - sum(out)
    order = sorted(range(n), key=lambda i: (-(share[i] - out[i]), i))
    for i in order:
        if rem <= 0:
            break
        if out[i] < icaps[i]:
            out[i] += 1
            rem -= 1
    return out


def _inner_slot(a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The slot in front of atom ``a`` when it is not the first atom of its line: the corridor of a
    SAFE cut, or the lead of a system that joins mid-line (its clef removed)."""
    if a.get("break_before") == "system_start":
        return (a.get("join") or {}).get("slot") if a.get("join_legal") else None
    return a.get("slot_before")


def _joined_trim(a: Dict[str, Any]) -> int:
    return int(a.get("join_trim") or 0) if a.get("break_before") == "system_start" and a.get("join_legal") else 0


def _floor(x: float) -> int:
    return int(math.floor(float(x) + 1e-9))


def _wide(g: Dict[str, Any]) -> float:
    """A gap's growth cap under the wider caps (never below its normal cap; absent: no wider growth)."""
    return max(float(g.get("max_expand") or 0.0), float(g.get("max_expand_wide") or 0.0))


def _free(g: Dict[str, Any]) -> float:
    """A gap's growth cap under tier 3 (Every line full): TIER3_MAX_GAP_RATIO x its natural width for a
    gap that can grow at all, never below its wider cap; ``max_expand_free`` overrides (join leads)."""
    if g.get("max_expand_free") is not None:
        return max(_wide(g), float(g["max_expand_free"]))
    w = _wide(g)
    return max(w, TIER3_MAX_GAP_RATIO * float(g.get("natural") or 0.0)) if w > 0 else 0.0


def wide_shrink_cap(natural_px: float, gap_px: float) -> float:
    """The wider contraction cap of one gap: it keeps max(60% of its natural width, 0.4 staff gap)."""
    w = max(0.0, float(natural_px))
    return max(0.0, w - max(WIDE_GAP_SHRINK_FLOOR * w, WIDE_GAP_CLEAR_MIN_GAPS * gap_px))


def _cwide(g: Dict[str, Any]) -> float:
    """A gap's contraction cap under the wider caps (never below its normal cap)."""
    return max(float(g.get("max_contract") or 0.0), float(g.get("max_contract_wide") or 0.0))


def _gap_sums(a: Dict[str, Any]) -> Tuple[float, ...]:
    """(natural width of gaps that can grow, sum of floored growth caps, natural width of gaps that
    can shrink, sum of floored shrink caps, natural width of gaps that can grow under the wider caps,
    sum of floored wider growth caps) of an atom's spread gaps (cached on the atom)."""
    gs = a.get("_gap_sums")
    if gs is None:
        gs = a["_gap_sums"] = _sums(a.get("gaps") or ())
    return gs


def _sums(gaps: Iterable[Dict[str, Any]]) -> Tuple[float, ...]:
    we = wc = w2 = w3 = wk = 0.0
    ce = cc = c2 = c3 = ck = 0
    for g in gaps:
        e, c, e2, e3, k2 = _floor(g["max_expand"]), _floor(g["max_contract"]), _floor(_wide(g)), _floor(_free(g)), _floor(_cwide(g))
        if k2 > 0:
            wk += float(g["natural"])
            ck += k2
        if e > 0:
            we += float(g["natural"])
            ce += e
        if c > 0:
            wc += float(g["natural"])
            cc += c
        if e2 > 0:
            w2 += float(g["natural"])
            c2 += e2
        if e3 > 0:
            w3 += float(g["natural"])
            c3 += e3
    return we, ce, wc, cc, w2, c2, w3, c3, wk, ck


def _line_gaps(atoms: Sequence[Dict[str, Any]], i: int, j: int) -> List[Dict[str, Any]]:
    """Every gap of the line [i, j): the corridor or join lead in front of each non-first atom and
    the spread gaps inside every atom, in line order."""
    out: List[Dict[str, Any]] = []
    for k in range(i, j):
        a = atoms[k]
        if k > i:
            sl = _inner_slot(a)
            if sl:
                out.append(sl)
        out.extend(a.get("gaps") or ())
    return out


def _line_eval(atoms: Sequence[Dict[str, Any]], i: int, j: int, width: int, final: bool,
               max_width: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Evaluate the line of atoms [i, j) for the justified edge ``width``; None when it does not fit
    ``max_width`` (the printable line, default ``width``) even fully contracted."""
    max_width = width if max_width is None else max_width
    first = atoms[i]
    replica = 0
    if i > 0 and first["break_before"] == "safe_cut":
        replica = int(first.get("replica_width") or 0)
    natural = replica + sum(int(a["width"]) for a in atoms[i:j]) - sum(_joined_trim(a) for a in atoms[i + 1:j])
    slots = [sl for sl in (_inner_slot(a) for a in atoms[i + 1:j]) if sl]
    tot = list(_sums(slots))
    for a in atoms[i:j]:
        g = _gap_sums(a)
        tot = [x + y for x, y in zip(tot, g)]
    we, ce, wc, cc, w2, c2, w3, c3, wk, ck = tot
    e_cap = min(ce, _floor(MAX_EXPAND_FRACTION * natural))
    e_wide = max(e_cap, min(c2, _floor(WIDE_MAX_EXPAND_FRACTION * natural)))
    e_free = max(e_wide, int(c3))
    c_cap = min(cc, _floor(MAX_CONTRACT_FRACTION * natural))
    c_wide = max(c_cap, min(int(ck), _floor(MAX_CONTRACT_FRACTION * natural)))
    overhang = int(atoms[j - 1].get("overhang") or 0)  # ink past the last staff end (a "Fine" box)
    if natural - c_wide + overhang > max_width:
        return None
    if natural - c_wide > width:
        return None  # a line never runs past the justified edge (only overhang ink may)
    counts = [a.get("measure_count") for a in atoms[i:j]]
    known = all(isinstance(c, int) for c in counts)
    count = sum(counts) if known else None
    tier = 1
    if natural - c_cap <= width <= natural + e_cap:
        delta, justified, ragged = width - natural, True, None
    elif natural - c_wide <= width < natural - c_cap:
        # Every line full: a system slightly wider than the edge tightens its gaps (wider contraction caps)
        delta, justified, ragged, tier = width - natural, True, None, 2
    elif natural + e_cap < width <= natural + e_wide:
        # Fill every line: the wider per-gap caps for this line only
        delta, justified, ragged, tier = width - natural, True, None, 2
    elif natural + e_wide < width <= natural + e_free:
        # Every line full: an even spread over all eligible gaps beyond the wider caps (last resort)
        delta, justified, ragged, tier = width - natural, True, None, 3
    else:
        # cannot reach the edge: natural spacing (contracted only as far as the printable line needs)
        delta = max(-c_wide, min(0, max_width - natural - overhang))
        justified = False
        ragged = RAGGED_INSUFFICIENT_SLACK
    # caps reported for this line (edge votes, records) are those of the tier that reaches ``width``
    cap_tier, cap_delta = tier, delta
    overhang_blocked = False
    if justified and width + overhang > max_width:
        # the staff would end at the edge and its overhang ink (a "Fine" box) cross the page margin: the
        # line cannot be justified to this edge; it keeps natural spacing (contracted only as far as the
        # printable line needs), like any line that cannot reach the edge
        delta = max(-c_wide, min(0, max_width - natural - overhang))
        justified, ragged, tier, overhang_blocked = False, RAGGED_OVERHANG_AT_MARGIN, 1, True
    # the per-gap stretch ratio (every gap that can take it grows or shrinks by this fraction)
    grow_w = w3 if tier == 3 else w2 if tier == 2 else we
    shrink_w = wk if tier == 2 else wc
    stretch = (delta / grow_w if grow_w > 0 else 0.0) if delta > 0 else (delta / shrink_w if shrink_w > 0 else 0.0) if delta < 0 else 0.0
    cost = COST_STRETCH * stretch * stretch + (COST_WIDE if tier == 2 else COST_WIDE + COST_TIER3 if tier == 3 else 0.0)
    tier3_stretch_cost = COST_STRETCH * stretch * stretch if tier == 3 else 0.0
    if known:
        cost += COST_COUNT * (count - PREFERRED_MEASURES) ** 2
    elif all(isinstance(a.get("measure_estimate"), int) for a in atoms[i:j]):
        est = sum(int(a["measure_estimate"]) for a in atoms[i:j])
        cost += COST_COUNT_ESTIMATE * COST_COUNT * (est - PREFERRED_MEASURES) ** 2
    if count == 1 and len(atoms) > 1:
        cost += COST_ORPHAN
    # where a section ends (a double barline, a labelled next section): recorded, no longer a reason for a short line
    nxt = atoms[j] if j < len(atoms) else None
    section_end = bool(atoms[j - 1].get("ends_section") or (nxt is not None and nxt.get("section_start")))
    ragged_cost = 0.0
    if ragged:
        # Fill every line: the final line and section ends included; the residual is measured against
        # the page line width, so an unavoidable short line never pulls the edge inward
        ragged_cost = COST_RAGGED + COST_RAGGED_RESIDUAL * ((max_width - natural - delta) / float(max_width)) ** 2
        if not final:
            ragged_cost += COST_RAGGED_MIDDLE
        cost += ragged_cost
    # fill = the line's content (natural width) against the page line width: justification does not
    # count as content, so the edge choice stays a matter of whitespace caps (plan_document)
    fill = natural / float(max_width) if max_width else 1.0
    # the last line pays half: a short last line is normal, but not at any price for the others
    cost += (0.5 if final else 1.0) * COST_UNDERFILL * max(0.0, FILL_TARGET - fill) ** 2
    if i > 0 and first["break_before"] == "safe_cut":
        cost += COST_SPLIT
    joins = sum(1 for a in atoms[i + 1:j] if a.get("break_before") == "system_start")
    cost += COST_JOIN * joins
    return {"start": i, "end": j, "natural": natural, "overhang": overhang, "replica_width": replica,
            "expand_cap": e_free if cap_tier == 3 else e_wide if cap_tier == 2 else e_cap, "expand_cap_normal": e_cap,
            "expand_cap_wide": e_wide, "expand_cap_free": e_free, "overhang_blocked": overhang_blocked,
            "contract_cap": c_wide if cap_tier == 2 and cap_delta < 0 else c_cap, "contract_cap_wide": c_wide, "stretch_ratio": stretch, "section_end": section_end, "tier": tier, "final": final,
            "delta": delta, "justified": justified, "ragged": ragged, "measure_count": count, "cost": cost, "ragged_cost": ragged_cost,
            "tier3_stretch_cost": tier3_stretch_cost,
            "slot_ids": [s["id"] for s in slots], "fill": fill, "joins": joins}


def _must_break_static(a: Dict[str, Any]) -> bool:
    return a["break_before"] == "system_start" and not a.get("join_legal")


def _ragged_reason(atoms: Sequence[Dict[str, Any]], ev: Dict[str, Any], width: int) -> Dict[str, Any]:
    """Why the line [start, end) cannot reach the edge: its unsplittable content, the content between
    the forced breaks around it, or no break choice there that fills every line."""
    i, j = ev["start"], ev["end"]
    if ev.get("overhang_blocked"):
        return {"reason": RAGGED_OVERHANG_AT_MARGIN, "final_line": bool(ev["final"]), "segment_atoms": [atoms[i]["id"], atoms[j - 1]["id"]],
                "forced_break_after": None}
    s = i
    while s > 0 and not _must_break_static(atoms[s]):
        s -= 1
    e = j
    while e < len(atoms) and not _must_break_static(atoms[e]):
        e += 1
    after = "DOCUMENT_END" if e == len(atoms) else "SYSTEM_CANNOT_JOIN"
    need = width - ev["natural"]
    seg = atoms[i:j]
    big = max(seg, key=lambda a: int(a["width"]))
    # unsplittable content (a locked group, a whole system, or one long measure such as a multi-measure
    # rest) makes up most of the line and has too little whitespace to reach the edge
    if int(big["width"]) >= 0.5 * ev["natural"] and ev["expand_cap_free"] < need:
        code = RAGGED_LOCKED_SPAN
    elif e - s == j - i:
        code = RAGGED_SEGMENT_TOO_SHORT  # the line is everything between two forced breaks
    else:
        code = RAGGED_INSUFFICIENT_SLACK
    return {"reason": code, "final_line": bool(ev["final"]), "segment_atoms": [atoms[s]["id"], atoms[e - 1]["id"]],
            "forced_break_after": after}


def plan_lines(atoms: Sequence[Dict[str, Any]], width: int, *, max_width: Optional[int] = None,
               locks: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Line breaks and justification for ``atoms`` on a line of ``width`` output pixels.

    Atom fields: ``id``, ``width`` (int px, to the staff end), ``overhang`` (int px of ink past the
    staff end, last atom of a system; outside the justified width but inside the page), ``measure_count`` (int|None), ``kind``, ``break_before``
    (``"system_start"`` | ``"safe_cut"``; the first atom's is ignored), ``join_legal`` (bool, for a
    system start), ``replica_width`` (int px | None, for a safe cut), ``slot_before`` (``{id,
    natural, max_expand, max_contract}`` or None), ``boundary_id`` (the cut's boundary id, for locks).

    Locks: ``forced_line_break`` (targets: [boundary id]) requires a break there; ``keep_together``
    (targets: [first atom id, last atom id]) forbids breaks inside. A lock that cannot be honoured
    is a conflict; nothing is clipped or shrunk. Returns lines, slot deltas, ragged exceptions,
    conflicts and the total cost."""
    n = len(atoms)
    conflicts: List[Dict[str, Any]] = []
    idx = {a["id"]: k for k, a in enumerate(atoms)}
    by_boundary = {a.get("boundary_id"): k for k, a in enumerate(atoms) if a.get("boundary_id")}
    forced = set()
    no_break = set()
    for lk in locks or ():
        if not lk.get("active", True):
            continue
        t = lk.get("type")
        targets = list(lk.get("targets") or [])
        if t == "forced_line_break":
            k = by_boundary.get(targets[0]) if targets else None
            if k is None:
                conflicts.append({"code": "FORCED_BREAK_NOT_A_CUT", "lock_ids": [lk.get("id")], "target_ids": targets})
                continue
            if atoms[k]["break_before"] == "safe_cut" and atoms[k].get("replica_width") is None:
                conflicts.append({"code": "FORCED_BREAK_PREFIX_UNVERIFIED", "lock_ids": [lk.get("id")], "target_ids": targets})
                continue
            forced.add(k)
        elif t == "keep_together":
            if len(targets) != 2 or targets[0] not in idx or targets[1] not in idx or idx[targets[0]] > idx[targets[1]]:
                conflicts.append({"code": "STALE_LOCK_TARGET", "lock_ids": [lk.get("id")], "target_ids": targets})
                continue
            for k in range(idx[targets[0]] + 1, idx[targets[1]] + 1):
                no_break.add(k)
    for k in sorted(forced & no_break):
        conflicts.append({"code": "CONTRADICTORY_LOCKS", "target_ids": [atoms[k]["id"]]})
    no_break -= forced

    def can_break(k: int) -> bool:
        if k == 0 or k == n:
            return True
        if k in no_break:
            return False
        a = atoms[k]
        if a["break_before"] == "system_start":
            return True
        return a.get("replica_width") is not None

    def must_break(k: int) -> bool:
        if k in forced:
            return True
        a = atoms[k]
        if a.get("alone") or (k > 0 and atoms[k - 1].get("alone")):
            return True  # an oversize unit scaled to the line has the line to itself
        return a["break_before"] == "system_start" and not a.get("join_legal") and k not in no_break

    for k in range(1, n):
        if k in no_break and atoms[k]["break_before"] == "system_start" and not atoms[k].get("join_legal"):
            conflicts.append({"code": "KEEP_TOGETHER_ACROSS_SYSTEMS", "target_ids": [atoms[k]["id"]]})
            no_break.discard(k)
    INF = float("inf")
    best = [INF] * (n + 1)
    back: List[Optional[Tuple[int, Dict[str, Any]]]] = [None] * (n + 1)
    best[0] = 0.0
    oversize: List[str] = []
    for i in range(n):
        if best[i] == INF or not can_break(i):
            continue
        for j in range(i + 1, n + 1):
            if j > i + 1 and must_break(j - 1):
                break
            if j < n and not can_break(j):
                continue
            ev = _line_eval(atoms, i, j, width, final=(j == n), max_width=max_width)
            if ev is None:
                if j == i + 1:
                    oversize.append(atoms[i]["id"])
                break
            c = best[i] + ev["cost"]
            if c < best[j] - 1e-12:
                best[j] = c
                back[j] = (i, ev)
    if best[n] == INF:
        conflicts.append({"code": "NO_FEASIBLE_LINE_BREAKS", "target_ids": oversize or [a["id"] for a in atoms[-1:]]})
        return {"version": LINES_VERSION, "width": width, "lines": [], "slots": [], "ragged_exceptions": [],
                "conflicts": conflicts, "cost": None, "valid": False}
    evs = []
    k = n
    while k > 0:
        i, ev = back[k]
        evs.append(ev)
        k = i
    evs.reverse()
    lines = []
    slots_out = []
    ragged = []
    for li, ev in enumerate(evs):
        lid = f"line-{li + 1:03d}"
        gl = _line_gaps(atoms, ev["start"], ev["end"])
        ids = [g["id"] for g in gl]
        nat = [float(g["natural"]) for g in gl]
        wide = ev["tier"] == 2
        free = ev["tier"] == 3
        caps_e = [float(_floor(_free(g) if free else _wide(g) if wide else g["max_expand"])) for g in gl]
        caps_c = [float(_floor(_cwide(g) if wide or not ev["justified"] else g["max_contract"])) for g in gl]
        d = int(ev["delta"])
        deltas = spread_fill(d, nat, caps_e) if d > 0 else [-x for x in spread_fill(-d, nat, caps_c)] if d < 0 else [0] * len(gl)
        achieved = ev["natural"] + sum(deltas)
        growth = []
        for g, dd in zip(gl, deltas):
            gr = round(dd / float(g["natural"]), 4) if g["natural"] else 0.0
            growth.append(gr)
            cap_e = _free(g) if free else _wide(g) if wide else float(g["max_expand"])
            cap_c = caps_c[len(growth) - 1]
            slots_out.append({"id": g["id"], "line_id": lid, "kind": g.get("kind", "barline_corridor"), "natural": g["natural"],
                              "max_expand": round(cap_e, 3), "max_contract": round(cap_c, 3),
                              "cap_tier": ev["tier"], "applied_delta": int(dd), "growth_ratio": gr,
                              "within_caps": -cap_c - 1e-9 <= dd <= cap_e + 1e-9})
        line = {"id": lid, "atom_ids": [a["id"] for a in atoms[ev["start"]:ev["end"]]], "start": ev["start"], "end": ev["end"],
                "replica_width": ev["replica_width"], "natural_width": ev["natural"], "overhang_px": ev["overhang"],
                "target_width": width,
                "achieved_width": achieved, "justified": bool(ev["justified"] and achieved == width),
                "adjustment_px": achieved - ev["natural"],
                "adjustment_fraction": round((achieved - ev["natural"]) / float(ev["natural"]), 5) if ev["natural"] else 0.0,
                "measure_count": ev["measure_count"], "slot_ids": ev["slot_ids"], "gap_count": len(ids),
                "spread_gap_count": sum(1 for g in gl if g.get("kind") == "spread"),
                "stretch_ratio": round(ev["stretch_ratio"], 4), "justify_tier": ev["tier"] if ev["justified"] else None,
                "section_end": ev["section_end"],
                "max_gap_growth": max(growth) if growth else 0.0, "min_gap_growth": min(growth) if growth else 0.0,
                "cost": round(ev["cost"], 4), "ragged_cost": round(ev["ragged_cost"], 4),
                "tier3_stretch_cost": round(ev["tier3_stretch_cost"], 4),
                "page_fill": round(achieved / float(max_width if max_width is not None else width), 4),
                "joined_system_ids": [a.get("system_id", a["id"]) for a in atoms[ev["start"] + 1:ev["end"]]
                                      if a.get("break_before") == "system_start"],
                "starts_inside_system": bool(ev["start"] > 0 and atoms[ev["start"]]["break_before"] == "safe_cut"),
                "expand_cap": round(ev["expand_cap"], 3), "contract_cap": round(ev["contract_cap"], 3),
                "expand_cap_wide": round(ev["expand_cap_wide"], 3)}
        why: Optional[Dict[str, Any]] = None
        if ev["justified"] and achieved != width:
            line["justified"] = False
            why = {"reason": RAGGED_INSUFFICIENT_SLACK, "final_line": bool(ev["final"]), "detail": "whole-pixel caps"}
        elif ev["ragged"]:
            why = _ragged_reason(atoms, ev, width)
        if why:
            line["ragged_reason"] = why["reason"]
            ragged.append(dict(why, line_id=lid, requested_width=width, achieved_width=achieved,
                               unresolved_residual_px=width - achieved, natural_width=ev["natural"],
                               available_expand_px=round(ev["expand_cap_free"], 2), available_contract_px=round(ev["contract_cap"], 2)))
        lines.append(line)
    return {"version": LINES_VERSION, "width": width, "max_width": max_width if max_width is not None else width, "lines": lines,
            "slots": slots_out, "ragged_exceptions": ragged, "conflicts": conflicts, "cost": round(best[n], 4), "valid": True}


def common_edge(plan: Dict[str, Any], max_width: int) -> Dict[str, Any]:
    """The justified edge of the document: the line width (<= ``max_width``) that the most non-final
    lines of a first plan can reach within their caps (ties: the wider). The teacher reference ends
    every line at one right edge; when the slots cannot carry the lines to the page margin, a
    common edge inside it is the closest whitespace-only match (DECISIONS: "lines justified to the
    same right edge")."""
    lines = plan.get("lines") or []
    body = lines[:-1] if len(lines) > 1 else lines
    widest = max((ln["natural_width"] for ln in lines), default=0)
    if len(lines) > 1 and lines[-1]["natural_width"] >= FULL_LINE_FRACTION * widest:
        body = lines  # a full-length last line counts too
    cands = {int(max_width)}
    def ecap(ln: Dict[str, Any]) -> float:  # within the normal or wider caps (a tier-3 spread does not count)
        return min(ln["expand_cap"], ln.get("expand_cap_wide", ln["expand_cap"]))

    for ln in body:
        n, e, c = ln["natural_width"], ecap(ln), ln["contract_cap"]
        cands |= {int(n), int(math.floor(n + e)), int(math.ceil(n - c))}
    cands = {w for w in cands if 0 < w <= max_width}

    def reach(w: int) -> int:
        return sum(1 for ln in body if ln["natural_width"] - ln["contract_cap"] <= w <= ln["natural_width"] + ecap(ln))

    best = max(cands, key=lambda w: (reach(w), w))
    return {"width": int(best), "lines_reaching": reach(best), "lines_considered": len(body), "page_line_width": int(max_width),
            "margin_reaching": reach(int(max_width))}


EDGE_COST = 100.0  # per line, times (1 - edge / page line width)^2: ties go to the edge nearer the margin
# (the fill of every line against the page line width is in the line cost: COST_UNDERFILL)
# Edge choice (Fill every line): ragged lines cost as much as inside a plan, so the edge goes where the
# fewest lines stay short. The block stays at least EDGE_MIN_FRACTION of the page line width wide: a
# narrower edge is used only when at every wider edge most lines would be ragged (e.g. every line a whole
# system far narrower than the page); one or two unsplittable lines never pull the whole block inward.
# A line that needs the wider caps counts EDGE_WIDE_COST more, so the edge is not widened by stretching
# every line to the wider caps.
EDGE_MIN_FRACTION = 0.85
EDGE_WIDE_COST = 100.0
EDGE_TIER3_COST = 2000.0  # per line that needs the tier-3 spread at that edge (Every line full)
MAX_EDGE_CANDIDATES = 48
EDGE_GRID_FROM, EDGE_GRID_STEP = 0.75, 0.01


def plan_document(atoms: Sequence[Dict[str, Any]], max_width: int, *, locks: Iterable[Dict[str, Any]] = (),
                  policy: str = "legacy", lambda_u: Optional[float] = None) -> Dict[str, Any]:
    """Line breaks and one justified edge for the whole document.

    The edge is chosen among the page line width and the widths that preferred-length lines
    (known count of ``PREFERRED_MEASURES``) can reach within their caps; each candidate is planned
    by ``plan_lines`` (lines must fit ``max_width``) and the lowest total cost wins, with
    ``EDGE_COST`` per line for an edge inside the margin and ``FINAL_RAGGED_EDGE_COST`` when a
    full-length last line cannot reach the edge. Without any such line the edge of a
    first plan at the page width is used (``common_edge``)."""
    if policy != "legacy":
        # Bounded atoms must come from reflow_optimize.prepare_built; native caps
        # cannot be reconstructed from legacy output-pixel caps alone.
        from app.pipeline import reflow_optimize as opt
        p, lam = opt.policy_config(policy, lambda_u)
        if any("native_scale" not in a for a in atoms):
            raise ValueError("bounded planner requires native prepared atoms")
        candidates = opt.plan_candidates(atoms, max_width, locks=locks, lambda_u=lam)
        if not candidates:
            return {"valid": False, "policy": p, "lines": [], "slots": [], "ragged_exceptions": [],
                    "conflicts": [{"code": "BOUNDED_CAPACITY_LIMIT"}], "edge": {"width": max_width}}
        plan = candidates[0]
        plan["policy"] = p
        return plan
    first = plan_lines(atoms, max_width, locks=locks)
    if not first["valid"]:
        return dict(first, edge={"width": int(max_width), "reason": "no feasible plan"})
    n = len(atoms)
    votes: Dict[int, int] = {}
    for i in range(n):
        for j in range(i + 1, n + 1):
            if j > i + 1 and atoms[j - 1]["break_before"] == "system_start" and not atoms[j - 1].get("join_legal"):
                break
            ev = _line_eval(atoms, i, j, max_width, final=False, max_width=max_width)
            if ev is None:
                break
            if ev["measure_count"] == PREFERRED_MEASURES or ev["natural"] >= (FILL_TARGET - 0.1) * max_width:
                lo, hi = int(math.ceil(ev["natural"] - ev["contract_cap"])), int(math.floor(ev["natural"] + min(ev["expand_cap"], ev["expand_cap_wide"])))
                for w in {lo, int(ev["natural"]), hi}:
                    if 0 < w <= max_width:
                        votes[w] = votes.get(w, 0) + 1
    cands = {int(max_width)}
    # a coarse grid over the well-filled range too, so an edge many lines nearly reach is not missed
    cands |= {int(round(max_width * (EDGE_GRID_FROM + k * EDGE_GRID_STEP)))
              for k in range(int(round((1.0 - EDGE_GRID_FROM) / EDGE_GRID_STEP)))}
    if votes:
        cands |= set(sorted(votes, key=lambda w: (-votes[w], -w))[:MAX_EDGE_CANDIDATES])
    else:
        cands.add(int(common_edge(first, max_width)["width"]))
    best = None
    best_wide = None  # among edges >= EDGE_MIN_FRACTION of the page line width
    for w in sorted(cands, reverse=True):
        plan = first if w == max_width else plan_lines(atoms, w, max_width=max_width, locks=locks)
        if not plan["valid"]:
            continue
        total = plan["cost"] + EDGE_COST * len(plan["lines"]) * (1.0 - w / float(max_width)) ** 2
        # Every line full: the edge goes where the fewest lines need the last-resort tier-3 spread
        total += EDGE_TIER3_COST * sum(1 for ln in plan["lines"] if ln["justify_tier"] == 3)
        total += EDGE_WIDE_COST * sum(1 for ln in plan["lines"] if ln["justify_tier"] in (2, 3))
        last = plan["lines"][-1]
        if not last["justified"] and last["natural_width"] >= FULL_LINE_FRACTION * w:
            total += FINAL_RAGGED_EDGE_COST  # prefer an edge a full-length last line also reaches
        if best is None or total < best[0] - 1e-9:
            best = (total, w, plan)
        if w >= EDGE_MIN_FRACTION * max_width - 1e-9 and (best_wide is None or total < best_wide[0] - 1e-9):
            best_wide = (total, w, plan)
    narrow = False
    if best_wide is not None:
        n_ragged = len(best_wide[2]["ragged_exceptions"])
        if 2 * n_ragged > len(best_wide[2]["lines"]):
            narrow = best[1] < best_wide[1]  # most lines cannot reach any wide edge: a narrower block
        else:
            best = best_wide
    total, w, plan = best
    reach = sum(1 for ln in plan["lines"] if ln["justified"])
    return dict(plan, edge={"width": int(w), "page_line_width": int(max_width), "candidates": len(cands),
                            "lines_justified": reach, "lines": len(plan["lines"]), "total_cost": round(total, 4),
                            "below_min_fraction": bool(w < EDGE_MIN_FRACTION * max_width - 1e-9), "narrow_fallback": narrow})
