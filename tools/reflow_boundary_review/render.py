"""Source-frame crops for boundary candidates (decoded in memory, never dumped as full frames).

Each candidate gets three small JPEGs cut from the SOURCE video (not the cleaned strip):

* ``<pid>_a.jpg`` reference frame, seam marked only by ticks in added top/bottom margins
  (no content pixel is covered);
* ``<pid>_b.jpg`` the same crop with a thin semi-transparent seam line over the content
  (the "overlay on" view);
* ``<pid>_c.jpg`` a neighbouring frame of the same display (other playhead position), ticks only.

No algorithm verdict and no candidate origin is drawn or encoded in file names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import cv2
import numpy as np

import common as C
from app.pipeline import observations as ob

MARGIN = 14
MAX_CROP_W = 1500
JPEG_QUALITY = 85


def decode_frames(video_path: Path, times: Iterable[float]) -> Dict[float, Tuple[float, np.ndarray]]:
    """target t -> (decoded PTS, BGR frame), one sequential pass."""
    out: Dict[float, Tuple[float, np.ndarray]] = {}
    for target, pts, frame in ob.iter_frames_at(Path(video_path), times):
        out[round(float(target), 6)] = (float(pts), frame)
    return out


def crop_window(cand: Dict[str, Any], record: Dict[str, Any], crop_size: Tuple[int, int]) -> List[int]:
    """Crop-coordinate box: the two adjacent measures (or the measure containing the seam),
    padded by half a gap, with the strip's full height plus one gap above and below."""
    g = float(record["staff_gap_px"])
    box = record["box_crop"]
    l0 = cand["ownership_proposal"]["left_unit_cols_strip"][0]
    r1 = cand["ownership_proposal"]["right_unit_cols_strip"][1]
    seam = cand["seam"]["x_strip"]
    x0 = int(np.floor(l0 - 0.5 * g)) + box[0]
    x1 = int(np.ceil(r1 + 0.5 * g)) + box[0]
    sx = seam + box[0]
    if x1 - x0 > MAX_CROP_W:
        half = MAX_CROP_W // 2
        x0, x1 = max(x0, sx - half), min(x1, sx + half)
    w, h = crop_size
    y0 = max(0, int(box[1] - g))
    y1 = min(h, int(box[3] + g))
    return [max(0, x0), y0, min(w, x1), y1]


def _with_ticks(img: np.ndarray, seam_x: int) -> np.ndarray:
    h, w = img.shape[:2]
    out = np.full((h + 2 * MARGIN, w, 3), 255, np.uint8)
    out[MARGIN:MARGIN + h] = img
    col = (0, 0, 230)
    for ytip, ybase in ((MARGIN - 1, 1), (MARGIN + h, MARGIN * 2 + h - 2)):
        pts = np.array([[seam_x, ytip], [seam_x - 6, ybase], [seam_x + 6, ybase]], np.int32)
        cv2.fillPoly(out, [pts], col)
    out[:, :1] = 160
    out[:, -1:] = 160
    return out


def _with_line(img: np.ndarray, seam_x: int) -> np.ndarray:
    out = _with_ticks(img, seam_x)
    h = img.shape[0]
    seg = out[MARGIN:MARGIN + h, seam_x:seam_x + 1].astype(np.float32)
    red = np.zeros_like(seg)
    red[..., 2] = 255
    out[MARGIN:MARGIN + h, seam_x:seam_x + 1] = np.rint(0.45 * seg + 0.55 * red).astype(np.uint8)
    return out


def render_candidate(frames: Dict[str, np.ndarray], obs: Dict[str, Dict[str, Any]], ref_id: str, other_id: str,
                     win: List[int], seam_x_crop: int, out_dir: Path, pid: str) -> Dict[str, Any]:
    x0, y0, x1, y1 = win
    ref = ob.crop_roi(frames[ref_id], obs[ref_id]["applied_roi"])[y0:y1, x0:x1]
    oth = ob.crop_roi(frames[other_id], obs[other_id]["applied_roi"])[y0:y1, x0:x1]
    sx = int(seam_x_crop - x0)
    files = {}
    for key, img in (("plain", _with_ticks(ref, sx)), ("seam_overlay", _with_line(ref, sx)), ("other_frame", _with_ticks(oth, sx))):
        suffix = {"plain": "a", "seam_overlay": "b", "other_frame": "c"}[key]
        name = f"{pid}_{suffix}.jpg"
        cv2.imwrite(str(out_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        files[key] = name
    return {"files": files, "seam_x_image": sx, "content_rows_image": [MARGIN, MARGIN + (y1 - y0)],
            "image_size": [int(x1 - x0), int(y1 - y0 + 2 * MARGIN)],
            "crop_pixels_sha256": {"reference": C.pixels_sha256(ref), "other": C.pixels_sha256(oth)}}
