"""Hook 4/5 geometry and independent generated origins, using delivered raster pixels."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_layout as layout
from app.pipeline import reflow_ledger as ledger_api
from app.pipeline import reflow_measure as measure
from app.pipeline import reflow_pipeline as pipeline
from app.pipeline import reflow_render as render

from test_reflow_measure import Doc, G, TOP, label_patch, measure_strip
from test_reflow_jump_numbers import numbered_strip


def point_destinations(records, strip_id, xy):
    out = []
    for rec in records:
        if rec["strip_id"] != strip_id:
            continue
        stage = rec["stages"][0]
        q = np.asarray(stage.get("pre_matrix", np.eye(3)), float) @ [*xy, 1]
        pieces = stage.get("pieces", [{"src_bbox": [-1e9, -1e9, 1e9, 1e9], "matrix": stage.get("matrix")}])
        for piece in pieces:
            x0, y0, x1, y1 = piece["src_bbox"]
            if x0 <= q[0] < x1 and y0 <= q[1] < y1:
                l = np.asarray(piece["matrix"], float) @ q
                p = np.asarray(rec["stages"][1]["matrix"], float) @ l
                out.append((rec, l, p))
    return out


def three_pages():
    images = {}
    records = []
    for i in range(3):
        sid = f"s{i}"
        img = np.full((2200, 400, 3), 255, np.uint8)
        cv2.circle(img, (170, 700), 9, (0, 0, 150), -1)
        images[sid] = img
        records.append({"system_id": sid, "staff_gap_px": 1.5 * layout.MM})
    header = {"title": "Synthetic source ledger", "performer": "Drummer", "bpm": 120, "locale": "en",
              "source_clipped": [{"system_id": "s1"}],
              "incomplete": {"locale": "en", "unresolved": [[i * 61., i * 61. + 20] for i in range(60)],
                             "markers": [{"start": 1., "end": 2., "before_ids": ["s0"]}]}}
    generated = []
    t = time.perf_counter()
    plan, pages = render.compose(records, images, header=header, generated=generated)
    return plan, pages, images, header, generated, time.perf_counter() - t


class PageOrigins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.pages, cls.images, cls.header, cls.generated, cls.elapsed = three_pages()

    def test_pages_identical_with_and_without_generated(self):
        before = copy.deepcopy(self.plan)
        plain = render.render_pages(self.plan, self.images, header=self.header)
        self.assertEqual(self.plan, before)
        self.assertEqual(len(plain), 3)
        for a, b in zip(plain, self.pages):
            np.testing.assert_array_equal(a, b)

    def test_independent_text_marker_appendix_templates_equal_page_pixels(self):
        kinds = {r["kind"] for r in self.generated}
        self.assertTrue({"header", "page_number", "incomplete_marker", "source_clipped_notice", "review_notice"} <= kinds)
        for rec in self.generated:
            with self.subTest(kind=rec["kind"], inputs=rec["inputs"]):
                template = ledger_api.unpack_crop(rec["template"])
                x, y = rec["origin"]
                h, w = template.shape[:2]
                np.testing.assert_array_equal(template, self.pages[rec["page_index"]][y:y + h, x:x + w])
                # Music has a red dot; all independently drawn notices are achromatic.
                np.testing.assert_array_equal(template[:, :, 0], template[:, :, 2])
                ink = np.any(template < 255, axis=-1)
                self.assertTrue(ink[0].any() and ink[-1].any() and ink[:, 0].any() and ink[:, -1].any())
                self.assertTrue(rec["generator"] and rec["inputs"])

    def test_three_page_size_and_runtime(self):
        size = len(json.dumps(self.generated, separators=(",", ":")).encode())
        print(f"\n3_PAGE_GENERATED records={len(self.generated)} json_bytes={size} render_seconds={self.elapsed:.6f}")
        self.assertGreater(size, 0)

    def test_whole_system_dot_with_label_band_offset(self):
        # S -> L includes a label band; L is the actual image passed to the renderer.
        s = np.full((320, 650, 3), 255, np.uint8)
        cv2.circle(s, (240, 155), 4, (0, 0, 140), -1)
        unit = np.full((360, 650, 3), 255, np.uint8)
        unit[40:] = s
        records = [{"system_id": "s", "staff_gap_px": 24.}]
        plan, pages = render.compose(records, {"s": unit}, header=None)
        maps = render.whole_system_ledger_placements(plan, {"s": unit.shape[:2]}, offsets={"s": [0, 40]})
        self.assertNotEqual(maps[0]["stages"][1]["matrix"][0][0], 1.)
        [(rec, _l, p)] = point_destinations(maps, "s", (240, 155))
        x, y = np.round(p[:2]).astype(int)
        region = pages[rec["page_index"]][y - 1:y + 2, x - 1:x + 2]
        self.assertTrue(np.any(region[:, :, 2].astype(int) - region[:, :, 0] > 40))
        forward = np.asarray(maps[0]["stages"][1]["matrix"]) @ np.asarray(maps[0]["stages"][0]["matrix"])
        np.testing.assert_allclose(np.linalg.inv(forward) @ p, [240, 155, 1])


class MeasureOrigins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def planned(self):
        decided, _ = pipeline.resolve_dependencies(self.doc.systems)
        return measure._plan_at(decided, 1.5, context=self.doc.context, locks=[], job_id="hooks", revision=0, doc_cache={})

    def test_native_dot_through_strip_and_page_resampling_and_unchanged_pages(self):
        image, rec = measure_strip(4, time_sig=True)
        xy = (290, TOP + 4 * G + 40)
        cv2.circle(image, xy, 3, (0, 0, 140), -1)
        self.doc.add("s", image, rec, label=label_patch())
        built, lines = self.planned()
        original = layout.plan_pages

        def scaled(units, **kw):
            return original(units, **dict(kw, staff_gap_mm=kw["staff_gap_mm"] * .8))

        with patch.object(layout, "plan_pages", side_effect=scaled):
            plan, pages = measure._render(built, lines, header={"title": "T"}, staff_gap_mm=1.5,
                                          content_w=layout.PAGE_W - 2 * layout.MARGIN_X, ledger_requested=True)
        maps = built["ledger_placements"]
        self.assertEqual(maps, plan["measure_reflow"]["ledger_placements"])
        [(r, _l, p)] = point_destinations(maps, "s", xy)
        self.assertNotEqual(r["stages"][0]["pre_matrix"][0][0], 1.)
        self.assertNotEqual(r["stages"][1]["matrix"][0][0], 1.)
        x, y = np.round(p[:2]).astype(int)
        region = pages[r["page_index"]][y - 1:y + 2, x - 1:x + 2]
        self.assertTrue(np.any(region[:, :, 2].astype(int) - region[:, :, 0] > 40))
        # The same line plan can be rendered with record assembly removed.
        def empty(ledger, *_args):
            ledger.update(ledger_placements=[], ledger_removed=[], generated_origins=[])

        built2, lines2 = self.planned()
        with patch.object(layout, "plan_pages", side_effect=scaled), patch.object(measure, "_ledger_line_records", side_effect=empty):
            plain_plan, plain = measure._render(built2, lines2, header={"title": "T"}, staff_gap_mm=1.5,
                                                content_w=layout.PAGE_W - 2 * layout.MARGIN_X)
        for a, b in zip(pages, plain):
            np.testing.assert_array_equal(a, b)
        self.assertEqual(plan["pages"], plain_plan["pages"])
        labels = [r for r in built["generated_origins"] if r["kind"] == "section_label"]
        self.assertTrue(labels)
        self.assert_origin_pixels(labels, pages)

    def assert_origin_pixels(self, records, pages):
        for r in records:
            img = ledger_api.unpack_crop(r["template"])
            x, y = r["origin"]
            np.testing.assert_array_equal(img, pages[r["page_index"]][y:y + img.shape[0], x:x + img.shape[1]])

    def test_insertions_have_exact_page_templates_and_source_geometry(self):
        self.doc.add("s", *measure_strip(4, time_sig=True))
        built, lines = self.planned()
        plan, pages = measure._render(built, lines, header=None, staff_gap_mm=1.5,
                                      content_w=layout.PAGE_W - 2 * layout.MARGIN_X, ledger_requested=True)
        origins = [r for r in built["generated_origins"] if r["kind"] == "staff_scaffold"]
        self.assertTrue(origins)
        self.assert_origin_pixels(origins, pages)
        for r in origins:
            self.assertEqual(len(r["staff_rows_local"]), 5)
            self.assertEqual(r["strip_id"], "s")
            self.assertEqual(len(r["source_bbox_S"]), 4)
            self.assertTrue(r["generator"] and r["inputs"])
        for pl in plan["measure_reflow"]["audit"]["placements"]:
            self.assertEqual(len(pl["source_col_index"]), pl["width_out"])
            self.assertEqual([j for j, c in enumerate(pl["source_col_index"]) if c is None], pl["inserted_offsets"])

    def test_removed_clef_is_in_no_piece(self):
        for i in range(3):
            self.doc.add(f"s{i}", *measure_strip(3))
        built, lines = self.planned()
        _images, fragment = measure.render_lines(built["atoms"], built["strips"], lines, target_gap_px=1.5 * layout.MM)
        removed = [r for r in fragment["ledger_removed"] if r["op"] == "remove_clef"]
        self.assertTrue(removed)
        # Every changed R pixel, including its antialiased fringe, is undelivered.
        for r in removed:
            a, b, c, d = r["src_bbox_R"]
            for pl in fragment["ledger_placements"]:
                if pl["strip_id"] == r["strip_id"] and pl["line_id"] == r["line_id"] and pl["copy_index"] == 0:
                    for piece in pl["stages"][0]["pieces"]:
                        x0, y0, x1, y1 = piece["src_bbox"]
                        self.assertFalse(max(a, x0) < min(c, x1) and max(b, y0) < min(d, y1))

    def test_moved_number_has_only_its_new_destination(self):
        img, rec = numbered_strip()
        s = self.doc.add("s", img, rec)
        s["layout"] = "jump_view"
        built, lines = self.planned()
        images, fragment = measure.render_lines(built["atoms"], built["strips"], lines, target_gap_px=1.5 * layout.MM)
        moves = [m for m in fragment["moved_measure_numbers"] if m["moved"]]
        self.assertTrue(moves)
        for move in moves:
            a, b, c, d = move["src_bbox_R"]
            candidates = []
            for pl in fragment["ledger_placements"]:
                if pl["strip_id"] != "s" or pl["copy_index"] != 0:
                    continue
                for piece in pl["stages"][0]["pieces"]:
                    x0, y0, x1, y1 = piece["src_bbox"]
                    ix0, iy0, ix1, iy1 = max(a, x0), max(b, y0), min(c, x1), min(d, y1)
                    if ix0 < ix1 and iy0 < iy1:
                        q = np.asarray(piece["matrix"]) @ [(ix0 + ix1 - 1) / 2, (iy0 + iy1 - 1) / 2, 1]
                        candidates.append((pl, q))
            self.assertTrue(candidates)
            for pl, q in candidates:
                self.assertEqual(pl["line_id"], move["line_id"])
                x0, y0, x1, y1 = move["to_box_out"]
                self.assertTrue(x0 <= q[0] < x1 and y0 <= q[1] < y1)
            x0, y0, x1, y1 = move["from_box_out"]
            self.assertTrue(np.all(images[move["from_line_id"]][y0:y1, x0:x1] == 255))
            x0, y0, x1, y1 = move["to_box_out"]
            self.assertLess(images[move["line_id"]][y0:y1, x0:x1].min(), 200)
        _plan, pages = measure._render(built, lines, header=None, staff_gap_mm=1.5,
                                       content_w=layout.PAGE_W - 2 * layout.MARGIN_X, ledger_requested=True)
        for move in moves:
            a, b, c, d = move["native_box"]
            ys, xs = np.nonzero(img[b:d, a:c].min(axis=-1) < 150)
            k = len(xs) // 2
            destinations = [(r, l, p) for r, l, p in point_destinations(built["ledger_placements"], "s", (xs[k] + a, ys[k] + b))
                            if r["copy_index"] == 0]
            self.assertEqual(len(destinations), 1)
            r, _l, p = destinations[0]
            self.assertEqual(r["line_id"], move["line_id"])
            x, y = np.round(p[:2]).astype(int)
            self.assertLess(pages[r["page_index"]][y - 1:y + 2, x - 1:x + 2].min(), 200)

    def test_replica_copy_indices_and_spread_removals(self):
        img, rec = numbered_strip()
        s = self.doc.add("s", img, rec)
        s["layout"] = "jump_view"
        built, lines = self.planned()
        _images, fragment = measure.render_lines(built["atoms"], built["strips"], lines, target_gap_px=1.5 * layout.MM)
        copies = [r["copy_index"] for r in fragment["ledger_placements"] if r["copy_index"] > 0]
        self.assertEqual(copies, list(range(1, len(fragment["replicas"]) + 1)))
        self.assertTrue(copies)
        # Force a legal contraction in one existing spread gap; production pixels and
        # the source domains must both exclude the exact recorded R columns.
        built, lines = self.planned()
        by_id = {a["id"]: a for a in built["atoms"]}
        line = lines["lines"][0]
        atom = next(by_id[i] for i in line["atom_ids"] if by_id[i].get("gaps"))
        gap = atom["gaps"][0]
        slot = next(s for s in lines["slots"] if s["id"] == gap["id"])
        delta = int(slot["applied_delta"])
        slot["applied_delta"] = -2
        line["achieved_width"] -= delta + 2
        _images, fragment = measure.render_lines(built["atoms"], built["strips"], lines, target_gap_px=1.5 * layout.MM)
        removed = [r for r in fragment["ledger_removed"] if r["line_id"] == line["id"] and r["op"] == "remove_spread_columns"]
        self.assertTrue(removed)
        for r in removed:
            for pl in fragment["ledger_placements"]:
                if pl["copy_index"] == 0 and pl["line_id"] == line["id"] and pl["strip_id"] == r["strip_id"]:
                    for p in pl["stages"][0]["pieces"]:
                        a, b, c, d = r["src_bbox_R"]
                        x0, y0, x1, y1 = p["src_bbox"]
                        self.assertFalse(max(a, x0) < min(c, x1) and max(b, y0) < min(d, y1))

    def test_nonuniform_scale_is_refused_only_when_requested(self):
        image = np.full((100, 200, 3), 255, np.uint8)
        plan = {"pages": [{"index": 0, "placements": [{"system_id": "l", "w": 200, "h": 80, "x": 10, "y": 10}]}]}
        fragment = {"ledger_placements": [{"line_id": "l", "stages": [{}, {}]}], "generated_origins": []}
        measure._bind_ledger_pages(plan, {"l": image}, copy.deepcopy(fragment), ledger_requested=False)
        with self.assertRaises(measure.MeasurePlanUnavailable) as ctx:
            measure._bind_ledger_pages(plan, {"l": image}, copy.deepcopy(fragment), ledger_requested=True)
        self.assertEqual(ctx.exception.reason, "NONUNIFORM_PAGE_SCALE")

    def test_exact_nonmonotone_columns_and_pre_crop(self):
        pl = {"scale": 1.25, "pre_crop": [10, 4], "cols_src_out": [1, 5], "rows_src_out": [2, 6], "width_out": 4,
              "source_col_index": [3, 1, None, 3], "inserted_offsets": [2], "removed_cols_out": [2, 4],
              "line_id": "l", "x_out": 7, "y_out": 9}
        stage = measure._placement_stage(pl)
        np.testing.assert_allclose(np.asarray(stage["pre_matrix"]) @ [10, 4, 1], [.125, .125, 1])
        destinations = []
        for piece in stage["pieces"]:
            for col in range(piece["src_bbox"][0], piece["src_bbox"][2]):
                destinations.append((col, int((np.asarray(piece["matrix"]) @ [col, 2, 1])[0]) - 7))
        self.assertEqual(destinations, [(3, 0), (1, 1), (3, 3)])


if __name__ == "__main__":
    unittest.main()
