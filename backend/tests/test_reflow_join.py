"""Joining source systems mid-line (DECISIONS "Joining systems"): clean removal of the repeated drum
clef, refusals, and the fill-preferring line planner."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_lines as rlines
from app.pipeline import reflow_units as ru
import test_reflow_measure as trm
from test_reflow_measure import G, INK, TOP, Doc, measure_strip


def analyse(img, rec):
    return rb.analyse_strip(img, rec, system_id="sys")


class CleanClefRemoval(unittest.TestCase):
    def test_removal_leaves_only_paper_and_staff_lines(self):
        img, rec = measure_strip(3)
        an = analyse(img, rec)
        res = ru.declef_patch(an)
        self.assertTrue(res["verified"], res.get("reason"))
        new = res["_image"]
        changed = np.any(new != img, axis=-1)
        clef = res["_clef"]
        # every changed pixel is in the removal mask; every changed non-staff pixel belongs to the clef
        self.assertFalse((changed & ~res["_mask"]).any())
        self.assertFalse((changed & an.nonstaff & ~clef).any())
        self.assertTrue(clef[changed].any())
        led = res["ledger"]
        self.assertEqual(led["changed_outside_mask_px"], 0)
        self.assertEqual(led["removed_nonstaff_not_clef_px"], 0)
        self.assertEqual(led["residue_px"], 0)
        # in the clef's columns only the five staff lines remain: each column equals a clean staff column
        x0, x1 = 30, 52
        ls = [TOP + i * G for i in range(5)]
        gray = cv2.cvtColor(new, cv2.COLOR_BGR2GRAY)
        ref = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[:, 100]  # a staff-only column before the first note
        for x in range(x0, x1):
            ink_rows = set(np.nonzero(gray[:, x] < 200)[0].tolist())
            self.assertTrue(ink_rows <= {y + d for y in ls for d in (-1, 0, 1)}, (x, sorted(ink_rows)))
            self.assertLessEqual(int(np.abs(gray[:, x].astype(int) - ref.astype(int)).max()), 40, x)
        # nothing outside the clef changed (notes, barlines, beams)
        self.assertTrue(np.array_equal(new[:, x1 + 3:], img[:, x1 + 3:]))

    def test_clef_touching_a_note_or_near_ink_is_refused(self):
        img, rec = measure_strip(3)
        ls = [TOP + i * G for i in range(5)]
        cv2.rectangle(img, (49, ls[1] + 4), (60, ls[2]), INK, -1)  # ink glued to the clef
        self.assertFalse(ru.declef_patch(analyse(img, rec))["verified"])
        img, rec = measure_strip(3)
        cv2.line(img, (41, ls[0] - 8), (41, ls[1] + 2), INK, 1)  # a mark above the staff that reaches down to the clef
        res = ru.declef_patch(analyse(img, rec))
        self.assertFalse(res["verified"])
        self.assertIn(res["reason"], ("CLEF_PATCH_CONTAMINATED", "CLEF_NEAR_INK", "CLEF_TOUCHES_OUTSIDE_INK"))
        img, rec = measure_strip(3)
        cv2.circle(img, (41, ls[1] - 4), 2, INK, -1)  # a dot inside the staff right above the clef
        res = ru.declef_patch(analyse(img, rec))
        self.assertFalse(res["verified"])
        self.assertIn(res["reason"], ("CLEF_PATCH_CONTAMINATED", "CLEF_NEAR_INK", "CLEF_TOUCHES_OUTSIDE_INK"))

    def test_text_above_or_below_the_staff_does_not_block_the_clef_removal(self):
        # user feedback 2026-10-07: a section box ([C]) or text ("h.h open") above the top staff line and a lyric
        # below the bottom one stay in place (they move with their measure); only the clef's pixels are removed
        ls = [TOP + i * G for i in range(5)]
        img, rec = measure_strip(3)
        cv2.rectangle(img, (26, ls[0] - 24), (56, ls[0] - 5), INK, 2)  # a section box whose edge dips into the band
        cv2.putText(img, "Ab", (28, ls[4] + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1, cv2.LINE_AA)  # a lyric below
        an = analyse(img, rec)
        self.assertTrue(ru.clef_patch(an)["verified"], ru.clef_patch(an).get("reason"))
        res = ru.declef_patch(an)
        self.assertTrue(res["verified"], res.get("reason"))
        self.assertEqual(len(res["ledger"]["kept_outside_staff_boxes"]), 2)
        changed = np.any(res["_image"] != img, axis=-1)
        self.assertFalse((changed & ~res["_mask"]).any())
        self.assertFalse((changed & an.nonstaff & ~res["_clef"]).any())
        self.assertEqual(res["ledger"]["removed_nonstaff_not_clef_px"], 0)
        # the box and the lyric are untouched
        self.assertTrue(np.array_equal(res["_image"][:ls[0] - 1], img[:ls[0] - 1]))
        self.assertTrue(np.array_equal(res["_image"][ls[4] + 2:], img[ls[4] + 2:]))
        # the clef replica (a copy for a new line start) leaves the box and lyric out
        cp = ru.clef_patch(an)
        patch = cp["_image"]
        self.assertFalse((cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)[:ls[0] - 2] < 200).any())
        # ink that touches the clef still blocks it
        cv2.line(img, (36, ls[0] - 3), (36, ls[1] + 1), INK, 1)
        self.assertFalse(ru.declef_patch(analyse(img, rec))["verified"])

    def test_start_with_time_signature_is_refused(self):
        img, rec = measure_strip(3, time_sig=True)
        res = ru.declef_patch(analyse(img, rec))
        self.assertFalse(res["verified"])
        self.assertIn(res["reason"], ("TIME_SIGNATURE", "PREFIX_INK_AFTER_CLEF"))
        # ... while the clef alone is still a verified replica for a new line start
        self.assertTrue(ru.clef_patch(analyse(img, rec))["verified"])

    def test_staff_glyph_right_after_the_clef_is_prefix_ink_but_measure_content_is_not(self):
        ls = [TOP + i * G for i in range(5)]
        near, rec = measure_strip(3)
        cv2.rectangle(near, (66, ls[1] + 3), (72, ls[3] - 3), INK, -1)  # a start-repeat-like stroke 1.1 gap after the clef
        res = ru.declef_patch(analyse(near, rec))
        self.assertFalse(res["verified"])
        self.assertEqual(res["reason"], "PREFIX_INK_AFTER_CLEF")
        far, rec = measure_strip(3)
        cv2.rectangle(far, (100, ls[1] + 3), (108, ls[3] - 3), INK, -1)  # a simile-like glyph inside the first measure
        self.assertTrue(ru.declef_patch(analyse(far, rec))["verified"])


def system(prefix, widths, sid, *, join=False, trim=0, safe=True, counts=None):
    """Planner atoms of one source system: a first atom (its prefix included) and SAFE-cut atoms."""
    out = []
    for k, w in enumerate(widths):
        a = {"id": f"{sid}/u{k}", "system_id": sid, "width": w + (prefix if k == 0 else 0), "kind": "measure",
             "measure_count": 1 if counts is None else counts[k]}
        if k == 0:
            slot = {"id": f"{sid}/join-slot", "natural": 20.0, "max_expand": 10.0, "max_contract": 5.0}
            a.update(break_before="system_start", join_legal=join, join_trim=trim if join else 0,
                     join={"mode": "declef", "trim": trim, "slot": slot} if join else None, slot_before=None, boundary_id=None)
        else:
            a.update(break_before="safe_cut", join_legal=False, replica_width=60 if safe else None, boundary_id=f"{sid}/b{k}",
                     slot_before={"id": f"{sid}/s{k}", "natural": 30.0, "max_expand": 15.0, "max_contract": 7.0})
        out.append(a)
    return out


class JoinPlanner(unittest.TestCase):
    def test_planner_prefers_filled_lines_over_one_short_system_per_line(self):
        atoms = []
        for k in range(4):
            atoms += system(120, [440, 440, 440], f"s{k}", join=k > 0, trim=60)
        plan = rlines.plan_document(atoms, 2126)
        self.assertTrue(plan["valid"])
        self.assertLess(len(plan["lines"]), 4)  # 3-measure systems (65% of the line) are joined/split
        self.assertTrue(any(ln["joined_system_ids"] for ln in plan["lines"]))
        for ln in plan["lines"][:-1]:
            self.assertGreaterEqual(ln["page_fill"], 0.75, ln)
        # without a legal join, every system stays its own line
        alone = []
        for k in range(4):
            alone += system(120, [440, 440, 440], f"s{k}")
        self.assertEqual(len(rlines.plan_document(alone, 2126)["lines"]), 4)

    def test_join_trim_and_slot_enter_the_line_width(self):
        atoms = system(120, [440, 440], "a") + system(120, [440], "b", join=True, trim=60)
        plan = rlines.plan_lines(atoms, 2126)
        ln = plan["lines"][0]
        self.assertEqual(ln["joined_system_ids"], ["b"])
        self.assertEqual(ln["natural_width"], 560 + 440 + 560 - 60)
        self.assertIn("b/join-slot", ln["slot_ids"])

    def test_no_line_starts_at_an_unknown_or_locked_boundary(self):
        # the second system has no SAFE cut with a verified clef (only whole) - it may join whole or start a line
        atoms = system(120, [440, 440, 440], "a") + system(120, [1320], "b", join=True, trim=60) \
            + system(120, [440, 440, 440], "c", join=True, trim=60)
        atoms[-2]["replica_width"] = None  # c's first SAFE cut has no verified replica: not a line start
        plan = rlines.plan_document(atoms, 2126)
        self.assertTrue(plan["valid"])
        starts = [ln["atom_ids"][0] for ln in plan["lines"]]
        self.assertNotIn("c/u1", starts)
        # c/u1 cannot start a line, so c/u0 and c/u1 always share one
        self.assertEqual(len([ln for ln in plan["lines"] if {"c/u0", "c/u1"} & set(ln["atom_ids"])]), 1)


class JoinIntegration(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def test_three_measure_systems_join_and_the_clef_removal_is_recorded(self):
        for k in range(3):
            self.doc.add(f"sys-00{k + 1}", *measure_strip(3))
        plan, pages = self.doc.compose(measure_reflow=True)
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        m = plan["measure_reflow"]
        self.assertLess(len(m["lines"]), 3)
        joined = [p for p in m["audit"]["placements"] if p.get("joined")]
        self.assertTrue(joined)
        self.assertEqual(m["joins"]["clefs_removed"], len(joined))
        for cr in m["audit"]["clef_removals"]:
            self.assertTrue(cr["verified"])
            self.assertEqual(cr["changed_outside_mask_px"], 0)
            self.assertEqual(cr["removed_nonstaff_not_clef_px"], 0)
            self.assertEqual(cr["resampled_changed_outside_clef_px"], 0)
        ops = [op for op in m["audit"]["scaffold_operations"] if op["op"] == "remove_scaffold_columns" and op["side"] == "join_lead"]
        self.assertTrue(ops)
        self.assertFalse(any(op["nonstaff_ink_removed"] for op in ops))
        # the joined system's region on the page: only staff lines between the previous barline and the first note
        page = pages[0]
        pl = {p["line_id"]: p for pg in plan["pages"] for p in pg["placements"]}
        j = joined[0]
        line = pl[j["line_id"]]
        X = line["x"] + j["x_out"]
        top = line["y"] + next(ln for ln in m["lines"] if ln["id"] == j["line_id"])["staff_top_px"]
        gap = 1.5 * 300 / 25.4
        region = cv2.cvtColor(page[int(top - 2 * gap):int(top + 6 * gap), X + 4:X + int(1.0 * gap)], cv2.COLOR_BGR2GRAY)
        rows = np.nonzero((region < 160).any(axis=1))[0] + int(top - 2 * gap)
        staff = {int(round(top + i * gap)) + d for i in range(5) for d in (-2, -1, 0, 1, 2)}
        self.assertTrue(set(rows.tolist()) <= staff, sorted(set(rows.tolist()) - staff))

    def test_system_starting_with_a_time_signature_keeps_its_line_start(self):
        self.doc.add("sys-001", *measure_strip(3))
        self.doc.add("sys-002", *measure_strip(3, time_sig=True))
        plan, _ = self.doc.compose(measure_reflow=True)
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        m = plan["measure_reflow"]
        self.assertEqual(m["audit"]["clef_removals"], [])
        self.assertIn(m["joins"]["refused"].get("sys-002"), ("TIME_SIGNATURE", "PREFIX_INK_AFTER_CLEF"))
        self.assertTrue(any(ln["atom_ids"][0].startswith("sys-002/") for ln in m["lines"]))

    def test_unregistered_system_is_never_split_when_joined(self):
        self.doc.add("sys-001", *measure_strip(3))
        self.doc.add("sys-002", *measure_strip(3), register=False)  # all its boundaries UNKNOWN: one atom
        self.doc.add("sys-003", *measure_strip(3))
        plan, _ = self.doc.compose(measure_reflow=True)
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        m = plan["measure_reflow"]
        units2 = [u["id"] for u in m["units"] if u["system_id"] == "sys-002"]
        self.assertEqual(len(units2), 1)
        on_lines = [ln for ln in m["lines"] if units2[0] in ln["atom_ids"]]
        self.assertEqual(len(on_lines), 1)


if __name__ == "__main__":
    unittest.main()
