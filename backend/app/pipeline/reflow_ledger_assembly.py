"""Assembly of raw observation inventory and producer ledger fragments.

No cleanup/tracking flags discharge evidence. Integration owns persistence and
call order; this module only retains frames when explicitly asked.
"""
from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np

from app.pipeline import observations as ob
from app.pipeline import reflow_ledger as rl
from app.pipeline.reflow_ledger import MIN_CONTRAST, pack_crop, pixels_hash, unpack_crop


def _empty(source_video: str | None = None) -> dict[str, Any]:
    return {"version": rl.VERSION, "source_video": source_video,
            **{k: [] for k in ("observations", "displays", "items", "representations", "dispositions",
                              "display_dispositions", "generated_origins", "occurrence_remaps")}}


def inventory_observations(manifest: dict, manifest_dir: Path, *, source_video: str) -> dict:
    """Hook 0: stream stored raw ROI frames, never re-decode missing evidence."""
    ledger = _empty(source_video)
    if manifest.get("detector_version") is not None:
        ledger["detector_version"] = manifest["detector_version"]
    scale = manifest.get("work_scale") or {}
    for obs in manifest["observations"]:
        if not obs.get("frame_path"):
            raise FileNotFoundError(f"{obs['id']}: missing stored frame")
        path = (Path(manifest_dir) / obs["frame_path"]).resolve()
        # Passing no manifest forbids the loader's fallback to a new decode.
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        image = ob.load_observation_image(Path(manifest_dir), obs)
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        light = rl._percentile(gray,.5)>=128
        contrast,_ = rl._photometry(image,"light" if light else "dark",gray=gray)
        ledger["observations"].append({
            "id": obs["id"], "t_sec": float(obs["t_sec"]), "sample_kind": obs["sample_kind"],
            "frame_path": str(path), "frame_png_sha256": file_hash, "pixels_sha256": pixels_hash(image),
            "crop_size": [image.shape[1], image.shape[0]],
            "native_crop_size": copy.deepcopy(scale.get("native_crop_size")), "work_scale": float(scale.get("scale", 1.)),
            "source_to_crop": copy.deepcopy(obs.get("source_to_crop", manifest.get("source_to_crop"))),
            "applied_roi": copy.deepcopy(obs.get("applied_roi", manifest.get("applied_roi"))),
            "roi_revision": obs.get("roi_revision", manifest.get("roi_revision")),
            "staff_regions": len(obs.get("system_regions", [])), "foreground_px": int(np.count_nonzero(contrast >= MIN_CONTRAST)),
            "associations": [], "terminal": None})
    return ledger


def annotate(ledger: dict, associations: Iterable[dict]) -> None:
    """Append annotations verbatim, retaining optional region/measurement evidence."""
    observations = {o["id"]: o for o in ledger.get("observations", [])}
    roles = ("member", "offered", "used", "rejected_fade", "rejected_registration", "duration_filtered",
             "excluded_candidate", "covered_by_kept_display", "transient", "unassigned")
    for association in associations:
        obs = observations[association["obs_id"]]
        if association["role"] not in roles:
            raise ValueError(f"unknown observation role: {association['role']}")
        obs.setdefault("associations", []).append(copy.deepcopy({k: v for k, v in association.items() if k != "obs_id"}))


