from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


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
) -> LayoutMode:
    if layout_hint in DETECTION_PROFILES:
        return layout_hint  # type: ignore[return-value]

    if prefer_bottom is True:
        return LAYOUT_BOTTOM_BAR
    if prefer_bottom is False:
        return LAYOUT_FULL_SCROLL

    if source_type == "youtube":
        return LAYOUT_BOTTOM_BAR
    return LAYOUT_FULL_SCROLL


def get_detection_profile(layout_mode: LayoutMode) -> DetectionProfile:
    return DETECTION_PROFILES.get(layout_mode, DETECTION_PROFILES[LAYOUT_FULL_SCROLL])
