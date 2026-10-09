"""Every line full (user 2026-10-07, DECISIONS "Every line full"): like the teacher PDF, every line runs to
the right edge, the last one included. Remedies in order: joins (a clef with a section box / text above the
staff or a lyric below it may be removed cleanly), rebalancing at SAFE cuts, then an even whitespace spread
beyond the wider caps (tier 3). A source system slightly wider than the edge tightens its gaps instead of
being split into short pieces. Join refusals are recorded in ``audit.join_refusals``."""

import tempfile
import unittest
from pathlib import Path

import cv2

from app.pipeline import reflow_lines as rlines
from app.pipeline import reflow_pipeline as rp
import test_reflow_measure as trm
from test_reflow_fill import STAFF_GAP, systems
from test_reflow_measure import G, INK, TOP, Doc, measure_strip


def narrow_gap_systems(measures, natural):
    atoms = systems(measures)
    for a in atoms:
        for g in a["gaps"]:
            e, c = rlines.slot_caps(natural, STAFF_GAP)
            g.update(natural=natural, max_expand=e, max_contract=c,
                     max_contract_wide=max(c, rlines.wide_shrink_cap(natural, STAFF_GAP)))
    return atoms


class EveryLineFull(unittest.TestCase):
    def test_short_last_line_is_rebalanced_4_2_to_3_3(self):
        atoms = systems([6])
        W = 1850
        # four measures alone would fill the first line within the normal caps ...
        first4 = rlines._line_eval(atoms, 0, 4, W, final=False)
        self.assertTrue(first4["justified"])
        self.assertEqual(first4["tier"], 1)
        # ... but that leaves a two-measure line at about half the width: the planner moves a measure instead
        plan = rlines.plan_lines(atoms, W)
        self.assertEqual([ln["measure_count"] for ln in plan["lines"]], [3, 3])
        self.assertEqual(plan["ragged_exceptions"], [])
        self.assertTrue(all(ln["justified"] and ln["achieved_width"] == W for ln in plan["lines"]))
        self.assertEqual(plan["lines"][1]["replica_width"], 50)  # the new line starts at a SAFE cut with a clef replica

    def test_system_slightly_wider_than_the_edge_stays_whole(self):
        # the user's video: full-width source systems 1.6% wider than the page line; the normal contraction caps
        # cannot take it, so the system used to be split into two half-empty lines
        atoms = narrow_gap_systems([4, 4], natural=20.0)
        nat = rlines._line_eval(atoms, 0, 4, 10 ** 6, final=False)["natural"]
        W = int(nat * 0.957)
        normal = sum(int(g["max_contract"]) for a in atoms[:4] for g in a["gaps"]) + \
            sum(int(a["slot_before"]["max_contract"]) for a in atoms[1:4])
        self.assertLess(normal, nat - W)
        plan = rlines.plan_lines(atoms, W)
        self.assertEqual([ln["atom_ids"][0] for ln in plan["lines"]], ["s0m0", "s1m0"])
        for ln in plan["lines"]:
            self.assertTrue(ln["justified"])
            self.assertEqual(ln["justify_tier"], 2)
            self.assertGreaterEqual(ln["adjustment_fraction"], -rlines.MAX_CONTRACT_FRACTION - 1e-9)
        for s in plan["slots"]:
            self.assertTrue(s["within_caps"], s)
            if s["kind"] == "spread":  # a gap keeps at least 60% of its width and 0.4 staff gap
                self.assertGreaterEqual(s["natural"] + s["applied_delta"],
                                        max(0.6 * s["natural"], 0.4 * STAFF_GAP) - 1e-9)

    def test_tier3_spread_is_even_and_recorded(self):
        atoms = systems([2, 2])
        atoms[2]["join_legal"] = False
        plan = rlines.plan_lines(atoms, 2126)
        self.assertEqual(plan["ragged_exceptions"], [])
        for ln in plan["lines"]:
            self.assertEqual(ln["justify_tier"], 3)
            self.assertEqual(ln["achieved_width"], 2126)
            spread = [s for s in plan["slots"] if s["line_id"] == ln["id"] and s["kind"] == "spread"]
            ratios = [s["applied_delta"] / s["natural"] for s in spread]
            self.assertLessEqual(max(ratios) - min(ratios), 1.0 / 60.0 + 1e-9)


class JoinRefusalsAndOutsideInk(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def compose(self):
        return rp.compose_systems(self.doc.systems, all_systems=self.doc.systems, workspace=None, measure_reflow=True,
                                  measure_context=self.doc.context)

    def test_refusal_reasons_are_recorded_and_a_section_box_no_longer_blocks_a_join(self):
        ls = [TOP + i * G for i in range(5)]
        for k in range(3):
            img, rec = measure_strip(3, time_sig=(k == 2))
            if k == 1:
                # a section box above the staff over the clef, its bottom edge inside the analysis band
                cv2.rectangle(img, (26, ls[0] - 24), (56, ls[0] - 5), INK, 2)
            self.doc.add(f"sys-{k + 1:03d}", img, rec)
        plan, _pages = self.compose()
        m = plan["measure_reflow"]
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        refusals = {r["system_id"]: r for r in m["audit"]["join_refusals"]}
        self.assertNotIn("sys-002", refusals)  # the boxed system joins: its clef is removed, the box kept
        self.assertIn(refusals["sys-003"]["reason"], ("TIME_SIGNATURE", "PREFIX_INK_AFTER_CLEF"))
        self.assertEqual(m["joins"]["refused"].get("sys-003"), refusals["sys-003"]["reason"])
        # every line reaches the edge, the last one included
        self.assertTrue(all(ln["justified"] for ln in m["lines"]))
        removed = [c for c in m["audit"]["clef_removals"] if c["system_id"] == "sys-002"]
        self.assertEqual(len(removed), 1)  # joined: the box is listed as kept, nothing but the clef changed
        if removed:
            self.assertEqual(len(removed[0]["kept_outside_staff_boxes"]), 1)
            self.assertEqual(removed[0]["removed_nonstaff_not_clef_px"], 0)
            self.assertEqual(removed[0]["changed_outside_mask_px"], 0)


if __name__ == "__main__":
    unittest.main()
