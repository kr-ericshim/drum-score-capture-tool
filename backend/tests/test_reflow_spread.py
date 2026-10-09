"""Spread justification (DECISIONS "Spread justification"): whitespace goes into many gaps between
note/rest columns, only through columns that are verified whitespace; per-gap caps; exact pixel
ledger; balanced line breaking."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_lines as rlines
from app.pipeline import reflow_measure as rmeas
import test_reflow_measure as trm
from test_reflow_measure import Doc, measure_strip

G = 18
TOP = 80
INK = (20, 20, 20)


def score_line():
    """An output-scale line with staff lines and, per region, a different glyph kind. Returns the image,
    the staff-row mask and a mask of every non-staff glyph pixel (which no spread gap may touch)."""
    h, w = 260, 1500
    img = np.full((h, w, 3), 255, np.uint8)
    glyph = np.zeros((h, w), bool)
    ls = [TOP + i * G for i in range(5)]
    for y in ls:
        img[y:y + 2, :] = INK
    rows = np.zeros(h, bool)
    for y in ls:
        rows[y - 1:y + 3] = True

    def draw(fn):
        m = np.zeros((h, w), np.uint8)
        fn(m)
        glyph[:] |= m > 0
        img[m > 0] = INK

    def note(x, up=True):
        y = ls[2] + G // 2
        draw(lambda m: cv2.ellipse(m, (x, y), (9, 6), -20, 0, 360, 255, -1))
        draw(lambda m: cv2.rectangle(m, (x + 8, ls[0] - 2 * G), (x + 9, y), 255, -1))

    # plain quarter notes (staff-only gaps between them)
    for x in (60, 160, 260):
        note(x)
    # two notes joined by a level beam
    note(400)
    note(520)
    draw(lambda m: cv2.rectangle(m, (408, ls[0] - 2 * G), (529, ls[0] - 2 * G + 5), 255, -1))
    # two notes joined by a sloped beam
    note(660)
    note(800)
    draw(lambda m: cv2.fillConvexPoly(m, np.array([[668, ls[0] - 2 * G], [809, ls[0] - 2 * G - 14],
                                                    [809, ls[0] - 2 * G - 8], [668, ls[0] - 2 * G + 6]]), 255))
    # a slur over two notes
    note(940)
    note(1080)
    draw(lambda m: cv2.ellipse(m, (1010, ls[4] + G), (90, 22), 0, 0, 180, 255, 2))
    # a thick horizontal smear (a strip artifact) between two stems: not a beam
    draw(lambda m: cv2.rectangle(m, (560, ls[0] - 4 * G), (640, ls[0] - 2 * G - 2), 255, -1))
    draw(lambda m: cv2.rectangle(m, (558, ls[0] - 5 * G), (559, ls[4]), 255, -1))
    draw(lambda m: cv2.rectangle(m, (641, ls[0] - 5 * G), (642, ls[4]), 255, -1))
    # lyrics under notes with a wide space between words, and a dot right after a notehead
    note(1200)
    note(1380)
    draw(lambda m: cv2.putText(m, "la", (1180, ls[4] + 3 * G), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2))
    draw(lambda m: cv2.putText(m, "lu", (1360, ls[4] + 3 * G), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2))
    draw(lambda m: cv2.circle(m, (1218, ls[2] + 3), 2, 255, -1))
    return img, rows, glyph, ls


class EligibleColumns(unittest.TestCase):
    def setUp(self):
        self.img, self.rows, self.glyph, self.ls = score_line()
        self.gaps = rmeas.spread_gaps(self.img, self.rows, float(G), 0, self.img.shape[1], id_prefix="t")

    def test_no_gap_column_touches_a_notehead_stem_dot_slur_or_text(self):
        self.assertTrue(self.gaps)
        glyph_cols = self.glyph.any(axis=0)
        for g in self.gaps:
            a, b = g["run_out"]
            # the run and its 2-px margins carry no glyph start/end: only continuing horizontal ink
            for c in range(a, b):
                self.assertTrue(rmeas.column_eligible(self.img, c), (g, c))
            if g["column_kind"] == "staff_only":
                self.assertFalse(glyph_cols[a - 2:b + 2].any(), g)
            ink = self.img[:, a:b].min(axis=2) < rmeas.SPREAD_INK_GRAY
            self.assertTrue((ink == ink[:, :1]).all(), g)

    def test_staff_only_gaps_between_plain_notes(self):
        mids = [g["col_out"] for g in self.gaps if g["column_kind"] == "staff_only"]
        for left, right in ((60, 160), (160, 260)):
            self.assertTrue(any(left + 10 < c < right - 9 for c in mids), (left, right, mids))

    def test_beam_is_extended_only_where_level(self):
        kinds = {g["column_kind"] for g in self.gaps if 410 < g["col_out"] < 520}
        self.assertEqual(kinds, {"level_beam"})
        self.assertFalse([g for g in self.gaps if 670 < g["col_out"] < 800], "sloped beam must not be extended")

    def test_a_thick_smear_is_not_extended_like_a_beam(self):
        self.assertFalse([g for g in self.gaps if 560 < g["col_out"] < 641])

    def test_no_gap_under_a_slur(self):
        self.assertFalse([g for g in self.gaps if 925 < g["col_out"] < 1095])

    def test_space_between_words_is_a_gap_but_not_inside_a_word_or_next_to_a_dot(self):
        between = [g for g in self.gaps if 1230 < g["col_out"] < 1360]
        self.assertTrue(between)
        self.assertFalse([g for g in self.gaps if 1205 <= g["col_out"] <= 1222])  # notehead to dot: too narrow

    def test_gaps_touching_the_atom_ends_or_left_of_the_prefix_guard_are_excluded(self):
        inner = rmeas.spread_gaps(self.img, self.rows, float(G), 100, 1300, id_prefix="t")
        for g in inner:
            self.assertGreater(g["run_out"][0] - 2, 100)
            self.assertLess(g["run_out"][1] + 2, 1300)
        guarded = rmeas.spread_gaps(self.img, self.rows, float(G), 0, 1500, guard_x=600, id_prefix="t")
        self.assertTrue(all(g["run_out"][0] - 2 >= 600 for g in guarded))

    def test_caps_follow_the_per_gap_rule(self):
        for g in self.gaps:
            self.assertAlmostEqual(g["max_expand"], max(0.35 * g["natural"], 0.6 * G))
            self.assertLessEqual(g["max_contract"], g["natural"] - max(0.85 * g["natural"], 0.5 * G) + 1e-9)
            self.assertLessEqual(g["max_contract"], g["run_out"][1] - g["run_out"][0])


def gap_atoms(widths, gaps_per_atom=4, gap_nat=60.0, replica=50, staff_gap=17.7):
    out = []
    e, c = rlines.slot_caps(gap_nat, staff_gap)
    for k, w in enumerate(widths):
        out.append({"id": f"a{k}", "width": w, "measure_count": 1, "kind": "measure",
                    "break_before": "system_start" if k == 0 else "safe_cut", "join_legal": False,
                    "slot_before": None, "replica_width": None if k == 0 else replica, "boundary_id": None if k == 0 else f"b{k}",
                    "gaps": [{"id": f"a{k}/g{i}", "kind": "spread", "natural": gap_nat, "max_expand": e, "max_contract": c}
                             for i in range(gaps_per_atom)]})
    return out


class PlannerCaps(unittest.TestCase):
    def test_per_gap_caps_and_line_limits_are_enforced(self):
        plan = rlines.plan_document(gap_atoms([420, 380, 450, 400, 430, 410, 390, 440, 400, 420]), 2126)
        self.assertTrue(plan["valid"])
        for s in plan["slots"]:
            self.assertTrue(s["within_caps"], s)
            self.assertLessEqual(s["applied_delta"], max(0.35 * s["natural"], 0.6 * 17.7) + 1e-9)
        for ln in plan["lines"]:
            self.assertLessEqual(ln["adjustment_fraction"], rlines.MAX_EXPAND_FRACTION + 1e-9)
            self.assertGreaterEqual(ln["adjustment_fraction"], -rlines.MAX_CONTRACT_FRACTION - 1e-9)
            if ln["justified"]:
                self.assertEqual(ln["achieved_width"], plan["edge"]["width"])

    def test_extra_width_is_spread_proportionally(self):
        a = gap_atoms([500, 500, 500, 500], gaps_per_atom=3)
        a[1]["gaps"][0]["natural"] = 120.0  # a gap twice as wide takes about twice the growth
        a[1]["gaps"][0]["max_expand"] = 0.35 * 120.0
        plan = rlines.plan_lines(a, 2150)
        ln = plan["lines"][0]
        self.assertTrue(ln["justified"])
        d = {s["id"]: s["applied_delta"] for s in plan["slots"]}
        small = [v for k, v in d.items() if k != "a1/g0"]
        self.assertGreater(len(set(small)), 0)
        self.assertLessEqual(max(small) - min(small), 1)
        self.assertAlmostEqual(d["a1/g0"], 2 * sum(small) / len(small), delta=2)

    def test_balanced_breaking_lowers_the_worst_stretch(self):
        # unknown counts: no measure preference, so the stretch term decides the breaks
        widths = [360, 540, 300, 300, 300, 300, 480, 420, 300, 540, 540, 300]
        atoms = gap_atoms(widths)
        for a in atoms:
            a["measure_count"] = None
        W = 2000
        plan = rlines.plan_lines(atoms, W)
        self.assertTrue(plan["valid"])
        # Every line full (2026-10-07): the last line too, so the extra width is balanced over all lines
        self.assertTrue(all(ln["justified"] for ln in plan["lines"]))
        dp_max = max(abs(ln["stretch_ratio"]) for ln in plan["lines"])
        # greedy first fit: as many atoms as fit on each line
        i, greedy = 0, []
        while i < len(atoms):
            j = i + 1
            while j < len(atoms) and rlines._line_eval(atoms, i, j + 1, W, final=False) is not None:
                j += 1
            greedy.append(rlines._line_eval(atoms, i, j, W, final=(j == len(atoms))))
            i = j
        greedy_max = max(abs(ev["stretch_ratio"]) for ev in greedy)
        self.assertLess(dp_max, greedy_max - 0.03, ([ln["atom_ids"] for ln in plan["lines"]], [(ev["start"], ev["end"]) for ev in greedy]))


class PixelLedger(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def test_removing_inserted_columns_reconstructs_the_strip(self):
        a = measure_strip(4, time_sig=True)
        b_img, b_rec = measure_strip(4, time_sig=True)
        b_img = np.ascontiguousarray(b_img[:, :-60])  # narrower: its line must expand
        b_rec = dict(b_rec, size=[b_img.shape[1], b_img.shape[0]], box_crop=[0, 0, b_img.shape[1], b_img.shape[0]])
        for k, (img, rec) in enumerate([a, (b_img, b_rec), a]):
            self.doc.add(f"sys-{k + 1:03d}", img, rec, obs_img=measure_strip(4, time_sig=True)[0])
        decided = [{"system": s, "strip_path": s["strip_path"], "variant": "cut", "label": None, "label_section": None}
                   for s in self.doc.systems]
        gap = 1.5 * rl.MM
        built = rmeas.build_atoms(decided, target_gap_px=gap, context=self.doc.context)
        plan = rlines.plan_document(built["atoms"], rl.PAGE_W - 2 * rl.MARGIN_X)
        images, ledger = rmeas.render_lines(built["atoms"], built["strips"], plan, target_gap_px=gap)
        self.assertEqual(ledger["render_mismatched_px"], 0)
        spread = [op for op in ledger["scaffold_operations"] if op["op"] == "insert_spread_columns"]
        self.assertTrue(spread, "the narrower line should be justified with spread insertions")
        self.assertTrue(all(op["eligible"] for op in spread))
        self.assertIn("level_beam", {op["column_kind"] for op in spread})
        for pl in ledger["placements"]:
            R = built["strips"][pl["system_id"]]["image"]
            X0, X1 = pl["cols_src_out"]
            kept = [c for c in range(X0, X1) if c not in set(pl["removed_cols_out"])]
            r0, r1 = pl["rows_src_out"]  # rows left off the line hold only paper in the unit's columns
            self.assertTrue(np.all(R[:r0, X0:X1] >= 200) and np.all(R[r1:, X0:X1] >= 200), pl["unit_id"])
            got = rmeas.reconstruct_atom(images[pl["line_id"]], pl)
            self.assertEqual(got.shape, R[r0:r1, kept].shape, pl["unit_id"])
            self.assertTrue(np.array_equal(got, R[r0:r1, kept]), pl["unit_id"])
            if not pl["removed_cols_out"]:
                self.assertTrue(np.array_equal(got, R[r0:r1, X0:X1]))
            # every inserted column repeats a column right before it (identical by eligibility)
            seg = images[pl["line_id"]][pl["y_out"]:pl["y_out"] + R.shape[0], pl["x_out"]:pl["x_out"] + pl["width_out"]]
            for o in pl["inserted_offsets"]:
                self.assertTrue(np.array_equal(seg[:, o], seg[:, o - 1]))

    def test_composed_plan_is_valid_with_spread_operations(self):
        a = measure_strip(4, time_sig=True)
        b_img, b_rec = measure_strip(4, time_sig=True)
        b_img = np.ascontiguousarray(b_img[:, :-60])
        b_rec = dict(b_rec, size=[b_img.shape[1], b_img.shape[0]], box_crop=[0, 0, b_img.shape[1], b_img.shape[0]])
        for k, (img, rec) in enumerate([a, (b_img, b_rec), a]):
            self.doc.add(f"sys-{k + 1:03d}", img, rec, obs_img=measure_strip(4, time_sig=True)[0])
        plan, _pages = self.doc.compose(measure_reflow=True)
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        m = plan["measure_reflow"]
        self.assertTrue(all(ln["justified"] for ln in m["lines"]))
        spread = [s for s in m["justification_slots"] if s["kind"] == "spread"]
        self.assertGreater(len(spread), 10)
        tier = {ln["id"]: ln["justify_tier"] for ln in m["lines"]}
        for s in spread:
            if tier[s["line_id"]] == 3:  # Every line full: an even spread beyond the wider caps, per gap bounded
                self.assertLessEqual(s["applied_delta"], max(rlines.TIER3_MAX_GAP_RATIO * s["natural"],
                                                             max(0.60 * s["natural"], 1.0 * 1.5 * rl.MM)) + 1e-9)
            elif tier[s["line_id"]] == 2:  # Fill every line: the wider caps, only on a line that needs them
                self.assertLessEqual(s["applied_delta"], max(0.60 * s["natural"], 1.0 * 1.5 * rl.MM) + 1e-9)
            else:
                self.assertLessEqual(s["applied_delta"], max(0.35 * s["natural"], 0.6 * 1.5 * rl.MM) + 1e-9)


if __name__ == "__main__":
    unittest.main()
