"""Remove moving playback highlights using aligned observations of one score."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

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


def colored_pixels(image: np.ndarray) -> np.ndarray:
    """Bright colored pixels (the ``_overlay_columns`` criterion, per pixel)."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return (hsv[..., 1] > 30) & (hsv[..., 2] > 150)


OVERLAY_MASK_DILATE_PX = 2   # tinted anti-aliased fringe around a colored overlay
_BOX_FILL_MIN = 0.25         # a colored component this solid in its box is a (translucent) box: mask the whole box
_BOX_MIN_PX = 12


def min_overlay_height(height: int) -> int:
    """The ``_overlay_columns`` sensitivity: a column counted only with more than max(8, 3.5% of
    the height) colored pixels. A colored object lower than that (a 1-px border line, a speck)
    was never an overlay and is not one in the 2-D mask either."""
    return int(max(8, 0.035 * height))


def overlay_mask_2d(image: np.ndarray) -> np.ndarray:
    """2-D mask of the colored overlays of one image (not whole columns).

    Colored pixels (``colored_pixels``) are grouped into components (3x3 closing);
    a component that fills at least a quarter of its bounding box is a translucent
    box or band and its whole box is masked (the notes inside are tinted, not
    bright); a sparse one (a thin outline) is masked as drawn. Everything is
    dilated by ``OVERLAY_MASK_DILATE_PX``. A mask marks pixels to recover from
    other observations; it is never an erase mask."""
    colored = colored_pixels(image).astype(np.uint8)
    out = np.zeros(colored.shape, np.uint8)
    if not colored.any():
        return out.astype(bool)
    closed = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _c = cv2.connectedComponentsWithStats(closed, connectivity=8)
    min_h = min_overlay_height(colored.shape[0])
    for k in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[k])
        if bh < min_h:
            continue
        if area >= _BOX_MIN_PX and area >= _BOX_FILL_MIN * bw * bh:
            out[y:y + bh, x:x + bw] = 1
        else:
            out[lab == k] = 1
    r = OVERLAY_MASK_DILATE_PX
    return cv2.dilate(out, np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0


# Screen-fixed chrome: colored pixels that stay put, with the same color, across
# displays whose notation differs (a preview inset's frame band, a player icon).
CHROME_SAMPLES = 32
CHROME_MIN_DISPLAYS = 3
CHROME_MIN_SHARE = 0.8
CHROME_MAX_STD = 12.0
CHROME_SAME_INK_IOU = 0.9   # two samples whose ink overlaps this much show the same notation
CHROME_DILATE_PX = 2


def _ink_signature(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if float(np.median(gray)) < 110:  # dark theme
        gray = 255 - gray
    paper = float(np.percentile(gray, 75))
    ink = (gray < min(150.0, paper - 60.0)).astype(np.uint8)
    # a little blur so a sub-pixel jitter is not a notation change
    return cv2.dilate(ink, np.ones((3, 3), np.uint8)) > 0


def distinct_displays(images: Sequence[np.ndarray]) -> List[int]:
    """Indices of images that show different notation (greedy: an image joins the
    first kept one whose ink overlaps it by ``CHROME_SAME_INK_IOU``)."""
    kept: List[int] = []
    sigs: List[np.ndarray] = []
    for i, im in enumerate(images):
        s = _ink_signature(im)
        same = False
        for t in sigs:
            union = int((s | t).sum())
            if union == 0 or (s & t).sum() / float(union) >= CHROME_SAME_INK_IOU:
                same = True
                break
        if not same:
            kept.append(i)
            sigs.append(s)
    return kept


CHROME_COUNTERPART_DISPLAYS = 2  # an object seen at another place nearby in this many displays moves with the score


def _objects(mask: np.ndarray) -> Tuple[int, np.ndarray, np.ndarray]:
    r = CHROME_DILATE_PX
    grown = cv2.dilate(mask.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8))
    return cv2.connectedComponentsWithStats(grown, connectivity=8)[:3]


def _drop_moving_objects(core: np.ndarray, reps: Sequence[np.ndarray]) -> Tuple[np.ndarray, List[List[int]]]:
    """Remove chrome candidates that are score-attached objects: the same-sized colored object
    appears at another place nearby (within one object size) in at least
    ``CHROME_COUNTERPART_DISPLAYS`` displays (an editor icon at a line end that varies).
    Returns (core, boxes of the removed objects)."""
    n, lab, stats = _objects(core)
    if n <= 1:
        return core, []
    disp = [_objects(colored_pixels(im)) for im in reps]
    out = core.copy()
    moving: List[List[int]] = []
    H, W = core.shape
    for k in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[k])
        obj = lab == k
        wx0, wy0, wx1, wy1 = max(0, x - bw), max(0, y - bh), min(W, x + 2 * bw), min(H, y + 2 * bh)
        found = 0
        for dn, dlab, dst in disp:
            win = dlab[wy0:wy1, wx0:wx1]
            hit = False
            for j in np.unique(win):
                if j == 0:
                    continue
                dx, dy, dw, dh, da = (int(v) for v in dst[j])
                if not (0.7 * bw <= dw <= 1.4 * bw and 0.7 * bh <= dh <= 1.4 * bh and 0.5 * area <= da <= 2.0 * area):
                    continue
                off = max(abs((dx + dw / 2.0) - (x + bw / 2.0)), abs((dy + dh / 2.0) - (y + bh / 2.0)))
                if off <= max(3.0, 0.15 * max(bw, bh)):
                    continue  # the object in place
                hit = True
                break
            found += int(hit)
            if found >= CHROME_COUNTERPART_DISPLAYS:
                break
        if found >= CHROME_COUNTERPART_DISPLAYS:
            out[obj] = 0
            moving.append([x, y, x + bw, y + bh])
    return out, moving


