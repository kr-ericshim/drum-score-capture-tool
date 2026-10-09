"""Shared helpers for the boundary-review protocol (MEASURE_BRIEF milestone 0).

Everything here reads the existing corpus run directories read-only. The
candidate generator uses only the existing staff/barline detector
(``app.pipeline.system_detect``) as proposal source, never the boundary
classifier (``app.pipeline.reflow_boundaries``), so the frozen candidates do
not depend on classifier thresholds.

Coordinates: ``x_strip`` is a column of the cleaned strip PNG; ``x_crop`` =
``x_strip + strip.box_crop[0]`` is a column of the observation's ROI crop.
Seams are half-open: the left side owns columns ``< seam_x``, the right side
owns ``>= seam_x``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.pipeline import system_detect as sd  # noqa: E402

PROTOCOL_VERSION = "boundary_review-1"
CORPUS = Path.home() / "Documents" / "drum-score-corpus"
DEFAULT_RUN = CORPUS / "reflow" / "e2e_r5"
DEFAULT_FREEZE = CORPUS / "reflow" / "boundaries" / "freeze_v1"
VIDEOS = CORPUS / "videos"
SPLIT = {
    "S1nlqQdnUks": "dev",
    "aOED5zskhGk": "dev",
    "Q8XtphO6Xz0": "heldout",
    "01MrRtwZgoE": "heldout",
    "bF69tpnUk5w": "heldout",
}
SAMPLING_SEED = 20261006
PER_VIDEO = {"baseline": 48, "adversarial": 16, "random": 16}
STRATA = ("ordinary", "dense_beams", "lyrics", "repeats", "arcs_voltas", "prefixes", "labels")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pixels_sha256(img: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(img).tobytes())


def canonical_json_sha256(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def seeded_rng(*parts: Any) -> np.random.Generator:
    key = ":".join(str(p) for p in (SAMPLING_SEED,) + tuple(parts))
    return np.random.default_rng(int(sha256_bytes(key.encode())[:16], 16))


# --------------------------------------------------------------------------- #
# Run directory access (read-only)
# --------------------------------------------------------------------------- #


def load_run(run_dir: Path, video: str) -> Dict[str, Any]:
    vdir = Path(run_dir) / video
    result = json.loads((vdir / "result.json").read_text())
    manifest = json.loads((vdir / "manifest.json").read_text())
    occurrences = json.loads((vdir / "occurrences.json").read_text())
    return {"dir": vdir, "result": result, "manifest": manifest, "occurrences": occurrences,
            "obs_by": {o["id"]: o for o in manifest["observations"]}}


def strip_path(vdir: Path, system: Dict[str, Any]) -> Path:
    rel = str(system.get("strip_path") or f"<job>/reflow/strips/strip_{system['id']}.png")
    name = rel.split("/strips/")[-1]
    return Path(vdir) / "strips" / name


def included_systems(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Included (checked) systems with a strip on a score layout. Alternates and
    listed (unchecked) systems are outside the measure denominator."""
    out = []
    for s in run["result"]["reflow"]["systems"]:
        if not s.get("included") or not s.get("strip"):
            continue
        if "-alt" in s["id"]:
            continue
        out.append(s)
    return out


# --------------------------------------------------------------------------- #
# Staff geometry and the existing barline detector on a cleaned strip
# --------------------------------------------------------------------------- #


def estimate_thickness(ink: np.ndarray, lines: Sequence[float], x0: int, x1: int) -> float:
    vals = []
    h = ink.shape[0]
    cols = np.linspace(x0, max(x0, x1 - 1), num=24).astype(int)
    for y in lines:
        yi = int(round(y))
        for c in cols:
            if not (0 <= yi < h) or not ink[yi, c]:
                continue
            a = yi
            while a > 0 and ink[a - 1, c]:
                a -= 1
            b = yi
            while b < h - 1 and ink[b + 1, c]:
                b += 1
            vals.append(b - a + 1)
    if not vals:
        return 1.0
    return float(np.median(vals))


def staff_of(record: Dict[str, Any], ink: np.ndarray) -> Optional[Dict[str, Any]]:
    lines = record.get("staff_y_strip") or []
    gap = record.get("staff_gap_px")
    sx = record.get("staff_x_strip") or []
    if len(lines) != 5 or not gap or len(sx) != 2:
        return None
    x0, x1 = int(sx[0]), int(sx[1])
    x0 = max(0, x0)
    x1 = min(ink.shape[1] - 1, x1)
    if x1 - x0 < 3 * gap:
        return None
    thick = estimate_thickness(ink, lines, x0, x1)
    return {"lines": [float(y) for y in lines], "gap": float(gap), "thick": thick, "x": (x0, x1)}


