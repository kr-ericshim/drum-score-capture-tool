"""Remove moving playback highlights using aligned observations of one score."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import cv2
import numpy as np

from app.pipeline.layout_profiles import LAYOUT_BOTTOM_BAR, LAYOUT_PAGE_TURN
from app.pipeline.process_control import checkpoint


_MAX_MEMBERS = 15
# Members are combined without resampling, so even a one-pixel offset would
# smear one-pixel staff lines into paper. Fixed video overlays align exactly.
_MAX_SHIFT_PX = 0.5


def _overlay_columns(image: np.ndarray) -> np.ndarray:
    """Bright color drives the mask; dark JPEG chroma around ink does not."""
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colored = (hsv[..., 1] > 30) & (hsv[..., 2] > 150)
    columns = colored.sum(axis=0) > max(8, 0.035 * h)
    half_width = max(6, round(0.005 * w))
    kernel = np.ones((1, 2 * half_width + 1), dtype=np.uint8)
    return cv2.dilate(columns.astype(np.uint8)[None, :], kernel)[0] > 0


def _evenly_first(items: Sequence[str], count: int) -> List[str]:
    """Evenly spread picks first, then the rest as replacements for rejects."""
    if len(items) <= count:
        return list(items)
    picks = sorted(set(np.linspace(0, len(items) - 1, count).round().astype(int).tolist()))
    return [items[i] for i in picks] + [item for i, item in enumerate(items) if i not in set(picks)]


def _alignment_gray(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return gray - float(gray.mean())


def compose_overlay_free_captures(
    *,
    kept_paths: List[Path],
    groups: Mapping[str, Sequence[str]],
    layout_mode: str,
    workspace: Path,
    logger,
    report: Optional[Dict[str, List[str]]] = None,
) -> List[Path]:
    """Return one path per kept capture, preserving originals on every skip.

    Optional `report` maps each written composite to the actual aligned, sampled
    source members used. Originals are never written to or removed.
    """
    output_paths = list(kept_paths)
    composed = 0
    if layout_mode in {LAYOUT_BOTTOM_BAR, LAYOUT_PAGE_TURN}:
        for index, kept_path in enumerate(kept_paths):
            checkpoint()
            # Retain the reference even if the caller omitted it from its group.
            member_paths = list(dict.fromkeys([str(kept_path), *groups.get(str(kept_path), [])]))
            if len(member_paths) < 2:
                continue
            reference = cv2.imread(str(kept_path))
            if reference is None:
                continue
            h, w = reference.shape[:2]
            reference_gray = _alignment_gray(reference)
            window = cv2.createHanningWindow((w, h), cv2.CV_32F)
            usable = []
            # Decode at most _MAX_MEMBERS images: a long-held page can have
            # hundreds of duplicates.
            for raw_path in [member_paths[0], *_evenly_first(member_paths[1:], _MAX_MEMBERS - 1)]:
                checkpoint()
                if len(usable) >= _MAX_MEMBERS:
                    break
                path = Path(raw_path)
                image = reference if path == kept_path else cv2.imread(str(path))
                if image is None or image.shape != reference.shape:
                    continue
                if path != kept_path:
                    # phaseCorrelate with a window can mutate its inputs. Copy
                    # the reference so every member is tested against the same ink.
                    shift, _response = cv2.phaseCorrelate(reference_gray.copy(), _alignment_gray(image), window)
                    if not np.isfinite(shift).all() or np.hypot(*shift) >= _MAX_SHIFT_PX:
                        continue
                usable.append((path, image, _overlay_columns(image)))
            if len(usable) < 2 or not any(mask.any() for _path, _image, mask in usable):
                continue
            masks = np.stack([mask for _path, _image, mask in usable])
            if not masks.any():
                continue
            # Columns covered in every member fall back to the median of all members.
            masks[:, masks.all(axis=0)] = False
            stack = np.stack([image for _path, image, _mask in usable])
            composite = np.empty_like(reference)
            # A moving box leaves only a few distinct clean-member sets; take one
            # median per set over all of its columns.
            patterns, column_pattern = np.unique(masks.T, axis=0, return_inverse=True)
            column_pattern = column_pattern.reshape(-1)
            for pattern_index, covered in enumerate(patterns):
                checkpoint()
                columns = np.flatnonzero(column_pattern == pattern_index)
                selected = stack[~covered][:, :, columns]
                composite[:, columns] = np.rint(np.median(selected, axis=0)).astype(np.uint8)
            checkpoint()
            workspace.mkdir(parents=True, exist_ok=True)
            target = workspace / f"{kept_path.stem}_clean.png"
            if target.resolve() in {Path(path).resolve() for path in member_paths}:
                raise ValueError("overlay composite destination would overwrite a source frame")
            if not cv2.imwrite(str(target), composite):
                raise RuntimeError(f"failed to write overlay composite: {target}")
            output_paths[index] = target
            if report is not None:
                report[str(target)] = [str(path) for path, _image, _mask in usable]
            composed += 1
    logger(f"overlay composites: {composed} composed, {len(kept_paths) - composed} skipped")
    return output_paths
