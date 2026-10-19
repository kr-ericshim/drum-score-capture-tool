from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2

from app.pipeline.process_control import checkpoint
import numpy as np

from app.pipeline.layout_profiles import LAYOUT_BOTTOM_BAR, LAYOUT_FULL_SCROLL, LAYOUT_PAGE_TURN, resolve_layout_hint
from app.pipeline.page_diff import FrameDiffVerdict, VERDICT_AMBIGUOUS, compare_frames, playhead_jumped_back
from app.schemas import StitchOptions


def select_review_candidates(
    *,
    frame_paths: List[Path],
    options: StitchOptions,
    source_type: Optional[str] = None,
    logger,
    report: Optional[Dict[str, Any]] = None,
) -> List[Path]:
    """Drop repeated frames and report similar pairs plus observation groups.

    Groups contain only direct duplicates of each kept frame (kept path first),
    so repeated observations can be composed without mixing in transition frames.
    Similar pairs remain separate captures for the review screen to compare.
    """
    if not frame_paths:
        if report is not None:
            report.update(similar_pairs=[], observation_groups={})
        return []

    layout_mode = resolve_layout_hint(options.layout_hint, source_type=source_type)
    logger(f"review candidate dedupe mode: {options.dedupe_level}")
    filtered_frames = _filter_redundant_frames(
        frame_paths=frame_paths,
        layout_mode=layout_mode,
        dedupe_level=options.dedupe_level,
        logger=logger,
        report=report,
    )
    if filtered_frames:
        logger(f"review candidates prepared: {len(filtered_frames)}")
    return filtered_frames


