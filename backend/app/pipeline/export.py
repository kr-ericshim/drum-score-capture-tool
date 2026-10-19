from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2

from app.pipeline.process_control import checkpoint, report_progress
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.pipeline.score_quality import analyze_score_structure

PDF_IMAGE_MAX_EDGE = 3600
PDF_JPEG_QUALITY = 86
PDF_RESOLUTION = 300.0
SCORE_HEADER_BACKGROUND = (255, 255, 255)
SCORE_HEADER_TEXT = (26, 23, 18)
SCORE_HEADER_MUTED = (88, 83, 72)


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


def _diagnose_page_image(image, page_index: int) -> Dict[str, object]:
    structure = analyze_score_structure(image)
    has_score = structure["has_score_structure"]
    possible_staff = (structure["staff_systems"] > 0 or structure["partial_staff_groups"] > 0
                      or structure["possible_single_line_notation"])
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
    col_density = (inv > 0).sum(axis=0).astype("float32") / float(max(1, h))
    top_band = row_density[: max(1, min(48, h))]
    bottom_band = row_density[max(0, h - min(48, h)) :]
    top_score = float(np.mean(top_band)) if top_band.size > 0 else 0.0
    bottom_score = float(np.mean(bottom_band)) if bottom_band.size > 0 else 0.0
    ink_ratio = float(np.mean(inv > 0)) if inv.size > 0 else 0.0
    active_rows = np.where(row_density > 0.003)[0]
    active_cols = np.where(col_density > 0.003)[0]
    if active_rows.size > 0:
        content_height_ratio = float((int(active_rows[-1]) - int(active_rows[0]) + 1) / max(1, h))
    else:
        content_height_ratio = 0.0
    if active_cols.size > 0:
        content_width_ratio = float((int(active_cols[-1]) - int(active_cols[0]) + 1) / max(1, w))
    else:
        content_width_ratio = 0.0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    color_mask = np.logical_and.reduce((saturation > 48, value > 32, value < 248))
    color_content_ratio = float(np.mean(color_mask)) if color_mask.size > 0 else 0.0

    warnings: List[str] = []
    diagnostic_codes: List[str] = []
    suspicious = False
    if top_score > 0.020:
        suspicious = True
        diagnostic_codes.append("top_edge_content")
        warnings.append("페이지 상단에 내용이 너무 붙어 있어 이전 페이지에서 잘렸을 수 있습니다.")
    if bottom_score > 0.020:
        suspicious = True
        diagnostic_codes.append("bottom_edge_content")
        warnings.append("페이지 하단에 내용이 너무 붙어 있어 다음 페이지로 잘렸을 수 있습니다.")
    if not possible_staff and (ink_ratio < 0.0035 or (content_height_ratio < 0.055 and content_width_ratio < 0.45)):
        suspicious = True
        diagnostic_codes.append("mostly_blank_page")
        warnings.append("페이지에 악보 내용이 거의 없어 출력에서 제외하는 편이 안전합니다.")
    elif not has_score and content_height_ratio < 0.24:
        suspicious = True
        diagnostic_codes.append("sparse_score_page")
        warnings.append("페이지에 악보 내용이 적어 앞뒤 페이지와 함께 확인해야 합니다.")
    photo_like = color_content_ratio > 0.085 or (structure["paper_ratio"] < 0.55 and structure["texture_ratio"] > 0.12)
    if not possible_staff and photo_like:
        suspicious = True
        diagnostic_codes.append("video_frame_content")
        warnings.append("악보가 아닌 영상 화면이 함께 들어간 것으로 보입니다. ROI를 다시 잡는 편이 안전합니다.")
    elif has_score and photo_like and structure["paper_ratio"] < 0.82:
        suspicious = True
        diagnostic_codes.append("mixed_visual_content")
        warnings.append("악보 구조와 배경 영상 또는 넓은 색상 영역이 함께 보입니다. 악보는 포함하고 영역 확인을 권장합니다.")

    should_exclude = any(code in diagnostic_codes for code in ("mostly_blank_page", "video_frame_content"))
    classification = "score" if has_score else "non_score" if should_exclude else "uncertain"
    if classification == "uncertain":
        suspicious = True
        diagnostic_codes.append("score_structure_uncertain")
        warnings.append("오선과 음표 구조를 확실히 확인하지 못했습니다. 악보가 빠지지 않도록 포함했습니다.")

    return {
        "page_index": int(page_index),
        "suspicious": bool(suspicious),
        "warning_reasons": warnings,
        "diagnostic_codes": diagnostic_codes,
        "top_edge_density": round(top_score, 5),
        "bottom_edge_density": round(bottom_score, 5),
        "ink_ratio": round(ink_ratio, 5),
        "content_height_ratio": round(content_height_ratio, 5),
        "content_width_ratio": round(content_width_ratio, 5),
        "color_content_ratio": round(color_content_ratio, 5),
        "score_classification": classification,
        "score_evidence": structure,
        "classification_method": "staff_geometry_v1",
        "recommended_action": "exclude" if should_exclude else "review" if suspicious else "keep",
    }


