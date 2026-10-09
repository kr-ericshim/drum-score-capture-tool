"""Independent delivered-page verifier, LEDGER_2D_INTERFACE sections 12.5/12.6.

No production renderer is imported. Coordinates are pixel centres, page indices
are zero based, and arrays use OpenCV BGR order. ``pages=`` is a diagnostic/test
transport: its certificate explicitly does not certify a PDF container.
Stage B must forward Stage A features as ``features: {strip_id: [feature, ...]}``
(or on each instance). Missing features are an incomplete verification, not clean.
"""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from pathlib import Path
import re
import time
import zlib

import cv2
import numpy as np
from PIL import PdfParser

from . import reflow_verify_common as common

# Frozen synthetic calibration, never estimated from the dev videos.
# RGB->gray conversion roundoff is covered by the prescribed +2 margin.
PROFILE_EPSILON = {"lossless-gray": 2, "lossless-rgb": 2}
CALIBRATION_BENIGN_MAX = {"lossless-gray": 0, "lossless-rgb": 0}
PAGE_SIZE = (2480, 3508)
A4_POINTS = (210 * 72 / 25.4, 297 * 72 / 25.4)
SEARCH_PX = 3
ACCEPTED_OFFSET_PX = 1
SURVIVAL_CONTRAST = 32
STRONG_SURVIVAL_FRACTION = .5
_METHOD = {"area": cv2.INTER_AREA, "cubic": cv2.INTER_CUBIC}


def _image(value):
    image = value if isinstance(value, np.ndarray) else cv2.imread(str(value), cv2.IMREAD_UNCHANGED)
    if image is None or image.dtype != np.uint8 or image.ndim not in (2, 3):
        raise ValueError("strip must be a decoded 8-bit gray/BGR PNG")
    if image.ndim == 3 and image.shape[2] != 3:
        raise ValueError("alpha/other image channels are unsupported")
    return image


def _bgr(image):
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image


def _paper_parameters(image):
    paper = float(np.percentile(common.gray(image), 75))
    return paper, 255. / paper if 170 < paper < 254.5 else 1.


def _paper(image, parameters=None):
    """Independent replay of the approved paper mapping, before each resize."""
    level, factor = parameters or _paper_parameters(image)
    out = np.clip(image.astype(np.float32) * factor, 0, 255).astype(np.uint8) if factor != 1 else image.copy()
    if level > 170:
        out[out >= 252] = 255
    return out


def _integer(values):
    a = np.asarray(values, dtype=float)
    rounded = np.rint(a)
    if not np.isfinite(a).all() or np.any(np.abs(a - rounded) > 1e-7):
        raise ValueError("placement and crop boundaries must be integral")
    return rounded.astype(int).tolist()


def _translation(matrix):
    m = np.asarray(matrix, dtype=float)
    if m.shape != (3, 3) or not np.allclose(m[:, :2], [[1, 0], [0, 1], [0, 0]], atol=1e-7, rtol=0) or m[2, 2] != 1:
        raise ValueError("piece placement must be an integer translation")
    return _integer(m[:2, 2])


def _piece_geometry(piece):
    """Integer cut/placement, including a declared one-column scaffold replica."""
    repeat = int(piece.get("column_repeat", 1))
    if repeat == 1:
        dx, dy = _translation(piece["matrix"])
        return dx, dy, repeat
    a, b, c, d = _integer(piece["src_bbox"])
    m = np.asarray(piece["matrix"], dtype=float)
    if repeat < 1 or c - a != 1 or m.shape != (3, 3) or not np.allclose(m[:, :2], [[repeat, 0], [0, 1], [0, 0]], atol=1e-7, rtol=0) or m[2, 2] != 1:
        raise ValueError("invalid declared column replica")
    x, dy = _integer([repeat * a + m[0, 2] - (repeat - 1) / 2, m[1, 2]])
    return x - a, dy, repeat


def _spec(spec):
    sw, sh = _integer(spec["source_size"])
    ow, oh = _integer(spec["output_size"])
    if min(sw, sh, ow, oh) <= 0 or spec["interpolation"] not in _METHOD:
        raise ValueError("invalid resize size/interpolation")
    x, y = _integer(spec.get("crop_origin", [0, 0]))
    return sw, sh, ow, oh, x, y


def _resize(image, spec, *, paper=False):
    sw, sh, ow, oh, x, y = _spec(spec)
    if x < 0 or y < 0 or x + sw > image.shape[1] or y + sh > image.shape[0]:
        raise ValueError("resize crop outside source")
    source = image[y:y + sh, x:x + sw]
    source = _paper(source) if paper else source
    return cv2.resize(source, (ow, oh), interpolation=_METHOD[spec["interpolation"]])


def _check_resize_matrix(matrix, spec, *, page=False):
    sw, sh, ow, oh, x, y = _spec(spec)
    sx, sy = ow / sw, oh / sh
    m = np.asarray(matrix, dtype=float)
    target = np.array([[sx, 0, (sx - 1) / 2 - sx * x], [0, sy, (sy - 1) / 2 - sy * y], [0, 0, 1]])
    if page:
        dx, dy = _integer(m[:2, 2] - target[:2, 2])
        target[:2, 2] += [dx, dy]
    else:
        dx, dy = 0, 0
    if m.shape != (3, 3) or not np.allclose(m, target, atol=1e-7, rtol=0):
        raise ValueError("resize metadata and pixel-centre matrix disagree")
    return dx, dy


