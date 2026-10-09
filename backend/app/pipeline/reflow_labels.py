"""Section labels drawn outside the score region (clean reflow, ``clean_reflow_v1``).

Some videos draw section labels ("Intro", "Verse 1") over the video, far from
the score band, so the applied score region does not contain them
(bF69tpnUk5w: 26 labels). This module

* suggests a label region (``suggest_label_region``): static, text-like lines
  outside the score region whose text changes during the video (at least two
  different texts at one place). A logo, a poster in the room or other text
  that never changes is not a label. The suggestion is only an editable draft;
  the user applies it (``DetectOptions.label_roi``).
* acquires label patches for an applied label region (``acquire_labels``): for
  each system occurrence, the label region is decoded at up to five of the
  occurrence's observation times; only pixels that are text in most samples are
  kept (the moving video behind the text is not), as dark ink on white. The
  text is never recognised, retyped or guessed; the patch is the source image.
  A patch identical to the previous system's patch continues the same section
  and is not placed again (the teacher reference puts a label where a section
  starts); it is kept on record.

Coordinates: source-frame pixels unless noted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

LABELS_VERSION = "reflow_labels-1"
SUGGEST_SAMPLES = 40
STATIC_DT_SEC = 1.5
TOPHAT_PX = 25
TEXT_CONTRAST = 70
SAMPLES_PER_SYSTEM = 5
# Development values from bF69tpnUk5w (labels: 8 text changes in 38 samples, background
# spread 31) against scenery in S1nlqQdnUks (17 / 39, 34) and aOED5zskhGk (10 / 35, 105).
# Not validated on held-out videos; the result is only an editable suggestion.
MAX_CHANGE_RATIO = 0.25
MAX_BG_SPREAD = 60.0


def _rect(roi: Sequence[Sequence[float]]) -> Tuple[int, int, int, int]:
    xs = [float(p[0]) for p in roi]
    ys = [float(p[1]) for p in roi]
    return int(np.floor(min(xs))), int(np.floor(min(ys))), int(np.ceil(max(xs))), int(np.ceil(max(ys)))


def text_mask(gray: np.ndarray, light_text: bool) -> np.ndarray:
    """Thin high-contrast strokes of the given polarity (top-hat / black-hat)."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (TOPHAT_PX, TOPHAT_PX))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT if light_text else cv2.MORPH_BLACKHAT, k)
    return th > TEXT_CONTRAST


def _text_lines(mask: np.ndarray, *, min_h: int = 8, max_h: int = 70) -> List[Dict[str, Any]]:
    """Group letter-like components into horizontal text lines (>= 2 letters)."""
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    letters = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in stats[i])
        if not (min_h <= h <= max_h) or w > 3 * h or a < 12:
            continue
        fill = a / float(w * h)
        # a solid narrow stroke ("I", "l", "1") fills its box; wider solid blocks are not letters
        if not (0.12 <= fill <= (1.0 if w <= 0.4 * h else 0.9)):
            continue
        letters.append((x, y, w, h))
    letters.sort()
    lines: List[List[Tuple[int, int, int, int]]] = []
    for b in letters:
        for line in lines:
            lx, ly, lw, lh = line[-1]
            hs = [q[3] for q in line]
            mh = float(np.median(hs))
            same_size = 0.55 * mh <= b[3] <= 1.8 * mh
            base = abs((b[1] + b[3]) - (ly + lh)) <= 0.45 * mh or abs((b[1] + b[3] / 2) - (ly + lh / 2)) <= 0.45 * mh
            if same_size and base and 0 <= b[0] - (lx + lw) <= 1.6 * mh:
                line.append(b)
                break
        else:
            lines.append([b])
    out = []
    for line in lines:
        if len(line) < 2:
            continue
        x0 = min(q[0] for q in line)
        y0 = min(q[1] for q in line)
        x1 = max(q[0] + q[2] for q in line)
        y1 = max(q[1] + q[3] for q in line)
        out.append({"bbox": [x0, y0, x1, y1], "letters": len(line), "height": int(np.median([q[3] for q in line]))})
    return out