def nonstaff_of(ink: np.ndarray, st: Dict[str, Any]) -> np.ndarray:
    nonstaff = ink.copy()
    half = st["thick"] / 2 + 1
    for y in st["lines"]:
        nonstaff[max(0, int(y - half)): int(y + half) + 1] = 0
    return nonstaff


def detector_barlines(img: np.ndarray, record: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], np.ndarray]:
    """Barline groups of the existing detector on the cleaned strip (strip coords)."""
    ink = sd.ink_mask(img)
    st = staff_of(record, ink)
    if st is None:
        return None, [], ink
    bars = sd.find_barlines(ink, st, nonstaff_of(ink, st))
    if sd.has_percussion_clef(ink, st):
        bars = [b for b in bars if b["x0"] - st["x"][0] >= 6 * st["gap"] or len(b["strokes"]) > 1]
    return st, bars, ink


def staff_band_rows(st: Dict[str, Any], h: int, pad_gaps: float = 0.5) -> Tuple[int, int]:
    g = st["gap"]
    return max(0, int(np.floor(st["lines"][0] - pad_gaps * g))), min(h, int(np.ceil(st["lines"][4] + pad_gaps * g)) + 1)


def side_dots(nonstaff: np.ndarray, st: Dict[str, Any], x0: int, x1: int) -> Dict[str, bool]:
    """Small blobs in the staff spaces within 1.2 gaps of a barline group (repeat dots)."""
    g = st["gap"]
    l = st["lines"]
    top, bot = int(l[0]), int(np.ceil(l[4]))
    spaces = [((l[1] + l[2]) / 2 - top), ((l[2] + l[3]) / 2 - top)]
    out = {}
    for side, (a, b) in (("left", (max(0, int(x0 - 1.2 * g)), x0)), ("right", (x1 + 1, min(nonstaff.shape[1], int(x1 + 1 + 1.2 * g))))):
        win = nonstaff[top:bot + 1, a:b].astype(np.uint8)
        dots = []
        if win.size:
            n, _lab, stats, cents = cv2.connectedComponentsWithStats(win, connectivity=8)
            for k in range(1, n):
                w, hh, area = stats[k, 2], stats[k, 3], stats[k, 4]
                if w <= 0.6 * g and hh <= 0.6 * g and area >= 2:
                    dots.append((float(cents[k][0]), float(cents[k][1])))
        # a repeat sign has one dot in each of the two middle spaces, one above the other
        found = False
        for p in dots:
            for q in dots:
                if abs(p[1] - spaces[0]) <= 0.3 * g and abs(q[1] - spaces[1]) <= 0.3 * g and abs(p[0] - q[0]) <= 0.3 * g:
                    found = True
        out[side] = found
    return out


def corridor(nonstaff: np.ndarray, rows: Tuple[int, int], start: int, step: int, limit: int) -> Tuple[int, int]:
    """Run of columns from ``start`` (moving by ``step``) with no non-staff ink in ``rows``."""
    band = nonstaff[rows[0]:rows[1]]
    empty = ~band.any(axis=0)
    x = start
    n = 0
    while 0 <= x < band.shape[1] and n < limit and empty[x]:
        x += step
        n += 1
    return (start, x) if step > 0 else (x + 1, start + 1)