def _stages(instance):
    stages = instance.get("transform", instance.get("stages"))
    if isinstance(stages, dict):
        stages = stages.get("stages")
    if not stages or len(stages) != 2 or stages[0].get("stage") != "strip_to_line" or stages[1].get("stage") != "line_to_page":
        raise ValueError("expected strip_to_line and line_to_page recorded stages")
    return stages


def _template(record):
    if isinstance(record, np.ndarray):
        return _bgr(_image(record))
    raw = base64.b64decode(record["png"], validate=True)
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or common.pixels_sha256(image) != record["sha256"]:
        raise ValueError("generated template digest mismatch")
    return _bgr(_image(image))


def _paste(canvas, image, x, y, *, minimum=False):
    h, w = image.shape[:2]
    if x < 0 or y < 0 or x + w > canvas.shape[1] or y + h > canvas.shape[0]:
        raise ValueError("recorded placement clips content")
    if minimum:
        np.minimum(canvas[y:y + h, x:x + w], image, out=canvas[y:y + h, x:x + w])
    else:
        canvas[y:y + h, x:x + w] = image


def _feature_list(cert, sid, records):
    if sid in cert.get("features", {}):
        return cert["features"][sid]
    embedded = [r["features"] for r in records if "features" in r]
    if embedded:
        return list({f["id"]: f for fs in embedded for f in fs}.values())
    return None


def _check_feature_geometry(cert, images):
    """A forwarded mask cannot silently remove or reclassify a strip obligation.

    A qualifies support; C independently checks its image-derived geometry with
    the same shared primitive. Qualification and observation integrity stay A's
    responsibility. All A features (including unsupported ones) must be forwarded.
    """
    records_by = defaultdict(list)
    for record in cert["instances"]:
        records_by[record["strip_id"]].append(record)
    for sid, records in records_by.items():
        features = _feature_list(cert, sid, records)
        if features is None:
            continue  # explicitly incomplete in _render, never clean
        if len({f["id"] for f in features}) != len(features):
            raise ValueError("duplicate feature ids for strip " + sid)
        for feature in features:
            a, b, c, d = feature["bbox"]
            if feature["kind"] not in ("strong", "weak") or c - a > common.TILE or d - b > common.TILE:
                raise ValueError("invalid local feature tile for strip " + sid)
        contrast = common.contrast_map(images[sid])
        independently_built = common.strip_features(contrast)
        for kind in ("strong", "weak"):
            expected = common.paint(contrast.shape, [f for f in independently_built if f["kind"] == kind])
            forwarded = common.paint(contrast.shape, [f for f in features if f["kind"] == kind])
            if not np.array_equal(expected, forwarded):
                raise ValueError("forwarded feature geometry differs from committed strip: " + sid + " / " + kind)


