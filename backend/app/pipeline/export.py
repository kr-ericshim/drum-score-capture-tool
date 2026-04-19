from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.pipeline.sheet_finalize import finalize_sheet_pages
from app.schemas import ExportOptions, PageFillMode

PDF_IMAGE_MAX_EDGE = 2400
PDF_JPEG_QUALITY = 86
PDF_RESOLUTION = 150.0
SCORE_HEADER_BACKGROUND = (255, 255, 255)
SCORE_HEADER_TEXT = (26, 23, 18)
SCORE_HEADER_MUTED = (88, 83, 72)
SCORE_HEADER_RULE = (190, 184, 170)


def export_frames(
    *,
    frame_paths: List[Path],
    options: ExportOptions,
    document_header: Optional[Dict[str, object]] = None,
    workspace: Path,
    logger,
    source_frames: Optional[List[Path]] = None,
) -> Dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    output: Dict[str, object] = {"images": [], "pdf": None, "raw_frames": [], "page_diagnostics": []}

    image_dir = workspace / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    if options.include_raw_frames and source_frames:
        raw_dir = workspace / "raw_frames"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for idx, source_path in enumerate(source_frames):
            target = raw_dir / f"raw_{idx:05d}.png"
            shutil.copy2(source_path, target)
            output["raw_frames"].append(str(target))

    image_paths: List[Path] = []
    wants_png = "png" in options.formats
    wants_jpg = "jpg" in options.formats or "jpeg" in options.formats
    wants_pdf = "pdf" in options.formats
    source_images: List = []
    page_fill_mode = getattr(options, "page_fill_mode", "performance")
    for page_path in frame_paths:
        image = cv2.imread(str(page_path))
        if image is None:
            continue
        source_images.append(image)

    finalized_pages = _finalize_export_pages(
        source_images,
        page_fill_mode=page_fill_mode,
    )

    if not finalized_pages:
        raise RuntimeError("no pages available for export")

    if len(finalized_pages) > len(source_images) and source_images:
        logger(f"export page split: input#{len(source_images)} -> {len(finalized_pages)} pages")

    export_idx = 1
    for finalized in finalized_pages:
        rgb = None
        if wants_jpg:
            rgb = cv2.cvtColor(finalized, cv2.COLOR_BGR2RGB)
        if wants_png:
            out = image_dir / f"page_{export_idx:04d}.png"
            if cv2.imwrite(str(out), finalized):
                image_paths.append(out)
        if wants_jpg:
            out = image_dir / f"page_{export_idx:04d}.jpg"
            if rgb is None:
                rgb = cv2.cvtColor(finalized, cv2.COLOR_BGR2RGB)
            Image.fromarray(rgb).save(out, quality=95)
            image_paths.append(out)
        output["page_diagnostics"].append(_diagnose_page_image(finalized, export_idx))
        export_idx += 1

    if not image_paths and not wants_pdf and not options.include_raw_frames:
        raise RuntimeError("no images could be exported")

    output["images"] = [str(path) for path in image_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]

    if wants_pdf:
        pdf_path = workspace / "sheet_export.pdf"
        pdf_images = _compose_pdf_pages_with_document_header(finalized_pages, document_header)
        if not pdf_images:
            raise RuntimeError("no pages available for PDF export")
        pil_images = [_prepare_pdf_image(img) for img in pdf_images]
        first, *rest = pil_images
        first.save(
            pdf_path,
            "PDF",
            save_all=True,
            append_images=rest,
            quality=PDF_JPEG_QUALITY,
            optimize=True,
            resolution=PDF_RESOLUTION,
        )
        for image in pil_images:
            image.close()
        for image in pdf_images:
            image.close()
        output["pdf"] = str(pdf_path)

    logger(f"exported {len(image_paths)} images")
    return output


