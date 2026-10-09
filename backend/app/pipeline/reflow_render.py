"""Page rasters for the clean reflow chart from a reflow_layout plan.

The same rasters are written to PNG, JPG and PDF (export.export_composed_pages),
so the three formats share page count, order, header and placements.

* Strips are resampled once, isotropically (INTER_AREA when shrinking,
  INTER_CUBIC when enlarging), and their paper level is mapped to page white.
* Page 1 header: title centred at the top, credits (performer, tempo, date,
  memo) right aligned beneath it. The title is editable metadata; it defaults
  to the video title.
* Page numbers at the bottom left from page 2. No footer text.
* Incomplete chart (STRATEGY Step 2A, jump coverage ``incomplete``): the header carries
  ``incomplete`` = {"unresolved": [[s, e], ...], "markers": [{"start", "end", "before_ids"}],
  "locale"}. Page 1 then shows a boxed notice under the title naming every unresolved video
  interval, and each interval whose place in the output order is known gets a one-row boxed
  marker ("[누락 구간 mm:ss–mm:ss]") between the lines before and after it. The layout reserves
  the room (reflow_layout ``markers``). Without ``incomplete`` nothing changes.
  When the list of intervals needs more than ``NOTICE_MAX_LINES`` lines, the page-1 notice is
  compact (the number of intervals and "full list at the end of the chart") and every interval
  is listed in an appendix after the last line (reflow_layout.append_trailing_rows), on the
  last page or on added pages that count in the plan's page count. No interval is left out.
* Source limits: header ``source_clipped`` lists the original ``system_id`` values whose
  visible content is kept. Each affected output line gets a small unboxed dagger notice,
  kept with that line, and page 1 names the number of original source-cut lines. This is
  independent of ``incomplete``; combined notices use the same missing-interval appendix.
* Header faces are selected using actual Unicode cmap coverage, with macOS/Windows CJK
  system-font fallbacks. No additional font package is required.

Ledger frames
-------------
S is the final written system/chunk PNG; R is its cropped, resampled measure strip;
L is a line canvas (a label-bearing unit for whole systems); P is the A4 300 dpi
page raster. All ledger matrices map pixel centres, including resize offsets.
"""

from __future__ import annotations

import os
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_ledger as ledger_api
from app.pipeline.export import (
    _measure_text_width,
    _iter_score_header_font_paths,
    _iter_score_header_title_font_paths,
    _truncate_text_to_width,
)

RENDER_VERSION = "reflow_render-1"
TEXT_COLOR = (20, 20, 20)
MUTED_COLOR = (70, 70, 70)
TITLE_PX = int(round(20 / 72 * rl.DPI))  # 20 pt
CREDIT_PX = int(round(10 / 72 * rl.DPI))  # 10 pt
PAGE_NUMBER_PX = int(round(9 / 72 * rl.DPI))  # 9 pt
NOTICE_PX = int(round(11 / 72 * rl.DPI))  # 11 pt
MARKER_PX = int(round(9 / 72 * rl.DPI))  # 9 pt
NOTICE_PAD_PX = int(round(0.25 * NOTICE_PX))
NOTICE_BORDER_PX = 4
MARKER_BORDER_PX = 3
MARKER_H = int(round(1.9 * MARKER_PX))  # one short boxed row
NOTICE_MAX_LINES = 3  # page-1 notice; a longer interval list moves to the appendix
APPENDIX_ITEM_SEP = "    "