def _render(cert_b, images, generated, page_count, *, obligations=False):
    width, height = _integer(cert_b.get("page_px", cert_b.get("plan_records", {}).get("page_px", PAGE_SIZE)))
    if min(width, height, page_count) <= 0:
        raise ValueError("invalid page size/count")
    pages = [np.full((height, width, 3), 255, np.uint8) for _ in range(page_count)]
    centres = [np.zeros((height, width), np.uint8) for _ in range(page_count)] if obligations else []
    by_line, cache, native_masks, missing_features = defaultdict(list), {}, {}, set()
    for rec in cert_b["instances"]:
        by_line[(int(rec["page_index"]), rec["line_id"])].append(rec)
    lines = []
    for (pi, lid), records in by_line.items():
        if not 0 <= pi < page_count:
            raise ValueError("instance references an absent page")
        page_stage = _stages(records[0])[1]
        # Whole-system affine maps without a resample still need the line canvas.
        if "resample" not in page_stage:
            raise ValueError("line_to_page needs an explicit recorded resize")
        sw, sh, ow, oh, cx, cy = _spec(page_stage["resample"])
        if cx or cy:
            raise ValueError("line_to_page may not crop the line canvas")
        px, py = _check_resize_matrix(page_stage["matrix"], page_stage["resample"], page=True)
        line = np.full((sh, sw, 3), 255, np.uint8)
        mask_line = np.zeros((sh, sw), np.uint8) if obligations else None
        replay = []
        for rec in records:
            sid = rec["strip_id"]
            source = _bgr(images[sid])
            stage, pg = _stages(rec)
            if pg != page_stage:
                raise ValueError("one line has inconsistent page transforms")
            features = _feature_list(cert_b, sid, records)
            if obligations and sid not in native_masks:
                if features is None:
                    missing_features.add(sid)
                    # Conservative diagnostic comparison; this is never a clean certificate.
                    native_masks[sid] = (common.contrast_map(source) >= common.C_WEAK).astype(np.uint8) * 255
                else:
                    c = common.contrast_map(source)
                    native_masks[sid] = common.obligation_centres(features, c.shape, c).astype(np.uint8) * 255
            if stage["kind"] == "piecewise":
                spec = stage["pre_resample"]
                _check_resize_matrix(stage["pre_matrix"], spec)
                key = (sid, common.json_sha256(spec))
                if key not in cache:
                    cache[key] = (_resize(source, spec, paper=True),
                                  _resize(native_masks[sid], spec) if obligations else None)
                elif obligations and cache[key][1] is None:
                    cache[key] = (cache[key][0], _resize(native_masks[sid], spec))
                resized, resized_mask = cache[key]
                pieces = stage["pieces"]
            elif stage["kind"] == "affine":
                resized, resized_mask, spec = source, native_masks.get(sid), None
                pieces = [{"src_bbox": [0, 0, source.shape[1], source.shape[0]], "matrix": stage["matrix"]}]
            else:
                raise ValueError("unknown strip_to_line transform")
            for piece in pieces:
                a, b, c, d = _integer(piece["src_bbox"])
                dx, dy, repeat = _piece_geometry(piece)
                if not (0 <= a < c <= resized.shape[1] and 0 <= b < d <= resized.shape[0]):
                    raise ValueError("piece domain outside recorded resize")
                piece_image = resized[b:d, a:c]
                _paste(line, np.repeat(piece_image, repeat, axis=1) if repeat != 1 else piece_image, a + dx, b + dy)
                if obligations:
                    piece_mask = resized_mask[b:d, a:c]
                    _paste(mask_line, np.repeat(piece_mask, repeat, axis=1) if repeat != 1 else piece_mask, a + dx, b + dy)
            replay.append({"record": rec, "spec": spec, "pieces": pieces, "resized": resized, "features": features})
        # Line-space generated elements participate in the final resize; page-space
        # templates are overlaid afterwards, exactly at their committed footprint.
        for gen in generated:
            if gen.get("line_id") == lid and gen.get("page_index") == pi and "template_L" in gen:
                a, b, _c, _d = _integer(gen["box_L"])
                _paste(line, _template(gen["template_L"]), a, b, minimum=True)
            elif gen.get("line_id") == lid and gen.get("page_index") == pi and gen.get("kind") == "staff_scaffold":
                # Rebuild the scaffold on the line BEFORE the second resize.
                # Page-template overlay alone would miss its kernel contribution
                # just outside the generated footprint at fractional page scales.
                a, b, c, d = _integer(gen["box_L"])
                donor_key = (gen["strip_id"], common.json_sha256(gen["source_resample"]))
                if donor_key not in cache:
                    cache[donor_key] = (_resize(_bgr(images[gen["strip_id"]]), gen["source_resample"], paper=True), None)
                donor = cache[donor_key][0]
                column = int(gen["source_column_R"])
                sy = int(gen["source_y_L"])
                if not 0 <= column < donor.shape[1]:
                    raise ValueError("scaffold source column outside strip")
                scaffold = np.full((d - b, c - a, 3), 255, np.uint8)
                y0, y1 = max(b, sy), min(d, sy + donor.shape[0])
                if y0 < y1:
                    scaffold[y0 - b:y1 - b] = donor[y0 - sy:y1 - sy, column:column + 1]
                _paste(line, scaffold, a, b)
        parameters = _paper_parameters(line)
        rendered = _resize(line, page_stage["resample"], paper=True)
        _paste(pages[pi], rendered, px, py)
        if obligations:
            mapped = _resize(mask_line, page_stage["resample"])
            _paste(centres[pi], (mapped > 0).astype(np.uint8), px, py)
        lines.append({"page_index": pi, "line_id": lid, "origin": [px, py], "size": [ow, oh],
                      "image": rendered, "line": line, "parameters": parameters,
                      "page_spec": page_stage["resample"], "replay": replay})
    for gen in generated:
        pi = int(gen["page_index"])
        if not 0 <= pi < page_count or not gen.get("generator") or not gen.get("inputs"):
            raise ValueError("generated origin has no page/generator/inputs")
        image = _template(gen["template"])
        x, y = _integer(gen["origin"])
        _paste(pages[pi], image, x, y, minimum=True)
        if obligations:
            # Generated weak ink also has a local preservation obligation.
            c = common.contrast_map(image)
            centres[pi][y:y + c.shape[0], x:x + c.shape[1]] |= (c >= common.C_WEAK).astype(np.uint8)
    return pages, centres, lines, sorted(missing_features)


def render_expected(cert_b: dict, strip_pngs: dict, generated: list, page_count: int) -> list[np.ndarray]:
    """Replay committed strips/stages/templates without importing a production renderer."""
    images = {sid: _image(value) for sid, value in strip_pngs.items()}
    return _render(cert_b, images, generated, page_count)[0]