def annotate_from_tracking(ledger: dict, tracking: dict) -> None:
    """Inventory every episode membership, transient and unassigned observation."""
    transients = list(tracking.get("transients", tracking.get("transient_observations", [])))
    by_obs: dict[str, list[dict]] = {}
    for rec in transients:
        by_obs.setdefault(rec["obs_id"], []).append(rec)
    attached = set()
    associations = []
    for episode in tracking.get("episodes", []):
        ids, regions = episode.get("observation_ids", []), episode.get("region_ids", [])
        if len(ids) != len(regions):
            raise ValueError("tracking observation/region lengths differ")
        for oid, rid in zip(ids, regions):
            associations.append({"obs_id": oid, "stage": "tracking", "display_id": None,
                                 "occurrence_id": episode["id"], "role": "member", "reason": None, "region_id": rid})
        for entry in episode.get("transient_observation_ids", []):
            oid = entry["obs_id"] if isinstance(entry, dict) else entry
            records = [entry] if isinstance(entry, dict) else [r for r in by_obs.get(oid, [])
                       if r.get("slot_id") in (None, episode.get("slot_id"))]
            for rec in records or [{}]:
                association = {"obs_id": oid, "stage": "tracking", "display_id": None,
                               "occurrence_id": episode["id"], "role": "transient", "reason": "tracking_transient"}
                for key in ("region_id", "slot_id"):
                    if key in rec:
                        association[key] = rec[key]
                associations.append(association)
                attached.add((oid, rec.get("region_id"), rec.get("slot_id")))
    for rec in transients:
        if (rec["obs_id"], rec.get("region_id"), rec.get("slot_id")) in attached:
            continue
        associations.append({"obs_id": rec["obs_id"], "stage": "tracking", "display_id": None,
                             "occurrence_id": None, "role": "transient", "reason": rec.get("reason", "tracking_transient"),
                             **{k: rec[k] for k in ("region_id", "slot_id") if k in rec}})
    annotate(ledger, associations)
    annotate(ledger, ({"obs_id": o["id"], "stage": "tracking", "display_id": None,
                      "occurrence_id": None, "role": "unassigned", "reason": "no_episode"}
                     for o in ledger.get("observations", [])
                     if not any(a.get("stage") == "tracking" for a in o.get("associations", []))))


def merge_ledgers(*fragments: dict) -> dict:
    """Merge independent inventories; only association-only observation stubs repeat."""
    result = _empty()
    observations: dict[str, dict] = {}
    full = set()
    seen = {"displays": set(), "items": set()}
    for fragment in fragments:
        source = fragment.get("source_video")
        if source is not None:
            if result["source_video"] is not None and result["source_video"] != source:
                raise ValueError("ledger source_video differs")
            result["source_video"] = source
        if fragment.get("evidence_root") is not None:
            root = str(Path(fragment["evidence_root"]).resolve())
            if result.get("evidence_root",root)!=root:
                raise ValueError("ledger evidence_root differs")
            result["evidence_root"] = root
        if fragment.get("detector_version") is not None:
            if result.get("detector_version", fragment["detector_version"]) != fragment["detector_version"]:
                raise ValueError("ledger detector_version differs")
            result["detector_version"] = fragment["detector_version"]
        for key in (k for k in result if isinstance(result[k], list)):
            for record in fragment.get(key, []):
                rec = copy.deepcopy(record)
                if key == "observations":
                    oid = rec["id"]
                    stub = set(rec) <= {"id", "associations"}
                    if not stub and oid in full:
                        raise ValueError(f"duplicate observation: {oid}")
                    if oid not in observations:
                        observations[oid] = rec
                        result[key].append(rec)
                    else:
                        dest = observations[oid]
                        associations = dest.get("associations", []) + rec.get("associations", [])
                        if not stub:
                            dest.update(rec)
                        dest["associations"] = associations
                    if not stub:
                        full.add(oid)
                else:
                    if key in seen:
                        ident = rec["id"]
                        if ident in seen[key]:
                            raise ValueError(f"duplicate {key} id: {ident}")
                        seen[key].add(ident)
                    result[key].append(rec)
    superseded = {d["display_id"] for d in result["display_dispositions"] if d.get("kind")=="superseded_inventory"}
    result["display_dispositions"] = [d for d in result["display_dispositions"] if not (d.get("kind")=="display_unresolved" and d.get("display_id") in superseded)]
    for oid in observations:
        if oid not in full:
            raise ValueError(f"observation stub has no full record: {oid}")
    return result


def _matrix(value: Sequence[Sequence[float]]) -> np.ndarray:
    m = np.asarray(value, dtype=float).reshape(3, 3)
    if not np.isfinite(m).all() or not np.allclose(m[2], [0, 0, 1]) or abs(np.linalg.det(m)) < 1e-9:
        raise ValueError("finite invertible affine matrix required")
    return m


def _chain_matrix(chain: dict) -> np.ndarray:
    stages = chain["stages"]
    if len(stages) != 1 or stages[0].get("kind") != "affine":
        raise ValueError("one display_to_strip affine required")
    return _matrix(stages[0]["matrix"])


