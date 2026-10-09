"""Dev-split-only evaluation of the boundary classifier (classifier tuning aid).

    backend/.venv/bin/python tools/reflow_boundary_review/dev_eval.py [-v] [-d] [--json OUT]

Reads only ``<freeze>/labels/labels_claude-opus_dev.json``, the physically split dev-only label
file (labels whose candidate has ``split == "dev"`` in the candidate manifest). It never opens the
full label file, so held-out labels are not read. It refuses to run when the dev file holds a
label of a non-dev candidate.

Prints per-video and dev-total accepted cuts, unsafe accepted cuts and safe-cut coverage of the
current classifier (``app.pipeline.reflow_boundaries``) at the frozen seams.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

from app.pipeline import reflow_boundaries as rb  # noqa: E402

DEV_LABELS = "labels_claude-opus_dev.json"


def load(freeze: Path):
    man = json.loads((freeze / "candidates_manifest.json").read_text())
    cands = [c for c in man["candidates"] if c["split"] == "dev"]
    dev_pids = {c["packet_id"] for c in cands}
    doc = json.loads((freeze / "labels" / DEV_LABELS).read_text())
    if doc.get("split") != "dev" or any(r["packet_id"] not in dev_pids for r in doc["labels"]):
        raise SystemExit(f"refusing: {DEV_LABELS} is not a dev-only label file")
    labels = {r["packet_id"]: r for r in doc["labels"]}
    return man, cands, labels


def run(man: Dict[str, Any], cands: List[Dict[str, Any]], labels: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    cache: Dict[Any, rb.StripAnalysis] = {}
    for video in sorted({c["video"] for c in cands}):
        run_ = C.load_run(Path(man["run_dir"]), video)
        occ_by = {s["id"]: s for s in run_["occurrences"]["systems"]}
        sys_by = {s["id"]: s for s in run_["result"]["reflow"]["systems"]}
        for c in [c for c in cands if c["video"] == video]:
            sid = c["system_id"]
            key = (video, sid)
            if key not in cache:
                s = sys_by[sid]
                rec = dict(s["strip"], layout=s.get("layout"))
                img = cv2.imread(str(C.CORPUS / c["strip"]["path"]))
                cache[key] = rb.analyse_strip(img, rec, system_id=sid,
                                              observations=rb.member_regions(rec, occ_by.get(sid), run_["obs_by"]))
            r = rb.classify_seam(cache[key], int(c["seam"]["x_strip"]))
            lab = labels.get(c["packet_id"], {})
            rows.append(dict(cid=c["candidate_id"], pid=c["packet_id"], video=video, origin=c["origin"],
                             label=lab.get("label", "UNSURE"), pred=r["class"], reasons=r["reasons"], stratum=c["stratum"],
                             seam=c["seam"]["x_strip"], sid=sid, lreason=lab.get("reason")))
    return rows


def summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for v in sorted({r["video"] for r in rows}) + ["dev"]:
        rr = [r for r in rows if v == "dev" or r["video"] == v]
        acc = [r for r in rr if r["pred"] == "SAFE"]
        safe = [r for r in rr if r["label"] == "SAFE"]
        out[v] = dict(n=len(rr), label_safe=len(safe), accepted=len(acc),
                      acc_safe=sum(r["label"] == "SAFE" for r in acc),
                      unsafe_acc=sum(r["label"] == "UNSAFE" for r in acc),
                      unsure_acc=sum(r["label"] == "UNSURE" for r in acc),
                      coverage=round(sum(r["label"] == "SAFE" for r in acc) / max(1, len(safe)), 3),
                      predicted={k: sum(r["pred"] == k for r in rr) for k in rb.CLASSES})
    out["config_hash"] = rb.config_hash()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", type=Path, default=C.DEFAULT_FREEZE)
    ap.add_argument("--json", type=Path, help="also write the summary and rows here")
    ap.add_argument("-v", action="store_true", help="reason counts of missed SAFE labels and any bad accepts")
    ap.add_argument("-d", action="store_true", help="list every missed SAFE label")
    args = ap.parse_args()
    man, cands, labels = load(args.freeze)
    rows = run(man, cands, labels)
    summ = summary(rows)
    print(json.dumps(summ, indent=1))
    if args.json:
        args.json.write_text(json.dumps({"summary": summ, "rows": rows}, indent=1))
    miss = [r for r in rows if r["label"] == "SAFE" and r["pred"] != "SAFE"]
    if args.v:
        cnt = collections.Counter(x for r in miss for x in r["reasons"])
        print("missed SAFE reason counts", cnt.most_common())
        for k, n in collections.Counter(tuple(r["reasons"]) for r in miss).most_common(30):
            print(n, k)
        for r in rows:
            if r["pred"] == "SAFE" and r["label"] != "SAFE":
                print("BAD ACCEPT", r)
    if args.d:
        for r in miss:
            print(r["cid"], r["pid"], r["sid"], r["seam"], r["origin"], r["reasons"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