def barline_proposals(img: np.ndarray, record: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Internal barline groups with the exact proposed seam (strip coords).

    The staff-end barline closes the system and is not an internal boundary.
    An ordinary or end-repeat group is owned by the left measure (seam in the
    clear corridor to its right); a group with dots on its right side only
    (start repeat) is owned by the right measure (seam in the corridor to its left).
    """
    st, bars, ink = detector_barlines(img, record)
    if st is None:
        return None, []
    g = st["gap"]
    nonstaff = nonstaff_of(ink, st)
    rows = staff_band_rows(st, img.shape[0])
    x_start, x_end = st["x"]
    out = []
    for b in bars:
        x0, x1 = int(b["x0"]), int(b["x1"])
        if x_end - x1 <= 1.0 * g or x0 - x_start <= 1.0 * g:
            continue  # system end / staff start
        dots = side_dots(nonstaff, st, x0, x1)
        start_repeat = dots["right"] and not dots["left"]
        if start_repeat:
            a, z = corridor(nonstaff, rows, x0 - 1, -1, int(4 * g))
            # skip the stroke group itself: the corridor ends at the group's left edge
            seam = (a + z) // 2 if z > a else x0
            owner = "right"
        else:
            a, z = corridor(nonstaff, rows, x1 + 1, 1, int(4 * g))
            seam = (a + z) // 2 if z > a else x1 + 1
            owner = "left"
        out.append({"bar_x0": x0, "bar_x1": x1, "strokes": [list(map(int, s)) for s in b["strokes"]],
                    "dots": dots, "barline_owner": owner, "corridor": [int(a), int(z)], "seam_x": int(seam)})
    return st, out


# --------------------------------------------------------------------------- #
# Heuristic strata tags (sampling/reporting only, never a verdict)
# --------------------------------------------------------------------------- #


def components(mask: np.ndarray) -> List[Tuple[int, int, int, int, int]]:
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [(int(stats[k, 0]), int(stats[k, 1]), int(stats[k, 2]), int(stats[k, 3]), int(stats[k, 4])) for k in range(1, n)]


def strata_tags(img: np.ndarray, st: Dict[str, Any], seam_x: int, *, proposal: Optional[Dict[str, Any]] = None,
                comps: Optional[List[Tuple[int, int, int, int, int]]] = None) -> List[str]:
    g = st["gap"]
    ink = sd.ink_mask(img)
    nonstaff = nonstaff_of(ink, st)
    if comps is None:
        comps = components(nonstaff)
    top, bot = st["lines"][0], st["lines"][4]
    tags = set()
    near = [c for c in comps if c[0] <= seam_x + 3 * g and c[0] + c[2] >= seam_x - 3 * g]
    if proposal is not None and (len(proposal["strokes"]) > 1 or proposal["dots"]["left"] or proposal["dots"]["right"]):
        tags.add("repeats")
    if seam_x - st["x"][0] <= 8 * g:
        tags.add("prefixes")
    for x, y, w, h, area in near:
        cx0, cx1 = x, x + w
        if y >= bot + 1.2 * g and h <= 1.6 * g and w <= 2.5 * g:
            tags.add("lyrics")
        if y + h <= top - 1.0 * g and h >= 0.8 * g and w <= 4 * g and abs((cx0 + cx1) / 2 - seam_x) <= 2.5 * g:
            tags.add("labels")
        fill = area / max(1, w * h)
        if w >= 2.0 * g and fill < 0.25 and h <= 2.0 * g:
            tags.add("arcs_voltas")
    # dense beams: many thick horizontal runs (beams) within +-3 gaps above/below the staff
    a, b = max(0, int(seam_x - 3 * g)), min(img.shape[1], int(seam_x + 3 * g))
    beams = cv2.morphologyEx(nonstaff[:, a:b].astype(np.uint8), cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(0.8 * g)), max(2, int(0.25 * g)))))
    if beams.sum() >= 3 * g * max(2, int(0.25 * g)):
        tags.add("dense_beams")
    if not tags:
        tags.add("ordinary")
    return sorted(tags)


def primary_stratum(tags: Sequence[str]) -> str:
    for s in ("repeats", "arcs_voltas", "labels", "prefixes", "lyrics", "dense_beams", "ordinary"):
        if s in tags:
            return s
    return "ordinary"


# --------------------------------------------------------------------------- #
# Repeated views of the same written system
# --------------------------------------------------------------------------- #


def strip_signature(img: np.ndarray, record: Dict[str, Any]) -> Tuple[np.ndarray, int]:
    """Gray strip, staff-top aligned, downsampled by 4 (for repeat-view collapse)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top = int(round(record["staff_y_strip"][0]))
    return gray, top


def same_written_system(a: Tuple[np.ndarray, int], b: Tuple[np.ndarray, int], gap: float) -> bool:
    ga, ta = a
    gb, tb = b
    if abs(ga.shape[1] - gb.shape[1]) > 2 * gap:
        return False
    up = min(ta, tb)
    down = min(ga.shape[0] - ta, gb.shape[0] - tb)
    w = min(ga.shape[1], gb.shape[1])
    pa = ga[ta - up: ta + down, :w].astype(np.float32)
    pb = gb[tb - up: tb + down, :w].astype(np.float32)
    pa = cv2.resize(pa, (max(1, w // 4), max(1, pa.shape[0] // 4)), interpolation=cv2.INTER_AREA)
    pb = cv2.resize(pb, (max(1, w // 4), max(1, pb.shape[0] // 4)), interpolation=cv2.INTER_AREA)
    best = -1.0
    for dx in (-2, -1, 0, 1, 2):
        xa = pa[:, max(0, dx): pa.shape[1] + min(0, dx)]
        xb = pb[:, max(0, -dx): pb.shape[1] + min(0, -dx)]
        xa = xa - xa.mean()
        xb = xb - xb.mean()
        den = float(np.sqrt((xa * xa).sum() * (xb * xb).sum()))
        if den > 0:
            best = max(best, float((xa * xb).sum() / den))
    return best >= 0.97


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    tmp.replace(path)