def _iou(a: Sequence[int], b: Sequence[int]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / float(ua) if ua > 0 else 0.0


def _same_text(ma: np.ndarray, mb: np.ndarray) -> bool:
    """Binary line patches show the same text (size and strokes agree)."""
    ha, wa = ma.shape
    hb, wb = mb.shape
    if abs(wa - wb) > 0.15 * max(wa, wb) or abs(ha - hb) > 0.3 * max(ha, hb):
        return False
    h, w = max(ha, hb), max(wa, wb)
    a = cv2.copyMakeBorder(ma.astype(np.uint8), 0, h - ha, 0, w - wa, cv2.BORDER_CONSTANT, value=0)
    b = cv2.copyMakeBorder(mb.astype(np.uint8), 0, h - hb, 0, w - wb, cv2.BORDER_CONSTANT, value=0)
    k = np.ones((3, 3), np.uint8)
    da, db = cv2.dilate(a, k), cv2.dilate(b, k)
    miss = int((a & (1 - db)).sum()) + int((b & (1 - da)).sum())
    return miss <= 0.12 * max(1, int(a.sum()) + int(b.sum()))


def _line_plainness(gray: np.ndarray, mask: np.ndarray, bbox: Sequence[int], height: int) -> Tuple[float, float]:
    """(background spread, stroke spread) around a text line: a label is evenly
    coloured strokes on an even background; scenery that looks like letters is not."""
    h, w = gray.shape
    pad = max(2, int(round(0.5 * height)))
    x0, y0, x1, y1 = max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad)
    g = gray[y0:y1, x0:x1].astype(np.float32)
    m = mask[y0:y1, x0:x1].astype(np.uint8)
    near = cv2.dilate(m, np.ones((5, 5), np.uint8)) > 0
    bg = g[~near]
    st = g[m > 0]
    return (float(np.percentile(bg, 90) - np.percentile(bg, 10)) if bg.size else 255.0,
            float(np.percentile(st, 90) - np.percentile(st, 10)) if st.size else 255.0)


def _static_lines(frame_a: np.ndarray, frame_b: np.ndarray, outside: np.ndarray) -> Tuple[List[Dict[str, Any]], np.ndarray, bool]:
    a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
    light = float(np.median(a[outside])) < 128 if outside.any() else True
    m = text_mask(a, light) & text_mask(b, light) & (np.abs(a.astype(np.int16) - b.astype(np.int16)) < 25) & outside
    lines = _text_lines(m)
    for ln in lines:
        ln["bg_spread"], ln["stroke_spread"] = _line_plainness(a, m, ln["bbox"], ln["height"])
    return lines, m, light


