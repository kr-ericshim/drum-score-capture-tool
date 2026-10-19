"""Observation manifest: timestamped score observations with ROI provenance.

Design reference: docs/archive/reflow/DESIGN_astra.md sections 5 ("Timestamp provenance
needs extension", "Data shapes") and 2 ("Shared acquisition/tracking
defaults").

Why a manifest: extraction writes sequential ``frame_%06d.png`` names after an
FFmpeg ``fps`` filter (extract.py ``_extract_with_ffmpeg``), so a file name is
not a timestamp contract. Here every observation carries the
presentation timestamp of the decoded source frame.

Sampling: a coarse pass at ``coarse_hz`` (2 Hz) over the whole source; every
coarse pair whose ROI content is not "same" by the overlay-aware page
comparator (page_diff.compare_frames) gets a fine window of +-``fine_window``
seconds at ``fine_hz`` (8 Hz) around the pair's midpoint. Frames are decoded
sequentially with OpenCV's FFmpeg backend; ``CAP_PROP_POS_MSEC`` after a grab
is the decoded frame's PTS (cross-checked against ffprobe ``pts_time``).

This module does not change any existing pipeline behavior.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import page_diff
from app.pipeline import system_detect
from app.pipeline.rectify import _order_points, _warp_sheet

SCHEMA_VERSION = 2  # 2: row_band field; envelope_bbox = attached ink chain (system_detect.attached_envelope)
MANIFEST_KIND = "observation_manifest"
TIME_BASIS = "source_pts"


# --------------------------------------------------------------------------- #
# ROI geometry
# --------------------------------------------------------------------------- #


def roi_source_to_crop(roi: Sequence[Sequence[float]]) -> Tuple[List[float], Tuple[int, int, int, int]]:
    """3x3 row-major transform from source pixels to crop pixels.

    Mirrors rectify._warp_sheet: an axis-aligned rectangle is sliced with
    ``ceil`` of the top-left corner (pure translation); any other quad is a
    perspective warp. Returns (matrix, (x0, y0, x1, y1) slice for rectangles or
    (0, 0, w, h) output size for warps).
    """
    pts = _order_points(np.array(roi, dtype=np.float32).reshape(4, 2))
    tl, tr, br, bl = pts
    if np.allclose([tl[1], tr[0], br[1], bl[0]], [tr[1], br[0], bl[1], tl[0]]):
        x1, y1 = np.ceil(tl).astype(int)
        x2, y2 = np.floor(br).astype(int)
        return [1.0, 0.0, float(-x1), 0.0, 1.0, float(-y1), 0.0, 0.0, 1.0], (int(x1), int(y1), int(x2), int(y2))
    width = max(int(np.linalg.norm(br - bl)), int(np.linalg.norm(tr - tl)))
    height = max(int(np.linalg.norm(tr - br)), int(np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(pts, dst)
    return [float(v) for v in m.reshape(-1)], (0, 0, width, height)


def crop_roi(frame: np.ndarray, roi: Sequence[Sequence[float]]) -> np.ndarray:
    """Crop exactly like the app's rectification (without enhancement)."""
    return _warp_sheet(frame, _order_points(np.array(roi, dtype=np.float32).reshape(4, 2)))


# Work scale: a source whose staves are much larger than any page size needs (a 4K video)
# is analysed at a reduced size. Every record stays in crop pixels; source_to_crop includes
# the scale, so source coordinates map back exactly. A4 at 300 dpi needs 17.7 px per staff
# space at the default 1.5 mm (29.5 px at the 2.5 mm maximum, reflow_layout.LOW_EFFECTIVE_DPI
# 180 keeps that at >= 17.7 px of source); 1080p corpus sources measure 16-24 px and are
# never scaled.
WORK_GAP_PX = 20.0  # staff space after scaling
WORK_SCALE_TRIGGER_GAP_PX = 28.0  # scale only when the probed staff space is larger than this
WORK_SCALE_PROBES = 7


def scaled_size(size: Tuple[int, int], scale: float) -> Tuple[int, int]:
    w, h = int(size[0]), int(size[1])
    if scale >= 1.0:
        return w, h
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def scale_crop(crop: np.ndarray, size: Optional[Sequence[int]]) -> np.ndarray:
    """``crop`` resized (area average) to ``size`` = [w, h]; unchanged when it already has that size."""
    if size is None:
        return crop
    w, h = int(size[0]), int(size[1])
    if crop.shape[1] == w and crop.shape[0] == h:
        return crop
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA)


def crop_observation(frame: np.ndarray, roi: Sequence[Sequence[float]], crop_size: Optional[Sequence[int]] = None) -> np.ndarray:
    """The ROI crop at the manifest's work size (``crop_size`` [w, h]; None = native)."""
    return scale_crop(crop_roi(frame, roi), crop_size)


