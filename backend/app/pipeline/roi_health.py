from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline.extract import extract_preview_frame


def analyze_roi_health_frames(
    frames: Sequence[np.ndarray],
    roi: Sequence[Sequence[float]],
) -> Dict[str, object]:
    if not frames:
        return {
            "risk_level": "info",
            "summary": "분석할 프레임이 없습니다.",
            "diagnostics": [],
            "sampled_frames": 0,
            "metrics": {},
        }

    height, width = frames[0].shape[:2]
    rect = _normalize_roi_rect(roi, width, height)
    roi_width = max(1, rect[2] - rect[0])
    roi_height = max(1, rect[3] - rect[1])
    width_ratio = roi_width / float(max(1, width))
    height_ratio = roi_height / float(max(1, height))
    top_margin_ratio = rect[1] / float(max(1, height))
    bottom_margin_ratio = (height - rect[3]) / float(max(1, height))

    top_edge_hits = 0
    bottom_edge_hits = 0
    low_density_hits = 0
    avg_density_values: List[float] = []

    for frame in frames:
        crop = frame[rect[1] : rect[3], rect[0] : rect[2]]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        inv = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            7,
        )
        crop_h, crop_w = gray.shape[:2]
        density = float(np.mean(inv > 0))
        avg_density_values.append(density)

        edge_band = max(4, min(28, crop_h // 5 or 4))
        top_density = float(np.mean(inv[:edge_band, :] > 0)) if crop_h > 0 else 0.0
        bottom_density = float(np.mean(inv[max(0, crop_h - edge_band) :, :] > 0)) if crop_h > 0 else 0.0

        if top_density > 0.058:
            top_edge_hits += 1
        if bottom_density > 0.058:
            bottom_edge_hits += 1
        if density < 0.018:
            low_density_hits += 1

    sampled_frames = len(avg_density_values)
    avg_density = float(np.mean(avg_density_values)) if avg_density_values else 0.0
    diagnostics: List[Dict[str, str]] = []
    risk_level = "info"

    def push(level: str, code: str, title: str, detail: str) -> None:
        nonlocal risk_level
        diagnostics.append({
            "level": level,
            "code": code,
            "title": title,
            "detail": detail,
        })
        if level == "critical":
            risk_level = "critical"
        elif level == "warning" and risk_level == "info":
            risk_level = "warning"

    if width_ratio < 0.34:
        push("warning", "roi_width_low", "좌우 폭 부족", "ROI 폭이 좁아 좌우 악보 끝이 잘릴 수 있습니다.")
    elif width_ratio > 0.96:
        push("warning", "roi_width_high", "좌우 폭 과다", "ROI 폭이 너무 넓어 플레이어 UI나 빈 여백이 포함될 수 있습니다.")

    if height_ratio < 0.18:
        push("warning", "roi_height_low", "세로 범위 부족", "ROI 높이가 얕아 여러 줄 악보가 빠질 수 있습니다.")
    elif height_ratio > 0.88:
        push("warning", "roi_height_high", "세로 범위 과다", "ROI 높이가 너무 커서 불필요한 배경이 많이 포함될 수 있습니다.")

    if top_margin_ratio < 0.015 or bottom_margin_ratio < 0.015:
        push("critical", "roi_margin_tight", "상하 여백 부족", "상단 또는 하단 경계가 너무 바짝 붙어 있어 잘림 위험이 큽니다.")

    if top_edge_hits > 0:
        level = "critical" if top_edge_hits >= max(1, sampled_frames - 1) else "warning"
        push(level, "top_edge_busy", "상단 잘림 위험", f"샘플 프레임 {top_edge_hits}개에서 상단 경계가 악보 내용과 가깝습니다.")

    if bottom_edge_hits > 0:
        level = "critical" if bottom_edge_hits >= max(1, sampled_frames - 1) else "warning"
        push(level, "bottom_edge_busy", "하단 잘림 위험", f"샘플 프레임 {bottom_edge_hits}개에서 하단 경계가 악보 내용과 가깝습니다.")

    if low_density_hits >= max(1, sampled_frames - 1):
        push("warning", "content_sparse", "내용 밀도 낮음", "선택 영역 안의 악보 밀도가 낮아 현재 프레임이 적절하지 않을 수 있습니다.")

    if not diagnostics:
        push("info", "roi_healthy", "ROI 상태 양호", "샘플 프레임 기준으로 뚜렷한 잘림 위험이 보이지 않습니다.")

    return {
        "risk_level": risk_level,
        "summary": f"샘플 프레임 {sampled_frames}개 기준으로 ROI를 점검했습니다.",
        "diagnostics": diagnostics,
        "sampled_frames": sampled_frames,
        "metrics": {
            "width_ratio": round(width_ratio, 5),
            "height_ratio": round(height_ratio, 5),
            "top_margin_ratio": round(top_margin_ratio, 5),
            "bottom_margin_ratio": round(bottom_margin_ratio, 5),
            "average_content_density": round(avg_density, 5),
            "top_edge_hits": int(top_edge_hits),
            "bottom_edge_hits": int(bottom_edge_hits),
            "low_density_hits": int(low_density_hits),
        },
    }


def analyze_roi_health_for_source(
    *,
    source_type: str,
    file_path: Optional[str],
    youtube_url: Optional[str],
    start_sec: Optional[float],
    roi: Sequence[Sequence[float]],
    workspace: Path,
    logger,
) -> Dict[str, object]:
    base_sec = max(0.0, float(start_sec or 0.0))
    sample_offsets = [0.0, 0.8, 1.6]
    frames: List[np.ndarray] = []
    checked_seconds: List[float] = []

    for offset in sample_offsets:
        sec = max(0.0, base_sec + offset)
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
        except Exception:
            continue

    analysis = analyze_roi_health_frames(frames, roi)
    analysis["checked_seconds"] = checked_seconds
    return analysis


def _normalize_roi_rect(
    roi: Sequence[Sequence[float]],
    width: int,
    height: int,
) -> Tuple[int, int, int, int]:
    xs = [float(point[0]) for point in roi]
    ys = [float(point[1]) for point in roi]
    x1 = int(max(0, min(width - 1, round(min(xs)))))
    y1 = int(max(0, min(height - 1, round(min(ys)))))
    x2 = int(max(x1 + 1, min(width, round(max(xs)))))
    y2 = int(max(y1 + 1, min(height, round(max(ys)))))
    return x1, y1, x2, y2
