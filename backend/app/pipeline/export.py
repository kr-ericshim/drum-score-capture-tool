from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import cv2
from PIL import Image

from app.pipeline.sheet_finalize import finalize_sheet_pages, finalize_sheet_sequence
from app.schemas import ExportOptions

PDF_IMAGE_MAX_EDGE = 2400
PDF_JPEG_QUALITY = 86
PDF_RESOLUTION = 150.0


def export_frames(
    *,
    frame_paths: List[Path],
    options: ExportOptions,
    workspace: Path,
    logger,
    source_frames: Optional[List[Path]] = None,
) -> Dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    output: Dict[str, object] = {"images": [], "pdf": None, "raw_frames": []}

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
    pdf_images: List[Image.Image] = []
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

    finalized_pages = []
    merged_sheet = None
    used_frame_count = 0
    if source_images:
        finalized_pages, merged_sheet, used_frame_count = finalize_sheet_sequence(
            source_images,
            page_fill_mode=page_fill_mode,
        )

    if not finalized_pages:
        for image in source_images:
            fallback_pages = finalize_sheet_pages(image, page_fill_mode=page_fill_mode)
            if fallback_pages:
                finalized_pages.extend(fallback_pages)
            else:
                finalized_pages.append(image)

    if not finalized_pages:
        raise RuntimeError("no pages available for export")

    if merged_sheet is not None and used_frame_count >= 2 and wants_png:
        complete_out = image_dir / "sheet_complete.png"
        if cv2.imwrite(str(complete_out), merged_sheet):
            output["full_sheet"] = str(complete_out)
            logger(f"exported complete stitched sheet: {complete_out.name} (frames={used_frame_count})")

    if len(finalized_pages) > len(source_images) and source_images:
        logger(f"export page split: input#{len(source_images)} -> {len(finalized_pages)} pages")

    export_idx = 1
    for finalized in finalized_pages:
        rgb = None
        if wants_pdf or wants_jpg:
            rgb = cv2.cvtColor(finalized, cv2.COLOR_BGR2RGB)
        if wants_pdf and rgb is not None:
            pdf_images.append(Image.fromarray(rgb))
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
        export_idx += 1

    if not image_paths and not wants_pdf and not options.include_raw_frames:
        raise RuntimeError("no images could be exported")

    output["images"] = [str(path) for path in image_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]

    if wants_pdf:
        pdf_path = workspace / "sheet_export.pdf"
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
    workspace: Path,
    logger,
) -> Dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    output: Dict[str, object] = {"images": [], "pdf": None}
    image_dir = workspace / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    _clear_previous_review_outputs(workspace=workspace, image_dir=image_dir)

    normalized_formats = _normalize_formats(formats)
    wants_png = "png" in normalized_formats
    wants_jpg = "jpg" in normalized_formats
    wants_pdf = "pdf" in normalized_formats

    pages: List = []
    for page_path in page_paths:
        image = cv2.imread(str(page_path))
        if image is None:
            continue
        pages.append(image)

    if not pages:
        raise RuntimeError("no valid pages available for review export")

    image_paths: List[Path] = []
    pdf_images: List[Image.Image] = []

    export_idx = 1
    for page in pages:
        rgb_image = None
        if wants_pdf or wants_jpg:
            rgb_image = cv2.cvtColor(page, cv2.COLOR_BGR2RGB)
        if wants_pdf and rgb_image is not None:
            pdf_images.append(Image.fromarray(rgb_image))
        if wants_png:
            png_out = image_dir / f"page_{export_idx:04d}.png"
            if cv2.imwrite(str(png_out), page):
                image_paths.append(png_out)
        if wants_jpg:
            jpg_out = image_dir / f"page_{export_idx:04d}.jpg"
            if rgb_image is None:
                rgb_image = cv2.cvtColor(page, cv2.COLOR_BGR2RGB)
            Image.fromarray(rgb_image).save(jpg_out, quality=95)
            image_paths.append(jpg_out)
        export_idx += 1

    if not image_paths and not wants_pdf:
        raise RuntimeError("review export produced no image output")

    output["images"] = [str(path) for path in image_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]

    if wants_pdf:
        pdf_path = workspace / "sheet_export.pdf"
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

    logger(f"review export saved: {len(pages)} pages kept")
    return output


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


def _clear_previous_review_outputs(*, workspace: Path, image_dir: Path) -> None:
    for pattern in ("*.png", "*.jpg", "*.jpeg"):
        for image_path in image_dir.glob(pattern):
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


def _prepare_pdf_image(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    width, height = rgb.size
    long_edge = max(width, height)
    if long_edge > PDF_IMAGE_MAX_EDGE and long_edge > 0:
        scale = PDF_IMAGE_MAX_EDGE / float(long_edge)
        target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        rgb = rgb.resize(target, resampling)

    # Re-encode once to JPEG in-memory so PIL PDF writer can use compressed streams reliably.
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=PDF_JPEG_QUALITY, optimize=True)
    buf.seek(0)
    compressed = Image.open(buf).convert("RGB")
    compressed.load()
    buf.close()
    rgb.close()
    return compressed