# Score-row protection (audit F10): a repeated place and color does not prove that an object is
# not notation (a red section mark at the same spot on several lines). Inside the rows of the
# score, an object no larger than a score symbol or label is never chrome; only what is clearly
# larger (a band, a frame, a logo) or lies outside the rows can be.
SYMBOL_MAX_H_GAPS = 4.0   # a symbol, a letter, a boxed rehearsal label: at most this many staff gaps tall
SYMBOL_MAX_W_GAPS = 12.0  # ... and this many wide (a boxed word label)


def _protect_symbols(core: np.ndarray, protect: np.ndarray, gap: float) -> Tuple[np.ndarray, np.ndarray, List[List[int]]]:
    """Remove from ``core`` every chrome object (pieces within 2 x ``CHROME_DILATE_PX`` joined)
    that touches the score-row zone ``protect`` and is symbol-sized (``SYMBOL_MAX_H_GAPS`` x
    ``SYMBOL_MAX_W_GAPS`` staff gaps). Returns (core, protected pixels, their object boxes)."""
    n, lab, _stats = _objects(core)
    out = core.copy()
    protected = np.zeros(core.shape, bool)
    boxes: List[List[int]] = []
    on = core > 0
    for k in range(1, n):
        obj = (lab == k) & on
        if not obj.any():
            continue
        ys, xs = np.nonzero(obj)
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if bh > SYMBOL_MAX_H_GAPS * gap or bw > SYMBOL_MAX_W_GAPS * gap:
            continue  # larger than a score symbol: a band, a frame, a logo
        if not (obj & protect).any():
            continue  # outside the score rows
        out[obj] = 0
        protected |= obj
        boxes.append([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])
    return out, protected, boxes


