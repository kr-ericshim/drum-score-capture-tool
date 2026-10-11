"""Original screens fallback (docs/reflow/ORIGINAL_SCREENS_DESIGN.md, 2nd version).

For one-line videos only (applied ROI width/height >= 2.25). Independent of the clean reflow
analysis: capture the source every 0.5 s, crop each frame with the applied ROI, drop repeated
screens with the existing comparator (``stitch.select_review_candidates``), drop single-color
screens, mark likely non-score screens as exclusion candidates (``diagnose_capture_sequence``),
and place the selected screens whole, in time order, one under another on A4 pages. Screens are
never split, cropped, stitched or corrected.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_render
from app.pipeline.export import diagnose_capture_sequence, export_composed_pages
from app.pipeline.extract import extract_frames
from app.pipeline.observations import crop_roi
from app.pipeline.process_control import checkpoint, report_progress
from app.pipeline.stitch import select_review_candidates
from app.schemas import ExtractOptions, StitchOptions

OUTPUT_MODEL = "original_screens_v1"
INTERVAL_SEC = 0.5  # fixed capture interval (2 fps)
DEDUPE = StitchOptions(dedupe_level="sensitive", layout_hint="page_turn")
ONE_LINE_MIN_ASPECT = 2.25  # the old app's bottom_bar rule (inferLayoutHintFromRoi)
UNIFORM_MAX_RANGE = 10.0  # gray levels between the 0.1 and 99.9 percentiles
HEADER_KEYS = ("title", "performer", "bpm", "date", "memo")

SCREEN_GAP = int(round(2 * rl.MM))
HEADER_GAP = int(round(rl.HEADER_GAP_MM * rl.MM))
BODY_W = rl.PAGE_W - 2 * rl.MARGIN_X


def roi_aspect(roi: Sequence[Sequence[float]]) -> float:
    xs = [float(p[0]) for p in roi]
    ys = [float(p[1]) for p in roi]
    height = max(ys) - min(ys)
    return (max(xs) - min(xs)) / height if height > 0 else 0.0


def is_one_line_roi(roi: Sequence[Sequence[float]]) -> bool:
    return roi_aspect(roi) >= ONE_LINE_MIN_ASPECT


def is_uniform(image: np.ndarray) -> bool:
    """A screen filled with one color (a black frame, an empty plate): nothing to lose."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    lo, hi = np.percentile(gray, (0.1, 99.9))
    return float(hi - lo) <= UNIFORM_MAX_RANGE


def capture_frames(*, video_path: Path, roi: Sequence[Sequence[float]], start_sec: Optional[float],
                   end_sec: Optional[float], work_dir: Path, logger) -> List[Dict[str, Any]]:
    """Every 0.5 s frame of the source cropped with ``roi``: [{path, t}] in time order."""
    def on_extract(update: Dict[str, object]) -> None:
        if update.get("progress") is not None:
            report_progress("capturing", float(update["progress"]))

    report_progress("capturing", 0.0)
    frames = extract_frames(source_type="file", file_path=str(video_path), youtube_url=None,
                            options=ExtractOptions(fps=1.0 / INTERVAL_SEC, start_sec=start_sec, end_sec=end_sec),
                            workspace=work_dir, logger=logger, progress_callback=on_extract)
    crops_dir = work_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    start = float(start_sec or 0.0)
    captured: List[Dict[str, Any]] = []
    for k, frame_path in enumerate(frames):
        checkpoint()
        frame = cv2.imread(str(frame_path))
        if frame is None:
            # never skip a frame: a missing screen could be the only one showing a line
            raise RuntimeError(f"a captured frame is unreadable: {frame_path.name}")
        crop_path = crops_dir / f"crop_{k + 1:06d}.png"
        if not cv2.imwrite(str(crop_path), crop_roi(frame, roi)):
            raise RuntimeError(f"a captured screen could not be saved: {crop_path.name}")
        frame_path.unlink(missing_ok=True)  # only the crops are needed from here on
        captured.append({"path": crop_path, "t": start + k * INTERVAL_SEC})
    return captured


def select_screens(captured: List[Dict[str, Any]], *, logger) -> List[Dict[str, Any]]:
    """The existing comparator, fixed to sensitive / page_turn; the order is kept."""
    report_progress("comparing", 0.0)
    by_path = {str(c["path"]): c for c in captured}
    kept = select_review_candidates(frame_paths=[Path(c["path"]) for c in captured], options=DEDUPE, logger=logger)
    return [by_path[str(p)] for p in kept]


def screen_records(screens: List[Dict[str, Any]], *, logger) -> tuple[List[Dict[str, Any]], int]:
    """Drop single-color screens; mark the rest with the old app's exclusion candidates."""
    kept, dropped = [], 0
    for screen in screens:
        checkpoint()
        image = cv2.imread(str(screen["path"]))
        if image is None:
            raise RuntimeError(f"a captured screen is unreadable: {Path(screen['path']).name}")
        if is_uniform(image):
            dropped += 1
            continue
        kept.append(screen)
    diagnostics = diagnose_capture_sequence([Path(s["path"]) for s in kept])
    records = []
    for screen in kept:
        item = diagnostics.get(str(Path(screen["path"]))) or {}
        candidate = item.get("recommended_action") == "exclude"
        records.append({"path": screen["path"], "t": float(screen["t"]), "candidate": candidate,
                        "reasons": list(item.get("warning_reasons") or []) if candidate else []})
    if dropped:
        logger(f"original screens: dropped {dropped} single-color screens")
    return records, dropped


