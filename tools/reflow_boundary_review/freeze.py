"""Freeze the boundary candidates (MEASURE_BRIEF milestone 0).

    backend/.venv/bin/python tools/reflow_boundary_review/freeze.py \
        [--run ~/Documents/drum-score-corpus/reflow/e2e_r5] \
        [--out ~/Documents/drum-score-corpus/reflow/boundaries/freeze_v1]

Writes (only into ``--out``, which must not exist yet):

* ``candidates_manifest.json`` - the frozen candidates with source/frame hashes, PTS, crop
  coordinates, exact seam and ownership proposal, origin, strata, seed, split, protocol;
* ``packet/labeller_packet.json`` + ``packet/crops/*.jpg`` - what the independent labeller
  sees (no origin, no verdict, shuffled order);
* ``packet/labels_template.json`` - the file the labeller fills (SAFE/UNSAFE/UNSURE + reason).

The run directory is read only. Frames are decoded in memory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as K  # noqa: E402
import common as C  # noqa: E402
import render as R  # noqa: E402
from app.pipeline import observations as ob  # noqa: E402

LABEL_INSTRUCTIONS = """You label proposed cut lines through drum-score images taken from videos.

Each item shows a vertical cut line (red ticks above and below the image; image b draws the line over the
image; image c is another moment of the same score display, for checking playback marks). Imagine the
score image is cut along this line over its FULL height: every pixel left of the line goes with the left
piece, every pixel on or right of it with the right piece, and the two pieces may end up on different
lines of a new page (the staff lines are redrawn; only staff lines may be cut).

Answer SAFE only when ALL of these hold:
  1. the line is at a boundary between two measures (next to a barline), not inside a measure;
  2. the line passes only through blank paper and staff lines over the full height (lyrics, text, labels,
     tempo marks, dynamics and markings above and below the staff included);
  3. nothing that belongs together is separated: no tie, slur, beam, tuplet bracket, volta bracket,
     hairpin, multi-measure rest, lyric word / hyphen / extender, text or label crosses the line;
  4. the barline group stays with the right measure: an ordinary barline and an end-repeat (dots on its
     left) with the LEFT piece, a start-repeat (dots on its right) with the RIGHT piece; repeat dots are
     never separated from their barline; a double/final barline is not split between its strokes;
  5. each symbol near the line clearly belongs to one side.
