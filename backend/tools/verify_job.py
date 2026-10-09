#!/usr/bin/env python3
"""Offline A+B+C over a saved job/export. Inputs are never modified.

Usage: PYTHONPATH=backend backend/.venv/bin/python backend/tools/verify_job.py WORKSPACE
       --artifacts ARTIFACT_DIR --output /tmp/verification
Old JPEG exports require a newly staged lossless export before C can assess them.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import tempfile
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_pipeline as rp
from app.pipeline import reflow_verify_common as vc
from app.pipeline import reflow_verify_strip as va
from app.pipeline import reflow_verify_plan as vb
from app.pipeline import reflow_verify_page as vp


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_job(path: Path, *, artifacts: Path | None = None, output: Path | None = None) -> dict:
    output = output or Path(tempfile.mkdtemp(prefix="verify-job-"))
    path = path.resolve()
    output = output.resolve()
    artifact = (artifacts or (path if (path/"sink.json").is_file() else path/"export")).resolve()
    sink = read(artifact/"sink.json")
    plan = read(artifact/"plan.json")
    workspace = Path(sink.get("workspace") or (path/"reflow" if (path/"reflow").is_dir() else path))
    # Artifact-only invocation follows persisted evidence/strip locations.
    # No video IDs or corpus-specific directory names are assumed.
    candidates = [workspace, artifact.parent/"reflow"]
    if sink.get("strip_paths"):
        candidates.extend(Path(next(iter(sink["strip_paths"].values()))).parents[:4])
    if (artifact/"ledger.json").is_file():
        saved = read(artifact/"ledger.json")
        if saved.get("evidence_root"):
            candidates.append(Path(saved["evidence_root"]).parent)
    workspace = next((p for p in candidates if (p/"ledger_base.json").is_file()), workspace)
    record_path = workspace/"wd3_record.json"
    record = read(record_path) if record_path.is_file() else {"workspace": str(workspace), "systems": sink.get("systems", [])}
    if output == path or output == artifact or output == workspace or any(output.is_relative_to(p) for p in (path, artifact, workspace)):
        raise ValueError("output must be outside read-only input directories")
    output.mkdir(parents=True, exist_ok=True)
    base = read(workspace/"ledger_base.json")
    chains = read(workspace/"ledger_chains.json")
    record.update(workspace=str(workspace))
    systems = sink.get("systems") or [dict(s, included=s["id"] in set(sink.get("decided_system_ids", []))) for s in record["systems"]]
    paths = sink.get("strip_paths") or {s["id"]: s["strip_path"] for s in systems if s.get("included", True)}
    strips = {sid: cv2.imread(str(p)) for sid, p in paths.items()}
    if any(image is None for image in strips.values()):
        raise ValueError("an input strip is unreadable")
    observations = {o["id"]: o for o in base["observations"]}
    def frame(oid):
        obs = observations[oid]
        image = cv2.imread(obs["frame_path"], cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"unreadable committed frame: {oid}")
        return image
    report = {"status": "pass", "stage_seconds": {}, "issues": [], "certificates": {"A": {}}, "exceptions": {}}
    for stage in ("A", "B", "C"):
        start = time.perf_counter()
        try:
            if stage == "A":
                by_id = {s["id"]: s for s in systems}
                for sid, image in strips.items():
                    rec = dict(by_id[sid].get("strip") or {}, system_id=sid)
                    cert = va.verify_strip(base, rec, image, frames=frame, chain=chains.get(sid, []))
                    report["certificates"]["A"][sid] = cert
                    report["issues"].extend(cert["findings"])
            elif stage == "B":
                cert = vb.verify_plan(report["certificates"]["A"], plan, sink, strips, systems=systems)
                report["certificates"]["B"] = cert
                report["issues"].extend(cert["findings"])
            else:
                cert = vp.verify_pages(report["certificates"]["B"], strips, artifact/"sheet_export.pdf",
                                       generated=sink.get("generated", sink.get("generated_origins", [])), profile="lossless")
                report["certificates"]["C"] = cert
                report["issues"].extend(cert["findings"])
        except Exception as exc:
            logging.exception("offline Stage %s failed", stage)
            report["exceptions"][stage] = {"type": type(exc).__name__, "detail": str(exc)}
        report["stage_seconds"][stage] = time.perf_counter()-start
    report["status"] = "fail" if any(f["severity"] == "fail" for f in report["issues"]) else "unassessed" if report["exceptions"] else "review_required" if report["issues"] else "pass"
    cert_b = report["certificates"].get("B", {})
    pages, expected = [], []
    try:
        pages = vp.decode_lossless_pdf(artifact/"sheet_export.pdf", profile="lossless")
        expected = vp.render_expected(cert_b, strips, sink.get("generated", []), len(pages))
    except Exception:
        logging.exception("offline example page crops unavailable")
    review = rp.write_review_hypotheses(record, {}, dict(report, staged_verification=True), output, pages=pages,
        expected=expected, strips=strips, cert_b=cert_b, sink=dict(sink, plan=plan), crop_limit=20)
    report.update(counts=review["counts"], output=str(output))
    rp._dump(report, output/"verify_report.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_job(args.path, artifacts=args.artifacts, output=args.output)
    print(json.dumps({k: report[k] for k in ("status", "stage_seconds", "counts", "exceptions", "output")}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