def _crop_child(item: dict, selection: np.ndarray, ident: str, resolver: rl.EvidenceResolver) -> dict:
    yy, xx = np.nonzero(selection)
    x0, y0, x1, y1 = int(xx.min()), int(yy.min()), int(xx.max())+1, int(yy.max())+1
    sl = np.s_[y0:y1, x0:x1]
    ox, oy = item["display_bbox"][:2]
    bbox = [ox+x0, oy+y0, ox+x1, oy+y1]
    child = copy.deepcopy(item)
    child.pop("partitioned_into", None)
    child.update(id=ident, partition_of=item["id"], display_bbox=bbox,
                 foreground_hypothesis=pack_crop(selection[sl].astype(np.uint8)*255),
                 expected_contrast=pack_crop(unpack_crop(item["expected_contrast"])[sl]))
    child["projection_context"] = copy.deepcopy(item.get("projection_context") or
        {"display_bbox": item["display_bbox"], "expected_contrast": item["expected_contrast"]})
    rl.record_marks(child)
    # Referenced children inherit member bitsets, never duplicate native patches.
    if "evidence" not in item:
        return child
    child["evidence"] = copy.deepcopy(list(resolver.views(item)))
    for ev in child["evidence"]:
        for key in ("display_patch", "contrast", "usable_mask"):
            if key in ev:
                ev[key] = pack_crop(unpack_crop(ev[key])[sl])
        inv = np.linalg.inv(_matrix(ev["transform"]["matrix"]))
        a, b, c, d = bbox
        corners = np.array([[a,b,1], [c,b,1], [a,d,1], [c,d,1]]) @ inv.T
        lo, hi = np.floor(corners[:,:2].min(axis=0)).astype(int), np.ceil(corners[:,:2].max(axis=0)).astype(int)
        nb = np.asarray(ev["native_bbox"], dtype=int)
        lo, hi = np.maximum(lo, nb[:2]), np.minimum(hi, nb[2:])
        if np.any(lo >= hi):
            raise ValueError("child has no corresponding raw evidence crop")
        native_sl = np.s_[lo[1]-nb[1]:hi[1]-nb[1], lo[0]-nb[0]:hi[0]-nb[0]]
        for key in ("raw_patch", "native_usable_mask", "native_occluded_mask"):
            if key in ev:
                ev[key] = pack_crop(unpack_crop(ev[key])[native_sl])
        ev["native_bbox"] = [*map(int, lo), *map(int, hi)]
    return child


def _warp_hypothesis(mask: np.ndarray, origin: Sequence[int], matrix: np.ndarray):
    h, w = mask.shape
    x, y = origin
    corners = np.array([[x,y,1], [x+w,y,1], [x,y+h,1], [x+w,y+h,1]]) @ matrix.T
    lo, hi = np.floor(corners[:,:2].min(axis=0)).astype(int), np.ceil(corners[:,:2].max(axis=0)).astype(int)
    size = hi-lo
    if np.any(size <= 0) or np.any(size > 1024):
        raise ValueError("unsupported projected footprint size")
    local = matrix.copy()
    local[:2,2] += matrix[:2,:2] @ np.array([x,y])-lo
    return cv2.warpAffine(mask.astype(np.uint8), local[:2], tuple(size), flags=cv2.INTER_NEAREST)>0, lo.tolist()


def _check_projection(item: dict, transforms: Sequence[dict]) -> None:
    marks = rl.mark_masks(item)
    if not marks:
        return
    for b,mark,_ in marks:
        rl._project_mark(item,transforms,b,mark)


