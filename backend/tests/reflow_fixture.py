"""Synthetic observation manifests for tracking / assembly tests.

Each "frame" is a rendered drum score (drum_score_fixture) with a playback
line; the manifest is built with the real observations helpers
(analyse_crop, assign_slots, assign_roles) so regions, slots and roles come
from the production detector.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.pipeline import observations as ob
from drum_score_fixture import Degrade, Overlay, PageSpec, degrade, groove_notes, render, strip_spec

STEP = 0.25


def strip(seed: int, *, first_bar: int = 1, numbers: bool = False, **kw) -> PageSpec:
    spec = strip_spec(height=190, first_bar_number=first_bar, show_bar_numbers=numbers, **kw)
    return groove_notes(spec, seed=seed)


def page(seeds: Sequence[int], *, first_bar: int = 1, numbers: bool = False) -> PageSpec:
    spec = PageSpec(width=1400, height=110 * len(seeds) + 60, systems=len(seeds), gap=12, first_bar_number=first_bar,
                    show_bar_numbers=numbers)
    out = spec.copy()
    for k, seed in enumerate(seeds):
        one = groove_notes(PageSpec(width=1400, height=200, systems=1, gap=12), seed=seed)
        for (s, b, sl), lines in one.notes.items():
            out.notes[(k, b, sl)] = list(lines)
    return out


def frame(spec: PageSpec, phase: float, *, system: int = 0, shift_x: int = 0, seed: int = 0) -> np.ndarray:
    img = render(spec, [Overlay("line", position=min(0.98, max(0.02, phase)), system=system, color=(220, 120, 40))])
    if shift_x:
        img = np.roll(img, -shift_x, axis=1)
        img[:, -shift_x:] = 255
    return degrade(img, Degrade(blur=0.6, jpeg_quality=90, noise=1.0, seed=seed))


def build(frames: List[Tuple[float, np.ndarray]]) -> Tuple[Dict, Dict[str, np.ndarray]]:
    """Manifest dict + {obs_id: image} from (t, image) pairs."""
    images: Dict[str, np.ndarray] = {}
    observations = []
    for k, (t, img) in enumerate(frames):
        oid = f"obs-{k:06d}"
        images[oid] = img
        ana = ob.analyse_crop(img)
        regions = []
        for ri, r in enumerate(ana["regions"]):
            regions.append({"region_id": f"{oid}-r{ri}", "bbox": r["bbox"], "staff_y": r["staff_y"], "staff_gap_px": r["staff_gap_px"],
                            "staff_x": r["staff_x"], "segments": r["segments"], "bars": r["bars"], "clef": r["clef"],
                            "envelope_bbox": r["envelope_bbox"], "slot_id": None, "role": None, "playhead_x": r["playhead_x"],
                            "issues": r["issues"]})
        observations.append({"id": oid, "t_sec": round(t, 4), "time_basis": "source_pts", "sample_kind": "coarse" if k % 2 == 0 else "fine",
                             "frame_path": None, "crop_size": [img.shape[1], img.shape[0]], "system_regions": regions,
                             "applied_roi": [[0, 0], [img.shape[1], 0], [img.shape[1], img.shape[0]], [0, img.shape[0]]],
                             "source_to_crop": [1, 0, 0, 0, 1, 0, 0, 0, 1]})
    slots = ob.assign_slots(observations)
    for o in observations:
        ob.assign_roles(o)
    manifest = {"schema_version": 1, "kind": "observation_manifest", "video_id": "synthetic", "slots": slots,
                "source_to_crop": [1, 0, 0, 0, 1, 0, 0, 0, 1], "observations": observations}
    return manifest, images


def show(spec: PageSpec, t0: float, seconds: float, *, system: Optional[int] = None, seed: int = 0, phases=None) -> List[Tuple[float, np.ndarray]]:
    n = int(round(seconds / STEP))
    out = []
    for i in range(n):
        ph = (i + 0.5) / n if phases is None else phases(i, n)
        out.append((t0 + i * STEP, frame(spec, ph, system=system or 0, seed=seed * 1000 + i)))
    return out


def loader(images: Dict[str, np.ndarray]):
    return lambda obs: images[obs["id"]]
