"""Delivered staff profiles across fractional-scale cuts and scaffold joins."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_measure as measure
from app.pipeline import reflow_pipeline as pipeline
from app.pipeline import reflow_render as render
from test_reflow_measure import Doc, G, MW, PREFIX, TOP, measure_strip


def column_runs(mask):
    cols = np.flatnonzero(mask)
    return [[int(a[0]), int(a[-1]) + 1] for a in np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1) if len(a)]


def staff_profiles(plan, pages, sources):
    """Measure actual page rows; source replay only excuses source-mapped paper.

    No reconstruction/coverage flags are read. Each raw strip is independently
    resized on the declared integer canvas; piece domains map its staff profile
    to the delivered row. A generated column is covered by its source column.
    """
    fragments = plan["measure_reflow"]
    by_line = {a["id"]: a for a in fragments["lines"]}
    records = fragments["ledger_placements"]
    cache, profiles = {}, []
    for page_index, page in enumerate(pages):
        gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
        for pl in plan["pages"][page_index]["placements"]:
            lid = pl["line_id"]
            line = by_line[lid]
            x, y, w, h = (pl[k] for k in ("x", "y", "w", "h"))
            line_records = [r for r in records if r["line_id"] == lid and r["copy_index"] == 0]
            # Find the darkest actual row near each predicted staff centre.
            rows = []
            for k in range(5):
                centre = y + int(round((line["staff_top_px"] + k * plan["staff_gap_px"] + .5) * h / line["height_px"] - .5))
                row = max(range(max(y, centre - 1), min(y + h, centre + 2)),
                          key=lambda r: np.median(255 - gray[r, x:x + w]))
                rows.append(row)
            vertical = np.mean(255 - gray[rows[0] + 2:rows[-1] - 1, x:x + w] >= 64, axis=0) >= .85
            bars = column_runs(vertical)
            if len(bars) < 2:
                raise AssertionError(f"{lid}: fewer than two measured barlines")
            first, last = bars[0][0], bars[-1][1]
            for k, row in enumerate(rows):
                points = np.column_stack((np.arange(x, x + w), np.full(w, row), np.ones(w)))
                expected = np.full(w, 255, np.uint8)
                mapped = np.zeros(w, bool)
                for record in line_records:
                    strip = record["strip_id"]
                    stage, page_stage = record["stages"]
                    spec = stage["pre_resample"]
                    key = (strip, tuple(spec["output_size"]), tuple(spec.get("crop_origin", [0, 0])))
                    if key not in cache:
                        raw = sources[strip]
                        dx, dy = spec.get("crop_origin", [0, 0])
                        sw, sh = spec["source_size"]
                        raw = raw[dy:dy + sh, dx:dx + sw]
                        interp = cv2.INTER_AREA if spec["interpolation"] == "area" else cv2.INTER_CUBIC
                        cache[key] = cv2.cvtColor(cv2.resize(render._to_page_paper(raw), tuple(spec["output_size"]), interpolation=interp), cv2.COLOR_BGR2GRAY)
                    raw = cache[key]
                    line_points = points @ np.linalg.inv(np.asarray(page_stage["matrix"])).T
                    for piece in stage["pieces"]:
                        q = line_points @ np.linalg.inv(np.asarray(piece["matrix"])).T
                        a, b, c, d = piece["src_bbox"]
                        own = (q[:, 0] >= a) & (q[:, 0] < c) & (q[:, 1] >= b) & (q[:, 1] < d)
                        cols = np.flatnonzero(own)
                        if len(cols):
                            cx, cy = np.rint(q[cols, :2]).astype(int).T
                            expected[cols] = np.minimum(expected[cols], raw[cy, cx])
                            mapped[cols] = True
                profile = 255 - gray[row, x:x + w]
                missing = profile < 64
                # Generated scaffolds must retain ink; only mapped raw paper
                # qualifies as a source gap, never an absent placement.
                source_gap = mapped & (255 - expected < 64)
                profiles.append({"line_id": lid, "staff_row": k, "row": row, "range": [first, last],
                                 "gaps": column_runs(missing[first:last]),
                                 "introduced_gaps": column_runs((missing & ~source_gap)[first:last])})
    return profiles


class StaffContinuity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def compose(self, mm, auto, *, source_gap=False):
        doc = Doc(self.root)
        sources = {}
        # Multiple strip joins and intra-strip cuts, all at nonintegral scales.
        for i in range(4):
            image, rec = measure_strip(5, time_sig=i == 0)
            if source_gap and i == 0:
                image[TOP - 2:TOP + 4 * G + 3, 565:572] = 252
            sid = f"s{i}"
            sources[sid] = image.copy()
            doc.add(sid, image, rec)
        start = time.perf_counter()
        plan, pages = doc.compose(measure_reflow=True, staff_gap_mm=mm, auto_staff_size=auto)
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        elapsed = time.perf_counter() - start
        return plan, pages, sources, elapsed

    def test_all_five_delivered_rows_fractional_scales_auto_off_and_on(self):
        for mm in (1.2, 1.5, 2.0):
            for auto in (False, True):
                with self.subTest(mm=mm, auto=auto):
                    plan, pages, sources, elapsed = self.compose(mm, auto)
                    profiles = staff_profiles(plan, pages, sources)
                    self.assertEqual(len(profiles), 5 * len(plan["measure_reflow"]["lines"]))
                    self.assertTrue(any(len(l["atom_ids"]) > 1 for l in plan["measure_reflow"]["lines"]))
                    self.assertTrue(any(abs(r["stages"][0]["pre_matrix"][0][0] - round(r["stages"][0]["pre_matrix"][0][0])) > .01
                                        for r in plan["measure_reflow"]["ledger_placements"]))
                    self.assertFalse([p for p in profiles if p["introduced_gaps"]], profiles)
                    # Each printed final barline stays a single contiguous
                    # stroke at its ledger-mapped destination, including joins.
                    for sid in sources:
                        found = []
                        point = np.array([[PREFIX + 5 * MW + .5, TOP + 2 * G, 1]])
                        for r in plan["measure_reflow"]["ledger_placements"]:
                            if r["strip_id"] != sid or r["copy_index"] != 0:
                                continue
                            identity = {"kind": "affine", "matrix": np.eye(3).tolist()}
                            q, valid = pipeline._review_page_points(point, [identity, *r["stages"]])
                            if valid[0]:
                                found.append((r, q[0]))
                        self.assertEqual(len(found), 1, sid)
                        r, q = found[0]
                        cx, cy = np.rint(q[:2]).astype(int)
                        pg = cv2.cvtColor(pages[r["page_index"]], cv2.COLOR_BGR2GRAY)
                        half = int(round(plan["staff_gap_px"] * 2)) - 2
                        vertical = np.mean(255 - pg[cy - half:cy + half, cx - 4:cx + 5] >= 64, axis=0) >= .85
                        self.assertEqual(len(column_runs(vertical)), 1, (sid, vertical.tolist()))
                    fragment = {k: plan["measure_reflow"][k] for k in ("ledger_placements", "ledger_removed", "generated_origins")}
                    size = len(json.dumps(fragment, separators=(",", ":")).encode())
                    print(f"\nSTAFF_CONTINUITY mm={mm} auto={auto} lines={len(profiles)//5} "
                          f"row_gaps={sum(len(p['gaps']) for p in profiles)} ledger_bytes={size} compose_seconds={elapsed:.6f}")

    def test_source_gap_is_permitted_but_new_output_paper_is_detected(self):
        plan, pages, sources, _ = self.compose(1.5, False, source_gap=True)
        profiles = staff_profiles(plan, pages, sources)
        self.assertTrue(any(p["gaps"] for p in profiles))
        self.assertFalse([p for p in profiles if p["introduced_gaps"]], profiles)
        broken = [p.copy() for p in pages]
        pl = plan["pages"][0]["placements"][0]
        first = profiles[0]
        col = pl["x"] + first["range"][0] + 5
        for profile in profiles[:5]:
            row = profile["row"]
            self.assertGreaterEqual(int(255 - broken[0][row, col, 0]), 64)
            broken[0][row, col] = 255
        bad = staff_profiles(plan, broken, sources)
        self.assertEqual(sum(bool(p["introduced_gaps"]) for p in bad), 5)

    def test_paper_tail_under_barline_influence_is_trimmed_without_erasing_ink(self):
        image = np.full((80, 40, 3), 255, np.uint8)
        for row in (12, 24, 36, 48, 60):
            image[row, :39] = 30
        image[12:61, 37:39] = 0
        # A dilated barline mask reaches the paper column, as at a fractional
        # source endpoint. The page mapping makes contrast <=3 white.
        image[:, 39] = 254
        nonstaff = np.zeros((80, 40), bool)
        nonstaff[10:63, 35:40] = True
        self.assertEqual(measure._tail_clear_columns(image, nonstaff, 0, 40), 1)
        # A gray dot anywhere in that column must stop the extra trim.
        image[70, 39] = 240
        self.assertEqual(measure._tail_clear_columns(image, nonstaff, 0, 40), 0)
        image[70, 39] = 254
        image[:, 38] = 254
        self.assertEqual(measure._tail_clear_columns(image, nonstaff, 0, 40), 2)

    def test_paper_tail_join_has_exact_removed_domain_and_one_barline(self):
        image = np.full((80, 40, 3), 255, np.uint8)
        ys = [12, 24, 36, 48, 60]
        for row in ys:
            image[row, :39] = 30
        image[12:61, 37:39] = 0
        image[:, 39] = 254
        mask = np.zeros((80, 40), bool)
        mask[10:63, 35:40] = True
        tail = measure._tail_clear_columns(image, mask, 0, 40)
        second = image.copy()
        for row in ys:
            second[row, 39] = 30
        strips = {sid: {"image": im, "nonstaff_out": mask, "top_out": 12., "scale": 1.,
                        "source_strip_id": sid, "pre_crop": [0, 0], "resample_source_size": [40, 80],
                        "record": {"staff_y_strip": ys}, "staff_rows_R": ys}
                  for sid, im in (("a", image), ("b", second))}
        atoms = [{"id": sid, "unit_id": sid, "system_id": sid, "kind": "measure", "cols_out": [0, 40],
                  "rows_out": [0, 80], "break_before": "system_start", "gaps": []} for sid in ("a", "b")]
        atoms[1]["join"] = {"mode": "prefix_free", "prev_tail_trim": tail}
        lines = {"slots": [], "lines": [{"id": "line", "atom_ids": ["a", "b"], "achieved_width": 80 - tail, "replica_width": 0}]}
        images, fragment = measure.render_lines(atoms, strips, lines, target_gap_px=12.)
        line = images["line"]
        self.assertTrue((255 - line[ys, :, 0] >= 64).all())
        vertical = np.mean(255 - line[14:59, :, 0] >= 64, axis=0) >= .85
        self.assertEqual(column_runs(vertical), [[37, 39], [76, 78]])
        removed = fragment["ledger_removed"]
        self.assertEqual(removed, [{"strip_id": "a", "src_bbox_R": [39, 0, 40, 80],
                                   "op": "remove_scaffold_columns", "line_id": "line", "reason": "join_tail"}])
        self.assertFalse(fragment["scaffold_operations"][0]["nonstaff_ink_removed"])
        stage = fragment["ledger_placements"][0]["stages"][0]
        self.assertEqual(stage["pre_resample"]["output_size"], [40, 80])
        self.assertEqual(stage["pieces"][0]["src_bbox"], [0, 0, 39, 80])
        self.assertEqual(fragment["placements"][1]["x_out"], 39)
        self.assertEqual(fragment["render_mismatched_px"], 0)
        self.assertEqual(fragment["generated_origins"], [])

    def test_contraction_page_is_continuous_when_native_review_grid_has_holes(self):
        # Removing a source column closes the actual line. Sampling it back on
        # the old source grid has no destination for that column.
        image, rec = measure_strip(4, time_sig=True)
        doc = Doc(self.root)
        doc.add("s", image, rec)
        decided, _ = pipeline.resolve_dependencies(doc.systems)
        built, lines = measure._plan_at(decided, 1.5, context=doc.context, locks=[], job_id="staff", revision=0, doc_cache={})
        by_id = {a["id"]: a for a in built["atoms"]}
        line = lines["lines"][0]
        atom = next(by_id[a] for a in line["atom_ids"] if by_id[a].get("gaps"))
        gap = atom["gaps"][0]
        slot = next(s for s in lines["slots"] if s["id"] == gap["id"])
        line["achieved_width"] -= int(slot["applied_delta"]) + 2
        slot["applied_delta"] = -2
        images, fragment = measure.render_lines(built["atoms"], built["strips"], lines, target_gap_px=1.5 * 300 / 25.4)
        pl = next(p for p in fragment["placements"] if p["unit_id"] == atom["unit_id"])
        removed = pl["removed_cols_out"]
        self.assertTrue(removed)
        stage = next(r["stages"][0] for r in fragment["ledger_placements"] if r["line_id"] == line["id"])
        yy = float(rec["staff_y_strip"][2])
        inv = np.linalg.inv(np.asarray(stage["pre_matrix"]))
        points = np.array([[c + .25, yy * stage["pre_matrix"][1][1] + stage["pre_matrix"][1][2], 1] for c in removed]) @ inv.T
        identity = {"kind": "affine", "matrix": np.eye(3).tolist()}
        _q, valid = pipeline._review_page_points(points, [identity, stage, identity])
        self.assertFalse(valid.any())
        # All actual output columns still carry the middle staff row.
        raster = images[line["id"]]
        centre = int(round(yy * stage["pre_matrix"][1][1] + stage["pre_matrix"][1][2])) - pl["rows_src_out"][0] + pl["y_out"]
        row = max(range(centre - 1, centre + 2),
                  key=lambda r: np.median(255 - raster[r, :, 0]))
        middle = 255 - raster[row, pl["x_out"]:pl["x_out"] + pl["width_out"], 0]
        self.assertTrue((middle >= 64).all())