def _filter_redundant_frames(
    *,
    frame_paths: List[Path],
    layout_mode: str,
    dedupe_level: str = "normal",
    logger,
    report: Optional[Dict[str, Any]] = None,
) -> List[Path]:
    observation_groups = {str(path): [str(path)] for path in frame_paths[:1]}
    if len(frame_paths) <= 1:
        if report is not None:
            report.update(similar_pairs=[], observation_groups=observation_groups)
        return frame_paths

    kept_paths: List[Path] = [frame_paths[0]]
    prev = cv2.imread(str(frame_paths[0]))
    if prev is None:
        if report is not None:
            report.update(similar_pairs=[], observation_groups={str(path): [str(path)] for path in frame_paths})
        return frame_paths

    similar_pairs: List[Dict[str, Any]] = []
    recent_frames: Deque[Tuple[int, np.ndarray, Path]] = deque(maxlen=8)
    first_hash = _frame_dhash(prev)
    if first_hash is not None:
        recent_frames.append((first_hash, prev, frame_paths[0]))

    removed = 0
    clarity_replacements = 0
    ambiguous_kept = 0
    scroll_direction = 0
    last_seen_playhead_x: Optional[float] = None
    # A return to an older kept page waits for the next frame: a page that stays
    # on screen is a real repeat (kept for review), a single frame is a flicker.
    pending_return: Optional[Dict[str, Any]] = None
    for path in frame_paths[1:]:
        checkpoint()
        current = cv2.imread(str(path))
        if current is None:
            continue
        if pending_return is not None:
            # Only a clearly different next frame proves a flicker. A same or
            # ambiguous one (e.g. playhead reset on yet another repeat) keeps the
            # return; the current frame is then judged against it as usual.
            persisted = not compare_frames(pending_return["image"], current, dedupe_level=dedupe_level).is_different
            if persisted:
                kept_paths.append(pending_return["path"])
                observation_groups[str(pending_return["path"])] = [str(pending_return["path"])]
                prev = pending_return["image"]
                recent_frames.append((pending_return["hash"], prev, pending_return["path"]))
                similar_pairs.append(pending_return["pair"])
                ambiguous_kept += 1
                logger(f"returning page kept for review (recent_return): {pending_return['path'].name}")
            else:
                # A dropped flicker frame must not count as the last seen playhead.
                last_seen_playhead_x = pending_return["playhead_before"]
                removed += 1
            pending_return = None
        verdict = compare_frames(prev, current, dedupe_level=dedupe_level)
        if verdict.is_same and playhead_jumped_back(last_seen_playhead_x, verdict.playhead_cur_x):
            # Same-looking score but playback restarted at the left edge: a
            # repeat, or the next page happens to be identical. Keep for review.
            verdict.verdict = VERDICT_AMBIGUOUS
            verdict.reason = "playhead_reset"
        playhead_before = last_seen_playhead_x
        last_seen_playhead_x = verdict.playhead_cur_x
        if _is_duplicate_verdict(verdict, layout_mode=layout_mode, dedupe_level=dedupe_level):
            group = observation_groups[str(kept_paths[-1])]
            if _should_replace_with_clearer_duplicate(prev, current):
                replaced = kept_paths[-1]
                kept_paths[-1] = path
                del observation_groups[str(replaced)]
                observation_groups[str(path)] = [str(path), *group]
                prev = current
                # The replaced frame is gone: a stale cache entry would make the
                # same page look like a return to an older one.
                recent_frames = deque((entry for entry in recent_frames if entry[2] != replaced), maxlen=8)
                current_hash = _frame_dhash(current)
                if current_hash is not None:
                    recent_frames.append((current_hash, current, path))
                if similar_pairs and similar_pairs[-1]["candidate"] == str(replaced):
                    similar_pairs[-1]["candidate"] = str(path)
                clarity_replacements += 1
            else:
                group.append(str(path))
            removed += 1
            continue

        if verdict.is_ambiguous:
            # Keep it, but hand the pair to the review step instead of guessing.
            ambiguous_kept += 1
            similar_pairs.append(
                {
                    "kept": str(kept_paths[-1]),
                    "candidate": str(path),
                    "reason": verdict.reason,
                    "metrics": verdict.to_dict(),
                }
            )
            logger(f"similar frame kept for review ({verdict.reason}): {path.name}")

        current_hash = _frame_dhash(current)
        if layout_mode in {LAYOUT_BOTTOM_BAR, LAYOUT_PAGE_TURN} and not verdict.is_ambiguous:
            # Flicker back to a recently seen page: the hash only nominates a
            # candidate; the blob-level comparison has to confirm it.
            match = None
            if current_hash is not None:
                match = _match_recent_frame(
                    current,
                    current_hash,
                    recent_frames=recent_frames,
                    layout_mode=layout_mode,
                    dedupe_level=dedupe_level,
                )
            if match is not None:
                matched_path, match_verdict = match
                if matched_path == kept_paths[-1]:
                    removed += 1
                else:
                    pending_return = {
                        "path": path,
                        "image": current,
                        "hash": current_hash,
                        "playhead_before": playhead_before,
                        "pair": {
                            "kept": str(matched_path),
                            "candidate": str(path),
                            "reason": "recent_return",
                            "metrics": match_verdict.to_dict(),
                        },
                    }
                continue

        if layout_mode == LAYOUT_FULL_SCROLL:
            # Static near-duplicates were already removed above (blob-level
            # verdict); here only the scroll direction jitter filter remains.
            shift_px, shift_conf = _estimate_vertical_shift(prev, current)
            min_scroll_shift = _min_scroll_shift_by_level(dedupe_level)
            if shift_conf >= 0.4 and abs(shift_px) >= 1.0:
                direction = 1 if shift_px > 0 else -1
                # Ignore tiny opposite-direction jitter while scrolling.
                if scroll_direction != 0 and direction != scroll_direction and abs(shift_px) < (min_scroll_shift * 1.8):
                    removed += 1
                    continue
                scroll_direction = direction

        kept_paths.append(path)
        observation_groups[str(path)] = [str(path)]
        prev = current
        if current_hash is not None:
            recent_frames.append((current_hash, current, path))

    if pending_return is not None:
        # The video ended on a single returning frame: treat it as a flicker.
        removed += 1

    if removed > 0:
        logger(f"temporal dedupe removed {removed} near-duplicate frames")
    if clarity_replacements > 0:
        logger(f"temporal dedupe replaced {clarity_replacements} low-clarity duplicate frames")
    if ambiguous_kept > 0:
        logger(f"temporal dedupe kept {ambiguous_kept} near-identical frames for review")
    if report is not None:
        report["similar_pairs"] = similar_pairs
        report["observation_groups"] = observation_groups
    return kept_paths