def decode_lossless_pdf(pdf_path, *, profile):
    """Decode the narrow A4 single-image contract, using Pillow only as a PDF parser.

    Flate bytes are decoded here, bounded by the declared 300-dpi raster size.
    No rasterizer, JPEG decode, auxiliary drawing, mask, crop or page modifier.
    """
    if profile not in PROFILE_EPSILON and profile != "lossless":
        raise ValueError("unknown frozen render profile")
    pdf = PdfParser.PdfParser(filename=str(pdf_path))
    output = []
    try:
        if pdf.trailer_dict.get(b"Encrypt") or not pdf.pages:
            raise ValueError("encrypted/empty PDF")
        def resolve(value):
            return pdf.read_indirect(value) if isinstance(value, PdfParser.IndirectReference) else value
        for ref in pdf.pages:
            p = resolve(ref)
            visited, inherited = set(), {}
            node = p
            while True:
                for key in (b"Rotate", b"Annots", b"CropBox", b"BleedBox", b"TrimBox", b"ArtBox", b"UserUnit", b"Group", b"AA"):
                    if key in node:
                        raise ValueError("unsupported page/tree modifier " + key.decode())
                for key in (b"MediaBox", b"Resources"):
                    if key in node and key not in inherited:
                        inherited[key] = node[key]
                parent = node.get(b"Parent")
                if parent is None:
                    break
                if parent in visited:
                    raise ValueError("cyclic PDF page tree")
                visited.add(parent)
                node = resolve(parent)
            mb = list(map(float, resolve(inherited[b"MediaBox"])))
            if len(mb) != 4 or mb[:2] != [0., 0.] or not np.allclose(mb[2:], A4_POINTS, atol=.15, rtol=0):
                raise ValueError("page is not A4 portrait")
            resources = resolve(inherited[b"Resources"])
            if set(resources) - {b"XObject", b"ProcSet"}:
                raise ValueError("unsupported page resources")
            xobjects = resolve(resources[b"XObject"])
            if len(xobjects) != 1:
                raise ValueError("expected one image XObject per page")
            name, image_ref = next(iter(xobjects.items()))
            stream = resolve(image_ref)
            d = stream.dictionary
            if d.get(b"Subtype") != b"Image" or d.get(b"Filter") != b"FlateDecode" or d.get(b"BitsPerComponent") != 8:
                raise ValueError("page image must be 8-bit FlateDecode")
            if d.get(b"ColorSpace") not in (b"DeviceGray", b"DeviceRGB"):
                raise ValueError("unsupported image color space")
            if any(k in d for k in (b"SMask", b"Mask", b"Decode", b"DecodeParms", b"Alternates", b"ImageMask")):
                raise ValueError("unsupported image modifiers")
            color = "lossless-gray" if d[b"ColorSpace"] == b"DeviceGray" else "lossless-rgb"
            if profile != "lossless" and color != profile:
                raise ValueError("wrong render profile: " + color)
            w, h = int(d[b"Width"]), int(d[b"Height"])
            if (w, h) != PAGE_SIZE:
                raise ValueError("expected the 2480x3508 300-dpi page raster")
            content = resolve(p[b"Contents"])
            if not isinstance(content, PdfParser.PdfStream):
                raise ValueError("contents must be one command stream")
            if content.dictionary.get(b"Filter") not in (None, b"FlateDecode"):
                raise ValueError("unsupported content encoding")
            if content.dictionary.get(b"DecodeParms"):
                raise ValueError("unsupported content predictor")
            commands = content.decode(max_length=4096)
            pattern = rb"\s*q\s+([\d.]+)\s+0\s+0\s+([\d.]+)\s+0\s+0\s+cm\s+" + re.escape(bytes(name)) + rb"\s+Do\s+Q\s*"
            match = re.fullmatch(pattern, commands)
            if not match or not np.allclose([float(match[1]), float(match[2])], mb[2:], atol=1e-4, rtol=0):
                raise ValueError("contents are not one unmodified full-page image")
            count = w * h * (1 if color == "lossless-gray" else 3)
            decoder = zlib.decompressobj()
            raw = decoder.decompress(stream.buf, count + 1)
            if len(raw) != count or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError("Flate raster length/end mismatch")
            image = np.frombuffer(raw, np.uint8).reshape((h, w) if color == "lossless-gray" else (h, w, 3)).copy()
            if image.ndim == 3:
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            output.append(image)
    finally:
        pdf.close()
    return output


def _register(expected, delivered, x, y):
    """Exactly one integer alignment decision per line, including weak ink."""
    h, w = expected.shape
    patch = delivered[y:y + h, x:x + w]
    if np.array_equal(expected, patch):
        return 0, 0, 0.
    padded = cv2.copyMakeBorder(delivered, SEARCH_PX, SEARCH_PX, SEARCH_PX, SEARCH_PX, cv2.BORDER_CONSTANT, value=0)
    search = padded[y:y + h + 2 * SEARCH_PX, x:x + w + 2 * SEARCH_PX]
    scores = cv2.matchTemplate(search.astype(np.float32), expected.astype(np.float32), cv2.TM_SQDIFF)
    # MatchTemplate can accumulate roundoff at near-exact matches. Resolve its
    # few best candidates by exact integer SSD, prefer the least movement on ties.
    candidates = []
    for iy, ix in zip(*np.nonzero(scores <= scores.min() + 64)):
        diff = search[iy:iy + h, ix:ix + w].astype(np.int16) - expected.astype(np.int16)
        score = float(np.sum(diff.astype(np.int32) ** 2, dtype=np.int64))
        dx, dy = int(ix) - SEARCH_PX, int(iy) - SEARCH_PX
        candidates.append((score, dx * dx + dy * dy, abs(dy), abs(dx), dx, dy))
    best = min(candidates)
    return best[-2], best[-1], best[0] / max(1, w * h)