def assemble_representations(ledger: dict, chains: Sequence[dict], placements: Sequence[dict]) -> None:
    """Partition by routing signature across copies; removed pixels stay unplaced."""
    resolver = rl.EvidenceResolver(ledger)
    by_display: dict[str, list[dict]] = {}
    for chain in chains:
        by_display.setdefault(chain["display_id"], []).append(chain)
    by_strip: dict[str, list[tuple[int, dict]]] = {}
    for index, placement in enumerate(placements):
        by_strip.setdefault(placement["strip_id"], []).append((index, placement))
    children, representations, partitions = [], [], []
    ids = {i["id"] for i in ledger.get("items", [])}
    dispositions = {d["item_id"]:d for d in ledger.get("dispositions",[])}
    for item in ledger.get("items", []):
        if item.get("partition_of") or item.get("partitioned_into") or item["display_id"] not in by_display:
            continue
        mask = unpack_crop(item["foreground_hypothesis"]) > 0
        d = dispositions.get(item["id"],{})
        if d.get("kind")=="cursor_recovery":
            recovered = rl._cursor_recovery(dict(item,evidence=list(resolver.views(item))),d,mask)
            if recovered is not None and np.array_equal(recovered,mask):
                continue
        yy, xx = np.nonzero(mask)
        if not len(xx):
            continue
        points = np.column_stack((xx+item["display_bbox"][0], yy+item["display_bbox"][1], np.ones(len(xx))))
        routes, chosen = [], {}
        for chain in by_display[item["display_id"]]:
            strip = points @ _chain_matrix(chain).T
            for index, placement in by_strip.get(chain["strip_id"], []):
                stages = placement["stages"]
                if len(stages) != 2 or stages[0]["kind"] not in ("affine", "piecewise") or stages[1]["kind"] != "affine":
                    raise ValueError("strip_to_line and line_to_page stages required")
                stage = stages[0]
                if stage["kind"] == "affine":
                    selected = np.ones(len(xx), bool)
                else:
                    coords = strip @ _matrix(stage.get("pre_matrix", np.eye(3))).T
                    ownership = np.zeros(len(xx), np.int32)
                    # Assign a native pixel once by its continuous mapped centre.
                    p = coords[:,:2]
                    for piece in stage["pieces"]:
                        a, b, c, d = piece["src_bbox"]
                        ownership += (p[:,0] >= a) & (p[:,0] < c) & (p[:,1] >= b) & (p[:,1] < d)
                    if np.any(ownership > 1):
                        raise ValueError("placement pieces double-own foreground")
                    selected = ownership == 1
                if chain.get("domain_strip") is not None:
                    a,b = chain["domain_strip"]
                    if not np.isfinite([a,b]).all() or a>=b:
                        raise ValueError("invalid chain domain_strip")
                    selected &= (strip[:,0]>=a)&(strip[:,0]<b)
                token = (index, len(routes))
                routes.append((token, selected))
                chosen[token] = (chain, placement)
        # Same copy cannot own a hypothesis pixel in two placements/chains.
        copies: dict[int, np.ndarray] = {}
        for token, selected in routes:
            ci = chosen[token][1]["copy_index"]
            copies.setdefault(ci, np.zeros(len(xx), np.int32))
            copies[ci] += selected
        if any(np.any(owned > 1) for owned in copies.values()):
            raise ValueError("placements double-own foreground for one copy")
        signatures: dict[tuple, np.ndarray] = {}
        if routes:
            membership = np.column_stack([r[1] for r in routes])
            patterns, inverse = np.unique(membership, axis=0, return_inverse=True)
            # Order children by first parent pixel, not sorted boolean signatures.
            for group in sorted(range(len(patterns)), key=lambda k: int(np.flatnonzero(inverse == k)[0])):
                signature = tuple(routes[j][0] for j in np.flatnonzero(patterns[group]))
                selection = np.zeros(mask.shape, bool)
                selection[yy[inverse == group], xx[inverse == group]] = True
                signatures[signature] = selection
        else:
            signatures[()] = mask
        partition = len(signatures) > 1 or not any(signatures)
        targets = []
        for k, (signature, selection) in enumerate(signatures.items()):
            target = item
            if partition:
                ident = f"{item['id']}/p{k}"
                if ident in ids:
                    raise ValueError(f"partition id already exists: {ident}")
                ids.add(ident)
                target = _crop_child(item, selection, ident, resolver)
                children.append(target)
            targets.append(target["id"])
            for token in signature:
                chain, placement = chosen[token]
                transforms = [dict(copy.deepcopy(chain["stages"][0]), stage="display_to_strip"),
                              dict(copy.deepcopy(placement["stages"][0]), stage="strip_to_line"),
                              dict(copy.deepcopy(placement["stages"][1]), stage="line_to_page")]
                rep = {"item_id": target["id"], "occurrence_id": item["occurrence_id"],
                                        "copy_index": placement["copy_index"], "page_index": placement["page_index"],
                                        "line_id": placement["line_id"], "transforms": transforms}
                try:
                    _check_projection(target, transforms)
                except ValueError as exc:
                    # A ledger finding must survive assembly, with its route.
                    rep["projection_error"] = {"code": "TRANSFORM_DROPS_OR_DUPLICATES_FOREGROUND"
                        if isinstance(exc, rl.TransformLossError) else "TRANSFORM_UNRESOLVED",
                        "detail": f"{type(exc).__name__}: {exc}"}
                representations.append(rep)
        if partition:
            partitions.append((item, targets))
    for parent, targets in partitions:
        parent["partitioned_into"] = targets
    partition_ids = {parent["id"] for parent, _ in partitions}
    if partition_ids:
        ledger["representations"] = [r for r in ledger.get("representations", []) if r["item_id"] not in partition_ids]
    ledger.setdefault("items", []).extend(children)
    # Faint proof visits every raw member. Batch those small children by member
    # rather than decoding a full frame for every fringe and every replica.
    targets = {i["id"]: i for i in ledger["items"]}
    pending = {}
    for rep in representations:
        if rep.get("projection_error", {}).get("detail") == "TransformLossError: resampling removes the entire source hypothesis":
            target = targets[rep["item_id"]]
            mask = unpack_crop(target["foreground_hypothesis"]) > 0
            if int(unpack_crop(target["expected_contrast"])[mask].max()) < rl.SOURCE_CLEAR_CONTRAST:
                pending.setdefault(target["id"], []).append(rep)
    ids = list(pending)
    for start in range(0, len(ids), 32):
        batch = [targets[ident] for ident in ids[start:start+32]]
        resolver.prefetch(batch)
        for target in batch:
            for rep in pending[target["id"]]:
                try:
                    proof = rl.below_contrast_floor(target, rep["transforms"], resolver=resolver)
                    if proof is not None:
                        rep["below_contrast_floor"] = proof
                        rep.pop("projection_error")
                except ValueError:
                    pass  # The retained projection error remains a finding.
    ledger.setdefault("representations", []).extend(representations)