def _is_duplicate_verdict(verdict: FrameDiffVerdict, *, layout_mode: str, dedupe_level: str) -> bool:
    """A frame is redundant only when the score content is the same AND nothing
    new scrolled into view. Ambiguous verdicts are never treated as duplicates."""
    if not verdict.is_same:
        return False
    if layout_mode == LAYOUT_PAGE_TURN:
        # Pages do not scroll; any small shift is ROI jitter.
        return True
    max_jitter = _min_scroll_shift_by_level(dedupe_level)
    return max(abs(verdict.shift_x), abs(verdict.shift_y)) < max_jitter


def _match_recent_frame(
    current: np.ndarray,
    current_hash: int,
    *,
    recent_frames: Deque[Tuple[int, np.ndarray, Path]],
    layout_mode: str,
    dedupe_level: str,
) -> Optional[Tuple[Path, FrameDiffVerdict]]:
    """The recently kept frame `current` duplicates, with the confirming verdict."""
    if not recent_frames:
        return None
    if not _looks_like_recent_hash_duplicate(
        current_hash,
        recent_hashes=deque(hash_value for hash_value, _image, _path in recent_frames),
        layout_mode=layout_mode,
        dedupe_level=dedupe_level,
    ):
        return None
    ranked = sorted(recent_frames, key=lambda item: _hamming_u64(current_hash, item[0]))
    for _hash_value, image, frame_path in ranked[:3]:
        verdict = compare_frames(image, current, dedupe_level=dedupe_level)
        if _is_duplicate_verdict(verdict, layout_mode=layout_mode, dedupe_level=dedupe_level):
            return frame_path, verdict
    return None


def _should_replace_with_clearer_duplicate(prev_img, cur_img) -> bool:
    prev_score = _sheet_clarity_score(prev_img)
    cur_score = _sheet_clarity_score(cur_img)
    return cur_score >= max(prev_score + 45.0, prev_score * 1.35)


