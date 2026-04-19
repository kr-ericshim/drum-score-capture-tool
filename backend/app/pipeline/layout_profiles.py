from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence


LayoutMode = Literal["bottom_bar", "full_scroll", "page_turn"]
FallbackMode = Literal["bottom", "center", "full_page"]


LAYOUT_AUTO = "auto"
LAYOUT_BOTTOM_BAR: LayoutMode = "bottom_bar"
LAYOUT_FULL_SCROLL: LayoutMode = "full_scroll"
LAYOUT_PAGE_TURN: LayoutMode = "page_turn"


@dataclass(frozen=True)
class DetectionProfile:
    key: LayoutMode
    prefer_bottom: bool
    confidence_threshold: float
    area_target: float
    area_tolerance: float
    page_aspect_target: float
    page_aspect_tolerance: float
    strip_aspect_target: float
    strip_aspect_tolerance: float
    center_y_target: float
    center_y_tolerance: float
    fallback_mode: FallbackMode


DETECTION_PROFILES: dict[LayoutMode, DetectionProfile] = {
    LAYOUT_BOTTOM_BAR: DetectionProfile(
        key=LAYOUT_BOTTOM_BAR,
        prefer_bottom=True,
        confidence_threshold=0.42,
        area_target=0.24,
        area_tolerance=0.34,
        page_aspect_target=1.35,
        page_aspect_tolerance=1.1,
        strip_aspect_target=4.5,
        strip_aspect_tolerance=3.6,
        center_y_target=0.81,
        center_y_tolerance=0.34,
        fallback_mode="bottom",
    ),
    LAYOUT_FULL_SCROLL: DetectionProfile(
        key=LAYOUT_FULL_SCROLL,
        prefer_bottom=False,
        confidence_threshold=0.36,
        area_target=0.64,
        area_tolerance=0.38,
        page_aspect_target=1.6,
        page_aspect_tolerance=1.25,
        strip_aspect_target=3.0,
        strip_aspect_tolerance=2.4,
        center_y_target=0.52,
        center_y_tolerance=0.45,
        fallback_mode="full_page",
    ),
    LAYOUT_PAGE_TURN: DetectionProfile(
        key=LAYOUT_PAGE_TURN,
        prefer_bottom=False,
        confidence_threshold=0.34,
        area_target=0.62,
        area_tolerance=0.4,
        page_aspect_target=1.55,
        page_aspect_tolerance=1.35,
        strip_aspect_target=2.8,
        strip_aspect_tolerance=2.2,
        center_y_target=0.52,
        center_y_tolerance=0.48,
        fallback_mode="full_page",
    ),
}


def resolve_layout_hint(
    layout_hint: Optional[str],
    *,
    source_type: Optional[str],
    prefer_bottom: Optional[bool] = None,
    roi: Optional[Sequence[Sequence[float]]] = None,
) -> LayoutMode:
    if layout_hint in DETECTION_PROFILES:
        return layout_hint  # type: ignore[return-value]

    if prefer_bottom is True:
        return LAYOUT_BOTTOM_BAR
    if prefer_bottom is False:
        return LAYOUT_FULL_SCROLL

    return infer_layout_hint_from_roi(roi, source_type=source_type)


def infer_layout_hint_from_roi(
    roi: Optional[Sequence[Sequence[float]]],
    *,
    source_type: Optional[str],
) -> LayoutMode:
    bounds = _roi_bounds(roi)
    if bounds is None:
        if source_type == "youtube":
            return LAYOUT_BOTTOM_BAR
        return LAYOUT_FULL_SCROLL

    width, height = bounds
    if width <= 0.0 or height <= 0.0:
        if source_type == "youtube":
            return LAYOUT_BOTTOM_BAR
        return LAYOUT_FULL_SCROLL

    aspect = width / max(1e-6, height)
    if aspect >= 2.25:
        return LAYOUT_BOTTOM_BAR
    if aspect <= 1.05:
        return LAYOUT_PAGE_TURN
    return LAYOUT_FULL_SCROLL


def _roi_bounds(roi: Optional[Sequence[Sequence[float]]]) -> Optional[tuple[float, float]]:
    if not roi or len(roi) != 4:
        return None
    try:
        xs = [float(point[0]) for point in roi]
        ys = [float(point[1]) for point in roi]
    except (TypeError, ValueError, IndexError):
        return None
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    return width, height


def get_detection_profile(layout_mode: LayoutMode) -> DetectionProfile:
    return DETECTION_PROFILES.get(layout_mode, DETECTION_PROFILES[LAYOUT_FULL_SCROLL])
