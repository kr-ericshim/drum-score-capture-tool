"""Independent, conservative display-member -> delivered PDF evidence ledger.

No imports from cleanup, tracking, measure accounting or render modules. See
docs/archive/reflow/LEDGER_2D_INTERFACE.md and docs/archive/reflow/LEDGER.md for the contract and hooks.
Arrays are BGR uint8 (or grayscale); persisted crops are lossless embedded PNGs.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import tempfile
from collections import OrderedDict
import re
import zlib
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, JpegImagePlugin, PdfParser

VERSION = "display-ledger-2"
TERMINALS = ("preserved", "recovered_beneath_overlay", "equivalent_observation",
             "non_score_material", "source_limited", "unresolved")
DISPOSITION_TERMINAL = {"cursor_recovery": "recovered_beneath_overlay",
    "overlap_duplicate": "equivalent_observation", "staff_scaffold": "preserved",
    "chrome": "non_score_material", "preview_inset": "non_score_material",
    "structural_replacement": "unresolved", "unresolved_alternative": "unresolved",
    "source_limited": "source_limited"}
SOURCE_LIMIT_REASONS = ("fade_transition", "registration_out_of_range", "source_clipped", "outside_requested_range")
MIN_CONTRAST = 12
C_CLEAR = 64  # Clear notation owns delivery; low-contrast fringes remain context.
C_PAGE = 64  # Local paper-relative ink tolerates resampling and JPEG softening.
COVER = .90  # A mark core must retain at least ninety percent of its ink.
IOU = .60  # Shape overlap rejects substituted or moved notation.
LINE_SEARCH = 3  # Recorded placement is independently registered within three output pixels.
MARK_SEARCH = 1  # Residual mark alignment may vary by one output pixel.
SOURCE_CLEAR_CONTRAST = C_CLEAR
MAX_CROP = 64
STAGES = ("display_to_strip", "strip_to_line", "line_to_page")


class TransformLossError(ValueError):
    """A supplied piecewise map demonstrably deletes/double-owns evidence."""


def pixels_hash(image: np.ndarray) -> str:
    a = np.ascontiguousarray(image)
    digest = hashlib.sha256(str((a.shape,a.dtype.str)).encode())
    digest.update(memoryview(a))
    return digest.hexdigest()


def pack_crop(image: np.ndarray) -> dict[str, Any]:
    """Small lossless, JSON-safe evidence; hash covers decoded shape/type/pixels."""
    a = np.asarray(image, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", a)
    if not ok:
        raise ValueError("cannot encode evidence crop")
    return {"png": base64.b64encode(buf).decode("ascii"), "sha256": pixels_hash(a)}


def unpack_crop(record: dict[str, Any]) -> np.ndarray:
    buf = base64.b64decode(record["png"], validate=True)
    a = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_UNCHANGED)
    if a is None or pixels_hash(a) != record["sha256"]:
        raise ValueError("evidence crop/hash mismatch")
    return a


def _gray(a: np.ndarray) -> np.ndarray:
    return a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)


def _contrast(a: np.ndarray, polarity: str = "light") -> np.ndarray:
    g = _gray(a).astype(np.float32)
    paper = np.percentile(g, 90 if polarity == "light" else 10)
    return np.clip(paper - g if polarity == "light" else g - paper, 0, 255).astype(np.uint8)


def _matrix(value: Sequence[Sequence[float]]) -> np.ndarray:
    m = np.array(value, dtype=float).reshape(3, 3)
    if not np.isfinite(m).all() or not np.allclose(m[2], [0, 0, 1]):
        raise ValueError("only finite affine transforms supported")
    if abs(np.linalg.det(m)) < 1e-9:
        raise ValueError("singular transform")
    return m


def _bbox(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _boxes(union: np.ndarray) -> list[tuple[list[int], np.ndarray]]:
    """Connected hypotheses, tiled when large; no area/duration filtering."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(union.astype(np.uint8), 8)
    out = []
    for k in range(1, n):
        x, y, w, h, _ = map(int, stats[k])
        for yy in range(y, y + h, MAX_CROP - 4):
            for xx in range(x, x + w, MAX_CROP - 4):
                x1, y1 = min(xx + MAX_CROP - 4, x + w), min(yy + MAX_CROP - 4, y + h)
                b = [max(0, xx - 2), max(0, yy - 2), min(union.shape[1], x1 + 2), min(union.shape[0], y1 + 2)]
                sel = labels[b[1]:b[3], b[0]:b[2]] == k
                # Tiling owns only its interior, with context padding kept separately.
                owned = np.zeros_like(sel)
                owned[yy - b[1]:y1 - b[1], xx - b[0]:x1 - b[0]] = True
                sel &= owned
                if sel.any():
                    out.append((b, sel))
    return out


def _mark_core(mask: np.ndarray) -> np.ndarray:
    # Erode in each direction only where a native three-pixel run exists.
    a = mask.astype(np.uint8)
    horizontal = cv2.erode(a,np.ones((1,3),np.uint8),borderType=cv2.BORDER_CONSTANT)>0
    vertical = cv2.erode(a,np.ones((3,1),np.uint8),borderType=cv2.BORDER_CONSTANT)>0
    thick_x = cv2.dilate(horizontal.astype(np.uint8),np.ones((1,3),np.uint8))>0
    thick_y = cv2.dilate(vertical.astype(np.uint8),np.ones((3,1),np.uint8))>0
    core = mask & (~thick_x | horizontal) & (~thick_y | vertical)
    return core if core.any() else mask.copy()


def mark_masks(item: dict) -> list[tuple[list[int], np.ndarray, np.ndarray]]:
    """Independent eight-connected clear marks; stored classes are not evidence."""
    raw = unpack_crop(item["foreground_hypothesis"])>0
    contrast = unpack_crop(item["expected_contrast"])
    if raw.shape!=contrast.shape:
        raise ValueError("contrast/hypothesis shape mismatch")
    n,labels,stats,_ = cv2.connectedComponentsWithStats((raw & (contrast>=C_CLEAR)).astype(np.uint8),8)
    result = []
    for k in range(1,n):
        x,y,w,h,_ = map(int,stats[k])
        mask = labels[y:y+h,x:x+w]==k
        result.append(([x,y,x+w,y+h],mask,_mark_core(mask)))
    return result


def record_marks(item: dict) -> None:
    contrast = unpack_crop(item["expected_contrast"])
    item["marks"] = []
    for b,mask,core in mark_masks(item):
        x,y,e,f = b
        c = contrast[y:f,x:e][mask]
        item["marks"].append({"bbox":b,"core":pack_crop(core.astype(np.uint8)*255),
            "source_contrast":{"min":int(c.min()),"max":int(c.max()),"mean":round(float(c.mean()),2)},
            "pixels":int(mask.sum())})
    item["delivery_obligation"] = "clear_marks" if item["marks"] else "faint_only"


def _project_mark(item: dict, transforms: Sequence[dict], b, mask):
    x,y,e,f = b
    ox,oy = item["display_bbox"][:2]
    small = dict(item,display_bbox=[ox+x,oy+y,ox+e,oy+f],
        foreground_hypothesis=pack_crop(mask.astype(np.uint8)*255),expected_contrast=pack_crop(mask.astype(np.uint8)*255))
    transforms = [dict(t) for t in transforms]
    if transforms[1].get("kind")=="piecewise":
        stage = transforms[1]
        matrix = _matrix(stage.get("pre_matrix",np.eye(3))) @ _matrix(transforms[0]["matrix"])
        points = np.array([[ox+x,oy+y,1],[ox+e,oy+y,1],[ox+x,oy+f,1],[ox+e,oy+f,1]]) @ matrix.T
        lo,hi = points[:,:2].min(axis=0)-3,points[:,:2].max(axis=0)+3
        stage["pieces"] = [p for p in stage["pieces"] if p["src_bbox"][0]<=hi[0] and p["src_bbox"][2]>=lo[0]
            and p["src_bbox"][1]<=hi[1] and p["src_bbox"][3]>=lo[1]]
    if transforms[1].get("pre_resample"):
        c,projected,origin = _project_raster_item(small,transforms,allow_empty=True)
    else:
        stages = [dict(t) for t in transforms]
        last = transforms[2]
        if last.get("resample"):
            stages[2] = {"stage":"line_to_page","kind":"affine","matrix":np.eye(3).tolist()}
            c,projected,origin = project_item(small,stages)
            c,projected,origin = _resize_evidence(c,projected,origin,last["resample"])
            matrix = _matrix(last["matrix"])
            offset = matrix[:2,2]-[(matrix[0,0]-1)/2,(matrix[1,1]-1)/2]
            origin = (np.asarray(origin)+np.rint(offset).astype(int)).tolist()
        else:
            c,projected,origin = project_item(small,stages)
    return c,c>=C_PAGE,origin


def _placement_offsets(ledger: dict, pages: Sequence[np.ndarray], projections=None) -> dict:
    groups = {}
    items = {i["id"]:i for i in ledger.get("items",[])}
    for rep in ledger.get("representations",[]):
        item = items.get(rep.get("item_id"))
        if item is None or rep.get("projection_error"):
            continue
        key = (rep["page_index"],rep.get("line_id",item["display_id"]),rep["copy_index"])
        for mi,(b,mark,core) in enumerate(mark_masks(item)):
            try:
                c,full,o = _project_mark(item,rep["transforms"],b,mark)
                _,m,co = _project_mark(item,rep["transforms"],b,core)
                if projections is not None:
                    pc = np.zeros(full.shape,bool)
                    cx,cy = np.asarray(co)-o
                    pc[cy:cy+m.shape[0],cx:cx+m.shape[1]] = m
                    projections[(id(rep),mi)] = (c,full,o,pc if pc.any() else full)
            except (ValueError,KeyError,cv2.error):
                continue
            yy,xx = np.nonzero(m)
            groups.setdefault(key,[]).append(np.column_stack((xx+co[0],yy+co[1])))
    result = {}
    for key,parts in groups.items():
        pi,_,_ = key
        if not 0<=pi<len(pages) or not parts:
            continue
        coords = np.unique(np.concatenate(parts),axis=0)
        gray = _gray(pages[pi])
        a,b = np.maximum(coords.min(axis=0)-LINE_SEARCH-3,0)
        e,f = np.minimum(coords.max(axis=0)+LINE_SEARCH+4,[gray.shape[1],gray.shape[0]])
        paper = _percentile(gray[b:f,a:e],.9)
        best = None
        for dy in range(-LINE_SEARCH,LINE_SEARCH+1):
            for dx in range(-LINE_SEARCH,LINE_SEARCH+1):
                p = coords+[dx,dy]
                inside = (p[:,0]>=0)&(p[:,1]>=0)&(p[:,0]<gray.shape[1])&(p[:,1]<gray.shape[0])
                score = float(np.maximum(paper-gray[p[inside,1],p[inside,0]].astype(float),0).sum())/len(p)
                rank = (score,-(dx*dx+dy*dy))
                if best is None or rank>best[0]: best = (rank,[dx,dy])
        result[key] = best[1]
    return result


def _record_embedded(*, source_video: str, display_id: str, occurrence_id: str,
                       members: Sequence[dict[str, Any]], expected_multiplicity: int = 1,
                       candidates: Sequence[Sequence[int]] | None = None) -> dict[str, Any]:
    """Snapshot *unmodified* members, including ones later excluded by duration.

    Each member: id, timestamp, image, roi_origin, registration_shift,
    registration_uncertainty, usable (bool array), occluded (bool array), and
    optional source_to_native / polarity. Registration is recorded, never estimated
    here. ``image`` is native ROI/display pixels BEFORE cleanup. Missing geometry
    is retained as unknown and prevents a pass. Automatic hypotheses use raw
    photometric contrast, not the pipeline's cleaned/protected masks.
    """
    if not members or expected_multiplicity < 1 or not source_video or not occurrence_id:
        raise ValueError("source, occurrence, members and positive multiplicity required")
    shape = members[0]["image"].shape[:2]
    if any(m["image"].shape[:2] != shape for m in members):
        raise ValueError("members must share a display canvas shape")
    aligned, contrasts, eligible, transforms = [], [], [], []
    for m in members:
        shift = m.get("registration_shift", [0, 0])
        mat = np.eye(3)
        mat[:2, 2] = shift
        raw = np.asarray(m["image"])
        polarity = m.get("polarity", "light" if np.median(_gray(raw)) >= 128 else "dark")
        # Border does not manufacture foreground outside the member.
        c = cv2.warpAffine(_contrast(raw, polarity), mat[:2], (shape[1], shape[0]), flags=cv2.INTER_LINEAR)
        img = cv2.warpAffine(raw, mat[:2], (shape[1], shape[0]), borderValue=255)
        free = np.asarray(m.get("usable", np.ones(shape, bool)), bool) & ~np.asarray(m.get("occluded", np.zeros(shape, bool)), bool)
        if free.shape != shape:
            raise ValueError("observation visibility mask shape mismatch")
        free = cv2.warpAffine(free.astype(np.uint8), mat[:2], (shape[1], shape[0]), flags=cv2.INTER_NEAREST) > 0
        aligned.append(img)
        contrasts.append(c)
        eligible.append(free)
        transforms.append({"stage": "observation_to_display", "matrix": mat.tolist(),
                           "registration_shift": m.get("registration_shift"),
                           "roi_origin": m.get("roi_origin"), "source_to_native": m.get("source_to_native"),
                           "registration_uncertainty": m.get("registration_uncertainty"), "polarity": polarity})
    # Inventory every raw hypothesis. A clear blank in another observation
    # cannot erase ink seen only in an obscured/unusable member. Visibility
    # classifies support below; it never filters the inventory.
    foreground = np.stack(contrasts) >= MIN_CONTRAST
    union = np.any(foreground, axis=0)
    if candidates is None:
        clear_foreground = np.any(foreground & np.stack(eligible), axis=0)
        # Separate unseen overlay ink from clearly witnessed notation, retaining
        # disjoint ownership of every raw foreground pixel in both inventories.
        boxes = _boxes(clear_foreground) + _boxes(union & ~clear_foreground)
    else:
        boxes = []
        for b0 in candidates:
            x0, y0, x1, y1 = b = list(map(int, b0))
            if not (0 <= x0 < x1 <= shape[1] and 0 <= y0 < y1 <= shape[0]) or max(x1-x0, y1-y0) > MAX_CROP:
                raise ValueError("candidate outside display or larger than small-crop cap")
            sel = union[y0:y1, x0:x1]
            if sel.any():
                boxes.append((b, sel))
    items = []
    order = sorted(range(len(members)), key=lambda i: (float(members[i]["timestamp"]), str(members[i]["id"])))
    counted_indices, last = set(), None
    for i in order:
        if last is None:
            same = False
        else:
            delta = np.abs(aligned[i].astype(np.int16)-aligned[last].astype(np.int16))
            same = delta.mean() <= 1.0 and (delta>8).mean() <= .001 and np.array_equal(eligible[i],eligible[last])
        if not same:
            counted_indices.add(i)
        last = i
    discovered = np.zeros(shape,bool)
    for b,hypothesis in boxes:
        discovered[b[1]:b[3],b[0]:b[2]] |= hypothesis
    for serial, (b, hypothesis) in enumerate(boxes):
        x0, y0, x1, y1 = b
        evidence = []
        for i in order:
            m, tf = members[i], transforms[i]
            c = contrasts[i][y0:y1, x0:x1]
            free = eligible[i][y0:y1, x0:x1]
            clear = bool(free[hypothesis].all())
            # The *whole* hypothesis must be seen. Majority pixels of a long
            # staff cannot certify a minority dot attached to it as repeated.
            seen = clear and bool((c[hypothesis] >= MIN_CONTRAST).all())
            # Consecutive near-identical RAW member frames with equal visibility
            # are one observation. Differences elsewhere in the frame avoid
            # mistaking a moving cursor's clear evidence for exact repeats.
            inv = np.linalg.inv(np.array(tf["matrix"]))
            corners = np.array([[x0,y0,1],[x1,y1,1]]) @ inv.T
            nb = [max(0,int(math.floor(corners[0,0]))), max(0,int(math.floor(corners[0,1]))),
                  min(shape[1],int(math.ceil(corners[1,0]))), min(shape[0],int(math.ceil(corners[1,1])))]
            if nb[0] >= nb[2] or nb[1] >= nb[3]:
                continue
            native = m["image"][nb[1]:nb[3], nb[0]:nb[2]]
            evidence.append({"observation_id": str(m["id"]), "timestamp": float(m["timestamp"]),
                             "native_bbox": nb, "raw_patch": pack_crop(native), "display_patch": pack_crop(aligned[i][y0:y1,x0:x1]),
                             "contrast": pack_crop(c), "usable_mask": pack_crop(free.astype(np.uint8)*255),
                             "native_usable_mask": pack_crop(np.asarray(m.get("usable",np.ones(shape,bool)),bool)[nb[1]:nb[3],nb[0]:nb[2]].astype(np.uint8)*255),
                             "native_occluded_mask": pack_crop(np.asarray(m.get("occluded",np.zeros(shape,bool)),bool)[nb[1]:nb[3],nb[0]:nb[2]].astype(np.uint8)*255),
                             "eligible": clear, "supports": seen, "counted": i in counted_indices, "transform": tf})
        counted = [e for e in evidence if e["counted"] and e["eligible"]]
        supports = [e for e in counted if e["supports"]]
        separated, prev = 0, -math.inf
        for e in supports:
            if e["timestamp"] - prev >= 1.0:
                separated += 1
                prev = e["timestamp"]
        ratio = len(supports) / len(counted) if counted else 0
        cls = "protected" if ratio >= .8 and separated >= 3 else "credible-few" if supports else "ambiguous"
        # Max clear contrast preserves minority dots/gray strokes; NOT a median.
        expected = np.zeros(hypothesis.shape, np.uint8)
        for e in evidence:
            c = unpack_crop(e["contrast"])
            free = unpack_crop(e["usable_mask"]) > 0
            expected = np.maximum(expected, np.where(free, c, 0).astype(np.uint8))
        if not supports:
            expected = np.maximum.reduce([contrasts[i][y0:y1,x0:x1] for i in order])
        items.append({"id": f"{display_id}:e{serial:05d}", "source_video": source_video, "display_id": display_id,
                      "occurrence_id": occurrence_id, "display_bbox": b, "foreground_hypothesis": pack_crop(hypothesis.astype(np.uint8)*255),
                      "expected_contrast": pack_crop(expected), "evidence": evidence, "class": cls,
                      "support": {"eligible": len(counted), "supporting": len(supports), "ratio": ratio, "separated_groups": separated},
                      "expected_multiplicity": expected_multiplicity})
    for item in items:
        record_marks(item)
    return {"version": VERSION, "source_video": source_video, "displays": [{"id": display_id, "occurrence_id": occurrence_id,
            "observations": [str(m["id"]) for m in members], "shape": list(shape),
            "raw_foreground_uninventoried_px": int((union & ~discovered).sum())}], "items": items,
            "representations": [], "dispositions": [], "generated_origins": [],
            "observations": [], "display_dispositions": [], "occurrence_remaps": []}