def diagnose_capture_sequence(frame_paths: Sequence[Path]) -> Dict[str, Dict[str, object]]:
    """Diagnose original captures; adjacent matching scores can rescue faint staffs.

    Neighbours only strengthen positive evidence. They never cause exclusion, and
    only the immediate candidates on BOTH sides may support a weak capture.
    """
    diagnostics = {}
    thumbnails = {}
    for index, path in enumerate(frame_paths):
        checkpoint()
        image = cv2.imread(str(path))
        if image is None:
            continue
        key = str(path)
        diagnostics[key] = _diagnose_page_image(image, index + 1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (128, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
        thumbnails[key] = (small - float(small.mean())) / max(12.0, float(small.std()))
    original_classes = {key: item["score_classification"] for key, item in diagnostics.items()}
    for index in range(1, len(frame_paths) - 1):
        key = str(frame_paths[index])
        item = diagnostics.get(key)
        if not item or original_classes[key] != "uncertain":
            continue
        evidence = item["score_evidence"]
        if not evidence["staff_systems"] and not evidence["partial_staff_groups"]:
            continue
        neighbors = [str(frame_paths[index - 1]), str(frame_paths[index + 1])]
        if not all(original_classes.get(neighbor) == "score" for neighbor in neighbors):
            continue
        if not all(float(np.mean(np.abs(thumbnails[key] - thumbnails[neighbor]))) < 0.22 for neighbor in neighbors):
            continue
        item["score_classification"] = "score"
        evidence["neighbor_supported"] = True
        # Keep edge/cropping warnings, but resolve the uncertain-structure warning.
        pairs = [(code, warning) for code, warning in zip(item["diagnostic_codes"], item["warning_reasons"])
                 if code not in {"score_structure_uncertain", "sparse_score_page"}]
        item["diagnostic_codes"] = [code for code, _ in pairs]
        item["warning_reasons"] = [warning for _, warning in pairs]
        item["suspicious"] = bool(pairs)
        item["recommended_action"] = "review" if pairs else "keep"
    return diagnostics


COMPOSED_JPEG_QUALITY = 92
COMPOSED_PREVIEW_WIDTH = 1240


def _write_composed_pdf(path: Path, pages: Sequence[np.ndarray], dpi: float) -> None:
    """Deterministic, one-image-per-page PDF; compress pixels without a codec round trip.

    Near-gray BGR pages use OpenCV's 8-bit luminance conversion (max chroma <= 24).
    Color pages retain all RGB bytes. Only one page's encoded pixels are held at a time.
    """
    import zlib

    offsets = [0]
    with path.open("wb") as fh:
        fh.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

        def obj(ident: int, body: bytes) -> None:
            offsets.append(fh.tell())
            fh.write(f"{ident} 0 obj\n".encode("ascii"))
            fh.write(body)
            fh.write(b"\nendobj\n")

        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(len(pages)))
        obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
        for i, page in enumerate(pages):
            checkpoint()
            h, w = page.shape[:2]
            width, height = f"{w * 72 / dpi:.8f}".rstrip("0").rstrip("."), f"{h * 72 / dpi:.8f}".rstrip("0").rstrip(".")
            ident = 3 + 3 * i
            obj(ident, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                        f"/Resources << /XObject << /Im {ident + 2} 0 R >> >> "
                        f"/Contents {ident + 1} 0 R >>").encode("ascii"))
            cmd = f"q {width} 0 0 {height} 0 0 cm /Im Do Q".encode("ascii")
            obj(ident + 1, f"<< /Length {len(cmd)} >>\nstream\n".encode("ascii") + cmd + b"\nendstream")
            chroma = int((page.max(axis=2) - page.min(axis=2)).max())
            if chroma <= 24:
                pixels, color_space = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY), "DeviceGray"
            else:
                pixels, color_space = cv2.cvtColor(page, cv2.COLOR_BGR2RGB), "DeviceRGB"
            encoded = zlib.compress(memoryview(np.ascontiguousarray(pixels)), level=9)
            obj(ident + 2, (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
                            f"/ColorSpace /{color_space} /BitsPerComponent 8 /Filter /FlateDecode "
                            f"/Length {len(encoded)} >>\nstream\n").encode("ascii") + encoded + b"\nendstream")
        xref = fh.tell()
        fh.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            fh.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        fh.write((f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
                  f"startxref\n{xref}\n%%EOF\n").encode("ascii"))