def _local_resize(image, spec, box, *, replacement=None, paper_parameters=None):
    """Only output ``box`` of a resize, with its full-canvas phase and kernel.

    Area uses separable fractional bin integrals; cubic uses OpenCV's separable
    A=-.75 kernel, half-pixel centres and border replication. No per-pixel loops.
    This helper is for feature survival, not for the expected page raster.
    """
    sw, sh, ow, oh, cx, cy = _spec(spec)
    source = image[cy:cy + sh, cx:cx + sw]
    a, b, c, d = box
    if a >= c or b >= d:
        return np.empty((0, 0), np.uint8)
    if (sw, sh) == (ow, oh):
        patch = source[b:d, a:c].copy()
        if replacement is not None:
            (ra, rb, rc, rd), pixels = replacement
            qa, qb, qc, qd = max(a + cx, ra), max(b + cy, rb), min(c + cx, rc), min(d + cy, rd)
            if qa < qc and qb < qd:
                patch[qb - cy - b:qd - cy - b, qa - cx - a:qc - cx - a] = pixels[qb - rb:qd - rb, qa - ra:qc - ra]
        return _paper(patch, paper_parameters) if paper_parameters is not None else patch
    def weights(start, stop, native, output):
        scale = native / output
        pos = np.arange(start, stop, dtype=np.float64)
        if spec["interpolation"] == "area":
            # AREA enlargement in OpenCV is nearest-style fractional coverage;
            # the general overlap expression has the same pixel-bin semantics.
            left, right = pos * scale, (pos + 1) * scale
            lo, hi = max(0, int(np.floor(left.min()))), min(native, int(np.ceil(right.max())))
            index = np.arange(lo, hi, dtype=np.float64)
            weight = np.maximum(0, np.minimum(right[:, None], index + 1) - np.maximum(left[:, None], index)) / scale
            return np.arange(lo, hi), weight
        centre = (pos + .5) * scale - .5
        base = np.floor(centre).astype(int)
        index = base[:, None] + np.arange(-1, 3)
        dist = np.abs(centre[:, None] - index)
        weight = np.where(dist <= 1, 1.25 * dist**3 - 2.25 * dist**2 + 1,
                          np.where(dist < 2, -.75 * dist**3 + 3.75 * dist**2 - 6 * dist + 3, 0))
        unique, inverse = np.unique(np.clip(index, 0, native - 1), return_inverse=True)
        matrix = np.zeros((len(pos), len(unique)), np.float64)
        np.add.at(matrix, (np.repeat(np.arange(len(pos)), 4), inverse.ravel()), weight.ravel())
        return unique, matrix
    xs, wx = weights(a, c, sw, ow)
    ys, wy = weights(b, d, sh, oh)
    patch = source[np.ix_(ys, xs)].copy()
    if replacement is not None:
        (ra, rb, rc, rd), pixels = replacement
        xi = np.flatnonzero((xs + cx >= ra) & (xs + cx < rc))
        yi = np.flatnonzero((ys + cy >= rb) & (ys + cy < rd))
        if len(xi) and len(yi):
            patch[np.ix_(yi, xi)] = pixels[np.ix_(ys[yi] + cy - rb, xs[xi] + cx - ra)]
    if paper_parameters is not None:
        patch = _paper(patch, paper_parameters)
    patch = patch.astype(np.float64)
    return np.clip(np.rint(wy @ patch @ wx.T), 0, 255).astype(np.uint8)


def _support_box(box, spec, parameters=None):
    sw, sh, ow, oh, x, y = parameters or _spec(spec)
    a, b, c, d = box
    halo = 2 if spec["interpolation"] == "cubic" else 0
    return [max(0, int(np.floor((a - x - halo) * ow / sw))),
            max(0, int(np.floor((b - y - halo) * oh / sh))),
            min(ow, int(np.ceil((c - x + halo) * ow / sw))),
            min(oh, int(np.ceil((d - y + halo) * oh / sh)))]