def document_header(header: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The title, performer, BPM, date and memo of the document header (no clean-only notices)."""
    return {k: header[k] for k in HEADER_KEYS if isinstance(header, dict) and header.get(k) not in (None, "")}


def plan_pages(sizes: Sequence[Sequence[int]], header_h: int = 0) -> List[List[Dict[str, int]]]:
    """Placements per page for screens of ``sizes`` ([w, h]): one column, time order.

    The screen width fills the body width and every screen uses that scale; a screen taller
    than a page body is shrunk on its own so it fits even below the page-1 header."""
    top = rl.MARGIN_TOP
    bottom = rl.PAGE_H - rl.MARGIN_BOTTOM
    first_top = top + (header_h + HEADER_GAP if header_h else 0)
    max_h = bottom - first_top
    pages: List[List[Dict[str, int]]] = [[]]
    y = first_top
    for index, (w, h) in enumerate(sizes):
        scale = BODY_W / float(w)
        if h * scale > max_h:
            scale = max_h / float(h)
        dw, dh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        if pages[-1] and y + dh > bottom:
            pages.append([])
            y = top
        pages[-1].append({"index": index, "x": rl.MARGIN_X + (BODY_W - dw) // 2, "y": y, "w": dw, "h": dh})
        y += dh + SCREEN_GAP
    return pages


class ComposedPages(Sequence):
    """A4 page rasters rendered on demand, so only one page is held in memory at a time."""

    def __init__(self, paths: List[Path], plan: List[List[Dict[str, int]]], header: Dict[str, Any]):
        self.paths, self.plan, self.header = paths, plan, header

    def __len__(self) -> int:
        return len(self.plan)

    def __getitem__(self, page_index):
        if isinstance(page_index, slice):
            return [self[i] for i in range(*page_index.indices(len(self)))]
        if page_index < 0:
            page_index += len(self)
        if not 0 <= page_index < len(self):
            raise IndexError(page_index)
        return render_page(self.paths, self.plan[page_index], header=self.header if page_index == 0 else None)


def render_page(paths: List[Path], placements: List[Dict[str, int]], *, header: Optional[Dict[str, Any]]) -> np.ndarray:
    page = np.full((rl.PAGE_H, rl.PAGE_W, 3), 255, np.uint8)
    for p in placements:
        checkpoint()
        img = cv2.imread(str(paths[p["index"]]))
        if img is None:
            raise RuntimeError(f"screen image is unreadable: {paths[p['index']]}")
        interp = cv2.INTER_AREA if p["w"] < img.shape[1] else cv2.INTER_CUBIC
        page[p["y"]:p["y"] + p["h"], p["x"]:p["x"] + p["w"]] = cv2.resize(img, (p["w"], p["h"]), interpolation=interp)
    runs = reflow_render._layout_header(header) if header else []
    if not runs:
        return page
    canvas = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    for run in runs:
        if run.get("font") is not None and run.get("text"):
            draw.text((run["x"], rl.MARGIN_TOP + run["y"]), run["text"], font=run["font"], fill=run["color"])
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def compose(*, selected: List[Path], header: Dict[str, Any], formats: List[str], workspace: Path,
            logger: Callable[[str], None]) -> Dict[str, object]:
    """Write the A4 pages of the ``selected`` screens (time order) into ``workspace``."""
    if not selected:
        raise RuntimeError("no screens are selected")
    report_progress("rendering", 0.0)
    sizes = []
    for path in selected:
        checkpoint()
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"screen image is unreadable: {path}")
        sizes.append((img.shape[1], img.shape[0]))
    plan = plan_pages(sizes, reflow_render.header_height(header) if header else 0)
    return export_composed_pages(pages=ComposedPages(list(selected), plan, header), formats=formats,
                                 workspace=Path(workspace), logger=logger)


def build(*, video_path: Path, roi: Sequence[Sequence[float]], start_sec: Optional[float], end_sec: Optional[float],
          header: Dict[str, Any], formats: List[str], workspace: Path, work_dir: Path,
          logger: Callable[[str], None]) -> Dict[str, object]:
    """First build (capture from the source) into ``workspace`` (a staged folder): pages, PDF and
    ``screens/screen_NNNN.png``. Exclusion candidates are stored but not selected.
    ``work_dir`` holds the decoded frames; the caller removes it."""
    captured = capture_frames(video_path=video_path, roi=roi, start_sec=start_sec, end_sec=end_sec,
                              work_dir=work_dir, logger=logger)
    if not captured:
        raise RuntimeError("no frames were captured from the source video")
    screens = select_screens(captured, logger=logger)
    records, dropped = screen_records(screens, logger=logger)
    screens_dir = Path(workspace) / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    for n, record in enumerate(records, start=1):
        checkpoint()
        target = screens_dir / f"screen_{n:04d}.png"
        shutil.copyfile(str(record["path"]), str(target))
        record["path"] = str(target)
    selected = [Path(r["path"]) for r in records if not r["candidate"]]
    logger(f"original screens: {len(records)} screens from {len(captured)} frames "
           f"({len(records) - len(selected)} exclusion candidates)")
    export = compose(selected=selected, header=header, formats=formats, workspace=workspace, logger=logger)
    return {"export": export, "screens": records, "selected": [str(p) for p in selected],
            "frames_captured": len(captured), "blank_dropped": dropped, "interval_sec": INTERVAL_SEC}


def rebuild(*, screens_dir: Path, selected_names: List[str], header: Dict[str, Any], formats: List[str],
            workspace: Path, logger: Callable[[str], None]) -> Dict[str, object]:
    """Rebuild from the saved screens (no capture): copy ``screens/`` into ``workspace`` and
    compose the pages of the screens named ``selected_names`` (file names, time order)."""
    target = Path(workspace) / "screens"
    shutil.copytree(str(screens_dir), str(target))
    selected = [target / name for name in selected_names]
    export = compose(selected=selected, header=header, formats=formats, workspace=workspace, logger=logger)
    return {"export": export, "selected": [str(p) for p in selected]}
