"""Conservative score-region suggestions from a few representative frames.

This module intentionally returns a suggestion rather than an authoritative
crop.  Missing or conflicting evidence is reported as ``not_found`` so the
existing manual ROI workflow remains the safe fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np

from app.pipeline.extract import extract_preview_frame


@dataclass(frozen=True)
class StaffGroup:
    x1: float
    y1: float
    x2: float
    y2: float
    spacing: float
    notation_components: int
    regularity: float
    polarity: str


@dataclass(frozen=True)
class FrameCandidate:
    roi: tuple[float, float, float, float]
    score: float
    staff_groups: int
    notation_components: int
    staff_spacing: float
    polarity: str


def estimate_auto_roi_for_source(
    *,
    source_type: str,
    file_path: Optional[str],
    youtube_url: Optional[str],
    start_sec: Optional[float],
    workspace: Path,
    logger,
) -> Dict[str, object]:
    """Sample nearby frames from a prepared source and estimate its score ROI."""
    base_sec = max(0.0, float(start_sec or 0.0))
    frames: List[np.ndarray] = []
    checked_seconds: List[float] = []
    for offset in (0.0, 0.8, 1.6):
        sec = base_sec + offset
        try:
            image_path = extract_preview_frame(
                source_type=source_type,
                file_path=file_path,
                youtube_url=youtube_url,
                start_sec=sec,
                workspace=workspace / f"sample_{len(checked_seconds)}",
                logger=logger,
            )
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            frames.append(image)
            checked_seconds.append(round(sec, 2))
        except Exception as exc:
            logger(f"auto ROI sample at {sec:.2f}s failed: {exc}")

    result = estimate_auto_roi(frames)
    diagnostics = dict(result.get("diagnostics") or {})
    diagnostics["checked_seconds"] = checked_seconds
    result["diagnostics"] = diagnostics
    return result


def estimate_auto_roi(frames: Sequence[np.ndarray]) -> Dict[str, object]:
    """Return a conservative axis-aligned ROI suggestion for BGR frames."""
    usable = [frame for frame in frames if isinstance(frame, np.ndarray) and frame.ndim == 3 and frame.size]
    if not usable:
        return _not_found(sampled_frames=0, reason="no_frames")

    frame_candidates: List[tuple[int, FrameCandidate]] = []
    dark_votes = 0
    for frame_index, frame in enumerate(usable):
        candidates, is_dark = detect_frame_candidates(frame)
        dark_votes += int(is_dark)
        for candidate in candidates[:4]:
            frame_candidates.append((frame_index, candidate))

    if not frame_candidates:
        return _not_found(
            sampled_frames=len(usable),
            reason="no_staff_candidate",
            is_dark_mode=dark_votes > len(usable) / 2,
        )

    clusters = _cluster_candidates(frame_candidates)
    best = max(
        clusters,
        key=lambda cluster: (
            len({item[0] for item in cluster}),
            sum(item[1].score for item in cluster),
            sum(item[1].notation_components for item in cluster),
        ),
    )
    supporting_frames = len({item[0] for item in best})
    selected = [item[1] for item in best]
    representative = max(selected, key=lambda candidate: candidate.score)
    # Median coordinates resist a single oversized panel-edge proposal while
    # keeping the result tied to a real detected frame.
    coords = np.median(np.asarray([candidate.roi for candidate in selected], dtype=np.float32), axis=0)
    height, width = usable[0].shape[:2]
    x1, y1, x2, y2 = _clamp_rect(tuple(float(value) for value in coords), width, height)
    if x2 - x1 < max(40, width * 0.08) or y2 - y1 < max(30, height * 0.04):
        return _not_found(sampled_frames=len(usable), reason="candidate_too_small")

    average_score = float(np.mean([candidate.score for candidate in selected]))
    notation_components = max(candidate.notation_components for candidate in selected)
    staff_groups = max(candidate.staff_groups for candidate in selected)
    if supporting_frames >= 2 and average_score >= 0.62 and notation_components >= 2:
        evidence_level = "high"
    elif average_score >= 0.48:
        evidence_level = "medium"
    else:
        return _not_found(sampled_frames=len(usable), reason="weak_staff_evidence")

    roi = [
        [float(round(x1, 2)), float(round(y1, 2))],
        [float(round(x2, 2)), float(round(y1, 2))],
        [float(round(x2, 2)), float(round(y2, 2))],
        [float(round(x1, 2)), float(round(y2, 2))],
    ]
    return {
        "status": "suggested",
        "roi": roi,
        "evidence_level": evidence_level,
        "is_dark_mode": representative.polarity == "light_on_dark",
        "diagnostics": {
            "sampled_frames": len(usable),
            "supporting_frames": supporting_frames,
            "staff_groups": staff_groups,
            "notation_components": notation_components,
            "staff_spacing": round(float(representative.staff_spacing), 3),
            # This is an internal heuristic, not a calibrated probability.
            "heuristic_score": round(average_score, 4),
        },
    }


def detect_frame_candidates(frame: np.ndarray) -> tuple[List[FrameCandidate], bool]:
    """Detect plausible score panels in one BGR frame."""
    height, width = frame.shape[:2]
    scale = min(1.0, 1200.0 / max(1, width), 900.0 / max(1, height))
    sample = (
        cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else frame
    )
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    is_dark = bool(np.median(gray) < 110)
    groups: List[StaffGroup] = []
    groups.extend(_detect_staff_groups(gray, polarity="dark_on_light"))
    groups.extend(_detect_staff_groups(255 - gray, polarity="light_on_dark"))
    groups = _deduplicate_groups(groups)
    if not groups:
        return [], is_dark

    clusters = _merge_staff_groups(groups)
    candidates: List[FrameCandidate] = []
    sample_h, sample_w = gray.shape
    inv_scale = 1.0 / scale
    for cluster in clusters:
        spacing = float(np.median([group.spacing for group in cluster]))
        x1 = min(group.x1 for group in cluster) - max(sample_w * 0.018, spacing * 2.0)
        x2 = max(group.x2 for group in cluster) + max(sample_w * 0.018, spacing * 2.0)
        y1 = min(group.y1 for group in cluster) - spacing * 4.5
        y2 = max(group.y2 for group in cluster) + spacing * 4.5
        x1, y1, x2, y2 = _clamp_rect((x1, y1, x2, y2), sample_w, sample_h)
        coverage = min(1.0, max(group.x2 - group.x1 for group in cluster) / max(1.0, sample_w * 0.55))
        notation = sum(group.notation_components for group in cluster)
        regularity = float(np.mean([group.regularity for group in cluster]))
        score = 0.42 * regularity + 0.25 * coverage + 0.25 * min(1.0, notation / 6.0) + 0.08 * min(1.0, len(cluster) / 2.0)
        candidates.append(
            FrameCandidate(
                roi=(x1 * inv_scale, y1 * inv_scale, x2 * inv_scale, y2 * inv_scale),
                score=float(score),
                staff_groups=len(cluster),
                notation_components=notation,
                staff_spacing=spacing * inv_scale,
                polarity=max(cluster, key=lambda group: group.notation_components).polarity,
            )
        )
    candidates.sort(key=lambda candidate: (candidate.score, candidate.staff_groups, candidate.notation_components), reverse=True)
    return candidates, is_dark


def _detect_staff_groups(gray: np.ndarray, *, polarity: str) -> List[StaffGroup]:
    height, width = gray.shape
    if height < 60 or width < 120:
        return []
    block_size = max(15, min(51, (min(height, width) // 20) | 1))
    ink = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        7,
    )
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(12, width // 45)), np.uint8))
    remaining = cv2.subtract(ink, cv2.dilate(horizontal, np.ones((3, 1), np.uint8)))
    remaining = cv2.morphologyEx(remaining, cv2.MORPH_CLOSE, np.ones((5, 1), np.uint8))
    _, _, stats, centroids = cv2.connectedComponentsWithStats(remaining, 8)

    windows = _horizontal_windows(width)
    found: List[StaffGroup] = []
    for window_x1, window_x2 in windows:
        strip = horizontal[:, window_x1:window_x2]
        density = np.mean(strip > 0, axis=1)
        rows = np.flatnonzero(density > 0.34)
        if rows.size < 5:
            continue
        bands = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
        usable_bands = [band for band in bands if band.size]
        centers = np.asarray([float(np.mean(band)) for band in usable_bands])
        thickness = np.asarray([len(band) for band in usable_bands])
        for start in range(max(0, len(centers) - 4)):
            group = centers[start:start + 5]
            if len(group) != 5:
                continue
            gaps = np.diff(group)
            spacing = float(np.median(gaps))
            tolerance = max(1.2, spacing * 0.24)
            deviation = float(np.max(np.abs(gaps - spacing)))
            if not 3.0 <= spacing <= 48.0 or deviation > tolerance:
                continue
            if np.max(thickness[start:start + 5]) > max(4.0, spacing * 0.5):
                continue
            before = start > 0 and abs(group[0] - centers[start - 1] - spacing) <= tolerance
            after = start + 5 < len(centers) and abs(centers[start + 5] - group[-1] - spacing) <= tolerance
            if before or after:
                continue

            row_pixels: List[np.ndarray] = []
            for center in group:
                row = horizontal[max(0, int(round(center)) - 1):min(height, int(round(center)) + 2), window_x1:window_x2]
                ys, xs = np.where(row > 0)
                del ys
                if xs.size:
                    row_pixels.append(xs + window_x1)
            if not row_pixels:
                continue
            pixels = np.concatenate(row_pixels)
            x1 = float(np.percentile(pixels, 2))
            x2 = float(np.percentile(pixels, 98))
            if x2 - x1 < max(50.0, width * 0.14):
                continue

            notation = 0
            for index in range(1, len(stats)):
                _, _, component_w, component_h, area = stats[index]
                cx, cy = centroids[index]
                if (
                    x1 - spacing <= cx <= x2 + spacing
                    and group[0] - 2.5 * spacing <= cy <= group[-1] + 2.5 * spacing
                    and max(2.0, spacing * 0.25) <= component_w <= spacing * 5.5
                    and spacing * 0.4 <= component_h <= spacing * 7.5
                    and area >= max(3.0, spacing * 0.65)
                ):
                    notation += 1
            regularity = max(0.0, 1.0 - deviation / max(tolerance, 1e-6))
            found.append(
                StaffGroup(
                    x1=x1,
                    y1=float(group[0]),
                    x2=x2,
                    y2=float(group[-1]),
                    spacing=spacing,
                    notation_components=notation,
                    regularity=regularity,
                    polarity=polarity,
                )
            )
    return found


def _horizontal_windows(width: int) -> List[tuple[int, int]]:
    raw = [
        (0, width),
        (0, round(width * 0.6)),
        (round(width * 0.2), round(width * 0.8)),
        (round(width * 0.4), width),
        (0, round(width * 0.45)),
        (round(width * 0.55), width),
    ]
    return [(max(0, x1), min(width, x2)) for x1, x2 in raw if x2 - x1 >= 80]


def _deduplicate_groups(groups: Sequence[StaffGroup]) -> List[StaffGroup]:
    ordered = sorted(groups, key=lambda group: (group.notation_components, group.regularity, group.x2 - group.x1), reverse=True)
    kept: List[StaffGroup] = []
    for group in ordered:
        if any(_staff_groups_match(group, existing) for existing in kept):
            continue
        kept.append(group)
    return sorted(kept, key=lambda group: (group.y1, group.x1))


def _staff_groups_match(left: StaffGroup, right: StaffGroup) -> bool:
    vertical_tolerance = max(left.spacing, right.spacing) * 1.5
    overlap = max(0.0, min(left.x2, right.x2) - max(left.x1, right.x1))
    shorter = max(1.0, min(left.x2 - left.x1, right.x2 - right.x1))
    return abs(left.y1 - right.y1) <= vertical_tolerance and overlap / shorter >= 0.55


def _merge_staff_groups(groups: Sequence[StaffGroup]) -> List[List[StaffGroup]]:
    clusters: List[List[StaffGroup]] = []
    for group in groups:
        matching: List[StaffGroup] | None = None
        for cluster in clusters:
            reference = cluster[-1]
            overlap = max(0.0, min(group.x2, reference.x2) - max(group.x1, reference.x1))
            shorter = max(1.0, min(group.x2 - group.x1, reference.x2 - reference.x1))
            spacing_ratio = max(group.spacing, reference.spacing) / max(1.0, min(group.spacing, reference.spacing))
            vertical_gap = group.y1 - reference.y2
            if overlap / shorter >= 0.42 and spacing_ratio <= 1.45 and vertical_gap <= max(group.spacing, reference.spacing) * 16:
                matching = cluster
                break
        if matching is None:
            clusters.append([group])
        else:
            matching.append(group)
    # A single-system candidate is useful for bottom overlays.  Multi-system
    # clusters cover full-page and stacked layouts.
    return clusters


def _cluster_candidates(items: Sequence[tuple[int, FrameCandidate]]) -> List[List[tuple[int, FrameCandidate]]]:
    clusters: List[List[tuple[int, FrameCandidate]]] = []
    for item in sorted(items, key=lambda entry: entry[1].score, reverse=True):
        frame_index, candidate = item
        best_cluster = None
        best_overlap = 0.0
        for cluster in clusters:
            if any(existing_frame == frame_index for existing_frame, _ in cluster):
                continue
            overlap = max(_rect_iou(candidate.roi, existing.roi) for _, existing in cluster)
            if overlap > best_overlap and overlap >= 0.28:
                best_cluster = cluster
                best_overlap = overlap
        if best_cluster is None:
            clusters.append([item])
        else:
            best_cluster.append(item)
    return clusters


def _rect_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    ix1 = max(left[0], right[0])
    iy1 = max(left[1], right[1])
    ix2 = min(left[2], right[2])
    iy2 = min(left[3], right[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _clamp_rect(rect: tuple[float, float, float, float], width: int, height: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = rect
    return (
        max(0.0, min(float(width - 1), x1)),
        max(0.0, min(float(height - 1), y1)),
        max(1.0, min(float(width), x2)),
        max(1.0, min(float(height), y2)),
    )


def _not_found(
    *,
    sampled_frames: int,
    reason: str,
    is_dark_mode: bool = False,
) -> Dict[str, object]:
    return {
        "status": "not_found",
        "roi": None,
        "evidence_level": "low",
        "is_dark_mode": is_dark_mode,
        "diagnostics": {
            "sampled_frames": sampled_frames,
            "supporting_frames": 0,
            "reason": reason,
        },
    }
