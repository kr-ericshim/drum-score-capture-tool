"""Render a corpus run's chart with measure-level reflow ON, in-process (no job, no API).

    PYTHONPATH=backend backend/.venv/bin/python tools/reflow_boundary_review/render_measure.py \
        --run ~/Documents/drum-score-corpus/reflow/e2e_r6 --out ~/Documents/drum-score-corpus/reflow/measure_m2 \
        S1nlqQdnUks aOED5zskhGk

Reads the run directory read-only (result.json, manifest.json, occurrences.json, strips/, labels/)
and writes ``<out>/<video>/``: sheet_export.pdf, images/page_NN.png (via export_composed_pages),
plan.json (the page plan with its ``measure_reflow`` record) and summary.json. Refuses to write
inside the run directory or into an existing output folder.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.pipeline import reflow_pipeline as rp  # noqa: E402
from app.pipeline.export import export_composed_pages  # noqa: E402


def _remap(path: Any, vdir: Path, sub: str) -> Any:
    if not path:
        return path
    name = str(path).split(f"/{sub}/")[-1]
    return str(vdir / sub / name)


def systems_of(vdir: Path) -> List[Dict[str, Any]]:
    result = json.loads((vdir / "result.json").read_text())
    systems = []
    for s in result["reflow"]["systems"]:
        s = json.loads(json.dumps(s))
        s["strip_path"] = _remap(s.get("strip_path"), vdir, "strips")
        unc = (s.get("strip") or {}).get("uncut")
        if unc and unc.get("path"):
            unc["path"] = _remap(unc["path"], vdir, "strips")
        if (s.get("label") or {}).get("path"):
            s["label"]["path"] = _remap(s["label"]["path"], vdir, "labels")
        systems.append(s)
    return systems, result["reflow"]


def summarize(plan: Dict[str, Any]) -> Dict[str, Any]:
    m = plan.get("measure_reflow") or {}
    lines = m.get("lines") or []
    adj = [ln["adjustment_fraction"] for ln in lines]
    return {
        "status": m.get("status"),
        "reason": m.get("reason"),
        "pages": len(plan.get("pages", [])),
        "lines": len(lines),
        "lines_per_page": [len(p["placements"]) for p in plan.get("pages", [])],
        "measures_per_line": m.get("measures_per_line"),
        "measures_per_line_estimated": m.get("measures_per_line_estimated"),
        "justified_edge": m.get("justified_edge"),
        "justified_lines": sum(1 for ln in lines if ln.get("justified")),
        "justification": m.get("justification"),
        "ragged": [{k: r.get(k) for k in ("line_id", "reason", "final_line", "natural_width", "requested_width", "achieved_width",
                                           "available_expand_px", "segment_atoms", "forced_break_after")}
                   for r in m.get("ragged_exceptions", [])],
        "lines_detail": [{"id": ln["id"], "measures": ln.get("measure_count"), "natural": ln["natural_width"],
                          "achieved": ln["achieved_width"], "justified": ln["justified"], "tier": ln.get("justify_tier"),
                          "adjustment": ln["adjustment_fraction"], "max_gap_growth": ln.get("max_gap_growth"),
                          "joined": ln.get("joined_system_ids")} for ln in lines],
        "adjustment_fraction": {"min": min(adj) if adj else None, "max": max(adj) if adj else None},
        "natural_width_px": sorted({ln["natural_width"] for ln in lines}),
        "target_width_px": lines[0]["target_width"] if lines else None,
        "boundary_counts": m.get("boundary_counts"),
        "replicas": len((m.get("audit") or {}).get("replicas", [])),
        "scaffold_ops": {op: sum(1 for x in (m.get("audit") or {}).get("scaffold_operations", []) if x.get("op") == op)
                         for op in ("insert_scaffold_columns", "remove_scaffold_columns", "insert_spread_columns",
                                   "remove_spread_columns", "margin_trim")},
        "validation": (m.get("audit") or {}).get("validation"),
        "native_accounting": (m.get("audit") or {}).get("native_accounting"),
        "render_mismatched_px": (m.get("audit") or {}).get("render_mismatched_px"),
        "conflicts": m.get("conflicts"),
        "labels": m.get("labels"),
        "plan_valid": (plan.get("validation") or {}).get("valid"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--staff-gap-mm", type=float, default=1.5)
    ap.add_argument("videos", nargs="+")
    args = ap.parse_args()
    run, out = args.run.resolve(), args.out.resolve()
    if out == run or run in out.parents:
        print("refusing: output inside the run directory", file=sys.stderr)
        return 2
    for v in args.videos:
        vdir = run / v
        odir = out / v
        if odir.exists():
            print(f"refusing: {odir} exists", file=sys.stderr)
            return 2
        systems, reflow = systems_of(vdir)
        included = [s for s in systems if s.get("included")]
        ctx = {"manifest": json.loads((vdir / "manifest.json").read_text()),
               "occurrences": json.loads((vdir / "occurrences.json").read_text())}
        t0 = time.time()
        # workspace=None: nothing is regenerated or written into the run directory
        plan, pages = rp.compose_systems(included, header=reflow.get("header"), staff_gap_mm=args.staff_gap_mm,
                                         all_systems=systems, workspace=None, measure_reflow=True, measure_context=ctx)
        dt = time.time() - t0
        odir.mkdir(parents=True)
        export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=odir, logger=lambda _m: None)
        (odir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
        summ = dict(summarize(plan), video=v, compose_seconds=round(dt, 2), run=str(vdir))
        (odir / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))
        print(json.dumps({k: summ[k] for k in ("video", "status", "reason", "pages", "lines", "lines_per_page", "measures_per_line", "measures_per_line_estimated",
                                              "justified_lines", "justification", "adjustment_fraction", "natural_width_px", "target_width_px",
                                              "replicas", "scaffold_ops", "validation", "render_mismatched_px", "compose_seconds")},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
