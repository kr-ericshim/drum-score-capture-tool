"""Measure-level reflow behind its option (reflow_measure + compose_systems): integration and
adversarial rendering fixtures (MEASURE_BRIEF milestone 2)."""

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_lines as rlines
from app.pipeline import reflow_pipeline as rp
from app.pipeline import system_detect as sd

G = 16
TOP = 92
MW = 300
PREFIX = 110
INK = (25, 25, 25)


def measure_strip(measures: int = 4, *, clef: bool = True, time_sig: bool = False, tie_at: Optional[int] = None,
                  dot_near: Optional[int] = None, extra_tail: int = 0, final_bar: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
    """A cleaned strip with ``measures`` measures of four beamed notes; barline k at PREFIX + k * MW."""
    w = PREFIX + measures * MW + 30 + extra_tail
    h = 250
    img = np.full((h, w, 3), 252, np.uint8)
    ls = [TOP + i * G for i in range(5)]
    x_start, x_end = 20, PREFIX + measures * MW + extra_tail
    for y in ls:
        cv2.line(img, (x_start, y), (x_end, y), INK, 1, cv2.LINE_AA)
    if clef:
        for cx in (34, 44):
            cv2.rectangle(img, (cx, ls[1]), (cx + 4, ls[3]), INK, -1)
    if time_sig:
        for y in (ls[2] - 2, ls[4] - 2):
            cv2.putText(img, "4", (62, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, INK, 2, cv2.LINE_AA)
    for k in range(1, measures + 1):
        x = PREFIX + k * MW
        if k < measures or final_bar:
            cv2.rectangle(img, (x, ls[0]), (x + 1, ls[4]), INK, -1)
    for m in range(measures):
        x0 = PREFIX + m * MW
        xs = [x0 + 60, x0 + 120, x0 + 180, x0 + 240]
        for i, x in enumerate(xs):
            y = ls[2] + G // 2 if i % 2 == 0 else ls[1] + G // 2
            cv2.ellipse(img, (x, y), (7, 5), -20, 0, 360, INK, -1, cv2.LINE_AA)
            cv2.line(img, (x + 7, y), (x + 7, ls[0] - 2 * G), INK, 1, cv2.LINE_AA)
        for a, b in ((xs[0], xs[1]), (xs[2], xs[3])):
            cv2.rectangle(img, (a + 7, ls[0] - 2 * G), (b + 7, ls[0] - 2 * G + 3), INK, -1)
    if tie_at is not None:
        cv2.ellipse(img, (PREFIX + tie_at * MW, ls[4] + G), (75, 14), 0, 0, 180, INK, 2, cv2.LINE_AA)
    if dot_near is not None:
        img[ls[4] + 40, PREFIX + dot_near * MW + 27] = INK  # a one-pixel dot right at the corridor seam
    rec = {"system_id": "sys", "staff_y_strip": [float(y) for y in ls], "staff_gap_px": float(G),
           "staff_x_strip": [x_start, x_end], "box_crop": [0, 0, w, h], "size": [w, h], "layout": "bottom_bar",
           "member_obs_ids": [], "issues": [], "envelope_flags": []}
    return img, rec


def observations(img: np.ndarray, sid: str, n: int = 3) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(len(sid))
    out = []
    for i in range(n):
        noisy = np.clip(img.astype(np.float32) + rng.normal(0, 2.0, img.shape), 0, 255).astype(np.uint8)
        det = sd.detect(cv2.GaussianBlur(noisy, (0, 0), 0.5))
        st = max(det["staves"], key=lambda s: s["x"][1] - s["x"][0])
        out.append({"id": f"{sid}-o{i}", "system_regions": [{"region_id": f"{sid}-o{i}-r0", "staff_gap_px": st["gap"],
                                                               "staff_x": st["x"], "bars": st["bars"]}]})
    return out


class Doc:
    """Systems written to a temp dir, with a registration context (manifest + occurrences)."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.systems: List[Dict[str, Any]] = []
        self.obs: List[Dict[str, Any]] = []
        self.occ: List[Dict[str, Any]] = []

    def add(self, sid: str, img: np.ndarray, rec: Dict[str, Any], *, label: Optional[np.ndarray] = None,
            register: bool = True, obs_img: Optional[np.ndarray] = None) -> Dict[str, Any]:
        path = self.tmp / f"strip_{sid}.png"
        cv2.imwrite(str(path), img)
        rec = dict(rec, system_id=sid)
        if register:
            obs = observations(img if obs_img is None else obs_img, sid)
            self.obs.extend(obs)
            rec["member_obs_ids"] = [o["id"] for o in obs]
            self.occ.append({"id": sid, "observations": [{"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]}
                                                         for o in obs]})
        s = {"id": sid, "included": True, "strip_path": str(path), "strip": rec, "layout": "bottom_bar", "issues": []}
        if label is not None:
            lp = self.tmp / f"label_{sid}.png"
            cv2.imwrite(str(lp), label)
            s["label"] = {"path": str(lp), "x_in_strip": 0, "placed": True}
        self.systems.append(s)
        return s

    @property
    def context(self) -> Dict[str, Any]:
        return {"manifest": {"observations": self.obs}, "occurrences": {"systems": self.occ}}

    def compose(self, systems=None, **kw):
        systems = self.systems if systems is None else systems
        return rp.compose_systems(systems, header={"title": "T"}, all_systems=self.systems, measure_context=self.context, **kw)


def label_patch(text: str = "B", boxed: bool = False) -> np.ndarray:
    img = np.full((40, 40, 3), 255, np.uint8)
    cv2.putText(img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
    if boxed:
        cv2.rectangle(img, (2, 2), (37, 37), (0, 0, 0), 2)
    return img


class MeasureReflow(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def assertValidMeasurePlan(self, plan):
        m = plan["measure_reflow"]
        self.assertEqual(m["status"], "measure_lines", m.get("reason"))
        self.assertTrue(m["audit"]["validation"]["valid"], m["audit"]["validation"]["errors"])
        self.assertTrue(m["audit"]["units_placed_once_in_order"])
        self.assertEqual(m["audit"]["render_mismatched_px"], 0)
        self.assertTrue(m["audit"]["native_accounting"]["exact_reconstruction"])
        self.assertEqual(m["audit"]["native_accounting"]["lost_px"], 0)
        self.assertEqual(m["audit"]["native_accounting"]["duplicated_px"], 0)
        content_w = rl.PAGE_W - 2 * rl.MARGIN_X
        for ln in m["lines"]:
            self.assertLessEqual(ln["achieved_width"], content_w)
            # the wider caps (Fill every line) only on a line that needs them; a tier-3 even spread (Every line
            # full) has no line limit, only the per-gap TIER3_MAX_GAP_RATIO (checked through within_caps)
            lim = float("inf") if ln.get("justify_tier") == 3 else \
                rlines.WIDE_MAX_EXPAND_FRACTION if ln.get("justify_tier") == 2 else rlines.MAX_EXPAND_FRACTION
            self.assertLessEqual(ln["adjustment_fraction"], lim + 1e-9)
            self.assertGreaterEqual(ln["adjustment_fraction"], -rlines.MAX_CONTRACT_FRACTION - 1e-9)
            if ln["justified"]:
                self.assertLessEqual(abs(ln["achieved_width"] - ln["target_width"]), 1)
            else:
                self.assertIn(ln["id"], [r["line_id"] for r in m["ragged_exceptions"]])
        self.assertTrue(all(s["within_caps"] for s in m["justification_slots"]))
        for op in m["audit"]["scaffold_operations"]:
            self.assertFalse(op.get("nonstaff_ink_removed"), op)
            self.assertFalse(op.get("nonstaff_ink_in_source_column"), op)
            self.assertEqual(op.get("protected_px", 0), 0, op)
            if op["op"] in ("insert_spread_columns", "remove_spread_columns"):
                self.assertTrue(op["eligible"], op)
        self.assertTrue(plan["validation"]["valid"])

    def test_option_off_leaves_the_composition_unchanged(self):
        for k in range(3):
            self.doc.add(f"sys-00{k + 1}", *measure_strip())
        plan_default, pages_default = self.doc.compose()
        plan_off, pages_off = self.doc.compose(measure_reflow=False)
        self.assertNotIn("measure_reflow", plan_default)
        self.assertEqual(plan_default, plan_off)
        self.assertEqual(len(pages_default), len(pages_off))
        for a, b in zip(pages_default, pages_off):
            self.assertTrue(np.array_equal(a, b))
        # whole systems, one per line, as before
        self.assertEqual([pl["system_id"] for p in plan_default["pages"] for pl in p["placements"]], ["sys-001", "sys-002", "sys-003"])

    def test_option_on_keeps_systems_whole_where_they_fit_and_justifies_to_one_edge(self):
        # every system starts with a time signature: none may continue mid-line
        imgs = [measure_strip(time_sig=True)[0], measure_strip(time_sig=True)[0], measure_strip(tie_at=2, time_sig=True)[0]]
        for k, img in enumerate(imgs):
            self.doc.add(f"sys-00{k + 1}", img, measure_strip()[1])
        plan, pages = self.doc.compose(measure_reflow=True)
        self.assertValidMeasurePlan(plan)
        m = plan["measure_reflow"]
        self.assertEqual(len(m["lines"]), 3)  # every source system keeps its prefix and starts a line
        self.assertEqual([ln["measure_count"] for ln in m["lines"]][:2], [4, 4])
        self.assertIsNone(m["lines"][2]["measure_count"])  # a locked group (tie) has an unknown count
        tied = [b for b in m["boundaries"] if b["system_id"] == "sys-003" and b["class"] == rb.LOCKED]
        self.assertEqual(len(tied), 1)
        edges = {pl["x"] + pl["w"] for p in plan["pages"] for pl in p["placements"]}
        self.assertEqual(len(edges), 1, edges)  # one right edge
        self.assertEqual(m["replicas"] if "replicas" in m else m["audit"]["replicas"], [])
        self.assertTrue(pages and pages[0].shape == (rl.PAGE_H, rl.PAGE_W, 3))

    def test_wide_system_splits_at_safe_cuts_with_a_clef_replica_and_no_time_signature_copy(self):
        img, rec = measure_strip(8, time_sig=True)
        self.doc.add("sys-001", img, rec)
        with self.assertRaises(rl.LayoutConflictError):
            self.doc.compose()  # whole systems: too wide, never shrunk
        plan, _pages = self.doc.compose(measure_reflow=True)
        self.assertValidMeasurePlan(plan)
        m = plan["measure_reflow"]
        counts = [ln["measure_count"] for ln in m["lines"]]
        self.assertEqual(len(counts), 2)
        self.assertEqual(sum(counts), 8)
        self.assertGreaterEqual(counts[0], 4)  # a short line may only be the last one
        self.assertTrue(m["lines"][0]["justified"])
        reps = m["audit"]["replicas"]
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]["line_id"], "line-002")
        self.assertEqual(reps[0]["replica_of_system_id"], "sys-001")
        self.assertEqual(reps[0]["time_signature"], "not replicated")
        # the replica patch ends before the time signature (drawn from x = 62)
        self.assertLess(reps[0]["source_box_native"][2], 62)
        self.assertTrue(m["prefixes"]["sys-001"]["verified_clef_replica"])

    def test_wide_system_without_registration_is_never_split(self):
        img, rec = measure_strip(8)
        self.doc.add("sys-001", img, rec, register=False)
        with self.assertRaises(rl.LayoutConflictError):
            self.doc.compose(measure_reflow=True)  # all boundaries UNKNOWN -> whole system -> conflict

    def test_clef_touching_a_glyph_prohibits_a_new_line(self):
        img, rec = measure_strip(8)
        ls = [TOP + i * G for i in range(5)]
        cv2.rectangle(img, (49, ls[1] + 4), (60, ls[2]), INK, -1)  # ink glued to the clef: patch not verified
        self.doc.add("sys-001", img, rec, obs_img=measure_strip(8)[0])
        with self.assertRaises(rl.LayoutConflictError):
            self.doc.compose(measure_reflow=True)

    def test_section_label_box_above_the_section_start_including_mid_line(self):
        a, rec_a = measure_strip(2)
        b, rec_b = measure_strip(2, clef=False)
        self.doc.add("sys-001", a, rec_a, label=label_patch("A"))
        self.doc.add("sys-002", b, rec_b, label=label_patch("B", boxed=True))
        plan, _pages = self.doc.compose(measure_reflow=True)
        self.assertValidMeasurePlan(plan)
        m = plan["measure_reflow"]
        self.assertEqual(len(m["lines"]), 1)  # the prefix-free system joins the line
        labels = {lab["system_id"]: lab for lab in m["labels"]}
        self.assertFalse(labels["sys-001"]["mid_line"])
        self.assertTrue(labels["sys-002"]["mid_line"])
        self.assertEqual(labels["sys-001"]["outline"], "drawn")
        self.assertEqual(labels["sys-002"]["outline"], "source_box")
        place = {p["unit_id"]: p for p in m["audit"]["placements"]}
        first_b = next(p for p in m["audit"]["placements"] if p["system_id"] == "sys-002")
        self.assertGreaterEqual(labels["sys-002"]["box_out"][0], first_b["x_out"])
        line = m["lines"][0]
        for lab in labels.values():
            self.assertLessEqual(lab["box_out"][3], line["label_band_px"])  # above the content, never over it
        self.assertTrue(place)

    def test_labels_follow_the_order_after_an_exclusion(self):
        for k in range(3):
            img, rec = measure_strip()
            self.doc.add(f"sys-00{k + 1}", img, rec, label=label_patch("A") if k == 0 else None)
        self.doc.systems[1]["label"] = dict(self.doc.systems[0]["label"], repeats_system_id="sys-001")
        placed = [self.doc.systems[1], self.doc.systems[2]]  # the section start is excluded in review
        plan, _ = self.doc.compose(placed, measure_reflow=True)
        self.assertValidMeasurePlan(plan)
        labels = plan["measure_reflow"]["labels"]
        self.assertEqual([lab["system_id"] for lab in labels], ["sys-002"])
        self.assertEqual(plan["dependencies"]["labels_moved"][0]["placed_on"], "sys-002")

    def test_restored_preview_tail_uses_the_uncut_strip(self):
        full, rec = measure_strip(4, extra_tail=120, final_bar=False)
        cut_x = PREFIX + 4 * MW + 2
        strip = full[:, :cut_x].copy()
        unc_path = Path(self._t.name) / "uncut_sys-001.png"
        cv2.imwrite(str(unc_path), full)
        rec_cut = dict(rec, box_crop=[0, 0, cut_x, full.shape[0]], size=[cut_x, full.shape[0]],
                       preview_tail={"cut": True, "cut_x": cut_x, "verified": True, "destination_system_id": "sys-002"},
                       uncut={"path": str(unc_path), "box_crop": [0, 0, full.shape[1], full.shape[0]],
                              "size": [full.shape[1], full.shape[0]]}, uncut_pixels_sha256=None)
        self.doc.add("sys-001", strip, rec_cut, obs_img=full)
        self.doc.add("sys-002", *measure_strip())
        self.doc.add("sys-003", *measure_strip())
        plan, _ = self.doc.compose([self.doc.systems[0], self.doc.systems[2]], measure_reflow=True)
        self.assertValidMeasurePlan(plan)
        self.assertEqual(plan["measure_reflow"]["variants"]["sys-001"], "uncut")
        self.assertEqual(plan["dependencies"]["preview_tails_restored"][0]["system_id"], "sys-001")
        in_order, _ = self.doc.compose(measure_reflow=True)
        self.assertEqual(in_order["measure_reflow"]["variants"]["sys-001"], "strip")


class AdversarialRendering(unittest.TestCase):
    """Rendering fixtures that try to make justification touch ink."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def _plan(self, imgs):
        # the fixtures here start every system with a time signature, so whole systems stay lines
        # (no join): these tests are about whitespace-only justification
        for k, (img, rec) in enumerate(imgs):
            self.doc.add(f"sys-{k + 1:03d}", img, rec, obs_img=measure_strip(4, time_sig=True)[0])
        plan, pages = self.doc.compose(measure_reflow=True)
        MeasureReflow.assertValidMeasurePlan(self, plan)
        return plan, pages

    def test_one_pixel_dot_at_a_seam_blocks_that_cut(self):
        plan, _ = self._plan([measure_strip(4, time_sig=True), measure_strip(4, dot_near=2, time_sig=True)])
        m = plan["measure_reflow"]
        b2 = [b for b in m["boundaries"] if b["system_id"] == "sys-002"]
        self.assertEqual(sum(1 for b in b2 if b["class"] == rb.SAFE), 2)
        self.assertNotIn(rb.SAFE, [b["class"] for b in b2 if abs(b["seam_x"] - (PREFIX + 2 * MW + 27)) <= 4])
        # no slot exists at the blocked seam, so nothing was inserted or removed next to the dot
        slots = [s for s in m["justification_slots"] if "sys-002" in s["id"] and s["kind"] == "barline_corridor"]
        self.assertEqual(len(slots), 2)

    def test_justification_moves_glyphs_rigidly(self):
        a = measure_strip(4, time_sig=True)
        b_img, b_rec = measure_strip(4, time_sig=True)
        b_img = np.ascontiguousarray(b_img[:, :-20])  # a narrower system: its line must expand to the edge
        b_rec = dict(b_rec, size=[b_img.shape[1], b_img.shape[0]], box_crop=[0, 0, b_img.shape[1], b_img.shape[0]])
        plan, pages = self._plan([a, a, (b_img, b_rec), a])
        m = plan["measure_reflow"]
        self.assertEqual(m["audit"]["render_mismatched_px"], 0)
        ops = [op for op in m["audit"]["scaffold_operations"] if op["op"] == "insert_scaffold_columns"]
        for op in ops:
            self.assertFalse(op["nonstaff_ink_in_source_column"])
            self.assertLessEqual(op["dark_px_per_column"], 5 * 4)  # staff-line pixels only
        self.assertEqual(len({ln["achieved_width"] for ln in m["lines"] if ln["justified"]}), 1)

    def test_kept_preview_tail_hangs_out_and_the_final_barlines_align(self):
        # a scrolling sheet: the staff runs on through the staff break into the next system's start,
        # which was kept (unverified, uncut); like a "Fine" box it hangs out of the justified width
        tail_w = 220
        t_img, t_rec = measure_strip(4, extra_tail=tail_w, time_sig=True)
        ls = [TOP + i * G for i in range(5)]
        bar = PREFIX + 4 * MW
        for cx in (bar + 30, bar + 40):  # the next system's clef and a note in the tail
            cv2.rectangle(t_img, (cx, ls[1]), (cx + 4, ls[3]), INK, -1)
        cv2.ellipse(t_img, (bar + 120, ls[2] + G // 2), (7, 5), -20, 0, 360, INK, -1, cv2.LINE_AA)
        t_rec = dict(t_rec, preview_tail={"cut": False, "verified": False, "kind": "next_system_start",
                                          "break_x": bar + 6, "cut_x": bar + 8})
        plan, _pages = self._plan([measure_strip(4, time_sig=True), (t_img, t_rec), measure_strip(4, time_sig=True)])
        m = plan["measure_reflow"]
        lines = m["lines"]
        self.assertEqual(len(lines), 3)
        self.assertEqual(m["ragged_exceptions"], [], m["ragged_exceptions"])
        self.assertTrue(all(ln["justified"] for ln in lines))
        # the final barlines share one edge; only the tail's ink lies past it
        self.assertEqual(len({ln["achieved_width"] for ln in lines}), 1, [ln["achieved_width"] for ln in lines])
        # (the tail is not stretched: it keeps the strip's output scale, target staff gap / source staff gap)
        self.assertGreater(lines[1]["overhang_px"], 0.8 * tail_w * (1.5 * rl.MM) / float(G))
        self.assertEqual(lines[0]["overhang_px"], 0)
        placed = {pl["line_id"]: pl for p in plan["pages"] for pl in p["placements"]}
        x_edge = {placed[ln["id"]]["x"] + ln["achieved_width"] for ln in lines}
        self.assertEqual(len(x_edge), 1, x_edge)
        content_w = rl.PAGE_W - 2 * rl.MARGIN_X
        self.assertLessEqual(placed["line-002"]["x"] - rl.MARGIN_X + placed["line-002"]["w"], content_w)

    def test_contraction_removes_only_clean_scaffold_columns(self):
        a = measure_strip(4, time_sig=True)
        wide_img, wide_rec = measure_strip(4, time_sig=True)
        col = PREFIX + 2 * MW + 20  # a clean corridor column right of barline 2
        wide_img = np.ascontiguousarray(np.concatenate([wide_img[:, :col], np.repeat(wide_img[:, col:col + 1], 12, axis=1),
                                                        wide_img[:, col:]], axis=1))
        sx = wide_rec["staff_x_strip"]
        wide_rec = dict(wide_rec, size=[wide_img.shape[1], wide_img.shape[0]], box_crop=[0, 0, wide_img.shape[1], wide_img.shape[0]],
                        staff_x_strip=[sx[0], sx[1] + 12])
        # without the tier-3 spread (Every line full) these short unjoinable systems keep a common edge at
        # their natural width, so the one wider system must contract: that path is what is tested here
        from unittest import mock
        with mock.patch.object(rlines, "_free", lambda g: 0.0):
            plan, _ = self._plan([a, (wide_img, wide_rec), a, a, a])
        m = plan["measure_reflow"]
        self.assertEqual(len({ln["achieved_width"] for ln in m["lines"]}), 1, [ln["achieved_width"] for ln in m["lines"]])
        removed = [op for op in m["audit"]["scaffold_operations"] if op["op"] == "remove_scaffold_columns"]
        self.assertTrue(removed)
        for op in removed:
            self.assertFalse(op["nonstaff_ink_removed"], op)
        line2 = m["lines"][1]
        self.assertLess(line2["adjustment_px"], 0)
        self.assertGreaterEqual(line2["adjustment_fraction"], -rlines.MAX_CONTRACT_FRACTION)



class ReviewExportOption(unittest.TestCase):
    """The review export composes with the job's own option (on by default for new jobs)."""

    def _job(self, root: Path, options):
        from app import main
        from app.job_store import Job, JobStatus, JobStore
        from app.pipeline.export import export_composed_pages
        art = root / "job-m"
        strips = art / "reflow" / "strips"
        strips.mkdir(parents=True)
        systems = []
        for i in range(3):
            img, rec = measure_strip()
            path = strips / f"strip_sys-00{i + 1}.png"
            cv2.imwrite(str(path), img)
            systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(path), "issues": [],
                            "t_start": float(i), "t_end": i + 0.9, "layout": "bottom_bar", "strip": dict(rec, system_id=f"sys-00{i + 1}")})
        plan, pages = rp.compose_systems(systems, header={"title": "T"}, measure_reflow=bool(options.get("measure_reflow")))
        out = export_composed_pages(pages=pages, formats=["png"], workspace=art / "export", logger=lambda _m: None)
        reflow = {"systems": systems, "page_plan": plan, "header": {"title": "T"}, "revision": 1, "duplicate_suggestions": [],
                  "workspace": str(art / "reflow")}
        result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "reflow": reflow, "images": out["images"], "pdf": None,
                  **main._reflow_capture_fields(reflow)}
        store = JobStore(root)
        store.create(Job(id="job-m", source_type="file", file_path=str(root / "v.mp4"), youtube_url=None,
                         options=dict(options, export={"formats": ["png"]}), artifact_dir=str(art), status=JobStatus.DONE, result=result))
        return store, systems

    def test_review_export_follows_the_job_option(self):
        from unittest.mock import patch
        from app import main
        from app.schemas import JobOptions, JobReviewExportRequest
        self.assertTrue(JobOptions.model_fields["measure_reflow"].default)
        for on in (False, True):
            with tempfile.TemporaryDirectory() as td:
                store, systems = self._job(Path(td), {"measure_reflow": on})
                paths = [s["strip_path"] for s in systems]
                with patch.object(main, "job_store", store):
                    main.review_export("job-m", JobReviewExportRequest(keep_captures=[paths[2], paths[0]], formats=["png"]))
                plan = store.get("job-m").result["reflow"]["page_plan"]
                if on:
                    self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
                    placed = [sid for p in plan["pages"] for pl in p["placements"] for sid in pl["system_ids"]]
                    self.assertEqual(placed, ["sys-003", "sys-001"])
                else:
                    self.assertNotIn("measure_reflow", plan)
                    self.assertEqual([pl["system_id"] for p in plan["pages"] for pl in p["placements"]], ["sys-003", "sys-001"])


if __name__ == "__main__":
    unittest.main()