class EvidenceUnavailableError(ValueError):
    """A referenced frame or mask cannot be read with its recorded integrity."""


def _value(value):
    return value() if callable(value) else value


def _visibility(member, shape):
    usable = np.asarray(_value(member.get("usable", True)), bool)
    occluded = np.asarray(_value(member.get("occluded", False)), bool)
    if usable.ndim == 0:
        usable = np.broadcast_to(usable,shape)
    if occluded.ndim == 0:
        occluded = np.broadcast_to(occluded,shape)
    if usable.shape != shape or occluded.shape != shape:
        raise ValueError("observation visibility mask shape mismatch")
    return usable, occluded


def _percentile(gray, q):
    counts = cv2.calcHist([gray],[0],None,[256],[0,256]).ravel()
    cumulative = np.cumsum(counts,dtype=np.float64)
    rank = (gray.size-1)*q
    lo,hi = np.searchsorted(cumulative,[math.floor(rank),math.ceil(rank)],side="right")
    return float(lo+(hi-lo)*(rank-math.floor(rank)))


def _photometry(raw, polarity, *, gray=None, output=None):
    gray = _gray(raw) if gray is None else gray
    paper = _percentile(gray,.9 if polarity=="light" else .1)
    # Integer subtraction equals the v1 clipped float-to-uint8 contrast.
    c = cv2.subtract(math.floor(paper),gray,dst=output) if polarity=="light" else cv2.subtract(gray,math.ceil(paper),dst=output)
    return c,paper


def _reference(root, image, *, mask=False):
    if mask and image.all():
        return "all"
    if mask and not image.any():
        return "none"
    path = root / (pixels_hash(image) + ".png")
    if not path.exists():
        if mask:
            Image.fromarray(image.astype(np.uint8)*255).convert("1").save(path)
        elif not cv2.imwrite(str(path), image):
            raise ValueError("cannot write evidence canvas")
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _evidence_view(raw, usable, occluded, tf, member, bbox, *, contrast=None, aligned=None, free=None,
                   paper=None, eligible=None, supports=None, arrays=False):
    x0,y0,x1,y1 = bbox
    mat = _matrix(tf["matrix"])
    inv = np.linalg.inv(mat)
    corners = np.array([[x0,y0,1],[x1,y1,1]]) @ inv.T
    nb = [max(0,int(math.floor(corners[0,0]))), max(0,int(math.floor(corners[0,1]))),
          min(raw.shape[1],int(math.ceil(corners[1,0]))), min(raw.shape[0],int(math.ceil(corners[1,1])))]
    if nb[0] >= nb[2] or nb[1] >= nb[3]:
        return None
    local = mat[:2].copy(); local[:,2] -= [x0,y0]
    size = (x1-x0,y1-y0)
    if aligned is None:
        patch = cv2.warpAffine(raw,local,size,borderValue=255)
    else:
        patch = aligned[y0:y1,x0:x1]
    if contrast is None:
        # Only a small native window is needed; paper was measured on the full canvas.
        lo = np.maximum(np.floor(np.array([x0,y0])-mat[:2,2]).astype(int)-2,0)
        hi = np.minimum(np.ceil(np.array([x1,y1])-mat[:2,2]).astype(int)+2,[raw.shape[1],raw.shape[0]])
        gray = _gray(raw[lo[1]:hi[1],lo[0]:hi[0]])
        c = cv2.subtract(math.floor(paper),gray) if tf["polarity"]=="light" else cv2.subtract(gray,math.ceil(paper))
        cm = local.copy(); cm[:,2] += lo
        c = cv2.warpAffine(c,cm,size,flags=cv2.INTER_LINEAR)
    else:
        c = contrast[y0:y1,x0:x1]
    if free is None:
        # Warp visibility in the same native window rather than allocating a canvas.
        native_free = usable[lo[1]:hi[1],lo[0]:hi[0]] & ~occluded[lo[1]:hi[1],lo[0]:hi[0]]
        f = cv2.warpAffine(native_free.astype(np.uint8),cm,size,flags=cv2.INTER_NEAREST)>0
    else:
        f = free[y0:y1,x0:x1]
    if arrays:
        return {"observation_id":member["observation_id"],"timestamp":member["timestamp"],
            "contrast_array":c,"free_array":f,"transform":tf}
    ns = np.s_[nb[1]:nb[3],nb[0]:nb[2]]
    return {"observation_id":member["observation_id"],"timestamp":member["timestamp"],"native_bbox":nb,
            "raw_patch":pack_crop(raw[ns]),"display_patch":pack_crop(patch),"contrast":pack_crop(c),
            "usable_mask":pack_crop(f.astype(np.uint8)*255),
            "native_usable_mask":pack_crop(usable[ns].astype(np.uint8)*255),
            "native_occluded_mask":pack_crop(occluded[ns].astype(np.uint8)*255),
            "eligible":eligible,"supports":supports,"counted":member["counted"],"transform":tf}


class EvidenceResolver:
    """Lazily expose the v1 views in either mode, with a bounded frame/mask LRU."""
    def __init__(self, ledger: dict, root: Path | str | None = None):
        self.ledger = ledger
        self.root = Path(root if root is not None else ledger.get("evidence_root", "."))
        self.displays = {d["id"]:d for d in ledger.get("displays",[])}
        self.observations = {o["id"]:o for o in ledger.get("observations",[])}
        self.cache = OrderedDict()
        self.paper = {}
        self.view_batch = {}
        self.canvas_checked = set()

    def _read(self, path, sha256=None, pixels_sha256=None):
        key = (str(path),sha256,pixels_sha256)
        if key not in self.cache:
            try:
                data = Path(path).read_bytes()
                if sha256 and hashlib.sha256(data).hexdigest()!=sha256:
                    raise ValueError("PNG byte hash mismatch")
                image = cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_UNCHANGED)
                if image is not None and pixels_sha256 and pixels_hash(image)!=pixels_sha256 and image.ndim==2:
                    # Hook-0 loader decodes stored grayscale PNGs as BGR.
                    image = cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
                if image is None or pixels_sha256 and pixels_hash(image)!=pixels_sha256:
                    raise ValueError("PNG pixel hash mismatch")
            except (OSError,ValueError,cv2.error) as exc:
                raise EvidenceUnavailableError(f"{path}: {exc}") from exc
            self.cache[key] = image
            # A small LRU of at most three decoded frames/masks.
            while len(self.cache)>3:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    def members(self, item):
        display = self.displays.get(item["display_id"],{})
        return display.get("members",[])

    def observation_ids(self, item):
        if "evidence" in item:
            return list(dict.fromkeys(e["observation_id"] for e in item["evidence"]))
        return list(dict.fromkeys(m["observation_id"] for m in self.members(item)))

    def _mask(self, ref, shape):
        if ref in ("all","none"):
            return np.broadcast_to(np.bool_(ref=="all"),shape)
        image = self._read(self.root/ref["path"],ref["sha256"])
        if image.shape!=shape:
            raise ValueError("referenced mask shape mismatch")
        return image>0

    def views(self, item, *, supporting_only: bool = False):
        if "evidence" not in item and item["id"] in self.view_batch:
            cached = self.view_batch[item["id"]]
            if isinstance(cached, Exception):
                raise cached
            yield from (e for e in cached if not supporting_only or e.get("eligible") and e.get("supports"))
            return
        yield from self._views(item, supporting_only=supporting_only)

    def prefetch(self, items: Sequence[dict]) -> None:
        """Bounded small-patch batch; decode each member once for these items."""
        self.view_batch = {}
        groups = {}
        for item in items:
            if "evidence" not in item:
                groups.setdefault(item["display_id"], []).append(item)
                self.view_batch[item["id"]] = []
        for group in groups.values():
            for member in self.members(group[0]):
                for item in group:
                    cache = self.view_batch[item["id"]]
                    if isinstance(cache, Exception):
                        continue
                    try:
                        cache.extend(self._views(item, member_index=member["index"]))
                    except (ValueError, KeyError, TypeError, IndexError, cv2.error) as exc:
                        self.view_batch[item["id"]] = exc
        for value in self.view_batch.values():
            if isinstance(value, list):
                value.sort(key=lambda e: (e["timestamp"], e["observation_id"]))

    def _views(self, item, *, supporting_only: bool = False, member_index: int | None = None, arrays: bool = False):
        if "evidence" in item:
            yield from (e for e in item["evidence"] if not supporting_only or e.get("eligible") and e.get("supports"))
            return
        display = self.displays[item["display_id"]]
        if display.get("evidence_mode")!="referenced" or "evidence_bits" not in item:
            raise ValueError("missing item evidence")
        bits = {k:int(item["evidence_bits"][k],16) for k in ("eligible","supports")}
        for member in sorted(self.members(item),key=lambda m:(m["timestamp"],m["observation_id"])):
            if member_index is not None and member["index"] != member_index:
                continue
            if supporting_only and not (bits["eligible"] & bits["supports"] & (1 << member["index"])):
                continue
            tf = member["transform"]
            if "frame_ref" in member:
                ref = member["frame_ref"]
                obs = self.observations.get(ref["observation_id"])
                if obs is None or not obs.get("frame_path"):
                    raise EvidenceUnavailableError(f"observation frame unavailable: {ref['observation_id']}")
                frame = self._read(obs["frame_path"],obs.get("retained_frame_png_sha256",obs.get("frame_png_sha256")),obs.get("pixels_sha256"))
                a,b,c,d = map(int,ref["crop_box"])
                if not 0<=a<c<=frame.shape[1] or not 0<=b<d<=frame.shape[0]:
                    raise ValueError("frame_ref crop outside observation")
                raw = frame[b:d,a:c]
                # frame_ref is before any resize (hook 0 work-scale may differ).
                if raw.shape[:2]!=tuple(display["shape"]):
                    raw = cv2.resize(raw,tuple(display["shape"][::-1]),interpolation=ref.get("resize_interpolation",cv2.INTER_AREA))
            else:
                ref = member["canvas_ref"]
                raw = self._read(self.root/ref["path"],ref["sha256"])
            shape = tuple(display["shape"])
            if raw.shape[:2]!=shape:
                raise ValueError("referenced canvas shape mismatch")
            canvas_key = (display["id"], member["index"], member.get("canvas_pixels_sha256"))
            if member.get("canvas_pixels_sha256") and canvas_key not in self.canvas_checked:
                if pixels_hash(raw)!=member["canvas_pixels_sha256"]:
                    raise EvidenceUnavailableError("referenced canvas pixels disagree with recorded member")
                self.canvas_checked.add(canvas_key)
            usable,occluded = self._mask(member["usable_ref"],shape),self._mask(member["occluded_ref"],shape)
            key = (display["id"],member["index"])
            if key not in self.paper:
                self.paper[key] = _photometry(raw,tf["polarity"])[1]
            ev = _evidence_view(raw,usable,occluded,tf,member,item["display_bbox"],paper=self.paper[key],
                    eligible=bool(bits["eligible"] & (1<<member["index"])),supports=bool(bits["supports"] & (1<<member["index"])),arrays=arrays)
            if ev is not None:
                yield ev


