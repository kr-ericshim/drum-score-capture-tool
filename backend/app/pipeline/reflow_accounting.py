"""Pixel ledger for measure units (MEASURE_BRIEF milestone 1).

Each unit owns a half-open region of one native-resolution asset (a cleaned strip, or the
uncut strip of a cut preview tail). For every asset the ownership masks must partition the
asset: each pixel, and in particular each protected content pixel (ink, anti-aliased fringe,
a one-pixel dot), has exactly one owner. Splitting an asset into its units and pasting the
units back must reproduce every pixel value exactly.

Staff-scaffold regeneration and clef replicas belong to later milestones; their ledgers are
present and empty here (``scaffold_operations``, ``replicas``).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ACCOUNTING_VERSION = "reflow_accounting-1"


def unit_mask(unit: Dict[str, Any], shape: Tuple[int, int]) -> np.ndarray:
    """Bool ownership mask of a unit on its asset (``_mask`` when given, else its half-open box)."""
    m = unit.get("_mask")
    if m is not None:
        if m.shape != tuple(shape):
            raise ValueError(f"{unit['id']}: mask shape {m.shape} != asset {shape}")
        return m.astype(bool)
    x0, y0, x1, y1 = (int(v) for v in unit["box"])
    out = np.zeros(shape, bool)
    out[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    return out


def _sha(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes() + str(a.shape).encode()).hexdigest()


def split_units(image: np.ndarray, units: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Independent copies of each unit's pixels (bounding box + mask), as layout would carry them."""
    h, w = image.shape[:2]
    out = []
    for u in units:
        m = unit_mask(u, (h, w))
        ys, xs = np.nonzero(m)
        if not len(ys):
            out.append({"unit_id": u["id"], "origin": (0, 0), "pixels": image[:0, :0].copy(), "mask": m[:0, :0].copy()})
            continue
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
        out.append({"unit_id": u["id"], "origin": (x0, y0), "pixels": image[y0:y1, x0:x1].copy(), "mask": m[y0:y1, x0:x1].copy()})
    return out


def reassemble(shape: Tuple[int, ...], pieces: Sequence[Dict[str, Any]], dtype=np.uint8) -> Tuple[np.ndarray, np.ndarray]:
    """Paste unit pieces back at native resolution. Returns (canvas, write count per pixel)."""
    canvas = np.zeros(shape, dtype)
    count = np.zeros(shape[:2], np.uint16)
    for p in pieces:
        x0, y0 = p["origin"]
        ph, pw = p["mask"].shape
        if not ph or not pw:
            continue
        region = canvas[y0:y0 + ph, x0:x0 + pw]
        region[p["mask"]] = p["pixels"][p["mask"]]
        count[y0:y0 + ph, x0:x0 + pw] += p["mask"].astype(np.uint16)
    return canvas, count


def account_asset(image: np.ndarray, units: Sequence[Dict[str, Any]], protected: Optional[np.ndarray] = None,
                  *, asset_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Ownership partition, protected-pixel ledger and exact split-and-reassemble check of one asset."""
    h, w = image.shape[:2]
    owners = np.zeros((h, w), np.uint16)
    entries = []
    asset_sha256 = asset_sha256 or _sha(image)
    for u in units:
        m = unit_mask(u, (h, w))
        owners += m.astype(np.uint16)
        entries.append({
            "unit_id": u["id"],
            "occurrence_id": u.get("owner_occurrence_id") or u.get("occurrence_id"),
            "asset_sha256": asset_sha256,
            "box": [int(v) for v in u["box"]],
            "pixels": int(m.sum()),
            "protected_px": int((m & protected).sum()) if protected is not None else None,
            "mask_sha256": _sha(np.packbits(m)),
        })
    pieces = split_units(image, units)
    canvas, count = reassemble(image.shape, pieces, image.dtype)
    lost = count == 0
    dup = count > 1
    mismatch = np.any(canvas != image, axis=-1) if image.ndim == 3 else canvas != image
    out = {
        "version": ACCOUNTING_VERSION,
        "asset_sha256": asset_sha256,
        "size": [int(w), int(h)],
        "pixels": int(h * w),
        "owned_once_px": int((owners == 1).sum()),
        "lost_px": int(lost.sum()),
        "duplicated_px": int(dup.sum()),
        "mismatched_px": int((mismatch & ~lost).sum()),
        "exact_reconstruction": bool(not lost.any() and not dup.any() and not mismatch.any()),
        "owner_map_sha256": _sha(owners),
        "entries": entries,
    }
    if protected is not None:
        out["protected_px"] = int(protected.sum())
        out["protected_lost_px"] = int((protected & lost).sum())
        out["protected_duplicated_px"] = int((protected & dup).sum())
    return out


def cut_strip_consistency(strip: np.ndarray, uncut: np.ndarray, record: Dict[str, Any]) -> Dict[str, Any]:
    """The placed (cut) strip must be exactly the uncut strip left of the tail seam, at its row offset."""
    box = record.get("box_crop") or [0, 0, 0, 0]
    ubox = (record.get("uncut") or {}).get("box_crop") or box
    dy = int(box[1]) - int(ubox[1])
    dx = int(box[0]) - int(ubox[0])
    h, w = strip.shape[:2]
    if dy < 0 or dx < 0 or dy + h > uncut.shape[0] or dx + w > uncut.shape[1]:
        return {"consistent": False, "reason": "cut strip outside the uncut strip", "row_offset": dy, "col_offset": dx}
    same = np.array_equal(uncut[dy:dy + h, dx:dx + w], strip)
    # rows of the uncut strip that the cut strip trimmed must be blank paper left of the seam
    seam = dx + w
    rest = np.ones(uncut.shape[0], bool)
    rest[dy:dy + h] = False
    trimmed = uncut[rest, :seam]
    return {"consistent": bool(same), "row_offset": dy, "col_offset": dx,
            "trimmed_rows": int(rest.sum()), "trimmed_rows_min_gray": int(trimmed.min()) if trimmed.size else None}


def totals(accounts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    keys = ("pixels", "lost_px", "duplicated_px", "mismatched_px", "protected_px", "protected_lost_px", "protected_duplicated_px")
    out: Dict[str, Any] = {k: int(sum(a.get(k) or 0 for a in accounts)) for k in keys}
    out["assets"] = len(accounts)
    out["exact_reconstruction"] = bool(accounts) and all(a["exact_reconstruction"] for a in accounts)
    out["scaffold_operations"] = []
    out["replicas"] = []
    return out