def finalize_terminals(ledger: dict, *, detector_version: str | None = None) -> dict:
    """Derive observation outcomes once; leave item/representation evidence intact."""
    terminals = ("preserved", "recovered_beneath_overlay", "equivalent_observation", "non_score_material", "source_limited", "unresolved")
    mapping = {"cursor_recovery": "recovered_beneath_overlay", "overlap_duplicate": "equivalent_observation",
               "staff_scaffold": "preserved", "chrome": "non_score_material", "preview_inset": "non_score_material",
               "structural_replacement": "unresolved", "unresolved_alternative": "unresolved"}
    resolver = rl.EvidenceResolver(ledger)
    superseded,_ = rl.verified_supersedes(ledger)
    ledger["display_dispositions"] = [d for d in ledger.get("display_dispositions",[]) if not (d.get("kind")=="display_unresolved" and d.get("display_id") in superseded)]
    dispositions = {d["item_id"]: d for d in ledger.get("dispositions", [])}
    display_dispositions = {d["display_id"]: d for d in ledger.get("display_dispositions", [])}
    represented = {r["item_id"] for r in ledger.get("representations", [])}
    linked: dict[str, list[tuple[dict, str, dict]]] = {}
    for item in ledger.get("items", []):
        if item.get("partitioned_into") or item["display_id"] in superseded:
            continue
        if not rl.mark_masks(item):
            continue
        disposition = dispositions.get(item["id"], {})
        dd = display_dispositions.get(item["display_id"], {})
        terminal = disposition.get("terminal", mapping.get(disposition.get("kind")))
        if terminal is None:
            terminal = "preserved" if item["id"] in represented else dd.get("terminal", "unresolved")
        if terminal not in terminals:
            terminal = "unresolved"
        for oid in resolver.observation_ids(item):
            linked.setdefault(oid, []).append((item, terminal, disposition or dd))
    counts = dict.fromkeys(terminals, 0)
    for obs in ledger.get("observations", []):
        if obs.get("terminal") is not None:
            if obs["terminal"] not in counts:
                raise ValueError(f"unknown observation terminal: {obs['terminal']}")
            counts[obs["terminal"]] += 1
            continue
        associations = obs.get("associations", [])
        outcomes = linked.get(obs["id"], [])
        states = {t for _, t, _ in outcomes}
        evidence: dict[str, Any] = {"observation_id": obs["id"], "pixels_sha256": obs["pixels_sha256"]}
        if outcomes:
            evidence["item_ids"] = [i["id"] for i, _, _ in outcomes]
            evidence["dispositions"] = [copy.deepcopy(d) for _, _, d in outcomes if d]
        if "unresolved" in states:
            terminal = "unresolved"
        elif "source_limited" in states:
            terminal = "source_limited"
        elif states and states <= {"preserved", "recovered_beneath_overlay", "equivalent_observation"}:
            terminal = next(t for t in terminals[:3] if t in states)
            if terminal == "preserved":
                displays = {i["display_id"] for i, t, _ in outcomes if t == "preserved" and i["id"] in represented}
                evidence["display_ids"] = sorted(displays)
                if not any(a.get("role") in ("used", "member") and superseded.get(a.get("display_id"),a.get("display_id")) in displays
                           for a in associations):
                    terminal = "unresolved"
                    evidence["reason"] = "no_delivery_association"
        else:
            outside = not any(a.get("occurrence_id") is not None or a.get("display_id") is not None for a in associations)
            detector = detector_version if detector_version is not None else ledger.get("detector_version")
            if (not states or states == {"non_score_material"}) and outside and obs["staff_regions"] == 0 and isinstance(detector, str) and detector:
                terminal = "non_score_material"
                evidence.update(staff_regions=0, detector_version=detector, outside_every_episode=True)
            else:
                limited = next((a for a in associations if a.get("reason") in
                                ("fade_transition", "registration_out_of_range", "source_clipped", "outside_requested_range")
                                or a.get("role") in ("rejected_fade", "rejected_registration")), None)
                if limited and not outcomes:
                    terminal = "source_limited"
                    evidence.update(copy.deepcopy(limited.get("evidence", {})))
                    evidence["reason"] = limited.get("reason") if limited.get("reason") in (
                        "fade_transition", "registration_out_of_range", "source_clipped", "outside_requested_range") else (
                        "fade_transition" if limited["role"] == "rejected_fade" else "registration_out_of_range")
                    for key in ("paper_drop", "shift_px", "clip_bbox", "clipped_px", "requested_range", "measured_value", "measured", "t_sec"):
                        if key in limited:
                            evidence[key] = copy.deepcopy(limited[key])
                else:
                    terminal = "unresolved"
        if terminal == "source_limited" and outcomes:
            limits = [copy.deepcopy(d) for _, t, d in outcomes if t == "source_limited"]
            evidence["source_limits"] = limits
            if limits:
                evidence.update({k: v for k, v in limits[0].items() if k not in ("item_id", "kind", "terminal")})
        if terminal == "unresolved":
            evidence.setdefault("review_artifact", obs["frame_path"])
            evidence.setdefault("reason", "unaccounted_foreground")
            if not associations:
                obs.setdefault("associations", []).append({"stage": "tracking", "display_id": None,
                    "occurrence_id": None, "role": "unassigned", "reason": "no_episode"})
        obs["terminal"] = terminal
        obs["evidence"] = evidence
        counts[terminal] += 1
    return counts


