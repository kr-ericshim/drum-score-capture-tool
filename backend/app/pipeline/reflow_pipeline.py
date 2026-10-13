"""Clean reflow job pipeline (output model ``clean_reflow_v1``).

source video + applied ROI
  -> observation manifest (observations.py)
  -> display episodes + layout intervals (system_tracking.py)
  -> system occurrences in display order (reflow_occurrences.py)
  -> clean system strips (reflow_strips.py) -> established replay exclusions
  -> A4 page plan + rasters (reflow_layout.py, reflow_render.py)
  -> PNG/JPG/PDF (export.export_composed_pages, called by the app)

A jump-view run (reflow_jump: overlapping static displays registered seam by
seam) becomes panorama strips; any other horizontal-scroll interval (smooth
scroll) stops the pipeline with an explicit unsupported state (decided out of
scope, docs/reflow/DECISIONS.md). "Looks similar"
suggestions are computed after the job is marked done (bounded, cancellable)
and never block or change the chart.
"""

from __future__ import annotations

import json
import hashlib
import shutil
import logging
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import observations as ob
from app.pipeline import reflow_jump as rj
from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_ledger_assembly as assembly
from app.pipeline import reflow_labels as rlab
from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_render as rr
from app.pipeline import reflow_strips as rs
from app.pipeline import reflow_verify_common as vc
from app.pipeline import reflow_verify_plan as vb
from app.pipeline import reflow_verify_page as vp
from app.pipeline import source_class as scls
from app.pipeline import system_tracking as stk
from app.pipeline.process_control import OperationCancelled, report_progress

OUTPUT_MODEL = "clean_reflow_v1"
PIPELINE_VERSION = "reflow_pipeline-1"


class UnsupportedLayoutError(RuntimeError):
    """The source shows a layout this slice does not reflow (horizontal or vertical scroll)."""

    def __init__(self, intervals: List[Dict[str, Any]]):
        self.intervals = intervals
        spans = ", ".join(f"{iv.get('kind', 'unsupported')} {iv['start']:.1f}-{iv['end']:.1f}s" for iv in intervals)
        super().__init__(f"scrolling score is not supported ({spans})")


class NoSystemsError(RuntimeError):
    pass


class UnsupportedSourceError(RuntimeError):
    """The score is not on an opaque plate (source_class gate): notation composited over live
    imagery or a translucent plate. The opaque-paper adapter would keep the video in the strips, so the job stops
    with the gate's evidence (``source_class``: {class, evidence, version})."""

    code = "UNSUPPORTED_SOURCE"

    def __init__(self, source_class: Dict[str, Any]):
        self.source_class = source_class
        reason = (source_class.get("evidence") or {}).get("reason", "")
        super().__init__(f"{self.code}: {source_class.get('class')} is not supported ({reason})")


class DependencyUnavailableError(RuntimeError):
    """A strip the final order needs (the uncut strip of a system whose preview tail was cut
    toward a destination that is no longer the next placed system) is missing or damaged
    and could not be regenerated and verified. The composition stops: a page is never made
    from a cut strip whose destination is not the next placed system."""

    code = "UNCUT_STRIP_UNAVAILABLE"

    def __init__(self, system_id: str, reason: str, attempts: Optional[List[Dict[str, Any]]] = None):
        self.system_id = system_id
        self.reason = reason
        self.attempts = attempts or []
        super().__init__(f"{self.code}: uncut strip of {system_id} unavailable ({reason})")


def _pixels_sha256(img: np.ndarray) -> str:
    import hashlib
    return hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest()


def _usable_uncut(s: Dict[str, Any]) -> Tuple[bool, str]:
    """Is the recorded uncut strip file there, decodable, of the recorded size and (when the
    record has one) of the recorded pixel hash?"""
    strip = s.get("strip") or {}
    unc = strip.get("uncut") or {}
    path = unc.get("path")
    if not path or not Path(path).is_file():
        return False, "uncut_strip_missing"
    img = cv2.imread(str(path))
    if img is None:
        return False, "uncut_strip_unreadable"
    size = unc.get("size")
    if size and [int(img.shape[1]), int(img.shape[0])] != [int(size[0]), int(size[1])]:
        return False, "uncut_strip_size_differs"
    want = strip.get("uncut_pixels_sha256")
    if want and _pixels_sha256(img) != want:
        return False, "uncut_strip_damaged"
    return True, "ok"


def regenerate_uncut_strip(workspace: Path, s: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild the uncut strip of system ``s`` from the job's stored observations (frames on
    disk, else decoded again from the source at their times) and verify it before writing it
    to the recorded uncut path.

    Verified when its pixels hash to the recorded ``uncut_pixels_sha256``; a record without the
    hash (made before it was kept) is verified against the cut strip: same box left edge and
    every cut-strip pixel identical in the shared rows/columns. Returns
    ``{"regenerated": bool, "reason", ...}``; nothing is written unless verified."""
    from app.pipeline import reflow_strips as _rs
    workspace = Path(workspace)
    strip = s.get("strip") or {}
    unc = strip.get("uncut") or {}
    path = unc.get("path")
    out: Dict[str, Any] = {"system_id": s["id"], "regenerated": False}
    try:
        occ = json.loads((workspace / "occurrences.json").read_text())
        manifest = json.loads((workspace / "manifest.json").read_text())
        occ_s = next((x for x in occ["systems"] if x["id"] == s["id"]), None)
        if occ_s is None or not path:
            out["reason"] = "no_record_to_regenerate_from"
            return out
        load = stk.manifest_image_loader(workspace / "manifest", manifest)
        img, rec = _rs.build_strip(occ_s, manifest, load, next_systems=())
        img = rec.pop("_uncut_image", None) if rec.get("uncut") else img
    except Exception as exc:
        out["reason"] = f"regeneration_failed: {exc}"
        return out
    if img is None:
        out["reason"] = "regeneration_failed: no image"
        return out
    size = unc.get("size")
    if size and [int(img.shape[1]), int(img.shape[0])] != [int(size[0]), int(size[1])]:
        out["reason"] = "regenerated_size_differs"
        return out
    want = strip.get("uncut_pixels_sha256")
    if want:
        if _pixels_sha256(img) != want:
            out["reason"] = "regenerated_pixels_differ"
            return out
        out["verified_by"] = "pixel_hash"
    else:
        cut = cv2.imread(str(s.get("strip_path") or ""))
        ub, cb = unc.get("box_crop"), strip.get("box_crop")
        if cut is None or not ub or not cb or int(ub[0]) != int(cb[0]):
            out["reason"] = "cannot_verify_without_the_cut_strip"
            return out
        y0, y1 = max(int(ub[1]), int(cb[1])), min(int(ub[3]), int(cb[3]))
        w = min(int(cb[2]) - int(cb[0]), img.shape[1], cut.shape[1])
        a = img[y0 - int(ub[1]):y1 - int(ub[1]), :w]
        b = cut[y0 - int(cb[1]):y1 - int(cb[1]), :w]
        if y1 <= y0 or w <= 0 or a.shape != b.shape or not np.array_equal(a, b):
            out["reason"] = "regenerated_pixels_differ_from_the_cut_strip"
            return out
        out["verified_by"] = "cut_strip_pixels"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".regenerated.tmp.png")
    if not cv2.imwrite(str(tmp), img):
        out["reason"] = "write_failed"
        return out
    back = cv2.imread(str(tmp))
    if back is None or not np.array_equal(back, img):
        tmp.unlink(missing_ok=True)
        out["reason"] = "written_file_differs"
        return out
    tmp.replace(target)
    out.update(regenerated=True, reason="ok", path=str(target))
    return out


def _dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=lambda o: None))
    tmp.replace(path)


def classify_source_class(video_path: Path, roi: Sequence[Sequence[float]], start_sec: Optional[float],
                          end_sec: Optional[float], *, logger: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Source-class gate (source_class.py) on a few dozen seeked ROI frames. A gate that cannot
    run (decode failure) returns unknown; the job remains conditional for review."""
    try:
        res = scls.classify_source(Path(video_path), roi, float(start_sec or 0.0), end_sec)
    except Exception as exc:  # noqa: BLE001
        logger(f"source class gate skipped: {type(exc).__name__}: {exc}")
        return {"class": scls.CLASS_UNKNOWN, "evidence": {"reason": f"gate failed: {type(exc).__name__}"},
                "version": scls.VERSION}
    ev = res["evidence"]
    logger(f"source class: {res['class']} ({ev.get('reason', '')}; median off-plate {ev.get('median_off_plate')}, "
           f"textured {ev.get('median_textured')}, ink-like {ev.get('median_ink_like')})")
    return res


