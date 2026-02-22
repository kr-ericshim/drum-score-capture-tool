from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

import cv2
from PIL import Image

from app.pipeline.sheet_finalize import finalize_sheet_pages
from app.schemas import ExportOptions


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
    export_idx = 1
    for idx, page_path in enumerate(frame_paths, start=1):
        image = cv2.imread(str(page_path))
        if image is None:
            continue
        finalized_pages = finalize_sheet_pages(image)
        if not finalized_pages:
            finalized_pages = [image]
        if len(finalized_pages) > 1:
            logger(f"export page split: input#{idx} -> {len(finalized_pages)} pages")

        for finalized in finalized_pages:
            pdf_images.append(Image.fromarray(cv2.cvtColor(finalized, cv2.COLOR_BGR2RGB)))
            if wants_png:
                out = image_dir / f"page_{export_idx:04d}.png"
                if cv2.imwrite(str(out), finalized):
                    image_paths.append(out)
            if wants_jpg:
                out = image_dir / f"page_{export_idx:04d}.jpg"
                rgb = cv2.cvtColor(finalized, cv2.COLOR_BGR2RGB)
                Image.fromarray(rgb).save(out, quality=95)
                image_paths.append(out)
            export_idx += 1

    if not image_paths and "pdf" not in options.formats and not options.include_raw_frames:
        raise RuntimeError("no images could be exported")

    output["images"] = [str(path) for path in image_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]

    if "pdf" in options.formats:
        pdf_path = workspace / "sheet_export.pdf"
        if not pdf_images:
            raise RuntimeError("no pages available for PDF export")
        pil_images = [img.convert("RGB") for img in pdf_images]
        first, *rest = pil_images
        first.save(pdf_path, save_all=True, append_images=rest, quality=95, optimize=False)
        for image in pil_images:
            image.close()
        output["pdf"] = str(pdf_path)

    logger(f"exported {len(image_paths)} images")
    return output