def record_obligations(*, source_video: str, display_id: str, occurrence_id: str,
                       members: Sequence[dict[str, Any]], expected_multiplicity: int = 1,
                       candidates: Sequence[Sequence[int]] | None = None,
                       evidence_dir: Path | None = None) -> dict[str, Any]:
    """Snapshot all offered members; callable canvases are streamed in two passes."""
    if evidence_dir is None and all(not any(callable(m.get(k)) for k in ("image","usable","occluded")) for m in members):
        return _record_embedded(source_video=source_video,display_id=display_id,occurrence_id=occurrence_id,
                                members=members,expected_multiplicity=expected_multiplicity,candidates=candidates)
    if not members or expected_multiplicity<1 or not source_video or not occurrence_id:
        raise ValueError("source, occurrence, members and positive multiplicity required")
    root = Path(evidence_dir).resolve() if evidence_dir is not None else None
    if root is not None:
        root.mkdir(parents=True,exist_ok=True)
    order = sorted(range(len(members)),key=lambda i:(float(members[i]["timestamp"]),str(members[i]["id"])))
    records = [None]*len(members)
    shape,union,clear_union = None,None,None
    previous_free = None
    # Spool the preceding image in stripes; dedup needs exact channel differences,
    # but retaining a preceding full canvas would defeat callable streaming.
    with tempfile.TemporaryFile() as previous:
        for ordinal,i in enumerate(order):
            m = members[i]
            raw = np.asarray(_value(m["image"]))
            if shape is None:
                shape = raw.shape[:2]
                union,clear_union = np.zeros(shape,bool),np.zeros(shape,bool)
                gray_buffer,contrast_buffer = np.empty(shape,np.uint8),np.empty(shape,np.uint8)
                free_buffer,foreground_buffer,temp_buffer = (np.empty(shape,bool) for _ in range(3))
            if raw.shape[:2]!=shape:
                raise ValueError("members must share a display canvas shape")
            usable,occluded = _visibility(m,shape)
            mat = np.eye(3); mat[:2,2] = m.get("registration_shift",[0,0])
            gray = raw if raw.ndim==2 else cv2.cvtColor(raw,cv2.COLOR_BGR2GRAY,dst=gray_buffer)
            polarity = m.get("polarity") or ("light" if _percentile(gray,.5)>=128 else "dark")
            tf = {"stage":"observation_to_display","matrix":mat.tolist(),"registration_shift":m.get("registration_shift"),
                  "roi_origin":m.get("roi_origin"),"source_to_native":m.get("source_to_native"),
                  "registration_uncertainty":m.get("registration_uncertainty"),"polarity":polarity}
            contrast,paper = _photometry(raw,polarity,gray=gray,output=contrast_buffer)
            free = np.logical_not(occluded,out=free_buffer)
            np.logical_and(free,usable,out=free)
            if np.any(mat[:2,2]):
                contrast = cv2.warpAffine(contrast,mat[:2],(shape[1],shape[0]),flags=cv2.INTER_LINEAR)
                free = cv2.warpAffine(free.astype(np.uint8),mat[:2],(shape[1],shape[0]),flags=cv2.INTER_NEAREST)>0
            foreground = np.greater_equal(contrast,MIN_CONTRAST,out=foreground_buffer)
            union |= foreground
            np.logical_and(foreground,free,out=temp_buffer); clear_union |= temp_buffer
            rec = {"index":i,"observation_id":str(m["id"]),"timestamp":float(m["timestamp"]),"transform":tf,
                   "registration_uncertainty":m.get("registration_uncertainty"),"polarity":polarity,
                   "canvas_pixels_sha256":pixels_hash(raw)}
            if root is not None:
                if m.get("frame_ref") is not None:
                    rec["frame_ref"] = dict(m["frame_ref"])
                else:
                    rec["canvas_ref"] = _reference(root,raw)
                rec["usable_ref"],rec["occluded_ref"] = _reference(root,usable,mask=True),_reference(root,occluded,mask=True)
            aligned = raw if not np.any(mat[:2,2]) else cv2.warpAffine(raw,mat[:2],(shape[1],shape[0]),borderValue=255)
            del raw,gray,usable,occluded,contrast,foreground
            total,large,count = 0,0,0
            previous.seek(0)
            for y in range(0,shape[0],16):
                stripe = aligned[y:y+16]
                data = stripe.tobytes()
                offset = previous.tell()
                old = previous.read(len(data))
                if ordinal and len(old)==len(data):
                    delta = np.abs(stripe.astype(np.int16)-np.frombuffer(old,np.uint8).reshape(stripe.shape))
                    total += int(delta.sum()); large += int((delta>8).sum()); count += delta.size
                previous.seek(offset); previous.write(data)
            packed_free = np.packbits(free).tobytes()
            rec["counted"] = not (ordinal and count==aligned.size and total/count<=1. and large/count<=.001 and packed_free==previous_free)
            previous_free = packed_free
            records[i] = rec
            del aligned,free,stripe
    del gray_buffer,contrast_buffer,free_buffer,foreground_buffer,temp_buffer
    boxes = _boxes(clear_union)+_boxes(union & ~clear_union) if candidates is None else []
    if candidates is not None:
        for b0 in candidates:
            x0,y0,x1,y1 = b = list(map(int,b0))
            if not (0<=x0<x1<=shape[1] and 0<=y0<y1<=shape[0]) or max(x1-x0,y1-y0)>MAX_CROP:
                raise ValueError("candidate outside display or larger than small-crop cap")
            sel = union[y0:y1,x0:x1]
            if sel.any(): boxes.append((b,sel.copy()))
    discovered = np.zeros(shape,bool)
    items,expected,raw_max = [],[],[]
    for serial,(b,hypothesis) in enumerate(boxes):
        discovered[b[1]:b[3],b[0]:b[2]] |= hypothesis
        item = {"id":f"{display_id}:e{serial:05d}","source_video":source_video,"display_id":display_id,
                "occurrence_id":occurrence_id,"display_bbox":b,"foreground_hypothesis":pack_crop(hypothesis.astype(np.uint8)*255),
                "expected_multiplicity":expected_multiplicity}
        item["evidence_bits" if root is not None else "evidence"] = {"eligible":0,"supports":0} if root is not None else []
        items.append(item); expected.append(np.zeros(hypothesis.shape,np.uint8)); raw_max.append(np.zeros(hypothesis.shape,np.uint8))
    bits = [{"eligible":0,"supports":0} for _ in items]
    gray_buffer,contrast_buffer = np.empty(shape,np.uint8),np.empty(shape,np.uint8)
    free_buffer = np.empty(shape,bool)
    for i in order:
        m,rec = members[i],records[i]
        raw = np.asarray(_value(m["image"]))
        if raw.shape[:2]!=shape or pixels_hash(raw)!=rec["canvas_pixels_sha256"]:
            raise ValueError("streamed member pixels changed between passes")
        usable,occluded = _visibility(m,shape)
        tf = rec["transform"]; mat = _matrix(tf["matrix"])
        gray = raw if raw.ndim==2 else cv2.cvtColor(raw,cv2.COLOR_BGR2GRAY,dst=gray_buffer)
        contrast,_ = _photometry(raw,tf["polarity"],gray=gray,output=contrast_buffer)
        free = np.logical_not(occluded,out=free_buffer)
        np.logical_and(free,usable,out=free)
        aligned = None
        if np.any(mat[:2,2]):
            contrast = cv2.warpAffine(contrast,mat[:2],(shape[1],shape[0]),flags=cv2.INTER_LINEAR)
            free = cv2.warpAffine(free.astype(np.uint8),mat[:2],(shape[1],shape[0]),flags=cv2.INTER_NEAREST)>0
        if root is None:
            aligned = raw if not np.any(mat[:2,2]) else cv2.warpAffine(raw,mat[:2],(shape[1],shape[0]),borderValue=255)
        for k,((b,hypothesis),item) in enumerate(zip(boxes,items)):
            x0,y0,x1,y1 = b; c,f = contrast[y0:y1,x0:x1],free[y0:y1,x0:x1]
            clear = bool(f[hypothesis].all()); seen = clear and bool((c[hypothesis]>=MIN_CONTRAST).all())
            if clear: bits[k]["eligible"] |= 1<<i
            if seen: bits[k]["supports"] |= 1<<i
            np.maximum(expected[k],np.where(f,c,0),out=expected[k]); np.maximum(raw_max[k],c,out=raw_max[k])
            if root is None:
                ev = _evidence_view(raw,usable,occluded,tf,rec,b,contrast=contrast,aligned=aligned,free=free,eligible=clear,supports=seen)
                if ev is not None: item["evidence"].append(ev)
        c,f = None,None
        del raw,gray,usable,occluded,contrast,free,aligned
    for k,item in enumerate(items):
        counted = [i for i in order if records[i]["counted"] and bits[k]["eligible"] & (1<<i)]
        supports = [i for i in counted if bits[k]["supports"] & (1<<i)]
        separated,prev = 0,-math.inf
        for i in supports:
            if records[i]["timestamp"]-prev>=1.:
                separated += 1; prev = records[i]["timestamp"]
        ratio = len(supports)/len(counted) if counted else 0
        item["class"] = "protected" if ratio>=.8 and separated>=3 else "credible-few" if supports else "ambiguous"
        item["support"] = {"eligible":len(counted),"supporting":len(supports),"ratio":ratio,"separated_groups":separated}
        item["expected_contrast"] = pack_crop(expected[k] if supports else np.maximum(expected[k],raw_max[k]))
        if root is not None: item["evidence_bits"] = {name:hex(value) for name,value in bits[k].items()}
    for item in items:
        record_marks(item)
    display = {"id":display_id,"occurrence_id":occurrence_id,"observations":[str(m["id"]) for m in members],
               "shape":list(shape),"raw_foreground_uninventoried_px":int((union & ~discovered).sum())}
    ledger = {"version":VERSION,"source_video":source_video,"displays":[display],"items":items,
              **{k:[] for k in ("representations","dispositions","generated_origins","observations","display_dispositions","occurrence_remaps")}}
    if root is not None:
        display.update(evidence_mode="referenced",members=records)
        ledger["evidence_root"] = str(root)
    return ledger

def _warp_patch(c: np.ndarray, mask: np.ndarray, origin: Sequence[int], matrix: np.ndarray, *, limit: int = 1024):
    h, w = c.shape
    x, y = origin
    corners = np.array([[x,y,1],[x+w,y,1],[x,y+h,1],[x+w,y+h,1]]) @ matrix.T
    lo, hi = np.floor(corners[:,:2].min(axis=0)).astype(int), np.ceil(corners[:,:2].max(axis=0)).astype(int)
    size = hi - lo
    if np.any(size <= 0) or np.any(size > limit):
        raise ValueError("unsupported projected footprint size")
    local = matrix.copy()
    local[:2,2] += matrix[:2,:2] @ np.array([x,y]) - lo
    return (cv2.warpAffine(c, local[:2], tuple(size), flags=cv2.INTER_LINEAR),
            cv2.warpAffine(mask.astype(np.uint8), local[:2], tuple(size), flags=cv2.INTER_NEAREST)>0, lo.tolist())


def _resize_evidence(c: np.ndarray, mask: np.ndarray, origin: Sequence[int], spec: dict):
    """Replay cv2.resize on its recorded integer canvas, preserving global phase.

    Contrast outside the small raw context is zero. Ownership uses the same
    resampling kernel as contrast; nearest-neighbour masks fabricate ink in
    cubic zero lobes. Eight is the existing delivered-pixel contrast floor.
    """
    sw, sh = map(int, spec["source_size"])
    dw, dh = map(int, spec["output_size"])
    if min(sw, sh, dw, dh) <= 0 or max(sw, sh, dw, dh) > 32768:
        raise ValueError("invalid recorded resize canvas")
    dx, dy = spec.get("crop_origin", [0, 0])
    x, y = int(origin[0] - dx), int(origin[1] - dy)
    if [x + dx, y + dy] != list(origin):
        raise ValueError("resize crop origin must be integral")
    a, b, e, f = max(0, x), max(0, y), min(sw, x+c.shape[1]), min(sh, y+c.shape[0])
    if a >= e or b >= f:
        raise TransformLossError("source hypothesis outside resize canvas")
    if (sw, sh) == (dw, dh):
        sl = np.s_[b-y:f-y, a-x:e-x]
        return c[sl].copy(), mask[sl].copy(), [a, b]
    methods = {"cubic": cv2.INTER_CUBIC, "area": cv2.INTER_AREA}
    method = methods.get(spec.get("interpolation"))
    if method is None:
        raise ValueError("unsupported recorded resize interpolation")
    sx,sy = dw/sw,dh/sh
    oa,ob = max(0,int(math.floor(a*sx))-2),max(0,int(math.floor(b*sy))-2)
    oe,of = min(dw,int(math.ceil(e*sx))+2),min(dh,int(math.ceil(f*sy))+2)
    # Replay global resize phase on a small crop. Area uses an exact fractional
    # integral; cubic remaps the four-pixel kernel without full-strip canvases.
    def resize_patch(patch):
        if method==cv2.INTER_AREA:
            integral = cv2.integral(patch,sdepth=cv2.CV_64F)
            def at(xp,yp):
                xp = np.clip(xp-x,0,patch.shape[1]); yp = np.clip(yp-y,0,patch.shape[0])
                xi,yi = np.floor(xp).astype(int),np.floor(yp).astype(int)
                xj,yj = np.minimum(xi+1,patch.shape[1]),np.minimum(yi+1,patch.shape[0])
                xf,yf = xp-xi,yp-yi
                return ((1-yf[:,None])*((1-xf)*integral[yi[:,None],xi]+xf*integral[yi[:,None],xj])+
                    yf[:,None]*((1-xf)*integral[yj[:,None],xi]+xf*integral[yj[:,None],xj]))
            left,right = np.arange(oa,oe)/sx,np.arange(oa+1,oe+1)/sx
            top,bottom = np.arange(ob,of)/sy,np.arange(ob+1,of+1)/sy
            values = (at(right,bottom)-at(left,bottom)-at(right,top)+at(left,top))*sx*sy
            return np.clip(np.rint(values),0,255).astype(np.uint8)
        xx,yy = np.meshgrid((np.arange(oa,oe)+.5)/sx-.5-x,(np.arange(ob,of)+.5)/sy-.5-y)
        return cv2.remap(patch,xx.astype(np.float32),yy.astype(np.float32),method,borderMode=cv2.BORDER_CONSTANT)
    expected = resize_patch(c)
    owned = resize_patch(np.where(mask,c,0).astype(np.uint8))>=8
    return expected,owned,[oa,ob]


def _project_raster_item(item: dict, transforms: Sequence[dict], *, reference: bool = False, allow_empty: bool = False):
    context = item.get("_projection_context") or item.get("projection_context") or item
    c = context.get("contrast_array")
    c = unpack_crop(context["expected_contrast"]) if c is None else c.copy()
    paper = float(context.get("paper_level", 255))
    if 170 < paper < 254.5:
        c = 255-np.clip((paper-c.astype(np.float32))*(255/paper), 0, 255).astype(np.uint8)
    if paper > 170:
        c[c <= 3] = 0
    origin = list(context["display_bbox"][:2])
    mask = np.zeros(c.shape, bool)
    raw = unpack_crop(item["foreground_hypothesis"]) > 0
    x, y = np.asarray(item["display_bbox"][:2]) - origin
    mask[y:y+raw.shape[0], x:x+raw.shape[1]] = raw
    if reference:
        c, mask, origin = _warp_patch(c, mask, origin, _matrix(transforms[0]["matrix"]), limit=32768)
    else:
        c, mask, origin = _warp_patch(c, mask, origin, _matrix(transforms[0]["matrix"]))
    stage = transforms[1]
    spec = stage["pre_resample"]
    sw, sh = spec["source_size"]
    dw, dh = spec["output_size"]
    dx, dy = spec.get("crop_origin", [0, 0])
    sx, sy = dw/sw, dh/sh
    expected_matrix = [[sx, 0, (sx-1)/2-sx*dx], [0, sy, (sy-1)/2-sy*dy], [0, 0, 1]]
    if not np.allclose(stage["pre_matrix"], expected_matrix):
        raise ValueError("resize metadata and pre_matrix disagree")
    # Keep the native-centre deletion/double-ownership check independent of
    # the raster replay. Assembly partitions those original hypotheses once.
    yy, xx = np.nonzero(raw)
    centres = np.column_stack((xx+item["display_bbox"][0], yy+item["display_bbox"][1], np.ones(len(xx))))
    centres = centres @ (_matrix(stage["pre_matrix"]) @ _matrix(transforms[0]["matrix"])).T
    ownership = np.zeros(len(xx), np.int32)
    for piece in stage["pieces"]:
        a, b, e, f = piece["src_bbox"]
        ownership += (centres[:,0]>=a)&(centres[:,0]<e)&(centres[:,1]>=b)&(centres[:,1]<f)
    if not len(xx) or np.any(ownership != 1):
        raise TransformLossError("piecewise map omits or double-owns source foreground centres")
    c, mask, origin = _resize_evidence(c, mask, origin, stage["pre_resample"])
    c[c <= 3] = 0  # The line's white-paper mapping before its page resize.
    parts = []
    for piece in stage["pieces"]:
        a, b, e, f = map(int, piece["src_bbox"])
        a, b, e, f = max(a, origin[0]), max(b, origin[1]), min(e, origin[0]+c.shape[1]), min(f, origin[1]+c.shape[0])
        if a >= e or b >= f:
            continue
        sl = np.s_[b-origin[1]:f-origin[1], a-origin[0]:e-origin[0]]
        if piece.get("column_repeat"):
            n = int(piece["column_repeat"])
            if e-a != 1 or n <= 0:
                raise ValueError("column repeat requires one source column")
            mat = _matrix(piece["matrix"])
            if not np.allclose(mat[:2,:2], [[n,0],[0,1]]):
                raise ValueError("column repeat matrix disagrees")
            start = mat @ [a, b, 1]
            start[0] -= (n-1)/2
            if not np.allclose(start[:2], np.rint(start[:2])):
                raise ValueError("column repeat placement must be integral")
            parts.append((np.repeat(c[sl], n, axis=1), np.repeat(mask[sl], n, axis=1), np.rint(start[:2]).astype(int).tolist()))
        else:
            mat = _matrix(piece["matrix"])
            if reference and np.allclose(mat[:2,:2], np.eye(2)) and np.allclose(mat[:2,2], np.rint(mat[:2,2])):
                parts.append((c[sl], mask[sl], (np.asarray([a,b])+np.rint(mat[:2,2]).astype(int)).tolist()))
            else:
                parts.append(_warp_patch(c[sl], mask[sl], [a, b], mat))
    if not parts:
        raise TransformLossError("piecewise map has no resampled source footprint")
    lo = np.min([p[2] for p in parts], axis=0)
    hi = np.max([[p[2][0]+p[0].shape[1], p[2][1]+p[0].shape[0]] for p in parts], axis=0)
    if not reference and np.any(hi-lo > 1024):
        raise ValueError("piecewise footprint too large")
    c, mask = np.zeros(tuple((hi-lo)[::-1]), np.uint8), np.zeros(tuple((hi-lo)[::-1]), bool)
    for pc, pm, po in parts:
        x, y = np.asarray(po)-lo
        sl = np.s_[y:y+pc.shape[0], x:x+pc.shape[1]]
        c[sl] = np.maximum(c[sl], pc)
        mask[sl] |= pm
    page_stage = transforms[2]
    mat = _matrix(page_stage["matrix"])
    if not np.allclose(mat[:2,:2], np.eye(2)*mat[0,0], atol=.002) or mat[0,0]<=0:
        raise ValueError("line_to_page must be a positive uniform scale and placement")
    if page_stage.get("resample"):
        sw, sh = page_stage["resample"]["source_size"]
        dw, dh = page_stage["resample"]["output_size"]
        if not np.allclose(mat[:2,:2], [[dw/sw,0],[0,dh/sh]]):
            raise ValueError("page resize metadata and matrix disagree")
        c, mask, origin = _resize_evidence(c, mask, lo.tolist(), page_stage["resample"])
        sx, sy = mat[0,0], mat[1,1]
        offset = mat[:2,2] - [(sx-1)/2, (sy-1)/2]
        if not np.allclose(offset, np.rint(offset)):
            raise ValueError("recorded resize page placement must be integral")
        origin = (np.asarray(origin) + np.rint(offset).astype(int)).tolist()
    else:
        c, mask, origin = _warp_patch(c, mask, lo.tolist(), mat)
    if not mask.any() and not allow_empty:
        raise TransformLossError("resampling removes the entire source hypothesis")
    return c, mask, origin


