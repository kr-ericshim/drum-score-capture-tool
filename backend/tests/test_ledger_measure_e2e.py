"""Measure source -> staged PDF controls, including exact resampling and provenance."""
import copy
import json
import os
import tempfile
import time
import unittest
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_ledger as rl, reflow_pipeline as pipeline
from app.pipeline import reflow_ledger_assembly as assembly
from app.pipeline.export import export_composed_pages
import test_ledger_integration_pipeline as fixtures
from test_reflow_measure import Doc, measure_strip
from test_ledger_v2_verify import lossless_legacy_verify_pdf



RETIRED_VERIFIER = "Retired raw-projection verifier (DECISIONS 2026-10-09 staged verification): not in the product path; its loss/tamper controls live in test_verify_* now."

class LedgerMeasureE2E(unittest.TestCase):
    def setUp(self):
        legacy = patch.object(rl, "verify_pdf", side_effect=lossless_legacy_verify_pdf)
        legacy.start()
        self.addCleanup(legacy.stop)
        debug = os.environ.get("WD_LEDGER_DEBUG_ROOT")
        if debug:
            self.root = Path(tempfile.mkdtemp(prefix=f"{self._testMethodName}-", dir=debug))
        else:
            self.tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self.tmp.cleanup)
            self.root = Path(self.tmp.name)

    def compose(self, record, auto, context=None, *, staff_gap_mm=1.5):
        sink = {}
        plan, pages = pipeline.compose_systems(record["systems"], workspace=Path(record["workspace"]),
            all_systems=record["systems"], ledger_sink=sink, measure_reflow=True,
            auto_staff_size=auto, measure_context=context, staff_gap_mm=staff_gap_mm)
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        self.assertTrue(sink["placements"])
        return plan, pages, sink

    def verify(self, record, sink, name):
        staged = self.root / name
        exported = export_composed_pages(pages=sink["pages"], formats=["pdf", "png"], workspace=staged, logger=lambda _m: None)
        start = time.perf_counter()
        report = pipeline.verify_delivered_ledger(record, exported["pdf"], staged, sink=sink)
        elapsed = time.perf_counter()-start
        ledger = json.loads((staged / "ledger.json").read_text())
        print(f"\nMEASURE_E2E case={name} status={report['status']} ledger_bytes={(staged/'ledger.json').stat().st_size} "
              f"verify_seconds={elapsed:.6f} counts={dict(Counter(i['code'] for i in report['issues']))}")
        return report, ledger, Path(exported["pdf"])

    def large_native_fixture(self, *, name="large-native"):
        root = self.root / name
        root.mkdir()
        image, rec = measure_strip(2, time_sig=True)
        image = cv2.resize(image, (image.shape[1]*2, image.shape[0]*2), interpolation=cv2.INTER_NEAREST)
        rec.update(staff_y_strip=[y*2+.5 for y in rec["staff_y_strip"]], staff_gap_px=rec["staff_gap_px"]*2,
                   staff_x_strip=[rec["staff_x_strip"][0]*2, rec["staff_x_strip"][1]*2+1],
                   size=[image.shape[1],image.shape[0]], box_crop=[0,0,image.shape[1],image.shape[0]])
        doc = Doc(root)
        system = doc.add("native", image, rec, register=False)
        observations, members = [], []
        for k in range(3):
            oid = f"native-{k}"
            path = root / f"{oid}.png"
            cv2.imwrite(str(path), image)
            observations.append({"id":oid, "t_sec":float(k), "sample_kind":"coarse", "frame_path":str(path),
                                 "system_regions":[{}], "source_to_crop":np.eye(3).tolist()})
            members.append({"id":oid, "timestamp":float(k), "image":image, "roi_origin":[0,0],
                            "registration_shift":[0,0], "registration_uncertainty":0.,
                            "frame_ref":{"observation_id":oid, "crop_box":[0,0,image.shape[1],image.shape[0]]}})
        inventory = assembly.inventory_observations({"observations":observations}, root, source_video="synthetic")
        fragment = rl.record_obligations(source_video="synthetic", display_id="strip:native", occurrence_id="native",
                                        members=members, evidence_dir=root/"ledger_evidence")
        base = assembly.merge_ledgers(inventory, fragment)
        assembly.annotate(base, [{"obs_id":o["id"], "stage":"composition", "role":"used", "display_id":"strip:native",
                                 "occurrence_id":"native", "reason":None} for o in observations])
        chain = {"display_id":"strip:native", "strip_id":"native",
                 "stages":[{"stage":"display_to_strip", "kind":"affine", "matrix":np.eye(3).tolist()}]}
        rl.write_ledger(root/"ledger_base.json", base)
        (root/"ledger_chains.json").write_text(json.dumps({"native": [chain]}))
        return {"workspace":str(root), "ledger_base_path":str(root/"ledger_base.json"), "systems":[system]}, doc.context

    def test_clean_measure_pdf_pass_auto_off_and_on(self):
        for auto in (False, True):
            with self.subTest(auto=auto):
                record = fixtures.fixture(self.root / f"clean-{auto}")
                _plan, _pages, sink = self.compose(record, auto)
                report, ledger, pdf = self.verify(record, sink, f"clean-export-{auto}")
                self.assertEqual(report["status"], "pass", report["issues"])
                self.assertEqual(rl.verify_pdf(ledger, pdf)["status"], "pass")
                self.assertTrue(any(r["transforms"][1].get("pre_resample") for r in ledger["representations"]))

    def test_assembly_projection_errors_become_verifier_findings(self):
        record = fixtures.fixture(self.root / "assembly-errors")
        _plan, _pages, sink = self.compose(record, False)
        for error, code, status in ((rl.TransformLossError("owned ink missing"),
                "TRANSFORM_DROPS_OR_DUPLICATES_FOREGROUND", "fail"),
                (ValueError("unknown resize"), "TRANSFORM_UNRESOLVED", "review_required")):
            with self.subTest(error=type(error).__name__), patch.object(assembly, "_check_projection", side_effect=error):
                ledger = pipeline.build_delivered_ledger(record, sink)
            self.assertTrue(ledger["representations"])
            self.assertTrue(all(r.get("projection_error") for r in ledger["representations"]))
            report = rl.verify_pages(ledger, sink["pages"])
            self.assertEqual(report["status"], status, report["issues"])
            self.assertIn(code, {i["code"] for i in report["issues"]})

    def test_export_B_C_errors_are_unassessed_without_pipeline_error(self):
        from test_reflow_review_export import ReflowJobFlowTest
        for target in ("app.pipeline.reflow_verify_plan.verify_plan",
                       "app.pipeline.reflow_verify_page.verify_pages"):
            with self.subTest(target=target):
                flow = ReflowJobFlowTest(); flow.setUp(); self.addCleanup(flow.tearDown)
                record = fixtures.fixture(flow.ws)
                with patch(target, side_effect=RuntimeError("injected verifier failure")), \
                        self.assertLogs(level="ERROR"):
                    job = flow.run_job(record, lambda *_a, **_kw: [], export={"formats": ["pdf"]}, measure_reflow=True)
                self.assertEqual(job.status, fixtures.JobStatus.DONE)
                self.assertIsNone(job.error_code)
                self.assertEqual(job.result["reflow_state"], "review_required")
                self.assertFalse(job.result["images"])  # this fixture requests PDF only
                self.assertTrue(Path(job.result["pdf"]).is_file())
                self.assertEqual(job.result["reflow"]["ledger_summary"]["status"], "unassessed")
                self.assertEqual(job.result["reflow"]["ledger_summary"]["issue_counts"],
                                 {"VERIFICATION_UNASSESSED": 2 if target.endswith("verify_plan") else 1})
                report = json.loads(Path(job.result["reflow"]["ledger_attempt_path"]).read_text())
                self.assertEqual(report["status"], "unassessed")
                self.assertEqual(report["issues"][0]["detail"]["exception_type"], "RuntimeError")
                self.assertEqual(report["issues"][0]["detail"]["reason"], "injected verifier failure")
                self.assertFalse(fixtures.main._ledger_failure_pending(job))
                self.assertTrue(Path(record["ledger_base_path"]).is_file())

    @unittest.skip(RETIRED_VERIFIER)

    def test_sub_floor_partition_child_is_proven_without_page_obligation(self):
        image = np.full((24,24,3), 255, np.uint8)
        image[4:6,4:6] = 0
        image[14,14] = 243
        members = [{"id": "fringe", "timestamp": 0., "image": image, "roi_origin": [0,0],
                    "registration_shift": [0,0], "registration_uncertainty": 0.}]
        ledger = rl.record_obligations(source_video="synthetic", display_id="d", occurrence_id="o",
                                      members=members, candidates=[[2,2,17,17]])
        ledger["observations"] = [{"id": "fringe", "terminal": None, "staff_regions": 1,
            "pixels_sha256": rl.pixels_hash(image), "associations": [{"stage": "composition", "role": "used",
            "display_id": "d", "occurrence_id": "o"}]}]
        chain = {"display_id": "d", "strip_id": "s", "stages": [{"stage": "display_to_strip", "kind": "affine",
                                                                      "matrix": np.eye(3).tolist()}]}
        placements = []
        for a, b, y in ((0,3,10), (3,6,20)):
            placements.append({"strip_id": "s", "copy_index": 0, "page_index": 0, "line_id": f"l-{a}",
                "stages": [{"stage": "strip_to_line", "kind": "piecewise", "pre_matrix": [[.25,0,-.375],[0,.25,-.375],[0,0,1]],
                    "pre_resample": {"source_size": [24,24], "output_size": [6,6], "interpolation": "area"},
                    "pieces": [{"src_bbox": [a,0,b,6], "matrix": [[1,0,-a],[0,1,0],[0,0,1]]}]},
                    {"stage": "line_to_page", "kind": "affine", "matrix": [[1,0,10],[0,1,y],[0,0,1]]}]})
        assembly.assemble_representations(ledger, [chain], placements)
        assembly.finalize_terminals(ledger)
        proof = next(r for r in ledger["representations"] if r.get("below_contrast_floor"))
        self.assertEqual(proof["below_contrast_floor"]["source_max_contrast"], 12)
        self.assertLess(proof["below_contrast_floor"]["delivered_max_contrast"], 8)
        parent = ledger["items"][0]
        self.assertEqual(len(parent["partitioned_into"]), 2)
        page = np.full((40,40,3), 255, np.uint8)
        resized = cv2.resize(image, (6,6), interpolation=cv2.INTER_AREA)
        page[10:16,10:13] = resized[:,:3]
        page[20:26,10:13] = resized[:,3:]
        report = rl.verify_pages(ledger, [page])
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertTrue(any(m.get("kind") == "below_contrast_floor" for m in report["matches"]))
        bad = copy.deepcopy(ledger)
        child = next(i for i in bad["items"] if i["id"] == proof["item_id"])
        c = rl.unpack_crop(child["expected_contrast"]); c[rl.unpack_crop(child["foreground_hypothesis"])>0] = 64
        child["expected_contrast"] = rl.pack_crop(c)
        self.assertIsNone(rl.below_contrast_floor(child, proof["transforms"]))
        bad_report = rl.verify_pages(bad, [page])
        self.assertEqual(bad_report["status"], "fail")
        raw_clear = copy.deepcopy(next(i for i in ledger["items"] if i["id"] == proof["item_id"]))
        view = raw_clear["evidence"][0]
        raw = rl.unpack_crop(view["raw_patch"]); raw[:] = 191
        view["raw_patch"] = rl.pack_crop(raw)
        self.assertIsNone(rl.below_contrast_floor(raw_clear, proof["transforms"]))

    def test_referenced_batch_preserves_every_view_and_reduces_frame_decodes(self):
        record = fixtures.fixture(self.root / "batched-views")
        ledger = json.loads(Path(record["ledger_base_path"]).read_text())
        items = ledger["items"][:32]
        plain, batched = rl.EvidenceResolver(ledger), rl.EvidenceResolver(ledger)
        with patch.object(cv2, "imdecode", wraps=cv2.imdecode) as decode:
            expected = {i["id"]: list(plain.views(i)) for i in items}
            plain_decodes = decode.call_count
        with patch.object(cv2, "imdecode", wraps=cv2.imdecode) as decode:
            batched.prefetch(items)
            actual = {i["id"]: list(batched.views(i)) for i in items}
            batch_decodes = decode.call_count
        self.assertEqual(actual, expected)
        self.assertLess(batch_decodes, plain_decodes)
        self.assertLessEqual(len(batched.cache), 3)
        print(f"REFERENCED_BATCH items={len(items)} ordinary_decodes={plain_decodes} batch_decodes={batch_decodes}")

    @unittest.skip(RETIRED_VERIFIER)

    def test_strong_two_pixel_dot_at_staff_floor_passes_and_erasure_fails(self):
        for erased in (False, True):
            with self.subTest(erased=erased):
                record, context = self.large_native_fixture(name=f"tiny-dot-source-{erased}")
                system = record["systems"][0]
                image = cv2.imread(system["strip_path"])
                image[400:402,500:502] = 0
                # The same raw dot belongs to every immutable observation.
                base = json.loads(Path(record["ledger_base_path"]).read_text())
                for obs in base["observations"]:
                    frame = cv2.imread(obs["frame_path"]); frame[400:402,500:502] = 0
                    cv2.imwrite(obs["frame_path"], frame)
                root = Path(record["workspace"])
                members = [{"id": o["id"], "timestamp": o["t_sec"], "image": image, "roi_origin": [0,0],
                    "registration_shift": [0,0], "registration_uncertainty": 0.,
                    "frame_ref": {"observation_id": o["id"], "crop_box": [0,0,image.shape[1],image.shape[0]]}}
                    for o in base["observations"]]
                inventory = assembly.inventory_observations({"observations": base["observations"]}, root, source_video="synthetic")
                fragment = rl.record_obligations(source_video="synthetic", display_id="strip:native", occurrence_id="native",
                    members=members, evidence_dir=root/"ledger_evidence")
                fresh = assembly.merge_ledgers(inventory, fragment)
                assembly.annotate(fresh, [{"obs_id":o["id"], "stage":"composition", "role":"used", "display_id":"strip:native",
                    "occurrence_id":"native", "reason":None} for o in base["observations"]])
                rl.write_ledger(root/"ledger_base.json", fresh)
                if erased:
                    image[400:402,500:502] = 255
                cv2.imwrite(system["strip_path"], image)
                _plan, _pages, sink = self.compose(record, False, context, staff_gap_mm=1.2)
                report, _ledger, _pdf = self.verify(record, sink, f"tiny-dot-{erased}")
                self.assertEqual(report["status"], "fail" if erased else "pass", report["issues"])
                if erased:
                    self.assertIn("SOURCE_FOREGROUND_MISSING_OR_CHANGED", {i["code"] for i in report["issues"]})

    def test_written_strip_dot_erasure_fails_auto_off_and_on(self):
        for auto in (False, True):
            with self.subTest(auto=auto):
                record = fixtures.fixture(self.root / f"erased-{auto}")
                system = record["systems"][0]
                image = cv2.imread(system["strip_path"])
                x, y = system["strip"]["box_crop"][:2]
                image[112-y:115-y, 420-x:423-x] = 255
                self.assertTrue(cv2.imwrite(system["strip_path"], image))
                _plan, _pages, sink = self.compose(record, auto)
                report, _ledger, _pdf = self.verify(record, sink, f"erased-export-{auto}")
                self.assertEqual(report["status"], "fail")
                self.assertIn("SOURCE_FOREGROUND_MISSING_OR_CHANGED", {i["code"] for i in report["issues"]})

    def test_clean_measure_area_shrink_and_cubic_enlarge(self):
        methods = set()
        for mm in (1.2, 1.6):
            with self.subTest(staff_gap_mm=mm):
                if mm == 1.2:
                    record, context = self.large_native_fixture()
                else:
                    record = fixtures.fixture(self.root / f"resize-{mm}")
                    context = None
                _plan, _pages, sink = self.compose(record, False, context, staff_gap_mm=mm)
                report, ledger, _pdf = self.verify(record, sink, f"resize-export-{mm}")
                self.assertEqual(report["status"], "pass", report["issues"])
                methods.update(r["transforms"][1]["pre_resample"]["interpolation"] for r in ledger["representations"])
        self.assertEqual(methods, {"area", "cubic"})

    @unittest.skip(RETIRED_VERIFIER)

    def test_line_shift_two_pixels_fails_auto_off_and_on(self):
        for auto in (False, True):
            with self.subTest(auto=auto):
                record = fixtures.fixture(self.root / f"shifted-{auto}")
                plan, _pages, sink = self.compose(record, auto)
                pl = plan["pages"][0]["placements"][0]
                page = sink["pages"][0].copy()
                x, y, w, h = (pl[k] for k in ("x", "y", "w", "h"))
                line = page[y:y+h, x:x+w].copy()
                page[y:y+h, x:x+w+2] = 255
                page[y:y+h, x+2:x+w+2] = line
                sink["pages"] = [page]
                report, _ledger, _pdf = self.verify(record, sink, f"shifted-export-{auto}")
                self.assertEqual(report["status"], "fail")
                self.assertIn("SOURCE_FOREGROUND_MISSING_OR_CHANGED", {i["code"] for i in report["issues"]})

    @unittest.skip(RETIRED_VERIFIER)

    def test_original_two_system_fixture_has_only_removal_review_auto_off_and_on(self):
        for auto in (False, True):
            with self.subTest(auto=auto):
                source = fixtures.LedgerIntegrationTest()
                source.root = self.root / f"two-{auto}"
                source.root.mkdir()
                record, context = source.measure_fixture()
                _plan, _pages, sink = self.compose(record, auto, context)
                report, ledger, _pdf = self.verify(record, sink, f"two-export-{auto}")
                self.assertEqual(report["status"], "review_required")
                self.assertFalse([i for i in report["issues"] if i["severity"] == "fail"], report["issues"])
                allowed = {"UNRESOLVED_ALTERNATIVE", "OBSERVATION_UNRESOLVED", "REMOVED_BY_remove_scaffold_columns"}
                self.assertTrue({i["code"] for i in report["issues"]} <= allowed)
                removed = [d for d in ledger["dispositions"] if d.get("reason", "").startswith("REMOVED_BY_")]
                self.assertEqual(len(removed), 2)
                self.assertTrue(any(p["copy_index"] > 0 for p in sink["placements"]))
                staff = [r for r in ledger["generated_origins"] if r["kind"] == "staff_scaffold"]
                self.assertTrue(staff)
                self.assertTrue(all(r.get("source_item_refs") and not r.get("unresolved_source") for r in staff))
                self.assertTrue(any(len(r["source_item_refs"]) > 1 for r in staff))

    def test_wrong_staff_reference_and_added_dot_still_fail(self):
        record = fixtures.fixture(self.root / "staff")
        _plan, _pages, sink = self.compose(record, False)
        report, ledger, pdf = self.verify(record, sink, "staff-export")
        self.assertEqual(report["status"], "pass", report["issues"])
        origin = next(r for r in ledger["generated_origins"] if r["kind"] == "staff_scaffold")
        wrong = copy.deepcopy(ledger)
        target = next(r for r in wrong["generated_origins"] if r["kind"] == "staff_scaffold")
        target["staff_rows_S"] = [y+2 for y in target["staff_rows_S"]]
        invalid = rl.verify_pdf(wrong, pdf)
        self.assertEqual(invalid["status"], "fail")
        self.assertIn("INVALID_GENERATED_ORIGIN", {i["code"] for i in invalid["issues"]})
        # A missing raw row cannot be supplied by another connected/tiled item.
        bad = copy.deepcopy(origin)
        bad["source_item_refs"] = bad["source_item_refs"][:1]
        with self.assertRaises(ValueError):
            rl.scaffold_source_column(ledger, bad)
        # Source geometry remains strict even when its actual page is unchanged.
        bad = copy.deepcopy(origin)
        template = rl.unpack_crop(bad["template"])
        yy = max(0, int(round(bad["staff_rows_local"][2]))-4)
        template[yy:yy+2, :2] = 0
        bad["template"] = rl.pack_crop(template)
        wrong = copy.deepcopy(ledger)
        wrong["generated_origins"] = [bad]
        invalid = rl.verify_pdf(wrong, pdf)
        self.assertIn("INVALID_GENERATED_ORIGIN", {i["code"] for i in invalid["issues"]})

    def test_resize_metadata_mismatch_is_not_accepted(self):
        record = fixtures.fixture(self.root / "metadata")
        _plan, _pages, sink = self.compose(record, False)
        _report, ledger, _pdf = self.verify(record, sink, "metadata-export")
        rep = next(r for r in ledger["representations"] if r["transforms"][1].get("pre_resample"))
        item = next(i for i in ledger["items"] if i["id"] == rep["item_id"])
        stages = copy.deepcopy(rep["transforms"])
        stages[1]["pre_matrix"][0][2] += 2
        with self.assertRaisesRegex(ValueError, "metadata and pre_matrix"):
            rl.project_item(item, stages)

    @unittest.skip(RETIRED_VERIFIER)

    def test_unresolved_observations_reuse_hash_checked_views(self):
        source = fixtures.LedgerIntegrationTest()
        source.root = self.root / "view-cache"
        source.root.mkdir()
        record, context = source.measure_fixture()
        _plan, _pages, sink = self.compose(record, False, context)
        report, ledger, pdf = self.verify(record, sink, "view-cache-export")
        calls = [0]
        original = rl.EvidenceResolver.views

        def counted(resolver, item):
            calls[0] += 1
            yield from original(resolver, item)

        with patch.object(rl.EvidenceResolver, "views", counted):
            checked = rl.verify_pdf(ledger, pdf)
        self.assertEqual(checked["matches"], report["matches"])
        self.assertEqual(Counter(i["code"] for i in checked["issues"]),
                         Counter(i["code"] for i in report["issues"] if not i["code"].startswith("REMOVED_BY_")))
        refs = sum(len(r.get("source_item_refs", [])) for r in ledger["generated_origins"])
        self.assertLessEqual(calls[0], 2*len(ledger["items"])+refs)


if __name__ == "__main__":
    unittest.main()