def _survival(cert_b, images, lines):
    findings, tested, at_risk = [], 0, 0
    seen = set()
    source_cache, prepared_cache, feature_cache, support_cache = {}, {}, {}, {}
    for line in lines:
        baseline = common.gray(line["line"])
        page_parameters = _spec(line["page_spec"])
        for replay in line["replay"]:
            rec, spec = replay["record"], replay["spec"]
            sid = rec["strip_id"]
            if sid not in source_cache:
                source_cache[sid] = (common.gray(_bgr(images[sid])), common.contrast_map(images[sid]))
            source, contrast = source_cache[sid]
            piece_key = common.json_sha256(replay["pieces"])
            spec_key = common.json_sha256(spec)
            spec_parameters = _spec(spec) if spec else None
            piece_geometry = [(piece["src_bbox"], _piece_geometry(piece)) for piece in replay["pieces"]]
            for feature in replay["features"] or []:
                key = (sid, feature["id"], line["page_index"], line["line_id"], rec.get("copy_index", 0), piece_key)
                if key in seen:
                    continue
                seen.add(key)
                feature_key = (sid, feature["id"])
                if feature_key not in feature_cache:
                    mask = feature["mask"] if isinstance(feature["mask"], np.ndarray) else common.unpack_mask(feature["mask"])
                    a, b, c, d = _integer(feature["bbox"])
                    if mask.shape != (d - b, c - a) or not (0 <= a < c <= source.shape[1] and 0 <= b < d <= source.shape[0]) or not mask.any():
                        raise ValueError("invalid Stage A feature footprint")
                    maximum = int(contrast[b:d, a:c][mask].max())
                    feature_cache[feature_key] = (mask, a, b, c, d, maximum, int(mask.sum()))
                mask, a, b, c, d, maximum, ink_count = feature_cache[feature_key]
                support_key = (sid, feature["id"], spec_key)
                if support_key not in support_cache:
                    support_cache[support_key] = _support_box([a, b, c, d], spec, spec_parameters) if spec else [a, b, c, d]
                outbox = support_cache[support_key]
                intersections = []
                for (pa, pb, pc, pd), geometry in piece_geometry:
                    qa, qb, qc, qd = max(outbox[0], pa), max(outbox[1], pb), min(outbox[2], pc), min(outbox[3], pd)
                    if qa < qc and qb < qd:
                        intersections.append(([qa, qb, qc, qd], geometry))
                if not intersections:
                    continue  # B decides authorised removal, never C.
                tested += 1
                scale = (spec["output_size"][0] / spec["source_size"][0] if spec else 1) * line["page_spec"]["output_size"][0] / line["page_spec"]["source_size"][0]
                if feature["kind"] != "weak" and ink_count * scale * scale > 16 and min(c - a, d - b) * scale >= 2:
                    continue
                at_risk += 1
                # Small phase-correct resize with and without this feature; keep
                # the full strip/line paper estimates fixed at the approved render.
                preparation_key = (sid, spec_key)
                if preparation_key not in prepared_cache:
                    parameters = _paper_parameters(_bgr(images[sid])) if spec is None else _paper_parameters(
                        _bgr(images[sid])[_spec(spec)[5]:_spec(spec)[5] + _spec(spec)[1],
                                          _spec(spec)[4]:_spec(spec)[4] + _spec(spec)[0]])
                    prepared_cache[preparation_key] = common.gray(_paper(_bgr(images[sid]), parameters))
                prepared_gray = prepared_cache[preparation_key]
                altered_tile = prepared_gray[b:d, a:c].copy()
                altered_tile[mask] = 255
                if spec:
                    with_tile = _local_resize(prepared_gray, spec, outbox)
                    without_tile = _local_resize(prepared_gray, spec, outbox, replacement=([a, b, c, d], altered_tile))
                else:
                    with_tile = prepared_gray[b:d, a:c]
                    without_tile = altered_tile
                contribution = np.maximum(without_tile.astype(np.int16) - with_tile.astype(np.int16), 0)
                peak, boxes = 0, []
                for box, (dx, dy, repeat) in intersections:
                    qa, qb, qc, qd = box
                    local = contribution[qb - outbox[1]:qd - outbox[1], qa - outbox[0]:qc - outbox[0]]
                    if repeat != 1:
                        local = np.repeat(local, repeat, axis=1)
                    if not local.any():
                        continue
                    la, lb, lc, ld = qa + dx, qb + dy, qa + dx + (qc - qa) * repeat, qd + dy
                    pagebox = _support_box([la, lb, lc, ld], line["page_spec"], page_parameters)
                    # A local line crop large enough to include the final kernel,
                    # expressed on the original canvas to retain its exact phase.
                    # Sparse differences reuse the baseline full line; only at-risk
                    # tiles need the counterfactual resize.
                    changed_tile = np.clip(baseline[lb:ld, la:lc].astype(np.int16) + local, 0, 255).astype(np.uint8)
                    with_page = _local_resize(baseline, line["page_spec"], pagebox, paper_parameters=line["parameters"])
                    without_page = _local_resize(baseline, line["page_spec"], pagebox,
                        replacement=([la, lb, lc, ld], changed_tile), paper_parameters=line["parameters"])
                    peak = max(peak, int(np.maximum(without_page.astype(np.int16) - with_page.astype(np.int16), 0).max(initial=0)))
                    boxes.append(pagebox)
                if peak < SURVIVAL_CONTRAST or (feature["kind"] == "strong" and peak < maximum * STRONG_SURVIVAL_FRACTION):
                    px, py = line["origin"]
                    if boxes:
                        bbox = [min(q[0] for q in boxes) + px, min(q[1] for q in boxes) + py,
                                max(q[2] for q in boxes) + px, max(q[3] for q in boxes) + py]
                    else:
                        q, (dx, dy, repeat) = intersections[0]
                        q = _support_box([q[0] + dx, q[1] + dy, q[0] + dx + (q[2] - q[0]) * repeat, q[3] + dy], line["page_spec"], page_parameters)
                        bbox = [q[0] + px, q[1] + py, q[2] + px, q[3] + py]
                    findings.append(common.finding("C", "review_required", "OUTPUT_FIDELITY", page_index=line["page_index"],
                        bbox=bbox, feature_ids=[feature["id"]], strip_id=sid,
                        detail={"source_max_contrast": maximum, "contribution_peak": peak, "line_id": line["line_id"]}))
    return findings, tested, at_risk


