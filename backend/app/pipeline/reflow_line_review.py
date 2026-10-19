"""Read-only source-video provenance for each composed output line."""

from __future__ import annotations

import json
import logging
import math
from bisect import bisect_left
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("expected a finite number")
    return float(value)


def _span(values: Sequence[Any]) -> List[float]:
    a, b = values
    if _number(a) < 0 or _number(b) < _number(a):
        raise ValueError("invalid interval")
    return [a, b]


def _index(records: Sequence[Dict[str, Any]], key: str = "id") -> Dict[str, Dict[str, Any]]:
    out = {r[key]: r for r in records}
    if len(out) != len(records) or any(not isinstance(k, str) or not k for k in out):
        raise ValueError("missing or duplicate record id")
    return out


def _failed(exc: Exception, logger: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
    message = f"line_review unavailable: {type(exc).__name__}: {exc}".replace("\n", " ").replace("\r", " ")
    try:
        if logger is None:
            logging.getLogger(__name__).warning(message)
        else:
            logger(message)
    except Exception:
        pass  # Optional review metadata (including its logger) must never fail an export.
    return []


def _x_frac(x: float, sid: str, units: List[dict], placement: dict, audit: dict, line: dict) -> float:
    width = _number(placement["w"])
    scale = _number(placement.get("scale", 1))
    if not units:
        # Whole-system placements have no measure units; labels can offset the strip in the rect.
        offset = placement.get("strip_offset_px", [0, 0])[0]
        return max(0.0, min(1.0, (x + _number(offset)) * scale / width))
    unit = next(u for u in units if u["system_id"] == sid and u["box"][0] <= x < u["box"][2])
    record = audit.get((placement.get("line_id") or placement["system_id"], unit["id"]))
    if record is not None:
        cols = record.get("source_col_index")
        if cols is not None:
            if not isinstance(cols, list) or len(cols) != record["width_out"]:
                raise ValueError("invalid source column map")
            retained = [(c, i) for i, c in enumerate(cols) if c is not None]
            if not retained or any(_number(c) < 0 for c, _i in retained):
                raise ValueError("empty source column map")
            source = [c for c, _i in retained]
            if any(a >= b for a, b in zip(source, source[1:])):
                raise ValueError("unordered source columns")
            sx = _number(record["scale"])
            if record.get("resample"):
                spec = record["resample"]
                sx = _number(spec["output_size"][0]) / _number(spec["source_size"][0])
            if sx <= 0:
                raise ValueError("invalid resampling scale")
            # Native S pixel centres -> resampled R -> output L. pre_crop handles oversize units;
            # x_out includes clef replicas/joins; column indices include whitespace justification.
            target = (x - _number(record.get("pre_crop", [0, 0])[0])) * sx + (sx - 1) / 2
            k = bisect_left(source, target)
            if k == 0:
                col = retained[0][1]
            elif k == len(source):
                col = retained[-1][1]
            else:
                a, ia = retained[k - 1]
                b, ib = retained[k]
                # Exact on retained columns; interpolate when a seam falls between raster columns
                # or on removed whitespace (there is then no surviving stitch pixel to locate).
                col = ia + (target - a) * (ib - ia) / (b - a)
            return max(0.0, min(1.0, (_number(record["x_out"]) + col) * scale / width))
        # Older audits give only the unit's rendered width: approximate within that width,
        # retaining its real x_out (prefix/joins), without pretending to recover gap operations.
        lo, hi = _span(record["cols_src_out"])
        sx = _number(record["scale"])
        target = (x - _number(record.get("pre_crop", [0, 0])[0])) * sx
        col = _number(record["x_out"]) + (target - lo) / (hi - lo) * _number(record["width_out"])
        return max(0.0, min(1.0, col * scale / width))
    # Without the renderer audit, approximate using the containing unit's native-width share
    # in placement order. Reserve a recorded clef replica; intra-unit justification is unknown.
    total = sum(u["box"][2] - u["box"][0] for u in units)
    prefix = _number(line.get("replica_width", 0)) * scale
    before = sum(u["box"][2] - u["box"][0] for u in units[:units.index(unit)])
    return max(0.0, min(1.0, (prefix + (before + x - unit["box"][0]) / total * (width - prefix)) / width))


def _build(plan: dict, systems: Sequence[dict], jump_record: Optional[dict], episodes: Optional[Sequence[dict]]) -> List[dict]:
    by_system = _index(systems)
    measured = plan.get("measure_reflow") or {}
    by_unit = _index(measured.get("units", []))
    by_line = _index(measured.get("lines", []))
    audit = {(a["line_id"], a["unit_id"]): a for a in (measured.get("audit") or {}).get("placements", [])}
    seams = _index(jump_record["seams"]) if jump_record is not None else {}
    by_pair = {(s["a"], s["b"]): s for s in seams.values()}
    if len(by_pair) != len(seams):
        raise ValueError("duplicate seam pair")
    times = {}
    for s in seams.values():
        for display, key in ((s["a"], "t_a"), (s["b"], "t_b")):
            if key in s:
                times[display] = _span(s[key])
    for e in _index(episodes or []).values():
        times[e["id"]] = _span([e["t_start"], e["t_end"]])
    out = []
    extents = {}
    for u in by_unit.values():
        a, b = extents.get(u["system_id"], (u["box"][0], u["box"][2]))
        extents[u["system_id"]] = (min(a, u["box"][0]), max(b, u["box"][2]))

    def describe(seam, x_frac, boundary=None):
        resolution = seam.get("resolution") or {}
        rejected = bool(seam.get("user_rejected"))
        status = "unverified" if rejected else \
                 "verified" if seam.get("verified") is True and seam.get("kind") in ("jump", "no_shift") else \
                 "resolved" if resolution.get("status") == "resolved" else "unverified"
        evidence = resolution.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("invalid resolution evidence")
        entry = {"id": seam["id"], "status": status, "evidence": list(evidence),
                 "low_ink": "low_ink_window" in evidence, "x_frac": x_frac, "user_rejected": rejected}
        if boundary:
            entry["boundary"] = boundary
        if rejected:
            entry.update(reason="USER_REJECTED", jump_time=times[seam["a"]][1])
        return entry
    for pi, page in enumerate(plan["pages"]):
        size = plan.get("page_px") or page.get("page_px") or page["size"]
        if len(size) != 2 or any(_number(v) <= 0 for v in size):
            raise ValueError("invalid page size")
        for pl in page["placements"]:
            lid = pl.get("line_id") or pl["system_id"]
            rect = [pl[k] for k in ("x", "y", "w", "h")]
            if not isinstance(lid, str) or not lid or any(_number(v) < 0 for v in rect) or min(rect[2:]) <= 0:
                raise ValueError("invalid line placement")
            if _number(pl.get("scale", 1)) <= 0:
                raise ValueError("invalid placement scale")
            units = [by_unit[uid] for uid in pl.get("unit_ids", [])]
            sids = pl.get("system_ids") or list(dict.fromkeys(u["system_id"] for u in units)) or [pl["system_id"]]
            if not isinstance(sids, list) or len(sids) != len(set(sids)):
                raise ValueError("invalid placed system ids")
            if len(units) != len({u["id"] for u in units}) or units and {u["system_id"] for u in units} != set(sids):
                raise ValueError("invalid placed units")
            for u in units:
                x0, y0, x1, y1 = u["box"]
                if _number(x0) < 0 or _number(y0) < 0 or _number(x1) <= x0 or _number(y1) <= y0 or u["system_id"] not in sids:
                    raise ValueError("invalid unit box or system")
            counts = [u.get("measure_count") for u in units]
            if any(c is not None and (isinstance(c, bool) or not isinstance(c, int) or c < 0) for c in counts):
                raise ValueError("invalid measure count")
            sources, found = [], []
            for sid in sids:
                s = by_system[sid]
                jump = (s.get("strip") or {}).get("jump")
                if jump is None or jump_record is None:
                    start, end = _span([s["t_start"], s["t_end"]])
                    sources.append({"system_id": sid, "display": None, "t_start": start, "t_end": end})
                    continue
                su = [u for u in units if u["system_id"] == sid]
                lo, hi = (min(u["box"][0] for u in su), max(u["box"][2] for u in su)) if su else (0, s["strip"]["size"][0])
                owners = jump["owners"]
                if not owners:
                    raise ValueError("missing jump owners")
                pairs = {}
                for owner in owners:
                    a, b = _span(owner["strip_cols"])
                    if a == b:
                        raise ValueError("empty jump owner")
                    if a < hi and b > lo:
                        start, end = times[owner["display"]]
                        sources.append({"system_id": sid, "display": owner["display"], "t_start": start, "t_end": end})
                for a, b in zip(owners, owners[1:]):
                    if a["strip_cols"][1] != b["strip_cols"][0]:
                        raise ValueError("non-contiguous jump owners")
                    pairs[a["strip_cols"][1]] = (a["display"], b["display"])
                # Cuts and owners have matching order on a panorama; match by their shared edge
                # rather than ordinal, since chunking can retain a cut at the chunk's left edge.
                for cut in jump["stitch_cuts"]:
                    x = _number(cut["x"])
                    if not lo <= x < hi:
                        continue
                    pair = pairs.get(x)
                    if pair is None and x == owners[0]["strip_cols"][0]:
                        incoming = [p for p in by_pair if p[1] == owners[0]["display"]]
                        pair = incoming[0] if len(incoming) == 1 else None
                    seam = by_pair[pair]
                    found.append(describe(seam, _x_frac(x, sid, units, pl, audit, by_line.get(lid, {}))))
                left, right = extents.get(sid, (0, s["strip"]["size"][0]))
                for key, boundary, edge, at_edge in (
                    ("unverified_seam_before", "start", lo, lo == left),
                    ("unverified_seam_after", "end", hi - 0.000001, hi == right),
                ):
                    if jump.get(key) and at_edge and seams[jump[key]].get("user_rejected"):
                        found.append(describe(seams[jump[key]],
                                              _x_frac(edge, sid, units, pl, audit, by_line.get(lid, {})), boundary))
            if not sources:
                raise ValueError("missing line sources")
            found = list({s["id"]: s for s in found}.values())
            found.sort(key=lambda s: s["x_frac"])
            statuses = {s["status"] for s in found}
            out.append({"line_id": lid, "page": pi + 1, "rect": rect, "page_size": list(size), "system_ids": list(sids),
                        "measures": sum(counts) if counts and all(c is not None for c in counts) else None,
                        "sources": sources, "seams": found,
                        "attention": "seam_unverified" if "unverified" in statuses else "seam_inferred" if "resolved" in statuses else None})
    return out


def build_line_review(plan: dict, systems: Sequence[dict], jump_record: Optional[dict] = None,
                      episodes: Optional[Sequence[dict]] = None) -> List[dict]:
    """Describe placements without changing inputs; invalid metadata yields an empty list."""
    try:
        return _build(plan, systems, jump_record, episodes)
    except Exception as exc:
        return _failed(exc)


def load_line_review(plan: dict, reflow: dict, *, logger: Optional[Callable[[str], None]] = None) -> List[dict]:
    """Use retained records, else read jump/tracking metadata from the job workspace."""
    try:
        systems = reflow["systems"]
        jump, episodes = reflow.get("jump"), reflow.get("episodes")
        if not isinstance(episodes, list):
            episodes = None  # The public record normally stores an episode count, not the records.
        units = _index((plan.get("measure_reflow") or {}).get("units", []))
        placed = set()
        for page in plan["pages"]:
            for pl in page["placements"]:
                placed.update(pl.get("system_ids") or [units[u]["system_id"] for u in pl.get("unit_ids", [])] or [pl["system_id"]])
        if any(s["id"] in placed and (s.get("strip") or {}).get("jump") is not None for s in systems):
            workspace = reflow.get("workspace")
            if jump is None:
                jump = json.loads((Path(workspace) / "jump.json").read_text(encoding="utf-8"))
            if episodes is None and workspace is not None:
                try:
                    episodes = json.loads((Path(workspace) / "tracking.json").read_text(encoding="utf-8"))["episodes"]
                except FileNotFoundError:
                    pass  # Seam t_a/t_b intervals can supply the same episode times.
        return _build(plan, systems, jump, episodes)
    except Exception as exc:
        return _failed(exc, logger)