def retain_evidence(ledger: dict, workspace: Path) -> int:
    """Retain hash-checked observation PNGs before pruning; deduplicate by pixels."""
    copied = 0
    needed = {m["frame_ref"]["observation_id"] for d in ledger.get("displays",[]) for m in d.get("members",[]) if m.get("frame_ref")}
    for obs in ledger.get("observations", []):
        if obs.get("terminal") == "non_score_material" and obs["foreground_px"] == 0 and obs["id"] not in needed:
            continue
        target = (Path(workspace) / "ledger_evidence" / f"{obs['pixels_sha256']}.png").resolve()
        if not target.exists():
            source = Path(obs["frame_path"])
            if hashlib.sha256(source.read_bytes()).hexdigest() != obs["frame_png_sha256"]:
                raise ValueError(f"observation PNG hash mismatch: {obs['id']}")
            image = cv2.imread(str(source))
            if image is None or pixels_hash(image) != obs["pixels_sha256"]:
                raise ValueError(f"observation pixels hash mismatch: {obs['id']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != obs["frame_png_sha256"]:
                raise ValueError(f"retained PNG hash mismatch: {obs['id']}")
            copied += 1
        retained_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if obs.get("retained_frame_png_sha256", retained_hash) != retained_hash:
            raise ValueError(f"retained PNG hash mismatch: {obs['id']}")
        image = cv2.imread(str(target))
        if image is None or pixels_hash(image) != obs["pixels_sha256"]:
            raise ValueError(f"retained pixels hash mismatch: {obs['id']}")
        obs["frame_path"] = str(target)
        obs["retained_frame_png_sha256"] = retained_hash
        if obs.get("evidence", {}).get("review_artifact"):
            obs["evidence"]["review_artifact"] = str(target)
    return copied


def _staff_only(item: dict, rows: Sequence[float]) -> bool:
    mask = unpack_crop(item["foreground_hypothesis"]) > 0
    yy, xx = np.nonzero(mask)
    if not len(yy) or not rows:
        return False
    y = yy + item["display_bbox"][1]
    return bool(np.min(np.abs(y[:,None]-np.asarray(rows)[None,:]), axis=1).max() <= .6 and len(np.unique(xx)) >= 8)


def resolve_generated(ledger: dict, chains: Sequence[dict], generated: Sequence[dict]) -> None:
    """Resolve strip scaffold provenance only when one raw staff hypothesis fits."""
    by_strip: dict[str, list[dict]] = {}
    by_display: dict[str, list[dict]] = {}
    for chain in chains:
        by_strip.setdefault(chain["strip_id"], []).append(chain)
    for item in ledger.get("items", []):
        if not item.get("partition_of"):
            by_display.setdefault(item["display_id"], []).append(item)
    for origin in generated:
        rec = copy.deepcopy(origin)
        if rec.get("kind") == "staff_scaffold" and rec.get("source_resample") is not None:
            refs = []
            a, b, c, d = rec["source_bbox_S"]
            for chain in by_strip.get(rec.get("strip_id"), []):
                matrix = _chain_matrix(chain)
                for item in by_display.get(chain["display_id"], []):
                    mask = unpack_crop(item["foreground_hypothesis"]) > 0
                    yy, xx = np.nonzero(mask)
                    points = np.column_stack((xx+item["display_bbox"][0], yy+item["display_bbox"][1], np.ones(len(xx)))) @ matrix.T
                    if np.any((points[:,0]>=a)&(points[:,0]<c)&(points[:,1]>=b)&(points[:,1]<d)):
                        refs.append({"item_id": item["id"], "display_to_strip": matrix.tolist()})
            rec["source_item_refs"] = refs
            rec["source_item_ids"] = [r["item_id"] for r in refs]
            try:
                rl.scaffold_source_column(ledger, rec)
                rec.pop("unresolved_source", None)
            except (ValueError, KeyError, TypeError, StopIteration, cv2.error):
                rec["unresolved_source"] = True
            ledger.setdefault("generated_origins", []).append(rec)
            continue
        if rec.get("kind") == "staff_scaffold" and not rec.get("source_item_id"):
            candidates = {}
            for chain in by_strip.get(rec.get("strip_id"), []):
                a, b, c, d = rec["source_bbox_S"]
                matrix = _chain_matrix(chain)
                inv = np.linalg.inv(matrix)
                box = np.array([[a,b,1], [c,b,1], [a,d,1], [c,d,1]]) @ inv.T
                lo, hi = box[:,:2].min(axis=0), box[:,:2].max(axis=0)
                for item in by_display.get(chain["display_id"], []):
                    mask = unpack_crop(item["foreground_hypothesis"]) > 0
                    yy, xx = np.nonzero(mask)
                    x, y = xx+item["display_bbox"][0], yy+item["display_bbox"][1]
                    intersects = (x >= lo[0]) & (x <= hi[0]) & (y >= lo[1]) & (y <= hi[1])
                    projected = np.column_stack((x, y, np.ones(len(x)))) @ matrix.T
                    intersects &= (projected[:,0] >= a) & (projected[:,0] < c) & (projected[:,1] >= b) & (projected[:,1] < d)
                    active = np.unique(y)
                    groups = np.split(active, np.flatnonzero(np.diff(active) > 1)+1)
                    rows = [float(g.mean()) for g in groups if len(g)]
                    if intersects.any() and _staff_only(item, rows):
                        # Without supplied rows, a filled rectangle is not raw staff.
                        supplied = rec.get("staff_rows_S")
                        if supplied is not None:
                            points = np.column_stack((np.full(len(supplied), a), supplied, np.ones(len(supplied)))) @ inv.T
                            rows = points[:,1].tolist()
                        elif np.any(mask.sum(axis=1)[mask.any(axis=1)] < 8):
                            continue
                        if _staff_only(item, rows):
                            candidates[item["id"]] = rows
            if len(candidates) == 1:
                rec["source_item_id"], rec["staff_rows_display"] = next(iter(candidates.items()))
                rec.pop("unresolved_source", None)
            else:
                rec["unresolved_source"] = True
        ledger.setdefault("generated_origins", []).append(rec)
