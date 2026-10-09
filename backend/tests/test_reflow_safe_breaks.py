"""STRATEGY Step 2A: only SAFE boundaries are cuts or line breaks (OVERSIZE_SPAN reverted), the
whole-system fallback at the largest fitting staff size (>= 1.2 mm, disclosed), and the export check
that keeps an empty or unreadable export from being published as done."""

import copy
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from unittest.mock import patch

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_measure as rmeas
from app.pipeline import reflow_units as ru
from app.pipeline.export import ExportVerificationError, export_composed_pages, pdf_page_count, verify_composed_export
from test_reflow_measure import Doc, measure_strip
from test_reflow_units import build, system
from test_reflow_boundaries import make_strip


class OnlySafeCuts(unittest.TestCase):
    def test_a_locked_barline_is_never_a_cut_even_with_an_old_forced_cut_record(self):
        # the reverted OVERSIZE_SPAN rule marked a crossing-only barline as a forced cut; such a record
        # no longer makes it a cut, and a document that cuts there is invalid
        b = {"id": "b1", "kind": "barline", "seam_x": 900, "class": rb.LOCKED, "reason_codes": ["TIE_SLUR_OR_LINE_CROSSES"],
             "forced_cut": {"reason": "OVERSIZE_SPAN", "limit_px": 800.0, "class": rb.LOCKED}}
        self.assertFalse(ru._is_cut(b))
        self.assertFalse(hasattr(ru, "oversize_splits"))
        img, rec = make_strip(tie_at=2)
        doc, _ = build([system("sys-001", img, rec)])
        self.assertEqual(ru.validate_document(doc), [])
        locked = next(x for x in doc["boundaries"] if x["class"] == rb.LOCKED)
        self.assertFalse(locked["is_cut"])
        bad = copy.deepcopy(doc)
        lb = next(x for x in bad["boundaries"] if x["id"] == locked["id"])
        lb["is_cut"] = True
        lb["forced_cut"] = {"reason": "OVERSIZE_SPAN"}
        lb["reason_codes"] = ["TIE_SLUR_OR_LINE_CROSSES"]
        self.assertTrue(any("non-SAFE" in e for e in ru.validate_document(bad)))

    def test_a_jump_span_wider_than_the_line_is_not_cut_at_a_crossed_barline(self):
        # 8 measures, ties over barlines 1..6: the span before the first SAFE barline (7, x = 2210) is
        # wider than the page line at 1.5 mm (split limit 2126 * 16 / 17.72 = 1919 native px). The old
        # jump-only rule cut it at a tied barline; now it stays one unit (an oversize unit).
        with tempfile.TemporaryDirectory() as td:
            doc = Doc(Path(td))
            img, rec = measure_strip(8)
            ls_bottom = 92 + 4 * 16
            for k in range(1, 7):
                cv2.ellipse(img, (110 + k * 300, ls_bottom + 16), (75, 14), 0, 0, 180, (25, 25, 25), 2, cv2.LINE_AA)
            s = doc.add("sys-001", img, dict(rec, layout="jump_view"))
            s["layout"] = "jump_view"
            content_w = rl.PAGE_W - 2 * rl.MARGIN_X
            built = rmeas.build_atoms([{"system": s, "strip_path": Path(s["strip_path"]), "variant": "strip", "label": None}],
                                      target_gap_px=1.5 * rl.MM, context=doc.context, line_width=content_w)
            d = built["doc"]
            self.assertEqual(d["audit"]["validation"]["status"], "valid", d["audit"]["validation"]["errors"])
            for b in d["boundaries"]:
                if b["is_cut"]:
                    self.assertEqual(b["class"], rb.SAFE, b)
                self.assertNotIn("forced_cut", b)
            locked = [b for b in d["boundaries"] if b["class"] == rb.LOCKED]
            self.assertGreaterEqual(len(locked), 6)
            self.assertTrue(all(not b["is_cut"] for b in locked))
            for u in d["measure_units"]:
                self.assertNotIn("OVERSIZE_SPLIT_BEFORE", u["flags"])
            # the wide span gets a line of its own at a smaller scale; nothing is cut or dropped
            self.assertTrue(any(a.get("oversize") for a in built["atoms"]))

    def test_no_eligible_plan_breaks_a_line_at_a_locked_or_unknown_boundary(self):
        cases = [
            [measure_strip(8, tie_at=t) for t in (2, 5)],
            [measure_strip(6, tie_at=1), measure_strip(6, tie_at=4)],
            [measure_strip(9, tie_at=3)],
        ]
        checked = 0
        for strips in cases:
            with self.subTest(n=len(strips)), tempfile.TemporaryDirectory() as td:
                doc = Doc(Path(td))
                for k, (img, rec) in enumerate(strips):
                    doc.add(f"sys-00{k + 1}", img, rec)
                plan, _pages = doc.compose(measure_reflow=True, auto_staff_size=True)
                m = plan["measure_reflow"]
                self.assertEqual(m["status"], "measure_lines", m.get("reason"))
                bmap = {b["id"]: b for b in m["boundaries"]}
                for b in m["boundaries"]:
                    if b.get("is_cut"):
                        self.assertEqual(b["class"], rb.SAFE, b)
                # every line that starts inside a system starts at a SAFE cut
                units = {u["id"]: u for u in m["units"]}
                for ln in m["lines"]:
                    if ln.get("starts_inside_system"):
                        checked += 1
                        bid = units[ln["atom_ids"][0]]["left_boundary_id"]
                        self.assertIn(bid, bmap, ln["id"])
                        self.assertEqual(bmap[bid]["class"], rb.SAFE, (ln["id"], bmap[bid]))
                        self.assertTrue(bmap[bid]["is_cut"])
        self.assertGreater(checked, 0)