def below_contrast_floor(item: dict, transforms: Sequence[dict], *, resolver: EvidenceResolver | None = None):
    """Prove faint raw ink contributes no pixel at the delivered contrast floor.

    Check every raw member, including rejected/occluded evidence. Clear source
    ink is never discharged by resampling, even if its footprint disappears.
    The isolated replay excludes the parent's strong sibling/context ink.
    """
    if not transforms[1].get("pre_resample"):
        return None
    mask = unpack_crop(item["foreground_hypothesis"]) > 0
    contrast = unpack_crop(item["expected_contrast"]).copy()
    maximum = int(contrast[mask].max())
    if maximum >= SOURCE_CLEAR_CONTRAST:
        return None
    yy, xx = np.nonzero(mask)
    points = np.column_stack((xx+item["display_bbox"][0], yy+item["display_bbox"][1], np.ones(len(xx))))
    views = resolver.views(item) if resolver is not None else iter(item.get("evidence", []))
    seen = False
    for view in views:
        seen = True
        aligned = unpack_crop(view["contrast"])
        native = points @ np.linalg.inv(_matrix(view["transform"]["matrix"])).T
        gray = _gray(unpack_crop(view["raw_patch"]))
        display_gray = _gray(unpack_crop(view["display_patch"])).astype(np.int16)
        if view["transform"].get("polarity", "light") == "light":
            paper = min(255, int((display_gray+aligned).max()))
            raw = np.clip(paper-gray.astype(np.int16), 0, 255).astype(np.uint8)
        else:
            paper = max(0, int((display_gray-aligned).min()))
            raw = np.clip(gray.astype(np.int16)-paper, 0, 255).astype(np.uint8)
        native = native[:,:2]-view["native_bbox"][:2]
        lower = np.floor(native).astype(int)
        fraction = native-lower
        # All interpolation neighbours must be faint, not just their average.
        for delta in ((0,0), (1,0), (0,1), (1,1)):
            coords = lower+delta
            inside = (coords[:,0]>=0)&(coords[:,1]>=0)&(coords[:,0]<raw.shape[1])&(coords[:,1]<raw.shape[0])
            for axis in (0,1):
                if delta[axis]:
                    inside &= fraction[:,axis] > 1e-9
            if inside.any():
                maximum = max(maximum, int(raw[coords[inside,1], coords[inside,0]].max()))
        maximum = max(maximum, int(aligned[mask].max()))
        if maximum >= SOURCE_CLEAR_CONTRAST:
            return None
    if not seen:
        return None
    context = {"display_bbox": item["display_bbox"], "expected_contrast": pack_crop(np.where(mask, contrast, 0).astype(np.uint8)),
               "paper_level": item.get("projection_context", {}).get("paper_level", 255)}
    isolated = dict(item, _projection_context=context)
    c, owned, _origin = _project_raster_item(isolated, transforms, allow_empty=True)
    delivered = int(c.max())
    if owned.any() or delivered >= 8:
        return None
    return {"kind": "below_contrast_floor", "source_max_contrast": maximum, "delivered_max_contrast": delivered,
            "source_clear_floor": SOURCE_CLEAR_CONTRAST, "delivered_floor": 8}


def project_item(item: dict[str, Any], transforms: Sequence[dict[str, Any]]):
    """Project native hypotheses; piece ownership follows mapped pixel centres."""
    if [t.get("stage") for t in transforms] != list(STAGES):
        raise ValueError("incomplete or unordered transform chain")
    if transforms[1].get("pre_resample") is not None:
        return _project_raster_item(item, transforms)
    c,mask,origin = unpack_crop(item["expected_contrast"]),unpack_crop(item["foreground_hypothesis"])>0,item["display_bbox"][:2]
    native_c,native_mask,native_origin = c,mask,origin
    yy,xx = np.nonzero(native_mask)
    native_centres = np.column_stack((xx+origin[0],yy+origin[1],np.ones(len(xx))))
    cumulative = np.eye(3)
    for t in transforms:
        if t["kind"]=="affine":
            mat = _matrix(t["matrix"])
            if t["stage"]=="line_to_page" and (not np.allclose(mat[:2,:2],np.eye(2)*mat[0,0],atol=.002) or mat[0,0]<=0):
                raise ValueError("line_to_page must be a positive uniform scale and placement")
            cumulative = mat @ cumulative
            c,mask,origin = _warp_patch(c,mask,origin,mat)
        elif t["kind"]=="piecewise" and t["stage"]=="strip_to_line":
            pre = _matrix(t.get("pre_matrix",np.eye(3))) @ cumulative
            centres = native_centres @ pre.T
            ownership = np.zeros(len(centres),np.int32)
            parts = []
            for piece in t["pieces"]:
                a,b,d,e = piece["src_bbox"]
                selected = (centres[:,0]>=a)&(centres[:,0]<d)&(centres[:,1]>=b)&(centres[:,1]<e)
                ownership += selected
                if not selected.any():
                    continue
                owned = np.zeros_like(native_mask)
                owned[yy[selected],xx[selected]] = True
                # Warp only the piece's owned native pixels, retaining their full
                # resampled footprint. Clipping at the cut can erase a centre's
                # entire footprint or split it into a neighbour's representation.
                parts.append(_warp_patch(native_c,owned,native_origin,_matrix(piece["matrix"]) @ pre))
            if not parts or np.any(ownership!=1):
                raise TransformLossError("piecewise map omits or double-owns source foreground centres")
            lo = np.min([p[2] for p in parts],axis=0)
            hi = np.max([[p[2][0]+p[0].shape[1],p[2][1]+p[0].shape[0]] for p in parts],axis=0)
            if np.any(hi-lo>1024):
                raise ValueError("piecewise footprint too large")
            c,mask = np.zeros(tuple((hi-lo)[::-1]),np.uint8),np.zeros(tuple((hi-lo)[::-1]),bool)
            for pc,pm,po in parts:
                x,y = np.array(po)-lo
                sl = np.s_[y:y+pc.shape[0],x:x+pc.shape[1]]
                c[sl] = np.maximum(c[sl],pc); mask[sl] |= pm
            origin = lo.tolist()
        else:
            raise ValueError("unsupported transform stage/kind")
    return c,mask,origin


def measure_placement_transform(placement: dict[str, Any], *, native_scale: float = 1.) -> dict[str, Any]:
    """Read existing measure placement columns/rows, never reconstruction flags.

    Source coordinates for the pieces are the *resampled* strip. ``pre_matrix``
    maps native strip pixel centres to them. Inserted columns are excluded from
    source ownership and require independently validated generated origins.
    Raises when the persisted record is insufficient to reconstruct the map.
    """
    if not math.isfinite(native_scale) or native_scale<=0:
        raise ValueError("invalid native strip scale")
    a,b = map(int,placement["cols_src_out"])
    r0,r1 = map(int,placement["rows_src_out"])
    width = int(placement["width_out"])
    inserted = set(map(int,placement.get("inserted_offsets",[])))
    removed = set(map(int,placement.get("removed_cols_out",[])))
    source = [c for c in range(a,b) if c not in removed]
    if not (a<b and r0<r1 and width>0) or any(j<0 or j>=width for j in inserted) or width-len(inserted)!=len(source):
        raise ValueError("measure record cannot reconstruct retained source columns")
    mapping = list(zip(source,[j for j in range(width) if j not in inserted]))
    pieces = []
    start = 0
    while start<len(mapping):
        end = start+1
        while end<len(mapping) and mapping[end][0]==mapping[end-1][0]+1 and mapping[end][1]==mapping[end-1][1]+1:
            end += 1
        src,dst = mapping[start]
        pieces.append({"src_bbox":[src,r0,mapping[end-1][0]+1,r1],
                       "matrix":[[1,0,float(placement["x_out"])+dst-src],
                                 [0,1,float(placement["y_out"])-r0],[0,0,1]]})
        start = end
    s = native_scale
    return {"stage":"strip_to_line","kind":"piecewise","pre_matrix":[[s,0,(s-1)/2],[0,s,(s-1)/2],[0,0,1]],
            "pieces":pieces,"inserted_offsets":sorted(inserted),"line_id":placement.get("line_id")}


def extract_pdf_pages(path: Path | str) -> list[dict[str, Any]]:
    """Read Pillow export's single full-page 300 dpi JPEG XObject, no rasteriser.

    Uses Pillow's own parser (already installed), deliberately rejects overlays,
    rotated pages, additional drawing commands and different PDF layouts.
    """
    pdf = PdfParser.PdfParser(filename=str(path))
    pages = []
    try:
        if pdf.trailer_dict.get(b"Encrypt") or not pdf.pages:
            raise ValueError("encrypted or empty PDF")
        for ref in pdf.pages:
            p = pdf.read_indirect(ref)
            if p.get(b"Rotate",0) or p.get(b"Annots") or p.get(b"CropBox") or p.get(b"UserUnit",1) != 1:
                raise ValueError("unsupported delivered page modifiers")
            resources = p[b"Resources"]
            if isinstance(resources, PdfParser.IndirectReference):
                resources = pdf.read_indirect(resources)
            if set(resources.keys()) - {b"ProcSet",b"XObject"}:
                raise ValueError("unsupported PDF resources")
            xo = resources[b"XObject"]
            if len(xo) != 1 or b"image" not in xo:
                raise ValueError("expected exactly one page JPEG")
            image = pdf.read_indirect(xo[b"image"])
            d = image.dictionary
            if d.get(b"Filter") != b"DCTDecode" or d.get(b"ColorSpace") != b"DeviceRGB" or d.get(b"BitsPerComponent") != 8 or d.get(b"SMask") or d.get(b"Mask") or d.get(b"Decode"):
                raise ValueError("unsupported JPEG image encoding")
            mb = list(map(float,p[b"MediaBox"]))
            if mb[:2] != [0.,0.] or min(mb[2:]) <= 0:
                raise ValueError("unexpected media box")
            stream = pdf.read_indirect(p[b"Contents"])
            if stream.dictionary.get(b"Filter"):
                raise ValueError("unsupported page command filter")
            match = re.fullmatch(rb"\s*q\s+([\d.]+)\s+0\s+0\s+([\d.]+)\s+0\s+0\s+cm\s+/image\s+Do\s+Q\s*",stream.buf)
            if not match or not np.allclose([float(match[1]),float(match[2])],mb[2:],atol=1e-5):
                raise ValueError("page commands are not a single full-page image")
            dpi = [float(d[b"Width"])*72/mb[2],float(d[b"Height"])*72/mb[3]]
            if not np.allclose(dpi,[300,300],atol=.05):
                raise ValueError("ledger contract requires embedded 300 dpi pages")
            with Image.open(io.BytesIO(image.buf)) as im:
                if im.format != "JPEG" or im.size != (d[b"Width"],d[b"Height"]):
                    raise ValueError("embedded JPEG dimensions disagree")
                bgr = cv2.cvtColor(np.asarray(im.convert("RGB")),cv2.COLOR_RGB2BGR)
                encoding = {"qtables": [im.quantization[k] for k in sorted(im.quantization)],
                            "subsampling": JpegImagePlugin.get_sampling(im)}
            pages.append({"image": bgr, "dpi": dpi, "jpeg_sha256": hashlib.sha256(image.buf).hexdigest(),
                          "pixels_sha256": pixels_hash(bgr), "page_index": len(pages), "jpeg_encoding": encoding})
    finally:
        pdf.close()
    return pages


class _PDFRef(tuple):
    pass


class _PDFStream:
    def __init__(self, dictionary, buf):
        self.dictionary, self.buf = dictionary, buf


