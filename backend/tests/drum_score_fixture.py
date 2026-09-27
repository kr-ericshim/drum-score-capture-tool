"""Synthetic drum-score frames for dedupe / page-diff tests.

Renders a plain drum notation page (5-line staves, x/oval note heads, stems,
bar lines, bar numbers) and optional playback overlays, then degrades it the
way a captured video frame would be (rescale, blur, JPEG, jitter, tone drift).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class PageSpec:
    width: int = 1400
    height: int = 900
    systems: int = 4
    bars_per_system: int = 4
    slots_per_bar: int = 8
    gap: int = 12  # staff line spacing in px
    margin_x: int = 70
    first_bar_number: int = 1
    # notes[(system, bar, slot)] = list of line indexes (0=top line .. 4=bottom line, halves allowed)
    notes: Dict[Tuple[int, int, int], List[float]] = field(default_factory=dict)
    show_bar_numbers: bool = True

    def copy(self) -> "PageSpec":
        return PageSpec(
            width=self.width,
            height=self.height,
            systems=self.systems,
            bars_per_system=self.bars_per_system,
            slots_per_bar=self.slots_per_bar,
            gap=self.gap,
            margin_x=self.margin_x,
            first_bar_number=self.first_bar_number,
            notes={key: list(value) for key, value in self.notes.items()},
            show_bar_numbers=self.show_bar_numbers,
        )


@dataclass
class Overlay:
    kind: str  # "line" | "box" | "progress"
    position: float  # 0..1 along the page (line/box: x fraction within system; progress: fraction)
    system: int = 0
    color: Tuple[int, int, int] = (40, 40, 220)  # BGR
    thickness: int = 3


@dataclass
class Degrade:
    scale: float = 1.0  # downscale then upscale (video resolution loss)
    blur: float = 0.0  # gaussian sigma
    jpeg_quality: int = 0  # 0 = no jpeg
    jitter: Tuple[int, int] = (0, 0)  # (dx, dy) translation of the whole frame
    gain: float = 1.0
    bias: float = 0.0
    noise: float = 0.0  # gaussian noise sigma
    seed: int = 0


def strip_spec(**kwargs) -> PageSpec:
    """A bottom-bar style single-system strip."""
    base = dict(width=1400, height=190, systems=1, bars_per_system=4, gap=14, margin_x=60)
    base.update(kwargs)
    return PageSpec(**base)


def groove_notes(spec: PageSpec, *, seed: int = 7, density: float = 0.55, repeat_bar: bool = False) -> PageSpec:
    """Fill a spec with a plausible rock groove (hi-hat 8ths, kick/snare pattern)."""
    rng = random.Random(seed)
    spec = spec.copy()
    pattern: Optional[Dict[int, List[float]]] = None
    for system in range(spec.systems):
        for bar in range(spec.bars_per_system):
            if repeat_bar and pattern is not None:
                for slot, lines in pattern.items():
                    spec.notes[(system, bar, slot)] = list(lines)
                continue
            bar_pattern: Dict[int, List[float]] = {}
            for slot in range(spec.slots_per_bar):
                lines: List[float] = []
                if rng.random() < density + 0.3:
                    lines.append(-0.5)  # hi-hat above the staff (x head)
                if slot % 4 == 0 and rng.random() < 0.9:
                    lines.append(4.0)  # kick on bottom space
                if slot % 4 == 2 and rng.random() < 0.9:
                    lines.append(1.5)  # snare
                elif rng.random() < density * 0.25:
                    lines.append(2.5)  # tom
                if lines:
                    bar_pattern[slot] = lines
                    spec.notes[(system, bar, slot)] = list(lines)
            if pattern is None:
                pattern = bar_pattern
    return spec


def system_top(spec: PageSpec, system: int) -> int:
    usable = spec.height - 2 * spec.gap * 4
    pitch = usable / float(spec.systems)
    return int(spec.gap * 4 + system * pitch + (pitch - spec.gap * 4) / 2.0)


def slot_x(spec: PageSpec, bar: int, slot: int) -> int:
    bar_w = (spec.width - 2 * spec.margin_x) / float(spec.bars_per_system)
    slot_w = bar_w / float(spec.slots_per_bar)
    return int(spec.margin_x + bar * bar_w + slot_w * (slot + 0.6))


def render(spec: PageSpec, overlays: Optional[List[Overlay]] = None) -> np.ndarray:
    image = np.full((spec.height, spec.width, 3), 255, dtype=np.uint8)
    ink = (20, 20, 20)
    gap = spec.gap
    bar_w = (spec.width - 2 * spec.margin_x) / float(spec.bars_per_system)

    # Overlays under the ink when they are highlight boxes.
    for overlay in overlays or []:
        if overlay.kind == "box":
            top = system_top(spec, overlay.system)
            bar = int(min(spec.bars_per_system - 1, max(0, overlay.position * spec.bars_per_system)))
            x0 = int(spec.margin_x + bar * bar_w)
            x1 = int(x0 + bar_w)
            box = image.copy()
            cv2.rectangle(box, (x0, top - int(gap * 2.5)), (x1, top + int(gap * 6.5)), overlay.color, -1)
            image = cv2.addWeighted(image, 0.55, box, 0.45, 0)

    for system in range(spec.systems):
        top = system_top(spec, system)
        for line in range(5):
            y = top + line * gap
            cv2.line(image, (spec.margin_x, y), (spec.width - spec.margin_x, y), ink, 2)
        for bar in range(spec.bars_per_system + 1):
            x = int(spec.margin_x + bar * bar_w)
            cv2.line(image, (x, top), (x, top + 4 * gap), ink, 2)
        if spec.show_bar_numbers:
            for bar in range(spec.bars_per_system):
                number = spec.first_bar_number + system * spec.bars_per_system + bar
                x = int(spec.margin_x + bar * bar_w) + 4
                cv2.putText(image, str(number), (x, top - int(gap * 1.9)), cv2.FONT_HERSHEY_SIMPLEX, gap / 28.0, ink, 1, cv2.LINE_AA)
        for bar in range(spec.bars_per_system):
            for slot in range(spec.slots_per_bar):
                lines = spec.notes.get((system, bar, slot))
                if not lines:
                    continue
                x = slot_x(spec, bar, slot)
                # A filled head fills the staff space (1 gap tall, ~1.2 gaps wide).
                head_rx = max(3, int(round(gap * 0.6)))
                head_ry = max(2, int(round(gap * 0.45)))
                for line_index in lines:
                    y = int(round(top + line_index * gap))
                    if line_index < 0:
                        # hi-hat / cymbal: x head
                        cv2.line(image, (x - head_ry, y - head_ry), (x + head_ry, y + head_ry), ink, 2)
                        cv2.line(image, (x - head_ry, y + head_ry), (x + head_ry, y - head_ry), ink, 2)
                    else:
                        cv2.ellipse(image, (x, y), (head_rx, head_ry), -20, 0, 360, ink, -1)
                lowest = int(round(top + max(lines) * gap))
                stem_x = x + head_rx
                cv2.line(image, (stem_x, lowest), (stem_x, top - int(gap * 2.2)), ink, 2)
                # 8th beam stub
                cv2.line(image, (stem_x, top - int(gap * 2.2)), (stem_x + int(gap * 0.9), top - int(gap * 2.2)), ink, 3)

    for overlay in overlays or []:
        if overlay.kind == "line":
            top = system_top(spec, overlay.system)
            x = int(spec.margin_x + overlay.position * (spec.width - 2 * spec.margin_x))
            cv2.line(image, (x, top - int(gap * 3)), (x, top + int(gap * 7)), overlay.color, overlay.thickness)
        elif overlay.kind == "progress":
            y = spec.height - 6
            cv2.line(image, (0, y), (spec.width, y), (200, 200, 200), 4)
            cv2.line(image, (0, y), (int(spec.width * overlay.position), y), overlay.color, 4)
    return image


def degrade(image: np.ndarray, spec_or_degrade: Degrade) -> np.ndarray:
    d = spec_or_degrade
    out = image
    rng = np.random.default_rng(d.seed)
    if d.jitter != (0, 0):
        dx, dy = d.jitter
        matrix = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
        out = cv2.warpAffine(out, matrix, (out.shape[1], out.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    if d.scale != 1.0:
        h, w = out.shape[:2]
        small = cv2.resize(out, (max(8, int(w * d.scale)), max(8, int(h * d.scale))), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if d.blur > 0:
        out = cv2.GaussianBlur(out, (0, 0), d.blur)
    if d.gain != 1.0 or d.bias != 0.0:
        out = np.clip(out.astype(np.float32) * d.gain + d.bias, 0, 255).astype(np.uint8)
    if d.noise > 0:
        out = np.clip(out.astype(np.float32) + rng.normal(0, d.noise, out.shape), 0, 255).astype(np.uint8)
    if d.jpeg_quality > 0:
        ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), int(d.jpeg_quality)])
        if ok:
            out = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return out


VIDEO_LIKE = Degrade(scale=0.75, blur=0.8, jpeg_quality=70, noise=2.0)


def add_note(spec: PageSpec, system: int, bar: int, slot: int, line: float) -> PageSpec:
    spec = spec.copy()
    spec.notes.setdefault((system, bar, slot), []).append(line)
    return spec


def remove_slot(spec: PageSpec, system: int, bar: int, slot: int) -> PageSpec:
    spec = spec.copy()
    spec.notes.pop((system, bar, slot), None)
    return spec


def move_note(spec: PageSpec, system: int, bar: int, slot: int, from_line: float, to_line: float) -> PageSpec:
    spec = spec.copy()
    lines = spec.notes.get((system, bar, slot), [])
    spec.notes[(system, bar, slot)] = [to_line if abs(v - from_line) < 1e-6 else v for v in lines]
    return spec