def screen_fixed_chrome(images: Sequence[np.ndarray], *, protect: Optional[np.ndarray] = None,
                        gap: Optional[float] = None) -> Tuple[np.ndarray, Dict[str, object]]:
    """Mask (dilated by ``CHROME_DILATE_PX``) of screen-fixed chrome in same-size
    images (crop coordinates): pixels colored in at least ``CHROME_MIN_SHARE`` of the
    images that show different notation (at least ``CHROME_MIN_DISPLAYS`` of them)
    with a steady color (per-channel std <= ``CHROME_MAX_STD``), plus any area a
    chrome frame closes in (a preview interior). A moving overlay (cursor) is not
    in it. Returns (mask, info); ``info["_appearance"]`` (H x W x 3 float, NaN elsewhere) is
    the chrome's mean color over the displays on its colored core and on enclosed pixels
    steady across all displays - its own steady
    appearance, the only thing besides paper a strip may paper-fill.

    ``protect`` (same size, bool) and ``gap`` (staff gap px): the score-row zone. A candidate
    object that touches it and is symbol-sized (``_protect_symbols``) is kept out of the mask,
    the appearance and the enclosed areas (``info["protected_objects"]``; ``info["_protected"]``:
    their pixels, a steady printed object for the composite's unrecovered count)."""
    info: Dict[str, object] = {"samples": len(images), "displays": 0, "chrome_px": 0}
    if not images:
        return np.zeros((0, 0), bool), info
    shape = images[0].shape
    images = [im for im in images if im.shape == shape]
    idx = distinct_displays(images)
    info["displays"] = len(idx)
    empty = np.zeros(shape[:2], bool)
    if len(idx) < CHROME_MIN_DISPLAYS:
        return empty, info
    reps = [images[i] for i in idx]
    colored = np.stack([colored_pixels(im) for im in reps])
    share = colored.mean(axis=0)
    cand = share >= CHROME_MIN_SHARE
    if not cand.any():
        return empty, info
    ys, xs = np.nonzero(cand)
    vals = np.stack([im[ys, xs].astype(np.float32) for im in reps])  # n x k x 3
    col = colored[:, ys, xs]
    # std over the samples in which the pixel is colored
    cnt = col.sum(axis=0).astype(np.float32)
    mean = (vals * col[..., None]).sum(axis=0) / cnt[:, None]
    var = (((vals - mean[None]) ** 2) * col[..., None]).sum(axis=0) / cnt[:, None]
    steady = np.sqrt(var).max(axis=1) <= CHROME_MAX_STD
    core = np.zeros(shape[:2], np.uint8)
    core[ys[steady], xs[steady]] = 1
    if not core.any():
        return empty, info
    # objects lower than an overlay (a 1-px border line at the crop edge) are not chrome
    n_o, lab_o, st_o = _objects(core)
    low = [k for k in range(1, n_o) if int(st_o[k][3]) < min_overlay_height(shape[0])]
    if low:
        core[np.isin(lab_o, low) & (core > 0)] = 0
    if not core.any():
        return empty, info
    core, moving = _drop_moving_objects(core, reps)
    info["moving_objects"] = moving
    protected = np.zeros(shape[:2], bool)
    if protect is not None and gap and gap > 0 and protect.shape == shape[:2] and core.any():
        core, protected, boxes = _protect_symbols(core, protect.astype(bool), float(gap))
        info["protected_objects"] = boxes
        info["protected_px"] = int(protected.sum())
        if protected.any():
            info["_protected"] = protected
    if not core.any():
        return empty, info
    # an area a chrome frame closes in (not touching the image border through non-chrome)
    inv = (1 - core).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    holes = np.isin(lab, [k for k in range(1, n) if k not in border])
    if protected.any():
        # a protected symbol (and its anti-aliased rim) is never chrome, also inside a chrome frame
        r = CHROME_DILATE_PX
        holes &= ~(cv2.dilate(protected.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0)
    colored_core = core > 0
    core = colored_core | holes
    # the chrome's own steady appearance: its mean color over the displays, on the colored core only
    appearance = np.full(shape[:2] + (3,), np.nan, np.float32)
    on_core = colored_core[ys, xs]
    appearance[ys[on_core], xs[on_core]] = mean[on_core]
    if holes.any():
        # inside a closed chrome frame: what every display shows there with one steady color (a dark
        # fold line of an icon, a white glyph) is the chrome's too; a preview's changing notation is not
        hy, hx = np.nonzero(holes)
        hv = np.stack([im[hy, hx].astype(np.float32) for im in reps])
        steady_h = hv.std(axis=0).max(axis=1) <= CHROME_MAX_STD
        appearance[hy[steady_h], hx[steady_h]] = hv.mean(axis=0)[steady_h]
    info["_appearance"] = appearance
    r = CHROME_DILATE_PX
    mask = cv2.dilate(core.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0
    mask &= ~protected
    info.update(chrome_px=int(core.sum()), enclosed_px=int(holes.sum()))
    if core.any():
        ys2, xs2 = np.nonzero(core)
        info["box"] = [int(xs2.min()), int(ys2.min()), int(xs2.max()) + 1, int(ys2.max()) + 1]
    return mask, info


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