class _PDFReader:
    """Narrow classic-xref reader; never searches JPEG bytes for PDF objects."""
    def __init__(self, data: bytes):
        self.data, self.cache, self.reading = data, {}, set()
        end = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", data)
        if not data.startswith(b"%PDF-") or not end:
            raise ValueError("missing PDF header/trailer")
        pos = int(end[1])
        tok,pos = self.token(pos)
        if tok != b"xref":
            raise ValueError("only classic xref tables supported")
        self.xref = {}
        while True:
            tok,pos = self.token(pos)
            if tok == b"trailer":
                break
            first = int(tok)
            tok,pos = self.token(pos)
            count = int(tok)
            if first < 0 or count < 0 or count > len(data):
                raise ValueError("invalid xref subsection")
            for ident in range(first,first+count):
                offset,pos = self.token(pos)
                generation,pos = self.token(pos)
                state,pos = self.token(pos)
                if state == b"n":
                    self.xref[(ident,int(generation))] = int(offset)
                elif state != b"f":
                    raise ValueError("invalid xref entry")
        self.trailer,_ = self.value(pos)
        if b"Encrypt" in self.trailer or b"Prev" in self.trailer or b"XRefStm" in self.trailer:
            raise ValueError("encrypted/incremental/hybrid PDF unsupported")

    def skip(self, pos):
        while pos < len(self.data):
            if self.data[pos] in b"\x00\t\n\f\r ":
                pos += 1
            elif self.data[pos] == 37:
                end = re.compile(rb"[\r\n]").search(self.data,pos)
                pos = len(self.data) if end is None else end.end()
            else:
                break
        return pos

    def token(self, pos):
        pos = self.skip(pos)
        m = re.compile(rb"[^\x00\t\n\f\r ()<>\[\]{}/%]+").match(self.data,pos)
        if not m:
            raise ValueError("missing PDF token")
        return m[0],m.end()

    def value(self, pos, depth=0):
        if depth > 64:
            raise ValueError("PDF nesting too deep")
        pos = self.skip(pos)
        data = self.data
        if data[pos:pos+2] == b"<<":
            result,pos = {},pos+2
            while data[self.skip(pos):self.skip(pos)+2] != b">>":
                start = self.skip(pos)
                if data[start:start+1] != b"/":
                    raise ValueError("PDF dictionary key is not a name")
                key,pos = self.value(start,depth+1)
                if key in result:
                    raise ValueError("duplicate PDF dictionary key")
                result[key],pos = self.value(pos,depth+1)
            return result,self.skip(pos)+2
        if data[pos:pos+1] == b"[":
            result,pos = [],pos+1
            while data[self.skip(pos):self.skip(pos)+1] != b"]":
                val,pos = self.value(pos,depth+1)
                result.append(val)
            return result,self.skip(pos)+1
        if data[pos:pos+1] == b"/":
            m = re.compile(rb"[^\x00\t\n\f\r ()<>\[\]{}/%]*").match(data,pos+1)
            raw = m[0]
            return re.sub(rb"#([0-9a-fA-F]{2})",lambda v: bytes([int(v[1],16)]),raw),m.end()
        if data[pos:pos+1] == b"(":
            start,pos,nesting = pos,pos+1,1
            while nesting and pos < len(data):
                if data[pos] == 92:
                    pos += 2
                    continue
                nesting += (data[pos] == 40) - (data[pos] == 41)
                pos += 1
            if nesting:
                raise ValueError("unterminated PDF string")
            return data[start:pos],pos
        if data[pos:pos+1] == b"<":
            end = data.find(b">",pos+1)
            if end < 0:
                raise ValueError("unterminated PDF hex string")
            return data[pos:end+1],end+1
        ref = re.compile(rb"(\d+)\s+(\d+)\s+R(?=[\s\[\]<>/%]|$)").match(data,pos)
        if ref:
            return _PDFRef((int(ref[1]),int(ref[2]))),ref.end()
        tok,end = self.token(pos)
        if tok in (b"true",b"false",b"null"):
            return {b"true":True,b"false":False,b"null":None}[tok],end
        if not re.fullmatch(rb"[-+]?(?:\d+\.?\d*|\.\d+)",tok):
            raise ValueError("unsupported PDF value")
        return float(tok) if b"." in tok else int(tok),end

    def resolve(self, value):
        if not isinstance(value,_PDFRef):
            return value
        if value in self.cache:
            return self.cache[value]
        if value in self.reading:
            raise ValueError("cyclic PDF reference")
        self.reading.add(value)
        try:
            pos = self.xref[value]
            ident,pos = self.token(pos)
            generation,pos = self.token(pos)
            op,pos = self.token(pos)
            if (int(ident),int(generation)) != value or op != b"obj":
                raise ValueError("xref/object mismatch")
            obj,pos = self.value(pos)
            tok,end = self.token(pos)
            if tok == b"stream":
                if not isinstance(obj,dict) or self.data[end:end+1] not in (b"\r",b"\n"):
                    raise ValueError("invalid PDF stream")
                start = end+2 if self.data[end:end+2] == b"\r\n" else end+1
                length = self.resolve(obj[b"Length"])
                if not isinstance(length,int) or length < 0 or start+length > len(self.data):
                    raise ValueError("invalid PDF stream length")
                tok,pos = self.token(start+length)
                if tok != b"endstream":
                    raise ValueError("stream length/end disagree")
                obj = _PDFStream(obj,self.data[start:start+length])
                tok,end = self.token(pos)
            if tok != b"endobj":
                raise ValueError("missing PDF endobj")
            self.cache[value] = obj
            return obj
        finally:
            self.reading.remove(value)

    def pages(self):
        root = self.resolve(self.trailer[b"Root"])
        if root.get(b"Type") != b"Catalog":
            raise ValueError("root is not a catalog")
        seen = set()
        inherited_keys = (b"Resources",b"MediaBox",b"CropBox",b"TrimBox",b"Rotate")

        def walk(ref, inherited, depth=0):
            if depth > 64 or ref in seen:
                raise ValueError("cyclic/deep page tree")
            seen.add(ref)
            node = self.resolve(ref)
            effective = dict(inherited)
            effective.update({k:v for k,v in node.items() if k in inherited_keys})
            if node.get(b"Type") == b"Page":
                yield node,effective
            elif node.get(b"Type") == b"Pages":
                kids = self.resolve(node[b"Kids"])
                for kid in kids:
                    yield from walk(kid,effective,depth+1)
            else:
                raise ValueError("invalid page-tree node")
        yield from walk(root[b"Pages"],{})


def check_pdf_contract(path: Path | str) -> dict[str, Any]:
    """Check the staged lossless gray/RGB profile independently of the old JPEG decoder.

    Decode each Flate stream to validate its exact byte count and selected color
    profile. Pixel preservation against source/expected pages belongs to stages A/C.
    """
    pages,issues = [],[]
    try:
        pdf = _PDFReader(Path(path).read_bytes())
        for pi,(page,attrs) in enumerate(pdf.pages()):
            try:
                mb = np.asarray(pdf.resolve(attrs[b"MediaBox"]),float)
                if mb.shape != (4,) or not np.isfinite(mb).all() or not np.allclose(mb[:2],[0,0],atol=1e-6,rtol=0):
                    raise ValueError("MediaBox must start at zero")
                size = mb[2:]-mb[:2]
                # Exporter: 2480 x 3508 px at 300 dpi -> 595.2 x 841.92 pt.
                if not np.allclose(size,[595.28,841.89],atol=.5,rtol=0):
                    raise ValueError("MediaBox is not A4")
                for key in (b"CropBox",b"TrimBox"):
                    if key in attrs and not np.array_equal(np.asarray(pdf.resolve(attrs[key]),float),mb):
                        raise ValueError(f"{key.decode()} differs from MediaBox")
                if b"Rotate" in attrs or b"Annots" in page or page.get(b"UserUnit",1) != 1:
                    raise ValueError("rotation, annotation or UserUnit not allowed")
                resources = pdf.resolve(attrs[b"Resources"])
                if set(resources)-{b"ProcSet",b"XObject"}:
                    raise ValueError("unsupported page resources")
                xo = pdf.resolve(resources[b"XObject"])
                if len(xo) != 1 or b"Im" not in xo:
                    raise ValueError("expected exactly one /Im XObject")
                name,ref = next(iter(xo.items()))
                image = pdf.resolve(ref)
                if not isinstance(image,_PDFStream):
                    raise ValueError("image is not a stream")
                d = image.dictionary
                if (d.get(b"Type") != b"XObject" or d.get(b"Subtype") != b"Image"
                        or d.get(b"Filter") != b"FlateDecode" or d.get(b"BitsPerComponent") != 8
                        or d.get(b"ColorSpace") not in (b"DeviceGray",b"DeviceRGB")):
                    raise ValueError("expected 8-bit DeviceGray/DeviceRGB FlateDecode Image")
                if set(d)-{b"Type",b"Subtype",b"Filter",b"BitsPerComponent",b"ColorSpace",b"Width",b"Height",b"Length"}:
                    raise ValueError("image mask/decode/other modifiers not allowed")
                w,h = d[b"Width"],d[b"Height"]
                if type(w) is not int or type(h) is not int or min(w,h) <= 0:
                    raise ValueError("invalid image dimensions")
                dpi = np.asarray([w,h])*72/size
                if not np.allclose(dpi,[300,300],atol=.05,rtol=0):
                    raise ValueError("lossless profile requires embedded 300 dpi pages")
                profile = "gray" if d[b"ColorSpace"] == b"DeviceGray" else "rgb"
                expected_bytes = w*h*(1 if profile == "gray" else 3)
                decoder = zlib.decompressobj()
                raw = decoder.decompress(image.buf,expected_bytes+1)
                if (len(raw) != expected_bytes or not decoder.eof
                        or decoder.unused_data or decoder.unconsumed_tail):
                    raise ValueError("Flate pixels disagree with dimensions or stream termination")
                if profile == "rgb":
                    rgb = np.frombuffer(raw,np.uint8).reshape(h,w,3)
                    if int((rgb.max(axis=2)-rgb.min(axis=2)).max()) <= 24:
                        raise ValueError("near-gray page must use DeviceGray")
                stream = pdf.resolve(page[b"Contents"])
                if not isinstance(stream,_PDFStream):
                    raise ValueError("expected one content stream")
                cmd = stream.buf
                filt = stream.dictionary.get(b"Filter")
                if filt == b"FlateDecode":
                    cmd = zlib.decompress(cmd)
                elif filt is not None:
                    raise ValueError("unsupported content compression")
                if b"DecodeParms" in stream.dictionary:
                    raise ValueError("content DecodeParms not allowed")
                tokens = re.findall(rb"/[^\x00\t\n\f\r ()<>\[\]{}/%]+|[^\x00\t\n\f\r ()<>\[\]{}/%]+|[^\x00\t\n\f\r ]",cmd)
                if len(tokens) != 11 or tokens[0] != b"q" or tokens[7] != b"cm" or tokens[9:] != [b"Do",b"Q"]:
                    raise ValueError("content must be exactly q matrix cm /Im Do Q (no clip/other operators)")
                if tokens[8] != b"/Im":
                    raise ValueError("content XObject name mismatch")
                if any(not re.fullmatch(rb"[-+]?(?:\d+\.?\d*|\.\d+)",v) for v in tokens[1:7]):
                    raise ValueError("invalid content matrix numbers")
                matrix = np.asarray([float(v) for v in tokens[1:7]])
                if not np.allclose(matrix,[size[0],0,0,size[1],0,0],atol=1e-6,rtol=0) or np.any(matrix[[1,2,4,5]] != 0):
                    raise ValueError("image is not drawn full-page")
                pages.append({"page_index":pi,"media_box":mb.tolist(),"image_name":name.decode("ascii"),
                              "profile":profile,"width":w,"height":h,"dpi":dpi.tolist()})
            except (ValueError,KeyError,TypeError,AttributeError,zlib.error) as exc:
                issues.append({"code":"PDF_CONTRACT_VIOLATION","detail":str(exc),"page_index":pi})
        if not pages and not issues:
            raise ValueError("empty PDF page tree")
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,RecursionError) as exc:
        issues.append({"code":"PDF_CONTRACT_VIOLATION","detail":str(exc)})
    return {"status":"fail" if issues else "pass","pages":pages,"issues":issues}


def _local_match(page: np.ndarray, c: np.ndarray, mask: np.ndarray, origin: Sequence[int], *, core=None, context=None):
    """Clear mark coverage and shape, with only one residual output pixel of search."""
    core = _mark_core(mask) if core is None else core
    h,w = mask.shape
    best = None
    gray = _gray(page)
    for dy in range(-MARK_SEARCH,MARK_SEARCH+1):
        for dx in range(-MARK_SEARCH,MARK_SEARCH+1):
            x,y = origin[0]+dx,origin[1]+dy
            if x<0 or y<0 or x+w>gray.shape[1] or y+h>gray.shape[0]:
                continue
            a,b,e,f = max(0,x-2),max(0,y-2),min(gray.shape[1],x+w+2),min(gray.shape[0],y+h+2)
            paper = _percentile(gray[b:f,a:e],.9)
            actual = np.maximum(paper-gray[y:y+h,x:x+w].astype(float),0)
            ink = paper-gray[b:f,a:e].astype(float)>=C_PAGE
            shape = np.zeros(ink.shape,np.uint8)
            shape[y-b:y-b+h,x-a:x-a+w] = mask
            domain = cv2.dilate(shape,np.ones((5,5),np.uint8))>0
            projected = shape>0
            if context is not None:
                neighbours = context[b:f,a:e] & ~projected
                other = cv2.dilate(neighbours.astype(np.uint8),np.ones((3,3),np.uint8))>0
                ink &= ~other | projected
            cover = float((actual[core]>=C_PAGE).mean()) if core.any() else 0.
            # Adjacent, disconnected marks in the context window belong to their
            # own checks; only components intersecting this footprint affect IoU.
            n,labels = cv2.connectedComponents((ink & domain).astype(np.uint8),8)
            linked = np.unique(labels[projected & ink])
            shape_ink = np.isin(labels,linked[linked>0]) & ink & domain
            union = int((projected | shape_ink).sum())
            iou = float((projected & ink).sum())/max(1,union)
            tiny = int(core.sum())<3
            tiny_ok = bool(actual[core].max(initial=0)>=C_PAGE/2) if tiny else False
            ok = tiny_ok if tiny else cover>=COVER and iou>=IOU
            rank = (int(ok),cover+iou,-(dx*dx+dy*dy))
            if best is None or rank>best[0]:
                best = (rank,ok,cover,iou,x,y,actual)
    if best is None:
        return False,{"reason":"footprint_outside_page"},None
    _,ok,cover,iou,x,y,actual = best
    return ok,{"cover":cover,"iou":iou,"core_coverage":cover,"shape_coverage":iou,
        "offset":[x-origin[0],y-origin[1]],"tiny_core":int(core.sum())<3},(x,y,actual)


def _staff_only(item: dict[str, Any], rows: Sequence[float]) -> bool:
    mask = unpack_crop(item["foreground_hypothesis"])>0
    yy,xx = np.nonzero(mask)
    if not len(yy) or not rows:
        return False
    native_y = yy + item["display_bbox"][1]
    return bool(np.min(np.abs(native_y[:,None]-np.asarray(rows)[None,:]),axis=1).max() <= .6 and len(np.unique(xx))>=8)


def scaffold_source_column(ledger: dict, origin: dict, *, items: dict | None = None, resolver=None):
    """Independent raw, local five-staff proof across disjoint tiled hypotheses.

    The connected parent may include notes elsewhere. Only this declared source
    window is copied; it must have eight unchanged columns and exactly five raw
    horizontal bands. Duplicate hypothesis ownership and attached dots fail.
    """
    items = items or {i["id"]:i for i in ledger.get("items", [])}
    resolver = resolver or EvidenceResolver(ledger)
    refs = origin["source_item_refs"]
    if not refs or len({r["item_id"] for r in refs}) != len(refs):
        raise ValueError("scaffold requires distinct raw source references")
    a, b, e, f = map(int, origin["source_bbox_S"])
    if e-a < 8 or b >= f:
        raise ValueError("scaffold lacks an eight-column raw context")
    contrast, ownership = np.zeros((f-b, e-a), np.uint8), np.zeros((f-b, e-a), np.int32)
    paper = []
    for ref in refs:
        item = items[ref["item_id"]]
        if item.get("partition_of"):
            raise ValueError("scaffold must reference original raw hypotheses")
        matrix = _matrix(ref["display_to_strip"]).copy()
        matrix[:2,2] += matrix[:2,:2] @ np.asarray(item["display_bbox"][:2]) - [a, b]
        c = unpack_crop(item["expected_contrast"])
        mask = (unpack_crop(item["foreground_hypothesis"])>0) & (c>=C_CLEAR)
        # Qualify only the declared staff window, not notes on the connected parent.
        local = cv2.warpAffine(mask.astype(np.uint8),matrix[:2],(e-a,f-b),flags=cv2.INTER_NEAREST)>0
        witnesses = 0
        for ev in resolver._views(item,arrays=True):
            ec = ev.get("contrast_array")
            ec = unpack_crop(ev["contrast"]) if ec is None else ec
            free = ev.get("free_array")
            free = unpack_crop(ev["usable_mask"])>0 if free is None else free
            observed = cv2.warpAffine((ec>=C_CLEAR).astype(np.uint8),matrix[:2],(e-a,f-b),flags=cv2.INTER_NEAREST)>0
            visible = cv2.warpAffine(free.astype(np.uint8),matrix[:2],(e-a,f-b),flags=cv2.INTER_NEAREST)>0
            if local.any() and visible[local].all() and float(observed[local].mean())>=COVER:
                witnesses += 1
                if "display_patch" in ev:
                    paper.append(float(np.percentile(_gray(unpack_crop(ev["display_patch"])),90)))
                else:
                    paper.append(255.)
                if witnesses>=2:
                    break
        if not witnesses:
            raise ValueError("scaffold raw local staff has no clear witness")
        contrast = np.maximum(contrast,cv2.warpAffine(c,matrix[:2],(e-a,f-b),flags=cv2.INTER_LINEAR))
        ownership += local.astype(np.int32)
    active = contrast>=C_CLEAR
    if not active.any() or np.any(ownership[active] != 1):
        raise ValueError("scaffold raw hypotheses have a gap or competing ownership")
    if np.any(active != active[:, :1]):
        raise ValueError("scaffold source contains non-horizontal ink")
    yy = np.flatnonzero(active[:, 0])
    bands = [g for g in np.split(yy, np.flatnonzero(np.diff(yy)>1)+1) if len(g)]
    rows = [float(g.mean())+b for g in bands]
    supplied = origin["staff_rows_S"]
    if len(bands) != 5 or len(supplied) != 5 or not np.allclose(rows, supplied, atol=.6):
        raise ValueError("scaffold source does not contain the declared five staff rows")
    if max(len(g) for g in bands) >= np.diff(rows).min()/2:
        raise ValueError("scaffold source bands are not thin staff lines")
    # Reproduce the renderer's white-paper mapping from the raw witness, not
    # the production strip or its protected/cleaned masks.
    p = float(np.median(paper))
    if 170 < p < 254.5:
        contrast = 255-np.clip((p-contrast.astype(np.float32))*(255/p), 0, 255).astype(np.uint8)
        contrast[contrast <= 3] = 0
    c, _mask, where = _resize_evidence(contrast, active, [a, b], origin["source_resample"])
    col = int(origin["source_column_R"])-where[0]
    if not 0 <= col < c.shape[1]:
        raise ValueError("scaffold copied column outside its raw context")
    H = origin["source_resample"]["output_size"][1]
    column = np.zeros(H, np.uint8)
    column[where[1]:where[1]+c.shape[0]] = c[:, col]
    spec = origin["line_resample"]
    source_h = spec["source_size"][1]
    line = np.zeros((source_h, 1), np.uint8)
    y = int(origin["source_y_L"])
    r0, r1 = max(0, -y), min(H, source_h-y)
    line[y+r0:y+r1, 0] = column[r0:r1]
    method = cv2.INTER_AREA if spec["output_size"][0] < spec["source_size"][0] else cv2.INTER_CUBIC
    page_column = cv2.resize(line, (1, spec["output_size"][1]), interpolation=method)[:, 0]
    matrix = _matrix(origin["inputs"]["line_to_page"])
    page_y = int(round(matrix[1,2] - (matrix[1,1]-1)/2))
    start = origin["origin"][1]-page_y
    template = unpack_crop(origin["template"])
    return page_column[start:start+template.shape[0]]