def export_selected_pages(
    *,
    page_paths: List[Path],
    formats: List[str],
    page_fill_mode: PageFillMode = "performance",
    document_header: Optional[Dict[str, object]] = None,
    workspace: Path,
    logger,
) -> Dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    output: Dict[str, object] = {"images": [], "pdf": None, "page_diagnostics": [], "preview_images": []}
    image_dir = workspace / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = workspace / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)

    _clear_previous_review_outputs(workspace=workspace, image_dir=image_dir, preview_dir=preview_dir)

    normalized_formats = _normalize_formats(formats)
    wants_png = "png" in normalized_formats
    wants_jpg = "jpg" in normalized_formats
    wants_pdf = "pdf" in normalized_formats

    source_images: List = []
    for page_path in page_paths:
        image = cv2.imread(str(page_path))
        if image is None:
            continue
        source_images.append(image)

    if not source_images:
        raise RuntimeError("no valid pages available for review export")

    finalized_pages = _finalize_export_pages(
        source_images,
        page_fill_mode=page_fill_mode,
    )

    if not finalized_pages:
        raise RuntimeError("no pages available after preparing selected captures")

    if len(finalized_pages) > len(source_images) and source_images:
        logger(f"review export page split: input#{len(source_images)} -> {len(finalized_pages)} pages")
    elif len(source_images) >= 2:
        logger(f"review export preserved captures: {len(source_images)} inputs -> {len(finalized_pages)} pages")

    image_paths: List[Path] = []
    preview_paths: List[Path] = []

    export_idx = 1
    for page in finalized_pages:
        rgb_image = None
        if wants_jpg:
            rgb_image = cv2.cvtColor(page, cv2.COLOR_BGR2RGB)
        if wants_png:
            png_out = image_dir / f"page_{export_idx:04d}.png"
            if cv2.imwrite(str(png_out), page):
                image_paths.append(png_out)
                preview_paths.append(png_out)
        elif cv2.imwrite(str(preview_dir / f"preview_{export_idx:04d}.png"), page):
            preview_paths.append(preview_dir / f"preview_{export_idx:04d}.png")
        if wants_jpg:
            jpg_out = image_dir / f"page_{export_idx:04d}.jpg"
            if rgb_image is None:
                rgb_image = cv2.cvtColor(page, cv2.COLOR_BGR2RGB)
            Image.fromarray(rgb_image).save(jpg_out, quality=95)
            image_paths.append(jpg_out)
        output["page_diagnostics"].append(_diagnose_page_image(page, export_idx))
        export_idx += 1

    if not image_paths and not wants_pdf:
        raise RuntimeError("review export produced no image output")

    output["images"] = [str(path) for path in image_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    output["preview_images"] = [str(path) for path in preview_paths]

    if wants_pdf:
        pdf_path = workspace / "sheet_export.pdf"
        pdf_images = _compose_pdf_pages_with_document_header(finalized_pages, document_header)
        if not pdf_images:
            raise RuntimeError("no pages available for PDF export")
        pil_images = [_prepare_pdf_image(img) for img in pdf_images]
        first, *rest = pil_images
        first.save(
            pdf_path,
            "PDF",
            save_all=True,
            append_images=rest,
            quality=PDF_JPEG_QUALITY,
            optimize=True,
            resolution=PDF_RESOLUTION,
        )
        for image in pil_images:
            image.close()
        for image in pdf_images:
            image.close()
        output["pdf"] = str(pdf_path)

    logger(f"review export saved: {len(finalized_pages)} pages from {len(source_images)} selected captures")
    return output


def _finalize_export_pages(
    images: List[np.ndarray],
    *,
    page_fill_mode: PageFillMode,
) -> List[np.ndarray]:
    finalized_pages: List[np.ndarray] = []
    for image in images:
        pages = finalize_sheet_pages(image, page_fill_mode=page_fill_mode, normalize_tone=False)
        if pages:
            finalized_pages.extend(pages)
            continue
        if image is not None and image.size > 0:
            finalized_pages.append(image)
    return finalized_pages


def _normalize_formats(formats: List[str]) -> List[str]:
    normalized: List[str] = []
    for raw in formats:
        token = str(raw or "").strip().lower()
        if token == "jpeg":
            token = "jpg"
        if token in {"png", "jpg", "pdf"} and token not in normalized:
            normalized.append(token)
    if not normalized:
        return ["png", "pdf"]
    return normalized


def _clear_previous_review_outputs(*, workspace: Path, image_dir: Path, preview_dir: Path) -> None:
    for pattern in ("*.png", "*.jpg", "*.jpeg"):
        for image_path in image_dir.glob(pattern):
            try:
                image_path.unlink()
            except OSError:
                continue
    for image_path in preview_dir.glob("*.png"):
        try:
            image_path.unlink()
        except OSError:
            continue
    pdf_path = workspace / "sheet_export.pdf"
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except OSError:
            pass


def _compose_pdf_pages_with_document_header(
    pages: List[np.ndarray],
    document_header: Optional[Dict[str, object]],
) -> List[Image.Image]:
    normalized_header = _normalize_document_header(document_header)
    pdf_pages: List[Image.Image] = []

    for page_index, page in enumerate(pages):
        rgb_page = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
        if page_index == 0 and normalized_header.get("title"):
            header_band = _render_document_header_band(
                page_size=rgb_page.size,
                document_header=normalized_header,
            )
            composed = Image.new(
                "RGB",
                (rgb_page.size[0], rgb_page.size[1] + header_band.size[1]),
                SCORE_HEADER_BACKGROUND,
            )
            composed.paste(header_band, (0, 0))
            composed.paste(rgb_page, (0, header_band.size[1]))
            composed.info["score_header_band_height"] = int(header_band.size[1])
            header_band.close()
            rgb_page.close()
            pdf_pages.append(composed)
            continue
        pdf_pages.append(rgb_page)

    return pdf_pages


def _render_document_header_band(
    *,
    page_size: tuple[int, int],
    document_header: Dict[str, object],
) -> Image.Image:
    page_width, page_height = page_size
    horizontal_padding = max(46, int(round(page_width * 0.07)))
    column_gap = max(30, int(round(page_width * 0.03)))
    right_column_width = max(210, int(round(page_width * 0.24)))
    note_column_width = max(180, page_width - (horizontal_padding * 2) - right_column_width - column_gap)
    title_max_width = max(240, page_width - max(horizontal_padding * 4, int(round(page_width * 0.30))))
    top_padding = max(38, int(round(page_height * 0.032)))
    bottom_padding = max(26, int(round(page_height * 0.025)))
    title_gap = max(10, int(round(page_height * 0.007)))
    block_gap = max(5, int(round(page_height * 0.004)))
    section_gap = max(18, int(round(page_height * 0.014)))
    title_font = _resolve_score_header_title_font(max(36, int(round(page_width * 0.044))))
    credit_font = _resolve_score_header_font(max(17, int(round(page_width * 0.0185))))
    note_font = _resolve_score_header_font(max(16, int(round(page_width * 0.0175))))
    measuring_image = Image.new("RGB", (page_width, 32), SCORE_HEADER_BACKGROUND)
    draw = ImageDraw.Draw(measuring_image)

    title_lines = _wrap_header_text(
        draw,
        str(document_header.get("title") or "").strip(),
        font=title_font,
        max_width=title_max_width,
        max_lines=3,
    )
    performer_text = str(document_header.get("performer") or "").strip()
    bpm_value = document_header.get("bpm")
    date_text = str(document_header.get("date") or "").strip()
    memo_text = str(document_header.get("memo") or "").strip()

    note_lines = _wrap_header_text(
        draw,
        memo_text,
        font=note_font,
        max_width=note_column_width,
        max_lines=2,
    ) if memo_text else []

    right_column_lines: List[tuple[str, ImageFont.ImageFont]] = []
    if performer_text:
        right_column_lines.append((
            _truncate_text_to_width(draw, performer_text, font=credit_font, max_width=right_column_width),
            credit_font,
        ))
    if bpm_value is not None:
        right_column_lines.append((
            _truncate_text_to_width(draw, f"BPM {bpm_value}", font=note_font, max_width=right_column_width),
            note_font,
        ))
    if date_text:
        right_column_lines.append((
            _truncate_text_to_width(draw, date_text, font=note_font, max_width=right_column_width),
            note_font,
        ))

    title_heights = [_measure_text_height(draw, line, title_font) for line in title_lines]
    note_heights = [_measure_text_height(draw, line, note_font) for line in note_lines]
    right_column_heights = [_measure_text_height(draw, line, font) for line, font in right_column_lines]
    footer_block_height = max(
        sum(note_heights) + (block_gap * max(0, len(note_heights) - 1)),
        sum(right_column_heights) + (block_gap * max(0, len(right_column_heights) - 1)),
    )
    needed_height = top_padding + bottom_padding + sum(title_heights)
    if len(title_heights) > 1:
        needed_height += title_gap * (len(title_heights) - 1)
    if title_heights and footer_block_height:
        needed_height += section_gap
    needed_height += footer_block_height
    needed_height += max(22, int(round(page_height * 0.015)))

    min_band_height = max(168, int(round(page_height * 0.135)))
    max_band_height = max(min_band_height, int(round(page_height * 0.30)))
    band_height = max(min_band_height, min(max_band_height, needed_height))
    band = Image.new("RGB", (page_width, band_height), SCORE_HEADER_BACKGROUND)
    draw = ImageDraw.Draw(band)
    y = top_padding

    for idx, line in enumerate(title_lines):
        draw.text(
            (page_width / 2.0, y),
            line,
            fill=SCORE_HEADER_TEXT,
            font=title_font,
            anchor="mt",
        )
        y += title_heights[idx] + title_gap

    if title_heights and footer_block_height:
        y += section_gap - title_gap

    footer_y = max(y, band_height - bottom_padding - footer_block_height)

    note_y = footer_y
    for idx, line in enumerate(note_lines):
        draw.text(
            (horizontal_padding, note_y),
            line,
            fill=SCORE_HEADER_MUTED,
            font=note_font,
            anchor="la",
        )
        note_y += note_heights[idx] + block_gap

    right_y = footer_y
    for idx, (line, font) in enumerate(right_column_lines):
        draw.text(
            (page_width - horizontal_padding, right_y),
            line,
            fill=SCORE_HEADER_MUTED,
            font=font,
            anchor="ra",
        )
        right_y += right_column_heights[idx] + block_gap

    measuring_image.close()
    return band


def _resolve_score_header_font(size: int) -> ImageFont.ImageFont:
    requested_size = max(12, int(size))
    for font_path in _iter_score_header_font_paths():
        if not font_path.exists():
            continue
        try:
            return ImageFont.truetype(str(font_path), requested_size)
        except OSError:
            continue
    return ImageFont.load_default()


def _resolve_score_header_title_font(size: int) -> ImageFont.ImageFont:
    requested_size = max(12, int(size))
    for font_path in _iter_score_header_title_font_paths():
        if not font_path.exists():
            continue
        try:
            return ImageFont.truetype(str(font_path), requested_size)
        except OSError:
            continue
    return _resolve_score_header_font(requested_size)


def _iter_score_header_font_paths() -> List[Path]:
    windows_root = Path(os.environ.get("WINDIR", "C:/Windows"))
    return [
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        windows_root / "Fonts" / "malgun.ttf",
        Path("/Library/Fonts/NotoSansCJK-Regular.ttc"),
        Path("/Library/Fonts/Noto Sans CJK KR.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ]


def _iter_score_header_title_font_paths() -> List[Path]:
    windows_root = Path(os.environ.get("WINDIR", "C:/Windows"))
    return [
        Path("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"),
        Path("/System/Library/Fonts/Supplemental/AppleMyungjo.ttc"),
        windows_root / "Fonts" / "batang.ttc",
        windows_root / "Fonts" / "batang.ttf",
        Path("/Library/Fonts/NotoSerifCJK-Regular.ttc"),
        Path("/Library/Fonts/Noto Serif CJK KR.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJKkr-Regular.otf"),
        Path("/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf"),
    ]


def _normalize_document_header(document_header: Optional[Dict[str, object]]) -> Dict[str, object]:
    header = document_header or {}
    title = str(header.get("title") or "").strip()
    performer = str(header.get("performer") or "").strip()
    date = str(header.get("date") or "").strip()
    memo = str(header.get("memo") or "").strip()
    bpm = _normalize_document_header_bpm(header.get("bpm"))
    return {
        "title": title,
        "performer": performer,
        "bpm": bpm,
        "date": date,
        "memo": memo,
    }


def _normalize_document_header_bpm(value: object) -> Optional[int]:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.lstrip("+-").isdigit():
        return int(text)
    return None


def _wrap_header_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> List[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []

    lines: List[str] = []
    remaining = normalized
    while remaining and len(lines) < max_lines:
        fitted = ""
        consumed = 0
        for idx in range(1, len(remaining) + 1):
            candidate = remaining[:idx]
            if fitted and _measure_text_width(draw, candidate, font) > max_width:
                break
            fitted = candidate
            consumed = idx
            if _measure_text_width(draw, candidate, font) > max_width:
                break

        if consumed == 0:
            fitted = remaining[:1]
            consumed = 1

        remaining = remaining[consumed:].lstrip()
        if len(lines) == max_lines - 1 and remaining:
            fitted = _truncate_text_to_width(
                draw,
                f"{fitted} {remaining}",
                font=font,
                max_width=max_width,
                ellipsis=True,
            )
            remaining = ""
        else:
            fitted = _truncate_text_to_width(draw, fitted, font=font, max_width=max_width)
        lines.append(fitted)
    return [line for line in lines if line]


def _truncate_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    max_width: int,
    ellipsis: bool = False,
) -> str:
    candidate = text.strip()
    suffix = "..." if ellipsis else ""
    while candidate and _measure_text_width(draw, f"{candidate}{suffix}", font) > max_width:
        candidate = candidate[:-1].rstrip()
    if not candidate:
        return suffix if suffix else text[:1]
    return f"{candidate}{suffix}"


def _measure_text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, int(bbox[2] - bbox[0]))


def _measure_text_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    sample = text or "Ag"
    bbox = draw.textbbox((0, 0), sample, font=font)
    return max(1, int(bbox[3] - bbox[1]))


def _prepare_pdf_image(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    width, height = rgb.size
    header_band_height = int(image.info.get("score_header_band_height") or rgb.info.get("score_header_band_height") or 0)
    content_height = max(1, height - max(0, header_band_height))
    long_edge = max(width, content_height)
    if long_edge > PDF_IMAGE_MAX_EDGE and long_edge > 0:
        scale = PDF_IMAGE_MAX_EDGE / float(long_edge)
        target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        rgb = rgb.resize(target, resampling)

    prepared = rgb.copy()
    rgb.close()
    return prepared


def _diagnose_page_image(image, page_index: int) -> Dict[str, object]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inv = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    h, w = gray.shape[:2]
    row_density = (inv > 0).sum(axis=1).astype("float32") / float(max(1, w))
    top_band = row_density[: max(1, min(48, h))]
    bottom_band = row_density[max(0, h - min(48, h)) :]
    top_score = float(np.mean(top_band)) if top_band.size > 0 else 0.0
    bottom_score = float(np.mean(bottom_band)) if bottom_band.size > 0 else 0.0

    warnings: List[str] = []
    suspicious = False
    if top_score > 0.020:
        suspicious = True
        warnings.append("페이지 상단에 내용이 너무 붙어 있어 이전 페이지에서 잘렸을 수 있습니다.")
    if bottom_score > 0.020:
        suspicious = True
        warnings.append("페이지 하단에 내용이 너무 붙어 있어 다음 페이지로 잘렸을 수 있습니다.")

    return {
        "page_index": int(page_index),
        "suspicious": bool(suspicious),
        "warning_reasons": warnings,
        "top_edge_density": round(top_score, 5),
        "bottom_edge_density": round(bottom_score, 5),
    }
