"""Stage A: hook-0 observations -> committed native strip (interface §12).

Only hook-0 frames supply pixels. Producer masks describe visibility, never
foreground. Registration is measured once per member; local obligations have
fixed coordinates, with no per-feature displacement search.
"""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from app.pipeline import minority_content as mc
from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_verify_common as vc


class _GeometryUnavailable(ValueError):
    pass


def _affine(stage: dict) -> np.ndarray:
    matrix = np.asarray(stage["matrix"], dtype=np.float64)
    if (stage.get("kind", "affine") != "affine" or matrix.shape != (3, 3)
            or not np.isfinite(matrix).all() or not np.array_equal(matrix[2], [0, 0, 1])
            or abs(np.linalg.det(matrix[:2, :2])) < 1e-12):
        raise _GeometryUnavailable("invalid affine transform")
    return matrix


def _chains(chain: dict, strip_id: str) -> list[dict]:
    entries = chain if isinstance(chain, list) else chain.get(strip_id, [chain])
    if isinstance(entries, dict):
        entries = [entries]
    if not entries:
        raise _GeometryUnavailable("no display-to-strip chain")
    for entry in entries:
        if entry.get("strip_id") != strip_id or len(entry.get("stages", [])) != 1:
            raise _GeometryUnavailable("one display-to-strip affine required")
        if entry["stages"][0].get("stage") != "display_to_strip":
            raise _GeometryUnavailable("unexpected chain stage")
        _affine(entry["stages"][0])
    return entries


def _members(ledger: dict, display: dict, record: dict) -> list[dict]:
    """Union member records, embedded evidence and associations (no eligible filter)."""
    by_id = {m["observation_id"]: dict(m) for m in display.get("members", [])}
    for item in ledger.get("items", []):
        if item.get("display_id") != display["id"]:
            continue
        for evidence in item.get("evidence", []):
            oid = evidence["observation_id"]
            member = by_id.setdefault(oid, {"observation_id": oid,
                                           "transform": evidence.get("transform", {})})
            member.setdefault("embedded", []).append(evidence)
    ids = set(display.get("observations", [])) | set(by_id)
    inventories = {d["id"]: d for d in ledger.get("displays", [])}
    for disposition in ledger.get("display_dispositions", []):
        if (disposition.get("kind") == "superseded_inventory"
                and disposition.get("retained_display_id") == display["id"]):
            inventory = inventories.get(disposition["display_id"], {})
            ids.update(inventory.get("observations", []))
            ids.update(m["observation_id"] for m in inventory.get("members", []))
    for obs in ledger.get("observations", []):
        if any(a.get("display_id") == display["id"] for a in obs.get("associations", [])):
            ids.add(obs["id"])
    # Association-only rejects retain the producer's canvas geometry, but cannot
    # qualify content. Missing geometry remains explicitly unassessed.
    example = next(iter(by_id.values()), {})
    for oid in ids:
        if oid not in by_id:
            member = {"observation_id": oid, "association_only": True}
            if record.get("ledger_canvas_box_crop"):
                member["frame_ref"] = {"observation_id": oid,
                                       "crop_box": record["ledger_canvas_box_crop"]}
                member["transform"] = {"matrix": np.eye(3).tolist(), "polarity": "light"}
            elif example.get("frame_ref"):
                member["frame_ref"] = dict(example["frame_ref"], observation_id=oid)
                member["transform"] = example.get("transform", {})
            by_id[oid] = member
    return [by_id[oid] for oid in sorted(by_id)]