def scaled_source_to_crop(s2c: Sequence[float], native: Tuple[int, int], scaled: Tuple[int, int]) -> List[float]:
    """``s2c`` followed by cv2.resize from ``native`` to ``scaled`` (pixel-centre convention)."""
    if tuple(native) == tuple(scaled):
        return [float(v) for v in s2c]
    sx = scaled[0] / float(native[0])
    sy = scaled[1] / float(native[1])
    r = np.array([[sx, 0.0, 0.5 * sx - 0.5], [0.0, sy, 0.5 * sy - 0.5], [0.0, 0.0, 1.0]])
    m = r @ np.array(s2c, dtype=np.float64).reshape(3, 3)
    return [float(v) for v in m.reshape(-1)]


def source_to_crop_point(source_to_crop: Sequence[float], x: float, y: float) -> Tuple[float, float]:
    m = np.array(source_to_crop, dtype=np.float64).reshape(3, 3)
    v = m @ np.array([x, y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


def probe_work_scale(video_path: Path, roi: Sequence[Sequence[float]], start: float, end: float,
                     *, probes: int = WORK_SCALE_PROBES) -> Dict[str, Any]:
    """Staff space of the score inside ``roi`` from a few seeked frames, and the work scale.

    Seeking is approximate, which is fine here: the frames only size the analysis. No staff
    found -> scale 1 (native)."""
    gaps: List[float] = []
    times: List[float] = []
    span = max(0.0, end - start)
    cap = cv2.VideoCapture(str(video_path))
    try:
        if cap.isOpened():
            for k in range(probes):
                t = start + span * (k + 0.5) / probes
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                times.append(round(t, 3))
                res = system_detect.system_regions(crop_roi(frame, roi))
                gaps.extend(float(r["staff_gap_px"]) for r in res["regions"])
    finally:
        cap.release()
    gap = float(np.median(gaps)) if gaps else None
    scale = 1.0
    if gap is not None and gap > WORK_SCALE_TRIGGER_GAP_PX:
        scale = WORK_GAP_PX / gap
    return {"scale": round(scale, 6), "probe_gap_px": round(gap, 2) if gap is not None else None,
            "probe_times": times, "regions": len(gaps), "work_gap_px": WORK_GAP_PX,
            "trigger_gap_px": WORK_SCALE_TRIGGER_GAP_PX}


def crop_to_source_point(source_to_crop: Sequence[float], x: float, y: float) -> Tuple[float, float]:
    m = np.array(source_to_crop, dtype=np.float64).reshape(3, 3)
    inv = np.linalg.inv(m)
    v = inv @ np.array([x, y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


def crop_box_to_source(source_to_crop: Sequence[float], box: Sequence[float]) -> List[float]:
    x0, y0 = crop_to_source_point(source_to_crop, box[0], box[1])
    x1, y1 = crop_to_source_point(source_to_crop, box[2], box[3])
    return [round(min(x0, x1), 2), round(min(y0, y1), 2), round(max(x0, x1), 2), round(max(y0, y1), 2)]


# --------------------------------------------------------------------------- #
# Source decoding with exact timestamps
# --------------------------------------------------------------------------- #


@dataclass
class VideoInfo:
    path: str
    fps: float
    frame_count: int
    width: int
    height: int
    duration_sec: float


def probe_video(path: Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()
    dur = count / fps if fps > 0 else 0.0
    return VideoInfo(str(path), fps, count, w, h, dur)


class VideoDecodeIncompleteError(RuntimeError):
    """The decoder stopped well before the end the container reports, so the later part of
    the video was never sampled. The job stops instead of passing off the decoded head as the
    whole video (Astra audit 2026-10-13, F08)."""

    code = "VIDEO_DECODE_INCOMPLETE"

    def __init__(self, decoded_until: Optional[float], expected_until: float):
        self.decoded_until = decoded_until
        self.expected_until = expected_until
        got = "no frame" if decoded_until is None else f"{decoded_until:.2f}s"
        super().__init__(f"{self.code}: the decoder stopped at {got} of {expected_until:.2f}s")


# Container frame counts can overshoot the decodable frames by a few frames, so coarse
# targets this close to the last decoded frame may go unserved without loss being reported.
DECODE_END_TOLERANCE_SEC = 1.0


def iter_frames_at(path: Path, targets: Iterable[float], *, checkpoint: Callable[[], None] = lambda: None,
                   reach: Optional[Dict[str, Any]] = None) -> Iterator[Tuple[float, float, np.ndarray]]:
    """Yield ``(target_sec, pts_sec, frame)`` for each target time.

    The chosen frame is the first decoded frame whose PTS is at or after
    ``target - half a frame`` (the frame nearest the target from the decoder's
    point of view). Targets are visited in ascending order with one
    sequential decode; a frame is decoded (retrieved) only when needed.

    When the stream ends before the last targets (the container's frame count overshoots the
    decodable frames), targets at most ``DECODE_END_TOLERANCE_SEC`` after the last decoded
    frame get that last frame, with its own PTS (audit F06: the end tail is observed).

    ``reach`` (when given) receives ``"last_pts"``: the PTS of the last frame the decoder
    delivered (None when none was), kept current while iterating. The decode-completeness check
    compares it with the requested final frame (audit F08).
    """
    todo = sorted(set(round(float(t), 6) for t in targets))
    if not todo:
        return
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    half = 0.5 / fps
    i = 0
    last: Optional[Tuple[float, np.ndarray]] = None  # the latest retrieved frame
    pts: Optional[float] = None  # the latest grabbed frame
    if reach is not None:
        reach["last_pts"] = None
    try:
        while i < len(todo):
            checkpoint()
            if not cap.grab():
                # only the stream's real last frame stands in for targets past the end
                if last is not None and last[0] == pts:
                    while i < len(todo) and todo[i] - last[0] <= DECODE_END_TOLERANCE_SEC:
                        yield todo[i], round(last[0], 6), last[1]
                        i += 1
                break
            pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if reach is not None:
                reach["last_pts"] = round(pts, 6)
            if pts + half < todo[i]:
                if todo[-1] - pts <= DECODE_END_TOLERANCE_SEC:
                    ok, frame = cap.retrieve()
                    if ok:
                        last = (pts, frame)
                continue
            ok, frame = cap.retrieve()
            if not ok:
                continue
            last = (pts, frame)
            while i < len(todo) and todo[i] <= pts + half:
                yield todo[i], round(pts, 6), frame
                i += 1
    finally:
        cap.release()


def decode_end_probes(reached: float, final: float) -> List[float]:
    """Seek targets that check a sequential decode's early end: halfway and three quarters of
    the way from the decoder's reach to the requested final frame."""
    gap = final - reached
    return [round(reached + gap * 0.5, 6), round(reached + gap * 0.75, 6)]


def stream_continues_after(path: Path, reached: float, probes: Sequence[float]) -> bool:
    """True when a frame later than ``reached`` decodes after seeking to one of ``probes``.

    Run only when a sequential decode ended more than ``DECODE_END_TOLERANCE_SEC`` before the
    requested end (audit F08): a later frame means the decoder stopped early; none means the
    video stream really ends at ``reached`` (a VFR recording holding its last frame, or a
    container longer than its video stream). A video that no longer opens counts as continuing,
    so the end is never confirmed without a seek."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return True
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        half = 0.5 / fps
        for t in probes:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            if not cap.grab():
                continue
            pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            ok, frame = cap.retrieve()
            if ok and frame is not None and pts > reached + half:
                return True
    finally:
        cap.release()
    return False


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Per-observation analysis
# --------------------------------------------------------------------------- #


def detect_playhead_x(region_img: np.ndarray, gap: float) -> Optional[float]:
    """Playhead x as a fraction of the region width, or None.

    Uses the app's overlay detector (page_diff._overlay_mask: colored bands,
    tinted highlight boxes, gray full-height bands).
    """
    if region_img is None or region_img.size == 0:
        return None
    norm, _ = system_detect.normalize_polarity(region_img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    ink = page_diff._ink_mask(gray)
    g = gap if gap and gap > 0 else page_diff._fallback_staff_gap(*gray.shape[:2])
    no_staff = page_diff._remove_staff_lines(ink, gap=g)
    _mask, cursor = page_diff._overlay_mask(norm, no_staff, gap=g)
    if cursor is None:
        return None
    return round(float(cursor) / float(region_img.shape[1]), 4)


EDGE_INK_MAX = 110  # same ink cut as system_tracking.CLEAN_INK_MAX (ignores a translucent video background)


def edge_content(crop: np.ndarray, regions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ink components cut by the top or bottom edge of the applied ROI.

    A component counts when it touches the first/last row, has area >= 0.05 gap^2
    and is not a long thin horizontal line (frame border, staff line). It is
    "attributed" when it lies inside a detected row's notation envelope (that
    row then already carries envelope_at_*_edge); unattributed components are
    notation or text of a system the detector does not see - e.g. a system
    above the ROI whose lowest notes reach into it.
    """
    norm, _ = system_detect.normalize_polarity(crop)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    paper = float(np.percentile(gray, 75))
    ink = (gray < min(EDGE_INK_MAX, paper - 60)).astype(np.uint8)
    gap = float(np.median([r["staff_gap_px"] for r in regions])) if regions else 10.0
    n, _lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = {"top": 0, "bottom": 0, "top_attributed": 0, "bottom_attributed": 0, "top_px": 0, "bottom_px": 0}
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if a < 0.05 * gap * gap or (bw > 0.5 * w and bh <= 3):
            continue
        for side, touches in (("top", y <= 0), ("bottom", y + bh >= h)):
            if not touches:
                continue
            inside = any(r["envelope_bbox"][0] <= x and x + bw <= r["envelope_bbox"][2]
                         and r["envelope_bbox"][1] <= y and y + bh <= r["envelope_bbox"][3] for r in regions)
            if inside:
                out[side + "_attributed"] += 1
            else:
                out[side] += 1
                out[side + "_px"] += int(bw)
    return out


def analyse_crop(crop: np.ndarray) -> Dict[str, Any]:
    """System regions + playhead + ROI-edge content for one ROI crop (slot/role assigned later)."""
    res = system_detect.system_regions(crop)
    regions = []
    for k, r in enumerate(res["regions"]):
        x0, y0, x1, y1 = r["bbox"]
        ph = detect_playhead_x(crop[y0:y1, x0:x1], r["staff_gap_px"])
        regions.append(dict(r, playhead_x=ph))
    return {"inverted": bool(res["inverted"]), "regions": regions, "edge_content": edge_content(crop, regions)}


def assign_slots(observations: List[Dict[str, Any]], *, tol_gaps: float = 1.0, min_members: int = 3) -> List[Dict[str, Any]]:
    """Cluster staff-top rows over the whole source into screen slots.

    Slot ids are ``slot-NN`` ordered top to bottom; a row that fits no cluster
    with at least ``min_members`` observations gets ``slot-transient``.
    Returns the slot table.
    """
    rows = []
    for oi, obs in enumerate(observations):
        for ri, r in enumerate(obs["system_regions"]):
            rows.append((r["staff_y"][0], r["staff_gap_px"], oi, ri))
    rows.sort()
    clusters: List[List[Tuple[float, float, int, int]]] = []
    for row in rows:
        if clusters:
            c = clusters[-1]
            centre = float(np.median([m[0] for m in c]))
            if abs(row[0] - centre) <= tol_gaps * row[1]:
                c.append(row)
                continue
        clusters.append([row])
    table = []
    k = 0
    for c in clusters:
        if len(c) < min_members:
            for _y, _g, oi, ri in c:
                observations[oi]["system_regions"][ri]["slot_id"] = "slot-transient"
            continue
        sid = f"slot-{k:02d}"
        k += 1
        ys = [m[0] for m in c]
        table.append({"slot_id": sid, "staff_top_y": round(float(np.median(ys)), 1),
                      "y_range": [round(min(ys), 1), round(max(ys), 1)], "members": len(c)})
        for _y, _g, oi, ri in c:
            observations[oi]["system_regions"][ri]["slot_id"] = sid
    return table


def assign_roles(obs: Dict[str, Any]) -> None:
    """active / preview / visible / unknown, per region.

    * one region: ``active`` (the only row on screen)
    * the region holding the playhead: ``active``
    * two regions and one is active: the other is ``preview``
    * three or more regions: the others are ``visible`` (page rows)
    * several regions and no playhead anywhere: ``unknown``
    """
    regs = obs["system_regions"]
    if not regs:
        return
    if len(regs) == 1:
        regs[0]["role"] = "active"
        return
    with_ph = [r for r in regs if r.get("playhead_x") is not None]
    if len(with_ph) == 1:
        for r in regs:
            if r is with_ph[0]:
                r["role"] = "active"
            else:
                r["role"] = "preview" if len(regs) == 2 else "visible"
        return
    for r in regs:
        r["role"] = "unknown"


def compare_crops(a: np.ndarray, b: np.ndarray, *, dedupe_level: str = "normal") -> page_diff.FrameDiffVerdict:
    """page_diff.compare_frames after normalizing dark-theme polarity.

    The page comparator's ink mask expects dark ink on light paper; a dark
    theme otherwise reads as a change in every pair.
    """
    a_n, _ = system_detect.normalize_polarity(a)
    b_n, _ = system_detect.normalize_polarity(b)
    return page_diff.compare_frames(a_n, b_n, dedupe_level=dedupe_level)


def is_apparent_change(v: page_diff.FrameDiffVerdict) -> bool:
    """A change worth fine resampling: a note-sized difference, a playhead reset
    or unreliable registration. Lone sub-note residue ("small_change", e.g. a
    playhead crossing a barline) is not."""
    if v.verdict == page_diff.VERDICT_SAME:
        return False
    return not (v.verdict == page_diff.VERDICT_AMBIGUOUS and v.reason == "small_change")


# --------------------------------------------------------------------------- #
# Manifest construction
# --------------------------------------------------------------------------- #


def _grid(start: float, end: float, hz: float) -> List[float]:
    step = 1.0 / hz
    n = int(np.floor((end - start) / step + 1e-9))
    return [round(start + i * step, 6) for i in range(n + 1)]


def _last_frame_time(fps: float, end: float) -> Optional[float]:
    """Nominal time of the last frame before ``end`` (source seconds), or None without a frame rate."""
    if not fps or fps <= 0 or end <= 0:
        return None
    index = int(np.ceil(end * fps - 1e-6)) - 1
    return round(max(0, index) / fps, 6)


def build_manifest(
    *,
    video_path: Path,
    roi: Sequence[Sequence[float]],
    out_dir: Optional[Path] = None,
    video_id: Optional[str] = None,
    roi_revision: int = 1,
    coarse_hz: float = 2.0,
    fine_hz: float = 8.0,
    fine_window: float = 1.0,
    max_duration: Optional[float] = None,
    start_sec: float = 0.0,
    store_frames: bool = True,
    logger: Callable[[str], None] = lambda _m: None,
    progress: Optional[Callable[[float], None]] = None,
    checkpoint: Callable[[], None] = lambda: None,
    work_scale: Optional[float] = None,
) -> Dict[str, Any]:
    """Sample a source video inside an applied ROI and return the manifest dict.

    ``work_scale`` (None = probe the source, ``probe_work_scale``): crops are resized by it
    (when < 1) before analysis and storage; ``source_to_crop`` and ``crop_size`` include it.

    When ``out_dir`` is given and ``store_frames`` is true, every observation's
    ROI crop is written losslessly to ``out_dir/frames/<obs_id>.png`` and the
    manifest records that path (relative to ``out_dir``).

    ``start_sec``/``max_duration`` limit sampling to ``[start_sec, max_duration)``
    (source seconds). ``progress`` receives the fraction of coarse samples
    analysed (0..1); ``checkpoint`` is called once per decoded sample so a
    caller can cancel.
    """
    video_path = Path(video_path)
    info = probe_video(video_path)
    duration = info.duration_sec if max_duration is None else min(info.duration_sec, max_duration)
    s2c, _box = roi_source_to_crop(roi)
    start = max(0.0, min(float(start_sec or 0.0), max(0.0, duration - 1e-3)))
    if work_scale is None:
        scale_rec = probe_work_scale(video_path, roi, start, duration)
    else:
        scale_rec = {"scale": round(float(work_scale), 6), "probe_gap_px": None, "given": True}
    scale = float(scale_rec["scale"])
    if scale < 1.0:
        logger(f"work scale {scale:.3f} (staff space {scale_rec.get('probe_gap_px')} px -> {WORK_GAP_PX:g} px)")
    sizes: Dict[str, Tuple[int, int]] = {}  # native and work crop size, from the first crop
    frames_dir = None
    if out_dir is not None and store_frames:
        frames_dir = Path(out_dir) / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for stale in frames_dir.glob("*.png"):  # a rebuild replaces the previous frames
            stale.unlink()

    samples: Dict[float, Dict[str, Any]] = {}
    changes: List[Dict[str, Any]] = []
    windows: List[Tuple[float, float]] = []
    served: Dict[str, Any] = {"targets": set(), "last_pts": None}

    reach: Dict[str, Any] = {"last_pts": None}

    def take(targets: List[float], kind: str, compare_consecutive: bool, reach_out: Optional[Dict[str, Any]] = None) -> None:
        prev: Optional[Tuple[float, np.ndarray]] = None
        done = 0
        for target, pts, frame in iter_frames_at(video_path, targets, reach=reach_out):
            checkpoint()
            done += 1
            served["targets"].add(target)
            served["last_pts"] = pts if served["last_pts"] is None else max(served["last_pts"], pts)
            if progress is not None and kind == "coarse" and targets:
                progress(min(1.0, done / float(len(targets))))
            if pts in samples:
                samples[pts]["requested_t"].append(target)
                continue
            crop = crop_roi(frame, roi)
            if not sizes:
                sizes["native"] = (int(crop.shape[1]), int(crop.shape[0]))
                sizes["work"] = scaled_size(sizes["native"], scale)
            crop = scale_crop(crop, sizes["work"])
            tmp_rel = None
            if frames_dir is not None:
                tmp_rel = f"frames/_t{int(round(pts * 1e6)):012d}.png"
                cv2.imwrite(str(Path(out_dir) / tmp_rel), crop)
            samples[pts] = {"t_sec": pts, "requested_t": [target], "sample_kind": kind, "tmp_rel": tmp_rel,
                            "crop_size": [int(crop.shape[1]), int(crop.shape[0])], "analysis": analyse_crop(crop)}
            if compare_consecutive and prev is not None:
                a, prev_crop = prev
                v = compare_crops(prev_crop, crop)
                if is_apparent_change(v):
                    mid = (a + pts) / 2.0
                    changes.append({"t_prev": a, "t_next": pts, "verdict": v.verdict, "reason": v.reason,
                                    "shift": [round(v.shift_x, 2), round(v.shift_y, 2)]})
                    windows.append((max(0.0, mid - fine_window), min(duration, mid + fine_window)))
            prev = (pts, crop)

    coarse = _grid(start, max(start, duration - 1e-3), coarse_hz)
    # the last frame once more (audit F06): a screen shown only after the last grid sample is
    # observed. Not a grid point: when the container overshoots the decodable frames it may go
    # unserved (or get the real last frame, iter_frames_at) without failing the decode check.
    tail = _last_frame_time(info.fps, duration)
    tail_targets = [tail] if tail is not None and tail >= start and (not coarse or tail > coarse[-1] + 1e-6) else []
    take(coarse + tail_targets, "coarse", True, reach)
    logger(f"coarse samples: {len(samples)}, changes: {len(changes)}")
    # decode completeness (audit F08): the decoder's real reach (the PTS of the last frame it
    # delivered) against the requested final frame, with DECODE_END_TOLERANCE_SEC applied once
    # (container frame counts overshoot the decodable frames by a few frames). Unserved grid
    # points alone are not the test: the tolerance on them let a decoder stop up to 1 s before
    # the last grid point plus the grid step and the tail. An early end is confirmed once by
    # seeking past it: when no later frame decodes, the video stream really ends there (VFR
    # held last frame, container longer than the video stream) and sampling stands.
    final = tail if tail is not None else (coarse[-1] if coarse else start)
    reached = reach.get("last_pts")
    if served["last_pts"] is None or reached is None:
        raise VideoDecodeIncompleteError(reached, duration)
    end_confirmed: Optional[Dict[str, Any]] = None
    if reached < final - DECODE_END_TOLERANCE_SEC - 1e-6:
        probes = decode_end_probes(float(reached), final)
        if stream_continues_after(video_path, float(reached), probes):
            raise VideoDecodeIncompleteError(reached, duration)
        end_confirmed = {"stream_end_sec": round(float(reached), 6), "requested_end_sec": round(final, 6),
                         "probe_sec": probes}
        logger(f"decode ended at {reached:.2f}s of {duration:.2f}s; no later frame after seeking, the stream ends there")
    frame_sec = 1.0 / info.fps if info.fps and info.fps > 0 else 0.0
    sampled_until = min(duration, max(float(reached), float(served["last_pts"])) + frame_sec)
    fine: List[float] = []
    for w0, w1 in windows:
        fine.extend(_grid(w0, w1, fine_hz))
    fine = sorted(set(fine) - set(coarse) - set(tail_targets))
    take(fine, "fine", False)
    logger(f"total samples: {len(samples)}")
    if sizes and sizes["work"] != sizes["native"]:
        s2c = scaled_source_to_crop(s2c, sizes["native"], sizes["work"])

    observations: List[Dict[str, Any]] = []
    for k, pts in enumerate(sorted(samples)):
        s = samples[pts]
        obs_id = f"obs-{k:06d}"
        frame_rel = None
        if s["tmp_rel"]:
            frame_rel = f"frames/{obs_id}.png"
            (Path(out_dir) / s["tmp_rel"]).replace(Path(out_dir) / frame_rel)
        ana = s["analysis"]
        regions = region_records(obs_id, ana, s2c)
        observations.append(
            {
                "id": obs_id,
                "t_sec": pts,
                "time_basis": TIME_BASIS,
                "time_uncertainty_sec": 0.0,
                "frame_duration_sec": round(1.0 / info.fps, 6) if info.fps else None,
                "requested_t": s["requested_t"],
                "sample_kind": s["sample_kind"],
                "frame_path": frame_rel,
                "crop_size": s["crop_size"],
                "inverted": ana["inverted"],
                "roi_revision": roi_revision,
                "applied_roi": [[float(x), float(y)] for x, y in roi],
                "source_to_crop": s2c,
                "system_regions": regions,
                "edge_content": ana["edge_content"],
            }
        )
    slots = assign_slots(observations)
    for obs in observations:
        assign_roles(obs)

    sampling: Dict[str, Any] = {
        "coarse_hz": coarse_hz,
        "fine_hz": fine_hz,
        "fine_window_sec": fine_window,
        "change_detector": "page_diff.compare_frames(normal) on polarity-normalized consecutive coarse ROI crops; resample unless same or ambiguous/small_change",
        "sampled_from_sec": round(start, 4),
        # what the decoder really reached (the end of its last frame), not the container's claim
        "sampled_until_sec": round(sampled_until, 4),
    }
    if end_confirmed is not None:
        # the sequential decode ended over DECODE_END_TOLERANCE_SEC before the container's end and
        # seeking past it decoded nothing later (audit F08)
        sampling["decode_end_confirmed_by_seek"] = end_confirmed

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "video_id": video_id or video_path.stem,
        "source": {
            "path": str(video_path),
            "sha256": file_sha256(video_path),
            "fps": info.fps,
            "frame_count": info.frame_count,
            "frame_size": [info.width, info.height],
            "duration_sec": round(info.duration_sec, 4),
            "decoder": f"opencv-{cv2.__version__}-ffmpeg",
            "time_basis": TIME_BASIS,
        },
        "applied_roi": [[float(x), float(y)] for x, y in roi],
        "roi_revision": roi_revision,
        "source_to_crop": s2c,
        "sampling": sampling,
        # crops are analysed and stored at this scale of the native ROI crop (1 = native);
        # source_to_crop and crop_size include it
        "work_scale": dict(scale_rec, native_crop_size=list(sizes["native"]) if sizes else None,
                           crop_size=list(sizes["work"]) if sizes else None),
        "detector_version": system_detect.DETECTOR_VERSION,
        "envelope_method": system_detect.ENVELOPE_METHOD,
        "acquisition_changes": changes,
        "slots": slots,
        "observations": observations,
    }


def region_records(obs_id: str, ana: Dict[str, Any], s2c: Sequence[float]) -> List[Dict[str, Any]]:
    regions = []
    for ri, r in enumerate(ana["regions"]):
        regions.append(
            {
                "region_id": f"{obs_id}-r{ri}",
                "bbox": r["bbox"],
                "row_band": r["row_band"],
                "staff_y": [round(v, 1) for v in r["staff_y"]],
                "staff_gap_px": round(r["staff_gap_px"], 2),
                "staff_x": r["staff_x"],
                "segments": r["segments"],
                "bars": r["bars"],
                "clef": r["clef"],
                "envelope_bbox": r["envelope_bbox"],
                "envelope_bbox_source": crop_box_to_source(s2c, r["envelope_bbox"]),
                "slot_id": None,
                "role": None,
                "playhead_x": r["playhead_x"],
                "issues": r["issues"],
            }
        )
    return regions


def refresh_regions(manifest: Dict[str, Any], manifest_dir: Path, *, logger: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Recompute every observation's system regions from its stored frame with
    the current detector/envelope code (timestamps, ids and frames unchanged),
    then reassign slots and roles. Returns the updated manifest (schema 2)."""
    s2c = manifest["source_to_crop"]
    for k, obs in enumerate(manifest["observations"]):
        crop = load_observation_image(manifest_dir, obs, manifest)
        ana = analyse_crop(crop)
        obs["system_regions"] = region_records(obs["id"], ana, s2c)
        obs["inverted"] = ana["inverted"]
        obs["edge_content"] = ana["edge_content"]
        if k % 200 == 0:
            logger(f"refreshed {k}/{len(manifest['observations'])}")
    manifest["slots"] = assign_slots(manifest["observations"])
    for obs in manifest["observations"]:
        assign_roles(obs)
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["envelope_method"] = system_detect.ENVELOPE_METHOD
    manifest.setdefault("revisions", []).append({"refresh_regions": system_detect.ENVELOPE_METHOD, "detector_version": system_detect.DETECTOR_VERSION})
    return manifest


# --------------------------------------------------------------------------- #
# IO + validation
# --------------------------------------------------------------------------- #


def write_manifest(manifest: Dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(path)


def load_manifest(path: Path) -> Dict[str, Any]:
    m = json.loads(Path(path).read_text())
    problems = validate_manifest(m)
    if problems:
        raise ValueError(f"invalid manifest {path}: {problems[:5]}")
    return m


def validate_manifest(m: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    if m.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version {m.get('schema_version')!r} != {SCHEMA_VERSION}")
    if m.get("kind") != MANIFEST_KIND:
        problems.append("kind")
    seen = set()
    last_t = -1.0
    for obs in m.get("observations", []):
        oid = obs.get("id")
        if oid in seen:
            problems.append(f"duplicate id {oid}")
        seen.add(oid)
        t = obs.get("t_sec")
        if not isinstance(t, (int, float)) or t < last_t:
            problems.append(f"{oid}: t_sec not ascending")
        last_t = t if isinstance(t, (int, float)) else last_t
        if obs.get("time_basis") != TIME_BASIS:
            problems.append(f"{oid}: time_basis")
        for r in obs.get("system_regions", []):
            if not str(r.get("region_id", "")).startswith(f"{oid}-r"):
                problems.append(f"{oid}: region id")
            if len(r.get("staff_y", [])) != 5:
                problems.append(f"{oid}: staff_y")
    return problems


def load_observation_image(manifest_dir: Path, obs: Dict[str, Any], manifest: Optional[Dict[str, Any]] = None) -> np.ndarray:
    """The observation's ROI crop: the stored frame, else re-decoded from the source at its PTS."""
    if obs.get("frame_path"):
        img = cv2.imread(str(Path(manifest_dir) / obs["frame_path"]))
        if img is not None:
            return img
    if manifest is None:
        raise FileNotFoundError(obs.get("frame_path"))
    for _t, _pts, frame in iter_frames_at(Path(manifest["source"]["path"]), [obs["t_sec"]]):
        return crop_observation(frame, obs["applied_roi"], obs.get("crop_size"))
    raise FileNotFoundError(f"frame at {obs['t_sec']} not decodable")


class SeamRepairSourceUnavailable(RuntimeError):
    code = "SEAM_REPAIR_SOURCE_UNAVAILABLE"

    def __init__(self, reason: str):
        super().__init__(f"{self.code}: {reason}; previous export kept")


def recover_observation_images(manifest_dir: Path, manifest: Dict[str, Any], observation_ids: Iterable[str],
                               recovery_dir: Path, *, checkpoint: Callable[[], None] = lambda: None,
                               progress: Callable[[float], None] = lambda _f: None,
                               max_bytes: int = 768 * 1024 * 1024) -> Callable[[Dict[str, Any]], np.ndarray]:
    """Reuse complete PNG crops; decode all missing saved PTS in one cancellable pass.

    Missing crops live only in the caller's unpublished workspace. The returned loader
    has a bounded LRU and never falls back to another source decode. The caller removes
    recovery_dir after the audited producers finish, including on cancellation/failure.
    """
    from collections import OrderedDict
    from app.pipeline.process_control import OperationCancelled

    by_id = {o["id"]: o for o in manifest["observations"]}
    ids = sorted(set(observation_ids), key=lambda oid: (float(by_id[oid]["t_sec"]), oid))
    paths, missing = {}, []

    def check_shape(img, obs):
        size = obs.get("crop_size")
        if img is None or not size or list(img.shape[:2][::-1]) != list(size) or img.ndim != 3 or img.shape[2] != 3:
            raise SeamRepairSourceUnavailable(f"crop shape mismatch for {obs['id']}")

    for i, oid in enumerate(ids):
        checkpoint()
        obs = by_id[oid]
        path = Path(manifest_dir) / obs["frame_path"] if obs.get("frame_path") else None
        img = cv2.imread(str(path)) if path is not None and path.is_file() else None
        if img is None:
            missing.append(obs)
        else:
            check_shape(img, obs)
            paths[oid] = path
        progress(0.1 * (i + 1) / max(1, len(ids)))
    if missing:
        source = manifest.get("source") or {}
        path = Path(source.get("path") or "")
        try:
            checkpoint()
            try:
                matches = path.is_file() and source.get("sha256") and file_sha256(path) == source["sha256"]
            except OSError as exc:
                raise SeamRepairSourceUnavailable("source missing or unreadable") from exc
            if not matches:
                raise SeamRepairSourceUnavailable("source missing or SHA-256 mismatch")
            recovery_dir = Path(recovery_dir)
            recovery_dir.mkdir(parents=True, exist_ok=True)
            targets = {}
            for obs in missing:
                targets.setdefault(round(float(obs["t_sec"]), 6), []).append(obs)
            recovered = 0
            for target, pts, frame in iter_frames_at(path, targets, checkpoint=checkpoint):
                checkpoint()
                if abs(float(pts) - target) > 0.000001:
                    raise SeamRepairSourceUnavailable(f"saved frame timing mismatch at {target}")
                if list(frame.shape[:2][::-1]) != list(source.get("frame_size") or []):
                    raise SeamRepairSourceUnavailable("source frame shape mismatch")
                for obs in targets[target]:
                    img = crop_observation(frame, obs["applied_roi"], obs.get("crop_size"))
                    check_shape(img, obs)
                    dest = recovery_dir / f"{obs['id']}.png"
                    if not cv2.imwrite(str(dest), img):
                        raise OSError(f"failed to write recovered crop {dest}")
                    paths[obs["id"]] = dest
                    recovered += 1
                    progress(0.1 + 0.9 * recovered / len(missing))
            if recovered != len(missing):
                raise SeamRepairSourceUnavailable("saved frames not decodable")
        except (OperationCancelled, SeamRepairSourceUnavailable):
            raise
        except (RuntimeError, ValueError, KeyError, cv2.error) as exc:
            raise SeamRepairSourceUnavailable(str(exc)) from exc
    progress(1.0)
    cache = OrderedDict()
    held = 0

    def load(obs):
        nonlocal held
        checkpoint()
        oid = obs["id"]
        if oid in cache:
            cache.move_to_end(oid)
            return cache[oid]
        if oid not in paths:
            raise SeamRepairSourceUnavailable(f"unrecovered dependency {oid}")
        img = cv2.imread(str(paths[oid]))
        check_shape(img, obs)
        if img.nbytes <= max_bytes:
            cache[oid] = img
            held += img.nbytes
            while held > max_bytes:
                _, dropped = cache.popitem(last=False)
                held -= dropped.nbytes
        return img

    load.paths = paths
    return load