Answer UNSAFE when any rule is broken. Answer UNSURE when the image does not let you decide (blurred,
covered by a playback mark, cut off, unclear which side a symbol belongs to). Do not guess; UNSURE is a
valid answer. Coloured lines/boxes that move between image a and image c are playback marks, not score.
Give a short reason naming what you saw (e.g. "clear gap after barline", "tie crosses", "lyric word
'...' split", "inside measure", "repeat dots on the right go left").
"""


def _other_member(rec: Dict[str, Any], obs_by: Dict[str, Dict[str, Any]]) -> str:
    ref = rec["reference_obs_id"]
    t_ref = obs_by[ref]["t_sec"]
    members = [m for m in rec.get("member_obs_ids") or [] if m in obs_by and m != ref]
    if not members:
        return ref
    return max(members, key=lambda m: abs(obs_by[m]["t_sec"] - t_ref))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=C.DEFAULT_RUN)
    ap.add_argument("--out", type=Path, default=C.DEFAULT_FREEZE)
    ap.add_argument("--videos", nargs="*", default=list(C.SPLIT))
    args = ap.parse_args()
    out: Path = args.out
    if out.exists():
        print(f"refusing: {out} exists (a freeze is never overwritten)", file=sys.stderr)
        return 2
    crops_dir = out / "packet" / "crops"
    crops_dir.mkdir(parents=True)
    created = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    per_video: Dict[str, Any] = {}
    all_cands: List[Dict[str, Any]] = []
    sources: Dict[str, Any] = {}
    for video in args.videos:
        run = C.load_run(args.run, video)
        gen = K.generate(run, video)
        man = run["manifest"]
        src_path = Path(man["source"]["path"])
        if not src_path.exists():
            src_path = C.VIDEOS / f"{video}.mp4"
        file_sha = C.sha256_file(src_path)
        info_path = C.VIDEOS / f"{video}.info.json"
        channel = None
        if info_path.exists():
            info = json.loads(info_path.read_text())
            channel = info.get("channel")
        sources[video] = {"path": str(src_path), "sha256": file_sha, "manifest_sha256": man["source"].get("sha256"),
                          "sha256_matches_manifest": file_sha == man["source"].get("sha256"),
                          "fps": man["source"].get("fps"), "frame_size": man["source"].get("frame_size"),
                          "template_group": channel, "split": C.SPLIT[video]}
        systems = {s["id"]: s for s in C.included_systems(run)}
        obs_by = run["obs_by"]
        strip_hash: Dict[str, Dict[str, str]] = {}
        rng = C.seeded_rng(video, "candidate_ids")
        order = rng.permutation(len(gen["candidates"]))
        for k, i in enumerate(order):
            c = gen["candidates"][int(i)]
            s = systems[c["system_id"]]
            rec = s["strip"]
            sp = C.strip_path(run["dir"], s)
            if s["id"] not in strip_hash:
                strip_hash[s["id"]] = {"file_sha256": C.sha256_file(sp),
                                       "pixels_sha256": C.pixels_sha256(gen["images"][s["id"]])}
            other = _other_member(rec, obs_by)
            crop_size = tuple(obs_by[rec["reference_obs_id"]]["crop_size"])
            win = R.crop_window(c, rec, crop_size)
            c["candidate_id"] = f"{video}-c{k:03d}"
            c["strip"] = {"path": str(sp.relative_to(C.CORPUS)), **strip_hash[s["id"]], "box_crop": rec["box_crop"],
                          "size": rec["size"], "inverted": rec.get("inverted"), "layout": s.get("layout"),
                          "member_obs_ids": rec.get("member_obs_ids"), "issues": rec.get("issues")}
            c["crop"] = {"box_crop": win,
                         "box_source": ob.crop_box_to_source(obs_by[rec["reference_obs_id"]]["source_to_crop"], win),
                         "applied_roi": obs_by[rec["reference_obs_id"]]["applied_roi"],
                         "seam_x_crop": c["seam"]["x_crop"],
                         "seam_x_source": round(ob.crop_to_source_point(obs_by[rec["reference_obs_id"]]["source_to_crop"],
                                                                         c["seam"]["x_crop"], (win[1] + win[3]) / 2)[0], 2)}
            c["_win"] = win
            c["_ref"], c["_other"] = rec["reference_obs_id"], other
            c["_obs_by"] = obs_by
            c["_src"] = src_path
            c["_fps"] = float(man["source"].get("fps") or 30.0)
            all_cands.append(c)
        per_video[video] = {
            "split": C.SPLIT[video], "candidates": len(gen["candidates"]),
            "by_origin": {o: sum(1 for c in gen["candidates"] if c["origin"] == o) for o in C.PER_VIDEO},
            "by_primary_stratum": {k: sum(1 for c in gen["candidates"] if c["stratum"] == k) for k in C.STRATA},
            "by_stratum_tag": {k: sum(1 for c in gen["candidates"] if k in c["strata"]) for k in C.STRATA},
            "absent_strata": gen["absent_strata"], "pool": gen["pool"], "shortfall": gen["shortfall"],
            "view_groups": gen["view_groups"],
        }

    # global shuffled packet ids (order carries no origin)
    rng = C.seeded_rng("packet_order")
    perm = rng.permutation(len(all_cands))
    for n, i in enumerate(perm, start=1):
        all_cands[int(i)]["packet_id"] = f"P{n:03d}"
    items = []
    for video in args.videos:
        cands = [c for c in all_cands if c["video"] == video]
        obs_by = cands[0]["_obs_by"]
        need = sorted({c["_ref"] for c in cands} | {c["_other"] for c in cands})
        times = {oid: obs_by[oid]["t_sec"] for oid in need}
        decoded = R.decode_frames(cands[0]["_src"], times.values())
        frames, frame_meta = {}, {}
        for oid, t in times.items():
            pts, frame = decoded[round(float(t), 6)]
            frames[oid] = frame
            frame_meta[oid] = {"obs_id": oid, "t_sec_manifest": t, "pts_decoded": pts,
                               "pts_matches": abs(pts - t) <= 0.5 / cands[0]["_fps"],
                               "frame_sha256": C.pixels_sha256(frame), "frame_shape": list(frame.shape)}
        del decoded
        for c in cands:
            pid = c["packet_id"]
            c["source_frames"] = {"reference": frame_meta[c["_ref"]], "other": frame_meta[c["_other"]]}
            r = R.render_candidate(frames, obs_by, c["_ref"], c["_other"], c["_win"], c["seam"]["x_crop"], crops_dir, pid)
            c["crop"].update(seam_x_image=r["seam_x_image"], image_size=r["image_size"], content_rows_image=r["content_rows_image"],
                             crop_pixels_sha256=r["crop_pixels_sha256"], files=r["files"])
            items.append({"packet_id": pid, "video": c["video"], "images": {k: f"crops/{v}" for k, v in r["files"].items()},
                          "image_size": r["image_size"], "seam_x_image": r["seam_x_image"],
                          "content_rows_image": r["content_rows_image"],
                          "staff_gap_px": round(float(c["staff"]["gap_px"]), 2),
                          "source_dark_theme": bool(c["strip"].get("inverted"))})
        del frames
    for c in all_cands:
        for k in [k for k in c if k.startswith("_")]:
            del c[k]
    all_cands.sort(key=lambda c: c["candidate_id"])
    items.sort(key=lambda it: it["packet_id"])

    tool_dir = Path(__file__).resolve().parent
    manifest = {
        "schema_version": 1,
        "kind": "boundary_candidate_freeze",
        "protocol_version": C.PROTOCOL_VERSION,
        "created_at_utc": created,
        "run_dir": str(args.run),
        "sampling_seed": C.SAMPLING_SEED,
        "per_video_quota": C.PER_VIDEO,
        "split": {v: C.SPLIT[v] for v in args.videos},
        "split_note": "held-out videos were already seen by the project (e2e runs); this is a prospective tuning holdout, not proof of unseen-style generalisation",
        "template_check": {"rule": "videos sharing a channel/template would be grouped in one split",
                           "groups": {v: sources[v]["template_group"] for v in sources},
                           "shared_templates": sorted({g for g in (sources[v]["template_group"] for v in sources)
                                                      if sum(1 for w in sources if sources[w]["template_group"] == g) > 1} - {None})},
        "sources": sources,
        "tool_code_sha256": {p.name: C.sha256_file(p) for p in sorted(tool_dir.glob("*.py"))},
        "detector": {"module": "app.pipeline.system_detect", "version": C.sd.DETECTOR_VERSION},
        "classifier_used_for_candidates": False,
        "strata": list(C.STRATA),
        "strata_note": "strata tags are geometric heuristics used for sampling and reporting only; synthetic substitutes are not counted",
        "per_video": per_video,
        "freeze_order": [
            {"step": 1, "what": "candidate_freeze", "status": "frozen", "at_utc": created},
            {"step": 2, "what": "label_freeze (independent model labels + user spot-check of hard cases on one image)",
             "status": "pending"},
            {"step": 3, "what": "classifier threshold tuning (dev split only)", "status": "not_started",
             "rule": "only after step 2; held-out labels are never used for tuning"},
        ],
        "m1_prediction_submission": {"status": "pending", "note": "milestone-1 classifier run over these candidates before labels exist; a frozen submission, not tuning"},
        "candidates": all_cands,
    }
    C.write_json(out / "candidates_manifest.json", manifest)
    man_sha = C.sha256_file(out / "candidates_manifest.json")
    packet = {
        "schema_version": 1,
        "kind": "boundary_labeller_packet",
        "protocol_version": C.PROTOCOL_VERSION,
        "candidate_manifest_sha256": man_sha,
        "labels": ["SAFE", "UNSAFE", "UNSURE"],
        "instructions": LABEL_INSTRUCTIONS,
        "output": "copy labels_template.json to labels_<labeller>.json, fill label and reason for every item, set labeller and frozen_at_utc",
        "items": items,
    }
    C.write_json(out / "packet" / "labeller_packet.json", packet)
    C.write_json(out / "packet" / "labels_template.json", {
        "schema_version": 1, "kind": "boundary_labels", "protocol_version": C.PROTOCOL_VERSION,
        "candidate_manifest_sha256": man_sha, "labeller": None, "labeller_is_implementer": False, "frozen_at_utc": None,
        "labels": [{"packet_id": it["packet_id"], "label": None, "reason": None} for it in items]})
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(json.dumps({"out": str(out), "candidates": len(all_cands), "bytes": size, "manifest_sha256": man_sha,
                      "per_video": {v: {k: per_video[v][k] for k in ("by_origin", "absent_strata", "shortfall")} for v in per_video}},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