@lru_cache(maxsize=32)
def _font_cmaps(path: str, index: int = 0) -> Tuple[bytes, ...]:
    """Unicode cmap subtables of an sfnt/collection face, without an extra font dependency."""
    try:
        data = Path(path).read_bytes()
        face = struct.unpack_from(">I", data, 12 + 4 * index)[0] if data[:4] == b"ttcf" else 0
        n = struct.unpack_from(">H", data, face + 4)[0]
        for i in range(n):
            tag, _checksum, offset, _length = struct.unpack_from(">4sIII", data, face + 12 + 16 * i)
            if tag != b"cmap":
                continue
            count = struct.unpack_from(">H", data, offset + 2)[0]
            tables = []
            for j in range(count):
                platform, encoding, rel = struct.unpack_from(">HHI", data, offset + 4 + 8 * j)
                if platform == 0 or (platform == 3 and encoding in (1, 10)):
                    start = offset + rel
                    fmt = struct.unpack_from(">H", data, start)[0]
                    if fmt not in (4, 12, 13):
                        continue  # e.g. format 14 (variation sequences) maps no characters
                    length = struct.unpack_from(">I" if fmt in (12, 13) else ">H", data, start + (4 if fmt in (12, 13) else 2))[0]
                    tables.append(data[start:start + length])
            return tuple(tables)
    except (OSError, struct.error):
        pass
    return ()


def _cmap_has_glyph(table: bytes, cp: int) -> bool:
    try:
        return _cmap_lookup(table, cp)
    except struct.error:  # truncated or malformed subtable: treat as not covered
        return False


def _cmap_lookup(table: bytes, cp: int) -> bool:
    fmt = struct.unpack_from(">H", table)[0]
    if fmt in (12, 13):
        for i in range(struct.unpack_from(">I", table, 12)[0]):
            start, end, glyph = struct.unpack_from(">III", table, 16 + 12 * i)
            if start <= cp <= end:
                return (glyph + (cp - start if fmt == 12 else 0)) != 0
    elif fmt == 4 and cp <= 0xffff:
        n = struct.unpack_from(">H", table, 6)[0] // 2
        for i in range(n):
            end = struct.unpack_from(">H", table, 14 + 2 * i)[0]
            start = struct.unpack_from(">H", table, 16 + 2 * n + 2 * i)[0]
            if start <= cp <= end:
                delta = struct.unpack_from(">h", table, 16 + 4 * n + 2 * i)[0]
                pos = 16 + 6 * n + 2 * i
                rel = struct.unpack_from(">H", table, pos)[0]
                glyph = struct.unpack_from(">H", table, pos + rel + 2 * (cp - start))[0] if rel else cp
                return glyph != 0 and ((glyph + delta) & 0xffff) != 0 if rel else ((cp + delta) & 0xffff) != 0
    return False


def font_covers_text(font, text: str) -> bool:
    """Every printable character maps to a nonzero glyph, rather than .notdef (tofu)."""
    tables = _font_cmaps(str(getattr(font, "path", "")), int(getattr(font, "index", 0)))
    return all(any(_cmap_has_glyph(t, cp) for t in tables) for cp in {ord(ch) for ch in text if not ch.isspace()})


def _resolve_cjk_font(size: int, text: str, *, title: bool = False):
    win = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    paths = (_iter_score_header_title_font_paths() if title else []) + _iter_score_header_font_paths() + [
        Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        win / "YuGothR.ttc", win / "YuGothM.ttc", win / "msgothic.ttc",
    ]
    fallback = None
    for path in dict.fromkeys(paths):
        try:
            font = ImageFont.truetype(str(path), max(12, int(size)))
        except OSError:
            continue
        fallback = fallback or font
        if font_covers_text(font, text):
            return font
    return fallback or ImageFont.load_default()


def _resolve_score_header_font(size: int, text: str = "Ag가ドラム譜†"):
    return _resolve_cjk_font(size, text)


def _resolve_score_header_title_font(size: int, text: str = "Ag가ドラム譜"):
    return _resolve_cjk_font(size, text, title=True)


