"""Shared primitives of the staged delivered verification (LEDGER_2D_INTERFACE §12).

Contrast space, strong/weak pixels, strip features tiled to local regions, packed masks,
3×3 local windows, grouped findings and digests. Stages A/B/C (reflow_verify_strip,
reflow_verify_plan, reflow_verify_page) build on these and nothing else of each other.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import cv2
import numpy as np

C_STRONG = 64   # strong ink seed (W-D: fringe 12–57, notation 249–253)
C_WEAK = 16     # weak but credible foreground; below this is background
TILE = 16       # features are cut into ≤ 16×16 tiles so every obligation stays local
PAPER_WINDOW = 31


def gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def contrast_map(img: np.ndarray, polarity: str = "light") -> np.ndarray:
    """8-bit contrast against the local paper level (local max of a 3×3-median image over a
    31×31 window; local min for light-on-dark sources)."""
    g = cv2.medianBlur(gray(img), 3)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (PAPER_WINDOW, PAPER_WINDOW))
    if polarity == "light":
        return cv2.subtract(cv2.dilate(g, k), gray(img))
    if polarity == "dark":
        return cv2.subtract(gray(img), cv2.erode(g, k))
    raise ValueError(f"unknown polarity {polarity!r}")


def strong_weak(contrast: np.ndarray):
    strong = contrast >= C_STRONG
    weak = (contrast >= C_WEAK) & ~strong
    return strong, weak


def strip_features(contrast: np.ndarray, *, tile: int = TILE) -> List[Dict[str, Any]]:
    """Features (§12.1): strong components with their attached weak pixels (within 1 px),
    and isolated weak components (kind "weak"; persistence is stage A's decision). Each
    feature is cut along a fixed ``tile`` grid; a part is one feature record."""
    strong, weak = strong_weak(contrast)
    near = cv2.dilate(strong.view(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    attached = strong | (weak & near)
    isolated = weak & ~near
    out: List[Dict[str, Any]] = []
    for kind, mask in (("strong", attached), ("weak", isolated)):
        n, labels = cv2.connectedComponents(mask.view(np.uint8), connectivity=8)
        if n <= 1:
            continue
        ys, xs = np.nonzero(labels)
        lab = labels[ys, xs]
        cell = (ys // tile) * ((labels.shape[1] + tile - 1) // tile) + xs // tile
        key = lab.astype(np.int64) * (cell.max() + 1) + cell
        order = np.argsort(key, kind="stable")
        key, ys, xs, lab = key[order], ys[order], xs[order], lab[order]
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        ends = np.r_[starts[1:], len(key)]
        for a, b in zip(starts, ends):
            fy, fx = ys[a:b], xs[a:b]
            x0, y0, x1, y1 = int(fx.min()), int(fy.min()), int(fx.max()) + 1, int(fy.max()) + 1
            m = np.zeros((y1 - y0, x1 - x0), bool)
            m[fy - y0, fx - x0] = True
            out.append({"id": f"{kind[0]}{int(lab[a])}:{x0 // tile},{y0 // tile}", "kind": kind,
                        "bbox": [x0, y0, x1, y1], "mask": m,
                        "max_contrast": int(contrast[fy, fx].max())})
    return out


def pack_mask(mask: np.ndarray) -> Dict[str, Any]:
    m = np.ascontiguousarray(mask, dtype=bool)
    return {"shape": list(m.shape), "bits": base64.b64encode(np.packbits(m, axis=None).tobytes()).decode("ascii")}


def unpack_mask(rec: Dict[str, Any]) -> np.ndarray:
    h, w = map(int, rec["shape"])
    bits = np.frombuffer(base64.b64decode(rec["bits"], validate=True), np.uint8)
    if bits.size != (h * w + 7) // 8:
        raise ValueError("packed mask size does not match its shape")
    return np.unpackbits(bits, count=h * w).reshape(h, w).astype(bool)


def feature_record(f: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    """JSON form of a feature (mask packed)."""
    return {**{k: v for k, v in f.items() if k != "mask"}, "mask": pack_mask(f["mask"]), **extra}


def paint(shape: Sequence[int], features: Iterable[Dict[str, Any]]) -> np.ndarray:
    """Union of feature masks on a canvas of ``shape``."""
    canvas = np.zeros(tuple(shape[:2]), bool)
    for f in features:
        m = f["mask"] if isinstance(f["mask"], np.ndarray) else unpack_mask(f["mask"])
        x0, y0, x1, y1 = f["bbox"]
        canvas[y0:y1, x0:x1] |= m
    return canvas


def obligation_centres(features: Iterable[Dict[str, Any]], contrast_shape: Sequence[int],
                       contrast: Optional[np.ndarray] = None) -> np.ndarray:
    """Window centres that carry an obligation: strong pixels of strong features, every
    pixel of weak features (§12.1)."""
    feats = list(features)
    centres = paint(contrast_shape, [f for f in feats if f["kind"] == "weak"])
    strong = paint(contrast_shape, [f for f in feats if f["kind"] == "strong"])
    if contrast is not None:
        strong &= contrast >= C_STRONG
    return centres | strong


def window_mean(a: np.ndarray, k: int = 3) -> np.ndarray:
    """Mean over k×k windows centred on each pixel (outside the image counts as 0)."""
    return cv2.blur(a.astype(np.float32), (k, k), borderType=cv2.BORDER_CONSTANT)


def finding(stage: str, severity: str, code: str, *, bbox: Optional[Sequence[int]] = None,
            **extra: Any) -> Dict[str, Any]:
    if stage not in ("A", "B", "C", "I") or severity not in ("fail", "review_required"):
        raise ValueError("invalid finding stage or severity")
    rec: Dict[str, Any] = {"stage": stage, "severity": severity, "code": code}
    if bbox is not None:
        rec["bbox"] = [int(v) for v in bbox]
    rec.update(extra)
    return rec


def group_findings(fail: np.ndarray, stage: str, severity: str, code: str, *,
                   max_findings: int = 2000, **extra: Any) -> List[Dict[str, Any]]:
    """One finding per 8-connected group of failing window centres (grouped after testing)."""
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(fail.astype(np.uint8), connectivity=8)
    order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1 if n > 1 else []
    out = []
    for i in order[:max_findings]:
        x, y, w, h, area = stats[i]
        out.append(finding(stage, severity, code, bbox=[x, y, x + w, y + h], pixels=int(area), **extra))
    if n - 1 > max_findings:
        out.append(finding(stage, severity, code, truncated=int(n - 1 - max_findings), **extra))
    return out


def pixels_sha256(image: np.ndarray) -> str:
    a = np.ascontiguousarray(image)
    digest = hashlib.sha256(str((a.shape, a.dtype.str)).encode())
    digest.update(memoryview(a))
    return digest.hexdigest()


def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