def analyse_source(
    *,
    video_path: Path,
    roi: Sequence[Sequence[float]],
    workspace: Path,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
    label_roi: Optional[Sequence[Sequence[float]]] = None,
    ledger: bool = False,
    logger: Callable[[str], None] = lambda _m: None,
    progress: Callable[[str, float], None] = lambda _s, _f: None,
    checkpoint: Callable[[], None] = lambda: None,
) -> Dict[str, Any]:
    """Manifest -> tracking -> occurrences -> strips. Returns the reflow record
    (systems with strip paths, fragments, layout) without composing pages.
    ``ledger`` (or REFLOW_DEV_LEDGER=1) opts into raw evidence for the offline verifier;
    lightweight chain/placement metadata remains available for every job."""
    ledger = ledger or os.environ.get("REFLOW_DEV_LEDGER") == "1"
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    source_cls = classify_source_class(video_path, roi, start_sec, end_sec, logger=logger)
    _dump(source_cls, workspace / "source_class.json")
    # a translucent plate shows the video through the notation like composited live imagery: the
    # opaque-paper adapter cannot tell video from ink there, so it is refused too (Pro #8, bF69 included)
    if source_cls["class"] == scls.CLASS_LIVE or scls.FLAG_TRANSLUCENT in (source_cls.get("flags") or []):
        raise UnsupportedSourceError(source_cls)
    checkpoint()
    mdir = workspace / "manifest"
    manifest = ob.build_manifest(
        video_path=Path(video_path), roi=roi, out_dir=mdir, start_sec=float(start_sec or 0.0), max_duration=end_sec,
        logger=logger, progress=lambda f: progress("sampling", f), checkpoint=checkpoint,
    )
    ob.write_manifest(manifest, workspace / "manifest.json")
    inventory = assembly.inventory_observations(manifest, mdir, source_video=str(manifest.get("video_id") or video_path)) if ledger else None
    checkpoint()
    load = stk.manifest_image_loader(mdir, manifest)
    progress("tracking", 0.0)
    tracking = stk.build_episodes(manifest, load, logger=logger)
    if ledger:
        assembly.annotate_from_tracking(inventory, tracking)
    _dump(tracking, workspace / "tracking.json")
    # Jump view (docs/archive/reflow/JUMP_PLAN.md): seams between consecutive displays are registered (reflow/jump.json).
    # Runs of verified/resolved jumps become panorama strips; a failure here falls back to the
    # tracker's own verdict (horizontal motion stays unsupported).
    jump: Optional[Dict[str, Any]] = None
    ev = workspace / "ledger_evidence" if ledger else None
    # the jump view works on the ordinary displays (one-observation transient displays are
    # short candidates of the occurrence stage only)
    jump_tracking = stk.without_transient_displays(tracking)
    try:
        jump = rj.analyse_jumps(jump_tracking, manifest, load, out_path=workspace / "jump.json", logger=logger,
                                checkpoint=checkpoint, keep_composites=True, ledger=ledger, evidence_dir=ev)
    except OperationCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        logger(f"jump registration skipped: {type(exc).__name__}: {exc}")
        jump = None
    runs = (jump or {}).get("runs") or []
    layout_gate(tracking, jump)  # refuses horizontal motion without a jump view before any strip work
    checkpoint()
    progress("assembling", 0.0)
    jump_eps = [i for r in runs for i in rj.run_episode_ids(r, jump_tracking)]
    occ = ro.build_occurrences(tracking, manifest, load, logger=logger, exclude_episode_ids=jump_eps, ledger=ledger, evidence_dir=ev)
    jump_built: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    if runs:
        jump_built = rj.build_jump_systems(jump, jump_tracking, manifest, workspace / "strips", composites=jump["_composites"],
                                           covered=jump["_covered"], load=load, logger=logger, checkpoint=checkpoint, ledger=ledger, evidence_dir=ev)
        occ = _merge_jump_occurrences(occ, [o for o, _r in jump_built])
    _dump(occ, workspace / "occurrences.json")
    if not any(s["included"] for s in occ["systems"]):
        raise NoSystemsError("no score system was found inside the applied region")
    page_occ = dict(occ, systems=[s for s in occ["systems"] if s.get("layout") != "jump_view"])
    strips = rs.build_strips(page_occ, manifest, load, workspace / "strips", logger=logger, checkpoint=checkpoint,
                             progress=lambda f: progress("cleaning", f), ledger=ledger) if page_occ["systems"] else []
    strips = strips + [r for _o, r in jump_built]
    aliases = [str(video_path), str(manifest.get("source_video") or ""), str((manifest.get("source") or {}).get("path") or "")]
    if not manifest.get("video_id"):
        aliases.extend(["manifest:unknown", "unknown_source"])
    ledger_started = time.perf_counter()
    if ledger:
        base, chains = _build_base_ledger(inventory, occ, strips, source_aliases=aliases)
    else:
        base = {"displays": []}
        chains = {r["system_id"]: (r["ledger_chain"] if isinstance(r["ledger_chain"], list) else [r["ledger_chain"]])
                  for r in strips if r.get("ledger_chain")}
    base_ledger_seconds = time.perf_counter() - ledger_started
    logger(f"base ledger build: {base_ledger_seconds:.3f}s")
    occ.pop("ledger", None)
    _dump(occ, workspace / "occurrences.json")
    by_id = {r["system_id"]: r for r in strips}
    # coverage of the leftover intervals, against what the chart actually exports: the included
    # systems after occurrence selection, with their strips written
    coverage = leftover_gate(jump_tracking, manifest, jump, exported=rj.exported_reference(occ["systems"], by_id))
    if jump is not None:
        if coverage is not None:
            jump["coverage"] = coverage
            rj.write_json(jump, workspace / "jump.json")
            for iv in coverage["intervals"]:
                logger(f"coverage: {iv['start']:.1f}-{iv['end']:.1f}s {iv['kind']}: {iv['status']}")
        jump.pop("_composites", None)
        jump.pop("_covered", None)
        jump.pop("_fixed", None)
    labels: Dict[str, Any] = {"status": "not_checked"}
    label_by: Dict[str, Dict[str, Any]] = {}
    if label_roi:
        # Section labels outside the score region, from the region the user applied.
        acquired = rlab.acquire_labels(page_occ["systems"], manifest, Path(video_path), label_roi, workspace / "labels",
                                       logger=logger, checkpoint=checkpoint)
        label_by = acquired["by_system"]
        s2c = manifest["source_to_crop"]
        for sid, lab in label_by.items():
            box = by_id[sid]["box_crop"]
            # label left edge in strip pixels (source -> crop pixels, work scale included)
            x_crop, _y = ob.source_to_crop_point(s2c, float(lab["bbox_source"][0]), float(lab["bbox_source"][1]))
            lab["x_in_strip"] = int(round(x_crop - box[0]))
        labels = {"status": "placed" if acquired["placed"] else "none_found", "label_roi": acquired["label_roi"],
                  "found": acquired["found"], "placed": acquired["placed"], "version": acquired["version"]}
    # Replay selection follows both leftover coverage and label acquisition:
    # coverage sees all original displays, and section-label evidence is kept.
    replay_blocks = []
    if occ.get("exclusions", {}).get("self_checks", {}).get("revisit_count", 0) >= 1:
        replay_blocks = ro.collapse_replay_blocks(
            [s for s in occ["systems"] if s.get("included", True)],
            {sid: rec["path"] for sid, rec in by_id.items()}, logger=logger, label_by=label_by,
        )
        # Candidates only by default (Pro checkpoint #5): a genuinely written A B C ... A B C passage passes
        # every test, so the user confirms by unticking. REFLOW_REPLAY_AUTO_EXCLUDE=1 excludes them (development).
        auto_exclude = os.environ.get("REFLOW_REPLAY_AUTO_EXCLUDE") == "1"
        occ.setdefault("exclusions", {})["replay_blocks"] = replay_blocks
        occ["exclusions"]["replay_mode"] = "auto_exclude" if auto_exclude else "candidate"
        replay_of = {entry["system_id"]: entry["replay_of"] for entry in replay_blocks}
        code = "REPLAY_COLLAPSED" if auto_exclude else "REPLAY_CANDIDATE"
        for s in occ["systems"]:
            if s["id"] in replay_of:
                if auto_exclude:
                    s["included"] = False
                if code not in s["issues"]:
                    s["issues"].append(code)
                s["replay_of"] = replay_of[s["id"]]
        _dump(occ, workspace / "occurrences.json")
    systems = []
    occ_systems = []
    for s in occ["systems"]:
        rec = by_id[s["id"]]
        occ_systems.append(s)
        systems.append({
            "id": s["id"],
            "index": s["index"],
            "included": s["included"],
            "auto_included": s["included"],
            **({"replay_of": s["replay_of"]} if s.get("replay_of") else {}),
            "strip_path": rec["path"],
            "t_start": s["t_start"],
            "t_end": s["t_end"],
            "slot_id": s["slot_id"],
            "layout": s["layout"],
            "episode_ids": s["episode_ids"],
            "first_display": s["first_display"],
            "terminal_display": s["terminal_display"],
            "issues": s["issues"] + rec.get("issues", []) + (["OVERLAY_UNRECOVERED"] if rec["unrecovered_columns"] > 0 else []),
            "strip": {k: v for k, v in rec.items() if k != "path"},
            **({"label": label_by[s["id"]]} if s["id"] in label_by else {}),
            **({k: s[k] for k in ("content_family", "possible_repeat_of", "possible_repeat_cleared", "repeat_cleared_with",
                                       "possible_repeat_chain") if k in s}),
        })
        # minority content the composite leaves out: each alternate is listed right after its
        # system, unchecked, so it can replace (or join) it in review
        for alt in (rec.get("minority_content") or {}).get("alternates", []):
            if (not s.get("included", True)
                    and "REPLAY_COLLAPSED" not in s.get("issues", [])):
                continue  # excluded candidates retain their bundle on their own record
            entry, occ_entry = alternate_system(s, rec, alt, label_by.get(s["id"]))
            _alternate_ledger_chain(base, chains, entry, ledger=ledger)
            systems.append(entry)
            occ_systems.append(occ_entry)
    # Minority moments are listed after their system in number order:
    # sys-001, sys-001-alt1, sys-001-alt2, ...
    order = _alternates_in_number_order(systems)
    if order != list(range(len(systems))):
        systems = [systems[i] for i in order]
        occ_systems = [occ_systems[i] for i in order]
    if len(occ_systems) != len(occ["systems"]) or [s["id"] for s in occ_systems] != [s["id"] for s in occ["systems"]]:
        occ = dict(occ, systems=occ_systems)
        _dump(occ, workspace / "occurrences.json")
    review_reasons = source_review_reasons(source_cls, systems)
    if ledger:
        rl.write_ledger(workspace / "ledger_base.json", base)
    _dump(chains, workspace / "ledger_chains.json")
    return {
        "version": PIPELINE_VERSION,
        "output_model": OUTPUT_MODEL,
        "workspace": str(workspace),
        "manifest_path": str(workspace / "manifest.json"),
        "dev_ledger": ledger,
        **({"ledger_base_path": str(workspace / "ledger_base.json")} if ledger else {}),
        "ledger_chains_path": str(workspace / "ledger_chains.json"),
        "base_ledger_seconds": base_ledger_seconds,
        "observations": len(manifest["observations"]),
        "layout_intervals": tracking.get("layout_intervals", []),
        "episodes": len(tracking.get("episodes", [])),
        "systems": systems,
        "fragments": occ["fragments"],
        "exclusions": occ.get("exclusions", {}),
        "labels": labels,
        "source_path": str(video_path),
        "source_range": [float(start_sec or 0.0), float(end_sec) if end_sec else None],
        "applied_roi": [list(map(float, p)) for p in roi],
        "source_class": source_cls,
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
        "continuity_suggestions": occ.get("continuity_suggestions", []),
        "duplicate_suggestions": [
            {"system_id": entry["system_id"], "of_system_id": entry["replay_of"],
             "reason": "looks_similar", "basis": "replay_block"} for entry in replay_blocks
        ],
        **({"jump_view": jump_view_summary(jump, jump_built)} if runs else {}),
        **({"coverage": coverage} if coverage is not None else {}),
        "_manifest": manifest,
        "_load": load,
    }


def _build_base_ledger(inventory: dict, occurrences: dict, records: Sequence[dict], *,
                       source_aliases: Sequence[str] = ()) -> Tuple[dict, dict]:
    """Merge producer evidence before removing large fragments from job records."""
    fragments = [occurrences.get("ledger") or {}] + [r.get("ledger") or {} for r in records]
    aliases = {inventory.get("source_video"), *source_aliases}
    canonical = []
    for fragment in fragments:
        source = fragment.get("source_video")
        if source is not None and source in aliases:
            fragment = dict(fragment, source_video=inventory["source_video"])
        canonical.append(fragment)
    base = assembly.merge_ledgers(inventory, *canonical)
    for fragment in fragments:
        assembly.annotate(base, fragment.get("observation_associations", []))
    chains = {}
    for rec in records:
        chain = rec.get("ledger_chain")
        if chain:
            chains[rec["system_id"]] = chain if isinstance(chain, list) else [chain]
        supersedes = rec.get("ledger_supersedes")
        if isinstance(supersedes, str) and supersedes.startswith("occ:") and not any(
                d.get("kind") == "superseded_inventory" and d.get("display_id") == supersedes
                for d in base["display_dispositions"]):
            retained = (rec.get("ledger") or {}).get("displays", [])
            for display in retained:
                base["display_dispositions"].append({"kind": "superseded_inventory", "terminal": "equivalent_observation",
                    "display_id": supersedes, "retained_display_id": display["id"]})
        rec.pop("ledger", None)
    superseded = {d["display_id"] for d in base["display_dispositions"] if d.get("kind") == "superseded_inventory"}
    base["display_dispositions"] = [d for d in base["display_dispositions"]
        if not (d.get("kind") == "display_unresolved" and d["display_id"] in superseded)]
    return base, chains


def rebuild_jump_runs(reflow, repair, order, composed, revision_dir, *, checkpoint, progress, logger):
    """Rebuild selected original run lineages in an unpublished revision workspace."""
    from app.pipeline.reflow_seam_reject import rebuild_jump_runs as rebuild
    return rebuild(reflow, repair, order, composed, revision_dir,
                   checkpoint=checkpoint, progress=progress, logger=logger)


def _alternate_ledger_chain(base: dict, chains: dict, entry: dict, *, ledger: bool = True) -> None:
    did = f"strip:{entry['id']}"
    strip = entry["strip"]
    if (ledger and not any(d["id"] == did for d in base["displays"])) or not strip.get("ledger_canvas_box_crop"):
        return
    origin, final = strip["ledger_canvas_box_crop"], strip["box_crop"]
    chains[entry["id"]] = [{"display_id": did, "strip_id": entry["id"], "stages": [
        {"stage": "display_to_strip", "kind": "affine",
         "matrix": [[1, 0, origin[0]-final[0]], [0, 1, origin[1]-final[1]], [0, 0, 1]]}]}]


def source_review_reasons(source_cls: Dict[str, Any], systems: Sequence[Dict[str, Any]]) -> List[str]:
    """Allowlisted complete classes; missing, unknown and future classes fail closed."""
    reasons = list(source_cls.get("review_reasons") or [])
    if source_cls.get("class") not in (scls.CLASS_LIGHT_PAPER, scls.CLASS_DARK_PAPER):
        reasons.append("SOURCE_CLASS_UNKNOWN")
    if scls.FLAG_TRANSLUCENT in source_cls.get("flags", []):
        reasons.append(rs.TRANSLUCENT_PLATE_GRAY)
    for system in systems:
        dc = ((system.get("strip") or {}).get("finishing") or {}).get("dark_cleanup") or {}
        if dc.get("plate") == "translucent" or dc.get("forced_opaque"):
            reasons.append(rs.TRANSLUCENT_PLATE_GRAY)
        reasons.extend(i for i in system.get("issues", []) if i in (
            "OVERLAY_UNRECOVERED", "OVERLAY_COVERS_NOTATION",
            rs.TRANSLUCENT_PLATE_GRAY, rs.UNCERTAIN_MARK_KEPT, rs.SOURCE_CLIPPED,
            rs.LOW_CONTRAST_KEPT, rs.CONTENT_LOST_IN_FINISHING))
        if (system.get("strip") or {}).get("unrecovered_columns", 0) > 0:
            reasons.append("OVERLAY_UNRECOVERED")
        if rj.JUMP_SEAM_UNVERIFIED in system.get("issues", []) and system.get("included", True):
            # a printed line next to an unverified view jump: a measure may repeat or be missing
            reasons.append(rj.JUMP_SEAM_UNVERIFIED)
    return sorted(set(reasons))


def layout_gate(tracking: Dict[str, Any], jump: Optional[Dict[str, Any]]) -> None:
    """Without a jump-view run, any unsupported tracker interval (horizontal or vertical scroll) refuses the
    job (``UnsupportedLayoutError``), before any occurrence or strip work."""
    runs = (jump or {}).get("runs") or []
    if not runs:
        unsupported = [iv for iv in tracking.get("layout_intervals", []) if not iv.get("supported", True)]
        if unsupported:
            raise UnsupportedLayoutError(unsupported)


