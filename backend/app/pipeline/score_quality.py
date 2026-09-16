"""Conservative score evidence, not optical music recognition.

Missing staff evidence is inconclusive (cropped, faint and one-line percussion
notation exist). Only independent blank/photo evidence may exclude a capture.
All measurements are heuristics, not calibrated probabilities.
"""
from __future__ import annotations

import cv2
import numpy as np


def analyze_score_structure(image: np.ndarray) -> dict:
    h, w = image.shape[:2]
    scale = min(1.0, 1400 / max(1, w), 6000 / max(1, h))
    sample = cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1 else image
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    # Support light notation on a dark background as well as conventional paper.
    if np.median(gray) < 110:
        gray = 255 - gray
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 31, 7)
    systems, partial, symbols, single_line = _staff_evidence(ink)
    # A small camera tilt should not turn an otherwise clear score into a photo.
    if not systems and min(gray.shape) >= 60:
        lines = cv2.HoughLinesP(ink, 1, np.pi / 180, threshold=40,
                               minLineLength=max(40, gray.shape[1] // 5), maxLineGap=12)
        angles = []
        if lines is not None:
            for x1, y1, x2, y2 in lines[:, 0]:
                angle = np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1)))
                if abs(angle) <= 5:
                    angles.append(angle)
        if len(angles) >= 5:
            tilt = float(np.median(angles))
            if 0.4 < abs(tilt) <= 5:
                gh, gw = gray.shape
                transform = cv2.getRotationMatrix2D((gw / 2, gh / 2), tilt, 1)
                straight = cv2.warpAffine(ink, transform, (gw, gh), flags=cv2.INTER_NEAREST)
                systems, tilted_partial, symbols, tilted_single = _staff_evidence(straight)
                partial = max(partial, tilted_partial)
                single_line = single_line or tilted_single
    return {
        "staff_systems": systems,
        "partial_staff_groups": partial,
        "notation_components": symbols,
        "has_score_structure": bool(systems and symbols >= 2),
        "possible_single_line_notation": bool(single_line),
        "paper_ratio": round(float(np.mean(gray > 190)), 5),
        "texture_ratio": round(float(np.mean(cv2.Canny(gray, 60, 160) > 0)), 5),
    }


def _staff_evidence(ink: np.ndarray) -> tuple[int, int, int, bool]:
    h, w = ink.shape
    if h < 12 or w < 40:
        return 0, 0, 0, False
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                 np.ones((1, max(12, w // 18)), np.uint8))
    remaining = cv2.subtract(ink, cv2.dilate(horizontal, np.ones((3, 1), np.uint8)))
    # Reconnect noteheads split in two by staff removal, without restoring rules.
    remaining = cv2.morphologyEx(remaining, cv2.MORPH_CLOSE, np.ones((5, 1), np.uint8))
    _, _, stats, centroids = cv2.connectedComponentsWithStats(remaining, 8)
    systems: list[tuple[float, float]] = []
    partials: list[float] = []
    notation: set[int] = set()
    single_line = False
    # Overlapping strips tolerate lyrics, short systems and uneven line lengths.
    for x1, x2 in ((0, w), (0, w // 2), (w // 4, 3 * w // 4), (w // 2, w)):
        density = np.mean(horizontal[:, x1:x2] > 0, axis=1)
        rows = np.flatnonzero(density > 0.42)
        bands = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
        centers = np.array([float(np.mean(b)) for b in bands if b.size])
        thickness = np.array([len(b) for b in bands if b.size])
        for center, line_thickness in zip(centers, thickness):
            # Short logo/text underlines are weak evidence for one-line notation.
            band = horizontal[max(0, int(center) - 1):min(h, int(center) + 2)]
            row = band[np.argmax(np.sum(band > 0, axis=1))]
            pixels = np.flatnonzero(row)
            runs = np.split(pixels, np.flatnonzero(np.diff(pixels) > 1) + 1)
            if line_thickness > 4 or max((len(run) for run in runs), default=0) < w * 0.5:
                continue
            nearby_symbols = 0
            for idx in range(1, len(stats)):
                _, _, sw, sh, area = stats[idx]
                cx, cy = centroids[idx]
                if (x1 <= cx < x2 and abs(cy - center) <= 24
                        and 3 <= sw <= min(40, w * 0.08) and 4 <= sh <= 50 and area >= 8):
                    nearby_symbols += 1
            if nearby_symbols >= 2:
                single_line = True
        for count in (5, 4, 3):
            for start in range(len(centers) - count + 1):
                group = centers[start:start + count]
                gaps = np.diff(group)
                spacing = float(np.median(gaps))
                tolerance = max(1.0, spacing * 0.22)
                if not 3 <= spacing <= 48 or np.max(np.abs(gaps - spacing)) > tolerance:
                    continue
                if np.max(thickness[start:start + count]) > max(3, spacing * 0.45):
                    continue
                if count != 5:
                    partials.append(float(group[0]))
                    continue
                # An uninterrupted run of six or more rules is not a five-line staff.
                before = start > 0 and abs(group[0] - centers[start - 1] - spacing) <= tolerance
                after = start + 5 < len(centers) and abs(centers[start + 5] - group[-1] - spacing) <= tolerance
                if before or after:
                    continue
                if not any(abs(group[0] - top) < spacing for top, _ in systems):
                    systems.append((float(group[0]), spacing))
                for idx in range(1, len(stats)):
                    sx, sy, sw, sh, area = stats[idx]
                    cx, cy = centroids[idx]
                    if (x1 <= cx < x2 and group[0] - 2 * spacing <= cy <= group[-1] + 2 * spacing
                            and max(2, spacing * 0.25) <= sw <= spacing * 5
                            and spacing * 0.45 <= sh <= spacing * 7
                            and area >= max(3, spacing * 0.7)):
                        notation.add(idx)
    return len(systems), len(partials), len(notation), single_line