def export_composed_pages(
    *,
    pages: Sequence[np.ndarray],
    formats: List[str],
    workspace: Path,
    logger,
    dpi: float = PDF_RESOLUTION,
) -> Dict[str, object]:
    """Write already-composed page rasters (clean reflow chart) to PNG/JPG/PDF.

    Every format encodes the same rasters: no page finalization or splitting,
    no extra header band, no resizing. PNG retains the color pixels; PDF embeds
    lossless 8-bit gray (max chroma <= 24) or RGB pixels. JPG is derived. All files declare
    ``dpi`` so A4 rasters print at A4. Preview images (reduced JPEGs) are
    always written for the review screen. ``workspace`` should be a staged
    folder: on any failure the caller discards it and keeps the previous files.
    """
    normalized = _normalize_formats(formats)  # empty -> png + pdf, like the other export paths
    if not pages:
        raise RuntimeError("no composed pages to export")
    if not np.isfinite(dpi) or dpi <= 0:
        raise ValueError("composed PDF resolution must be finite and positive")
    workspace = Path(workspace)
    image_dir = workspace / "images"
    preview_dir = workspace / "preview"
    image_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    images: List[str] = []
    previews: List[str] = []
    for index, page in enumerate(pages, start=1):
        report_progress("writing", (index - 1) / float(len(pages)))
        if (page is None or page.ndim != 3 or page.shape[2] != 3
                or page.dtype != np.uint8 or min(page.shape[:2]) <= 0):
            raise RuntimeError(f"composed page {index} is not a color raster")
        rgb = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
        if "png" in normalized:
            target = image_dir / f"page_{index:04d}.png"
            rgb.save(target, "PNG", dpi=(dpi, dpi))
            images.append(str(target))
        if "jpg" in normalized:
            target = image_dir / f"page_{index:04d}.jpg"
            rgb.save(target, "JPEG", quality=COMPOSED_JPEG_QUALITY, dpi=(int(dpi), int(dpi)))
            images.append(str(target))
        scale = COMPOSED_PREVIEW_WIDTH / float(rgb.width)
        preview = rgb.resize((COMPOSED_PREVIEW_WIDTH, max(1, int(round(rgb.height * scale)))), Image.LANCZOS)
        preview_path = preview_dir / f"preview_{index:04d}.jpg"
        preview.save(preview_path, "JPEG", quality=88)
        preview.close()
        previews.append(str(preview_path))
        rgb.close()
    pdf_path = None
    if "pdf" in normalized:
        pdf_path = workspace / "sheet_export.pdf"
        _write_composed_pdf(pdf_path, pages, float(dpi))
    logger(f"composed export: {len(pages)} pages -> {', '.join(normalized)}")
    return {
        "images": images,
        "pdf": str(pdf_path) if pdf_path else None,
        "preview_images": previews,
        "page_count": len(pages),
        "formats": normalized,
        "raw_frames": [],
        "page_diagnostics": [],
        "dropped_pages": [],
    }


class ExportVerificationError(RuntimeError):
    """A composed export that may not be published as done (STRATEGY Step 2A "no done without a valid
    placement plan and a non-empty PDF"). ``code`` is the job/task error code; the message starts
    with it (``CODE: detail``) so a background task reports the same code."""

    def __init__(self, code: str, detail: str, facts: Optional[Dict[str, object]] = None):
        self.code = code
        self.detail = detail
        self.facts = dict(facts or {})
        super().__init__(f"{code}: {detail}")


