from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import notation_envelope
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
    # An ROI edge on (or within 1.5% of) the video frame edge cannot move further
    # out. Paper there is harmless; only notation cut by the frame itself matters.
    at_frame = {"top": top_margin_ratio < 0.015, "bottom": bottom_margin_ratio < 0.015}
    frame_cut_hits = {"top": 0, "bottom": 0}

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
        for side in ("top", "bottom"):
            if at_frame[side] and _ink_cut_by_frame_edge(gray, side=side, frame_height=height, rect=rect):
                frame_cut_hits[side] += 1
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

    # Margins at the frame edge: harmless when the edge rows are paper (info only);
    # a warning when notation reaches the frame edge (cut by the video itself; moving
    # the region cannot recover it). Never critical: it is not an ROI clipping error.
    frame_sides = [side for side in ("top", "bottom") if at_frame[side]]
    cut_sides = [side for side in frame_sides if frame_cut_hits[side] > 0]
    if cut_sides:
        labels = ", ".join("위" if side == "top" else "아래" for side in cut_sides)
        push("warning", "frame_edge_content", "화면 끝에 닿은 악보",
             f"악보 기호가 영상 화면 끝({labels})에 닿아 있습니다. 영상 자체에서 잘린 부분은 영역을 넓혀도 되살릴 수 없습니다.")
    elif frame_sides:
        push("info", "roi_at_frame_edge", "화면 끝까지 선택됨", "영역이 영상 화면 끝까지 닿아 있지만 그 가장자리는 빈 종이입니다.")

    # Content near an ROI edge that can still move out is a clipping risk.
    if top_edge_hits > 0 and not at_frame["top"]:
        level = "critical" if top_edge_hits >= max(1, sampled_frames - 1) else "warning"
        push(level, "top_edge_busy", "상단 잘림 위험", f"샘플 프레임 {top_edge_hits}개에서 상단 경계가 악보 내용과 가깝습니다.")

    if bottom_edge_hits > 0 and not at_frame["bottom"]:
        level = "critical" if bottom_edge_hits >= max(1, sampled_frames - 1) else "warning"
        push(level, "bottom_edge_busy", "하단 잘림 위험", f"샘플 프레임 {bottom_edge_hits}개에서 하단 경계가 악보 내용과 가깝습니다.")

    if low_density_hits >= max(1, sampled_frames - 1):
        push("warning", "content_sparse", "내용 밀도 낮음", "선택 영역 안의 악보 밀도가 낮아 현재 프레임이 적절하지 않을 수 있습니다.")

    if all(item["level"] == "info" for item in diagnostics) and not any(item["code"] == "roi_healthy" for item in diagnostics):
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
            "roi_at_frame_edge": {side: bool(flag) for side, flag in at_frame.items()},
            "frame_edge_cut_hits": {side: int(count) for side, count in frame_cut_hits.items()},
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

    if not frames:
        raise RuntimeError("preview extraction failed for all sampled frames")

    analysis = analyze_roi_health_frames(frames, roi)
    analysis["checked_seconds"] = checked_seconds
    try:
        envelope = notation_envelope.analyze_source(
            source_type=source_type,
            file_path=file_path,
            youtube_url=youtube_url,
            workspace=workspace,
            logger=logger,
        )
    except Exception as exc:
        logger(f"roi health notation envelope failed: {exc}")
        envelope = {"status": "error", "reason": str(exc)}
    return add_envelope_clipping(analysis, envelope, roi)