def _fmt_time(sec: float, *, up: bool = False) -> str:
    import math
    t = int(math.ceil(float(sec) - 1e-6)) if up else int(math.floor(float(sec) + 1e-6))
    t = max(0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def time_range(start: float, end: float) -> str:
    return f"{_fmt_time(start)}\u2013{_fmt_time(end, up=True)}"


def _incomplete(header: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    inc = (header or {}).get("incomplete")
    if not isinstance(inc, dict) or not inc.get("unresolved"):
        return None
    return inc


def _locale(header: Optional[Dict[str, Any]], inc: Dict[str, Any]) -> str:
    loc = str(inc.get("locale") or (header or {}).get("locale") or "ko").lower()
    return "en" if loc.startswith("en") else "ko"


def _full_notice(header: Optional[Dict[str, Any]], inc: Dict[str, Any]) -> str:
    spans = ", ".join(time_range(a, b) for a, b in inc["unresolved"])
    if _locale(header, inc) == "en":
        notice = f"Incomplete chart: video {spans} could not be recovered."
    else:
        notice = f"미완성 악보: 영상 {spans} 구간을 복구하지 못했습니다."
    return " ".join(x for x in (notice, source_clipped_notice(header)) if x)


def source_clipped_notice(header: Optional[Dict[str, Any]]) -> Optional[str]:
    clipped = (header or {}).get("source_clipped") or []
    if not clipped:
        return None
    n = len({r["system_id"] for r in clipped})
    if _locale(header, {}) == "en":
        return f"{n} source-cut lines — only the visible part is kept."
    return f"원본 영상에서 잘린 줄 {n}개 — 보이는 부분만 담음"


def _notice_width() -> int:
    return rl.PAGE_W - 2 * rl.MARGIN_X - 2 * NOTICE_PAD_PX - 2 * NOTICE_BORDER_PX


def needs_appendix(header: Optional[Dict[str, Any]]) -> bool:
    """True when the full interval list does not fit the page-1 notice (``NOTICE_MAX_LINES``)."""
    inc = _incomplete(header)
    if inc is None:
        return False
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines = wrap_words(probe, _full_notice(header, inc), font=_resolve_score_header_font(NOTICE_PX),
                       max_width=_notice_width(), max_lines=10 ** 6)
    return len(lines) > NOTICE_MAX_LINES


def incomplete_notice_text(header: Optional[Dict[str, Any]]) -> Optional[str]:
    """Page-1 notice for an incomplete chart (None for a complete one). It names every interval
    when they fit ``NOTICE_MAX_LINES`` lines; otherwise it gives their number and points to the
    appendix at the end of the chart (``appendix_rows``)."""
    inc = _incomplete(header)
    if inc is None:
        return source_clipped_notice(header)
    if not needs_appendix(header):
        return _full_notice(header, inc)
    n = len(inc["unresolved"])
    if _locale(header, inc) == "en":
        notice = f"Incomplete chart: {n} video intervals could not be recovered. The full list is at the end of the chart."
    else:
        notice = f"미완성 악보: 영상 {n}개 구간을 복구하지 못했습니다. 전체 목록은 악보 끝에 있습니다."
    return " ".join(x for x in (notice, source_clipped_notice(header)) if x)


def appendix_rows(header: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows of the end-of-chart list of every unresolved interval (empty when the page-1 notice
    names them all): a title row, then numbered intervals packed into lines of the content width.
    Each row is ``{id, kind, text, h}`` for reflow_layout.append_trailing_rows."""
    inc = _incomplete(header)
    if inc is None or not needs_appendix(header):
        return []
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    font = _resolve_score_header_font(NOTICE_PX)
    bbox = probe.textbbox((0, 0), "Ag가", font=font)
    line_h = bbox[3] - bbox[1]
    spans = list(inc["unresolved"])
    if _locale(header, inc) == "en":
        title = f"Video intervals that could not be recovered ({len(spans)})"
    else:
        title = f"복구하지 못한 영상 구간 ({len(spans)})"
    rows = [{"id": "appendix-title", "kind": "appendix_title", "text": title,
             "h": line_h + int(0.8 * NOTICE_PX), "ranges": []}]
    width = rl.PAGE_W - 2 * rl.MARGIN_X
    cur, cur_idx = "", []
    for i, (a, b) in enumerate(spans):
        item = f"{i + 1}. {time_range(a, b)}"
        cand = f"{cur}{APPENDIX_ITEM_SEP}{item}" if cur else item
        if cur and _measure_text_width(probe, cand, font) > width:
            rows.append({"id": f"appendix-{len(rows)}", "kind": "appendix_row", "text": cur,
                         "h": line_h + int(0.45 * NOTICE_PX), "ranges": cur_idx})
            cur, cur_idx = item, [i]
        else:
            cur, cur_idx = cand, cur_idx + [i]
    if cur:
        rows.append({"id": f"appendix-{len(rows)}", "kind": "appendix_row", "text": cur,
                     "h": line_h + int(0.45 * NOTICE_PX), "ranges": cur_idx})
    return rows


def marker_text(header: Optional[Dict[str, Any]], start: float, end: float) -> str:
    inc = _incomplete(header) or {}
    if _locale(header, inc) == "en":
        return f"[Missing {time_range(start, end)}]"
    return f"[누락 구간 {time_range(start, end)}]"


def layout_markers(header: Optional[Dict[str, Any]],
                   unit_systems: Sequence[Tuple[str, Sequence[str]]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Missing-interval markers for reflow_layout.plan_pages, and the record of every interval.

    ``unit_systems``: the units in output order, each with the systems whose content it holds. A
    marker goes between units k-1 and k when every unit before k holds only systems placed before
    the interval (``before_ids``) and no unit from k on holds one. Otherwise (unknown position, or a
    line that joins content from both sides) the interval is named in the page-1 notice only."""
    markers: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    clipped_ids = {r["system_id"] for r in (header or {}).get("source_clipped", [])}
    for uid, systems in unit_systems:
        clipped = [sid for sid in systems if sid in clipped_ids]
        if clipped:
            text = "† Cut off in source video" if _locale(header, {}) == "en" else "† 원본 영상에서 잘림"
            mark = {"id": f"source-clipped-{uid}", "kind": "source_clipped", "after": uid,
                    "keep_with_previous": True, "h": MARKER_H, "text": text, "system_ids": clipped}
            markers.append(mark)
            records.append(dict(mark, position="placed"))
    inc = _incomplete(header)
    if inc is None:
        return markers, records
    for i, m in enumerate(inc.get("markers") or [{"start": a, "end": b, "before_ids": None} for a, b in inc["unresolved"]]):
        rec = {"id": f"missing-{i + 1}", "start": float(m["start"]), "end": float(m["end"]),
               "text": marker_text(header, m["start"], m["end"])}
        before = m.get("before_ids")
        split = None
        if before is not None:
            before = set(before)
            flags = [[sid in before for sid in systems] for _uid, systems in unit_systems]
            for k in range(len(unit_systems) + 1):
                if all(all(f) for f in flags[:k]) and not any(any(f) for f in flags[k:]):
                    split = k
                    break
        if split is None:
            rec["position"] = "unknown" if before is None else "inside_line"
        else:
            rec["position"] = "placed"
            rec["after"] = unit_systems[split - 1][0] if split > 0 else None
            markers.append({"id": rec["id"], "after": rec["after"], "h": MARKER_H, "text": rec["text"],
                            "start": rec["start"], "end": rec["end"]})
        records.append(rec)
    return markers, records


def attach_incomplete(plan: Dict[str, Any], header: Optional[Dict[str, Any]], records: Sequence[Dict[str, Any]]) -> None:
    """Record the incomplete-chart notice and markers in the plan (nothing for a complete chart)."""
    notice = incomplete_notice_text(header)
    if notice is None:
        return
    plan["header"]["notice"] = notice
    where = {mk["id"]: p["index"] for p in plan.get("pages", []) for mk in p.get("markers", [])}
    source_records = [r for r in records if r.get("kind") == "source_clipped"]
    if source_clipped_notice(header):
        plan["source_limited"] = {"notice": source_clipped_notice(header),
                                  "count": len({r["system_id"] for r in header["source_clipped"]}),
                                  "markers": [dict(r, page=where.get(r["id"])) for r in source_records]}
    if _incomplete(header) is None:
        return
    plan["incomplete"] = {"notice": notice, "unresolved": [list(x) for x in _incomplete(header)["unresolved"]],
                          "markers": [dict(r, page=where.get(r["id"])) for r in records if r.get("kind") != "source_clipped"]}
    rows = appendix_rows(header)
    if rows:
        # every interval is listed on paper: the appendix rows take part in the plan and its page count
        pages = rl.append_trailing_rows(plan, rows)
        listed = sorted({i for r in rows for i in r["ranges"]})
        plan["incomplete"]["appendix"] = {"pages": pages, "rows": len(rows) - 1, "listed": len(listed),
                                          "complete": listed == list(range(len(_incomplete(header)["unresolved"])))}


def header_lines(header: Optional[Dict[str, Any]]) -> Tuple[str, List[str]]:
    h = header or {}
    title = str(h.get("title") or "").strip()
    credits = []
    if str(h.get("performer") or "").strip():
        credits.append(str(h["performer"]).strip())
    bpm = h.get("bpm")
    if bpm not in (None, ""):
        credits.append(f"♩ = {bpm}")
    for key in ("date", "memo"):
        if str(h.get(key) or "").strip():
            credits.append(str(h[key]).strip())
    return title, credits


def _layout_header(header: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Text runs of the page-1 header, positioned relative to the top margin."""
    title, credits = header_lines(header)
    notice = incomplete_notice_text(header)
    if not title and not credits and not notice:
        return []
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    width = rl.PAGE_W - 2 * rl.MARGIN_X
    runs = []
    y = 0
    if title:
        font = _resolve_score_header_title_font(TITLE_PX, title)
        lines = wrap_words(probe, title, font=font, max_width=width, max_lines=2)
        for line in lines:
            bbox = probe.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            runs.append({"text": line, "font": font, "x": rl.MARGIN_X + (width - tw) // 2 - bbox[0], "y": y - bbox[1],
                         "h": bbox[3] - bbox[1], "color": TEXT_COLOR, "kind": "title"})
            y += (bbox[3] - bbox[1]) + int(0.35 * TITLE_PX)
    if notice:
        font = _resolve_score_header_font(NOTICE_PX)
        pad = NOTICE_PAD_PX
        lines = wrap_words(probe, notice, font=font, max_width=_notice_width(), max_lines=NOTICE_MAX_LINES)
        box_top = y
        y += pad + NOTICE_BORDER_PX
        line_h = probe.textbbox((0, 0), "Ag가", font=font)
        line_h = line_h[3] - line_h[1]
        for line in lines:
            bbox = probe.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            runs.append({"text": line, "font": font, "x": rl.MARGIN_X + (width - tw) // 2 - bbox[0], "y": y - bbox[1],
                         "h": line_h, "color": TEXT_COLOR, "kind": "notice"})
            y += line_h + int(0.3 * NOTICE_PX)
        y = y - int(0.3 * NOTICE_PX) + pad + NOTICE_BORDER_PX
        runs.append({"text": "", "font": None, "x": rl.MARGIN_X, "y": box_top, "h": y - box_top, "w": width,
                     "color": TEXT_COLOR, "kind": "notice_box"})
        y += int(0.35 * CREDIT_PX)
    if credits:
        font = _resolve_score_header_font(CREDIT_PX, " ".join(credits))
        y += int(0.2 * CREDIT_PX)
        for line in credits:
            line = _truncate_text_to_width(probe, line, font=font, max_width=int(width * 0.6))
            bbox = probe.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            runs.append({"text": line, "font": font, "x": rl.PAGE_W - rl.MARGIN_X - tw - bbox[0], "y": y - bbox[1],
                         "h": bbox[3] - bbox[1], "color": MUTED_COLOR, "kind": "credit"})
            y += (bbox[3] - bbox[1]) + int(0.45 * CREDIT_PX)
    return runs


def wrap_words(draw: ImageDraw.ImageDraw, text: str, *, font, max_width: int, max_lines: int) -> List[str]:
    """Greedy wrap at spaces (a single word wider than the line is broken by
    characters). Text beyond ``max_lines`` is folded into the last line and
    truncated with an ellipsis."""
    words = " ".join(str(text or "").split()).split(" ")
    if words == [""]:
        return []
    lines: List[str] = []
    cur = ""
    k = 0
    while k < len(words) and len(lines) < max_lines:
        word = words[k]
        cand = f"{cur} {word}".strip()
        if _measure_text_width(draw, cand, font) <= max_width:
            cur = cand
            k += 1
            continue
        if cur:
            lines.append(cur)
            cur = ""
            continue
        # one word wider than the line: break it by characters
        part = ""
        for ch in word:
            if part and _measure_text_width(draw, part + ch, font) > max_width:
                break
            part += ch
        lines.append(part)
        words[k] = word[len(part):]
        if not words[k]:
            k += 1
    if cur and len(lines) < max_lines:
        lines.append(cur)
    rest = " ".join(w for w in words[k:] if w)
    if rest and lines:
        lines[-1] = _truncate_text_to_width(draw, f"{lines[-1]} {rest}", font=font, max_width=max_width, ellipsis=True)
    return lines[:max_lines]


def header_height(header: Optional[Dict[str, Any]]) -> int:
    runs = _layout_header(header)
    if not runs:
        return 0
    return int(max(r["y"] + r["h"] + 0 for r in runs) + 4)


def _to_page_paper(img: np.ndarray) -> np.ndarray:
    """Map the strip's paper level to white (ink ratios kept)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    paper = float(np.percentile(gray, 75))
    out = img if (paper <= 170 or paper >= 254.5) else np.clip(img.astype(np.float32) * (255.0 / paper), 0, 255).astype(np.uint8)
    if paper > 170:
        out = out.copy()
        out[out >= 252] = 255  # rounding residue of the paper level, not ink
    return out


def resize_strip(img: np.ndarray, w: int, h: int) -> np.ndarray:
    if (img.shape[1], img.shape[0]) == (w, h):
        return img.copy()
    interp = cv2.INTER_AREA if w < img.shape[1] else cv2.INTER_CUBIC
    return cv2.resize(img, (w, h), interpolation=interp)


def page_placement_transform(pl: Dict[str, Any], shape: Tuple[int, int]) -> Dict[str, Any]:
    """Exact L -> P resize/placement; ``shape`` is the rendered canvas (height, width)."""
    h, w = shape
    sx, sy = float(pl["w"]) / w, float(pl["h"]) / h
    return {"stage": "line_to_page", "kind": "affine",
            "resample": {"source_size": [w, h], "output_size": [pl["w"], pl["h"]],
                         "interpolation": "area" if pl["w"] < w else "cubic"},
            "matrix": [[sx, 0, float(pl["x"]) + (sx - 1) / 2],
                       [0, sy, float(pl["y"]) + (sy - 1) / 2], [0, 0, 1]]}


def whole_system_ledger_placements(plan: dict, strip_shapes: dict[str, tuple[int, int]], *,
                                   offsets: dict[str, list[float]] | None = None) -> list[dict]:
    """Maps for the whole-system path, without reading pipeline bookkeeping as proof.

    ``strip_shapes`` must describe the actual images passed to render_pages, including
    any label band (L), not the bare source PNG (S). Pass ``units[sid]['strip_offset']``
    from compose_systems, also recorded as ``pl['strip_offset_px']``, in ``offsets``.
    It translates the chosen strip variant S into its label-bearing L canvas. Label
    boxes are separate source origins; their ``label_box_px`` is NOT a music offset.
    The caller must use the producer chain for the chosen strip/uncut variant.
    Call after rr.compose in _compose_whole_systems, or after placement annotation in
    compose_systems with the actual ``images`` shapes and ``units`` offsets.
    """
    out = []
    for page_index, p in enumerate(plan["pages"]):
        for pl in p["placements"]:
            sid = pl["system_id"]
            dx, dy = (offsets or {}).get(sid, [0, 0])
            out.append({"strip_id": sid, "copy_index": 0, "page_index": page_index, "line_id": sid,
                        "stages": [{"stage": "strip_to_line", "kind": "affine",
                                    "matrix": [[1, 0, float(dx)], [0, 1, float(dy)], [0, 0, 1]]},
                                   page_placement_transform(pl, strip_shapes[sid])]})
    return out


def _draw_generated(draw, generated: Optional[list], page_index: int, kind: str, inputs: dict,
                    operation, *, template_operation=None) -> None:
    operation(draw)
    if generated is None:
        return
    white = Image.new("RGB", (rl.PAGE_W, rl.PAGE_H), "white")
    element = white.copy()
    (template_operation or operation)(ImageDraw.Draw(element))
    box = ImageChops.difference(element, white).getbbox()
    if box is not None:
        crop = cv2.cvtColor(np.asarray(element.crop(box)), cv2.COLOR_RGB2BGR)
        generated.append({"kind": kind, "page_index": page_index, "origin": list(box[:2]),
                          "template": ledger_api.pack_crop(crop), "generator": f"render_pages:{RENDER_VERSION}",
                          "inputs": inputs})


def render_pages(plan: Dict[str, Any], strips: Dict[str, np.ndarray], *, header: Optional[Dict[str, Any]] = None,
                 generated: Optional[list] = None) -> List[np.ndarray]:
    """BGR page rasters (A4 at 300 dpi) for ``plan``; ``strips`` maps system id -> strip image.
    An invalid plan (layout conflict, overflow, overlap, missing or duplicated unit)
    is refused with reflow_layout.LayoutConflictError before anything is drawn.
    ``generated`` receives independently drawn, packed P-frame element templates.
    A notice box template includes its enclosed notice runs to match the page crop.
    """
    rl.require_valid_plan(plan)
    runs = _layout_header(header)
    pages = []
    num_font = _resolve_score_header_font(PAGE_NUMBER_PX)
    for page_index, p in enumerate(plan["pages"]):
        page = np.full((rl.PAGE_H, rl.PAGE_W, 3), 255, np.uint8)
        for pl in p["placements"]:
            img = _to_page_paper(strips[pl["system_id"]])
            r = resize_strip(img, pl["w"], pl["h"])
            page[pl["y"]:pl["y"] + pl["h"], pl["x"]:pl["x"] + pl["w"]] = r
        if p.get("header") or p.get("page_number") or p.get("markers") or p.get("appendix"):
            pil = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil)
            if p.get("header"):
                for run in runs:
                    if run["kind"] == "notice_box":
                        y0 = rl.MARGIN_TOP + run["y"]
                        box = [run["x"], y0, run["x"] + run["w"] - 1, y0 + run["h"] - 1]
                        def outline(d):
                            d.rectangle(box, outline=run["color"], width=NOTICE_BORDER_PX)
                        def notice(d):
                            for r in runs:
                                if r["kind"] == "notice":
                                    d.text((r["x"], rl.MARGIN_TOP + r["y"]), r["text"], font=r["font"], fill=r["color"])
                            outline(d)
                        _draw_generated(draw, generated, page_index, "header",
                                        {"kind": run["kind"], "box": box, "text": [r["text"] for r in runs if r["kind"] == "notice"],
                                         "border_px": NOTICE_BORDER_PX}, outline, template_operation=notice)
                        continue
                    xy = (run["x"], rl.MARGIN_TOP + run["y"])
                    _draw_generated(draw, generated, page_index, "header", {"kind": run["kind"], "text": run["text"], "xy": list(xy)},
                                    lambda d: d.text(xy, run["text"], font=run["font"], fill=run["color"]))
            if p.get("markers"):
                mfont = _resolve_score_header_font(MARKER_PX)
                for mk in p["markers"]:
                    source_mark = mk.get("kind") == "source_clipped"
                    text = _truncate_text_to_width(draw, mk["text"], font=mfont, max_width=mk["w"] - 4 * MARKER_BORDER_PX)
                    bbox = draw.textbbox((0, 0), text, font=mfont)
                    xy = (mk["x"] + (0 if source_mark else (mk["w"] - (bbox[2] - bbox[0])) // 2) - bbox[0],
                          mk["y"] + (mk["h"] - (bbox[3] - bbox[1])) // 2 - bbox[1])
                    box = [mk["x"], mk["y"], mk["x"] + mk["w"] - 1, mk["y"] + mk["h"] - 1]
                    def marker(d):
                        if not source_mark:
                            d.rectangle(box, outline=TEXT_COLOR, width=MARKER_BORDER_PX)
                        d.text(xy, text, font=mfont, fill=TEXT_COLOR)
                    _draw_generated(draw, generated, page_index, "source_clipped_notice" if source_mark else "incomplete_marker",
                                    {"text": text, "box": box, "xy": list(xy), "marker": dict(mk)}, marker)
            if p.get("appendix"):
                body_font = _resolve_score_header_font(NOTICE_PX)
                title_font = _resolve_score_header_title_font(NOTICE_PX)
                for row in p["appendix"]:
                    font = title_font if row.get("kind") == "appendix_title" else body_font
                    text = _truncate_text_to_width(draw, row.get("text", ""), font=font, max_width=row["w"])
                    bbox = draw.textbbox((0, 0), "Ag가", font=font)
                    xy = (row["x"], row["y"] - bbox[1])
                    _draw_generated(draw, generated, page_index, "review_notice", {"text": text, "xy": list(xy), "row": dict(row)},
                                    lambda d: d.text(xy, text, font=font, fill=TEXT_COLOR))
            if p.get("page_number"):
                text = str(p["page_number"])
                bbox = draw.textbbox((0, 0), text, font=num_font)
                y = rl.PAGE_H - rl.MARGIN_BOTTOM + (rl.MARGIN_BOTTOM - (bbox[3] - bbox[1])) // 2 - bbox[1]
                xy = (rl.MARGIN_X - bbox[0], y)
                _draw_generated(draw, generated, page_index, "page_number", {"number": p["page_number"], "text": text, "xy": list(xy)},
                                lambda d: d.text(xy, text, font=num_font, fill=MUTED_COLOR))
            page = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        pages.append(page)
    return pages


def compose(strip_records: Sequence[Dict[str, Any]], strips: Dict[str, np.ndarray], *, header: Optional[Dict[str, Any]] = None,
            staff_gap_mm: float = rl.DEFAULT_STAFF_GAP_MM, generated: Optional[list] = None) -> Tuple[Dict[str, Any], List[np.ndarray]]:
    """Plan and render ``strip_records`` (ordered; each has ``system_id``, ``size``, ``staff_gap_px``)."""
    units = [{"id": r["system_id"], "width": int(strips[r["system_id"]].shape[1]), "height": int(strips[r["system_id"]].shape[0]),
              "staff_gap_px": float(r["staff_gap_px"])} for r in strip_records]
    markers, missing = layout_markers(header, [(u["id"], [u["id"]]) for u in units])
    plan = rl.plan_pages(units, header_height_px=header_height(header), staff_gap_mm=staff_gap_mm, markers=markers)
    title, credits = header_lines(header)
    plan["header"] = {"title": title, "credits": credits}
    attach_incomplete(plan, header, missing)
    plan["render_version"] = RENDER_VERSION
    pages = render_pages(plan, strips, header=header, generated=generated)
    return plan, pages
