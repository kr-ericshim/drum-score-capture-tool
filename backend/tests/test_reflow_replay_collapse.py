"""Established whole-display replay blocks and their persisted review state."""

import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app import main
from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_pipeline as rp
from app.pipeline import source_class as sc


def strip_image(glyph, *, measure=None):
    """Common staff plus independently distinct notation and measure-number ink."""
    image = np.full((140, 480, 3), 255, np.uint8)
    for y in (42, 54, 66, 78, 90):
        cv2.line(image, (12, y), (468, y), (0, 0, 0), 1)
    cv2.putText(image, str(glyph if measure is None else measure), (18, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
    for bit in range(5):
        x = 90 + bit * 65
        y = 57 if glyph & (1 << bit) else 81
        cv2.ellipse(image, (x, y), (6, 4), -20, 0, 360, (0, 0, 0), -1)
        cv2.line(image, (x + 5, y), (x + 5, y - 28), (0, 0, 0), 2)
    cv2.putText(image, "drum chart", (290, 123), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (0, 0, 0), 1)
    return image


class ReplayFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def sequence(self, values):
        systems, paths = [], {}
        for index, (sid, glyph) in enumerate(values):
            image = strip_image(glyph)
            path = self.root / f"{sid}.png"
            self.assertTrue(cv2.imwrite(str(path), image))
            paths[sid] = str(path)
            systems.append({
                "id": sid, "index": index, "included": True, "layout": "page",
                "staff_gap_px": 12.0, "order_t": index * 5.0,
                "t_start": index * 5.0, "t_end": index * 5.0 + 4.0,
                "slot_id": "slot-1", "episode_ids": [f"ep-{index}"],
                "first_display": index == 0, "terminal_display": index == len(values) - 1,
                "issues": [], "observations": [],
            })
        return systems, paths

    def collapse(self, systems, paths, **kwargs):
        return ro.collapse_replay_blocks(systems, paths, logger=lambda _m: None, **kwargs)


class ReplayBlockTests(ReplayFixture):
    def test_three_in_order_collapse_to_the_correct_earlier_block(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [(f"B{i}", i + 1) for i in range(1, 4)])
        original = copy.deepcopy(systems)
        result = self.collapse(systems, paths)
        self.assertEqual(result, [
            {"system_id": f"B{i}", "replay_of": f"A{i + 1}",
             "block": ["B1", "B3"], "block_of": ["A2", "A4"]} for i in range(1, 4)
        ])
        self.assertEqual(systems, original)

    def test_only_two_consecutive_copies_stay_included(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 2), ("B2", 3)])
        self.assertEqual(self.collapse(systems, paths), [])

    def test_three_copies_out_of_order_stay_included(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 4), ("B2", 2), ("B3", 3)])
        self.assertEqual(self.collapse(systems, paths), [])

    def test_two_earlier_blocks_make_the_later_block_ambiguous(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"C{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        result = self.collapse(systems, paths)
        # C uniquely replays A; B has both A and C as earlier starts, even
        # though C was already returned as a replay by this invocation.
        self.assertEqual([entry["system_id"] for entry in result], ["C1", "C2", "C3"])
        self.assertFalse(any(entry["system_id"].startswith("B") for entry in result))

    def test_jump_view_in_the_replay_breaks_the_run(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 2), ("B2", 3), ("B3", 4)])
        systems[-2]["layout"] = "jump_view"
        self.assertEqual(self.collapse(systems, paths), [])

    def test_jump_view_in_the_earlier_block_breaks_the_run(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 2), ("B2", 3), ("B3", 4)])
        systems[2]["layout"] = "jump_view"
        self.assertEqual(self.collapse(systems, paths), [])

    def test_a_maximal_block_is_not_split_at_three(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [(f"B{i}", i) for i in range(1, 6)])
        result = self.collapse(systems, paths)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(entry["block"] == ["B1", "B5"] and
                            entry["block_of"] == ["A1", "A5"] for entry in result))
        self.assertEqual(len({entry["system_id"] for entry in result}), 5)

    def test_an_earlier_partial_block_makes_individual_replay_lines_ambiguous(self):
        systems, paths = self.sequence(
            [("C1", 1), ("C2", 2), ("C3", 3), ("X", 9)] +
            [(f"A{i}", i) for i in range(1, 6)] +
            [(f"B{i}", i) for i in range(1, 6)])
        result = [entry for entry in self.collapse(systems, paths)
                  if entry["system_id"].startswith("B")]
        self.assertEqual(result, [])

    def test_missing_strip_breaks_the_run(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 2), ("B2", 3), ("B3", 4)])
        paths.pop("B2")
        self.assertEqual(self.collapse(systems, paths), [])

    def test_different_measure_numbers_prevent_a_block(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 4)] +
                                       [(f"B{i}", i) for i in range(1, 4)])
        for i in range(1, 4):
            self.assertTrue(cv2.imwrite(paths[f"B{i}"], strip_image(i, measure=i + 20)))
        self.assertEqual(self.collapse(systems, paths), [])

    def test_budget_stop_does_not_publish_a_partly_established_block(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 4)] +
                                       [(f"B{i}", i) for i in range(1, 4)])
        log = []
        with patch.object(ro, "_same_whole_display", wraps=ro._same_whole_display) as compare:
            result = ro.collapse_replay_blocks(systems, paths, logger=log.append, budget_pairs=6)
        self.assertEqual(result, [])
        self.assertEqual(compare.call_count, 6)
        self.assertTrue(any("budget exhausted" in message for message in log))
        self.assertIn("6 comparisons", log[-1])

    def test_budget_stop_during_distinctiveness_never_publishes_a_block(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        log = []
        with patch.object(ro, "_same_whole_display", wraps=ro._same_whole_display) as compare:
            result = ro.collapse_replay_blocks(systems, paths, logger=log.append, budget_pairs=14)
        self.assertEqual(result, [])
        self.assertEqual(compare.call_count, 14)
        self.assertTrue(any("budget exhausted" in message for message in log))
        self.assertEqual(len(self.collapse(systems, paths, budget_pairs=15)), 3)

    def test_budget_stop_keeps_an_already_established_complete_block(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)] +
            [("X1", 7), ("X2", 8), ("X3", 9)])
        log = []
        result = ro.collapse_replay_blocks(systems, paths, logger=log.append, budget_pairs=19)
        self.assertEqual([entry["system_id"] for entry in result], ["B1", "B2", "B3"])
        self.assertTrue(any("budget exhausted" in message for message in log))

    def test_each_pair_is_compared_once_and_uses_the_earlier_gap(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 2), ("B2", 3), ("B3", 4)])
        systems[0]["staff_gap_px"] = 15.0
        systems[1]["staff_gap_px"] = None
        before = self.collapse(systems, paths)
        with patch.object(ro, "_same_whole_display", wraps=ro._same_whole_display) as compare:
            after = self.collapse(systems, paths)
        self.assertEqual(before, after)
        keys = [(id(call.args[0]), id(call.args[1])) for call in compare.call_args_list]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(compare.call_args_list[0].args[2], 15.0)
        self.assertTrue(any(call.args[2] == 12.0 for call in compare.call_args_list))

    def test_one_extra_earlier_line_vetoes_an_otherwise_unique_block(self):
        systems, paths = self.sequence(
            [("G", 2), ("X", 9)] + [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        self.assertEqual(self.collapse(systems, paths), [])

    def test_generic_repeated_lines_inside_a_block_are_not_distinctive(self):
        systems, paths = self.sequence(
            [(f"A{i}", 1) for i in range(1, 4)] +
            [(f"B{i}", 1) for i in range(1, 4)])
        self.assertEqual(self.collapse(systems, paths), [])

    def test_counterpart_checks_do_not_assume_pixel_matching_is_transitive(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        images = {paths[s["id"]]: np.full((2, 2), n, np.uint8)
                  for n, s in enumerate(systems)}
        # Every B matches only its own A, yet A1 and A2 also match. That
        # additional match must veto the block even without transitivity.
        matches = {(0, 3), (1, 4), (2, 5), (0, 1)}
        with patch.object(ro.cv2, "imread", side_effect=images.get), patch.object(
                ro, "_same_whole_display",
                side_effect=lambda a, b, *_args, **_kwargs:
                    ((int(a[0, 0]), int(b[0, 0])) in matches, {})):
            self.assertEqual(self.collapse(systems, paths), [])

    def test_six_simultaneous_rows_do_not_form_a_temporal_replay(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        for s in systems:
            s.update(order_t=0.0, t_start=0.0, t_end=20.0)
        with patch.object(ro, "_same_whole_display", wraps=ro._same_whole_display) as compare:
            self.assertEqual(self.collapse(systems, paths), [])
        compare.assert_not_called()

    def test_same_view_uses_first_row_anchored_cluster_tolerance(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        systems[0]["order_t"] = 0.0
        systems[3]["order_t"] = ro.VIEW_CLUSTER_SEC
        # Display intervals remain separated, isolating the view-cluster veto.
        self.assertEqual(self.collapse(systems, paths), [])
        systems[3]["order_t"] += 0.01
        self.assertEqual(len(self.collapse(systems, paths)), 3)

    def test_replay_start_must_follow_the_last_a_display_end(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        systems[2]["t_end"] = systems[3]["t_start"] + 0.01
        self.assertEqual(self.collapse(systems, paths), [])
        systems[2]["t_end"] = systems[3]["t_start"]
        self.assertEqual(len(self.collapse(systems, paths)), 3)

    def test_missing_temporal_evidence_keeps_the_block(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        systems[2].pop("t_end")
        self.assertEqual(self.collapse(systems, paths), [])

    def test_thirteen_pixel_augmentation_dot_vetoes_automatic_exclusion(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        a = cv2.imread(paths["A1"])
        b = a.copy()
        cv2.circle(b, (106, 60), 2, (0, 0, 0), -1)
        self.assertEqual(int(np.any(a != b, axis=2).sum()), 13)
        self.assertTrue(cv2.imwrite(paths["B1"], b))
        self.assertTrue(ro._same_whole_display(a, b, 12.0)[0])
        same, diagnostics = ro._same_whole_display(a, b, 12.0,
                                                 min_area_px=4, min_area_gaps=0.04)
        self.assertFalse(same)
        self.assertEqual(diagnostics["largest_piece_px"], 13)
        self.assertEqual(self.collapse(systems, paths), [])

    def test_b_label_keeps_block_even_when_counterpart_has_a_label(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        for labels in ({"B2": {}}, {"A2": {}, "B2": {}}):
            with self.subTest(labels=labels):
                self.assertEqual(self.collapse(systems, paths, label_by=labels), [])
        self.assertEqual(len(self.collapse(systems, paths, label_by={"A2": {}})), 3)

    def test_strips_are_not_decoded_without_a_comparison(self):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 4)])
        with patch.object(ro.cv2, "imread", wraps=cv2.imread) as read:
            self.assertEqual(self.collapse(systems, paths, budget_pairs=0), [])
        read.assert_not_called()
        with patch.object(ro.cv2, "imread", wraps=cv2.imread) as read:
            self.assertEqual(self.collapse(systems[:2], paths), [])
        read.assert_not_called()

    def test_excluded_and_alternate_systems_break_runs_and_are_not_decoded(self):
        for attributes in ({"included": False}, {"alternate_of": "B1"}):
            systems, paths = self.sequence(
                [(f"A{i}", i) for i in range(1, 4)] +
                [(f"B{i}", i) for i in range(1, 4)])
            systems[4].update(attributes)
            with patch.object(ro.cv2, "imread", wraps=cv2.imread) as read:
                self.assertEqual(self.collapse(systems, paths), [])
            self.assertNotIn(paths["B2"], [call.args[0] for call in read.call_args_list])

    def test_image_decodes_are_cached(self):
        systems, paths = self.sequence(
            [(f"A{i}", i) for i in range(1, 4)] +
            [(f"B{i}", i) for i in range(1, 4)])
        with patch.object(ro.cv2, "imread", wraps=cv2.imread) as read:
            self.assertEqual(len(self.collapse(systems, paths)), 3)
        loaded = [call.args[0] for call in read.call_args_list]
        self.assertEqual(len(loaded), len(set(loaded)))


class ReplayPipelineTests(ReplayFixture):
    def analyse(self, *, revisit=1, with_alternates=False, excluded=False,
                occurrence_alternate=False, labels=()):
        systems, paths = self.sequence([(f"A{i}", i) for i in range(1, 6)] +
                                       [("B1", 2), ("B2", 3), ("B3", 4)])
        if excluded:
            systems[-2]["included"] = False
        if occurrence_alternate:
            systems[-2].update(included=False, alternate_of="B1")
        occ = {"systems": systems, "fragments": [],
               "exclusions": {"self_checks": {"revisit_count": revisit}}}
        records = [{
            "system_id": s["id"], "path": paths[s["id"]], "issues": [],
            "unrecovered_columns": 0, "box_crop": [0, 0, 480, 140],
            "size": [480, 140], "staff_gap_px": 12.0,
            "staff_y_strip": [42, 54, 66, 78, 90],
        } for s in systems]
        if with_alternates:
            for sid in ("A2", "B1"):
                alt_path = self.root / f"{sid}-alt1.png"
                self.assertTrue(cv2.imwrite(str(alt_path), strip_image(2)))
                rec = next(r for r in records if r["system_id"] == sid)
                rec["minority_content"] = {"alternates": [{
                    "suffix": "alt1", "path": str(alt_path), "box_crop": [0, 0, 480, 140],
                    "size": [480, 140], "t_start": 0.0, "t_end": 1.0,
                    "obs_ids": [], "region_ids": [],
                }]}
        manifest = {"observations": [], "source_to_crop": {}}
        tracking = {"episodes": [], "layout_intervals": []}
        log = []

        def covered(*_args, **_kwargs):
            self.assertTrue(all(s["included"] for s in occ["systems"] if s["id"].startswith("B")))
            self.assertFalse(any("REPLAY_COLLAPSED" in s["issues"] for s in occ["systems"]))
            return None

        label_by = {sid: {"path": str(self.root / f"{sid}-label.png"),
                          "bbox_source": [0, 0, 20, 10]} for sid in labels}

        def acquired(*_args, **_kwargs):
            self.assertTrue(all(s["included"] for s in occ["systems"]
                                if s["id"].startswith("B")))
            self.assertTrue(coverage.called)
            self.assertFalse(collapse.called)
            return {"by_system": label_by, "placed": len(labels), "found": len(labels),
                    "label_roi": [[0, 0], [20, 0], [20, 10], [0, 10]], "version": "test"}

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"REFLOW_DEV_LEDGER": "0"}))
            stack.enter_context(patch.object(rp, "classify_source_class", return_value={"class": sc.CLASS_LIGHT_PAPER}))
            stack.enter_context(patch.object(rp.ob, "build_manifest", return_value=manifest))
            stack.enter_context(patch.object(rp.stk, "manifest_image_loader", return_value=lambda _o: None))
            stack.enter_context(patch.object(rp.stk, "build_episodes", return_value=tracking))
            stack.enter_context(patch.object(rp.rj, "analyse_jumps", return_value=None))
            stack.enter_context(patch.object(rp.ro, "build_occurrences", return_value=occ))
            stack.enter_context(patch.object(rp.rs, "build_strips", return_value=records))
            coverage = stack.enter_context(patch.object(rp, "leftover_gate",
                side_effect=covered if not (excluded or occurrence_alternate) else lambda *_a, **_k: None))
            collapse = stack.enter_context(patch.object(rp.ro, "collapse_replay_blocks",
                                                       wraps=ro.collapse_replay_blocks))
            acquire = stack.enter_context(patch.object(rp.rlab, "acquire_labels", side_effect=acquired))
            stack.enter_context(patch.object(rp.ob, "source_to_crop_point", return_value=(0, 0)))
            record = rp.analyse_source(video_path=self.root / "unused-synthetic.mp4",
                roi=[[0, 0], [480, 0], [480, 140], [0, 140]],
                workspace=self.root / "job", logger=log.append,
                label_roi=[[0, 0], [20, 0], [20, 10], [0, 10]] if labels else None)
            if labels:
                acquire.assert_called_once()
        coverage.assert_called_once()
        return record, collapse, log

    def test_occurrences_and_returned_systems_persist_exclusion_without_order_change(self):
        record, collapse, log = self.analyse()
        collapse.assert_called_once()
        stored = json.loads((self.root / "job" / "occurrences.json").read_text())
        self.assertEqual(stored["exclusions"]["replay_blocks"], record["exclusions"]["replay_blocks"])
        self.assertEqual(len(record["systems"]), 8)
        for rows in (stored["systems"], record["systems"]):
            replay = [s for s in rows if s["id"].startswith("B")]
            self.assertEqual([s["replay_of"] for s in replay], ["A2", "A3", "A4"])
            for s in replay:
                self.assertFalse(s["included"])
                self.assertIn("REPLAY_COLLAPSED", s["issues"])
                self.assertTrue(Path(record["systems"][-1]["strip_path"]).is_file())
        self.assertTrue(all(not s["auto_included"] for s in record["systems"] if s["id"].startswith("B")))
        self.assertTrue(all(s["included"] for s in record["systems"] if s["id"].startswith("A")))
        self.assertTrue(any("comparisons" in line and "s)" in line for line in log))

    def test_zero_revisits_skip_the_comparison(self):
        record, collapse, _log = self.analyse(revisit=0)
        collapse.assert_not_called()
        self.assertTrue(all(s["included"] and s["auto_included"] for s in record["systems"]))
        self.assertNotIn("replay_blocks", record["exclusions"])
        self.assertEqual(record["duplicate_suggestions"], [])

    def test_input_contains_only_included_non_alternate_systems(self):
        for kwargs in ({"excluded": True}, {"occurrence_alternate": True}):
            with self.subTest(kwargs=kwargs):
                _record, collapse, _log = self.analyse(**kwargs)
                passed = collapse.call_args.args[0]
                self.assertNotIn("B2", [s["id"] for s in passed])

    def test_canonical_and_collapsed_replay_alternates_are_listed_unchecked(self):
        record, _collapse, _log = self.analyse(with_alternates=True)
        by_id = {s["id"]: s for s in record["systems"]}
        self.assertIn("A2-alt1", by_id)
        self.assertFalse(by_id["A2-alt1"]["included"])
        self.assertIn("B1-alt1", by_id)
        self.assertFalse(by_id["B1-alt1"]["included"])
        self.assertEqual(by_id["B1-alt1"]["alternate_of"], "B1")
        self.assertTrue(Path(by_id["B1-alt1"]["strip_path"]).is_file())
        self.assertTrue(by_id["B1"]["strip"]["minority_content"]["alternates"])
        stored = json.loads((self.root / "job" / "occurrences.json").read_text())
        self.assertEqual([s["id"] for s in stored["systems"]], [s["id"] for s in record["systems"]])
        self.assertFalse(next(s for s in stored["systems"] if s["id"] == "B1")["included"])
        self.assertFalse(next(s for s in stored["systems"] if s["id"] == "B1-alt1")["included"])

    def test_labels_are_acquired_before_collapse_and_keep_labeled_replay(self):
        record, collapse, _log = self.analyse(labels=("B2",))
        self.assertEqual(set(collapse.call_args.kwargs["label_by"]), {"B2"})
        self.assertTrue(all(s["included"] for s in record["systems"]))
        self.assertEqual(record["exclusions"]["replay_blocks"], [])
        by_id = {s["id"]: s for s in record["systems"]}
        self.assertIn("label", by_id["B2"])

    def test_diagnostics_review_candidates_and_replay_pairs_need_no_renderer_change(self):
        record, _collapse, _log = self.analyse()
        by_id = {s["id"]: s for s in record["systems"]}
        fields = main._reflow_capture_fields(record)
        self.assertEqual(fields["auto_excluded_captures"], [by_id[f"B{i}"]["strip_path"] for i in range(1, 4)])
        self.assertEqual(len(fields["review_candidates"]), 8)
        for i in range(1, 4):
            diagnostics = fields["capture_diagnostics"][by_id[f"B{i}"]["strip_path"]]
            self.assertIn("REPLAY_COLLAPSED", diagnostics["diagnostic_codes"])
            self.assertIn(dict(main.REFLOW_ISSUE_REASONS)["REPLAY_COLLAPSED"], diagnostics["warning_reasons"])
        expected = [{
            "candidate": by_id[f"B{i}"]["strip_path"], "kept": by_id[f"A{i + 1}"]["strip_path"],
            "reason": "looks_similar", "metrics": {"reason": "looks_similar", "basis": "replay_block"}
        } for i in range(1, 4)]
        self.assertEqual(fields["similar_capture_pairs"], expected)
        # The normal post-job replacement must retain the established pairs.
        record["duplicate_suggestions"] = rp.duplicate_suggestions(record)
        self.assertEqual(main._reflow_capture_fields(record)["similar_capture_pairs"], expected)
        record["duplicate_suggestions"] = rp.duplicate_suggestions(record, should_stop=lambda: True)
        self.assertEqual(main._reflow_capture_fields(record)["similar_capture_pairs"], expected)


if __name__ == "__main__":
    unittest.main()
