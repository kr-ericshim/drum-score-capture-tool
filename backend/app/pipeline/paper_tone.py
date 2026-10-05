"""Even out the paper background of captured scores without touching the ink."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from app.pipeline.page_diff import _ink_mask, estimate_staff_gap
from app.pipeline.process_control import checkpoint


_TARGET_PAPER = 250.0
# Below this the capture is not a light score page (video background, dark theme).
_MIN_PAPER_LEVEL = 170.0
# A dark area wider than the closing kernel would read as "background"; never
# lift the estimate's dark side by more than this fraction of the paper level.
_MIN_BACKGROUND_FRACTION = 0.85
_EDGE_ROWS = 3
# Paper already this close to uniform target white needs no rewrite.
_SETTLED_TOLERANCE = 6.0


def flatten_paper_background(image: np.ndarray) -> Optional[np.ndarray]:
    """Divide out a smooth background estimate so paper becomes uniform.

    Ink keeps its ratio to the local paper, so gray ghost notes stay gray.
    Returns None when the capture does not look like a light score page, or when
    its paper is already uniform white with no border rule to clear.
    """
    if image is None or image.ndim != 3 or min(image.shape[:2]) < 16:
        return None
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    paper_level = float(np.percentile(gray, 75))
    if paper_level < _MIN_PAPER_LEVEL:
        return None

    gap = estimate_staff_gap(_ink_mask(gray))
    scale = 0.25 if min(h, w) >= 128 else 1.0
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # Closing removes everything thinner than ~3 staff gaps: notes, beams, text.
    kernel_size = max(5, int(round(gap * 3 * scale))) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    background = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel, borderType=cv2.BORDER_REPLICATE)
    background = cv2.GaussianBlur(background, (0, 0), kernel_size)
    background = cv2.resize(background, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    np.maximum(background, paper_level * _MIN_BACKGROUND_FRACTION, out=background)

    edge_rules = _edge_rule_rows(gray, paper_level, gap=gap)
    settled = (
        float(background.max() - background.min()) < _SETTLED_TOLERANCE
        and abs(float(np.median(background)) - _TARGET_PAPER) <= _SETTLED_TOLERANCE
    )
    if settled and not edge_rules:
        return None

    flattened = np.clip(image.astype(np.float32) / background * _TARGET_PAPER, 0, 255).astype(np.uint8)
    flattened[edge_rules] = np.uint8(_TARGET_PAPER)
    return flattened


def _edge_rule_rows(gray: np.ndarray, paper_level: float, *, gap: float) -> List[int]:
    """Rows holding a full-width UI border caught at the very edge of the ROI.

    A staff line touching a tightly drawn ROI is not a border: it has further
    lines at staff spacing inward, and it rarely spans the full width.
    """
    h = gray.shape[0]
    dark = gray < paper_level - 25

    def spans(row: int, fraction: float) -> bool:
        return 0 <= row < h and bool(dark[max(row - 1, 0) : row + 2].any(axis=0).mean() >= fraction)

    rules = []
    for row, inward in [*((r, 1) for r in range(min(_EDGE_ROWS, h))), *((r, -1) for r in range(max(h - _EDGE_ROWS, 0), h))]:
        if dark[row].mean() < 0.97:
            continue
        staff_like = sum(spans(int(round(row + inward * k * gap)), 0.5) for k in range(1, 5))
        if staff_like >= 2:
            continue
        rules.append(row)
    return sorted(set(rules))


def flatten_capture_backgrounds(*, paths: List[Path], workspace: Path, logger) -> List[Path]:
    """Return one path per capture, flattened where it looks like a score page.

    Files already inside `workspace` (our own composites) are rewritten in place;
    source frames are never modified, their flattened copy goes to `workspace`.
    """
    output_paths = list(paths)
    flattened_count = 0
    workspace_root = workspace.resolve()
    for index, path in enumerate(paths):
        checkpoint()
        image = cv2.imread(str(path))
        flattened = flatten_paper_background(image) if image is not None else None
        if flattened is None:
            continue
        workspace.mkdir(parents=True, exist_ok=True)
        if path.resolve().parent == workspace_root:
            target = path
        else:
            target = workspace / f"{path.stem}_clean.png"
        if not cv2.imwrite(str(target), flattened):
            raise RuntimeError(f"failed to write flattened capture: {target}")
        output_paths[index] = target
        flattened_count += 1
    logger(f"paper tone: {flattened_count} flattened, {len(paths) - flattened_count} kept as captured")
    return output_paths
