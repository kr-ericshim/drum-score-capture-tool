"""Transactional jump repair from frozen analysis and recovered observation crops.

No sampling, tracking, registration or classification is called here. Revision folders
are unpublished until the caller verifies/installs the export and records its pointer.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np

from app.pipeline import observations as ob
from app.pipeline import reflow_jump as jump
from app.pipeline import reflow_strips as strips
from app.pipeline import system_tracking


class SeamRepairError(RuntimeError):
    def __init__(self, code, detail, status=409):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def original_analysis(reflow):
    return read(reflow["original_analysis_path"]) if reflow.get("original_analysis_path") else copy.deepcopy(reflow)


def run_index(system, by_id):
    parent = by_id.get(system.get("alternate_of")) if system.get("alternate_of") else system
    return ((parent or {}).get("strip", {}).get("jump") or {}).get("run")


def validate_request(reflow, systems, composed, payload):
    revision = int(reflow.get("revision", 1))
    if payload.base_revision is not None and payload.base_revision != revision:
        raise SeamRepairError("STALE_REVISION", f"expected revision {revision}, received {payload.base_revision}")
    committed = sorted(reflow.get("rejected_seam_ids") or [])
    desired = committed if payload.rejected_seam_ids is None else sorted(payload.rejected_seam_ids)
    if not desired and not committed:
        return {"desired": [], "changed_runs": [], "changed": False}
    original = original_analysis(reflow)
    try:
        source_jump = read(Path(original["workspace"]) / "jump.json")
    except FileNotFoundError as exc:
        raise SeamRepairError("SEAM_UNKNOWN", "this job has no recorded jump seams", 422) from exc
    seam_by = {s["id"]: s for s in source_jump.get("seams", [])}
    membership = [{d for c in r["panorama_chains"] for d in c["displays"]} for r in source_jump.get("runs", [])]
    seam_runs = {s["id"]: i for i, members in enumerate(membership) for s in seam_by.values()
                 if s["a"] in members and s["b"] in members}
    if len(desired) != len(set(desired)):
        raise SeamRepairError("SEAM_UNKNOWN", "duplicate seam ids are not supported", 422)
    for sid in desired:
        if sid not in seam_runs or jump.effective_seam_status(seam_by[sid]) not in ("resolved", "unverified"):
            raise SeamRepairError("SEAM_UNKNOWN", f"{sid} is not a resolved/unverified seam in this job's jump runs", 422)
    before = jump.apply_seam_rejections(source_jump, committed)
    after = jump.apply_seam_rejections(source_jump, desired)
    changed_runs = [i for i in range(len(membership))
                    if before["runs"][i]["panorama_chains"] != after["runs"][i]["panorama_chains"]]
    by_id = {s["id"]: s for s in systems}
    for ri in changed_runs:
        primary = [s for s in systems if not s.get("alternate_of") and run_index(s, by_id) == ri]
        primary.sort(key=lambda s: (s["strip"]["jump"]["chain"], s["strip"]["jump"]["chunk"]))
        selected = [s for s in composed if run_index(s, by_id) == ri]
        positions = [i for i, s in enumerate(composed) if run_index(s, by_id) == ri]
        if (not primary or [s["id"] for s in selected] != [s["id"] for s in primary]
                or positions != list(range(min(positions, default=0), min(positions, default=0) + len(primary)))):
            raise SeamRepairError("SEAM_REPAIR_SELECTION",
                                  f"run {ri + 1}: select every primary chunk together in chronological order, "
                                  "and unselect its alternate moments before rebuilding")
    return {"desired": desired, "changed_runs": changed_runs, "changed": desired != committed,
            "original": original, "jump": after, "source_jump": source_jump}


def _dependencies(source_jump, tracking, manifest, changed_runs):
    # The coverage gate may need unplaced displays outside the affected slot.
    # Recreate its original registered-slot dependencies as well as the run masks.
    slots = {s["slot_id"] for s in source_jump.get("slots", [])}
    slots.update(source_jump["runs"][i]["slot_id"] for i in changed_runs)
    eps = [e for slot, seq in jump.slot_sequences(tracking).items() if slot in slots for e in seq if e.get("confirmed")]
    ids = {oid for e in eps for oid in e["observation_ids"]}
    score = sorted([o for o in manifest["observations"] if o.get("system_regions")], key=lambda o: float(o["t_sec"]))
    if score:
        ids.update(score[i]["id"] for i in set(np.linspace(0, len(score)-1, min(len(score), strips.oc.CHROME_SAMPLES)).round().astype(int)))
    return eps, ids


def _public_system(occ, rec):
    return {"id": occ["id"], "index": occ["index"], "included": True, "auto_included": True,
            "strip_path": rec["path"], **{k: occ[k] for k in ("t_start", "t_end", "slot_id", "layout", "episode_ids", "first_display", "terminal_display")},
            "issues": occ["issues"] + rec.get("issues", []) + (["OVERLAY_UNRECOVERED"] if rec["unrecovered_columns"] else []),
            "strip": {k: v for k, v in rec.items() if k not in ("path", "ledger")}}


def _require_repaired_start_output(built):
    """A repaired start may not publish missing notation only as an alternate."""
    for _occ, rec in built:
        info = rec.get("jump") or {}
        trim = int(info.get("left_trim_native") or 0)
        if not trim or not info.get("unverified_seam_before"):
            continue
        first = info["owners"][0]["display"]
        preservation = info.get("preservation") or {}
        evidence = {(e["display"], tuple(e["box_crop"])): e
                    for e in preservation.get("start_trim_evidence", [])}
        for conflict in preservation.get("conflicts", []):
            if conflict["display"] != first or conflict["box_crop"][0] >= trim:
                continue
            item = evidence.get((first, tuple(conflict["box_crop"])))
            if item is None or item["unexplained_px"] > jump.PRESERVE_CONFIG["min_foreign_px"]:
                raise SeamRepairError("SEAM_REPAIR_INCOMPATIBLE",
                                      f"{first}: unexplained notation inside the repaired start's panel trim; "
                                      "the previous export is kept")


def rebuild_jump_runs(reflow, repair, order, composed, revision_dir, *, checkpoint, progress, logger):
    """Return a deep candidate and migrated order/selection. Never edit committed files."""
    from app.pipeline import reflow_pipeline as pipeline
    candidate = copy.deepcopy(reflow)
    original = repair["original"]
    original_workspace = Path(original["workspace"])
    current_workspace = Path(reflow["workspace"])
    revision_dir = Path(revision_dir)
    revision_dir.mkdir(parents=True, exist_ok=False)
    for name in ("manifest.json", "tracking.json", "manifest"):
        src = original_workspace / name
        if src.exists():
            (revision_dir / name).symlink_to(src.resolve(), target_is_directory=src.is_dir())
    if not candidate.get("original_analysis_path"):
        pipeline._dump(original, revision_dir / "original_analysis.json")
        candidate["original_analysis_path"] = str(revision_dir / "original_analysis.json")
    manifest = read(original_workspace / "manifest.json")
    # the jump view was analysed without the one-observation transient displays
    tracking = system_tracking.without_transient_displays(read(original_workspace / "tracking.json"))
    occurrences = read(current_workspace / "occurrences.json")
    chains = read(current_workspace / "ledger_chains.json")
    effective = repair["jump"]
    changed_runs = repair["changed_runs"]
    built = []
    ledger = bool(reflow.get("dev_ledger"))
    base = read(reflow.get("ledger_base_path") or current_workspace / "ledger_base.json") if ledger else {"displays": []}
    if changed_runs:
        cfg = repair["source_jump"].get("config")
        if not cfg or jump.config_hash(cfg) != repair["source_jump"].get("config_hash"):
            raise SeamRepairError("SEAM_REPAIR_INCOMPATIBLE", "saved jump configuration is missing or inconsistent")
        eps, ids = _dependencies(repair["source_jump"], tracking, manifest, changed_runs)
        obs_by = {o["id"]: o for o in manifest["observations"]}
        recovery = revision_dir / "recovery"
        baseline = revision_dir / "baseline"
        progress("recovering", 0.0)
        try:
            load = ob.recover_observation_images(original_workspace / "manifest", manifest, ids, recovery,
                                                  checkpoint=checkpoint, progress=lambda f: progress("recovering", f))
            composites, covered, fixed, displays = {}, {}, {}, {}
            for i, e in enumerate(eps):
                checkpoint()
                rec = jump.display_record(e, manifest, load, obs_by, cfg, keep_composite=True)
                composites[e["id"]] = rec.pop("composite")
                covered[e["id"]] = rec["covered"]
                displays.setdefault(e["slot_id"], []).append(rec)
                progress("rebuilding", 0.2 * (i+1) / len(eps))
            for slot, records in displays.items():
                mask, _ = jump.screen_fixed_pixels(records, cfg)
                if mask is not None:
                    fixed[slot] = mask
            # Same producers, original decisions: stop if any primary changes even one pixel.
            control = copy.deepcopy(repair["source_jump"])
            control["_fixed"] = fixed
            baseline_built = jump.build_jump_systems(control, tracking, manifest, baseline,
                                composites=composites, covered=covered, load=load, checkpoint=checkpoint,
                                run_indices=changed_runs, logger=logger)
            expected = {s["id"]: s for s in original["systems"] if not s.get("alternate_of")
                        and ((s.get("strip") or {}).get("jump") or {}).get("run") in changed_runs}
            if set(expected) != {o["id"] for o, _ in baseline_built}:
                raise SeamRepairError("SEAM_REPAIR_INCOMPATIBLE", "unchanged reconstruction changed chunk membership")
            for occ, rec in baseline_built:
                old = expected[occ["id"]]
                img = pipeline.cv2.imread(old["strip_path"])
                digest = old["strip"].get("uncut_pixels_sha256")
                if (img is None or not digest or pipeline._pixels_sha256(img) != digest
                        or rec["uncut_pixels_sha256"] != digest):
                    raise SeamRepairError("SEAM_REPAIR_INCOMPATIBLE", f"unchanged reconstruction differs for {occ['id']}")
            del baseline_built
            shutil.rmtree(baseline)
            progress("rebuilding", 0.4)
            effective["_fixed"] = fixed
            built = jump.build_jump_systems(effective, tracking, manifest, revision_dir / "strips",
                            composites=composites, covered=covered, load=load, checkpoint=checkpoint,
                            run_indices=changed_runs, logger=logger, ledger=ledger,
                            evidence_dir=revision_dir / "ledger_evidence" if ledger else None)
            _require_repaired_start_output(built)
            if ledger:
                # Dev-ledger raw obligations must remain independently resolvable after
                # temporary source recovery is removed. Normal jobs keep no raw cache.
                for obs in base.get("observations", []):
                    if obs["id"] not in ids:
                        continue
                    img = load(obs_by[obs["id"]])
                    if pipeline.rl.pixels_hash(img) != obs["pixels_sha256"]:
                        raise SeamRepairError("SEAM_REPAIR_INCOMPATIBLE", f"raw inventory differs for {obs['id']}")
                    path = Path(load.paths[obs["id"]])
                    if path.is_relative_to(recovery):
                        dest = revision_dir / "ledger_evidence" / "raw" / path.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, dest)
                        path = dest
                    obs["frame_path"] = str(path)
                    obs["frame_png_sha256"] = ob.file_sha256(path)
                    obs.pop("retained_frame_png_sha256", None)
            effective.update(_composites=composites, _covered=covered)
        finally:
            shutil.rmtree(recovery, ignore_errors=True)
            shutil.rmtree(baseline, ignore_errors=True)
    by_id = {s["id"]: s for s in order}
    removed = {s["id"] for s in order if run_index(s, by_id) in changed_runs}
    replacements, occ_replacements = {}, []
    fresh_records = []
    for occ, rec in built:
        occ["index"] = len(occ_replacements) + 1
        ri = rec["jump"]["run"]
        entry = _public_system(occ, rec)
        replacements.setdefault(ri, []).append(entry)
        occ_replacements.append(occ)
        fresh_records.append(rec)
        for alt in (rec.get("minority_content") or {}).get("alternates", []):
            alt_entry, alt_occ = pipeline.alternate_system(occ, rec, alt, None)
            replacements[ri].append(alt_entry)
            occ_replacements.append(alt_occ)
    candidate_order, seen = [], set()
    for s in order:
        ri = run_index(s, by_id)
        if ri in changed_runs:
            if ri not in seen and not s.get("alternate_of"):
                candidate_order.extend(replacements.get(ri, []))
                seen.add(ri)
        else:
            candidate_order.append(copy.deepcopy(s))
    # Selection migration follows run lineage, including when chunk IDs were reused.
    selected = []
    seen.clear()
    for s in composed:
        ri = run_index(s, by_id)
        if ri in changed_runs:
            if ri not in seen:
                selected.extend(s for s in replacements[ri] if not s.get("alternate_of"))
                seen.add(ri)
        else:
            selected.append(next(x for x in candidate_order if x["id"] == s["id"]))
    selected_ids = {s["id"] for s in selected}
    for i, s in enumerate(candidate_order):
        s.update(index=i+1, included=s["id"] in selected_ids)
    occurrences["systems"] = [o for o in occurrences["systems"] if o["id"] not in removed] + occ_replacements
    occ_by = {o["id"]: o for o in occurrences["systems"]}
    occurrences["systems"] = [dict(occ_by[s["id"]], index=s["index"], included=s["included"]) for s in candidate_order]
    chains = {sid: value for sid, value in chains.items() if sid not in removed}
    if ledger and built:
        base, fresh_chains = _replace_ledger(base, fresh_records, removed, pipeline)
        chains.update(fresh_chains)
    else:
        chains.update({rec["system_id"]: rec["ledger_chain"] for rec in fresh_records})
    for s in candidate_order:
        if s["id"] not in by_id or s["id"] in removed:
            if s.get("alternate_of"):
                pipeline._alternate_ledger_chain(base, chains, s, ledger=ledger)
    records = {s["id"]: dict(s["strip"], path=s["strip_path"]) for s in candidate_order}
    coverage = pipeline.leftover_gate(tracking, manifest, effective,
                                     exported=jump.exported_reference(occurrences["systems"], records))
    if coverage is not None:
        effective["coverage"] = coverage
        candidate["coverage"] = coverage
    pipeline._dump(occurrences, revision_dir / "occurrences.json")
    pipeline._dump(chains, revision_dir / "ledger_chains.json")
    jump.write_json(effective, revision_dir / "jump.json")
    if ledger:
        pipeline.rl.write_ledger(revision_dir / "ledger_base.json", base)
        candidate["ledger_base_path"] = str(revision_dir / "ledger_base.json")
    candidate.update(workspace=str(revision_dir), systems=candidate_order,
                     ledger_chains_path=str(revision_dir / "ledger_chains.json"),
                     rejected_seam_ids=repair["desired"],
                     jump_view=pipeline.jump_view_summary(effective, [(None, s["strip"]) for s in candidate_order if not s.get("alternate_of") and s["strip"].get("jump")]))
    # Repair findings stay in review. Keep the original missing-interval notices
    # on paper; changing a seam must not introduce a new repair warning in the PDF.
    candidate["seam_repair_pdf_coverage"] = copy.deepcopy(original.get("coverage"))
    # The summary expects system_id on strip records (as recorded by the producers).
    reasons = pipeline.source_review_reasons(candidate.get("source_class") or {}, candidate_order)
    if repair["desired"] and "JUMP_SEAM_UNVERIFIED" not in reasons:
        reasons.insert(0, "JUMP_SEAM_UNVERIFIED")
    candidate.update(review_reasons=reasons, review_required=bool(reasons))
    progress("rebuilding", 1.0)
    return candidate, candidate_order, selected


def _replace_ledger(base, records, removed, pipeline):
    """Replace affected producer displays/dispositions; old overlap equivalences cannot survive."""
    fragments = [r.get("ledger") or {} for r in records]
    replaced = {d["id"] for f in fragments for d in f.get("displays", [])} | {f"strip:{sid}" for sid in removed}
    old_items = {i["id"] for i in base.get("items", []) if i.get("display_id") in replaced}
    kept = copy.deepcopy(base)
    for key in ("displays", "items", "representations", "dispositions", "display_dispositions", "generated_origins", "occurrence_remaps"):
        kept[key] = [r for r in kept.get(key, []) if r.get("display_id") not in replaced
                     and r.get("retained_display_id") not in replaced and r.get("source_display_id") not in replaced
                     and r.get("item_id") not in old_items and r.get("id") not in replaced | old_items]
    def absolute_refs(fragment):
        root = fragment.pop("evidence_root", None)
        if not root:
            return
        def visit(value):
            if isinstance(value, dict):
                if "path" in value and "sha256" in value:
                    value["path"] = str((Path(root) / value["path"]).resolve())
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(fragment)
    absolute_refs(kept)
    for f in fragments:
        f["source_video"] = kept.get("source_video")
        absolute_refs(f)
    merged = pipeline.assembly.merge_ledgers(kept, *fragments)
    for f in fragments:
        pipeline.assembly.annotate(merged, f.get("observation_associations", []))
    chains = {r["system_id"]: r["ledger_chain"] for r in records}
    for r in records:
        r.pop("ledger", None)
    return merged, chains
