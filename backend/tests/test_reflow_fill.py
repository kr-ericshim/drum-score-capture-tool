"""Fill every line (user request 2026-10-06, DECISIONS "Fill every line"): section starts do not force a
line break, every line reaches the common edge (final line included) through break choice, then the
wider per-line caps, then final-line rebalancing; a ragged line is a recorded last resort."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_lines as rlines
import test_reflow_measure as trm
from test_reflow_measure import G, INK, MW, PREFIX, TOP, Doc, label_patch, measure_strip

STAFF_GAP = 17.7


def gap(gid, natural=60.0):
    e, c = rlines.slot_caps(natural, STAFF_GAP)
    return {"id": gid, "kind": "spread", "natural": natural, "max_expand": e, "max_contract": c,
            "max_expand_wide": max(e, rlines.wide_grow_cap(natural, STAFF_GAP))}


def systems(measures, *, width=430, gaps=4, ends_section=(), section_start=(), join=True, replica=50, trim=40):
    """Atoms of source systems with ``measures[k]`` one-measure units each; every system after the first
    may join mid-line (its clef removed) unless ``join`` is False."""
    out = []
    for s, n in enumerate(measures):
        for m in range(n):
            aid = f"s{s}m{m}"
            a = {"id": aid, "system_id": f"sys-{s}", "width": width, "measure_count": 1, "kind": "measure",
                 "gaps": [gap(f"{aid}/g{i}") for i in range(gaps)]}
            if m == 0:
                jl = bool(join and s > 0)
                a.update(break_before="system_start", join_legal=jl, slot_before=None, boundary_id=None,
                         section_start=s in section_start, join_trim=trim if jl else 0,
                         join={"slot": dict(gap(f"{aid}/join"), kind="join_lead")} if jl else None)
            else:
                a.update(break_before="safe_cut", join_legal=False, replica_width=replica, boundary_id=f"b-{aid}",
                         slot_before=dict(gap(f"{aid}/slot", 40.0), kind="barline_corridor"))
            a["ends_section"] = bool(m == n - 1 and s in ends_section)
            out.append(a)
    return out


class SectionStarts(unittest.TestCase):
    def test_a_line_continues_across_a_section_start(self):
        # sys-1 ends with a double barline and sys-2 starts a labelled section; spread justification (m5)
        # ended a short line there (SECTION_END); the section start no longer stops the line
        atoms = systems([4, 3, 5, 5, 4], ends_section=(1,), section_start=(2,))
        plan = rlines.plan_document(atoms, 2126)
        self.assertEqual(plan["ragged_exceptions"], [])
        crossing = [ln for ln in plan["lines"] if "s1m2" in ln["atom_ids"]][0]
        self.assertIn("s2m0", crossing["atom_ids"], [ln["atom_ids"] for ln in plan["lines"]])
        self.assertTrue(crossing["justified"])
        self.assertIn("sys-2", crossing["joined_system_ids"])

    def test_a_system_that_cannot_join_still_starts_a_line(self):
        atoms = systems([5, 5, 5, 5])
        atoms[10]["join_legal"] = False  # sys-2 has its own time signature
        plan = rlines.plan_document(atoms, 2126)
        starts = [ln["atom_ids"][0] for ln in plan["lines"]]
        self.assertIn("s2m0", starts)


class FillEveryLine(unittest.TestCase):
    def test_final_line_is_rebalanced_from_the_lines_before_it(self):
        # 13 measures: five per line (2150 px, slightly contracted) leaves a 3-measure last line (61%);
        # moving measures from the previous lines (at SAFE cuts) fills it
        atoms = systems([13])
        plan = rlines.plan_document(atoms, 2126)
        self.assertEqual(plan["ragged_exceptions"], [], [ln["atom_ids"] for ln in plan["lines"]])
        counts = [ln["measure_count"] for ln in plan["lines"]]
        self.assertEqual(sum(counts), 13)
        self.assertGreaterEqual(counts[-1], 4)
        edge = plan["edge"]["width"]
        for ln in plan["lines"]:
            self.assertTrue(ln["justified"])
            self.assertEqual(ln["achieved_width"], edge)
        # every line starting inside the system carries a clef replica; no measure is lost or repeated
        self.assertEqual([a for ln in plan["lines"] for a in ln["atom_ids"]], [a["id"] for a in atoms])

    def test_very_short_final_line_moves_measures_instead_of_stretching(self):
        # 12 measures at the page width: 5 + 5 + 2 (m5) leaves a 910 px last line (43%) that no stretch can
        # fill; measures move from the previous lines at SAFE cuts instead
        atoms = systems([12])
        plan = rlines.plan_lines(atoms, 2126)
        self.assertEqual(plan["ragged_exceptions"], [])
        self.assertEqual([ln["measure_count"] for ln in plan["lines"]], [4, 4, 4])
        for ln in plan["lines"]:
            self.assertTrue(ln["justified"])
            self.assertLessEqual(ln["adjustment_fraction"], rlines.WIDE_MAX_EXPAND_FRACTION + 1e-9)
        self.assertTrue(all(ln["atom_ids"][0] == "s0m0" or ln["replica_width"] == 50 for ln in plan["lines"]))

    def test_wider_caps_are_enforced_and_used_only_where_needed(self):
        # four 430 px measures (1810 px with corridors and replica) need about 17%: more than the 15%
        # line limit, within the wider 25%
        atoms = systems([4, 4])
        atoms[4]["join_legal"] = False
        plan = rlines.plan_lines(atoms, 2126)
        for ln in plan["lines"]:
            self.assertTrue(ln["justified"], ln)
            self.assertEqual(ln["justify_tier"], 2)
            self.assertGreater(ln["adjustment_fraction"], rlines.MAX_EXPAND_FRACTION)
            self.assertLessEqual(ln["adjustment_fraction"], rlines.WIDE_MAX_EXPAND_FRACTION + 1e-9)
        for s in plan["slots"]:
            self.assertEqual(s["cap_tier"], 2)
            self.assertTrue(s["within_caps"], s)
            self.assertLessEqual(s["applied_delta"], max(0.60 * s["natural"], 1.0 * STAFF_GAP) + 1e-9)
        # a line within the normal caps keeps them
        normal = rlines.plan_lines(atoms, 1950)
        for ln in normal["lines"]:
            self.assertEqual(ln["justify_tier"], 1)
        for s in normal["slots"]:
            self.assertEqual(s["cap_tier"], 1)
            self.assertLessEqual(s["applied_delta"], max(0.35 * s["natural"], 0.6 * STAFF_GAP) + 1e-9)
        # beyond 25% (Every line full, 2026-10-07): an even spread over every eligible gap of that line
        # (tier 3), each gap growing by the same fraction of its natural width, at most TIER3_MAX_GAP_RATIO
        short = systems([3, 3])
        short[3]["join_legal"] = False
        far = rlines.plan_lines(short, 2126)
        self.assertEqual(far["ragged_exceptions"], [])
        for ln in far["lines"]:
            self.assertTrue(ln["justified"])
            self.assertEqual(ln["justify_tier"], 3)
            self.assertGreater(ln["adjustment_fraction"], rlines.WIDE_MAX_EXPAND_FRACTION)
            ratios = [s["applied_delta"] / s["natural"] for s in far["slots"] if s["line_id"] == ln["id"]]
            self.assertLessEqual(max(ratios) - min(ratios), 2.0 / 40.0 + 1e-9, ratios)  # even, up to whole pixels
            self.assertLessEqual(max(ratios), rlines.TIER3_MAX_GAP_RATIO + 1e-9)
        self.assertTrue(all(s["cap_tier"] == 3 and s["within_caps"] for s in far["slots"]))
        # only when even that cannot fill the line does it stay short, at natural width, recorded
        tiny = systems([1, 1], gaps=1)
        tiny[1]["join_legal"] = False
        rag = rlines.plan_lines(tiny, 2126)
        for ln in rag["lines"]:
            self.assertFalse(ln["justified"])
            self.assertEqual(ln["adjustment_px"], 0)
        self.assertEqual(len(rag["ragged_exceptions"]), 2)

    def test_no_ragged_line_where_spread_justification_left_some(self):
        # the 01Mr pattern: three-measure systems joining mid-line, a double barline after the second
        # system, a fourth system with its own prefix (a new time signature) and a short last system.
        # Spread justification (m5) left the section-end line, the line before the new time signature and
        # the last line short; now every line reaches the edge.
        atoms = systems([3, 3, 3, 3, 3, 3, 3], ends_section=(1,), section_start=(2,))
        atoms[9]["join_legal"] = False  # sys-3 starts with its own time signature
        plan = rlines.plan_document(atoms, 2126)
        self.assertEqual(plan["ragged_exceptions"], [], [(ln["atom_ids"], ln["natural_width"]) for ln in plan["lines"]])
        self.assertTrue(all(ln["achieved_width"] == plan["edge"]["width"] for ln in plan["lines"]))
        self.assertGreaterEqual(plan["edge"]["width"], rlines.EDGE_MIN_FRACTION * 2126)

    def test_unsplittable_short_content_is_recorded_not_stretched(self):
        # a whole-system atom with no whitespace (a multi-measure rest) that no neighbour can share a line with
        atoms = systems([1, 5, 5], gaps=0)
        atoms[0].update(kind="system", width=1400, measure_count=None)
        atoms[1]["join_legal"] = True
        atoms[1]["width"] = 900
        plan = rlines.plan_document(atoms, 2126)
        first = plan["lines"][0]
        self.assertEqual(first["atom_ids"], ["s0m0"])
        ex = plan["ragged_exceptions"][0]
        self.assertEqual(ex["line_id"], first["id"])
        self.assertEqual(ex["reason"], rlines.RAGGED_LOCKED_SPAN)
        self.assertEqual(first["adjustment_px"], 0)
        # the edge is not pulled inward to the one short line
        self.assertGreaterEqual(plan["edge"]["width"], rlines.EDGE_MIN_FRACTION * 2126)


def double_bar(img, measures):
    ls = [TOP + i * G for i in range(5)]
    x = PREFIX + measures * MW
    cv2.rectangle(img, (x - 7, ls[0]), (x - 6, ls[4]), INK, -1)  # thin + final barline: a double barline
    return img


class SectionLabelMidLine(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def test_section_start_mid_line_keeps_its_label_above_its_first_measure(self):
        a, rec_a = measure_strip(4)
        self.doc.add("sys-001", double_bar(a, 4), rec_a, label=label_patch("A"))
        self.doc.add("sys-002", *measure_strip(4), label=label_patch("B"))
        self.doc.add("sys-003", *measure_strip(4))
        plan, _pages = self.doc.compose(measure_reflow=True)
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        m = plan["measure_reflow"]
        self.assertEqual(m["ragged_exceptions"], [], [(ln["atom_ids"], ln["natural_width"]) for ln in m["lines"]])
        labels = {lab["system_id"]: lab for lab in m["labels"]}
        self.assertTrue(labels["sys-002"]["mid_line"])  # the section start did not force a new line
        line = next(ln for ln in m["lines"] if ln["id"] == labels["sys-002"]["line_id"])
        self.assertTrue(any(a.startswith("sys-001") for a in line["atom_ids"]))
        first_b = min((p for p in m["audit"]["placements"] if p["system_id"] == "sys-002"), key=lambda p: (p["line_id"], p["x_out"]))
        self.assertEqual(first_b["line_id"], line["id"])
        self.assertTrue(first_b.get("joined"))
        box = labels["sys-002"]["box_out"]
        # above the measure where the section starts: over its first measure, not over the previous one
        self.assertGreaterEqual(box[0], first_b["x_out"])
        self.assertLess(box[0], first_b["x_out"] + first_b["width_out"])
        self.assertLessEqual(box[3], line["label_band_px"])
        self.assertIn("sys-002", line["joined_system_ids"])
        self.assertEqual(len(m["audit"]["clef_removals"]), sum(len(ln["joined_system_ids"]) for ln in m["lines"]))

    def test_a_tall_mark_makes_only_its_own_line_taller(self):
        # a system split over two lines: the mark above its first measure must not make the second line as tall
        img, rec = measure_strip(8, time_sig=True)
        img = np.pad(img, ((60, 0), (0, 0), (0, 0)), constant_values=252)
        rec = dict(rec, staff_y_strip=[y + 60 for y in rec["staff_y_strip"]], size=[img.shape[1], img.shape[0]],
                   box_crop=[0, 0, img.shape[1], img.shape[0]])
        cv2.putText(img, "Fine", (PREFIX + 80, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, INK, 2, cv2.LINE_AA)
        obs = np.pad(measure_strip(8, time_sig=True)[0], ((60, 0), (0, 0), (0, 0)), constant_values=252)
        self.doc.add("sys-001", img, rec, obs_img=obs)
        plan, _pages = self.doc.compose(measure_reflow=True)
        trm.MeasureReflow.assertValidMeasurePlan(self, plan)
        m = plan["measure_reflow"]
        self.assertEqual(len(m["lines"]), 2)
        first, second = m["lines"]
        self.assertGreater(first["height_px"], second["height_px"] + 40)
        self.assertEqual(first["staff_top_px"] - second["staff_top_px"], first["height_px"] - second["height_px"])
        cropped = [p for p in m["audit"]["placements"] if p["line_id"] == second["id"]]
        self.assertTrue(all(p["rows_src_out"][0] > 0 for p in cropped))


if __name__ == "__main__":
    unittest.main()