def staff_continuity(expected, delivered, *, page_index, line_id, origin):
    """Expected source paper excuses existing gaps, never introduced page seams.

    Find long staff row runs on E, choose the strongest delivered row within one
    pixel (the original continuity metric), and check each expected ink column.
    """
    h, w = expected.shape
    horizontal = cv2.morphologyEx((expected >= common.C_STRONG).astype(np.uint8), cv2.MORPH_OPEN,
                                 np.ones((1, max(16, w // 4)), np.uint8))
    rows = np.flatnonzero(horizontal.sum(axis=1) >= w * .5)
    groups = [r for r in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1) if len(r)]
    failures, profiles = np.zeros_like(expected, bool), []
    for group in groups:
        row = int(group[np.argmax(expected[group].sum(axis=1))])
        cols = expected[row] >= common.C_STRONG
        candidates = np.arange(max(0, row - 1), min(h, row + 2))
        chosen = int(candidates[np.argmax(delivered[candidates][:, cols].sum(axis=1))])
        missing = cols & (delivered[chosen] < common.C_STRONG)
        failures[row] = missing
        profiles.append({"row": row, "delivered_row": chosen, "introduced_gap_columns": int(missing.sum())})
    out = common.group_findings(failures, "C", "review_required", "STAFF_SEAM", page_index=page_index,
                                feature_ids=[], detail={"line_id": line_id})
    ox, oy = origin
    for f in out:
        if "bbox" in f:
            a, b, c, d = f["bbox"]
            f["bbox"] = [a + ox, b + oy, c + ox, d + oy]
    return out, profiles


def verify_pages(cert_b, strip_pngs, pdf_path, *, generated, profile, pages=None):
    """Return certC; contract/integrity errors fail closed and reviews never pass."""
    started = time.perf_counter()
    findings, page_records = [], []
    counters = {"pdf_contract_checked": pages is None, "line_registrations": [], "features_tested": 0, "features_at_risk": 0}
    cert = {"stage": "C", "plan_sha256": cert_b.get("plan_sha256"), "pdf_sha256": None,
            "pages": page_records, "findings": findings, "counters": counters}
    def finish():
        counts = Counter(f["code"] for f in findings)
        counters.update(by_code=dict(counts), seconds=time.perf_counter() - started)
        cert["status"] = "fail" if any(f["severity"] == "fail" for f in findings) else "review_required" if findings else "pass"
        return cert
    try:
        if profile not in PROFILE_EPSILON and profile != "lossless":
            raise ValueError("unknown frozen render profile")
        if pdf_path is not None:
            cert["pdf_sha256"] = common.file_sha256(pdf_path)
        if pages is None:
            actual = decode_lossless_pdf(pdf_path, profile=profile)
        else:
            if pdf_path is not None:
                raise ValueError("pages= diagnostics must not claim a staged PDF digest")
            actual = [_image(p) for p in pages]
        if not actual:
            raise ValueError("no delivered pages")
    except Exception as error:
        findings.append(common.finding("C", "fail", "PDF_CONTRACT", feature_ids=[], detail={"reason": str(error)}))
        return finish()
    images = {}
    for sid, committed in cert_b.get("strips", {}).items():
        try:
            images[sid] = _image(strip_pngs[sid])
            if common.pixels_sha256(images[sid]) != committed:
                raise ValueError("strip differs from Stage A/B commitment")
        except Exception as error:
            findings.append(common.finding("I", "fail", "ARTIFACT_MISMATCH", strip_id=sid, feature_ids=[], detail={"reason": str(error)}))
    if any(f["code"] == "ARTIFACT_MISMATCH" for f in findings):
        return finish()
    if not cert_b.get("plan_sha256"):
        findings.append(common.finding("I", "fail", "ARTIFACT_MISMATCH", feature_ids=[], detail={"reason": "missing plan commitment"}))
        return finish()
    try:
        _check_feature_geometry(cert_b, images)
    except Exception as error:
        findings.append(common.finding("I", "fail", "ARTIFACT_MISMATCH", feature_ids=[], detail={"reason": str(error)}))
        return finish()
    records = cert_b.get("plan_records")
    if records is not None:
        try:
            if common.json_sha256(records) != cert_b["plan_sha256"]:
                raise ValueError("plan records differ from Stage B commitment")
            bound = Counter(common.json_sha256({k: r[k] for k in ("strip_id", "page_index", "copy_index", "line_id", "stages")})
                            for r in records["placements"])
            replay = Counter(common.json_sha256({**{k: r[k] for k in ("strip_id", "page_index", "copy_index", "line_id")}, "stages": _stages(r)})
                             for r in cert_b["instances"])
            if bound != replay:
                raise ValueError("instances differ from committed placement records")
            if common.json_sha256(generated) != common.json_sha256(records["generated_origins"]):
                raise ValueError("generated origins differ from committed plan records")
        except Exception as error:
            findings.append(common.finding("I", "fail", "ARTIFACT_MISMATCH", feature_ids=[], detail={"reason": str(error)}))
            return finish()
    if generated:
        committed_generated = cert_b.get("generated_sha256")
        if committed_generated is None and records is None:
            findings.append(common.finding("C", "review_required", "GENERATED_ORIGIN_UNBOUND", feature_ids=[],
                detail={"reason": "Stage B must bind generated templates/records to the plan certificate"}))
        elif committed_generated is not None and common.json_sha256(generated) != committed_generated:
            findings.append(common.finding("I", "fail", "ARTIFACT_MISMATCH", feature_ids=[],
                detail={"reason": "generated records differ from the Stage B commitment"}))
            return finish()
    try:
        expected, centres, lines, incomplete = _render(cert_b, images, generated, len(actual), obligations=True)
        for sid in incomplete:
            findings.append(common.finding("C", "review_required", "VERIFICATION_INCOMPLETE", strip_id=sid, feature_ids=[],
                                          detail={"reason": "Stage B did not forward Stage A features"}))
        survival, tested, risk = _survival(cert_b, images, lines)
        findings.extend(survival)
        counters.update(features_tested=tested, features_at_risk=risk)
        for pi, (e, d) in enumerate(zip(expected, actual)):
            page_profile = ("lossless-gray" if d.ndim == 2 else "lossless-rgb") if profile == "lossless" else profile
            epsilon = PROFILE_EPSILON[page_profile]
            if d.shape[:2] != e.shape[:2]:
                raise ValueError("delivered and expected page dimensions differ")
            if pages is not None and (d.ndim == 2) != (page_profile == "lossless-gray"):
                raise ValueError("diagnostic pixels disagree with declared profile")
            ec, dc = common.contrast_map(e), common.contrast_map(d)
            aligned, aligned_centres = ec.copy(), centres[pi].copy()
            for line in [l for l in lines if l["page_index"] == pi]:
                x, y = line["origin"]
                w, h = line["size"]
                region = ec[y:y + h, x:x + w]
                dx, dy, score = _register(region, dc, x, y)
                counters["line_registrations"].append({"page_index": pi, "line_id": line["line_id"], "offset": [dx, dy], "mean_ssd": score})
                if max(abs(dx), abs(dy)) > ACCEPTED_OFFSET_PX:
                    findings.append(common.finding("C", "fail", "PLACEMENT_MISMATCH", page_index=pi,
                        bbox=[x, y, x + w, y + h], feature_ids=[], detail={"line_id": line["line_id"], "offset": [dx, dy]}))
                if dx or dy:
                    aligned[y:y + h, x:x + w] = 0
                    aligned_centres[y:y + h, x:x + w] = 0
                    if x + dx < 0 or y + dy < 0 or x + dx + w > ec.shape[1] or y + dy + h > ec.shape[0]:
                        findings.append(common.finding("C", "fail", "PLACEMENT_MISMATCH", page_index=pi, feature_ids=[], detail={"reason": "line offset clips page"}))
                    else:
                        aligned[y + dy:y + dy + h, x + dx:x + dx + w] = region
                        aligned_centres[y + dy:y + dy + h, x + dx:x + dx + w] = centres[pi][y:y + h, x:x + w]
                xx, yy = max(0, x + dx), max(0, y + dy)
                seam, profiles = staff_continuity(region, dc[yy:yy + h, xx:xx + w], page_index=pi, line_id=line["line_id"], origin=[xx, yy])
                findings.extend(seam)
                counters.setdefault("staff_profiles", []).append({"page_index": pi, "line_id": line["line_id"], "rows": profiles})
            minus = np.maximum(aligned.astype(np.int16) - dc.astype(np.int16) - epsilon, 0)
            plus = np.maximum(dc.astype(np.int16) - aligned.astype(np.int16) - epsilon, 0)
            missing = (common.window_mean(minus) > 0) & (aligned_centres > 0)
            extra = common.window_mean(plus) > 0
            findings.extend(common.group_findings(missing, "C", "fail", "DELIVERED_FEATURE_MISSING", page_index=pi, feature_ids=[], detail={"epsilon": epsilon}))
            findings.extend(common.group_findings(extra, "C", "fail", "DELIVERED_EXTRA_INK", page_index=pi, feature_ids=[], detail={"epsilon": epsilon}))
            page_records.append({"index": pi, "pixels_sha256": common.pixels_sha256(d), "profile": page_profile,
                                 "missing_window_centres": int(missing.sum()), "extra_window_centres": int(extra.sum())})
    except Exception as error:
        findings.append(common.finding("C", "fail", "RENDER_CONTRACT", feature_ids=[], detail={"reason": str(error)}))
    return finish()