class WholeSystemFallback(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def test_systems_too_wide_at_the_chosen_size_use_the_largest_fitting_size(self):
        # 7 measures: 2240 px at a 16 px gap fit the line up to about 1.28 mm -> 1.25 mm on the grid
        self.doc.add("sys-001", *measure_strip(7))
        self.doc.add("sys-002", *measure_strip(4))
        plan, pages = self.doc.compose(measure_reflow=False, auto_staff_size=True)
        size = plan["staff_size"]
        self.assertTrue(size["auto_reduced"])
        self.assertEqual(size["reason"], "WHOLE_SYSTEMS_DO_NOT_FIT")
        self.assertAlmostEqual(size["staff_gap_mm"], 1.25)
        self.assertEqual(size["staff_gap_mm_requested"], 1.5)
        self.assertEqual(size["systems_not_fitting_at_requested"], ["sys-001"])
        self.assertAlmostEqual(plan["staff_gap_mm"], 1.25, places=3)
        self.assertEqual(plan["staff_gap_mm_requested"], 1.5)
        self.assertTrue(plan["validation"]["valid"])
        self.assertFalse(plan["conflicts"])
        self.assertTrue(pages)

    def test_a_size_the_user_chose_is_never_changed(self):
        self.doc.add("sys-001", *measure_strip(7))
        with self.assertRaises(rl.LayoutConflictError) as ctx:
            self.doc.compose(measure_reflow=False, auto_staff_size=False)
        self.assertEqual(ctx.exception.plan["staff_size"]["reason"], "AUTO_OFF")
        self.assertFalse(ctx.exception.plan["staff_size"]["auto_reduced"])

    def test_below_the_automatic_floor_is_a_visible_conflict_with_the_measure_reason_kept(self):
        # 9 measures without registration: no SAFE cut, so no line plan at any size down to 1.2 mm, and
        # the whole system fits only below 1.2 mm
        self.doc.add("sys-001", *measure_strip(9), register=False)
        with self.assertRaises(rl.LayoutConflictError) as ctx:
            self.doc.compose(measure_reflow=True, auto_staff_size=True)
        plan = ctx.exception.plan
        self.assertEqual(plan["staff_size"]["reason"], "BELOW_AUTO_MINIMUM")
        self.assertLess(plan["staff_size"]["largest_fitting_staff_gap_mm"], rmeas.AUTO_MIN_STAFF_GAP_MM)
        self.assertEqual(plan["measure_reflow"]["status"], "fallback_whole_systems")
        self.assertTrue(plan["measure_reflow"]["reason"])

    def test_measure_fallback_reason_is_kept_with_the_reduced_whole_system_plan(self):
        self.doc.add("sys-001", *measure_strip(7))
        with patch.object(rmeas, "compose", side_effect=rmeas.MeasurePlanUnavailable("NO_STAFF_GAP", {"system_id": "sys-001"})):
            plan, _pages = self.doc.compose(measure_reflow=True, auto_staff_size=True)
        self.assertEqual(plan["measure_reflow"], {"status": "fallback_whole_systems", "reason": "NO_STAFF_GAP",
                                                  "detail": {"system_id": "sys-001"}})
        self.assertEqual(plan["staff_size"]["reason"], "WHOLE_SYSTEMS_DO_NOT_FIT")
        self.assertAlmostEqual(plan["staff_gap_mm"], 1.25, places=3)

    def test_measure_lines_use_the_largest_size_at_which_an_unsplittable_unit_fits(self):
        # no registration: the 7-measure system has no SAFE cut and is wider than the line at 1.5 mm
        self.doc.add("sys-001", *measure_strip(7), register=False)
        plan, _pages = self.doc.compose(measure_reflow=True, auto_staff_size=True)
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        size = plan["staff_size"]
        self.assertEqual(size["reason"], "UNITS_DO_NOT_FIT")
        self.assertTrue(size["auto_reduced"])
        self.assertEqual(size["staff_gap_mm_requested"], 1.5)
        self.assertEqual(size["unfit_at_requested"]["reason"], "NO_FEASIBLE_LINE_BREAKS")
        # the largest size on the grid with a plan: the last size tried, every larger one had none
        tried = size["unfit_at_requested"]["sizes_tried"]
        self.assertEqual(tried[0], 1.5)
        self.assertAlmostEqual(size["staff_gap_mm"], tried[-1])
        self.assertTrue(1.2 <= size["staff_gap_mm"] < 1.5)
        self.assertTrue(all(abs(a - b - 0.05) < 1e-9 for a, b in zip(tried, tried[1:])))
        # off (a size the user chose): no plan, whole systems, and the conflict is shown
        with self.assertRaises(rl.LayoutConflictError) as ctx:
            self.doc.compose(measure_reflow=True, auto_staff_size=False)
        self.assertEqual(ctx.exception.plan["measure_reflow"]["reason"], "NO_FEASIBLE_LINE_BREAKS")

    def test_systems_that_fit_keep_the_chosen_size(self):
        self.doc.add("sys-001", *measure_strip(4))
        plan, _ = self.doc.compose(measure_reflow=False, auto_staff_size=True)
        self.assertFalse(plan["staff_size"]["auto_reduced"])
        self.assertEqual(plan["staff_size"]["reason"], "FITS")
        self.assertAlmostEqual(plan["staff_gap_mm"], 1.5, places=3)


class ExportVerification(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def plan(self, n):
        return {"pages": [{"index": i + 1, "placements": [{"system_id": f"s{i}"}]} for i in range(n)],
                "conflicts": [], "validation": {"valid": True, "errors": []}}

    def pages(self, n):
        return [np.full((140, 100, 3), 255, np.uint8) for _ in range(n)]

    def test_a_complete_export_passes(self):
        res = export_composed_pages(pages=self.pages(2), formats=["png", "pdf"], workspace=self.root / "a", logger=lambda m: None)
        facts = verify_composed_export(res, plan=self.plan(2), pages=self.pages(2))
        self.assertEqual(facts["pdf_pages"], 2)
        self.assertEqual(facts["png_pages"], 2)
        self.assertTrue(facts["verified"])

    def test_no_pages_is_never_done(self):
        with self.assertRaises(ExportVerificationError) as ctx:
            verify_composed_export({"formats": ["pdf"], "pdf": None, "images": []}, plan=self.plan(0), pages=[])
        self.assertEqual(ctx.exception.code, "EMPTY_EXPORT")
        self.assertTrue(str(ctx.exception).startswith("EMPTY_EXPORT:"))

    def test_invalid_plan_is_refused(self):
        plan = dict(self.plan(1), conflicts=[{"system_id": "s0"}], validation={"valid": False, "errors": ["x"]})
        with self.assertRaises(ExportVerificationError) as ctx:
            verify_composed_export({"formats": ["png"], "images": []}, plan=plan, pages=self.pages(1))
        self.assertEqual(ctx.exception.code, "INVALID_PLACEMENT_PLAN")

    def test_pdf_page_count_must_match_the_plan(self):
        res = export_composed_pages(pages=self.pages(2), formats=["pdf"], workspace=self.root / "b", logger=lambda m: None)
        with self.assertRaises(ExportVerificationError) as ctx:
            verify_composed_export(res, plan=self.plan(3), pages=self.pages(3))
        self.assertEqual(ctx.exception.code, "PAGE_COUNT_MISMATCH")

    def test_truncated_pdf_is_unreadable(self):
        res = export_composed_pages(pages=self.pages(2), formats=["pdf"], workspace=self.root / "c", logger=lambda m: None)
        pdf = Path(res["pdf"])
        data = pdf.read_bytes()
        pdf.write_bytes(data[: len(data) // 2])
        self.assertIsNone(pdf_page_count(pdf))
        with self.assertRaises(ExportVerificationError) as ctx:
            verify_composed_export(res, plan=self.plan(2), pages=self.pages(2))
        self.assertEqual(ctx.exception.code, "PDF_UNREADABLE")

    def test_pdf_page_count_reads_pillow_pdfs(self):
        p = self.root / "x.pdf"
        ims = [Image.new("RGB", (60, 80), "white") for _ in range(4)]
        ims[0].save(p, "PDF", save_all=True, append_images=ims[1:], resolution=300.0)
        self.assertEqual(pdf_page_count(p), 4)
        self.assertIsNone(pdf_page_count(self.root / "missing.pdf"))


if __name__ == "__main__":
    unittest.main()