_PDF_PAGE_RE = None


def pdf_page_count(path: Path) -> Optional[int]:
    """Pages of a PDF written by ``export_composed_pages`` (Pillow: uncompressed object table), or None
    when the file is missing, empty or not structurally readable (no header, no %%EOF, no page tree,
    or a page tree whose /Count disagrees with the page objects). No PDF library is required."""
    import re

    global _PDF_PAGE_RE
    if _PDF_PAGE_RE is None:
        _PDF_PAGE_RE = (re.compile(rb"/Type\s*/Page(?![A-Za-z])"), re.compile(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", re.S),
                        re.compile(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", re.S))
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) < 64 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        return None
    pages = len(_PDF_PAGE_RE[0].findall(data))
    counts = [int(m) for m in _PDF_PAGE_RE[1].findall(data)] + [int(m) for m in _PDF_PAGE_RE[2].findall(data)]
    if not counts or max(counts) != pages:
        return None
    return pages


def verify_composed_export(export_result: Dict[str, object], *, plan: Dict[str, object],
                           pages: Sequence[np.ndarray]) -> Dict[str, object]:
    """Check a composed export before it is published as done: the placement plan is valid (no
    conflicts) and has at least one page, every page holds a placement (or, after the last page with
    one, the incomplete-chart appendix), the rendered rasters match
    the plan's page count, and every written format holds exactly those pages (the PDF readable,
    when PDF was requested; each image file non-empty). Raises ExportVerificationError; returns
    the facts checked."""
    plan_pages = list((plan or {}).get("pages") or [])
    validation = (plan or {}).get("validation") or {}
    facts: Dict[str, object] = {"plan_pages": len(plan_pages), "rendered_pages": len(pages)}
    if (plan or {}).get("conflicts") or not validation.get("valid", False):
        raise ExportVerificationError("INVALID_PLACEMENT_PLAN", "the page plan is not valid "
                                      + "; ".join(str(e) for e in (validation.get("errors") or [])[:3]), facts)
    # A page without lines may only be a trailing page of the incomplete-chart appendix (the
    # end-of-chart list of unresolved intervals, reflow_layout.append_trailing_rows).
    with_lines = [i for i, p in enumerate(plan_pages) if p.get("placements")]
    if (not with_lines or any(not p.get("placements") and not (p.get("appendix") and i > with_lines[-1])
                              for i, p in enumerate(plan_pages))):
        raise ExportVerificationError("EMPTY_EXPORT", "the page plan has no pages or an empty page", facts)
    if len(pages) != len(plan_pages):
        raise ExportVerificationError("PAGE_COUNT_MISMATCH",
                                      f"{len(pages)} rendered pages for {len(plan_pages)} planned pages", facts)
    formats = list(export_result.get("formats") or [])
    n = len(plan_pages)
    if "pdf" in formats:
        pdf = export_result.get("pdf")
        if not pdf or not Path(str(pdf)).is_file() or Path(str(pdf)).stat().st_size == 0:
            raise ExportVerificationError("EMPTY_EXPORT", "the PDF was not written", facts)
        count = pdf_page_count(Path(str(pdf)))
        facts["pdf_pages"] = count
        if count is None:
            raise ExportVerificationError("PDF_UNREADABLE", "the PDF could not be read back", facts)
        if count != n:
            raise ExportVerificationError("PAGE_COUNT_MISMATCH", f"the PDF has {count} pages, the plan {n}", facts)
    images = [Path(str(p)) for p in (export_result.get("images") or [])]
    for ext in ("png", "jpg"):
        if ext in formats:
            files = [p for p in images if p.suffix.lower() == f".{ext}"]
            facts[f"{ext}_pages"] = len(files)
            if len(files) != n:
                raise ExportVerificationError("PAGE_COUNT_MISMATCH", f"{len(files)} {ext.upper()} files for {n} planned pages", facts)
            if any(not p.is_file() or p.stat().st_size == 0 for p in files):
                raise ExportVerificationError("EMPTY_EXPORT", f"an empty or missing {ext.upper()} page", facts)
    if not formats or not any(f in formats for f in ("pdf", "png", "jpg")):
        raise ExportVerificationError("EMPTY_EXPORT", "no output format was written", facts)
    facts["verified"] = True
    return facts