def _source_limit_evidence(record: dict[str, Any]) -> bool:
    if record.get("reason") not in SOURCE_LIMIT_REASONS:
        return False
    fields = {"fade_transition":("paper_drop",), "registration_out_of_range":("shift_px",),
              "source_clipped":("clip_bbox","clipped_px"), "outside_requested_range":("t_sec",)}
    values = [record.get(k) for k in ("measured_value","measured",*fields[record["reason"]])]
    def measured(value):
        if isinstance(value,dict):
            return bool(value) and all(measured(v) for v in value.values())
        if isinstance(value,(list,tuple)):
            return bool(value) and all(measured(v) for v in value)
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    return any(measured(v) for v in values)


def _cursor_recovery(item: dict[str, Any], disposition: dict[str, Any], hypothesis: np.ndarray):
    recovery = disposition.get("recovery")
    if not isinstance(recovery,dict) or not recovery.get("recovered_mask"):
        return None
    witnesses = recovery.get("witnesses",[])
    if len(witnesses)<2 or len({w.get("observation_id") for w in witnesses})<2:
        return None
    evidence = {e["observation_id"]:e for e in item["evidence"]}
    positions = []
    for w in witnesses:
        ev = evidence.get(w.get("observation_id"))
        x,residual = w.get("cursor_x"),w.get("residual_registration_px")
        if ev is None or not ev.get("eligible") or not isinstance(x,(int,float)) or not isinstance(residual,(int,float)):
            return None
        if not math.isfinite(x) or not math.isfinite(residual) or not 0<=residual<=.5:
            return None
        positions.append(x)
    if max(positions)-min(positions)<=1:
        return None
    ev = evidence.get(disposition.get("clear_observation_id"))
    if ev is None or not ev.get("eligible") or ev["raw_patch"]["sha256"]!=disposition.get("raw_patch_sha256") or ev["observation_id"] not in {w["observation_id"] for w in witnesses}:
        return None
    # Round-2 lead decision: eligible underlay witnesses may be blank; they
    # need not support the cursor hypothesis (identity is not recovery).
    recovered = unpack_crop(recovery["recovered_mask"])>0
    if recovered.shape!=hypothesis.shape or np.any(recovered & ~hypothesis):
        raise ValueError("recovered mask lies outside raw hypothesis")
    return recovered



def verified_supersedes(ledger: dict):
    """Membership is a verified alias, never proof a member was used to compose."""
    displays = {d["id"]:d for d in ledger.get("displays",[])}
    aliases,errors = {},{}
    for d in ledger.get("display_dispositions",[]):
        if d.get("kind")!="superseded_inventory":
            continue
        did,rid = d.get("display_id"),d.get("retained_display_id")
        if (did not in displays or rid not in displays or not did.startswith("occ:") or
                not rid.startswith(("strip:","jump:")) or d.get("terminal")!="equivalent_observation"):
            errors[did] = "invalid supersede relationship"
            continue
        dropped = set(displays[did].get("observations",[]))-set(displays[rid].get("observations",[]))
        if dropped:
            errors[did] = sorted(dropped)
        elif did in aliases and aliases[did]!=rid:
            errors[did] = "multiple retained inventories"
            aliases.pop(did,None)
        else:
            aliases[did] = rid
    for did in errors:
        aliases.pop(did,None)
    return aliases,errors

def _encoded_reference(ledger: dict, pages: Sequence[np.ndarray], encodings: Sequence[dict] | None):
    """Predict block-phased JPEG from raw evidence, never from delivered pixels."""
    if encodings is None or not any(r["transforms"][1].get("pre_resample") for r in ledger.get("representations", [])):
        return None
    contrast = [np.zeros(p.shape[:2], np.uint8) for p in pages]
    items = {i["id"]:i for i in ledger.get("items", [])}
    displays = {d["id"]:d for d in ledger.get("displays", [])}
    raw_by_display = {}
    for item in items.values():
        if not item.get("partition_of"):
            raw_by_display.setdefault(item["display_id"], []).append(item)
    contexts, seen = OrderedDict(), set()
    for rep in ledger.get("representations", []):
        try:
            item = items[rep["item_id"]]
            key = (item["display_id"], rep["page_index"], json.dumps(rep["transforms"], sort_keys=True))
            if key in seen:
                continue
            if rep["transforms"][1].get("pre_resample"):
                did = item["display_id"]
                if did not in contexts:
                    shape = displays[did]["shape"]
                    canvas = np.zeros(shape, np.uint8)
                    papers = []
                    for parent in raw_by_display[did]:
                        a,b,e,f = parent["display_bbox"]
                        sl = np.s_[b:f,a:e]
                        canvas[sl] = np.maximum(canvas[sl], unpack_crop(parent["expected_contrast"]))
                        papers.append(parent.get("projection_context", {}).get("paper_level", 255))
                    contexts[did] = {"display_bbox": [0,0,shape[1],shape[0]], "contrast_array": canvas,
                                     "paper_level": float(np.median(papers))}
                    while len(contexts) > 2:
                        contexts.popitem(last=False)
                contexts.move_to_end(did)
                c, _mask, origin = _project_raster_item(dict(item, _projection_context=contexts[did]), rep["transforms"],
                                                       reference=True, allow_empty=True)
            else:
                c, _mask, origin = project_item(item, rep["transforms"])
            x, y = origin
            canvas = contrast[rep["page_index"]]
            if x < 0 or y < 0 or x+c.shape[1] > canvas.shape[1] or y+c.shape[0] > canvas.shape[0]:
                continue
            sl = np.s_[y:y+c.shape[0], x:x+c.shape[1]]
            canvas[sl] = np.maximum(canvas[sl], c)
            seen.add(key)
        except (ValueError, KeyError, TypeError, cv2.error):
            continue  # The ordinary source check reports unsupported/lost evidence.
    for rec in ledger.get("generated_origins", []):
        try:
            template = unpack_crop(rec["template"])
            c = _contrast(template)
            x, y = rec["origin"]
            sl = np.s_[y:y+c.shape[0], x:x+c.shape[1]]
            canvas = contrast[rec["page_index"]]
            canvas[sl] = np.maximum(canvas[sl], c)
        except (ValueError, KeyError, TypeError, cv2.error):
            continue  # Generated provenance is still checked independently below.
    encoded = []
    for canvas, encoding in zip(contrast, encodings):
        stream = io.BytesIO()
        rgb = Image.fromarray(255-canvas).convert("RGB")
        rgb.save(stream, "JPEG", qtables=encoding["qtables"], subsampling=encoding["subsampling"])
        rgb.close()
        with Image.open(io.BytesIO(stream.getvalue())) as image:
            encoded.append(255-np.asarray(image.convert("L")))
    return encoded


def qualify_marks(ledger: dict, resolver=None) -> dict:
    """Batch raw members once per display; compact results contain no fringe arrays."""
    resolver = resolver or EvidenceResolver(ledger)
    groups,result = {},{}
    for item in ledger.get("items",[]):
        if item.get("partitioned_into"):
            continue
        groups.setdefault(item["display_id"],[]).append(item)
    for group in groups.values():
        for start in range(0,len(group),256):
            batch = group[start:start+256]
            masks = {i["id"]:mark_masks(i) for i in batch}
            for item in batch:
                result[item["id"]] = {"marks":[{"eligible":0,"supporting":0} for _ in masks[item["id"]]],"good":[]}
            members = resolver.members(batch[0])
            rounds = [m["index"] for m in members] if members else [None]
            for index in rounds:
                for item in batch:
                    ident = item["id"]
                    if not masks[ident]:
                        continue
                    try:
                        views = resolver._views(item,member_index=index,arrays=True)
                        for view in views:
                            c = view.get("contrast_array")
                            c = unpack_crop(view["contrast"]) if c is None else c
                            free = view.get("free_array")
                            free = unpack_crop(view["usable_mask"])>0 if free is None else free
                            padded = np.pad(c>=C_CLEAR,1)
                            supported = False
                            for k,(b,_mask,core) in enumerate(masks[ident]):
                                x,y,e,f = b
                                if not free[y:f,x:e][core].all():
                                    continue
                                count = result[ident]["marks"][k]
                                count["eligible"] += 1
                                cover = max(float(padded[y+1+dy:f+1+dy,x+1+dx:e+1+dx][core].mean())
                                    for dy in (-1,0,1) for dx in (-1,0,1))
                                if cover>=COVER:
                                    count["supporting"] += 1
                                    supported = True
                            if supported:
                                result[ident]["good"].append({"observation_id":view["observation_id"],"transform":view["transform"]})
                    except EvidenceUnavailableError as exc:
                        result[ident]["error"] = str(exc)
            for item in batch:
                for count in result[item["id"]]["marks"]:
                    count["minority"] = count["supporting"]==1
    return result


