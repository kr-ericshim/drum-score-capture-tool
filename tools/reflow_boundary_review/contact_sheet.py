"""Hard-case contact sheet: one PNG with a few dozen numbered crops for the user's spot check.

    backend/.venv/bin/python tools/reflow_boundary_review/contact_sheet.py \
        --freeze ~/Documents/drum-score-corpus/reflow/boundaries/freeze_v1 \
        --labels <freeze>/labels/labels_<model>.json [--predictions <freeze>/predictions_m1.json] [--n 36]

Selection (recorded in the JSON next to the PNG, never drawn on the image):
1. items the independent labeller marked UNSURE;
2. items where the labeller and a frozen prediction disagree (label UNSAFE vs predicted SAFE first,
   then label SAFE vs predicted LOCKED);
3. a seeded random audit sample of the labeller's SAFE and UNSAFE answers.
The tiles show only a number, the source crop and the seam ticks: no label, no verdict, no origin.
Writes ``hardcases/contact_sheet_<tag>.png``, ``hardcases/contact_sheet_<tag>.json`` (number -> packet id)
and ``hardcases/user_verdicts_<tag>_template.json`` (the user writes S / U / ? per number).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

TILE_W = 880
COLS = 3
HEAD = 40


def select(packet: Dict[str, Any], labels: Dict[str, Any], predictions: Optional[Dict[str, Any]],
           manifest: Dict[str, Any], n: int) -> List[Dict[str, str]]:
    lab = {r["packet_id"]: r for r in labels["labels"]}
    pid_to_cid = {c["packet_id"]: c["candidate_id"] for c in manifest["candidates"]}
    pred = {}
    if predictions:
        for cid, p in predictions["predictions"].items():
            pred[cid] = p["class"]
    chosen: List[Dict[str, str]] = []
    seen = set()

    def add(pid: str, why: str) -> None:
        if pid not in seen and len(chosen) < n:
            seen.add(pid)
            chosen.append({"packet_id": pid, "why": why})

    for it in packet["items"]:
        if (lab.get(it["packet_id"]) or {}).get("label") == "UNSURE":
            add(it["packet_id"], "labeller_unsure")
    for want_label, want_pred, why in (("UNSAFE", "SAFE", "label_unsafe_pred_safe"), ("SAFE", "LOCKED", "label_safe_pred_locked"),
                                       ("SAFE", "UNKNOWN", "label_safe_pred_unknown")):
        for it in packet["items"]:
            pid = it["packet_id"]
            if (lab.get(pid) or {}).get("label") == want_label and pred.get(pid_to_cid[pid]) == want_pred:
                add(pid, why)
    rng = C.seeded_rng("contact_sheet", labels.get("labeller"))
    rest = [it["packet_id"] for it in packet["items"] if it["packet_id"] not in seen and (lab.get(it["packet_id"]) or {}).get("label") in ("SAFE", "UNSAFE")]
    for i in rng.permutation(len(rest)):
        add(rest[int(i)], "audit_sample")
    return chosen


def render_sheet(packet_dir: Path, packet: Dict[str, Any], chosen: List[Dict[str, str]]) -> np.ndarray:
    items = {it["packet_id"]: it for it in packet["items"]}
    tiles = []
    for k, ch in enumerate(chosen, start=1):
        it = items[ch["packet_id"]]
        img = cv2.imread(str(packet_dir / it["images"]["plain"]))
        if img.shape[1] > TILE_W:  # keep the seam in view: crop around it instead of shrinking (keeps 1-px dots)
            sx = it["seam_x_image"]
            x0 = int(np.clip(sx - TILE_W // 2, 0, img.shape[1] - TILE_W))
            img = img[:, x0:x0 + TILE_W]
        tile = np.full((img.shape[0] + HEAD, TILE_W, 3), 255, np.uint8)
        tile[HEAD:, :img.shape[1]] = img
        cv2.putText(tile, str(k), (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.rectangle(tile, (0, 0), (TILE_W - 1, tile.shape[0] - 1), (150, 150, 150), 1)
        tiles.append(tile)
    rows = []
    for r in range(0, len(tiles), COLS):
        row = tiles[r:r + COLS]
        h = max(t.shape[0] for t in row)
        canvas = np.full((h, TILE_W * COLS, 3), 255, np.uint8)
        for j, t in enumerate(row):
            canvas[:t.shape[0], j * TILE_W:(j + 1) * TILE_W] = t
        rows.append(canvas)
    return np.vstack(rows) if rows else np.full((10, 10, 3), 255, np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", type=Path, default=C.DEFAULT_FREEZE)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--predictions", type=Path)
    ap.add_argument("--n", type=int, default=36)
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args()
    manifest_path = args.freeze / "candidates_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    packet = json.loads((args.freeze / "packet" / "labeller_packet.json").read_text())
    labels = json.loads(args.labels.read_text())
    sha = C.sha256_file(manifest_path)
    if labels.get("candidate_manifest_sha256") != sha:
        print("labels do not reference this candidate freeze", file=sys.stderr)
        return 2
    predictions = json.loads(args.predictions.read_text()) if args.predictions else None
    chosen = select(packet, labels, predictions, manifest, args.n)
    sheet = render_sheet(args.freeze / "packet", packet, chosen)
    out_dir = args.out_dir or (args.freeze / "hardcases")
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"contact_sheet_{args.tag}.png"
    cv2.imwrite(str(png), sheet, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    mapping = {"candidate_manifest_sha256": sha, "labels_file": str(args.labels), "image": png.name,
               "tiles": [{"number": k, **ch} for k, ch in enumerate(chosen, start=1)]}
    C.write_json(out_dir / f"contact_sheet_{args.tag}.json", mapping)
    C.write_json(out_dir / f"user_verdicts_{args.tag}_template.json", {
        "kind": "boundary_user_spot_check", "candidate_manifest_sha256": sha, "image": png.name, "frozen_at_utc": None,
        "legend": "S = safe to cut here, U = unsafe, ? = unsure",
        "verdicts": [{"number": k, "packet_id": ch["packet_id"], "verdict": None} for k, ch in enumerate(chosen, start=1)]})
    print(json.dumps({"png": str(png), "tiles": len(chosen), "bytes": png.stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
