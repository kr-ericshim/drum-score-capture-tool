"""Source-class gate (STRATEGY Step 2A): what kind of picture is the score inside the ROI?

The clean-reflow adapter assumes the notation sits on an opaque plate ("paper"): a flat light
page with dark ink, or a flat dark page with light ink (dark-theme score). A dark plate may be
semi-opaque over video (the video shows through dimly); such plates get a ``translucent_plate``
flag and the job is refused like composited live imagery (reflow_pipeline.analyse_source).

Notation composited over live imagery (white notes drawn straight over the camera picture) is a
different source class: the "paper" between the staff lines is the video itself, with
full-contrast texture. The adapter would keep that video in the strips,
so such a source is refused with evidence instead of processed.

Everything here is measured inside the staves (between the top and bottom staff line, over the
staff's own width), where an opaque page can only show paper, ink, or a playback highlight. ROI
margins outside the score therefore do not count.

Per sampled frame:
1. Staff detection in both polarities: rows where a thin-horizontal-line response (vertical
   top-hat) covers a large part of the width, grouped into five evenly spaced lines. The
   polarity whose staves are found is the ink polarity (dark ink = light paper). When both
   polarities find staves (the paper rows between dark lines are thin light "lines" too), the
   ink polarity is the one with the larger ink-minus-plate contrast inside its staves.
2. Background plate inside the staves: a median filter about three staff spaces wide removes the
   ink (a minority of pixels inside a staff). ``C`` = ink level minus plate level.
3. Evidence, all relative to ``C``:
   - ``off_plate``: fraction of the plate more than 0.25 C from its median level (texture or a
     second fill such as a highlight band);
   - ``textured``: fraction of the plate whose local standard deviation (one staff space) is
     above 0.05 C (camera picture; a flat band is textured only along its two edges);
   - ``ink_like``: fraction of the plate more than 0.5 C toward the ink (background that looks
     like ink: a white wall behind white notes);
   - ``changed``: fraction of the plate that moved more than 0.25 C since the previous sampled
     frame (rows inside the staves of both frames). Reported only: playback bands move too,
     and tripod shots of a static room barely change between samples.
   A frame is "live" when ``off_plate >= LIVE_OFF_PLATE`` and the off-plate part is textured
   or ink-like (``textured >= LIVE_TEXTURED`` or ``ink_like >= LIVE_INK_LIKE``).
4. The source is class ``composited_live`` when at least ``LIVE_FRAME_FRAC`` of the frames with
   staves are live. Frames without staves (intro, outro, cut-aways) do not vote. Fewer than
   ``MIN_SCORE_FRAMES`` frames with staves -> ``unknown`` (review required).

Tuned on 6 opaque dev sources (light paper, and bF69's dark semi-opaque plate) and 12
transparent-overlay studio videos (corpus ``videos_transparent``): per frame, the dev sources
show off_plate <= 0.07 and ink_like <= 0.02 (medians 0.00); the overlays show
median off_plate 0.17-0.61 with median textured >= 0.10 or ink_like >= 0.06.

Pure function on frames: ``classify_frames``. ``sample_roi_frames`` decodes a few dozen seeked
frames in memory (nothing is written to disk).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

VERSION = "source_class-3"  # -3: both polarities with staves -> the larger ink contrast is the ink

CLASS_LIGHT_PAPER = "opaque_light_paper"
CLASS_DARK_PAPER = "opaque_dark_paper"
CLASS_LIVE = "composited_live"
CLASS_UNKNOWN = "unknown"  # no staff found in the sampled frames: the gate does not decide
FLAG_TRANSLUCENT = "translucent_plate"

SAMPLES = 24
MAX_WORK_WIDTH = 1600  # frames wider than this are analysed downscaled

# staff detection
LINE_TOPHAT_PX = 9  # vertical top-hat height (work pixels): thicker than a staff line
LINE_MIN_RESPONSE = 18  # gray levels above the local plate
LINE_ROW_MIN_FRAC = 0.22  # a staff-line row responds over at least this fraction of the width
STAFF_GAP_RANGE = (4.0, 60.0)
STAFF_GAP_TOL = 0.22  # max relative deviation of the four gaps from their median
STAFF_GAP_SAME = 0.2  # other staves of a frame keep the strongest staff's gap within this

# per-frame evidence thresholds (relative to the ink contrast C)
MIN_CONTRAST = 40.0
OFF_PLATE_DELTA = 0.25
INK_LIKE_DELTA = 0.5
CHANGED_DELTA = 0.25
TEXTURE_DELTA = 0.05
LIVE_OFF_PLATE = 0.10
LIVE_TEXTURED = 0.05
LIVE_INK_LIKE = 0.03
# source decision
LIVE_FRAME_FRAC = 0.30
MIN_SCORE_FRAMES = 4
TRANSLUCENT_TEXTURED = 0.005  # dim texture below the live-imagery refusal threshold


def _odd(n: float) -> int:
    k = max(3, int(round(n)))
    return k if k % 2 == 1 else k + 1


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        g = frame
    else:
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if g.dtype != np.uint8:
        g = np.clip(g, 0, 255).astype(np.uint8)
    if g.shape[1] > MAX_WORK_WIDTH:
        s = MAX_WORK_WIDTH / g.shape[1]
        g = cv2.resize(g, (MAX_WORK_WIDTH, max(1, int(round(g.shape[0] * s)))), interpolation=cv2.INTER_AREA)
    return g


def _line_rows(ink: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Per-row fraction of the width covered by a thin horizontal line response, and the mask."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, LINE_TOPHAT_PX))
    resp = cv2.morphologyEx(ink, cv2.MORPH_TOPHAT, kernel)
    mask = resp > LINE_MIN_RESPONSE
    prof = mask.mean(axis=1)
    # a 2-3 px line spreads over adjacent rows: merge them
    prof = np.maximum(prof, np.maximum(np.r_[0.0, prof[:-1]], np.r_[prof[1:], 0.0]))
    return prof, mask


def _find_staves(prof: np.ndarray) -> List[Tuple[int, int, float]]:
    """Five evenly spaced line rows -> (top_row, bottom_row, gap), strongest first, no overlap.

    Line centres are local maxima of the row profile (a run of beam rows next to the top line
    must not merge with it). Every evenly spaced 5-sequence is a candidate, scored by its
    weakest line."""
    n = prof.size
    cand = [y for y in range(n) if prof[y] >= LINE_ROW_MIN_FRAC
            and prof[y] >= (prof[y - 1] if y > 0 else 0.0) and prof[y] >= (prof[y + 1] if y + 1 < n else 0.0)]
    centres: List[int] = []
    for y in sorted(cand, key=lambda r: -prof[r]):  # non-maximum suppression within 2 rows
        if all(abs(y - c) > 2 for c in centres):
            centres.append(y)
    centres.sort()
    seqs: List[Tuple[float, int, int, float]] = []
    for i, c0 in enumerate(centres):
        for c1 in centres[i + 1:]:
            gap = float(c1 - c0)
            if gap > STAFF_GAP_RANGE[1]:
                break
            if gap < STAFF_GAP_RANGE[0]:
                continue
            seq = [c0, c1]
            for _k in range(3):
                want = seq[-1] + gap
                near = [c for c in centres if abs(c - want) <= max(1.5, STAFF_GAP_TOL * gap)]
                if not near:
                    break
                seq.append(min(near, key=lambda c: abs(c - want)))
            if len(seq) < 5:
                continue
            gaps = np.diff(seq).astype(float)
            med = float(np.median(gaps))
            if med <= 0 or np.any(np.abs(gaps - med) > max(1.5, STAFF_GAP_TOL * med)):
                continue
            seqs.append((float(min(prof[y] for y in seq)), seq[0], seq[-1], med))
    staves: List[Tuple[int, int, float]] = []
    for _score, top, bottom, med in sorted(seqs, key=lambda q: -q[0]):
        # one score has one staff size: a sequence at another spacing is beams or text rows
        if staves and abs(med - staves[0][2]) > STAFF_GAP_SAME * staves[0][2]:
            continue
        if all(bottom < t - 2 or top > b + 2 for t, b, _g in staves):
            staves.append((top, bottom, med))
    return sorted(staves)


def _staff_columns(mask: np.ndarray, staff: Tuple[int, int, float]) -> Tuple[int, int]:
    top, bottom, gap = staff
    band = mask[max(0, top - 1): bottom + 2]
    cols = np.flatnonzero(band.mean(axis=0) >= 3.0 / max(1, band.shape[0]))
    if cols.size < 10:
        return 0, mask.shape[1]
    return int(np.percentile(cols, 1)), int(np.percentile(cols, 99)) + 1


def _ink_contrast(ink: np.ndarray, staves: List[Tuple[int, int, float]], mask: np.ndarray) -> float:
    """Ink level minus plate level inside ``staves`` for one polarity (0 when too small to judge)."""
    gap = float(np.median([g for _t, _b, g in staves]))
    plate = cv2.medianBlur(ink, min(_odd(3.0 * gap), 255))
    region = np.zeros(ink.shape, dtype=bool)
    for staff in staves:
        x0, x1 = _staff_columns(mask, staff)
        region[staff[0]: staff[1] + 1, x0:x1] = True
    if region.sum() < 50:
        return 0.0
    return float(np.percentile(ink[region], 99.0)) - float(np.median(plate[region]))


def frame_evidence(frame: np.ndarray) -> Dict[str, Any]:
    """Staves, ink polarity and plate evidence of one ROI frame (BGR or gray)."""
    gray = _to_gray(frame)
    cands: List[Dict[str, Any]] = []
    for polarity, ink in (("light_ink", gray), ("dark_ink", 255 - gray)):
        prof, mask = _line_rows(ink)
        staves = _find_staves(prof)
        if not staves:
            continue
        strength = float(np.mean([prof[max(0, t): b + 1].max() for t, b, _g in staves]))
        cands.append({"polarity": polarity, "ink": ink, "mask": mask, "staves": staves, "strength": strength,
                      "ink_contrast": _ink_contrast(ink, staves, mask)})
    if not cands:
        return {"score": False}
    if len(cands) == 2 and cands[0]["ink_contrast"] != cands[1]["ink_contrast"]:
        # the thin paper rows between dark staff lines are "lines" in the other polarity too;
        # the ink polarity is the one whose ink stands out from its plate
        best = max(cands, key=lambda c: c["ink_contrast"])
    else:
        best = max(cands, key=lambda c: (len(c["staves"]), c["strength"]))
    ink = best["ink"]
    gap = float(np.median([g for _t, _b, g in best["staves"]]))
    k = min(_odd(3.0 * gap), 255)
    plate = cv2.medianBlur(ink, k)
    region = np.zeros(ink.shape, dtype=bool)
    for staff in best["staves"]:
        x0, x1 = _staff_columns(best["mask"], staff)
        region[staff[0]: staff[1] + 1, x0:x1] = True
    if region.sum() < 50:
        return {"score": False}
    vals = plate[region].astype(np.float32)
    level = float(np.median(vals))
    ink_level = float(np.percentile(ink[region], 99.0))
    contrast = max(MIN_CONTRAST, ink_level - level)
    off_plate = float(np.mean(np.abs(vals - level) > OFF_PLATE_DELTA * contrast))
    ink_like = float(np.mean(vals - level > INK_LIKE_DELTA * contrast))
    # local texture of the plate: std over about one staff space (a flat fill or band is ~0)
    pf = plate.astype(np.float32)
    w = _odd(gap)
    mean = cv2.boxFilter(pf, -1, (w, w))
    sq = cv2.boxFilter(pf * pf, -1, (w, w))
    std = np.sqrt(np.maximum(0.0, sq - mean * mean))
    textured = float(np.mean(std[region] > TEXTURE_DELTA * contrast))
    dim_textured = float(np.mean(std[region] > max(1.5, 0.008 * contrast)))
    plate_spread = float(np.percentile(vals, 90) - np.percentile(vals, 10))
    return {
        "score": True,
        "polarity": best["polarity"],
        "staves": len(best["staves"]),
        "gap_px": round(gap, 2),
        "plate_level": round(level if best["polarity"] == "dark_ink" else 255.0 - level, 1),
        "contrast": round(contrast, 1),
        "off_plate": round(off_plate, 4),
        "ink_like": round(ink_like, 4),
        "textured": round(textured, 4),
        "dim_textured": round(dim_textured, 4),
        "plate_spread": round(plate_spread, 2),
        "_plate": plate,
        "_region": region,
        "_contrast": contrast,
        "_polarity": best["polarity"],
    }


def _changed(prev: Dict[str, Any], cur: Dict[str, Any]) -> Optional[float]:
    if not (prev.get("score") and cur.get("score")) or prev["_polarity"] != cur["_polarity"]:
        return None
    if prev["_plate"].shape != cur["_plate"].shape:
        return None
    region = prev["_region"] & cur["_region"]
    if region.sum() < 50:
        return None
    diff = np.abs(prev["_plate"][region].astype(np.float32) - cur["_plate"][region].astype(np.float32))
    contrast = min(prev["_contrast"], cur["_contrast"])
    return float(np.mean(diff > CHANGED_DELTA * contrast))


def _live(ev: Dict[str, Any]) -> bool:
    """The plate inside the staves is not one flat fill: a large part of it is off the plate
    level, and that part is textured or as bright/dark as the ink. A flat highlight band is off
    the plate level but neither textured nor ink-like."""
    return ev["off_plate"] >= LIVE_OFF_PLATE and (ev["textured"] >= LIVE_TEXTURED or ev["ink_like"] >= LIVE_INK_LIKE)


def classify_frames(frames: Sequence[np.ndarray], times: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """Source class of the score in a sequence of ROI frames (time order).

    Returns {"class", "evidence", "version"}. ``class`` is one of opaque_light_paper,
    opaque_dark_paper, composited_live, unknown (too few frames with staves to decide)."""
    per: List[Dict[str, Any]] = []
    prev: Dict[str, Any] = {"score": False}
    for i, frame in enumerate(frames):
        ev = frame_evidence(frame)
        if ev.get("score"):
            ev["changed"] = _changed(prev, ev)
            ev["live"] = _live(ev)
        prev = ev
        public = {k: v for k, v in ev.items() if not k.startswith("_")}
        if times is not None:
            public["t"] = round(float(times[i]), 2)
        per.append(public)
    score = [e for e in per if e.get("score")]
    live = [e for e in score if e["live"]]
    dark = [e for e in score if e["polarity"] == "light_ink"]

    def med(key: str) -> Optional[float]:
        vals = [e[key] for e in score if e.get(key) is not None]
        return round(float(np.median(vals)), 4) if vals else None

    evidence: Dict[str, Any] = {
        "frames": len(per),
        "score_frames": len(score),
        "live_frames": len(live),
        "live_frame_frac": round(len(live) / len(score), 3) if score else None,
        "light_ink_frac": round(len(dark) / len(score), 3) if score else None,
        "median_off_plate": med("off_plate"),
        "median_ink_like": med("ink_like"),
        "median_changed": med("changed"),
        "median_textured": med("textured"),
        "median_contrast": med("contrast"),
        "thresholds": {"live_off_plate": LIVE_OFF_PLATE, "live_ink_like": LIVE_INK_LIKE,
                       "live_textured": LIVE_TEXTURED, "live_frame_frac": LIVE_FRAME_FRAC,
                       "min_score_frames": MIN_SCORE_FRAMES},
        "per_frame": per,
    }
    if len(score) < MIN_SCORE_FRAMES:
        cls = CLASS_UNKNOWN
        evidence["reason"] = f"staves found in {len(score)} of {len(per)} sampled frames"
    elif len(live) >= LIVE_FRAME_FRAC * len(score):
        cls = CLASS_LIVE
        evidence["reason"] = (f"{len(live)} of {len(score)} frames with staves show textured or changing "
                              "background between the staff lines (notation over live imagery)")
    else:
        cls = CLASS_DARK_PAPER if len(dark) * 2 > len(score) else CLASS_LIGHT_PAPER
        evidence["reason"] = f"{len(score) - len(live)} of {len(score)} frames with staves show a flat plate"
    # Retain the polarity class for existing consumers, but dark paper with dim
    # plate texture is conditional rather than clean-complete. Static texture
    # counts too: absence of motion does not prove an opaque plate.
    textured_dark = [e for e in dark if e["dim_textured"] >= TRANSLUCENT_TEXTURED
                     and e["plate_spread"] >= max(5.0, 0.025 * e["contrast"])]
    flags = [FLAG_TRANSLUCENT] if cls == CLASS_DARK_PAPER and len(textured_dark) >= LIVE_FRAME_FRAC * len(score) else []
    evidence["translucent_frames"] = len(textured_dark)
    evidence["thresholds"]["translucent_textured"] = TRANSLUCENT_TEXTURED
    reasons = (["TRANSLUCENT_PLATE_GRAY"] if flags else []) + (["SOURCE_CLASS_UNKNOWN"] if cls == CLASS_UNKNOWN else [])
    return {"class": cls, "flags": flags, "review_required": bool(reasons),
            "review_reasons": reasons, "evidence": evidence, "version": VERSION}


def sample_roi_frames(video_path: Path, roi: Sequence[Sequence[float]], start: float, end: float,
                      *, samples: int = SAMPLES) -> Tuple[List[np.ndarray], List[float]]:
    """``samples`` seeked ROI crops over [start, end), in memory. Seeking is approximate; the
    gate only needs frames spread over the range."""
    from app.pipeline import observations as ob

    frames: List[np.ndarray] = []
    times: List[float] = []
    span = max(0.0, float(end) - float(start))
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return frames, times
        for k in range(samples):
            t = float(start) + span * (k + 0.5) / samples
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            frames.append(ob.crop_roi(frame, roi))
            times.append(t)
    finally:
        cap.release()
    return frames, times


def classify_source(video_path: Path, roi: Sequence[Sequence[float]], start: float = 0.0,
                    end: Optional[float] = None, *, samples: int = SAMPLES) -> Dict[str, Any]:
    """Sample the video over [start, end) and classify. ``end`` None or past the end = the end
    of the video."""
    from app.pipeline import observations as ob

    duration = float(ob.probe_video(Path(video_path)).duration_sec)
    stop = duration if end is None else min(float(end), duration)
    frames, times = sample_roi_frames(Path(video_path), roi, float(start or 0.0), stop, samples=samples)
    result = classify_frames(frames, times)
    result["evidence"]["range"] = [round(float(start or 0.0), 3), round(stop, 3)]
    return result