def verify_pages(ledger: dict[str, Any], pages: Sequence[np.ndarray], *, encodings: Sequence[dict] | None = None) -> dict[str, Any]:
    """Check raw obligations and actual delivered pixels, independent of flags."""
    if ledger.get("transform_chains"):
        ledger = dict(ledger,representations=[dict(r,transforms=ledger["transform_chains"][r["transform_ref"]])
            if "transform_ref" in r else r for r in ledger.get("representations",[])])
    issues,matches,accounting = [],[],[]
    unassessed_pages = set(range(len(pages))) if not ledger.get("items") or not ledger.get("displays") or not ledger.get("observations") or ledger.get("version")=="display-ledger-1" else set()
    resolver = EvidenceResolver(ledger)
    encoded_reference = None
    projections = {}
    placement_offsets = _placement_offsets(ledger,pages,projections)
    qualifications = qualify_marks(ledger,resolver)
    unresolved_obs = {o["id"] for o in ledger.get("observations", []) if o.get("terminal") == "unresolved"}
    raw_hashes_by_observation = {ident: set() for ident in unresolved_obs}
    source = [np.zeros(p.shape[:2],bool) for p in pages]
    source_items = {i["id"]:i for i in ledger.get("items",[])}
    for rep in ledger.get("representations",[]):
        if rep.get("projection_error"):
            continue
        item = source_items.get(rep["item_id"])
        if item is None:
            continue
        pi = rep["page_index"]
        key = (pi,rep.get("line_id",item["display_id"]),rep["copy_index"])
        for mi,(b,mark,_) in enumerate(mark_masks(item)):
            try:
                if (id(rep),mi) not in projections:
                    continue
                c,m,o,_core = projections[(id(rep),mi)]
                x,y = np.asarray(o)+placement_offsets.get(key,[0,0])
                if 0<=pi<len(pages) and 0<=x and 0<=y and x+m.shape[1]<=pages[pi].shape[1] and y+m.shape[0]<=pages[pi].shape[0]:
                    source[pi][y:y+m.shape[0],x:x+m.shape[1]] |= m
            except (ValueError,KeyError,cv2.error):
                pass
    generated = [np.zeros(p.shape[:2],bool) for p in pages]
    owners = [np.full(p.shape[:2],-1,np.int32) for p in pages]
    tokens = {}
    items = {i["id"]:i for i in ledger.get("items",[])}
    displays = {d["id"]:d for d in ledger.get("displays",[])}
    dispositions = {d["item_id"]:d for d in ledger.get("dispositions",[])}
    user_excluded = {d.get("display_id") for d in ledger.get("display_dispositions",[])
                     if d.get("kind")=="user_excluded" and isinstance(d.get("system_id"),str) and d["system_id"]
                     and "terminal" in d and d["terminal"] is None}
    excluded_items = {i["id"] for i in items.values() if i["display_id"] in user_excluded}
    reps_by_item,items_by_display,items_by_observation = {},{},{}
    for r in ledger.get("representations",[]):
        reps_by_item.setdefault(r.get("item_id"),[]).append(r)
    for item in items.values():
        items_by_display.setdefault(item["display_id"],[]).append(item)
        for ident in resolver.observation_ids(item):
            items_by_observation.setdefault(ident,[]).append(item)
    masks,exempt,partitioned,recovered_items = {},{},{},set()
    unassessed_items = set()
    display_checks = []
    terminal_counts = {"observations":dict.fromkeys(TERMINALS,0),"items":dict.fromkeys(TERMINALS,0)}

    def issue(severity,code,item=None,**facts):
        rec = {"severity":severity,"code":code,**facts}
        if item is not None:
            rec["item_id"] = item["id"]
            try:
                ev = next(resolver.views(item),None)
                rec["source_crop"] = ev["raw_patch"] if ev else item.get("expected_contrast")
            except (ValueError,KeyError,TypeError,IndexError,StopIteration,cv2.error):
                rec["source_crop"] = item.get("expected_contrast")
        issues.append(rec)

    def hypothesis(item):
        if item["id"] not in masks:
            mask = unpack_crop(item["foreground_hypothesis"])>0
            x0,y0,x1,y1 = item["display_bbox"]
            if mask.shape!=(y1-y0,x1-x0) or not mask.any():
                raise ValueError("hypothesis shape/bbox disagreement or empty hypothesis")
            masks[item["id"]] = mask
        return masks[item["id"]]

    if not pages:
        issue("fail","EMPTY_DELIVERED_OUTPUT")
    if ledger.get("version") not in (VERSION,"display-ledger-1"):
        issue("review_required","LEDGER_SCHEMA_UNASSESSED")
    if not items or not displays:
        issue("review_required","PRE_CLEANUP_OBLIGATIONS_MISSING")
    if len(items)!=len(ledger.get("items",[])) or len(displays)!=len(ledger.get("displays",[])) or len(dispositions)!=len(ledger.get("dispositions",[])):
        issue("fail","DUPLICATE_EVIDENCE_ID")
    for d in ledger.get("dispositions",[]):
        if d["item_id"] in excluded_items:
            continue
        expected = DISPOSITION_TERMINAL.get(d.get("kind"))
        if "terminal" not in d or d["terminal"] is None:
            issue("review_required","TERMINAL_EVIDENCE_MISSING",items.get(d["item_id"]),kind=d.get("kind"))
        elif expected is None or d["terminal"]!=expected:
            issue("fail","INVALID_EVIDENCE_OR_DISPOSITION",items.get(d["item_id"]),detail="disposition terminal does not match kind")
        if d["item_id"] not in items:
            issue("fail","INVALID_EVIDENCE_OR_DISPOSITION",detail="disposition item missing")
    superseded,_ = verified_supersedes(ledger)
    display_dispositions = [d for d in ledger.get("display_dispositions",[]) if not (d.get("kind")=="display_unresolved" and d.get("display_id") in superseded)]
    for display in displays.values():
        if display["id"] in user_excluded:
            continue
        if display.get("raw_foreground_uninventoried_px",0):
            issue("review_required","RAW_FOREGROUND_INVENTORY_INCOMPLETE",display_id=display["id"],pixels=display["raw_foreground_uninventoried_px"])
        if not items_by_display.get(display["id"]) and display["id"] not in superseded:
            issue("review_required","DISPLAY_WITHOUT_FOREGROUND_EVIDENCE",display_id=display["id"])

    retained_masks = {}
    for d in display_dispositions:
        did,kind = d.get("display_id"),d.get("kind")
        try:
            display = displays[did]
            group = items_by_display.get(did,[])
            if kind=="user_excluded":
                if did not in user_excluded or any(reps_by_item.get(i["id"]) for i in group):
                    raise ValueError("user exclusion requires a system id and no delivered placements")
                continue
            expected = "unresolved" if kind=="display_unresolved" else "equivalent_observation"
            if d.get("terminal") is None:
                issue("review_required","TERMINAL_EVIDENCE_MISSING",display_id=did)
            elif d["terminal"]!=expected:
                raise ValueError("display terminal does not match kind")
            if kind=="display_unresolved":
                if not d.get("reason"):
                    issue("review_required","TERMINAL_EVIDENCE_MISSING",display_id=did)
                issue("review_required","DISPLAY_UNRESOLVED",display_id=did,reason=d.get("reason"))
                exempt.update({i["id"]:"unresolved" for i in group})
                continue
            retained = displays[d["retained_display_id"]]
            if retained["id"]==did:
                raise ValueError("display cannot supersede/equate itself")
            if kind=="superseded_inventory":
                if not did.startswith("occ:") or not retained["id"].startswith(("strip:","jump:")):
                    raise ValueError("superseded inventory requires occ -> strip/jump")
                dropped = sorted(set(display.get("observations",[]))-set(retained.get("observations",[])))
                if dropped:
                    issue("fail","INVENTORY_MEMBER_DROPPED",display_id=did,observation_ids=dropped)
                exempt.update({i["id"]:"equivalent_observation" for i in group})
                continue
            if kind!="display_equivalent":
                raise ValueError("unknown display disposition")
            matrix = _matrix(d["equivalence_map"])
            uncertainty = float(d["registration_uncertainty"])
            if not math.isfinite(uncertainty) or uncertainty<0 or not d.get("evidence",{}).get("method"):
                raise ValueError("display equivalence lacks measured evidence")
            radius = max(1,math.ceil(uncertainty))
            cache_key = (retained["id"],radius)
            if cache_key not in retained_masks:
                shape = tuple(retained["shape"])
                raw = np.zeros(shape,np.uint8)
                for owner in items_by_display.get(retained["id"],[]):
                    mask = hypothesis(owner)
                    x0,y0,x1,y1 = owner["display_bbox"]
                    if not 0<=x0<x1<=shape[1] or not 0<=y0<y1<=shape[0]:
                        raise ValueError("retained item outside display")
                    raw[y0:y1,x0:x1] |= mask.astype(np.uint8)
                retained_masks[cache_key] = cv2.dilate(raw,np.ones((2*radius+1,2*radius+1),np.uint8))>0
            raw = retained_masks[cache_key]
            region = d.get("region")
            if region is not None and (len(region)!=4 or not all(math.isfinite(v) for v in region) or region[0]>=region[2] or region[1]>=region[3]):
                raise ValueError("invalid equivalence region")
            for item in group:
                x0,y0,x1,y1 = item["display_bbox"]
                if region is not None:
                    rx0,ry0,rx1,ry1 = region
                    if not (rx0<=x0 and ry0<=y0 and x1<=rx1 and y1<=ry1):
                        if x0<rx1 and x1>rx0 and y0<ry1 and y1>ry0:
                            issue("review_required","EQUIVALENCE_REGION_SPLITS_ITEM",item,region=region)
                        continue
                mask = hypothesis(item)
                yy,xx = np.nonzero(mask)
                projected = np.column_stack((xx+x0,yy+y0,np.ones(len(xx)))) @ matrix.T
                points = np.rint(projected[:,:2]).astype(np.int64)
                inside = (points[:,0]>=0)&(points[:,1]>=0)&(points[:,0]<raw.shape[1])&(points[:,1]<raw.shape[0])
                covered = np.zeros(len(xx),bool)
                covered[inside] = raw[points[inside,1],points[inside,0]]
                if not covered.all():
                    ev = next(resolver.views(item))
                    patch = unpack_crop(ev["raw_patch"])
                    # Locate mismatch in the raw native patch through its recorded map.
                    native = np.column_stack((xx[~covered]+x0,yy[~covered]+y0,np.ones(int((~covered).sum())))) @ np.linalg.inv(_matrix(ev["transform"]["matrix"])).T
                    nx,ny = ev["native_bbox"][:2]
                    px,py = np.rint(native[0,:2]-[nx,ny]).astype(int)
                    px,py = max(0,min(px,patch.shape[1]-1)),max(0,min(py,patch.shape[0]-1))
                    crop = patch[max(0,py-2):min(patch.shape[0],py+94),max(0,px-2):min(patch.shape[1],px+94)]
                    issue("fail","EQUIVALENCE_CONTAINMENT_FAILED",item,retained_display_id=retained["id"],pixels=int((~covered).sum()),mismatch_crop=pack_crop(crop))
                exempt[item["id"]] = "equivalent_observation"
            display_checks.append(d)
        except EvidenceUnavailableError as exc:
            unassessed_pages.update(range(len(pages)))
            issue("review_required","EVIDENCE_UNAVAILABLE",display_id=did,detail=str(exc))
        except (ValueError,KeyError,TypeError,IndexError,StopIteration,cv2.error,np.linalg.LinAlgError) as exc:
            issue("fail","INVALID_EVIDENCE_OR_DISPOSITION",display_id=did,detail=str(exc))

    for parent in items.values():
        if parent["id"] in excluded_items:
            continue
        if "partitioned_into" not in parent:
            continue
        partitioned[parent["id"]] = parent["partitioned_into"]
        try:
            mask = hypothesis(parent)
            count = np.zeros(mask.shape,np.int32)
            x0,y0,x1,y1 = parent["display_bbox"]
            ids = parent["partitioned_into"]
            if not ids or len(ids)!=len(set(ids)) or reps_by_item.get(parent["id"]):
                raise ValueError("partition parent has representations/invalid children")
            for ident in ids:
                child = items[ident]
                if child.get("partition_of")!=parent["id"] or child["display_id"]!=parent["display_id"] or child["occurrence_id"]!=parent["occurrence_id"]:
                    raise ValueError("partition child identity mismatch")
                yy,xx = np.nonzero(hypothesis(child))
                xx,yy = xx+child["display_bbox"][0]-x0,yy+child["display_bbox"][1]-y0
                if np.any((xx<0)|(yy<0)|(xx>=mask.shape[1])|(yy>=mask.shape[0])):
                    raise ValueError("child foreground outside parent")
                count[yy,xx] += 1
            if not np.array_equal(count,mask.astype(np.int32)):
                raise ValueError("partition union has gap, extra pixels or overlap")
        except (ValueError,KeyError,TypeError,IndexError,cv2.error) as exc:
            issue("fail","PARTITION_MISMATCH",parent,detail=str(exc))

    for item in items.values():
        if item["id"] in excluded_items:
            continue
        try:
            if item["id"] in exempt or item["id"] in partitioned:
                continue
            q = qualifications.get(item["id"],{})
            if q.get("error"):
                raise EvidenceUnavailableError(q["error"])
            clear_marks = mark_masks(item)
            if not clear_marks:
                matches.append({"item_id":item["id"],"kind":"faint_only","reason":"no_source_pixel_at_C_CLEAR"})
                continue
            d = dispositions.get(item["id"])
            item = dict(item,evidence=list(resolver.views(item)) if d else [])
            for ev in item["evidence"]:
                if ev["observation_id"] in raw_hashes_by_observation:
                    raw_hashes_by_observation[ev["observation_id"]].add(ev["raw_patch"]["sha256"])
            mask = hypothesis(item)
            contrast = unpack_crop(item["expected_contrast"])
            if contrast.shape!=mask.shape:
                raise ValueError("contrast/hypothesis shape mismatch")
            for e in item["evidence"]:
                unpack_crop(e["raw_patch"])
                unpack_crop(e["contrast"])
            d = dispositions.get(item["id"])
            ir = reps_by_item.get(item["id"],[])
            cls = item["class"]
            if cls not in ("protected","credible-few","ambiguous"):
                raise ValueError("unknown evidence class")
            if item["id"] in exempt or item["id"] in partitioned:
                if ir:
                    raise ValueError("excluded/partition parent unexpectedly represented")
                continue
            if d:
                kind = d.get("kind")
                if d.get("terminal") is not None and d["terminal"]!=DISPOSITION_TERMINAL.get(kind):
                    raise ValueError("disposition terminal does not match kind")
                if kind=="unresolved_alternative":
                    if not d.get("review_artifact") or not d.get("observation_id"):
                        issue("review_required","TERMINAL_EVIDENCE_MISSING",item)
                    else:
                        path = Path(d["review_artifact"])
                        im = cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                        ev = next(e for e in item["evidence"] if e["observation_id"]==d["observation_id"])
                        if im is None or pixels_hash(im)!=ev["raw_patch"]["sha256"]:
                            raise ValueError("review artifact does not contain raw alternative")
                        issue("review_required","UNRESOLVED_ALTERNATIVE",item,artifact=str(path))
                    if not ir:
                        continue
                elif kind=="overlap_duplicate":
                    if not d.get("retained_item_id") or not d.get("equivalence"):
                        issue("review_required","TERMINAL_EVIDENCE_MISSING",item)
                        continue
                    owner = items[d["retained_item_id"]]
                    if owner["occurrence_id"]!=item["occurrence_id"] or d.get("equivalence")!="same_written_occurrence":
                        raise ValueError("overlap explanation merges distinct occurrences")
                    ir = [dict(r,item_id=item["id"]) for r in reps_by_item.get(owner["id"],[])]
                    if owner["display_bbox"]!=item["display_bbox"]:
                        raise ValueError("overlap requires equal display coordinates in v1")
                elif kind=="staff_scaffold":
                    if not all(k in d for k in ("staff_rows_display","retained_item_id","retained_staff_rows_display")):
                        issue("review_required","TERMINAL_EVIDENCE_MISSING",item)
                        continue
                    if not _staff_only(item,d["staff_rows_display"]):
                        raise ValueError("scaffold geometry intersects non-staff mark")
                    owner = items[d["retained_item_id"]]
                    if not _staff_only(owner,d["retained_staff_rows_display"]):
                        raise ValueError("retained scaffold evidence is not staff")
                    ir = [dict(r,item_id=item["id"]) for r in reps_by_item.get(owner["id"],[])]
                    if not ir:
                        issue("fail","PRESERVED_NOT_DELIVERED",item)
                    if item["display_bbox"]!=owner["display_bbox"]:
                        issue("review_required","SCAFFOLD_RELOCATION_NEEDS_MAP",item)
                        continue
                elif kind=="cursor_recovery":
                    recovered = _cursor_recovery(item,d,mask)
                    if recovered is None:
                        issue("review_required","CURSOR_RECOVERY_INSUFFICIENT",item)
                    elif np.array_equal(recovered,mask):
                        recovered_items.add(item["id"])
                        if ir:
                            issue("fail","OVERLAY_DELIVERED",item)
                        continue
                    else:
                        mask = mask & ~recovered
                        issue("review_required","PARTIAL_RECOVERY_REMAINDER",item,pixels=int(mask.sum()))
                        item = dict(item,foreground_hypothesis=pack_crop(mask.astype(np.uint8)*255))
                elif kind in ("chrome","preview_inset","structural_replacement"):
                    if not d.get("exclusion_mask"):
                        issue("review_required","TERMINAL_EVIDENCE_MISSING",item)
                    else:
                        exclusion = unpack_crop(d["exclusion_mask"])>0
                        if exclusion.shape!=mask.shape or np.any(exclusion & mask):
                            raise ValueError("exemption intersects raw foreground hypothesis")
                        issue("review_required","SEMANTIC_EXEMPTION_UNPROVEN",item,kind=kind)
                elif kind=="source_limited":
                    if not _source_limit_evidence(d):
                        issue("review_required","TERMINAL_EVIDENCE_MISSING",item)
                    issue("review_required","SOURCE_LIMITED",item,reason=d.get("reason"))
                    if not ir:
                        continue
                else:
                    raise ValueError("category without supported evidence disposition")
            supported = bool(q.get("marks")) and all(m["supporting"]>=1 for m in q["marks"])
            cls = "protected" if q.get("marks") and all(m["supporting"]>=2 for m in q["marks"]) else "credible-few" if supported else "ambiguous"
            if cls=="ambiguous":
                issue("review_required","AMBIGUOUS_EVIDENCE",item,disposition_recorded=bool(d),marks=q.get("marks",[]))
            good = q.get("good",[])
            unknown = not good or any(any(e["transform"].get(k) is None for k in ("roi_origin","registration_shift","registration_uncertainty")) for e in good)
            uncertain = any(float(e["transform"].get("registration_uncertainty") or 0)>.5 for e in good)
            if unknown or uncertain:
                unassessed_items.add(item["id"])
                issue("review_required","REGISTRATION_UNRESOLVED",item)
            keys = [(r.get("occurrence_id"),r.get("copy_index")) for r in ir]
            if len(ir)!=item["expected_multiplicity"] or len(set(keys))!=len(keys):
                issue("fail" if cls!="ambiguous" else "review_required","OUTPUT_MULTIPLICITY_MISMATCH",item,expected=item["expected_multiplicity"],actual=len(ir))
            for r in ir:
                if r.get("occurrence_id")!=item["occurrence_id"] or not isinstance(r.get("copy_index"),int) or not 0<=r["copy_index"]<item["expected_multiplicity"]:
                    raise ValueError("representation occurrence/copy mismatch")
                pi = r["page_index"]
                if not isinstance(pi,int) or not 0<=pi<len(pages):
                    raise ValueError("representation references absent page")
                if unknown or uncertain:
                    unassessed_pages.add(pi)
                if r.get("below_contrast_floor"):
                    proof = below_contrast_floor(item, r["transforms"])
                    if proof is None or proof != r["below_contrast_floor"]:
                        raise ValueError("below_contrast_floor lacks independent raw/resampling proof")
                    matches.append({"item_id": item["id"], "occurrence_id": item["occurrence_id"],
                                    "copy_index": r["copy_index"], "page_index": pi, "kind": "below_contrast_floor", "evidence": proof})
                    continue
                if r.get("projection_error"):
                    error = r["projection_error"]
                    if error["code"] not in ("TRANSFORM_DROPS_OR_DUPLICATES_FOREGROUND", "TRANSFORM_UNRESOLVED"):
                        raise ValueError("unknown assembly projection error")
                    unresolved = error["code"] == "TRANSFORM_UNRESOLVED"
                    if unresolved:
                        unassessed_items.add(item["id"])
                        unassessed_pages.add(pi)
                    issue("review_required" if unresolved else "fail", error["code"], item,
                          page_index=pi, detail=error["detail"])
                    continue
                key = (pi,r.get("line_id",item["display_id"]),r["copy_index"])
                offset = placement_offsets.get(key,[0,0])
                if max(abs(v) for v in offset)>1:
                    issue("fail","PLACEMENT_MISMATCH",item,page_index=pi,offset=offset)
                all_ok = True
                metrics_list = []
                for mi,(b,mark,core) in enumerate(clear_marks):
                    try:
                        if (id(r),mi) in projections:
                            c,projected,origin,projected_core = projections[(id(r),mi)]
                        else:
                            c,projected,origin = _project_mark(item,r["transforms"],b,mark)
                            _,pc,co = _project_mark(item,r["transforms"],b,core)
                            projected_core = np.zeros(projected.shape,bool)
                            cx,cy = np.asarray(co)-origin
                            projected_core[cy:cy+pc.shape[0],cx:cx+pc.shape[1]] = pc
                            if not projected_core.any(): projected_core = projected
                    except TransformLossError as exc:
                        issue("fail","TRANSFORM_DROPS_OR_DUPLICATES_FOREGROUND",item,detail=str(exc))
                        all_ok = False
                        continue
                    except ValueError as exc:
                        unassessed_items.add(item["id"])
                        unassessed_pages.add(pi)
                        issue("review_required","TRANSFORM_UNRESOLVED",item,detail=str(exc))
                        all_ok = False
                        continue
                    origin = (np.asarray(origin)+offset).tolist()
                    ok,metrics,actual = _local_match(pages[pi],c,projected,origin,core=projected_core,context=source[pi])
                    metrics["placement_offset"] = offset
                    metrics_list.append(metrics)
                    # Reverse accounting uses the projected mark, independent of forward success.
                    x,y = origin
                    if 0<=x and 0<=y and x+c.shape[1]<=pages[pi].shape[1] and y+c.shape[0]<=pages[pi].shape[0]:
                        source[pi][y:y+c.shape[0],x:x+c.shape[1]] |= projected
                    if not ok:
                        facts = {"page_index":pi,"predicted_origin":origin,"mark_index":mi,"metrics":metrics}
                        if actual:
                            x,y,_ = actual
                            crop = pages[pi][y:y+c.shape[0],x:x+c.shape[1]]
                            if max(crop.shape[:2])>96:
                                crop = cv2.resize(crop,None,fx=96/max(crop.shape[:2]),fy=96/max(crop.shape[:2]),interpolation=cv2.INTER_AREA)
                            facts["output_crop"] = pack_crop(crop)
                        issue("review_required" if unknown or uncertain or cls=="ambiguous" else "fail","SOURCE_FOREGROUND_MISSING_OR_CHANGED",item,**facts)
                        all_ok = False
                        continue
                    x,y,a = actual
                    # Cores avoid shared resampling lobes at replica/measure edges.
                    present = projected_core & (a>=C_PAGE/2)
                    token = (item["occurrence_id"],r["copy_index"])
                    token_id = tokens.setdefault(token,len(tokens))
                    owned = owners[pi][y:y+c.shape[0],x:x+c.shape[1]]
                    if np.any(present & (owned>=0) & (owned!=token_id)):
                        issue("fail","OUTPUT_PATCH_REUSED_BY_DISTINCT_OCCURRENCES",item,page_index=pi,mark_index=mi)
                    owned[present] = token_id
                if all_ok:
                    matches.append({"item_id":item["id"],"occurrence_id":item["occurrence_id"],"copy_index":r["copy_index"],
                        "page_index":pi,"metrics":metrics_list,"mark_support":q.get("marks",[])})
        except EvidenceUnavailableError as exc:
            unassessed_items.add(item["id"])
            unassessed_pages.update(range(len(pages)))
            issue("review_required","EVIDENCE_UNAVAILABLE",item,detail=str(exc))
        except (ValueError,KeyError,TypeError,IndexError,StopIteration,cv2.error) as exc:
            issue("fail","INVALID_EVIDENCE_OR_DISPOSITION",item,detail=str(exc))

    matched = {m["item_id"] for m in matches}
    matched_displays = {items[m["item_id"]]["display_id"] for m in matches if m.get("kind")!="faint_only"}
    for d in display_checks:
        if d["retained_display_id"] not in matched_displays:
            unassessed = any(i["id"] in unassessed_items for i in items_by_display.get(d["retained_display_id"],[]))
            issue("review_required" if unassessed else "fail","PRESERVED_NOT_DELIVERED",display_id=d["retained_display_id"],excluded_display_id=d["display_id"])
    dispositioned_displays = {d.get("display_id") for d in ledger.get("display_dispositions",[])}
    for display in displays.values():
        group = items_by_display.get(display["id"],[])
        if group and not any(reps_by_item.get(i["id"]) for i in group) and display["id"] not in dispositioned_displays and not any(i["id"] in dispositions for i in group):
            issue("review_required","DISPLAY_UNACCOUNTED",display_id=display["id"])
    for item in items.values():
        if item["id"] in excluded_items:
            continue
        d = dispositions.get(item["id"])
        if item["id"] in exempt:
            terminal = exempt[item["id"]]
        elif item["id"] in partitioned:
            children = partitioned[item["id"]]
            terminal = "preserved" if children and all(c in matched or c in recovered_items for c in children) else "unresolved"
        elif d:
            terminal = d.get("terminal")
            if terminal=="preserved" and item["id"] not in matched:
                issue("review_required" if item["id"] in unassessed_items else "fail","PRESERVED_NOT_DELIVERED",item)
        else:
            terminal = "preserved" if item["id"] in matched else "unresolved"
        if terminal not in TERMINALS:
            terminal = "unresolved"
        if terminal in TERMINALS:
            terminal_counts["items"][terminal] += 1

    observations = ledger.get("observations",[])
    if ledger.get("version")=="display-ledger-1" or not observations:
        issue("review_required","OBSERVATION_INVENTORY_MISSING")
    if len({o["id"] for o in observations})!=len(observations):
        issue("fail","DUPLICATE_EVIDENCE_ID",detail="observation ids repeat")
    for obs in observations:
        ident,terminal = obs.get("id"),obs.get("terminal")
        linked = items_by_observation.get(ident,[])
        associations = obs.get("associations",[])
        associated = {a["display_id"] for a in associations if a.get("display_id")}
        if (linked and all(i["id"] in excluded_items for i in linked) and associated <= user_excluded) or (
                not linked and associated and associated <= user_excluded):
            continue
        if terminal not in TERMINALS:
            issue("review_required","OBSERVATION_WITHOUT_TERMINAL",observation_id=ident)
            continue
        terminal_counts["observations"][terminal] += 1
        evidence = dict(obs)
        if isinstance(obs.get("evidence"),dict):
            evidence.update(obs["evidence"])
        associations = obs.get("associations",[])
        linked = [i for i in items_by_observation.get(ident,[]) if i["id"] not in excluded_items]
        faint_only = bool(linked) and all(not mark_masks(i) for i in linked if not i.get("partitioned_into"))
        delivered = faint_only or any(a.get("role") in ("used","member") and superseded.get(a.get("display_id"),a.get("display_id")) in matched_displays for a in associations)
        if terminal=="preserved":
            if not delivered:
                unassessed = any(i["id"] in unassessed_items for i in linked)
                issue("review_required" if unassessed else "fail","PRESERVED_NOT_DELIVERED",observation_id=ident)
        elif terminal=="non_score_material":
            if obs.get("staff_regions")!=0 or not isinstance(evidence.get("detector_version"),str) or not evidence["detector_version"] or not obs.get("pixels_sha256") or any(a.get("role") in ("member","used","offered") for a in associations):
                issue("review_required","TERMINAL_EVIDENCE_MISSING",observation_id=ident)
        elif terminal=="recovered_beneath_overlay":
            if not linked or not all(i["id"] in recovered_items or i["id"] in matched for i in linked) or not any(i["id"] in recovered_items for i in linked):
                issue("review_required","TERMINAL_EVIDENCE_MISSING",observation_id=ident)
        elif terminal=="equivalent_observation":
            if not linked or not all(exempt.get(i["id"])=="equivalent_observation" or (dispositions.get(i["id"],{}).get("kind")=="overlap_duplicate" and i["id"] in matched) for i in linked):
                issue("review_required","TERMINAL_EVIDENCE_MISSING",observation_id=ident)
        elif terminal=="source_limited":
            valid = _source_limit_evidence(evidence)
            if not valid:
                issue("review_required","TERMINAL_EVIDENCE_MISSING",observation_id=ident)
            try:
                fade_preserved = valid and evidence["reason"]=="fade_transition" and bool(linked) and all(i["id"] in matched and any(e["observation_id"]!=ident and e.get("eligible") and e.get("supports") for e in resolver.views(i)) for i in linked)
            except EvidenceUnavailableError as exc:
                fade_preserved = False
                issue("review_required","EVIDENCE_UNAVAILABLE",observation_id=ident,detail=str(exc))
            if not fade_preserved:
                issue("review_required","OBSERVATION_SOURCE_LIMITED",observation_id=ident,reason=evidence.get("reason"))
        elif terminal=="unresolved":
            path = evidence.get("review_artifact")
            artifact_ok = False
            if path:
                im = cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                # Those hash-checked views were already materialised during
                # source matching. Replaying all members for every unresolved
                # observation makes this quadratic in observations per display.
                hashes = list(raw_hashes_by_observation.get(ident, ()))
                if evidence.get("pixels_sha256"):
                    hashes.append(evidence["pixels_sha256"])
                artifact_ok = im is not None and pixels_hash(im) in hashes
            else:
                artifact_ok = bool(linked) and all(dispositions.get(i["id"],{}).get("kind")=="unresolved_alternative" and dispositions[i["id"]].get("observation_id")==ident and dispositions[i["id"]].get("review_artifact") for i in linked)
            if not artifact_ok:
                issue("review_required","TERMINAL_EVIDENCE_MISSING",observation_id=ident)
            issue("review_required","OBSERVATION_UNRESOLVED",observation_id=ident)

    for origin in ledger.get("generated_origins",[]):
        try:
            pi = origin["page_index"]
            if not isinstance(pi,int) or not 0<=pi<len(pages):
                raise ValueError("generated origin page missing")
            x,y = map(int,origin["origin"])
            template = unpack_crop(origin["template"])
            c = _contrast(template)
            mask = c>=C_CLEAR
            kind = origin["kind"]
            if y<0 or x<0 or y+mask.shape[0]>pages[pi].shape[0] or x+mask.shape[1]>pages[pi].shape[1]:
                raise ValueError("generated template outside page")
            if kind=="staff_scaffold":
                if origin.get("source_resample") is not None:
                    column = scaffold_source_column(ledger, origin, items=items, resolver=resolver)
                    if len(column) != mask.shape[0] or np.any(mask & ~(column[:,None] >= MIN_CONTRAST)):
                        raise ValueError("generated scaffold differs from its independently resampled raw staff")
                else:
                    ref = items[origin["source_item_id"]]
                    if not _staff_only(ref,origin["staff_rows_display"]):
                        raise ValueError("generated scaffold lacks raw staff evidence")
                    yy,xx = np.nonzero(mask)
                    rows = np.array(origin["staff_rows_local"])
                    if not len(rows) or not len(yy) or np.min(abs(yy[:,None]-rows),axis=1).max()>.6:
                        raise ValueError("generated scaffold template contains non-staff ink")
            elif kind in ("header","page_number","review_notice","incomplete_marker","source_clipped_notice","possible_repeat_notice","number_step_notice","section_label"):
                if not origin.get("generator") or not origin.get("inputs"):
                    raise ValueError("generated text requires generator and inputs")
                if kind=="section_label":
                    if not origin["inputs"].get("source"):
                        raise ValueError("section label requires video source")
                    issue("review_required","SECTION_LABEL_SOURCE_UNLEDGERED",page_index=pi)
                if np.any(source[pi][y:y+mask.shape[0],x:x+mask.shape[1]] & mask):
                    raise ValueError("generated text overlaps source music")
            else:
                raise ValueError("unsupported generated origin")
            if encoded_reference is not None:
                c = encoded_reference[pi][y:y+c.shape[0], x:x+c.shape[1]]
                mask &= c >= 8
            ok,metrics,actual = _local_match(pages[pi],c,mask,[x,y])
            if not ok:
                raise ValueError(f"generated pixels differ: {metrics}")
            ax,ay,a = actual
            present = mask & (a>=8)
            if kind!="staff_scaffold" and np.any(source[pi][ay:ay+c.shape[0],ax:ax+c.shape[1]] & present):
                raise ValueError("generated text actual match overlaps source music")
            generated[pi][ay:ay+c.shape[0],ax:ax+c.shape[1]] |= present
        except (ValueError,KeyError,TypeError,cv2.error) as exc:
            issue("fail","INVALID_GENERATED_ORIGIN",detail=str(exc))
    for pi,page in enumerate(pages):
        source_halo = cv2.dilate(source[pi].astype(np.uint8),np.ones((5,5),np.uint8))>0
        generated_halo = cv2.dilate(generated[pi].astype(np.uint8),np.ones((5,5),np.uint8))>0
        gray = _gray(page)
        foreground = _percentile(gray,.9)-gray.astype(np.int16)>=C_PAGE
        unexplained = foreground & ~(source_halo | generated_halo)
        accounting.append({"page_index":pi,"foreground_px":int(foreground.sum()),
            "explained_by_source_px":int((foreground & source_halo).sum()),
            "explained_by_generated_px":int((foreground & generated_halo & ~source_halo).sum()),
            "unexplained_px":int(unexplained.sum())})
        n,labels,stats,_ = cv2.connectedComponentsWithStats(unexplained.astype(np.uint8),8)
        for k in range(1,n):
            x,y,w,h,area = map(int,stats[k])
            crop = page[y:y+min(h,96),x:x+min(w,96)]
            issue("review_required" if pi in unassessed_pages else "fail","OUTPUT_FOREGROUND_WITHOUT_ORIGIN",page_index=pi,bbox=[x,y,x+w,y+h],pixels=area,output_crop=pack_crop(crop))
    status = "fail" if any(i["severity"]=="fail" for i in issues) else "review_required" if issues else "pass"
    return {"version":VERSION,"status":status,"issues":issues,"matches":matches,
        "checked_items":len(items)-len(excluded_items),"checked_pages":len(pages),"terminal_counts":terminal_counts,"accounting":accounting,
        "user_excluded":{"displays":len(user_excluded),"items":len(excluded_items)}}