def _sheet_clarity_score(image: np.ndarray) -> float:
    h = min(image.shape[0], 900)
    w = min(image.shape[1], 1600)
    if h <= 16 or w <= 16:
        return 0.0
    gray = cv2.cvtColor(cv2.resize(image, (w, h)), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _threshold_by_level(level: str, *, aggressive: float, normal: float, sensitive: float) -> float:
    if level == "aggressive":
        return aggressive
    if level == "sensitive":
        return sensitive
    return normal


def _min_scroll_shift_by_level(level: str) -> float:
    if level == "aggressive":
        return 5.4
    if level == "sensitive":
        return 1.8
    return 3.2


def _frame_dhash(image: np.ndarray) -> Optional[int]:
    h, w = image.shape[:2]
    if h < 8 or w < 9:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = 0
    for flag in diff.reshape(-1):
        bits = (bits << 1) | int(flag)
    return bits


def _hamming_u64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def _looks_like_recent_hash_duplicate(
    current_hash: int,
    *,
    recent_hashes: Deque[int],
    layout_mode: str,
    dedupe_level: str,
) -> bool:
    if not recent_hashes:
        return False

    if layout_mode == LAYOUT_PAGE_TURN:
        threshold = int(_threshold_by_level(dedupe_level, aggressive=3, normal=2, sensitive=1))
    elif layout_mode == LAYOUT_BOTTOM_BAR:
        threshold = int(_threshold_by_level(dedupe_level, aggressive=8, normal=6, sensitive=4))
    else:
        threshold = int(_threshold_by_level(dedupe_level, aggressive=7, normal=5, sensitive=3))

    min_dist = min(_hamming_u64(current_hash, candidate) for candidate in recent_hashes)
    return min_dist <= threshold


def _pad_to_width(image: np.ndarray, target_w: int) -> np.ndarray:
    h, w = image.shape[:2]
    if target_w <= w:
        return image
    pad_left = (target_w - w) // 2
    pad_right = target_w - w - pad_left
    return cv2.copyMakeBorder(image, 0, 0, pad_left, pad_right, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def _estimate_vertical_shift(img_a: np.ndarray, img_b: np.ndarray) -> Tuple[float, float]:
    h = min(img_a.shape[0], img_b.shape[0], 1200)
    w = min(img_a.shape[1], img_b.shape[1], 1400)
    if h < 40 or w < 40:
        return 0.0, 0.0

    a = cv2.cvtColor(cv2.resize(img_a, (w, h)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(img_b, (w, h)), cv2.COLOR_BGR2GRAY)
    a = cv2.GaussianBlur(a, (3, 3), 0)
    b = cv2.GaussianBlur(b, (3, 3), 0)

    # Use central columns to reduce side overlays/watermarks impact.
    x_pad = max(4, int(w * 0.08))
    if w - (x_pad * 2) <= 10:
        return 0.0, 0.0
    a_center = a[:, x_pad : w - x_pad]
    b_center = b[:, x_pad : w - x_pad]

    row_a = a_center.mean(axis=1).astype(np.float32)
    row_b = b_center.mean(axis=1).astype(np.float32)
    row_a -= float(np.mean(row_a))
    row_b -= float(np.mean(row_b))

    std_a = float(np.std(row_a))
    std_b = float(np.std(row_b))
    if std_a < 1e-5 or std_b < 1e-5:
        return 0.0, 0.0

    max_shift = max(20, int(h * 0.22))
    lags = range(-max_shift, max_shift + 1)
    best_lag = 0
    best_score = -1e12
    for lag in lags:
        if lag >= 0:
            a_seg = row_a[lag:]
            b_seg = row_b[: len(a_seg)]
        else:
            b_seg = row_b[-lag:]
            a_seg = row_a[: len(b_seg)]
        if a_seg.size < 24 or b_seg.size < 24:
            continue
        score = float(np.dot(a_seg, b_seg) / float(max(1, a_seg.size)))
        if score > best_score:
            best_score = score
            best_lag = lag

    denom = std_a * std_b
    norm = best_score / max(1e-6, denom)
    # Typical normalized correlation for valid scroll shifts is around 0.9~1.0 on score videos.
    # Rescale confidence so shift gating can reliably reject near-static jitter frames.
    row_confidence = float(max(0.0, min(1.0, (norm - 0.16) / 0.72)))

    phase_shift, phase_confidence = _estimate_vertical_shift_phasecorr(
        a_center,
        b_center,
        max_shift=max_shift,
    )

    if phase_confidence >= max(0.38, row_confidence + 0.12):
        return phase_shift, phase_confidence
    if row_confidence >= 0.24:
        return float(best_lag), row_confidence
    if phase_confidence >= 0.3:
        # Low-confidence case: phase correlation usually gives better magnitude on smooth scroll.
        return phase_shift, phase_confidence
    return float(best_lag), row_confidence


def _estimate_vertical_shift_phasecorr(a_gray: np.ndarray, b_gray: np.ndarray, *, max_shift: int) -> Tuple[float, float]:
    if a_gray.size == 0 or b_gray.size == 0 or a_gray.shape != b_gray.shape:
        return 0.0, 0.0

    a_f = a_gray.astype(np.float32)
    b_f = b_gray.astype(np.float32)
    a_f -= float(np.mean(a_f))
    b_f -= float(np.mean(b_f))

    std_a = float(np.std(a_f))
    std_b = float(np.std(b_f))
    if std_a < 1e-5 or std_b < 1e-5:
        return 0.0, 0.0

    (dx, dy), response = cv2.phaseCorrelate(a_f, b_f)
    if not np.isfinite(dy):
        return 0.0, 0.0

    # Match row-correlation sign convention used in this module.
    # (row method returns +shift for visually upward moved next frame)
    shift = float(-dy)
    shift = float(np.clip(shift, -float(max_shift), float(max_shift)))
    confidence = float(np.clip((float(response) - 0.08) / 0.76, 0.0, 1.0))
    return shift, confidence

