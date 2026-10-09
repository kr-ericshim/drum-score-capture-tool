"""Stage B controls; synthetic fixtures do not claim packaged/media verification."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_verify_common as vc
from app.pipeline import reflow_verify_plan as vb
from app.pipeline import reflow_pipeline as pipeline
from app.pipeline.reflow_ledger import pack_crop
import test_ledger_integration_pipeline as fixtures
import test_ledger_measure_e2e as measure_fixtures


def certificates(images):
    return {sid: {"strip_id": sid, "strip_sha256": vc.pixels_sha256(im),
                  "features": [vc.feature_record(f, supporters=["o0", "o1"], contradicts=[])
                               for f in vc.strip_features(vc.contrast_map(im))], "findings": []}
            for sid, im in images.items()}


class VerifyPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def compose(self, *, measure=False, large=False, mm=1.5, staff_only=False):
        context = None
        if large:
            helper = measure_fixtures.LedgerMeasureE2E()
            helper.root = self.root
            record, context = helper.large_native_fixture()
        else:
            record = fixtures.fixture(self.root/"source")
        if staff_only:
            # Retain the imported fixture's native dimensions and staff geometry.
            # Its beams otherwise produce undeclared column_repeat placements,
            # which are tested as destructive duplicates separately below.
            for system in record["systems"]:
                im = cv2.imread(system["strip_path"])
                im[:] = 255
                left,right = map(int,system["strip"]["staff_x_strip"])
                for y in system["strip"]["staff_y_strip"]:
                    im[int(round(y)),left+1:right-1] = 0
                cv2.imwrite(system["strip_path"],im)
        sink = {}
        plan, _ = pipeline.compose_systems(record["systems"], workspace=Path(record["workspace"]),
            all_systems=record["systems"], ledger_sink=sink, measure_reflow=measure,
            measure_context=context, staff_gap_mm=mm)
        images = {s["id"]: cv2.imread(s["strip_path"]) for s in record["systems"]}
        return certificates(images), plan, sink, images, record["systems"]

    def run_plan(self, data):
        ca, plan, sink, images, systems = data
        return vb.verify_plan(ca, plan, sink, images, systems=systems)

    def codes(self, report):
        return {f["code"] for f in report["findings"]}

    def basic(self, *, removal=False, dot=False, attached=False):
        image = np.full((100,200,3), 255, np.uint8)
        for y in (20,32,44,56,68):
            image[y, :] = 0
        if dot:
            if attached:
                cv2.circle(image, (90,44), 2, (0,0,0), -1)
            else:
                image[78:81,89:92] = 0
        sid = "s"
        page = {"index": 1, "placements": [{"system_id":"l", "line_id":"l", "x":177,"y":165,"w":300,"h":150}]}
        plan = {"page_px":[2480,3508], "dpi":300,
                "margins_px":{"left":177,"right":177,"top":165,"bottom":165}, "pages":[page]}
        pieces = [{"src_bbox":[0,0,200,100], "matrix":np.eye(3).tolist()}]
        if removal:
            pieces = [{"src_bbox":[0,0,89,100], "matrix":np.eye(3).tolist()},
                      {"src_bbox":[92,0,200,100], "matrix":[[1,0,-3],[0,1,0],[0,0,1]]}]
        rec = {"strip_id":sid,"line_id":"l","page_index":0,"copy_index":0,
               "stages":[{"stage":"strip_to_line","kind":"piecewise","pre_matrix":np.eye(3).tolist(),
                          "pre_resample":{"source_size":[200,100],"output_size":[200,100],"interpolation":"cubic"},
                          "pieces":pieces},
                         {"stage":"line_to_page","kind":"affine",
                          "resample":{"source_size":[200,100],"output_size":[300,150],"interpolation":"cubic"},
                          "matrix":[[1.5,0,177.25],[0,1.5,165.25],[0,0,1]]}]}
        sink = {"placements":[rec],"removed":[],"decided_system_ids":[sid],"excluded_system_ids":[]}
        if removal:
            sink["removed"] = [{"strip_id":sid,"line_id":"l","src_bbox_R":[89,0,92,100],"op":"remove_spread_columns"}]
        images = {sid:image}
        return certificates(images), plan, sink, images, [{"id":sid,"included":True}]

    def test_clean_whole_system_plan_from_pipeline(self):
        data = self.compose()
        report = self.run_plan(data)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["counters"]["duplicated_pixels"], 0)
        self.assertEqual(report["plan_sha256"], vc.json_sha256(vb.plan_records(data[1],data[2])))
        json.dumps(report, allow_nan=False)

    def test_clean_measure_plan_from_pipeline(self):
        data = self.compose(measure=True)
        report = self.run_plan(data)
        self.assertEqual(report["findings"], [])
        self.assertTrue(report["staff_models"]["sys-001"]["removal_footprints"])

    def test_clean_measure_area_shrink_at_floor(self):
        data = self.compose(measure=True, large=True, mm=1.2, staff_only=True)
        report = self.run_plan(data)
        self.assertEqual(report["findings"], [])

    def test_area_fixture_beam_columns_without_replica_roles_fail(self):
        data = self.compose(measure=True, large=True, mm=1.2)
        report = self.run_plan(data)
        self.assertIn("DUPLICATED_CONTENT",self.codes(report))
        self.assertTrue(any(p["stages"][0]["pieces"][0].get("column_repeat",1)>1
                            for p in data[2]["placements"] if p["copy_index"]>0))

    def test_removed_spread_dot_fails(self):
        report = self.run_plan(self.basic(removal=True,dot=True))
        self.assertIn("REMOVED_FEATURE", self.codes(report))
        self.assertTrue(any(f["code"]=="REMOVED_FEATURE" and f["severity"]=="fail" for f in report["findings"]))

    def test_removed_staff_only_column_passes(self):
        self.assertEqual(self.run_plan(self.basic(removal=True))["findings"], [])

    def test_removed_dot_touching_staff_line_fails_locally(self):
        report = self.run_plan(self.basic(removal=True,dot=True,attached=True))
        bad = [f for f in report["findings"] if f["code"]=="REMOVED_FEATURE" and f["severity"]=="fail"]
        self.assertTrue(bad,report["findings"])
        self.assertTrue(any(f["bbox"][0] <= 90 < f["bbox"][2] and f["bbox"][1] <= 44 < f["bbox"][3] for f in bad))
        self.assertTrue(all(f["feature_ids"] for f in bad))

    def test_same_interval_twice_is_duplicate_even_with_new_copy_index(self):
        data = self.basic()
        extra = copy.deepcopy(data[2]["placements"][0]); extra["copy_index"] = 3
        data[2]["placements"].append(extra)
        report = self.run_plan(data)
        self.assertIn("DUPLICATED_CONTENT", self.codes(report))
        self.assertIn("PLAN_INVALID", self.codes(report))

    def test_kernel_reads_across_cut_do_not_duplicate_centres(self):
        data = self.basic()
        stage = data[2]["placements"][0]["stages"][0]
        stage["pre_matrix"] = [[.8,0,-.1],[0,.8,-.1],[0,0,1]]
        stage["pre_resample"]["output_size"] = [160,80]
        stage["pieces"] = [{"src_bbox":[0,0,80,80],"matrix":np.eye(3).tolist()},
                           {"src_bbox":[80,0,160,80],"matrix":np.eye(3).tolist()}]
        last = data[2]["placements"][0]["stages"][1]
        last["resample"]["source_size"] = [160,80]
        last["matrix"] = [[1.875,0,177.4375],[0,1.875,165.4375],[0,0,1]]
        report = self.run_plan(data)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["counters"]["owned_pixels"], 20000)

    def test_cut_must_match_recorded_safe_boundary(self):
        data = self.basic()
        data[1]["measure_reflow"] = {"boundaries":[{"id":"b","system_id":"s","seam_x":100,"class":"UNKNOWN","is_cut":False}],
            "units":[{"id":"u0","system_id":"s","box":[0,0,100,100],"right_boundary_id":"b"},
                     {"id":"u1","system_id":"s","box":[100,0,200,100],"left_boundary_id":"b"}],
            "lines":[{"id":"l","atom_ids":["u0","u1"]}]}
        report = self.run_plan(data)
        self.assertIn("PLAN_INVALID",self.codes(report))
        self.assertTrue(any(f["detail"]["reason"]=="unit cut is not at a recorded SAFE boundary" for f in report["findings"]))

    def test_swapped_piece_list_fails(self):
        data = self.basic(removal=True)
        data[2]["placements"][0]["stages"][0]["pieces"].reverse()
        report = self.run_plan(data)
        self.assertIn("PLAN_INVALID", self.codes(report))
        self.assertTrue(any(f["detail"]["reason"]=="piece column order reversed" for f in report["findings"]))

    def test_swapped_piece_destinations_fail(self):
        data = self.basic()
        data[2]["placements"][0]["stages"][0]["pieces"] = [
            {"src_bbox":[0,0,100,100],"matrix":[[1,0,100],[0,1,0],[0,0,1]]},
            {"src_bbox":[100,0,200,100],"matrix":[[1,0,-100],[0,1,0],[0,0,1]]}]
        self.assertIn("PLAN_INVALID", self.codes(self.run_plan(data)))

    def test_piece_vertical_shift_fails_even_inside_line_canvas(self):
        data = self.basic()
        data[1]["pages"][0]["placements"][0]["h"] = 156
        rec = data[2]["placements"][0]
        rec["stages"][1]["resample"].update(source_size=[200,104],output_size=[300,156])
        rec["stages"][0]["pieces"] = [
            {"src_bbox":[0,0,100,100],"matrix":np.eye(3).tolist()},
            {"src_bbox":[100,0,200,100],"matrix":[[1,0,0],[0,1,2],[0,0,1]]}]
        report = self.run_plan(data)
        self.assertTrue(any(f["code"]=="PLAN_INVALID" and
                            f["detail"]["reason"]=="pieces of one strip have different vertical mappings within line"
                            for f in report["findings"]))

    def test_safe_unit_metadata_does_not_certify_different_actual_cut(self):
        data = self.basic()
        data[1]["measure_reflow"] = {"boundaries":[{"id":"b","system_id":"s","seam_x":100,"class":"SAFE","is_cut":True}],
            "units":[{"id":"u0","system_id":"s","box":[0,0,100,100],"right_boundary_id":"b"},
                     {"id":"u1","system_id":"s","box":[100,0,200,100],"left_boundary_id":"b"}],
            "lines":[{"id":"l","atom_ids":["u0"]},{"id":"next","atom_ids":["u1"]}]}
        # Actual ownership of the first line still extends to 200, despite the
        # metadata claiming its SAFE unit ends at 100.
        report = self.run_plan(data)
        self.assertTrue(any(f["code"]=="PLAN_INVALID" and
                            f["detail"]["reason"]=="piece ownership disagrees with SAFE unit placement"
                            for f in report["findings"]))

    def test_strip_tampering_refuses_artifact(self):
        data = self.basic(dot=True)
        data[3]["s"][78:81,89:92] = 255
        report = self.run_plan(data)
        self.assertEqual(self.codes(report),{"ARTIFACT_MISMATCH"})
        self.assertEqual(report["instances"], [])

    def test_tampered_certA_features_cannot_drop_delivery_obligations(self):
        data = self.basic(dot=True,attached=True)
        data[0]["s"]["features"] = []
        report = self.run_plan(data)
        self.assertIn("ARTIFACT_MISMATCH",self.codes(report))
        self.assertEqual(report["instances"], [])

    def test_resample_metadata_tampering_fails(self):
        data = self.basic()
        data[2]["placements"][0]["stages"][0]["pre_matrix"][0][2] += 2
        self.assertIn("PLAN_INVALID", self.codes(self.run_plan(data)))

    def test_plan_digest_binds_removal_placement_and_safe_boundary(self):
        data = self.basic(removal=True)
        original = self.run_plan(data)["plan_sha256"]
        altered = copy.deepcopy(data)
        altered[2]["removed"][0]["src_bbox_R"][0] += 1
        self.assertNotEqual(original,self.run_plan(altered)["plan_sha256"])
        altered = copy.deepcopy(data)
        altered[2]["placements"][0]["stages"][0]["pieces"][0]["matrix"][0][2] += 2
        self.assertNotEqual(original,self.run_plan(altered)["plan_sha256"])
        altered = copy.deepcopy(data)
        altered[1]["measure_reflow"] = {"boundaries":[{"id":"b","class":"SAFE"}]}
        self.assertNotEqual(original,self.run_plan(altered)["plan_sha256"])

    def test_missing_internal_column_and_missing_system_fail(self):
        data = self.basic(removal=True)
        data[2]["removed"] = []
        self.assertIn("PLAN_INVALID",self.codes(self.run_plan(data)))
        data = self.basic()
        data[2]["placements"] = []
        self.assertIn("PLAN_INVALID",self.codes(self.run_plan(data)))

    def test_page_bounds_floor_and_glyph_stretch_fail(self):
        for kind in ("bounds","floor","stretch"):
            with self.subTest(kind=kind):
                data = self.basic()
                if kind=="bounds":
                    data[1]["pages"][0]["placements"][0]["x"] = 0
                elif kind=="floor":
                    pl = data[1]["pages"][0]["placements"][0]
                    pl.update(w=200,h=100)
                    last = data[2]["placements"][0]["stages"][1]
                    last["resample"]["output_size"] = [200,100]
                    last["matrix"] = [[1,0,177],[0,1,165],[0,0,1]]
                else:
                    data[2]["placements"][0]["stages"][0]["pieces"][0]["matrix"][0][0] = 1.1
                self.assertIn("PLAN_INVALID",self.codes(self.run_plan(data)))

    def test_declared_scaffold_replica_requires_exact_footprint(self):
        data = self.basic()
        rec = copy.deepcopy(data[2]["placements"][0])
        rec.update(copy_index=1,replica_role="scaffold",source_footprint=[0,0,1,100])
        stage = rec["stages"][0]
        stage["pieces"] = [{"src_bbox":[0,0,1,100],"matrix":[[1,0,200],[0,1,0],[0,0,1]]}]
        # Extend the line canvas to make the authorised replica disjoint.
        data[1]["pages"][0]["placements"][0].update(w=303,h=150)
        for r in (data[2]["placements"][0],rec):
            r["stages"][1]["resample"].update(source_size=[202,100],output_size=[303,150])
        data[2]["placements"].append(rec)
        report = self.run_plan(data)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["instances"][-1]["replica_role"],"scaffold")
        rec["source_footprint"] = [0,0,2,100]
        self.assertIn("DUPLICATED_CONTENT",self.codes(self.run_plan(data)))

    def test_removal_replica_exception_needs_verified_replacement(self):
        data = self.basic(removal=True,dot=True)
        data[2]["removed"][0]["replica_role"] = "clef"
        self.assertTrue(any(f["code"]=="REMOVED_FEATURE" and f["severity"]=="fail"
                            for f in self.run_plan(data)["findings"]))
        rec = copy.deepcopy(data[2]["placements"][0])
        rec.update(copy_index=1,replica_role="clef",source_footprint=[89,0,92,100])
        rec["stages"][0]["pieces"] = [{"src_bbox":[89,0,92,100],"matrix":[[1,0,108],[0,1,0],[0,0,1]]}]
        data[2]["placements"].append(rec)
        report = self.run_plan(data)
        self.assertTrue(any(f["code"]=="REMOVED_FEATURE" and f["severity"]=="review_required" for f in report["findings"]))
        self.assertFalse([f for f in report["findings"] if f["severity"]=="fail"],report["findings"])

    def test_generated_evidence_tampering_fails(self):
        data = self.basic()
        patch = np.zeros((3,3,3),np.uint8)
        origin = {"kind":"header", "page_index":0, "origin":[200,40], "template":pack_crop(patch),
                  "inputs":{"text":"fixture"}, "generator":"fixture"}
        data[2]["generated_origins"] = [origin]
        self.assertEqual(self.run_plan(data)["findings"], [])
        origin["template"]["sha256"] = "0"*64
        self.assertIn("ARTIFACT_MISMATCH",self.codes(self.run_plan(data)))

    def test_generated_draw_overlap_fails(self):
        data = self.basic()
        data[2]["generated_origins"] = [{"kind":"header", "page_index":0,"origin":[200,180],
                                         "template":pack_crop(np.zeros((3,3,3),np.uint8))}]
        report = self.run_plan(data)
        self.assertTrue(any(f["code"]=="PLAN_INVALID" and
                            f["detail"]["reason"]=="draw-order overlap can hide owned content"
                            for f in report["findings"]))

    def test_generated_scaffold_does_not_authorise_staff_attached_dot(self):
        data = self.basic(dot=True,attached=True)
        data[2]["generated_origins"] = [{"kind":"staff_scaffold", "strip_id":"s", "page_index":0,
            "origin":[200,40],"template":pack_crop(np.full((100,3,3),255,np.uint8)),
            "source_resample":{"source_size":[200,100],"output_size":[200,100],"interpolation":"cubic"},
            "source_column_R":90}]
        report = self.run_plan(data)
        self.assertTrue(any(f["code"]=="PLAN_INVALID" and
                            f["detail"]["reason"]=="generated scaffold replicates non-scaffold source"
                            for f in report["findings"]))

    def test_independent_staff_fit_handles_fractional_row_spacing(self):
        image = np.full((150,300),255,np.uint8)
        for y in (20,40,61,81,102):
            image[y,:] = 0
        _scaffold,model = vb._staff_model(vc.contrast_map(image))
        self.assertEqual(model["rows"],[20.,40.,61.,81.,102.])
        self.assertLessEqual(model["gap_range_px"][0],20.5)
        self.assertGreaterEqual(model["gap_range_px"][1],20.5)

    def test_certificate_is_snapshot_and_inputs_unchanged(self):
        data = self.basic(removal=True)
        original = copy.deepcopy(data)
        report = self.run_plan(data)
        self.assertEqual(data[0],original[0]);self.assertEqual(data[1],original[1]);self.assertEqual(data[2],original[2])
        data[2]["placements"][0]["stages"][0]["pieces"][0]["matrix"][0][2] += 4
        self.assertEqual(report["plan_sha256"],vc.json_sha256(report["plan_records"]))

    def test_measure_certificate_runtime_and_json_size(self):
        data = self.compose(measure=True)
        start = time.perf_counter()
        report = self.run_plan(data)
        elapsed = time.perf_counter()-start
        size = len(json.dumps(report,separators=(",",":")).encode())
        print(f"VERIFY_PLAN fixture_seconds={elapsed:.6f} certB_bytes={size}")
        self.assertLess(elapsed,3.)
        self.assertEqual(report["findings"], [])


if __name__ == "__main__":
    unittest.main()
