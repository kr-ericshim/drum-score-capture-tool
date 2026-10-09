"""Line breaking DP, bounded slots and water-filling (reflow_lines, MEASURE_BRIEF milestone 2)."""

import unittest

from app.pipeline import reflow_lines as rlines


def atoms(widths, *, system_starts=(0,), replica=50, slot=40.0, gap=17.0, counts=None, join=()):
    out = []
    for k, w in enumerate(widths):
        start = k in system_starts
        e, c = rlines.slot_caps(slot, gap)
        a = {"id": f"a{k}", "width": w, "measure_count": 1 if counts is None else counts[k], "kind": "measure",
             "break_before": "system_start" if start else "safe_cut", "join_legal": k in join,
             "slot_before": None if start else {"id": f"s{k}", "natural": slot, "max_expand": e, "max_contract": c},
             "replica_width": None if start else replica, "boundary_id": None if start else f"b{k}"}
        out.append(a)
    return out


class SlotsAndFill(unittest.TestCase):
    def test_per_gap_caps(self):
        # growth <= max(35% natural, 0.6 staff gap); the gap keeps >= max(85% natural, 0.5 staff gap)
        e, c = rlines.slot_caps(40.0, 17.0)
        self.assertAlmostEqual(e, max(0.35 * 40.0, 0.6 * 17.0))
        self.assertAlmostEqual(c, 40.0 - max(0.85 * 40.0, 0.5 * 17.0))
        e, c = rlines.slot_caps(100.0, 17.0)
        self.assertAlmostEqual(e, 35.0)
        self.assertAlmostEqual(c, 15.0)
        e, c = rlines.slot_caps(8.0, 17.0)  # a gap narrower than 0.5 staff gap cannot contract
        self.assertEqual(c, 0.0)
        self.assertAlmostEqual(e, 0.6 * 17.0)
        self.assertEqual(rlines.slot_caps(0.0, 17.0), (0.0, 0.0))

    def test_spread_fill_is_proportional_exact_and_capped(self):
        out = rlines.spread_fill(30, [100, 50, 50], [35, 17.5, 17.5])
        self.assertEqual(sum(out), 30)
        self.assertEqual(out, [15, 8, 7] if out[1] >= out[2] else [15, 7, 8])
        out = rlines.spread_fill(50, [100, 20, 20], [35, 12, 12])  # the big gap caps at 35, the rest pour into the others
        self.assertEqual(sum(out), 50)
        self.assertLessEqual(out[0], 35)
        for o, c in zip(out, [35, 12, 12]):
            self.assertLessEqual(o, c)
        self.assertEqual(rlines.spread_fill(99, [10, 10], [3.5, 3.5]), [3, 3])

    def test_water_fill_is_exact_and_bounded(self):
        for total, caps in ((10, [5, 5, 5]), (7, [1.5, 10, 10]), (3, [0.4, 0.9, 5]), (0, [3, 3])):
            out = rlines.water_fill(total, caps)
            self.assertEqual(sum(out), total, (total, caps, out))
            for o, c in zip(out, caps):
                self.assertLessEqual(o, int(c))
                self.assertGreaterEqual(o, 0)
        self.assertEqual(rlines.water_fill(9, [3, 3, 3]), [3, 3, 3])
        self.assertEqual(rlines.water_fill(50, [3, 3]), [3, 3])  # never beyond the caps


