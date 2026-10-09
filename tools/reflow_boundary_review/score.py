"""Fixed scorer for frozen boundary predictions (MEASURE_BRIEF "Metrics, negative controls and gates").

    backend/.venv/bin/python tools/reflow_boundary_review/score.py \
        --freeze ~/Documents/drum-score-corpus/reflow/boundaries/freeze_v1 \
        --labels <freeze>/labels/labels_<model>.json [--user <freeze>/hardcases/user_verdicts_v1.json] \
        --predictions <freeze>/predictions_m1.json [--negatives negatives.json] [--out score.json]

Rules (fixed; do not edit after labels are frozen):
* label source: the independent model's label, replaced by the user's spot-check verdict where one exists
  (S/U/? -> SAFE/UNSAFE/UNSURE). A missing label counts as UNSURE.
* accepted cut = predicted SAFE. LOCKED and UNKNOWN are both "no cut".
* unsafe accepted = accepted with label UNSAFE; accepted UNSURE = accepted with label UNSURE.
* safe-cut coverage = accepted & label SAFE / all label-SAFE candidates (every origin: missed proposals count).
* denominators are the frozen candidates; nothing is removed after the fact.
* zero-error 95% one-sided upper bound on the unsafe-accept rate: 1 - 0.05 ** (1 / n_accepted_verified).
Gates: safety (0 unsafe accepted, 0 accepted UNSURE, 100% injected negatives rejected, >= 100 verified accepted
held-out cuts else INSUFFICIENT_EVIDENCE); usefulness (>= 60% coverage overall, >= 40% per held-out video);
accounting (0 lost/duplicated pixels and exact reconstruction, from the prediction file's accounting block).
Layout and persistence gates belong to milestones 2-3 and are reported as not evaluated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

USER_MAP = {"S": "SAFE", "U": "UNSAFE", "?": "UNSURE", "SAFE": "SAFE", "UNSAFE": "UNSAFE", "UNSURE": "UNSURE"}
LABELS = ("SAFE", "UNSAFE", "UNSURE")
CLASSES = ("SAFE", "LOCKED", "UNKNOWN")


def upper_bound_zero_errors(n: int) -> Optional[float]:
    return None if n <= 0 else round(1 - 0.05 ** (1.0 / n), 4)


def metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    lab = {k: sum(1 for r in rows if r["label"] == k) for k in LABELS}
    pred = {k: sum(1 for r in rows if r["pred"] == k) for k in CLASSES}
    acc = [r for r in rows if r["pred"] == "SAFE"]
    safe = [r for r in rows if r["label"] == "SAFE"]
    acc_safe = sum(1 for r in acc if r["label"] == "SAFE")
    unsafe_acc = sum(1 for r in acc if r["label"] == "UNSAFE")
    return {
        "candidates": n,
        "labels": lab,
        "predicted": pred,
        "accepted_cuts": len(acc),
        "accepted_verified_safe": acc_safe,
        "unsafe_accepted": unsafe_acc,
        "unsafe_accepted_rate": round(unsafe_acc / len(acc), 4) if acc else None,
        "accepted_unsure": sum(1 for r in acc if r["label"] == "UNSURE"),
        "safe_cut_coverage": round(acc_safe / len(safe), 4) if safe else None,
        "label_safe": len(safe),
        "unknown_rate": round(pred["UNKNOWN"] / n, 4) if n else None,
        "locked_rate": round(pred["LOCKED"] / n, 4) if n else None,
        "unsure_rate": round(lab["UNSURE"] / n, 4) if n else None,
        "upper95_unsafe_rate_if_zero_errors": upper_bound_zero_errors(acc_safe) if unsafe_acc == 0 else None,
        "by_origin": {o: {"candidates": sum(1 for r in rows if r["origin"] == o),
                          "accepted": sum(1 for r in acc if r["origin"] == o),
                          "label_safe": sum(1 for r in safe if r["origin"] == o)} for o in C.PER_VIDEO},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", type=Path, default=C.DEFAULT_FREEZE)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--user", type=Path)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--negatives", type=Path, help="JSON {cases: [{name, class}]} from the injected negative-control tests")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    mpath = args.freeze / "candidates_manifest.json"
    manifest = json.loads(mpath.read_text())
    sha = C.sha256_file(mpath)
    labels = json.loads(args.labels.read_text())
    preds = json.loads(args.predictions.read_text())
    problems = []
    if labels.get("candidate_manifest_sha256") != sha:
        problems.append("labels reference another candidate freeze")
    if preds.get("candidate_manifest_sha256") != sha:
        problems.append("predictions reference another candidate freeze")
    if labels.get("labeller_is_implementer"):
        problems.append("labels were made by the implementer")
    if not labels.get("frozen_at_utc"):
        problems.append("labels are not frozen (frozen_at_utc missing)")
    elif labels["frozen_at_utc"] < manifest["created_at_utc"]:
        problems.append("labels frozen before the candidates")
    if problems:
        print(json.dumps({"error": problems}, indent=1))
        return 2
    by_pid = {r["packet_id"]: r for r in labels["labels"]}
    user = {}
    if args.user:
        u = json.loads(args.user.read_text())
        if u.get("candidate_manifest_sha256") != sha:
            print(json.dumps({"error": ["user verdicts reference another candidate freeze"]}))
            return 2
        user = {v["packet_id"]: USER_MAP.get(str(v.get("verdict")).upper()) for v in u["verdicts"] if v.get("verdict")}
    rows = []
    overrides = disagreements = 0
    for c in manifest["candidates"]:
        lab = (by_pid.get(c["packet_id"]) or {}).get("label")
        lab = lab if lab in LABELS else "UNSURE"
        if c["packet_id"] in user and user[c["packet_id"]]:
            overrides += 1
            disagreements += int(user[c["packet_id"]] != lab)
            lab = user[c["packet_id"]]
        p = (preds["predictions"].get(c["candidate_id"]) or {}).get("class")
        if p not in CLASSES:
            p = "UNKNOWN"
        rows.append({"cid": c["candidate_id"], "video": c["video"], "split": c["split"], "origin": c["origin"],
                     "label": lab, "pred": p})
    per_video = {v: metrics([r for r in rows if r["video"] == v]) for v in sorted({r["video"] for r in rows})}
    per_split = {s: metrics([r for r in rows if r["split"] == s]) for s in ("dev", "heldout")}
    overall = metrics(rows)
    held = per_split["heldout"]
    neg = None
    if args.negatives:
        cases = json.loads(args.negatives.read_text()).get("cases", [])
        neg = {"cases": len(cases), "rejected": sum(1 for c in cases if c.get("class") != "SAFE")}
    acct = preds.get("accounting") or {}
    gates = {
        "safety": {
            "unsafe_accepted_zero": overall["unsafe_accepted"] == 0,
            "accepted_unsure_zero": overall["accepted_unsure"] == 0,
            "injected_negatives_all_rejected": (None if neg is None else neg["rejected"] == neg["cases"] and neg["cases"] > 0),
            "heldout_verified_accepted": held["accepted_verified_safe"],
            "evidence": "SUFFICIENT" if held["accepted_verified_safe"] >= 100 else "INSUFFICIENT_EVIDENCE",
        },
        "usefulness": {
            "overall_coverage_ge_60": (overall["safe_cut_coverage"] or 0) >= 0.60,
            "heldout_videos_coverage_ge_40": {v: (per_video[v]["safe_cut_coverage"] or 0) >= 0.40
                                              for v in per_video if per_video[v] and C.SPLIT.get(v) == "heldout"},
        },
        "accounting": {"lost_px": acct.get("lost_px"), "duplicated_px": acct.get("duplicated_px"),
                       "exact_reconstruction": acct.get("exact_reconstruction"),
                       "pass": bool(acct) and acct.get("lost_px") == 0 and acct.get("duplicated_px") == 0 and bool(acct.get("exact_reconstruction"))},
        "layout": "not evaluated (milestone 2)",
        "persistence": "not evaluated (milestone 3)",
    }
    gates["safety"]["pass"] = (gates["safety"]["unsafe_accepted_zero"] and gates["safety"]["accepted_unsure_zero"]
                               and gates["safety"]["injected_negatives_all_rejected"] is True
                               and gates["safety"]["evidence"] == "SUFFICIENT")
    gates["usefulness"]["pass"] = gates["usefulness"]["overall_coverage_ge_60"] and all(gates["usefulness"]["heldout_videos_coverage_ge_40"].values())
    report = {"candidate_manifest_sha256": sha, "predictions_config_hash": preds.get("config_hash"),
              "labeller": labels.get("labeller"), "user_overrides": overrides, "user_disagreements_with_labeller": disagreements,
              "overall": overall, "per_split": per_split, "per_video": per_video, "negatives": neg, "gates": gates}
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