def _anchored_canvas(frame: np.ndarray, display: dict, member: dict) -> tuple[np.ndarray, dict]:
    tf = member.get("transform", {})
    ref = member.get("frame_ref")
    if ref is not None:
        if ref.get("observation_id") != member["observation_id"]:
            raise ValueError("frame_ref observation identity mismatch")
        box = ref["crop_box"]
    else:
        origin = tf.get("roi_origin")
        shape = display.get("shape")
        if origin is None or shape is None:
            raise _GeometryUnavailable("hook-0 crop geometry unavailable")
        box = [*origin, origin[0] + shape[1], origin[1] + shape[0]]
    x0, y0, x1, y1 = map(int, box)
    if list(box) != [x0, y0, x1, y1] or not (0 <= x0 < x1 <= frame.shape[1]
                                                           and 0 <= y0 < y1 <= frame.shape[0]):
        raise _GeometryUnavailable("hook-0 crop outside frame")
    raw = frame[y0:y1, x0:x1]
    shape = display.get("shape")
    operations = {"crop_box": [x0, y0, x1, y1]}
    if shape is None:
        raise _GeometryUnavailable("display canvas shape unavailable")
    if raw.shape[:2] != tuple(shape):
        if ref is None:
            raise _GeometryUnavailable("unrecorded canvas resize")
        interpolation = ref.get("resize_interpolation", cv2.INTER_AREA)
        raw = cv2.resize(raw, tuple(shape[::-1]), interpolation=interpolation)
        operations["canvas_resize"] = {"size": list(shape[::-1]), "interpolation": interpolation}
    if member.get("canvas_pixels_sha256") and vc.pixels_sha256(raw) != member["canvas_pixels_sha256"]:
        raise ValueError("canvas differs from anchored hook-0 crop")
    # Embedded patches are checked against the frame crop, not their own hash.
    for evidence in member.get("embedded", []):
        a, b, c, d = map(int, evidence["native_bbox"])
        patch = rl.unpack_crop(evidence["raw_patch"])
        if not (0 <= a < c <= raw.shape[1] and 0 <= b < d <= raw.shape[0]):
            raise ValueError("embedded evidence outside anchored crop")
        if not np.array_equal(patch, raw[b:d, a:c]):
            raise ValueError("embedded evidence disagrees with hook-0 frame")
    return raw, operations


def _visibility(raw: np.ndarray, member: dict, resolver: rl.EvidenceResolver) -> tuple[np.ndarray, np.ndarray]:
    shape = raw.shape[:2]
    if "usable_ref" in member or "occluded_ref" in member:
        # Resolver checks the recorded file-byte digests and mask dimensions.
        usable = resolver._mask(member.get("usable_ref", "all"), shape)
        hidden = resolver._mask(member.get("occluded_ref", "none"), shape)
    else:
        usable = np.ones(shape, bool)
        hidden = mc.colored_mask(raw)
        for evidence in member.get("embedded", []):
            x0, y0, x1, y1 = evidence["native_bbox"]
            area = np.s_[y0:y1, x0:x1]
            if "native_usable_mask" in evidence:
                usable[area] &= rl.unpack_crop(evidence["native_usable_mask"]) > 0
            if "native_occluded_mask" in evidence:
                hidden[area] |= rl.unpack_crop(evidence["native_occluded_mask"]) > 0
    return usable & ~hidden, hidden


def _integer_translation(matrix: np.ndarray) -> bool:
    return (np.array_equal(matrix[:2, :2], np.eye(2))
            and np.array_equal(matrix[:2, 2], np.rint(matrix[:2, 2])))


def _warp(array: np.ndarray, matrix: np.ndarray, shape: tuple[int, int], interpolation: int) -> np.ndarray:
    # Integer translations do not resample, and this path avoids a full affine
    # allocation in the common case. Other recorded affines use explicit linear
    # interpolation for contrast and nearest for visibility.
    if _integer_translation(matrix):
        dx, dy = map(int, matrix[:2, 2])
        out = np.zeros(shape, array.dtype)
        h, w = array.shape
        x0, x1 = max(0, dx), min(shape[1], w + dx)
        y0, y1 = max(0, dy), min(shape[0], h + dy)
        if x0 < x1 and y0 < y1:
            out[y0:y1, x0:x1] = array[y0-dy:y1-dy, x0-dx:x1-dx]
        return out
    return cv2.warpAffine(array, matrix[:2], shape[::-1], flags=interpolation, borderValue=0)