class LineBreaking(unittest.TestCase):
    def test_four_measures_per_line_preferred(self):
        plan = rlines.plan_lines(atoms([500] * 8), 2040)
        self.assertTrue(plan["valid"])
        self.assertEqual([ln["measure_count"] for ln in plan["lines"]], [4, 4])
        first, second = plan["lines"]
        self.assertEqual(first["replica_width"], 0)
        self.assertEqual(second["replica_width"], 50)  # the new line starts with a clef replica
        for ln in plan["lines"]:
            self.assertTrue(ln["justified"], ln)
            self.assertEqual(ln["achieved_width"], 2040)
            self.assertLessEqual(ln["adjustment_fraction"], rlines.MAX_EXPAND_FRACTION)
            self.assertGreaterEqual(ln["adjustment_fraction"], -rlines.MAX_CONTRACT_FRACTION)
        self.assertTrue(all(s["within_caps"] for s in plan["slots"]))

    def test_cut_without_verified_prefix_is_not_a_line_start(self):
        a = atoms([700] * 4, replica=None)
        a[2]["replica_width"] = None
        plan = rlines.plan_lines(a, 2126)
        self.assertFalse(plan["valid"])  # 2800 px cannot fit and no legal break exists
        self.assertEqual(plan["conflicts"][-1]["code"], "NO_FEASIBLE_LINE_BREAKS")

    def test_system_start_breaks_unless_a_join_is_legal(self):
        a = atoms([400, 400, 400, 400], system_starts=(0, 2))
        plan = rlines.plan_lines(a, 2126)
        self.assertEqual([ln["atom_ids"] for ln in plan["lines"]], [["a0", "a1"], ["a2", "a3"]])
        joined = rlines.plan_lines(atoms([400, 400, 400, 400], system_starts=(0, 2), join=(2,)), 2126)
        self.assertEqual([ln["atom_ids"] for ln in joined["lines"]], [["a0", "a1", "a2", "a3"]])

    def test_ragged_line_is_recorded_at_natural_width(self):
        # a last resort (Fill every line): all content between two forced breaks is too short for any line
        plan = rlines.plan_lines(atoms([400, 400, 400, 400]), 2126)
        ln = plan["lines"][0]
        self.assertFalse(ln["justified"])
        self.assertEqual(ln["achieved_width"], ln["natural_width"])
        ex = plan["ragged_exceptions"][0]
        self.assertEqual(ex["reason"], rlines.RAGGED_SEGMENT_TOO_SHORT)
        self.assertTrue(ex["final_line"])
        self.assertEqual(ex["forced_break_after"], "DOCUMENT_END")
        # the next system must start a line (it cannot join): the segment before it is too short
        two = rlines.plan_lines(atoms([400] * 4 + [400] * 4, system_starts=(0, 4)), 2126)
        self.assertEqual(two["ragged_exceptions"][0]["reason"], rlines.RAGGED_SEGMENT_TOO_SHORT)
        self.assertFalse(two["ragged_exceptions"][0]["final_line"])
        self.assertEqual(two["ragged_exceptions"][0]["forced_break_after"], "SYSTEM_CANNOT_JOIN")
        self.assertEqual(two["ragged_exceptions"][0]["unresolved_residual_px"], 2126 - two["lines"][0]["achieved_width"])
        # no choice of breaks lets both lines reach the edge: short for lack of slack
        three = atoms([400] * 4 + [1300])
        three[4]["break_before"], three[4]["join_legal"] = "system_start", True
        three[4]["slot_before"] = None
        plan3 = rlines.plan_lines(three, 2126)
        self.assertIn(rlines.RAGGED_INSUFFICIENT_SLACK, [r["reason"] for r in plan3["ragged_exceptions"]], plan3["lines"])

    def test_oversized_atom_is_a_conflict_not_a_clip(self):
        plan = rlines.plan_lines(atoms([3000]), 2126)
        self.assertFalse(plan["valid"])
        self.assertEqual(plan["conflicts"][0]["code"], "NO_FEASIBLE_LINE_BREAKS")
        self.assertEqual(plan["conflicts"][0]["target_ids"], ["a0"])

    def test_unknown_counts_omit_the_count_penalty(self):
        a = atoms([500] * 6, counts=[1, None, 1, 1, 1, 1])
        plan = rlines.plan_lines(a, 2040)
        self.assertTrue(plan["valid"])
        self.assertIsNone(plan["lines"][0]["measure_count"])

    def test_forced_break_and_keep_together(self):
        a = atoms([500] * 8)
        plan = rlines.plan_lines(a, 2040, locks=[{"id": "L1", "type": "forced_line_break", "targets": ["b2"]}])
        self.assertEqual(plan["lines"][0]["atom_ids"], ["a0", "a1"])
        kept = rlines.plan_lines(a, 2600, locks=[{"id": "L2", "type": "keep_together", "targets": ["a3", "a4"]}])
        for ln in kept["lines"]:
            self.assertFalse("a3" in ln["atom_ids"] and "a4" not in ln["atom_ids"])
        bad = atoms([500] * 4)
        bad[2]["replica_width"] = None
        res = rlines.plan_lines(bad, 2126, max_width=2126, locks=[{"id": "L3", "type": "forced_line_break", "targets": ["b2"]}])
        self.assertEqual(res["conflicts"][0]["code"], "FORCED_BREAK_PREFIX_UNVERIFIED")
        both = rlines.plan_lines(a, 2040, locks=[{"id": "F", "type": "forced_line_break", "targets": ["b3"]},
                                                 {"id": "K", "type": "keep_together", "targets": ["a2", "a4"]}])
        self.assertIn("CONTRADICTORY_LOCKS", [c["code"] for c in both["conflicts"]])

    def test_common_edge_inside_the_margin(self):
        a = atoms([480, 500, 500, 500, 490, 500, 500, 500], system_starts=(0, 4))
        first = rlines.plan_lines(a, 2126)
        edge = rlines.common_edge(first, 2126)
        self.assertLess(edge["width"], 2126)
        self.assertEqual(edge["lines_reaching"], 2)
        plan = rlines.plan_lines(a, edge["width"], max_width=2126)
        self.assertTrue(all(ln["justified"] and ln["achieved_width"] == edge["width"] for ln in plan["lines"]))


if __name__ == "__main__":
    unittest.main()
