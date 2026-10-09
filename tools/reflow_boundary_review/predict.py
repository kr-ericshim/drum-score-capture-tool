"""Frozen prediction submission: run the boundary classifier over the frozen candidates.

    backend/.venv/bin/python tools/reflow_boundary_review/predict.py --tag m1

Writes ``<freeze>/predictions_<tag>.json`` (class + reasons per candidate, config/code hashes,
per-video rates, real-strip pixel accounting from reflow_units) and ``<freeze>/negatives_<tag>.json``
(the injected negative and positive synthetic controls). Refuses to overwrite either file.
This is a submission, not tuning: it reads no labels.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

sys.path.insert(0, str(C.REPO / "backend" / "tests"))
from app.pipeline import reflow_accounting as ra  # noqa: E402
from app.pipeline import reflow_boundaries as rb  # noqa: E402
from app.pipeline import reflow_units as ru  # noqa: E402


def controls() -> Dict[str, Any]:
    import test_reflow_boundaries as T  # synthetic strips shared with the unit tests

    s2 = T._proposed_seam_x(2)
    neg = [
        ("tie_across", dict(tie_at=2), s2),
        ("slur_above", dict(slur_above_at=2), s2),
        ("broken_tie", dict(broken_tie_at=2), s2),
        ("blurred_tie", dict(tie_at=2, blur=1.2), s2),
        ("lyric_word_across", dict(lyric_across=2), s2),
        ("repeat_boundary", dict(repeat_at=2), s2),
        ("repeat_dots_thin", dict(repeat_at=2), T.bar_x(2) - 11),
        ("repeat_thin_thick", dict(repeat_at=2), T.bar_x(2) - 6),
        ("one_px_dot_below", dict(dot_at=(s2, T.TOP + 4 * T.G + 30)), s2),
        ("one_px_dot_above", dict(dot_at=(s2, T.TOP - 40)), s2),
        ("one_px_dot_in_staff", dict(dot_at=(s2, T.TOP + 2 * T.G + 4)), s2),
        ("faint_one_px_dot", dict(faint_dot_at=(s2 - 1, T.TOP + 4 * T.G + 40)), s2),
        ("volta_endpoint", dict(volta_end_at=2), s2),
        ("mid_measure", {}, T.bar_x(1) + 170),
        ("through_barline", {}, T.bar_x(2) + 1),
        ("left_of_plain_barline", {}, T.bar_x(2) - 20),
    ]
    # dark-theme (light ink on dark textured paper, JPEG) and start-repeat / single-dot variants
    dark = [("dark_" + name, kw, seam) for name, kw, seam in neg if name in
            ("tie_across", "slur_above", "lyric_word_across", "repeat_boundary", "repeat_dots_thin", "repeat_thin_thick",
             "one_px_dot_below", "through_barline")]
    cases = []
    sharp_cache: Dict[str, Any] = {}
    for name, kw, seam in neg + dark:
        img, rec = T.make_strip(**kw)
        key = json.dumps({k: v for k, v in kw.items() if k != "blur"}, sort_keys=True)
        if key not in sharp_cache:
            sharp_cache[key] = T.observations_of(T.make_strip(**{k: v for k, v in kw.items() if k != "blur"})[0])
        if name.startswith("dark_"):
            img = T.darken(T.barline_fringe(img))
        an = rb.analyse_strip(img, rec, observations=sharp_cache[key])
        r = rb.classify_seam(an, seam)
        cases.append({"name": name, "kind": "negative", "class": r["class"], "reasons": r["reasons"]})
    clean_obs = T.observations_of(T.make_strip()[0])
    sr_img, sr_rec = T.make_strip()
    sr_img = T.start_repeat(sr_img, 2)
    sr_an = rb.analyse_strip(sr_img, sr_rec, observations=T.observations_of(sr_img))
    for name, seam in (("start_repeat_strokes_dots", T.bar_x(2) + 4), ("start_repeat_after_dots", T.bar_x(2) + 13),
                       ("start_repeat_thick_thin", T.bar_x(2) - 2)):
        r = rb.classify_seam(sr_an, seam)
        cases.append({"name": name, "kind": "negative", "class": r["class"], "reasons": r["reasons"]})
    od_img, od_rec = T.make_strip()
    ls = T._lines()
    cv2.circle(od_img, (T.bar_x(2) + 8, (ls[1] + ls[2]) // 2), 2, T.INK, -1, cv2.LINE_AA)
    od_an = rb.analyse_strip(od_img, od_rec, observations=clean_obs)
    for name, seam in (("one_dot_after_bar_before", T.bar_x(2) + 5), ("one_dot_after_bar_after", T.bar_x(2) + 14)):
        r = rb.classify_seam(od_an, seam)
        cases.append({"name": name, "kind": "negative", "class": r["class"], "reasons": r["reasons"]})
    # a start repeat whose dots are fused with the strokes, scored at the PROPOSER's seam (light and dark)
    for name, dark in (("fused_start_repeat_proposed_seam", False), ("dark_fused_start_repeat_proposed_seam", True)):
        fs_img, fs_rec = T.make_strip()
        fs_img = T.fused_start_repeat(fs_img, 2)
        fs_obs = T.observations_of(fs_img)
        if dark:
            fs_img = T.darken(T.barline_fringe(fs_img))
        fs_an = rb.analyse_strip(fs_img, fs_rec, observations=fs_obs)
        prop = [p for p in rb.propose(fs_an) if p["bar"]["x0"] - 8 <= T.bar_x(2) <= p["bar"]["x1"] + 8]
        r = rb.classify_seam(fs_an, prop[0]["seam_x"]) if prop else {"class": "NO_PROPOSAL", "reasons": []}
        cases.append({"name": name, "kind": "negative", "class": r["class"], "reasons": r["reasons"],
                      "seam_x": prop[0]["seam_x"] if prop else None})
    pos = []
    for name, kw in (("clean", {}), ("lyrics_inside_measures", dict(lyrics=True)), ("dark_clean", dict(dark=True)),
                     ("dark_lyrics", dict(lyrics=True, dark=True))):
        dk = kw.pop("dark", False)
        img, rec = T.make_strip(**kw)
        obs = T.observations_of(img)
        if dk:
            img = T.darken(T.barline_fringe(img))
        for b in rb.strip_boundaries(rb.analyse_strip(img, rec, observations=obs)):
            pos.append({"name": f"{name}:{b['id']}", "kind": "positive", "class": b["class"], "reasons": b["reason_codes"]})
    return {"cases": cases, "positive_controls": pos,
            "negatives_rejected": sum(1 for c in cases if c["class"] != rb.SAFE), "negatives": len(cases),
            "positives_safe": sum(1 for c in pos if c["class"] == rb.SAFE), "positives": len(pos)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", type=Path, default=C.DEFAULT_FREEZE)
    ap.add_argument("--run", type=Path)
    ap.add_argument("--tag", default="m1")
    ap.add_argument("--note", default="milestone-1 classifier with the brief's initial thresholds; frozen submission, no labels read, no tuning")
    args = ap.parse_args()
    mpath = args.freeze / "candidates_manifest.json"
    manifest = json.loads(mpath.read_text())
    out = args.freeze / f"predictions_{args.tag}.json"
    neg_out = args.freeze / f"negatives_{args.tag}.json"
    if out.exists() or neg_out.exists():
        print(f"refusing: {out.name} or {neg_out.name} exists", file=sys.stderr)
        return 2
    run_dir = args.run or Path(manifest["run_dir"])
    labels_present = (args.freeze / "labels").exists()
    preds: Dict[str, Any] = {}
    per_video: Dict[str, Any] = {}
    accounting: List[Dict[str, Any]] = []
    unit_stats: Dict[str, Any] = {}
    by_video: Dict[str, List[Dict[str, Any]]] = {}
    for c in manifest["candidates"]:
        by_video.setdefault(c["video"], []).append(c)
    for video, cands in by_video.items():
        run = C.load_run(run_dir, video)
        occ_by = {s["id"]: s for s in run["occurrences"]["systems"]}
        systems = run["result"]["reflow"]["systems"]
        sys_by = {s["id"]: s for s in systems}
        analyses: Dict[str, rb.StripAnalysis] = {}
        doc_systems = []
        for s in systems:
            if not s.get("strip"):
                continue
            sp = C.strip_path(run["dir"], s)
            img = cv2.imread(str(sp))
            rec = dict(s["strip"], layout=s.get("layout"))
            regions = rb.member_regions(rec, occ_by.get(s["id"]), run["obs_by"])
            unc = None
            if (rec.get("preview_tail") or {}).get("cut"):
                up = run["dir"] / "strips" / "uncut" / sp.name
                unc = cv2.imread(str(up)) if up.exists() else None
            doc_systems.append(dict(system_id=s["id"], included=bool(s.get("included")), image=img, record=rec,
                                    observations=regions, uncut_image=unc, strip_path=str(sp.relative_to(C.CORPUS))))
        doc, analyses = ru.build_document(job_id=f"corpus:{video}", revision=0, systems=doc_systems,
                                          sources={"source_sha256": run["manifest"]["source"].get("sha256")})
        tot = doc["audit"]["accounting"]["totals"]
        accounting.append(dict(video=video, **{k: tot[k] for k in ("assets", "pixels", "lost_px", "duplicated_px", "mismatched_px",
                                                                   "protected_px", "protected_lost_px", "exact_reconstruction")},
                               validation=doc["audit"]["validation"]["status"], validation_errors=doc["audit"]["validation"]["errors"][:5],
                               cut_strip_consistency=[a.get("cut_strip_consistency") for a in doc["audit"]["accounting"]["assets"]
                                                      if a.get("asset_role") == "uncut"]))
        unit_stats[video] = doc["stats"]
        counts = {k: 0 for k in rb.CLASSES}
        for c in cands:
            an = analyses.get(c["system_id"])
            if an is None:
                s = sys_by[c["system_id"]]
                rec = dict(s["strip"], layout=s.get("layout"))
                an = rb.analyse_strip(cv2.imread(str(C.CORPUS / c["strip"]["path"])), rec, system_id=s["id"],
                                      observations=rb.member_regions(rec, occ_by.get(s["id"]), run["obs_by"]))
            if C.pixels_sha256(an.image) != c["strip"]["pixels_sha256"]:
                r = {"class": rb.UNKNOWN, "reasons": ["STRIP_HASH_MISMATCH"]}
            else:
                r = rb.classify_seam(an, int(c["seam"]["x_strip"]))
            preds[c["candidate_id"]] = {"class": r["class"], "reasons": r["reasons"]}
            counts[r["class"]] += 1
        n = len(cands)
        per_video[video] = {"split": C.SPLIT[video], "candidates": n, "counts": counts,
                            "rates": {k: round(v / n, 4) for k, v in counts.items()},
                            "by_origin": {o: {k: sum(1 for c in cands if c["origin"] == o and preds[c["candidate_id"]]["class"] == k)
                                              for k in rb.CLASSES} for o in C.PER_VIDEO}}
    acct_tot = {"lost_px": sum(a["lost_px"] for a in accounting), "duplicated_px": sum(a["duplicated_px"] for a in accounting),
                "mismatched_px": sum(a["mismatched_px"] for a in accounting),
                "exact_reconstruction": all(a["exact_reconstruction"] for a in accounting), "per_video": accounting}
    code = {p: C.sha256_file(C.REPO / "backend" / "app" / "pipeline" / p)
            for p in ("reflow_boundaries.py", "reflow_units.py", "reflow_accounting.py", "system_detect.py")}
    sub = {
        "schema_version": 1,
        "kind": "boundary_predictions",
        "tag": args.tag,
        "protocol_version": C.PROTOCOL_VERSION,
        "candidate_manifest_sha256": C.sha256_file(mpath),
        "submitted_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "labels_present_at_submission": labels_present,
        "note": args.note,
        "config": rb.CONFIG,
        "config_hash": rb.config_hash(),
        "code_sha256": code,
        "per_video": per_video,
        "unit_stats": unit_stats,
        "accounting": acct_tot,
        "predictions": preds,
    }
    C.write_json(out, sub)
    ctl = controls()
    ctl.update(config_hash=rb.config_hash(), code_sha256=code)
    C.write_json(neg_out, ctl)
    print(json.dumps({"predictions": str(out), "config_hash": sub["config_hash"],
                      "per_video": {v: per_video[v]["counts"] for v in per_video},
                      "accounting": {k: acct_tot[k] for k in ("lost_px", "duplicated_px", "mismatched_px", "exact_reconstruction")},
                      "negatives_rejected": f"{ctl['negatives_rejected']}/{ctl['negatives']}",
                      "positives_safe": f"{ctl['positives_safe']}/{ctl['positives']}"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