def _residual(reference: np.ndarray, observed: np.ndarray, visible: np.ndarray,
              gap: float) -> float | None:
    if visible.any() and np.array_equal(reference[visible], observed[visible]):
        return 0.0
    # Same masked SSD/parabola primitive as the cursor recovery producer. One
    # central full-height scaffold window, independent of feature locations.
    h, w = reference.shape
    return mc._cursor_residual_registration(reference, observed, np.zeros((h, w), bool),
                                            ~visible, [w//2, 0, w//2+1, h], gap)


def _distinct_vote(mask: np.ndarray, state: int, observation: int, first: np.ndarray,
                   first_obs: np.ndarray, second_obs: np.ndarray) -> None:
    empty = mask & (first == 0)
    different = mask & (first != 0) & (first != state) & (first_obs != observation) & (second_obs == 0)
    second_obs[different] = observation
    first[empty] = state
    first_obs[empty] = observation


def _attach_features(findings: list[dict], features: list[dict]) -> None:
    for finding in findings:
        if "bbox" not in finding:
            finding["feature_ids"] = []
            continue
        a, b, c, d = finding["bbox"]
        finding["feature_ids"] = [f["id"] for f in features
                                  if f["bbox"][0] < c and f["bbox"][2] > a
                                  and f["bbox"][1] < d and f["bbox"][3] > b]


def verify_strip(base_ledger: dict, strip_record: dict, strip_png: np.ndarray, *,
                 frames: Callable[[str], np.ndarray], chain: dict) -> dict:
    """Return certA (§12.3.6); no artifacts are read except recorded masks.

    ``frames`` must return the decoded hook-0 ROI frame, including its recorded
    channel count/type. Frame, embedded-crop and mask integrity errors fail closed.
    Unmeasurable geometry is a review finding, never a clean certificate.
    """
    strip_id = str(strip_record.get("system_id", strip_record.get("strip_id", strip_record.get("id", ""))))
    contrast = vc.contrast_map(strip_png)
    shape = contrast.shape
    features = vc.strip_features(contrast)
    # Certificate identities belong to A. Keep helper segmentation/masks intact;
    # its component/tile labels can repeat and are unsuitable as JSON identities.
    for index, feature in enumerate(features):
        feature["id"] = f"{strip_id}/f{index:06d}"
    cert = {"strip_id": strip_id, "strip_sha256": vc.pixels_sha256(strip_png),
            "features": [], "findings": [], "counters": {}}
    findings = cert["findings"]
    counters = cert["counters"]
    counters.update(observations=0, informative=0, uninformative=0, integrity_failed=0,
                    features=len(features), registrations=[], source_minority_pixels=0)
    try:
        entries = _chains(chain, strip_id)
    except (ValueError, KeyError, TypeError) as exc:
        entries = []
        findings.append(vc.finding("A", "review_required", "SOURCE_REGISTRATION_UNRESOLVED",
                                   strip_id=strip_id, detail={"reason": str(exc)}))
    displays = {d["id"]: d for d in base_ledger.get("displays", [])}
    observations = {o["id"]: o for o in base_ledger.get("observations", [])}
    obs_numbers = {oid: index for index, oid in enumerate(observations, 1)}
    obs_ids = [None, *observations]
    resolver = rl.EvidenceResolver(base_ledger)
    labels = np.zeros(shape, np.int32)
    centres = vc.obligation_centres(features, shape, contrast)
    for index, feature in enumerate(features, 1):
        x0, y0, x1, y1 = feature["bbox"]
        labels[y0:y1, x0:x1][feature["mask"]] = index
    ys, xs = np.nonzero(centres)
    local_labels = labels[ys, xs]
    areas = np.bincount(local_labels, minlength=len(features)+1)
    strong = contrast >= vc.C_STRONG
    weak = (contrast >= vc.C_WEAK) & ~strong
    supporters = [[] for _ in features]
    supporter_states = [set() for _ in features]
    contradicts = [set() for _ in features]
    pixel_first = np.zeros(shape, np.uint32)
    pixel_first_obs = np.zeros(shape, np.uint32)
    pixel_second_obs = np.zeros(shape, np.uint32)
    missing_first = np.zeros(shape, np.uint32)
    missing_first_obs = np.zeros(shape, np.uint32)
    missing_second_obs = np.zeros(shape, np.uint32)
    visibility_states = {}
    seen_pairs = set()
    excluded_roles = {"rejected_fade", "rejected_registration", "duration_filtered", "excluded_candidate", "transient"}
    for entry in entries:
        display = displays.get(entry["display_id"])
        if display is None:
            findings.append(vc.finding("A", "review_required", "SOURCE_REGISTRATION_UNRESOLVED",
                                       strip_id=strip_id, detail={"display_id": entry["display_id"], "reason": "display missing"}))
            continue
        for member in _members(base_ledger, display, strip_record):
            oid = member["observation_id"]
            pair = (display["id"], oid)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            counters["observations"] += 1
            obs = observations.get(oid, {})
            try:
                frame = frames(oid)
                expected_hash = obs.get("pixels_sha256")
                if not expected_hash or vc.pixels_sha256(frame) != expected_hash:
                    raise ValueError("hook-0 observation pixel hash mismatch or missing commitment")
                raw, operations = _anchored_canvas(frame, display, member)
                free, hidden = _visibility(raw, member, resolver)
                tf = member.get("transform", {})
                matrix = _affine(entry["stages"][0]) @ _affine(tf)
                polarity = member.get("polarity", tf.get("polarity", "light" if np.median(vc.gray(raw)) >= 128 else "dark"))
                observed = _warp(vc.contrast_map(raw, polarity), matrix, shape, cv2.INTER_LINEAR)
                visible = _warp(free.astype(np.uint8), matrix, shape, cv2.INTER_NEAREST) > 0
                domain = entry.get("domain_strip")
                if domain is not None:
                    visible &= (np.arange(shape[1])[None, :] >= domain[0]) & (np.arange(shape[1])[None, :] < domain[1])
                scale = float(obs.get("work_scale", 1.))
                if not np.isfinite(scale) or scale <= 0:
                    raise _GeometryUnavailable("invalid hook-0 native scale")
                residual = _residual(contrast, observed, visible, float(strip_record.get("staff_gap_px", vc.TILE)))
                crop = operations["crop_box"]
                sampling = np.diag([raw.shape[1] / (crop[2]-crop[0]), raw.shape[0] / (crop[3]-crop[1])])
                # The SSD primitive returns a norm, not a direction. The minimum
                # singular value gives a conservative native-pixel upper bound
                # for a recorded resize/nonuniform affine as well as translation.
                native_scale_bound = float(np.linalg.svd(matrix[:2, :2] @ sampling, compute_uv=False)[-1]) * scale
                native_residual = None if residual is None else residual / native_scale_bound
                integer_copy = _integer_translation(matrix)
                operations.update(observation_id=oid, display_id=display["id"],
                                  matrix=matrix.tolist(),
                                  warp_operation="integer_translation_copy" if integer_copy else "affine",
                                  contrast_interpolation=None if integer_copy else cv2.INTER_LINEAR,
                                  mask_interpolation=None if integer_copy else cv2.INTER_NEAREST,
                                  residual_native_scale_bound=native_scale_bound,
                                  residual_registration_px=native_residual)
                counters["registrations"].append(operations)
            except _GeometryUnavailable as exc:
                counters["uninformative"] += 1
                findings.append(vc.finding("A", "review_required", "SOURCE_REGISTRATION_UNRESOLVED",
                                           strip_id=strip_id, detail={"observation_id": oid, "reason": str(exc)}))
                continue
            except (OSError, ValueError, KeyError, TypeError, IndexError, cv2.error) as exc:
                counters["integrity_failed"] += 1
                findings.append(vc.finding("I", "fail", "EVIDENCE_INTEGRITY", strip_id=strip_id,
                                           detail={"observation_id": oid, "reason": str(exc)}))
                continue
            roles = {a.get("role") for a in obs.get("associations", []) if a.get("display_id") == display["id"]}
            transition = member.get("transition", False) or any(
                a.get("reason") == "fade_transition" for a in obs.get("associations", []) if a.get("display_id") == display["id"])
            can_qualify = not member.get("association_only") and not (roles & excluded_roles)
            if native_residual is None or native_residual > .5 or transition:
                counters["uninformative"] += 1
                findings.append(vc.finding("A", "review_required", "SOURCE_REGISTRATION_UNRESOLVED",
                                           strip_id=strip_id, detail={"observation_id": oid,
                                           "residual_registration_px": native_residual, "transition": bool(transition)}))
                continue
            counters["informative"] += 1
            # Clear sources are distinct observations; obscured sources require
            # different recorded visibility/cursor states, even outside this tile.
            state_key = (oid if not hidden.any() else vc.pixels_sha256(hidden),
                         str(member.get("cursor_position", "")), str(member.get("transition_state", "")))
            state = visibility_states.setdefault(state_key, len(visibility_states)+1)
            free_windows = cv2.erode(visible.astype(np.uint8), np.ones((3, 3), np.uint8),
                                     borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
            obs_strong = observed >= vc.C_STRONG
            obs_weak = (observed >= vc.C_WEAK) & ~obs_strong
            # Fringe attached to strong notation is context; isolated weak ink
            # retains a separate persistent obligation path.
            isolated_weak = obs_weak & ~(cv2.dilate(obs_strong.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
            absent = (obs_strong & ~strong) | (isolated_weak & (contrast < vc.C_WEAK))
            missing = (vc.window_mean(absent & visible) > 0) & (obs_strong | isolated_weak) & free_windows
            _distinct_vote(missing, state, obs_numbers[oid], missing_first, missing_first_obs, missing_second_obs)
            supported = ((strong & obs_strong) | (weak & (observed >= vc.C_WEAK))) & free_windows
            if can_qualify:
                _distinct_vote(supported & centres, state, obs_numbers[oid], pixel_first, pixel_first_obs, pixel_second_obs)
            coverage = np.bincount(local_labels, weights=supported[ys, xs], minlength=len(features)+1)
            hidden_counts = np.bincount(local_labels, weights=~free_windows[ys, xs], minlength=len(features)+1)
            novel_counts = np.bincount(local_labels, weights=(vc.window_mean(absent & visible) > 0)[ys, xs],
                                       minlength=len(features)+1)
            informative = (hidden_counts[1:] == 0) & (areas[1:] > 0)
            supports = informative & (coverage[1:] >= .9*areas[1:]) & (novel_counts[1:] == 0)
            # Every obligation window must survive: a tile's 90% allowance may
            # not dilute an added dot/stroke attached to a long staff component.
            unsupported_local = (vc.window_mean(centres & ~supported & visible) > 0) & centres
            local_bad = np.bincount(local_labels, weights=unsupported_local[ys, xs], minlength=len(features)+1)
            supports &= local_bad[1:] == 0
            for index in np.flatnonzero(informative & ~supports):
                contradicts[index].add(oid)
            if can_qualify:
                for index in np.flatnonzero(supports):
                    if state not in supporter_states[index] and oid not in supporters[index] and len(supporters[index]) < 2:
                        supporters[index].append(oid)
                        supporter_states[index].add(state)
    missing_second = missing_second_obs != 0
    counters["source_minority_pixels"] = int(np.count_nonzero((missing_first != 0) & ~missing_second))
    for index, feature in enumerate(features):
        x0, y0, x1, y1 = feature["bbox"]
        obligation = centres[y0:y1, x0:x1] & feature["mask"]
        qualified = len(supporters[index]) == 2 and bool((pixel_second_obs[y0:y1, x0:x1][obligation] != 0).all())
        cert["features"].append(vc.feature_record(feature, supporters=supporters[index],
                                                 contradicts=sorted(contradicts[index]), qualified=qualified))
    unsupported = np.zeros(shape, bool)
    for feature in cert["features"]:
        if not feature["qualified"]:
            x0, y0, x1, y1 = feature["bbox"]
            unsupported[y0:y1, x0:x1] |= centres[y0:y1, x0:x1] & vc.unpack_mask(feature["mask"])
    source_findings = vc.group_findings(missing_second, "A", "fail", "SOURCE_FEATURE_MISSING_IN_STRIP",
                                        strip_id=strip_id, feature_ids=[])
    for finding in source_findings:
        detail = {"distinct_visibility_support": 2}
        if "bbox" in finding:
            a, b, c, d = finding["bbox"]
            group_mask = missing_second[b:d, a:c]
            # Actual witnesses of a failed window, rather than a duplicated list
            # of every witness anywhere in this strip.
            first_id = int(missing_first_obs[b:d, a:c][group_mask][0])
            second_id = int(missing_second_obs[b:d, a:c][group_mask][0])
            detail["witness_observation_ids"] = [obs_ids[first_id], obs_ids[second_id]]
        finding["detail"] = detail
    findings.extend(source_findings)
    findings.extend(vc.group_findings(unsupported, "A", "review_required", "STRIP_CONTENT_UNSUPPORTED",
                                      strip_id=strip_id, detail={"required_supporters": 2}))
    _attach_features(findings, features)
    counters["qualified_features"] = sum(f["qualified"] for f in cert["features"])
    counters["strong_features"] = sum(f["kind"] == "strong" for f in features)
    counters["weak_features"] = sum(f["kind"] == "weak" for f in features)
    counters["findings_by_code"] = dict(sorted((code, sum(f["code"] == code for f in findings))
                                              for code in {f["code"] for f in findings}))
    return cert