def add_envelope_clipping(
    analysis: Dict[str, object],
    envelope: Dict[str, object],
    roi: Sequence[Sequence[float]],
) -> Dict[str, object]:
    """Add the whole-source clipping check (``ENVELOPE_CLIPPED``) to an analysis.

    Every content-bearing component near or beyond an ROI edge counts, so one
    small circle is enough (design section 3, step 7). The level is
    ``warning``: it informs and proposes a larger draft, it does not block
    capture.
    """
    out = dict(analysis)
    status = str(envelope.get("status") or "unavailable")
    report: Dict[str, object] = {
        "status": status,
        "sampled_times": list(envelope.get("sampled_times") or []),
        "score_times": list(envelope.get("score_times") or []),
        "envelope_bbox": envelope.get("envelope_bbox"),
        "flags": list(envelope.get("flags") or []),
        "clipped": False,
        "code": "",
        "counts": {},
        "cut_counts": {},
        "locations": [],
        "frames_with_clipping": [],
        "suggested_roi": None,
    }
    if status == "found":
        clip = notation_envelope.check_roi_clipping(envelope, roi)
        report.update(clip)
    out["envelope"] = report
    if status == "found" and not report["clipped"]:
        # The whole-source, component-level check found no cut notation. Edge
        # density near the ROI edge then comes from video, UI or paper texture
        # (e.g. drum footage behind a dark score band), not from clipped notes.
        diagnostics = []
        for item in list(out.get("diagnostics") or []):
            if item.get("code") in ("top_edge_busy", "bottom_edge_busy") and item.get("level") in ("critical", "warning"):
                item = dict(item, level="info", detail=f"{item.get('detail', '')} 영상 전체 점검에서는 잘린 기호가 없습니다.".strip(),
                            downgraded_by="envelope_check")
            diagnostics.append(item)
        out["diagnostics"] = diagnostics
        levels = [str(item.get("level") or "info") for item in diagnostics]
        out["risk_level"] = "critical" if "critical" in levels else "warning" if "warning" in levels else "info"
    if report["clipped"]:
        diagnostics = list(out.get("diagnostics") or [])
        diagnostics = [item for item in diagnostics if item.get("code") != "roi_healthy"]
        counts = report["counts"] if isinstance(report["counts"], dict) else {}
        sides = [label for key, label in (("top", "위"), ("bottom", "아래"), ("left", "왼쪽"), ("right", "오른쪽")) if counts.get(key)]
        if counts.get("staff_outside"):
            sides.append("영역 밖 악보 줄")
        frames_hit = len(report["frames_with_clipping"] or [])
        diagnostics.append({
            "level": "warning",
            "code": "envelope_clipped",
            "title": "악보 위아래가 잘렸습니다",
            "detail": f"영상 전체 샘플 {len(report['score_times'])}개 중 {frames_hit}개에서 기호나 글자가 영역 경계({', '.join(sides)})에 걸립니다.",
        })
        out["diagnostics"] = diagnostics
        if out.get("risk_level") == "info":
            out["risk_level"] = "warning"
    return out


def _ink_cut_by_frame_edge(gray: np.ndarray, *, side: str, frame_height: int, rect: Tuple[int, int, int, int]) -> bool:
    """Notation touching the video frame's own top/bottom rows inside the ROI columns.

    ``gray`` is the ROI crop. Only applies when the ROI edge is within the outer
    1.5% of the frame; the rows between the ROI edge and the frame edge are not
    visible here, so the crop's outermost rows stand for the frame edge when
    the ROI reaches it, and nothing is reported otherwise. Long thin
    horizontal lines (a UI border, a staff line) are not notation.
    """
    h, w = gray.shape[:2]
    reaches = rect[1] <= 1 if side == "top" else rect[3] >= frame_height - 1
    if not reaches or h < 8:
        return False
    paper = float(np.percentile(gray, 75))
    dark = paper >= 110
    ink = (gray < paper - 60) if dark else (gray > paper + 60)
    ink = ink.astype(np.uint8)
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    edge_rows = 2
    hits = 0
    for idx in range(1, count):
        x, y, bw, bh, area = stats[idx]
        if area < 6 or (bw > 0.5 * w and bh <= 4):
            continue
        touches = y < edge_rows if side == "top" else y + bh > h - edge_rows
        if touches:
            hits += 1
    return hits >= 2


def should_block_roi_capture(analysis: Dict[str, object]) -> bool:
    return str(analysis.get("risk_level") or "info").strip().lower() == "critical"


def pad_roi_rect(
    roi: Sequence[Sequence[float]],
    *,
    image_width: int,
    image_height: int,
    pad_ratio_y: float = 0.03,
    pad_ratio_x: float = 0.01,
) -> List[List[float]]:
    x1, y1, x2, y2 = _normalize_roi_rect(roi, image_width, image_height)
    pad_y = max(8, int(round((y2 - y1) * pad_ratio_y)))
    pad_x = max(4, int(round((x2 - x1) * pad_ratio_x)))
    return [
        [float(max(0, x1 - pad_x)), float(max(0, y1 - pad_y))],
        [float(min(image_width, x2 + pad_x)), float(max(0, y1 - pad_y))],
        [float(min(image_width, x2 + pad_x)), float(min(image_height, y2 + pad_y))],
        [float(max(0, x1 - pad_x)), float(min(image_height, y2 + pad_y))],
    ]


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