def suggest_label_region(samples: Sequence[Tuple[float, np.ndarray, np.ndarray]], roi: Sequence[Sequence[float]],
                         should_stop: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """Editable draft of a label region from ``(t, frame, frame STATIC_DT_SEC later)`` samples.

    A place holds a label when static text lines there show at least two
    different texts across the samples (a section label that changes). Text
    that is the same in every sample where it appears (a logo, a poster) is
    not a label. Returns ``status`` "suggested" with ``label_roi`` (4 points)
    or "not_found".
    """
    if not samples:
        return {"status": "not_found", "reason": "no_samples"}
    h, w = samples[0][1].shape[:2]
    x0, y0, x1, y1 = _rect(roi)
    outside = np.ones((h, w), bool)
    outside[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = False
    tracks: List[Dict[str, Any]] = []
    for si, (t, fa, fb) in enumerate(samples):
        if should_stop():
            return {"status": "incomplete", "reason": "stopped", "samples_checked": si, "samples": len(samples)}
        lines, mask, _light = _static_lines(fa, fb, outside)
        for ln in lines:
            bx = ln["bbox"]
            patch = mask[bx[1]:bx[3], bx[0]:bx[2]]
            for tr in tracks:
                if _iou(tr["bbox"], bx) >= 0.3 or (abs((tr["bbox"][0] + tr["bbox"][2]) / 2 - (bx[0] + bx[2]) / 2) <= 2 * ln["height"]
                                                   and abs((tr["bbox"][1] + tr["bbox"][3]) / 2 - (bx[1] + bx[3]) / 2) <= ln["height"]):
                    if tr["seen"] and tr["seen"][-1][0] == si:
                        break  # one line per place and sample
                    for k, p in enumerate(tr["texts"]):
                        if _same_text(p, patch):
                            break
                    else:
                        tr["texts"].append(patch)
                        k = len(tr["texts"]) - 1
                    tr["seen"].append((si, k))
                    tr["plain"].append((ln["bg_spread"], ln["stroke_spread"]))
                    tr["union"] = [min(tr["union"][0], bx[0]), min(tr["union"][1], bx[1]), max(tr["union"][2], bx[2]), max(tr["union"][3], bx[3])]
                    break
            else:
                tracks.append({"bbox": list(bx), "union": list(bx), "seen": [(si, 0)], "texts": [patch], "height": ln["height"],
                               "plain": [(ln["bg_spread"], ln["stroke_spread"])]})
    # A label place shows at least two different texts, each held over consecutive
    # samples (a section label stays on screen for a while). Video texture that looks
    # like text changes from sample to sample and does not form such runs.
    for tr in tracks:
        runs: Dict[int, int] = {}
        for (sa, ka), (sb, kb) in zip(tr["seen"], tr["seen"][1:]):
            if sb == sa + 1 and ka == kb:
                runs[ka] = runs.get(ka, 0) + 1
        changes = sum(1 for (_sa, ka), (_sb, kb) in zip(tr["seen"], tr["seen"][1:]) if ka != kb)
        tr["held_texts"] = len(runs)
        tr["changes"] = changes
        tr["steady"] = changes <= MAX_CHANGE_RATIO * max(1, len(tr["seen"]) - 1)
        tr["bg_spread"] = float(np.median([p[0] for p in tr["plain"]]))
        tr["stroke_spread"] = float(np.median([p[1] for p in tr["plain"]]))
    labels = [tr for tr in tracks if tr["held_texts"] >= 2 and tr["steady"] and tr["bg_spread"] <= MAX_BG_SPREAD]
    import os
    if os.environ.get("LABELS_DEBUG"):
        for tr in sorted(tracks, key=lambda x: -len(x["seen"]))[:10]:
            print("track", tr["union"], len(tr["seen"]), tr["held_texts"], tr["changes"], tr["steady"], round(tr["bg_spread"]), round(tr["stroke_spread"]))
    if not labels:
        return {"status": "not_found", "reason": "no_changing_text_outside_the_score_region",
                "static_text_places": len(tracks)}
    best = max(labels, key=lambda tr: (tr["held_texts"], len(tr["seen"])))
    u = best["union"]
    pad_x, pad_y = int(round(1.5 * best["height"])), int(round(0.6 * best["height"]))
    box = [max(0, u[0] - pad_x), max(0, u[1] - pad_y), min(w, u[2] + 2 * pad_x), min(h, u[3] + pad_y)]
    # never overlap the score region
    if box[3] > y0 and box[1] < y0 and x0 <= box[0] < x1:
        box[3] = y0
    return {
        "status": "suggested",
        "label_roi": [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]],
        "evidence": {"texts_held_over_samples": best["held_texts"], "text_changes": best["changes"], "distinct_texts": len(best["texts"]),
                     "samples_with_text": len(best["seen"]), "samples": len(samples),
                     "text_height_px": best["height"], "places_considered": len(tracks)},
    }


def suggest_for_video(video_path: Path, roi: Sequence[Sequence[float]], *, start_sec: float = 0.0,
                      end_sec: Optional[float] = None, samples: int = SUGGEST_SAMPLES,
                      should_stop: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """``should_stop`` is checked between decoded frames and between checked samples; when it
    returns True the result is ``{"status": "incomplete"}`` (never a partial suggestion)."""
    from app.pipeline import notation_envelope as ne
    if should_stop():
        return {"status": "incomplete", "reason": "stopped", "frames_decoded": 0}
    dur = ne.video_duration_cv2(str(video_path))
    if dur <= 0:
        return {"status": "not_found", "reason": "unreadable_video"}
    lo = max(0.0, float(start_sec or 0.0))
    hi = min(dur, float(end_sec)) if end_sec else dur
    ts = [float(t) for t in np.linspace(lo + 0.03 * (hi - lo), lo + 0.97 * (hi - lo) - STATIC_DT_SEC, samples)]
    want = sorted(ts + [t + STATIC_DT_SEC for t in ts])
    decoded = ne.read_frames_cv2(str(video_path), want, should_stop=should_stop)
    if should_stop():
        return {"status": "incomplete", "reason": "stopped", "frames_decoded": len(decoded), "frames": len(want)}
    frames = dict(decoded)
    pairs = [(t, frames[t], frames[t + STATIC_DT_SEC]) for t in ts if t in frames and t + STATIC_DT_SEC in frames]
    return suggest_label_region(pairs, roi, should_stop=should_stop)


# --------------------------------------------------------------------------- #
# Acquisition
# --------------------------------------------------------------------------- #


def label_patch(crops: Sequence[np.ndarray]) -> Optional[Dict[str, Any]]:
    """Static text of label-region crops (source pixels) as dark ink on white, or None.

    Text pixels must be text in most crops (60%, all of them for two or fewer)
    and the patch takes the per-pixel median, so moving video behind the label
    does not survive. Letter-like lines only; a line touching the region edge is
    kept (it is part of the label the user framed)."""
    if not crops:
        return None
    grays = [cv2.cvtColor(c, cv2.COLOR_BGR2GRAY) if c.ndim == 3 else c for c in crops]
    if len({g.shape for g in grays}) != 1:
        return None
    stack = np.stack(grays)
    light = float(np.median(stack)) < 128
    steady = np.median(stack, axis=0)
    masks = np.stack([text_mask(g, light) for g in grays])
    # text in most samples (a moving object may cover a letter in one of them)
    need = len(grays) if len(grays) <= 2 else int(np.ceil(0.6 * len(grays)))
    m = masks.sum(axis=0) >= need
    lines = _text_lines(m)
    if not lines:
        return None
    keep = np.zeros_like(m)
    for ln in lines:
        x0, y0, x1, y1 = ln["bbox"]
        keep[y0:y1, x0:x1] = m[y0:y1, x0:x1]
    ys, xs = np.nonzero(keep)
    th = max(ln["height"] for ln in lines)
    pad = max(2, int(round(0.25 * th)))
    bx = [max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad), min(m.shape[1], int(xs.max()) + 1 + pad), min(m.shape[0], int(ys.max()) + 1 + pad)]
    region = steady[bx[1]:bx[3], bx[0]:bx[2]].astype(np.float32)
    support = cv2.dilate(keep[bx[1]:bx[3], bx[0]:bx[2]].astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if light:
        bg = float(np.percentile(region[~support], 50)) if (~support).any() else 0.0
        ink = np.clip((region - bg) / max(1.0, 255.0 - bg), 0, 1)
    else:
        bg = float(np.percentile(region[~support], 50)) if (~support).any() else 255.0
        ink = np.clip((bg - region) / max(1.0, bg), 0, 1)
    ink[~support] = 0
    img = (255 - np.round(255 * ink)).astype(np.uint8)
    return {"image": cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), "bbox_in_region": bx, "light_text": light,
            "lines": len(lines), "text_height_px": int(th), "mask": keep[bx[1]:bx[3], bx[0]:bx[2]]}


def acquire_labels(
    systems: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    video_path: Path,
    label_roi: Sequence[Sequence[float]],
    out_dir: Path,
    *,
    logger: Callable[[str], None] = lambda _m: None,
    checkpoint: Callable[[], None] = lambda: None,
) -> Dict[str, Any]:
    """Label patches for ``systems`` (display order; each with ``observations``).

    Writes ``label_<system id>.png`` and returns ``{"by_system": {id: record}, ...}``.
    A record has the patch path, its source box, ``placed`` (False when the same
    label continues from the previous system) and ``repeats_system_id``."""
    from app.pipeline import observations as ob

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lx0, ly0, lx1, ly1 = _rect(label_roi)
    obs_t = {o["id"]: float(o["t_sec"]) for o in manifest["observations"]}
    want: Dict[str, List[float]] = {}
    for s in systems:
        ts = [obs_t[m["obs_id"]] for m in s.get("observations", []) if m["obs_id"] in obs_t]
        if ts:
            idx = sorted(set(np.linspace(0, len(ts) - 1, min(SAMPLES_PER_SYSTEM, len(ts))).round().astype(int).tolist()))
            want[s["id"]] = [ts[i] for i in idx]
    times = sorted({t for v in want.values() for t in v})
    # patches go above strips at the strip scale: a source analysed at a work scale
    # (observations.build_manifest) gets its label region at the same scale
    scale = float((manifest.get("work_scale") or {}).get("scale") or 1.0)
    crops: Dict[float, np.ndarray] = {}
    for target, _pts, frame in ob.iter_frames_at(Path(video_path), times):
        region = frame[max(0, ly0):ly1, max(0, lx0):lx1]
        if scale < 1.0:
            region = ob.scale_crop(region, ob.scaled_size((region.shape[1], region.shape[0]), scale))
        crops[round(target, 6)] = region.copy()
    checkpoint()
    by_system: Dict[str, Dict[str, Any]] = {}
    prev: Optional[Tuple[str, np.ndarray]] = None
    placed = 0
    for s in systems:
        ts = want.get(s["id"], [])
        found = label_patch([crops[round(t, 6)] for t in ts if round(t, 6) in crops])
        if found is None:
            prev = None
            continue
        bx = found["bbox_in_region"]
        if scale < 1.0:  # region pixels -> source pixels (pixel-centre convention of cv2.resize)
            bx = [round((v + 0.5) / scale - 0.5, 2) for v in bx]
        rec: Dict[str, Any] = {"bbox_source": [lx0 + bx[0], ly0 + bx[1], lx0 + bx[2], ly0 + bx[3]],
                               "light_text": found["light_text"], "lines": found["lines"],
                               "text_height_px": found["text_height_px"], "samples": len(ts)}
        path = out_dir / f"label_{s['id']}.png"
        if not cv2.imwrite(str(path), found["image"]):
            raise RuntimeError(f"failed to write label patch {path}")
        rec["path"] = str(path)
        if prev is not None and _same_text(prev[1], found["mask"]):
            rec["placed"] = False
            rec["repeats_system_id"] = prev[0]
        else:
            rec["placed"] = True
            placed += 1
            prev = (s["id"], found["mask"])
        by_system[s["id"]] = rec
    logger(f"labels: {len(by_system)} systems with a label patch, {placed} placed (section starts)")
    return {"version": LABELS_VERSION, "label_roi": [list(map(float, p)) for p in label_roi], "by_system": by_system,
            "placed": placed, "found": len(by_system)}


def with_label(strip: np.ndarray, label: Optional[np.ndarray], *, label_x: int, gap_px: int) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The strip with its label patch above it (same source scale, left edge at
    ``label_x`` strip pixels, clamped to >= 0). Returns the unit image and the
    label and strip offsets inside it."""
    if label is None:
        return strip, {"strip_offset": [0, 0]}
    lh, lw = label.shape[:2]
    sh, sw = strip.shape[:2]
    lx = max(0, int(label_x))
    width = max(sw, lx + lw)
    top = lh + max(1, gap_px)
    unit = np.full((top + sh, width, 3), 255, np.uint8)
    unit[0:lh, lx:lx + lw] = label
    unit[top:top + sh, 0:sw] = strip
    return unit, {"label_box": [lx, 0, lx + lw, lh], "strip_offset": [0, top]}