def verify_pdf(ledger: dict[str, Any], path: Path | str, *, pages_sink: list[np.ndarray] | None = None) -> dict[str, Any]:
    contract = check_pdf_contract(path)
    if contract["status"]=="fail":
        return {"version":VERSION,"status":"fail","issues":[dict(i,severity="fail") for i in contract["issues"]],
                "matches":[],"pdf_contract":contract,"checked_pages":0,"checked_items":0}
    try:
        extracted = extract_pdf_pages(path)
    except (OSError,ValueError,KeyError,TypeError,NotImplementedError,AttributeError,PdfParser.PdfFormatError) as exc:
        return {"version":VERSION,"status":"review_required","issues":[{"severity":"review_required","code":"DELIVERED_PDF_UNASSESSED","detail":str(exc)}],"matches":[]}
    pages = [p["image"] for p in extracted]
    if pages_sink is not None:
        pages_sink.extend(pages)
    report = verify_pages(ledger,pages,encodings=[p["jpeg_encoding"] for p in extracted])
    report["pdf_contract"] = contract
    report["delivered_pdf_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    report["embedded_pages"] = [{k:v for k,v in p.items() if k!="image"} for p in extracted]
    return report


def write_ledger(path: Path | str, ledger: dict[str, Any]) -> None:
    if ledger.get("evidence_root") and ledger.get("representations"):
        items,by_id = [],{}
        for item in ledger.get("items",[]):
            rec = {k:v for k,v in item.items() if k!="projection_context"}
            record_marks(rec)
            contrast = unpack_crop(rec["expected_contrast"])
            rec["expected_contrast"] = pack_crop(np.where(contrast>=C_CLEAR,contrast,0).astype(np.uint8))
            items.append(rec); by_id[rec["id"]] = rec
        reps = []
        for rep in ledger["representations"]:
            item = by_id[rep["item_id"]]
            raw = unpack_crop(item["foreground_hypothesis"])>0
            yy,xx = np.nonzero(raw)
            points = np.column_stack((xx+item["display_bbox"][0],yy+item["display_bbox"][1],np.ones(len(xx))))
            stages = [dict(t) for t in rep["transforms"]]
            stage = stages[1]
            if stage.get("kind")=="piecewise":
                points = points @ (_matrix(stage.get("pre_matrix",np.eye(3))) @ _matrix(stages[0]["matrix"])).T
                lo,hi = points[:,:2].min(axis=0)-3,points[:,:2].max(axis=0)+3
                stage["pieces"] = [p for p in stage["pieces"] if p["src_bbox"][0]<=hi[0] and p["src_bbox"][2]>=lo[0]
                    and p["src_bbox"][1]<=hi[1] and p["src_bbox"][3]>=lo[1]]
                stage.pop("inserted_offsets",None)
            reps.append(dict(rep,transforms=stages))
        compact = dict(ledger,items=items,representations=reps,matching="clear-marks-1")
        Path(path).write_text(json.dumps(compact,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    else:
        Path(path).write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