def leftover_gate(tracking: Dict[str, Any], manifest: Dict[str, Any], jump: Optional[Dict[str, Any]], *,
                  exported: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Layout gate (``layout_gate``), then, with a jump-view run, each leftover interval accounted
    for on its own (``reflow_jump.account_coverage``) against ``exported``
    (``reflow_jump.exported_reference``: the included systems whose strips were written, i.e.
    after occurrence selection and strip building): the recovered work goes ahead and an
    unresolved interval only marks the result incomplete. Returns the coverage record (None: no
    jump view). With no exported reference nothing counts as output."""
    layout_gate(tracking, jump)
    if not (jump or {}).get("runs"):
        return None
    return rj.account_coverage(tracking, manifest, jump, exported=exported or {"systems": [], "page": {}, "chains": []})


def _merge_jump_occurrences(occ: Dict[str, Any], jump_occ: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Jump-view strips go into the system list in video order (before the first page system
    shown after them); every system is then numbered in that order."""
    systems = list(occ["systems"])
    for j in sorted(jump_occ, key=lambda x: (x["t_start"], x["id"])):
        at = next((i for i, s in enumerate(systems) if s.get("layout") != "jump_view"
                   and float(s.get("order_t", s["t_start"])) > float(j["t_start"])), len(systems))
        # keep the jump strips of one run together and in order
        while at > 0 and systems[at - 1].get("layout") == "jump_view" and systems[at - 1]["t_start"] > j["t_start"]:
            at -= 1
        systems.insert(at, j)
    for i, s in enumerate(systems):
        s["index"] = i + 1
    return dict(occ, systems=systems)


def jump_view_summary(jump: Dict[str, Any], built: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Any]:
    """``result.reflow.jump_view``: what the jump-view runs became."""
    seams = jump.get("seams") or []
    return {
        "version": jump.get("version"), "config_hash": jump.get("config_hash"),
        "runs": [{"start": r["start"], "end": r["end"], "displays": sum(len(c["displays"]) for c in r["panorama_chains"]),
                  "chains": len(r["panorama_chains"]), "still_unverified_seam_ids": r.get("still_unverified_seam_ids", [])}
                 for r in jump.get("runs") or []],
        "seams": len(seams),
        "verified": sum(1 for s in seams if rj.effective_seam_status(s) == "verified"),
        "resolved": sum(1 for s in seams if rj.effective_seam_status(s) == "resolved"),
        "unverified": sum(1 for s in seams if rj.effective_seam_status(s) == "unverified"),
        "strips": [r["system_id"] for _o, r in built],
        "flagged_strips": [r["system_id"] for _o, r in built if rj.JUMP_SEAM_UNVERIFIED in r.get("issues", [])],
    }


MINORITY_ALTERNATE = "MINORITY_ALTERNATE"


def _alternates_in_number_order(systems: Sequence[Dict[str, Any]]) -> List[int]:
    """Indexes of ``systems`` with the run of alternates right after each system (all
    ``alternate_of`` it) sorted by their ``-altN`` number; everything else keeps its place."""
    def number(s: Dict[str, Any]) -> int:
        tail = str(s["id"]).rsplit("-alt", 1)
        return int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else 0

    out: List[int] = []
    i, n = 0, len(systems)
    while i < n:
        out.append(i)
        j = i + 1
        while j < n and systems[j].get("alternate_of") == systems[i]["id"]:
            j += 1
        out.extend(sorted(range(i + 1, j), key=lambda k: number(systems[k])))
        i = j
    return out


def alternate_system(s: Dict[str, Any], rec: Dict[str, Any], alt: Dict[str, Any], label: Optional[Dict[str, Any]]
                     ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The system record (and its occurrence record) of an alternate strip that shows minority
    content of system ``s`` (reflow_strips.build_alternates). It is not included by default.
    The alternate keeps any preview tail on its strip (it is never cut); its section label is
    the label of ``s`` (same section, placed above whichever of the two comes first)."""
    parent = alt.get("parent_id") or s["id"]
    aid = f"{parent}-{alt['suffix']}"
    dy = int(rec["box_crop"][1]) - int(alt["box_crop"][1])
    issues = [MINORITY_ALTERNATE, rs.UNCERTAIN_MARK_KEPT] + list((alt.get("finishing") or {}).get("issues", []))
    tail = None
    if rec.get("preview_tail"):
        tail = {"cut": False, "verified": False, "reason": "alternate_keeps_the_tail"}
        issues.append("PREVIEW_TAIL_UNVERIFIED")
    strip = {
        "system_id": aid,
        "alternate_of": parent,
        "box_crop": list(alt["box_crop"]),
        "size": list(alt["size"]),
        "staff_gap_px": rec["staff_gap_px"],
        "staff_y_strip": [round(float(y) + dy, 2) for y in rec["staff_y_strip"]],
        "inverted": alt.get("inverted", rec.get("inverted")),
        "paper_flattened": alt.get("paper_flattened"),
        "preview_tail": tail,
        "issues": list(issues),
        "minority_alternate": {k: v for k, v in alt.items() if k != "path"},
        "finishing": alt.get("finishing", {}),
        "uncut_pixels_sha256": None,
    }
    if alt.get("ledger_canvas_box_crop") is not None:
        strip["ledger_canvas_box_crop"] = list(alt["ledger_canvas_box_crop"])
    # Page-display alternates retain the same source-edge warning when their
    # window includes that edge. Jump alternates have display coordinates, so
    # they use their own diagnostic rather than a panorama-column offset.
    clipped = alt.get("source_clipped")
    if clipped is None and not rec.get("jump") and rec.get("source_clipped"):
        source = rec["source_clipped"]
        sides = [side for side in source["sides"] if
                 (side == "top" and alt["box_crop"][1] <= rec["box_crop"][1]) or
                 (side == "bottom" and alt["box_crop"][3] >= rec["box_crop"][3]) or
                 (side == "left" and alt["box_crop"][0] <= rec["box_crop"][0]) or
                 (side == "right" and alt["box_crop"][2] >= rec["box_crop"][2])]
        offset = int(rec["box_crop"][0]) - int(alt["box_crop"][0])
        columns = [max(0, source["columns"][0] + offset), min(alt["size"][0], source["columns"][1] + offset)]
        if sides and columns[0] < columns[1]:
            clipped = {"sides": sides, "columns": columns}
    if clipped:
        issues.append(rs.SOURCE_CLIPPED)
        strip["source_clipped"] = clipped
        strip["issues"] = list(issues)
    entry = {
        "id": aid,
        "index": s["index"],
        "included": False,
        "alternate_of": parent,
        "alternate_kind": alt.get("kind", "minority_content"),
        "review_bundle": alt if alt.get("kind") == "uncertain_mark_bundle" else None,
        "strip_path": alt["path"],
        "t_start": alt["t_start"],
        "t_end": alt["t_end"],
        "slot_id": s["slot_id"],
        "layout": s["layout"],
        "episode_ids": s["episode_ids"],
        "first_display": False,
        "terminal_display": False,
        "issues": issues,
        "strip": strip,
    }
    if label and label.get("path"):
        entry["label"] = dict(label, repeats_system_id=label.get("repeats_system_id") or s["id"], placed=False)
    obs_ep = {o["obs_id"]: o.get("episode_id") for o in s.get("observations", [])}
    occ_entry = {k: v for k, v in s.items() if k not in ("observations",)}
    occ_entry.update(id=aid, included=False, alternate_of=parent, t_start=alt["t_start"], t_end=alt["t_end"],
                     first_display=False, terminal_display=False, issues=[MINORITY_ALTERNATE],
                     observations=[{"obs_id": o, "region_id": r, "episode_id": obs_ep.get(o)}
                                   for o, r in zip(alt["obs_ids"], alt["region_ids"])])
    return entry, occ_entry


def duplicate_suggestions(record: Dict[str, Any], *, logger: Callable[[str], None] = lambda _m: None,
                          should_stop: Callable[[], bool] = lambda: False) -> List[Dict[str, Any]]:
    """"Looks similar" suggestions (appearance only, never applied), computed after
    the job is done from the cleaned strips: a later system whose whole display
    (notation and all text) matches an earlier one, plus tracker continuity
    matches that were not accepted as the same display. ``should_stop`` ends the
    work early (time budget / cancel)."""
    # Preserve established replay pairs when the post-job suggestions replace
    # the initial list; excluded replay systems are absent from 'included'.
    out = [
        {"system_id": entry["system_id"], "of_system_id": entry["replay_of"],
         "reason": "looks_similar", "basis": "replay_block"}
        for entry in record.get("exclusions", {}).get("replay_blocks", [])
    ]
    replay_ids = {x["system_id"] for x in out}
    out.extend(dict(x) for x in record.get("continuity_suggestions", []) if x["system_id"] not in replay_ids)
    occ_path = Path(record["workspace"]) / "occurrences.json"
    if not occ_path.is_file():
        return out
    occ = json.loads(occ_path.read_text())
    included = [s for s in occ["systems"] if s["included"]]
    strip_of = {s["id"]: s["strip_path"] for s in record.get("systems", []) if s.get("strip_path")}
    seen = {x["system_id"] for x in out}
    for x in ro.suggest_similar_strips(included, strip_of, logger=logger, should_stop=should_stop):
        if x["system_id"] not in seen:
            out.append(x)
    return out


def check_labels_outside(record: Dict[str, Any], *, should_stop: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """For a job without a label region: are section labels drawn outside the score
    region? Returns the updated ``labels`` record (``LABELS_OUTSIDE_ROI`` with the
    suggested region as an editable draft, or ``none_outside``). When ``should_stop``
    ends the check (time budget / cancel) the status stays ``not_checked`` with
    ``check: "incomplete"``."""
    labels = dict(record.get("labels") or {})
    if labels.get("status") != "not_checked" or not record.get("source_path") or not record.get("applied_roi"):
        return labels
    lo, hi = (record.get("source_range") or [0.0, None])[:2]
    found = rlab.suggest_for_video(Path(record["source_path"]), record["applied_roi"], start_sec=lo or 0.0, end_sec=hi,
                                   should_stop=should_stop)
    if found.get("status") == "incomplete" or should_stop():
        labels.update(check="incomplete", evidence={k: v for k, v in found.items() if k != "status"})
        return labels
    if found.get("status") == "suggested":
        labels.update(status="LABELS_OUTSIDE_ROI", suggested_label_roi=found["label_roi"], evidence=found.get("evidence", {}))
    else:
        labels.update(status="none_outside", evidence={"reason": found.get("reason")})
    return labels


def persist_ledger_evidence(record: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the job's pre-cleanup ledger and referenced alternatives outside exports.

    This is persistence, never a reconstruction of obligations from cleaned strips.
    Missing hooks stay unassessed. An unreadable persisted ledger prevents pruning.
    """
    workspace = Path(record["workspace"])
    path = workspace / "ledger.json"
    if isinstance(record.get("ledger"), dict):
        ledger = json.loads(json.dumps(record["ledger"]))
    else:
        source = Path(record.get("ledger_path") or path)
        ledger = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else {}
    # A review alternative may otherwise disappear when a staged export or raw
    # frame directory is removed. Preserve its actual bytes, not just its name.
    for disposition in ledger.get("dispositions", []):
        if not disposition.get("review_artifact"):
            continue
        source = Path(disposition["review_artifact"])
        if not source.is_file():
            continue  # verifier reports missing evidence; no invented artifact
        data = source.read_bytes()
        target = workspace / "ledger_evidence" / (hashlib.sha256(data).hexdigest() + source.suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            target.write_bytes(data)
        disposition["review_artifact"] = str(target)
    workspace.mkdir(parents=True, exist_ok=True)
    _dump(ledger, path)
    record["ledger_path"] = str(path)
    if "ledger" in record:
        record["ledger"] = ledger
    return ledger


def _removed_dispositions(ledger: dict, sink: dict, workspace: Path) -> None:
    """Only unplaced raw hypotheses need a removal alternative; replicas discharge them."""
    by_display, by_strip = {}, {}
    for chain in sink.get("chains", []):
        by_display.setdefault(chain["display_id"], []).append(chain)
    for placement in sink.get("placements", []):
        by_strip.setdefault(placement["strip_id"], []).append(placement)
    removed = {}
    for rec in sink.get("removed", sink.get("ledger_removed", [])):
        removed.setdefault(rec["strip_id"], []).append(rec)
    represented = {r["item_id"] for r in ledger["representations"]}
    dispositioned = {d["item_id"] for d in ledger["dispositions"]}
    resolver = rl.EvidenceResolver(ledger)
    for item in ledger["items"]:
        if item.get("partitioned_into") or item["id"] in represented or item["id"] in dispositioned:
            continue
        if not rl.mark_masks(item):
            item["delivery_obligation"] = "faint_only"
            continue
        mask = rl.unpack_crop(item["foreground_hypothesis"]) > 0
        yy, xx = np.nonzero(mask)
        points = np.column_stack((xx+item["display_bbox"][0], yy+item["display_bbox"][1], np.ones(len(xx))))
        hit = None
        for chain in by_display.get(item["display_id"], []):
            sid = chain["strip_id"]
            strip_points = points @ np.asarray(chain["stages"][0]["matrix"], float).T
            for rec in removed.get(sid, []):
                for placement in by_strip.get(sid, []):
                    if placement["line_id"] != rec.get("line_id", placement["line_id"]):
                        continue
                    stage = placement["stages"][0]
                    projected = strip_points @ np.asarray(stage.get("pre_matrix", np.eye(3)), float).T
                    a, b, c, d = rec["src_bbox_R"]
                    if np.any((projected[:,0] >= a) & (projected[:,0] < c) & (projected[:,1] >= b) & (projected[:,1] < d)):
                        hit = rec
                        break
                if hit:
                    break
            if hit:
                break
        # Crops not reported as column removals still cannot discharge raw ink.
        if hit is None and item.get("partition_of") and any(p["stages"][0]["kind"] == "piecewise"
                for c in by_display.get(item["display_id"], []) for p in by_strip.get(c["strip_id"], [])):
            hit = {"op": "unmapped_crop"}
        if hit is None:
            continue
        try:
            view = next(resolver.views(item))
        except (ValueError, StopIteration) as exc:
            ledger["display_dispositions"].append({"kind": "display_unresolved", "terminal": "unresolved",
                "display_id": item["display_id"], "reason": f"REMOVAL_EVIDENCE_UNAVAILABLE:{exc}"})
            continue
        raw = rl.unpack_crop(view["raw_patch"])
        artifact = workspace / "ledger_evidence" / f"removed_{view['raw_patch']['sha256']}.png"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(artifact), raw):
            raise OSError(f"cannot retain removal evidence: {artifact}")
        ledger["dispositions"].append({"item_id": item["id"], "kind": "unresolved_alternative", "terminal": "unresolved",
            "observation_id": view["observation_id"], "review_artifact": str(artifact), "reason": f"REMOVED_BY_{hit['op']}",
            "removal": hit})


def _user_exclusions(ledger: dict, sink: dict) -> None:
    excluded = set(sink.get("excluded_system_ids", []))
    if not excluded:
        return
    owners = {}
    for sid, chains in sink.get("all_chains", {}).items():
        for chain in chains:
            owners.setdefault(chain["display_id"], set()).add(sid)
    for remap in ledger.get("occurrence_remaps", []):
        if remap.get("final_system_id"):
            owners.setdefault(remap["display_id"], set()).add(remap["final_system_id"])
    superseded, _ = rl.verified_supersedes(ledger)
    for did, retained in superseded.items():
        owners.setdefault(did, set()).update(owners.get(retained, set()))
    represented = {r["item_id"] for r in ledger["representations"]}
    placed_displays = {i["display_id"] for i in ledger["items"] if i["id"] in represented}
    for did, sids in owners.items():
        if sids and sids <= excluded and did not in placed_displays:
            ledger["display_dispositions"] = [d for d in ledger["display_dispositions"] if d["display_id"] != did]
            ledger["display_dispositions"].append({"kind": "user_excluded", "terminal": None,
                "display_id": did, "system_id": sorted(sids)[0]})


def _finalize_export_terminals(ledger: dict) -> None:
    excluded = {d["display_id"] for d in ledger["display_dispositions"] if d.get("kind") == "user_excluded"}
    if not excluded:
        assembly.finalize_terminals(ledger)
        return
    # An observation can show several systems. Only its selected obligations
    # determine its export terminal; the full inventory/annotations stay intact.
    items = ledger["items"]
    associations = [o["associations"] for o in ledger["observations"]]
    try:
        ledger["items"] = [i for i in items if i["display_id"] not in excluded]
        for obs in ledger["observations"]:
            obs["associations"] = [a for a in obs["associations"] if a.get("display_id") not in excluded]
        assembly.finalize_terminals(ledger)
    finally:
        ledger["items"] = items
        for obs, original in zip(ledger["observations"], associations):
            obs["associations"] = original


def build_delivered_ledger(record: dict, sink: dict) -> dict:
    """Build raw-to-page evidence; unexpected errors remain ledger failures."""
    try:
        return _build_delivered_ledger(record, sink)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception("delivered ledger assembly failed")
        return _ledger_error_inventory(record, exc)


def _ledger_error_inventory(record: dict, exc: Exception) -> dict:
    try:
        path = Path(record.get("ledger_base_path") or Path(record.get("workspace") or ".") / "ledger_base.json")
        ledger = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(ledger, dict):
            raise ValueError("ledger inventory must be a dictionary")
        for key in ("items", "displays", "observations", "representations", "dispositions", "display_dispositions", "generated_origins"):
            if not isinstance(ledger.setdefault(key, []), list):
                raise ValueError(f"ledger inventory {key} must be a list")
    except Exception:  # noqa: BLE001
        ledger = {"version": rl.VERSION, "items": [], "displays": [], "observations": [],
                  "representations": [], "dispositions": [], "display_dispositions": [], "generated_origins": []}
    ledger["verifier_error"] = {"severity": "fail", "code": "LEDGER_VERIFIER_ERROR",
                               "detail": f"{type(exc).__name__}: {exc}"}
    return ledger


def _build_delivered_ledger(record: dict, sink: dict) -> dict:
    """Start every export from immutable raw inventory, never an earlier page ledger."""
    workspace = Path(record["workspace"])
    path = Path(record.get("ledger_base_path") or workspace / "ledger_base.json")
    ledger = json.loads(path.read_text(encoding="utf-8"))
    restored = {f"strip:{sid}" for sid, variant in sink.get("variants", {}).items() if variant == "uncut"}
    ledger["display_dispositions"] = [d for d in ledger.get("display_dispositions", []) if not (
        d.get("display_id") in restored and (d.get("evidence") or {}).get("method") == "verify_removed_pixels")]
    assembly.assemble_representations(ledger, sink.get("chains", []), sink.get("placements", []))
    # A replica placement specifies a distinct written copy. Partitioning keeps
    # that expectation local to the pixels actually routed into each copy.
    by_item = {}
    for rep in ledger["representations"]:
        by_item.setdefault(rep["item_id"], []).append(rep)
    for item in ledger["items"]:
        reps = by_item.get(item["id"], [])
        copies = sorted({r["copy_index"] for r in reps})
        if copies:
            item["expected_multiplicity"] = max(item["expected_multiplicity"], len(copies))
            for rep in reps:
                rep["copy_index"] = copies.index(rep["copy_index"])
    _removed_dispositions(ledger, sink, workspace)
    assembly.resolve_generated(ledger, sink.get("chains", []), sink.get("generated", []))
    for rec in sink.get("unavailable", []):
        did = rec["display_id"]
        if not any(d["id"] == did for d in ledger["displays"]):
            ledger["displays"].append({"id": did, "observations": [], "shape": [0, 0]})
        ledger["display_dispositions"] = [d for d in ledger["display_dispositions"] if d["display_id"] != did]
        ledger["display_dispositions"].append({"kind": "display_unresolved", "terminal": "unresolved",
            "display_id": did, "reason": f"CHAIN_UNAVAILABLE:{rec['variant']}"})
    _user_exclusions(ledger, sink)
    _finalize_export_terminals(ledger)
    return ledger


def _review_witness(resolver: rl.EvidenceResolver, item: dict, disposition: dict) -> Optional[dict]:
    clear = disposition.get("clear_observation_id")
    if not clear:
        supported = next(resolver.views(item, supporting_only=True), None)
        return supported if supported is not None else next(resolver.views(item), None)
    fallback = None
    for view in resolver.views(item):
        if fallback is None:
            fallback = view
        if clear and view["observation_id"] == clear:
            return view
        if not clear and view.get("eligible") and view.get("supports"):
            return view
    return fallback


def _review_native_frame(resolver: rl.EvidenceResolver, item: dict, view: dict) -> Tuple[np.ndarray, np.ndarray]:
    """Frame pixel centres -> display centres, including referenced canvas resize."""
    tf = np.asarray(view["transform"]["matrix"], float).reshape(3, 3)
    member = next((m for m in resolver.members(item) if m["observation_id"] == view["observation_id"]), {})
    obs = resolver.observations.get(view["observation_id"], {})
    if obs.get("frame_path"):
        frame = resolver._read(obs["frame_path"], obs.get("retained_frame_png_sha256", obs.get("frame_png_sha256")), obs.get("pixels_sha256"))
        ref = member.get("frame_ref")
        if ref:
            a, b, c, d = ref["crop_box"]
            h, w = resolver.displays[item["display_id"]]["shape"]
            sx, sy = float(w)/(c-a), float(h)/(d-b)
            tf = tf @ np.array([[sx, 0, (sx-1)/2-sx*a], [0, sy, (sy-1)/2-sy*b], [0, 0, 1]])
        elif member.get("canvas_ref"):
            frame = resolver._read(resolver.root/member["canvas_ref"]["path"], member["canvas_ref"]["sha256"])
        return frame, tf
    if member.get("canvas_ref"):
        ref = member["canvas_ref"]
        return resolver._read(resolver.root/ref["path"], ref["sha256"]), tf
    # Embedded v1 evidence may retain only a raw patch, not its full frame.
    a, b = view["native_bbox"][:2]
    return rl.unpack_crop(view["raw_patch"]), tf @ np.array([[1, 0, a], [0, 1, b], [0, 0, 1]])


def _review_page_points(points: np.ndarray, transforms: Sequence[dict]) -> Tuple[np.ndarray, np.ndarray]:
    valid = np.ones(len(points), bool)
    for stage in transforms:
        if stage["kind"] == "affine":
            points = points @ np.asarray(stage["matrix"], float).T
        elif stage["kind"] == "piecewise":
            points = points @ np.asarray(stage.get("pre_matrix", np.eye(3)), float).T
            mapped, owned = points.copy(), np.zeros(len(points), np.int32)
            for piece in stage["pieces"]:
                a, b, c, d = piece["src_bbox"]
                selected = (points[:,0] >= a) & (points[:,0] < c) & (points[:,1] >= b) & (points[:,1] < d)
                mapped[selected] = points[selected] @ np.asarray(piece["matrix"], float).T
                owned += selected
            points, valid = mapped, valid & (owned == 1)
        else:
            raise ValueError("unsupported review transform")
    return points, valid & np.isfinite(points).all(axis=1)


def _review_crop_pair(resolver: rl.EvidenceResolver, item: dict, view: dict, representation: Optional[dict],
                      pages: Sequence[np.ndarray], gap: float) -> Tuple[np.ndarray, Optional[np.ndarray], float]:
    """Native-coordinate pairs: page pixels are sampled back onto the raw crop grid."""
    frame, frame_to_display = _review_native_frame(resolver, item, view)
    a, b, c, d = item["display_bbox"]
    corners = np.array([[a,b,1], [c,b,1], [a,d,1], [c,d,1]]) @ np.linalg.inv(frame_to_display).T
    native_gap = gap/max(1e-9, float(np.linalg.norm(frame_to_display[:2,1])))
    lo = np.maximum(0, np.floor(corners[:,:2].min(axis=0)-2*native_gap).astype(int))
    hi = np.minimum([frame.shape[1], frame.shape[0]], np.ceil(corners[:,:2].max(axis=0)+2*native_gap).astype(int))
    w, h = hi-lo
    if min(w, h) <= 0:
        raise ValueError("review crop outside raw frame")
    scale = min(1., 480./max(w, h))
    width, height = max(1, int(math.floor(w*scale))), max(1, int(math.floor(h*scale)))
    xx, yy = np.meshgrid(lo[0]+(np.arange(width)+.5)/scale-.5, lo[1]+(np.arange(height)+.5)/scale-.5)
    raw = cv2.remap(frame, xx.astype(np.float32), yy.astype(np.float32), cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(255,255,255))
    primary = None
    if representation is not None and 0 <= representation["page_index"] < len(pages):
        try:
            points = np.column_stack((xx.ravel(), yy.ravel(), np.ones(xx.size))) @ frame_to_display.T
            mapped, valid = _review_page_points(points, representation["transforms"])
            mapped[~valid,:2] = -1
            if valid.any():
                primary = cv2.remap(pages[representation["page_index"]], mapped[:,0].reshape(height,width).astype(np.float32),
                    mapped[:,1].reshape(height,width).astype(np.float32), cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(255,255,255))
        except (ValueError, KeyError, TypeError, cv2.error) as exc:
            logging.getLogger(__name__).warning("review page crop unavailable for %s: %s", item["id"], exc)
    return raw, primary, scale


def _review_system_map(record: dict, ledger: dict, sink: dict) -> dict:
    systems = record.get("systems", [])
    result = {f"strip:{s['id']}": s["id"] for s in systems}
    for s in systems:
        for ep in s.get("episode_ids", []):
            result.setdefault(f"jump:{ep}", s["id"])
    for sid, chains in sink.get("all_chains", {}).items():
        for chain in chains:
            if not chain["display_id"].startswith("occ:"):
                result.setdefault(chain["display_id"], sid)
    for dd in ledger.get("display_dispositions", []):
        if dd.get("kind") == "superseded_inventory":
            result[dd["display_id"]] = result.get(dd["retained_display_id"])
    return result


def _review_chain_key(display_id: str, stages: Sequence[dict]) -> Optional[tuple]:
    if not stages or stages[0].get("kind") != "affine":
        return None
    try:
        matrix = np.asarray(stages[0].get("matrix"), float)
    except (ValueError, TypeError):
        return None
    return (display_id, tuple(matrix.ravel())) if matrix.shape == (3,3) else None


def write_review_hypotheses(record: dict, ledger: dict, report: dict, staged: Path, *,
                            pages: Sequence[np.ndarray], sink: Optional[dict] = None, crop_limit: int = 2000,
                            expected: Sequence[np.ndarray] = (), strips: Optional[dict] = None,
                            cert_b: Optional[dict] = None) -> dict:
    if report.get("staged_verification"):
        return _write_staged_review_hypotheses(record, report, staged, pages=pages, expected=expected,
            strips=strips or {}, cert_b=cert_b or {}, sink=sink or {}, crop_limit=crop_limit)
    return _write_legacy_review_hypotheses(record, ledger, report, staged, pages=pages, sink=sink, crop_limit=crop_limit)


def _write_legacy_review_hypotheses(record: dict, ledger: dict, report: dict, staged: Path, *,
                                   pages: Sequence[np.ndarray], sink: Optional[dict] = None, crop_limit: int = 2000) -> dict:
    """Persist sorted review entries once; portable paths are promoted by the API."""
    started = time.perf_counter()
    sink = sink or {}
    items = {i["id"]: i for i in ledger.get("items", [])}
    dispositions = {d["item_id"]: d for d in ledger.get("dispositions", [])}
    display_dispositions = {}
    for dd in ledger.get("display_dispositions", []):
        display_dispositions.setdefault(dd["display_id"], []).append(dd)
    representations = {}
    for rep in ledger.get("representations", []):
        representations.setdefault(rep["item_id"], []).append(rep)
    entries, page_codes = {}, Counter()
    rank = {"fail": 0, "review_required": 1, "unresolved": 2}
    def add(item, code, status, page_index=None):
        key = (item["id"], code)
        if key not in entries or rank[status] < rank[entries[key]["status"]]:
            entries[key] = {"id": f"{item['id']}:{code}", "item_id": item["id"], "display_id": item["display_id"],
                "occurrence_id": item.get("occurrence_id"), "system_id": None, "timestamp_sec": None,
                "status": status, "code": code, "page_index": None if page_index is None else page_index+1,
                "raw_crop": "", "primary_crop": None, "crop_scale": 1.}
    for issue in report.get("issues", []):
        if issue.get("severity") not in ("fail", "review_required"):
            continue
        if issue.get("item_id") in items:
            add(items[issue["item_id"]], issue["code"], issue["severity"], issue.get("page_index"))
        elif not issue.get("item_id"):
            page_codes[issue["code"]] += 1
    for item in items.values():
        if not rl.mark_masks(item):
            continue
        dd = display_dispositions.get(item["display_id"], [])
        if any(d.get("kind") == "user_excluded" for d in dd):
            continue
        d = dispositions.get(item["id"], {})
        if d.get("terminal") == "unresolved" or item.get("terminal") == "unresolved":
            add(item, d.get("reason") or "UNRESOLVED_ALTERNATIVE", "unresolved")
        elif d.get("terminal") in ("source_limited", "review_required") or item.get("terminal") == "review_required":
            add(item, d.get("reason") or "SOURCE_LIMITED", "review_required")
        for disposition in dd:
            if disposition.get("kind") == "display_unresolved" or disposition.get("terminal") == "unresolved":
                add(item, disposition.get("reason") or "DISPLAY_UNRESOLVED", "unresolved")
            elif disposition.get("terminal") == "review_required":
                add(item, disposition.get("reason") or "DISPLAY_REVIEW_REQUIRED", "review_required")
        if not item.get("partitioned_into") and not representations.get(item["id"]) and not d and not dd:
            add(item, "UNRESOLVED", "unresolved")
    resolver = rl.EvidenceResolver(ledger)
    system_map = _review_system_map(record, ledger, sink)
    systems = {s["id"]: s for s in record.get("systems", [])}
    chain_owners = {}
    for sid, chains in sink.get("all_chains", {}).items():
        for chain in chains:
            key = _review_chain_key(chain["display_id"], chain["stages"])
            if key is not None:
                chain_owners.setdefault(key, set()).add(sid)
    witnesses = {}
    for entry in entries.values():
        ident = entry["item_id"]
        entry["system_id"] = system_map.get(entry["display_id"])
        if ident not in witnesses:
            try:
                witnesses[ident] = _review_witness(resolver, items[ident], dispositions.get(ident, {}))
            except (OSError, ValueError, KeyError, TypeError, cv2.error) as exc:
                logging.getLogger(__name__).warning("review witness unavailable for %s: %s", ident, exc)
                witnesses[ident] = None
        view = witnesses[ident]
        if view:
            obs = resolver.observations.get(view["observation_id"], {})
            entry["timestamp_sec"] = obs.get("t_sec", view.get("timestamp"))
        reps = representations.get(ident, [])
        if not reps:
            entry["page_index"] = None
        elif entry["page_index"] is None:
            entry["page_index"] = reps[0]["page_index"]+1
        if reps:
            rep = next((r for r in reps if r["page_index"]+1 == entry["page_index"]), reps[0])
            if rep.get("line_id") in systems:
                entry["system_id"] = rep["line_id"]
            else:
                owners = chain_owners.get(_review_chain_key(entry["display_id"], rep["transforms"]), set())
                if len(owners) == 1 and next(iter(owners)) in systems:
                    entry["system_id"] = next(iter(owners))
    ordered = sorted(entries.values(), key=lambda e: (rank[e["status"]], e["timestamp_sec"] if e["timestamp_sec"] is not None else math.inf, e["id"]))
    directory = Path(staged) / "review_hypotheses"
    directory.mkdir(parents=True, exist_ok=True)
    crops, truncated = {}, len(ordered) > crop_limit
    for entry in ordered[:max(0, crop_limit)]:
        ident, pi = entry["item_id"], entry["page_index"]
        key = (ident, pi)
        if key not in crops and witnesses[ident]:
            reps = representations.get(ident, [])
            rep = next((r for r in reps if r["page_index"]+1 == pi), None)
            system = systems.get(entry["system_id"], {})
            gap = float((system.get("strip") or {}).get("staff_gap_px") or 12.)
            try:
                raw, primary, scale = _review_crop_pair(resolver, items[ident], witnesses[ident], rep, pages, gap)
                stem = hashlib.sha256(f"{ident}:{pi}".encode()).hexdigest()[:24]
                paths = [f"review_hypotheses/{stem}-raw.png", None]
                if not cv2.imwrite(str(Path(staged)/paths[0]), raw):
                    raise OSError("review raw crop write failed")
                if primary is not None:
                    paths[1] = f"review_hypotheses/{stem}-primary.png"
                    if not cv2.imwrite(str(Path(staged)/paths[1]), primary):
                        raise OSError("review primary crop write failed")
                crops[key] = (*paths, scale)
            except (ValueError, KeyError, TypeError, np.linalg.LinAlgError, cv2.error) as exc:
                logging.getLogger(__name__).warning("review crop unavailable for %s: %s", ident, exc)
                crops[key] = ("", None, 1.)
        entry["raw_crop"], entry["primary_crop"], entry["crop_scale"] = crops.get(key, ("", None, 1.))
    measured = sink.get("measure_plan") or {}
    boundary_counts = measured.get("boundary_counts") or Counter(b["class"] for b in measured.get("boundaries", []))
    by_code = page_codes + Counter(e["code"] for e in ordered)
    counts = {"hypotheses": len(ordered), "bundles": sum(bool(s.get("alternate_kind") or s.get("minority_alternate") or
        (s.get("strip") or {}).get("minority_alternate")) for s in systems.values()),
        "boundaries_safe": int(boundary_counts.get("SAFE", 0)), "boundaries_unknown": int(boundary_counts.get("UNKNOWN", 0)),
        "pages": len(pages), "by_code": dict(by_code), "user_excluded": report.get("user_excluded", {"displays": 0, "items": 0})}
    payload = {"job_id": str(sink.get("job_id") or record.get("job_id") or ""),
        "status": "unassessed" if report.get("assessment") == "unassessed" and report["status"] != "fail" else report["status"],
        "export_revision": sink.get("export_revision", record.get("revision")), "counts": counts,
        "total": len(ordered), "offset": 0, "limit": len(ordered), "hypotheses": ordered, "truncated": truncated}
    _dump(payload, Path(staged)/"review_hypotheses.json")
    size = (Path(staged)/"review_hypotheses.json").stat().st_size + sum(p.stat().st_size for p in directory.glob("*.png"))
    logging.getLogger(__name__).info("review hypotheses: %s entries, %s bytes, %.3fs", len(ordered), size, time.perf_counter()-started)
    return payload


def strip_snapshots(strips: dict) -> dict:
    """Native strip commitments for B/C only; never claim Stage A support."""
    snapshots = {}
    for sid, image in strips.items():
        features = vc.strip_features(vc.contrast_map(image))
        snapshots[sid] = {"strip_id": sid, "strip_sha256": vc.pixels_sha256(image),
            "scope": "strip_pixels_only", "source_support": "unassessed",
            "features": [vc.feature_record(dict(f, id=f"{sid}/f{i:06d}"), supporters=[])
                         for i, f in enumerate(features)]}
    return snapshots


def _box_intersection(a, b):
    box = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
    return box if box[0] < box[2] and box[1] < box[3] else None


def _mapped_box(box, matrix):
    a, b, c, d = box
    points = np.array([[a, b, 1], [c-1, b, 1], [a, d-1, 1], [c-1, d-1, 1]]) @ matrix.T
    return [int(np.floor(points[:, 0].min())), int(np.floor(points[:, 1].min())),
            int(np.ceil(points[:, 0].max()))+1, int(np.ceil(points[:, 1].max()))+1]


def _staged_regions(cert_b: dict, strips: dict):
    """Rectangular source/page correspondence for crops; never sample a warped grid."""
    for inst in cert_b.get("instances", []):
        sid = inst["strip_id"]
        if sid not in strips:
            continue
        h, w = strips[sid].shape[:2]
        strip_stage, page_stage = inst["transform"]
        page_matrix = np.asarray(page_stage["matrix"], float)
        if strip_stage["kind"] == "affine":
            pieces = [([0, 0, w, h], np.asarray(strip_stage["matrix"], float))]
        else:
            pre = np.asarray(strip_stage.get("pre_matrix", np.eye(3)), float)
            pieces = [(_mapped_box(p["src_bbox"], np.linalg.inv(pre)), np.asarray(p["matrix"], float) @ pre)
                      for p in strip_stage["pieces"]]
        for native, matrix in pieces:
            native = _box_intersection(native, inst.get("owned_strip_bbox") or [0, 0, w, h])
            if native:
                matrix = page_matrix @ matrix
                yield inst, native, matrix, _mapped_box(native, matrix)


def _padded_crop(image, box, padding):
    h, w = image.shape[:2]
    a, b, c, d = box
    box = [max(0, int(np.floor(a-padding))), max(0, int(np.floor(b-padding))),
           min(w, int(np.ceil(c+padding))), min(h, int(np.ceil(d+padding)))]
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError("finding bbox outside image")
    return image[box[1]:box[3], box[0]:box[2]].copy(), box


def _staged_excluded_counts(record, sink):
    excluded = set(sink.get("excluded_system_ids", []))
    counts = {"displays": len(excluded), "items": 0}
    path = Path(record.get("ledger_base_path") or Path(record["workspace"])/"ledger_base.json")
    if not excluded or not path.is_file():
        return counts
    try:
        # Optional inventory counts only. B/C assessment never depends on this
        # ledger, and no representations or raw projections are assembled.
        base = json.loads(path.read_text(encoding="utf-8"))
        owners = {}
        for sid, chains in sink.get("all_chains", {}).items():
            for chain in chains:
                owners.setdefault(chain["display_id"], set()).add(sid)
        for remap in base.get("occurrence_remaps", []):
            if remap.get("final_system_id"):
                owners.setdefault(remap["display_id"], set()).add(remap["final_system_id"])
        for disposition in base.get("display_dispositions", []):
            if disposition.get("kind") == "superseded_inventory":
                owners.setdefault(disposition["display_id"], set()).update(owners.get(disposition["retained_display_id"], set()))
        displays = {did for did, ids in owners.items() if ids and ids <= excluded}
        return {"displays": len(displays), "items": sum(i["display_id"] in displays for i in base.get("items", []))}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logging.getLogger(__name__).warning("optional excluded inventory counts unavailable: %s", exc)
        return counts


def _write_staged_review_hypotheses(record, report, staged, *, pages, expected, strips, cert_b, sink, crop_limit):
    systems = {s["id"]: s for s in record.get("systems", [])}
    systems.update({s["id"]: s for s in sink.get("systems", [])})
    try:
        regions = list(_staged_regions(cert_b, strips))
    except (KeyError, ValueError, TypeError, np.linalg.LinAlgError):
        logging.getLogger(__name__).exception("review crop geometry unavailable")
        regions = []
    entries = []
    directory = Path(staged)/"review_hypotheses"
    directory.mkdir(parents=True, exist_ok=True)
    for i, issue in enumerate(report["issues"]):
        sid, pi, box = issue.get("strip_id"), issue.get("page_index"), issue.get("bbox")
        source_kind, raw, primary, native_scale = None, None, None, 1.
        candidates = []
        for inst, native, matrix, pagebox in regions:
            if sid is not None and inst["strip_id"] != sid or pi is not None and inst["page_index"] != pi:
                continue
            overlap = _box_intersection(box, pagebox if issue.get("stage") == "C" else native) if box else None
            if overlap:
                candidates.append(((overlap[2]-overlap[0])*(overlap[3]-overlap[1]), inst, native, matrix, pagebox))
        chosen = max(candidates, key=lambda c: c[0]) if candidates else None
        if chosen:
            _, inst, native, matrix, pagebox = chosen
            sid, pi = inst["strip_id"], inst["page_index"]
            native_scale = abs(float(matrix[0, 0]))
        system = systems.get(sid, {})
        gap = float((system.get("strip") or {}).get("staff_gap_px") or 12.)
        ident = f"{issue.get('stage', 'I')}:{sid or 'page'}:{pi}:{i}"
        entry = {"id": f"{ident}:{issue['code']}", "item_id": ident, "display_id": f"strip:{sid}" if sid else "",
            "occurrence_id": sid, "system_id": sid, "timestamp_sec": system.get("t_start"),
            "status": "review_required", "code": issue["code"], "page_index": None if pi is None else pi+1,
            "raw_crop": "", "primary_crop": None, "crop_scale": 1., "stage": issue.get("stage"),
            "bbox": box, "detail": issue.get("detail", {})}
        if i < max(0, crop_limit) and box:
            try:
                if issue.get("stage") == "C" and pi is not None and 0 <= pi < len(pages):
                    primary, page_crop_box = _padded_crop(pages[pi], box, 2*gap*native_scale)
                    if chosen:
                        native_box = _box_intersection(_mapped_box(page_crop_box, np.linalg.inv(matrix)), native)
                        if native_box:
                            raw, _ = _padded_crop(strips[sid], native_box, 0)
                            source_kind = "source_strip"
                    if raw is None and pi < len(expected):
                        raw, _ = _padded_crop(expected[pi], page_crop_box, 0)
                        native_scale, source_kind = 1., "expected_render"
                elif sid in strips:
                    raw, native_crop_box = _padded_crop(strips[sid], box, 2*gap)
                    source_kind = "source_strip"
                    if chosen and pi is not None and 0 <= pi < len(pages):
                        primary, _ = _padded_crop(pages[pi], _mapped_box(native_crop_box, matrix), 0)
                if raw is not None:
                    # Put native strip pixels at delivered scale, then apply one
                    # common preview scale. Primary is always a contiguous crop.
                    if source_kind == "source_strip" and native_scale != 1:
                        raw = cv2.resize(raw, (max(1, round(raw.shape[1]*native_scale)),
                                              max(1, round(raw.shape[0]*native_scale))), interpolation=cv2.INTER_AREA)
                    scale = min(1., 480/max(*raw.shape[:2], *(primary.shape[:2] if primary is not None else (1, 1))))
                    def save(image, suffix):
                        if image is None:
                            return None
                        if scale != 1:
                            image = cv2.resize(image, (max(1, round(image.shape[1]*scale)), max(1, round(image.shape[0]*scale))), interpolation=cv2.INTER_AREA)
                        path = f"review_hypotheses/{i:05d}-{suffix}.png"
                        if not cv2.imwrite(str(Path(staged)/path), image):
                            raise OSError("review crop write failed")
                        return path
                    entry.update(raw_crop=save(raw, "raw"), primary_crop=save(primary, "primary"),
                                 crop_scale=native_scale*scale, raw_crop_kind=source_kind)
            except (OSError, ValueError, KeyError, TypeError, cv2.error, np.linalg.LinAlgError) as exc:
                logging.getLogger(__name__).warning("review crop unavailable for %s: %s", ident, exc)
        entries.append(entry)
    entries.sort(key=lambda e: (e["timestamp_sec"] if e["timestamp_sec"] is not None else math.inf, e["id"]))
    measured = sink.get("measure_plan") or {}
    boundaries = measured.get("boundary_counts") or Counter(b["class"] for b in measured.get("boundaries", []))
    counts = {"hypotheses": len(entries), "bundles": sum(bool(s.get("alternate_kind") or s.get("minority_alternate") or
              (s.get("strip") or {}).get("minority_alternate")) for s in record.get("systems", [])),
        "boundaries_safe": int(boundaries.get("SAFE", 0)), "boundaries_unknown": int(boundaries.get("UNKNOWN", 0)),
        "pages": len(pages) or len(sink.get("plan", {}).get("pages", [])), "by_code": dict(Counter(i["code"] for i in report["issues"])),
        "user_excluded": _staged_excluded_counts(record, sink)}
    payload = {"job_id": str(sink.get("job_id") or record.get("job_id") or ""), "status": report["status"],
        "export_revision": sink.get("export_revision", record.get("revision")), "counts": counts,
        "total": len(entries), "offset": 0, "limit": len(entries), "hypotheses": entries, "truncated": len(entries) > crop_limit}
    _dump(payload, Path(staged)/"review_hypotheses.json")
    return payload


def _light_report(record, staged, report, review):
    counts = review["counts"]
    record["ledger_summary"] = {"status": report["status"], "issue_counts": counts["by_code"], "counts": counts,
        "review_hypotheses": counts["hypotheses"], "stage_seconds": report.get("stage_seconds", {}),
        "dev_issue_counts": report.get("dev_issue_counts", {})}
    if report.get("exceptions"):
        record["ledger_summary"]["exceptions"] = report["exceptions"]
    record["ledger_verification"] = {"status": report["status"], "assessment": report["status"],
        "issue_counts": counts["by_code"], "user_excluded": counts["user_excluded"], "scope": "strip_plan_to_deliverable"}
    codes = {"LEDGER_UNASSESSED", "LEDGER_REVIEW_REQUIRED", "LEDGER_VERIFICATION_FAILED", "DELIVERED_PDF_UNASSESSED"}
    reasons = [r for r in record.get("review_reasons", []) if r not in codes]
    reasons.extend(source_review_reasons(record.get("source_class") or {}, record.get("systems") or []))
    if report["status"] != "pass":
        reasons.append("LEDGER_VERIFICATION_FAILED" if report["status"] == "fail" else
                       "LEDGER_UNASSESSED" if report["status"] == "unassessed" else "LEDGER_REVIEW_REQUIRED")
    record["review_reasons"], record["review_required"] = sorted(set(reasons)), bool(reasons)
    _dump(report, Path(staged)/"ledger_report.json")
    workspace = Path(record["workspace"])
    record["ledger_attempt_path"] = str(workspace/"ledger_last_attempt.json")
    _dump(report, workspace/"ledger_last_attempt.json")


# Finding codes shown to the user as "items to check". Only codes whose real-video findings were
# shown to be real defects belong here (DECISIONS "User-visible findings", 2026-10-09): a spot check of
# OUTPUT_FIDELITY, REMOVED_FEATURE, DUPLICATED_CONTENT, PLAN_INVALID and DELIVERED_EXTRA_INK on S1/01Mr
# found no real defect, so they stay in the developer report (verify_dev_findings.json).
USER_VISIBLE_CODES = frozenset({"DELIVERED_FEATURE_MISSING", "PLACEMENT_MISMATCH", "STAFF_SEAM",
                                "ARTIFACT_MISMATCH", "EVIDENCE_INTEGRITY", "VERIFICATION_UNASSESSED"})


def verify_light_deliverable(record: dict, export_result: dict, staged: Path, *, sink: dict) -> dict:
    """Only PDF container violations block. B/C findings are human review items."""
    started = time.perf_counter()
    report = {"staged_verification": True, "status": "pass", "issues": [], "stage_seconds": {}, "exceptions": {},
              "scope": "strip_plan_to_deliverable"}
    pdf = export_result.get("pdf")
    paths = ([pdf] if pdf else []) + [p for p in export_result.get("images", []) if Path(p).suffix.lower() == ".png"]
    binding = {str(Path(p).relative_to(staged)): vc.file_sha256(p) for p in paths}
    if pdf:
        contract = rl.check_pdf_contract(pdf)
        report["pdf_contract"] = contract
        if contract["status"] != "pass":
            report["status"] = "fail"
            report["issues"] = [dict(i, stage="I", severity="fail", check="check_pdf_contract") for i in contract["issues"]]
            review = write_review_hypotheses(record, {}, report, staged, pages=(), sink=sink)
            _light_report(record, staged, report, review)
            return report
    strips, cert_b, expected, pages = {}, {}, [], []
    _dump(sink.get("plan", {}), Path(staged)/"plan.json")
    _dump({k: v for k, v in sink.items() if k != "pages"}, Path(staged)/"sink.json")
    for stage in ("B", "C"):
        stage_started = time.perf_counter()
        try:
            if stage == "B":
                for sid, path in sink.get("strip_paths", {}).items():
                    strips[sid] = cv2.imread(str(path))
                    if strips[sid] is None:
                        raise ValueError(f"unreadable strip: {sid}")
                cert_b = vb.verify_plan(strip_snapshots(strips), sink["plan"], sink, strips, systems=sink["systems"])
                cert_b["source_support"] = "unassessed"  # app deliberately does not run A
                findings = cert_b["findings"]
                _dump(cert_b, Path(staged)/"verify_B.json")
            else:
                if not cert_b:
                    raise ValueError("Stage B certificate unavailable")
                if pdf:
                    cert_c = vp.verify_pages(cert_b, strips, pdf, generated=sink.get("generated", []), profile="lossless")
                    pages = vp.decode_lossless_pdf(pdf, profile="lossless")
                else:
                    pngs = [p for p in export_result.get("images", []) if Path(p).suffix.lower() == ".png"]
                    if not pngs:
                        raise ValueError("no lossless PDF or PNG deliverable selected")
                    pages = [cv2.imread(str(p)) for p in pngs]
                    cert_c = vp.verify_pages(cert_b, strips, None, generated=sink.get("generated", []), profile="lossless-rgb", pages=pages)
                findings = cert_c["findings"]
                _dump(cert_c, Path(staged)/"verify_C.json")
            # Retain original certificate severity for developers; app findings
            # are non-blocking, including integrity/plan findings from B/C.
            report["issues"].extend(dict(f, verifier_severity=f["severity"], severity="review_required") for f in findings)
        except Exception as exc:  # noqa: BLE001 - verifier failure cannot suppress an export
            logging.getLogger(__name__).exception("non-blocking Stage %s verification unavailable", stage)
            report["exceptions"][stage] = {"type": type(exc).__name__, "detail": str(exc)}
            report["issues"].append({"stage": stage, "severity": "review_required", "code": "VERIFICATION_UNASSESSED",
                                     "detail": {"exception_type": type(exc).__name__, "reason": str(exc)}})
        finally:
            report["stage_seconds"][stage] = time.perf_counter()-stage_started
    if cert_b and pages and any(f.get("stage") == "C" and f.get("bbox") for f in report["issues"]):
        try:
            expected = vp.render_expected(cert_b, strips, sink.get("generated", []), len(pages))
        except Exception:  # crops are auxiliary; preserve the original findings
            logging.getLogger(__name__).exception("expected review render unavailable")
    dev = [i for i in report["issues"] if i["code"] not in USER_VISIBLE_CODES]
    report["issues"] = [i for i in report["issues"] if i["code"] in USER_VISIBLE_CODES]
    report["dev_issue_counts"] = dict(Counter(i["code"] for i in dev))
    _dump({"issue_counts": report["dev_issue_counts"], "issues": dev}, Path(staged)/"verify_dev_findings.json")
    report["status"] = "unassessed" if report["exceptions"] else "review_required" if report["issues"] else "pass"
    review = write_review_hypotheses(record, {}, report, staged, pages=pages, expected=expected,
                                   strips=strips, cert_b=cert_b, sink=sink)
    report["artifact_digests"] = binding
    report["gate_seconds"] = time.perf_counter()-started
    _light_report(record, staged, report, review)
    return report


def check_export_binding(workspace: Path, binding: dict, *, check: str) -> None:
    from app.pipeline.export import ExportVerificationError
    for relative, digest in binding.items():
        try:
            matches = vc.file_sha256(Path(workspace)/relative) == digest
        except OSError:
            matches = False
        if not matches:
            raise ExportVerificationError("LEDGER_VERIFICATION_FAILED", f"{check}: checked artifact changed: {relative}",
                                          {"check": check, "artifact": relative})


def verify_delivered_ledger(record: Dict[str, Any], pdf: Optional[str], staged: Path, *, sink: Optional[dict] = None) -> Dict[str, Any]:
    """Test/dev only: verify the delivered ledger, recording failures for review."""
    try:
        return _verify_delivered_ledger(record, pdf, staged, sink=sink)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception("delivered ledger verification failed")
        return _ledger_verifier_failure(record, staged, exc, sink=sink)


def _ledger_verifier_failure(record: dict, staged: Path, exc: Exception, *, sink: Optional[dict] = None) -> dict:
    ledger = _ledger_error_inventory(record, exc)
    try:
        return _verify_delivered_ledger(record, None, staged, sink=sink, ledger=ledger)
    except Exception:  # noqa: BLE001
        # Even artifact/review failures must block publication through the
        # ledger gate. Raw inventory and its frames remain in the workspace.
        logging.getLogger(__name__).exception("ledger failure artifacts unavailable")
        report = {"status": "fail", "assessment": "fail", "issues": [ledger["verifier_error"]], "matches": []}
        counts = {"hypotheses": 0, "bundles": 0, "boundaries_safe": 0, "boundaries_unknown": 0,
                  "pages": len((sink or {}).get("pages", [])), "by_code": {"LEDGER_VERIFIER_ERROR": 1},
                  "user_excluded": {"displays": 0, "items": 0}}
        record["ledger_summary"] = {"status": "fail", "issue_counts": counts["by_code"],
            "items": len(ledger["items"]), "displays": len(ledger["displays"]), "observations": len(ledger["observations"]),
            "terminals": dict.fromkeys(rl.TERMINALS, 0), "review_hypotheses": 0, "counts": counts}
        record["ledger_verification"] = {"status": "fail", "assessment": "fail", "issue_counts": counts["by_code"]}
        record["review_required"] = True
        record["review_reasons"] = sorted(set(record.get("review_reasons", []) + ["LEDGER_VERIFICATION_FAILED"]))
        report_path = Path(record["workspace"]) / "ledger_last_attempt.json"
        record["ledger_attempt_path"] = str(report_path)
        review = {"status": "fail", "counts": counts, "total": 0, "offset": 0, "limit": 0,
                  "hypotheses": [], "truncated": False, "export_revision": (sink or {}).get("export_revision")}
        for value, path in ((ledger, Path(staged)/"ledger.json"), (report, Path(staged)/"ledger_report.json"),
                            (report, report_path), (review, Path(staged)/"review_hypotheses.json")):
            try:
                _dump(value, path)
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).exception("could not retain ledger failure artifact %s", path)
        return report


def _verify_delivered_ledger(record: Dict[str, Any], pdf: Optional[str], staged: Path, *, sink: Optional[dict] = None,
                             ledger: Optional[dict] = None) -> Dict[str, Any]:
    """Assess the actual staged PDF before either export transaction is installed."""
    from app.pipeline import reflow_ledger as rl

    base_path = Path(record.get("ledger_base_path") or Path(record["workspace"]) / "ledger_base.json")
    if ledger is None:
        ledger = build_delivered_ledger(record, sink or {}) if base_path.is_file() else persist_ledger_evidence(record)
    delivered_pages = []
    if ledger.get("verifier_error"):
        report = {"status": "fail", "issues": [ledger["verifier_error"]], "matches": []}
    elif pdf:
        report = rl.verify_pdf(ledger, pdf, pages_sink=delivered_pages)
    elif sink is not None and sink.get("pages"):
        delivered_pages = sink["pages"]
        report = rl.verify_pages(ledger, delivered_pages)
        report["issues"].append({"severity":"review_required","code":"DELIVERED_PDF_UNASSESSED"})
        if report["status"]=="pass":
            report["status"] = "review_required"
    else:
        report = {"status": "review_required", "issues": [
            {"severity": "review_required", "code": "DELIVERED_PDF_UNASSESSED"}], "matches": []}
    if not ledger.get("items") or not ledger.get("displays"):
        report["assessment"] = "unassessed"
        report["issues"].append({"severity": "review_required", "code": "LEDGER_UNASSESSED"})
        if report["status"] != "fail":
            report["status"] = "review_required"
    else:
        report["assessment"] = report["status"]
    unknown_regions = (sink or {}).get("unavailable_regions", []) if base_path.is_file() else []
    for issue in report["issues"]:
        box = issue.get("bbox")
        unknown = box is not None and any(r["page_index"] == issue.get("page_index") and
            r["bbox"][0] <= box[0] and r["bbox"][1] <= box[1] and box[2] <= r["bbox"][2] and box[3] <= r["bbox"][3]
            for r in unknown_regions)
        if issue["code"] == "OUTPUT_FOREGROUND_WITHOUT_ORIGIN" and unknown:
            issue["severity"] = "review_required"
            issue["reason"] = "CHAIN_UNAVAILABLE"
    if unknown_regions:
        report["status"] = "fail" if any(i["severity"] == "fail" for i in report["issues"]) else "review_required"
        report["assessment"] = report["status"]
    ledger_items = {i["id"]:i for i in ledger.get("items",[])}
    for d in ledger.get("dispositions", []):
        if not rl.mark_masks(ledger_items[d["item_id"]]):
            continue
        if d.get("reason", "").startswith("REMOVED_BY_"):
            report["issues"].append({"severity": "review_required", "code": d["reason"], "item_id": d["item_id"]})
    if report["status"] == "pass" and report["issues"]:
        report["status"] = report["assessment"] = "review_required"
    rl.write_ledger(Path(staged)/"ledger.json",ledger)
    _dump(report, Path(staged) / "ledger_report.json")
    # Also retain failed-attempt mismatch crops after staged cleanup. Do not
    # replace the last installed result's report/path during a failed rebuild.
    report_path = Path(record["workspace"]) / "ledger_last_attempt.json"
    _dump(report, report_path)
    item_terminals = {t: report.get("terminal_counts", {}).get("items", {}).get(t, 0) for t in rl.TERMINALS}
    review_items = {i["item_id"] for i in report["issues"] if i["severity"] == "review_required" and i.get("item_id")}
    review_displays = {i["display_id"] for i in report["issues"] if i["severity"] == "review_required" and i.get("display_id")}
    represented = {r["item_id"] for r in ledger.get("representations", [])}
    exempt = {d["display_id"] for d in ledger.get("display_dispositions", [])
        if d.get("kind") in ("user_excluded", "superseded_inventory", "display_equivalent")}
    review_items.update(i["id"] for i in ledger.get("items", []) if not i.get("partitioned_into") and
        (i["display_id"] in review_displays or (i["id"] not in represented and i["display_id"] not in exempt)))
    summary = {"status": report["status"], "issue_counts": dict(Counter(i["code"] for i in report["issues"])),
        "items": len(ledger.get("items", [])), "displays": len(ledger.get("displays", [])),
        "observations": len(ledger.get("observations", [])), "terminals": item_terminals,
        "review_hypotheses": len(review_items)}
    record["ledger_summary"] = summary
    review = write_review_hypotheses(record, ledger, report, Path(staged), pages=delivered_pages, sink=sink)
    record["ledger_summary"]["counts"] = review["counts"]
    record["ledger_verification"] = {k: v for k, v in report.items() if k not in ("issues", "matches", "accounting")}
    record["ledger_verification"]["issue_counts"] = summary["issue_counts"]
    record["ledger_attempt_path"] = str(report_path)
    ledger_codes = {"LEDGER_UNASSESSED", "LEDGER_REVIEW_REQUIRED", "LEDGER_VERIFICATION_FAILED", "DELIVERED_PDF_UNASSESSED"}
    reasons = [r for r in record.get("review_reasons", []) if r not in ledger_codes]
    # Keep source uncertainty across selection/reordering. Only new positive
    # recovery evidence upstream may remove an overlay reason.
    reasons.extend(source_review_reasons(record.get("source_class") or {}, record.get("systems") or []))
    if report["status"] == "fail":
        reasons.append("LEDGER_VERIFICATION_FAILED")
    elif report["status"] != "pass":
        reasons.append("LEDGER_UNASSESSED" if report["assessment"] == "unassessed" else "LEDGER_REVIEW_REQUIRED")
        if any(i["code"] == "DELIVERED_PDF_UNASSESSED" for i in report["issues"]):
            reasons.append("DELIVERED_PDF_UNASSESSED")
    record["review_reasons"] = sorted(set(reasons))
    record["review_required"] = bool(reasons)
    return report


def prune_frames(record: Dict[str, Any]) -> None:
    """Remove the per-observation frame PNGs once strips exist (they can be
    decoded again from the source when needed). Persist evidence first; unresolved
    overlays retain their raw observations until positive recovery is available.
    ``REFLOW_KEEP_FRAMES`` (development) keeps them for diagnosis."""
    if os.environ.get("REFLOW_KEEP_FRAMES"):
        record["frames_pruned"] = False
        return
    base_path = Path(record.get("ledger_base_path") or Path(record["workspace"]) / "ledger_base.json")
    if record.get("dev_ledger", base_path.is_file()):
        try:
            if base_path.is_file():
                base = json.loads(base_path.read_text(encoding="utf-8"))
                assembly.retain_evidence(base, Path(record["workspace"]))
                rl.write_ledger(base_path, base)
            else:
                persist_ledger_evidence(record)
        except (OSError, ValueError, KeyError) as exc:
            record["frames_pruned"] = False
            logging.getLogger(__name__).warning("ledger evidence retention prevents frame pruning: %s", exc)
            return
    reasons = source_review_reasons(record.get("source_class") or {}, record.get("systems") or [])
    if any(r in reasons or r in record.get("review_reasons", [])
           for r in ("OVERLAY_UNRECOVERED", "OVERLAY_COVERS_NOTATION")):
        evidence_path = Path(record["workspace"]) / "overlay_review_evidence.json"
        _dump({"reasons": sorted(set(reasons + list(record.get("review_reasons", [])))),
               "systems": record.get("systems", []),
               "manifest_path": record.get("manifest_path") or str(Path(record["workspace"]) / "manifest.json"),
               "frames_path": str(Path(record["workspace"]) / "manifest" / "frames"),
               "source_path": record.get("source_path")}, evidence_path)
        record["overlay_evidence_path"] = str(evidence_path)
        record["frames_pruned"] = False
        return
    frames = Path(record["workspace"]) / "manifest" / "frames"
    if frames.is_dir():
        shutil.rmtree(frames, ignore_errors=True)
    record["frames_pruned"] = True


def _label_section(s: Dict[str, Any]) -> Optional[str]:
    """The section a system's label patch belongs to: the system where that label was
    first acquired (``repeats_system_id`` for a continuing label), or None without a patch."""
    lab = s.get("label") or {}
    if not lab.get("path"):
        return None
    return lab.get("repeats_system_id") or s["id"]


def resolve_dependencies(systems: Sequence[Dict[str, Any]], all_systems: Optional[Sequence[Dict[str, Any]]] = None,
                         *, workspace: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Re-validate cross-system dependencies for the final order and selection.

    ``systems``: the included systems in their final order; ``all_systems``: every system
    of the job (for reporting labels that lost every system of their section).

    * Preview tail: a strip whose tail was cut (moved to its destination) keeps the cut
      only while the destination is the next placed system; otherwise the uncut strip
      (tail on the source strip) is used. A missing, unreadable or damaged uncut strip is
      regenerated from the job's observations and verified (``regenerate_uncut_strip``, needs
      ``workspace``); when that fails the composition stops with
      ``DependencyUnavailableError`` (never a page from the cut strip).
    * Section label: placed above the first placed system of each section in the final
      order (where the label text changes), so a label whose original owner was excluded
      or moved goes to the next placed system of that section. A section without any
      placed system is reported, never dropped silently.

    Returns per-system decisions ``[{"system": s, "strip_path", "variant", "label": rec or None,
    "label_section"}]`` and the dependency report."""
    decided: List[Dict[str, Any]] = []
    restored: List[Dict[str, Any]] = []
    moved: List[Dict[str, Any]] = []
    prev_section: Optional[str] = None
    for i, s in enumerate(systems):
        strip = s.get("strip") or {}
        tail = strip.get("preview_tail") or {}
        path, variant = s["strip_path"], "strip"
        if tail.get("cut"):
            nxt = systems[i + 1]["id"] if i + 1 < len(systems) else None
            dest = tail.get("destination_system_id")
            if nxt != dest:
                uncut = (strip.get("uncut") or {}).get("path")
                reason = "destination_not_placed" if dest not in {x["id"] for x in systems} else "destination_not_next"
                rec = {"system_id": s["id"], "destination_system_id": dest, "next_system_id": nxt, "reason": reason}
                ok, why = _usable_uncut(s)
                if not ok:
                    attempt = regenerate_uncut_strip(Path(workspace), s) if workspace is not None else \
                        {"system_id": s["id"], "regenerated": False, "reason": "no_workspace"}
                    if not attempt.get("regenerated"):
                        raise DependencyUnavailableError(s["id"], f"{why}; regeneration: {attempt.get('reason')}", [attempt])
                    ok2, why2 = _usable_uncut(s)
                    if not ok2:
                        raise DependencyUnavailableError(s["id"], f"{why}; regenerated file: {why2}", [attempt])
                    rec["regenerated"] = {"was": why, "verified_by": attempt.get("verified_by")}
                path, variant = uncut, "uncut"
                restored.append(rec)
        section = _label_section(s)
        label = None
        if section is not None and section != prev_section:
            label = s["label"]
            if section != s["id"]:
                moved.append({"section": section, "placed_on": s["id"],
                              "reason": "section_start_excluded" if section not in {x["id"] for x in systems} else "order_changed"})
        prev_section = section
        decided.append({"system": s, "strip_path": path, "variant": variant, "label": label, "label_section": section if label else None})
    placed_sections = {d["label_section"] for d in decided if d["label_section"]}
    unplaced = []
    seen = set()
    for s in all_systems or []:
        sec = _label_section(s)
        if sec and sec not in placed_sections and sec not in seen:
            seen.add(sec)
            unplaced.append({"section": sec, "systems": [x["id"] for x in all_systems if _label_section(x) == sec],
                             "reason": "no_placed_system_of_this_section"})
    report = {"preview_tails_restored": restored, "labels_moved": moved, "labels_unplaced": unplaced}
    return decided, report


def _compose_ledger_inputs(sink: dict, decided: Sequence[dict], all_systems: Sequence[dict], workspace: Optional[Path]) -> None:
    path = Path(workspace) / "ledger_chains.json" if workspace is not None else None
    saved = json.loads(path.read_text()) if path is not None and path.is_file() else {}
    chains, unavailable = [], []
    for d in decided:
        s = d["system"]
        current = json.loads(json.dumps(saved.get(s["id"], [])))
        if d["variant"] == "uncut":
            strip = s.get("strip") or {}
            origin, unc = strip.get("ledger_canvas_box_crop"), strip.get("uncut") or {}
            # Page strips are native crop translations. Jump/alternate extents
            # without an explicit producer origin cannot be reconstructed here.
            if origin and unc.get("box_crop") and not strip.get("jump") and all(
                    c["display_id"] == f"strip:{s['id']}" for c in current):
                box = unc["box_crop"]
                for c in current:
                    c["stages"] = [{"stage": "display_to_strip", "kind": "affine",
                        "matrix": [[1, 0, origin[0]-box[0]], [0, 1, origin[1]-box[1]], [0, 0, 1]]}]
                    c.pop("domain_strip", None)
            else:
                current = []
        if not current:
            unavailable.append({"system_id": s["id"], "display_id": f"strip:{s['id']}", "variant": d["variant"]})
        chains.extend(current)
    decided_ids = {d["system"]["id"] for d in decided}
    user_ids = set(sink.get("excluded_system_ids", []))
    sink.update(chains=chains, decided_system_ids=sorted(decided_ids),
                strip_paths={d["system"]["id"]: str(d["strip_path"]) for d in decided},
                systems=[dict(d["system"], included=True) for d in decided],
                excluded_system_ids=sorted(user_ids - decided_ids),
                unplaced_system_ids=[s["id"] for s in all_systems if s["id"] not in decided_ids],
                all_chains=saved, unavailable=unavailable, removed=[],
                variants={d["system"]["id"]: d["variant"] for d in decided})


def _unavailable_regions(sink: dict, plan: dict) -> None:
    missing = {r["system_id"] for r in sink.get("unavailable", [])}
    sink["unavailable_regions"] = [{"page_index": pi, "bbox": [pl["x"], pl["y"], pl["x"]+pl["w"], pl["y"]+pl["h"]]}
        for pi, p in enumerate(plan["pages"]) for pl in p["placements"]
        if missing.intersection(pl.get("system_ids", [pl["system_id"]]))]


def _whole_label_origins(plan: dict, images: dict, units: dict, decided: Sequence[dict], generated: list) -> None:
    by_id = {d["system"]["id"]: d for d in decided}
    for pi, page in enumerate(plan["pages"]):
        for pl in page["placements"]:
            sid = pl["system_id"]
            box = units[sid].get("label_box")
            if box is None:
                continue
            im = images[sid]
            sx, sy = float(pl["w"])/im.shape[1], float(pl["h"])/im.shape[0]
            a, b = np.floor(np.asarray(box[:2])*[sx, sy]).astype(int)
            c, d = np.ceil(np.asarray(box[2:])*[sx, sy]).astype(int)
            resized = rr.resize_strip(rr._to_page_paper(im), pl["w"], pl["h"])
            if not np.any(255-resized[b:d, a:c].min(axis=2).astype(np.int16) >= rl.MIN_CONTRAST):
                continue
            generated.append({"kind": "section_label", "page_index": pi, "origin": [pl["x"]+int(a), pl["y"]+int(b)],
                "template": rl.pack_crop(resized[b:d, a:c]), "generator": "reflow_labels.with_label",
                "inputs": {"source": by_id[sid]["label"]["path"], "system_id": sid, "box": box}})


def compose_systems(systems: Sequence[Dict[str, Any]], *, header: Optional[Dict[str, Any]] = None,
                    staff_gap_mm: float = 1.5, all_systems: Optional[Sequence[Dict[str, Any]]] = None,
                    workspace: Optional[Path] = None, measure_reflow: bool = False,
                    measure_context: Optional[Dict[str, Any]] = None, measure_locks: Sequence[Dict[str, Any]] = (),
                    auto_staff_size: bool = False, ledger_sink: Optional[dict] = None):
    """Plan + render the included systems in the given order. Returns (plan, pages).

    Dependencies are re-validated first (``resolve_dependencies``): preview tails whose
    destination is no longer the next placed system go back on their source strip, and
    section labels go above the first placed system of their section. A system with a
    label patch to place is laid out as one unit: the label above the strip, at the
    source scale. Placements then record where the strip and the label sit inside the
    unit (``strip_offset_px``, ``label_box_px``), the strip variant used and the label's
    section; ``plan["dependencies"]`` reports restored tails and moved/unplaced labels.

    ``measure_reflow`` (off by default; MEASURE_BRIEF milestone 2): after the dependencies are
    resolved, the placed strips are split only at SAFE measure boundaries and laid out as justified
    lines (reflow_measure). ``measure_context`` (manifest + occurrences, for barline registration)
    defaults to the workspace's files. When no measure plan can be made the whole systems are
    composed as usual and ``plan["measure_reflow"]`` says why.

    ``auto_staff_size`` (DECISIONS "Automatic staff size for dense charts"; STRATEGY Step 2A): measure
    lines may use a smaller size down to 1.2 mm when dense measures leave lines short; whole systems
    that do not fit the page at ``staff_gap_mm`` are composed at the largest fitting size on the same
    grid, never below 1.2 mm (``_compose_whole_systems``). Off (a size the user chose explicitly) the
    size is never changed. ``plan["staff_size"]`` records the size used and why."""
    report_progress("planning")
    # These findings describe this export, and must clear when selection/size changes.
    for s in all_systems or systems:
        if any(c in ("FORCED_LINE_BREAK", "LINE_BELOW_MIN_SIZE") for c in s.get("issues", [])):
            s["issues"] = [c for c in s["issues"] if c not in ("FORCED_LINE_BREAK", "LINE_BELOW_MIN_SIZE")]
            s.pop("effective_staff_gap_mm", None)
    decided, report = resolve_dependencies(systems, all_systems, workspace=workspace)
    if not decided:
        raise NoSystemsError("no systems selected")
    if ledger_sink is not None:
        _compose_ledger_inputs(ledger_sink, decided, all_systems or systems, workspace)
    clipped = [{"system_id": s["id"], **(s.get("source_clipped") or {})} for s in systems
               if "SOURCE_CLIPPED" in (s.get("issues") or []) or s.get("source_clipped")]
    if clipped:
        header = dict(header or {}, source_clipped=clipped)
    composed_systems = [d["system"] for d in decided]
    # worked out on the composed selection: a part whose family neighbour is not printed is
    # paired with the nearest printed one (audit F07)
    possible_repeats = ro.possible_repeat_pairs(composed_systems)
    if possible_repeats or (header or {}).get("possible_repeats"):
        header = dict(header or {})
        header.pop("possible_repeats", None)
        if possible_repeats:
            header["possible_repeats"] = possible_repeats
    number_steps = [{"system_id": s["id"]} for s in composed_systems
                    if "NUMBER_STEP_UNRESOLVED" in (s.get("issues") or [])]
    if number_steps or (header or {}).get("number_steps_unresolved"):
        header = dict(header or {})
        header.pop("number_steps_unresolved", None)
        if number_steps:
            header["number_steps_unresolved"] = number_steps
    fallback: Optional[Dict[str, Any]] = None
    if measure_reflow:
        from app.pipeline import reflow_measure as rmeas
        ctx = measure_context if measure_context is not None else rmeas.load_context(workspace)
        try:
            plan, pages = rmeas.compose(decided, header=header, staff_gap_mm=staff_gap_mm, context=ctx, locks=measure_locks,
                                        auto_staff_size=auto_staff_size, **({"ledger_requested": True} if ledger_sink is not None else {}))
        except rmeas.MeasurePlanUnavailable as exc:
            fallback = {"status": "fallback_whole_systems", "reason": exc.reason, "detail": exc.detail}
        except OperationCancelled:
            raise
        except Exception as exc:  # any failure (incl. a line layout conflict) -> whole systems, whose conflict record names systems
            fallback = {"status": "fallback_whole_systems", "reason": "MEASURE_PLAN_ERROR", "detail": {"error": repr(exc)[:300]}}
        else:
            plan["measure_reflow"]["status"] = "measure_lines"
            plan["measure_reflow"]["registration_context"] = bool(ctx)
            plan["dependencies"] = report
            _line_review_issues(plan, all_systems or systems)
            if ledger_sink is not None:
                measured = plan["measure_reflow"]
                for source, dest in (("ledger_placements", "placements"), ("ledger_removed", "removed"), ("generated_origins", "generated")):
                    ledger_sink[dest] = measured.pop(source, [])
                    ledger_sink[source] = ledger_sink[dest]
                ledger_sink["pages"] = pages
                ledger_sink["measure_plan"] = {k: measured[k] for k in ("boundary_counts", "boundaries") if k in measured}
                _unavailable_regions(ledger_sink, plan)
                ledger_sink["plan"] = json_safe(plan)
            return json_safe(plan), pages
    records = []
    images: Dict[str, np.ndarray] = {}
    units: Dict[str, Dict[str, Any]] = {}
    for d in decided:
        s = d["system"]
        img = cv2.imread(str(d["strip_path"]))
        if img is None:
            raise RuntimeError(f"strip image missing for {s['id']}: {d['strip_path']}")
        lab = d["label"] or {}
        unit: Dict[str, Any] = {"strip_offset": [0, 0]}
        if lab.get("path"):
            patch = cv2.imread(str(lab["path"]))
            if patch is None:
                raise RuntimeError(f"label patch missing for {s['id']}: {lab['path']}")
            img, unit = rlab.with_label(img, patch, label_x=int(lab.get("x_in_strip", 0)),
                                        gap_px=int(round(0.5 * float(s["strip"]["staff_gap_px"]))))
            unit["label_section"] = d["label_section"]
        unit["variant"] = d["variant"]
        images[s["id"]] = img
        units[s["id"]] = unit
        records.append({"system_id": s["id"], "staff_gap_px": float(s["strip"]["staff_gap_px"])})
    if not records:
        raise NoSystemsError("no systems selected")
    report_progress("rendering")
    generated = [] if ledger_sink is not None else None
    plan, pages = _compose_whole_systems(records, images, header=header, staff_gap_mm=staff_gap_mm,
                                         auto_staff_size=auto_staff_size, fallback=fallback,
                                         **({"generated": generated} if ledger_sink is not None else {}))
    for p in plan["pages"]:
        for pl in p["placements"]:
            u = units.get(pl["system_id"], {})
            pl["strip_offset_px"] = list(u.get("strip_offset", [0, 0]))
            pl["strip_variant"] = u.get("variant", "strip")
            if "label_box" in u:
                pl["label_box_px"] = list(u["label_box"])
                pl["label_section"] = u.get("label_section")
    plan["dependencies"] = report
    if fallback is not None:
        plan["measure_reflow"] = fallback
    from app.pipeline import reflow_measure as rmeas
    rmeas.flag_line_sizes(plan, systems=systems)
    _line_review_issues(plan, all_systems or systems)
    if ledger_sink is not None:
        ledger_sink["placements"] = rr.whole_system_ledger_placements(plan, {sid: im.shape[:2] for sid, im in images.items()},
            offsets={sid: u["strip_offset"] for sid, u in units.items()})
        ledger_sink["generated"] = generated
        ledger_sink["ledger_placements"] = ledger_sink["placements"]
        ledger_sink["ledger_removed"] = ledger_sink["removed"]
        ledger_sink["generated_origins"] = generated
        ledger_sink["pages"] = pages
        ledger_sink["measure_plan"] = {}
        _unavailable_regions(ledger_sink, plan)
        _whole_label_origins(plan, images, units, decided, generated)
        ledger_sink["plan"] = json_safe(plan)
    return json_safe(plan), pages


def _line_review_issues(plan: dict, systems: Sequence[Dict[str, Any]]) -> None:
    by = {s["id"]: s for s in systems}
    for page in plan.get("pages", []):
        for pl in page["placements"]:
            codes = [c for c in pl.get("issues", []) if c in ("FORCED_LINE_BREAK", "LINE_BELOW_MIN_SIZE")]
            if not codes:
                continue
            for sid in pl.get("system_ids", [pl["system_id"]]):
                if sid in by:
                    s = by[sid]
                    s["issues"] = list(dict.fromkeys(s.get("issues", []) + codes))
                    if "LINE_BELOW_MIN_SIZE" in codes:
                        mm = pl["effective_staff_gap_mm"]
                        s["effective_staff_gap_mm"] = min(mm, s.get("effective_staff_gap_mm", mm))


def _compose_whole_systems(records: Sequence[Dict[str, Any]], images: Dict[str, np.ndarray], *,
                           header: Optional[Dict[str, Any]], staff_gap_mm: float, auto_staff_size: bool,
                           fallback: Optional[Dict[str, Any]], generated: Optional[list] = None) -> Tuple[Dict[str, Any], List[np.ndarray]]:
    """Whole systems at ``staff_gap_mm``; when some do not fit the page (a layout conflict) and the size
    may change (``auto_staff_size``), the largest size on the automatic grid (AUTO_STEP_MM) at which
    every system fits, never below AUTO_MIN_STAFF_GAP_MM (STRATEGY Step 2A "whole-system fallback").
    The size used is disclosed in ``plan["staff_size"]`` (reason ``WHOLE_SYSTEMS_DO_NOT_FIT``). Otherwise
    the conflict is raised (reflow_layout.LayoutConflictError) with ``staff_size`` and the measure
    fallback record attached to its plan, so the reason the measure plan was not used is kept."""
    from app.pipeline import reflow_layout as rl
    from app.pipeline import reflow_measure as rmeas

    requested = float(staff_gap_mm)
    size: Dict[str, Any] = {"staff_gap_mm": requested, "staff_gap_mm_requested": requested, "auto_reduced": False,
                            "layout": "whole_systems"}
    try:
        plan, pages = rr.compose(records, images, header=header, staff_gap_mm=requested, **({"generated": generated} if generated is not None else {}))
    except rl.LayoutConflictError as exc:
        conflicts = exc.plan.get("conflicts") or []
        fits = [c.get("largest_fitting_staff_gap_mm") for c in conflicts]
        fit_mm = min(fits) if fits and all(v is not None for v in fits) else None
        size["largest_fitting_staff_gap_mm"] = fit_mm
        tried: List[Dict[str, Any]] = [{"staff_gap_mm": requested, "fits": False}]
        if not auto_staff_size:
            size["reason"] = "AUTO_OFF"
        elif fit_mm is None:
            size["reason"] = "NO_FITTING_SIZE"
        else:
            candidates = [mm for mm in rmeas.staff_size_candidates(requested) if mm <= fit_mm + 1e-9]
            if not candidates:
                size["reason"] = "BELOW_AUTO_MINIMUM"
                size["auto_min_staff_gap_mm"] = rmeas.AUTO_MIN_STAFF_GAP_MM
            for mm in candidates:
                try:
                    plan, pages = rr.compose(records, images, header=header, staff_gap_mm=mm, **({"generated": generated} if generated is not None else {}))
                except rl.LayoutConflictError:
                    tried.append({"staff_gap_mm": mm, "fits": False})
                    size["reason"] = "BELOW_AUTO_MINIMUM"
                    continue
                tried.append({"staff_gap_mm": mm, "fits": True})
                size.update(staff_gap_mm=mm, auto_reduced=True, reason="WHOLE_SYSTEMS_DO_NOT_FIT", candidates=tried,
                            systems_not_fitting_at_requested=[c.get("system_id") for c in conflicts])
                plan["staff_gap_mm_requested"] = requested
                plan["staff_size"] = size
                return plan, pages
        size["candidates"] = tried
        exc.plan["staff_size"] = size
        if fallback is not None:
            exc.plan["measure_reflow"] = fallback
        raise
    size["reason"] = "FITS"
    plan["staff_size"] = size
    return plan, pages


def json_safe(value: Any) -> Any:
    """Plain JSON types (numpy scalars/arrays become Python numbers/lists)."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def public_record(record: Dict[str, Any]) -> Dict[str, Any]:
    def compact(value):
        if isinstance(value, dict):
            return {k: compact(v) for k, v in value.items() if k != "ledger" and not k.startswith("_")}
        if isinstance(value, (list, tuple)):
            return [compact(v) for v in value]
        return value
    return json_safe(compact(record))
