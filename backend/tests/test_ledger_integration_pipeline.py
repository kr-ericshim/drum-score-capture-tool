"""Real export gates over synthetic raw observations, never real-video claims."""
import copy
import asyncio
import json
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_ledger as rl, reflow_ledger_assembly as assembly
from app.pipeline import reflow_pipeline as rp, reflow_strips as rs, source_class as sc
from app.pipeline.export import ExportVerificationError, export_composed_pages
from app.schemas import JobReviewExportRequest
from reflow_fixture import build, loader
from test_ledger_v2_verify import hand_pdf, lossless_legacy_verify_pdf
from test_reflow_measure import Doc, measure_strip
from test_reflow_visibility_marks import paper


def store_frames(manifest, load, root):
    frames = root / "manifest" / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for obs in manifest["observations"]:
        path = frames / f"{obs['id']}.png"
        if not cv2.imwrite(str(path), load(obs)):
            raise OSError(path)
        obs["frame_path"] = str(path)


def fixture(root, count=1):
    frames = []
    for k in range(count):
        image = paper()
        image[112:115, 420+k*20:423+k*20] = 0
        frames.extend((len(frames)*.25+j*.25, image.copy()) for j in range(8))
    manifest, images = build(frames)
    load = loader(images)
    store_frames(manifest, load, root)
    inventory = assembly.inventory_observations(manifest, root / "manifest", source_video="synthetic")
    systems = []
    for k in range(count):
        obs = manifest["observations"][k*8:(k+1)*8]
        systems.append({"id": f"sys-{k+1:03d}", "index": k+1, "included": True, "auto_included": True,
            "observations": [{"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]} for o in obs],
            "first_display": True, "terminal_display": True, "t_start": obs[0]["t_sec"], "t_end": obs[-1]["t_sec"],
            "slot_id": "slot-00", "layout": "bottom_bar", "episode_ids": [f"ep-{k}"], "issues": []})
    strips = rs.build_strips({"systems": systems}, manifest, load, root / "strips", ledger=True)
    occ = {"ledger": {"source_video": "synthetic", "displays": []}}
    for k, rec in enumerate(strips):
        rec["ledger_supersedes"] = f"occ:root-{k}"
        display = copy.deepcopy(rec["ledger"]["displays"][0])
        display.update(id=f"occ:root-{k}", inventory_only=True)
        occ["ledger"]["displays"].append(display)
    base, chains = rp._build_base_ledger(inventory, occ, strips)
    for system, rec in zip(systems, strips):
        system.update(strip_path=rec["path"], strip={k: v for k, v in rec.items() if k != "path"})
        system.pop("observations")
    rl.write_ledger(root / "ledger_base.json", base)
    (root / "ledger_chains.json").write_text(json.dumps(chains))
    return {"workspace": str(root), "dev_ledger": True, "ledger_base_path": str(root / "ledger_base.json"),
        "ledger_chains_path": str(root / "ledger_chains.json"), "systems": systems,
        "source_class": {"class": sc.CLASS_LIGHT_PAPER}, "review_reasons": [], "output_model": rp.OUTPUT_MODEL}


class LedgerIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.legacy_pdf = patch.object(rl, "verify_pdf", side_effect=lossless_legacy_verify_pdf)
        self.legacy_pdf.start()
        self.addCleanup(self.legacy_pdf.stop)

    def compose(self, record, systems=None, **kw):
        sink = kw.pop("sink", {})
        plan, pages = rp.compose_systems(record["systems"] if systems is None else systems,
            workspace=Path(record["workspace"]), all_systems=record["systems"], ledger_sink=sink, **kw)
        return plan, pages, sink

    def verify(self, record, sink, staged="staged", formats=("pdf",)):
        path = self.root / staged
        exported = export_composed_pages(pages=sink["pages"], formats=list(formats), workspace=path, logger=lambda _m: None)
        t = time.perf_counter()
        # These raw-loss/terminal assertions exercise the retired LIBRARY.
        report = rp.verify_delivered_ledger(record, exported.get("pdf"), path, sink=sink)
        if report["status"] == "fail":
            raise ExportVerificationError("LEDGER_VERIFICATION_FAILED", "legacy library finding")
        elapsed = time.perf_counter()-t
        report = json.loads((path / "ledger_report.json").read_text())
        ledger = json.loads((path / "ledger.json").read_text())
        print(f"INTEGRATION_EXPORT case={staged} status={report['status']} base_bytes={Path(record['ledger_base_path']).stat().st_size} "
              f"delivered_bytes={(path/'ledger.json').stat().st_size} verify_seconds={elapsed:.6f} "
              f"issue_counts={dict(Counter(i['code'] for i in report['issues']))}")
        return report, ledger

    def test_analyse_source_writes_base_and_chains_without_embedded_ledger(self):
        root = self.root / "reflow"
        manifest, images = build([(k*.25, paper()) for k in range(8)])
        manifest.pop("video_id")
        def sampled(**_kw):
            store_frames(manifest, loader(images), root)
            return manifest
        with patch.object(rp, "classify_source_class", return_value={"class": sc.CLASS_LIGHT_PAPER}), \
                patch.object(rp.ob, "build_manifest", side_effect=sampled), patch.object(rp.rj, "analyse_jumps", return_value=None):
            record = rp.analyse_source(video_path=self.root / "synthetic.mp4", roi=[[0,0],[800,0],[800,160],[0,160]], workspace=root, ledger=True)
        base = json.loads(Path(record["ledger_base_path"]).read_text())
        chains = json.loads(Path(record["ledger_chains_path"]).read_text())
        self.assertEqual(len(base["observations"]), 8)
        self.assertEqual(base["source_video"], str(self.root / "synthetic.mp4"))
        self.assertTrue(base["items"] and chains)
        self.assertTrue(any(d["kind"] == "superseded_inventory" for d in base["display_dispositions"]))
        public = rp.public_record(record)
        self.assertNotIn("ledger", public)
        self.assertTrue(all("ledger" not in s["strip"] for s in public["systems"]))
        self.assertNotIn("ledger", json.loads((root / "occurrences.json").read_text()))
        print(f"ANALYSE_BASE bytes={Path(record['ledger_base_path']).stat().st_size} result_bytes={len(json.dumps(public).encode())}")

    def test_whole_system_staged_pdf_pass_and_written_dot_erasure_fail(self):
        record = fixture(self.root / "reflow")
        _, _, sink = self.compose(record, header={"title": "Synthetic chart"})
        report, _ = self.verify(record, sink)
        self.assertEqual(report["status"], "pass", report["issues"])
        strip = record["systems"][0]
        image = cv2.imread(strip["strip_path"])
        x, y = strip["strip"]["box_crop"][:2]
        image[112-y:115-y, 420-x:423-x] = 255
        self.assertTrue(cv2.imwrite(strip["strip_path"], image))
        _, _, sink = self.compose(record, header={"title": "Synthetic chart"})
        with self.assertRaises(ExportVerificationError) as caught:
            self.verify(record, sink, staged="erased")
        self.assertEqual(caught.exception.code, "LEDGER_VERIFICATION_FAILED")
        report = json.loads((self.root / "erased" / "ledger_report.json").read_text())
        self.assertEqual(report["status"], "fail")
        self.assertIn("SOURCE_FOREGROUND_MISSING_OR_CHANGED", {i["code"] for i in report["issues"]})

    def test_initial_job_path_installs_clean_pdf_and_compact_summary(self):
        from test_reflow_review_export import ReflowJobFlowTest
        flow = ReflowJobFlowTest(); flow.setUp(); self.addCleanup(flow.tearDown)
        record = fixture(flow.ws)
        job = flow.run_job(record, lambda *_a, **_kw: [], export={"formats": ["pdf"]}, measure_reflow=False)
        self.assertEqual(job.status, JobStatus.DONE, job.error_code)
        self.assertEqual(job.result["reflow_state"], "done")
        self.assertEqual(job.result["reflow"]["ledger_summary"]["status"], "pass")
        self.assertFalse(job.result["review_required"])
        self.assertTrue(Path(job.result["pdf"]).is_file())
        self.assertTrue((Path(job.artifact_dir) / "export" / "verify_B.json").is_file())
        self.assertTrue(all("ledger" not in s["strip"] for s in job.result["reflow"]["systems"]))

    def test_label_band_offset_pass_and_ink_label_requires_review(self):
        record = fixture(self.root / "reflow")
        path = self.root / "label.png"
        cv2.imwrite(str(path), np.full((30, 50, 3), 255, np.uint8))
        record["systems"][0]["label"] = {"path": str(path), "x_in_strip": 0}
        plan, _, sink = self.compose(record)
        self.assertGreater(plan["pages"][0]["placements"][0]["strip_offset_px"][1], 0)
        report, _ = self.verify(record, sink, staged="label_band")
        self.assertEqual(report["status"], "pass", report["issues"])
        image = cv2.imread(str(path)); image[10:15,10:15] = 0; cv2.imwrite(str(path), image)
        _, _, sink = self.compose(record)
        report, _ = self.verify(record, sink, staged="ink_label")
        self.assertEqual(report["status"], "review_required", report["issues"])
        self.assertIn("SECTION_LABEL_SOURCE_UNLEDGERED", {i["code"] for i in report["issues"]})

    def test_uncut_crop_translation_pass_and_unknown_extent_review(self):
        record = fixture(self.root / "reflow")
        system = record["systems"][0]
        strip = system["strip"]
        image = cv2.imread(system["strip_path"])
        # An extra paper column changes the uncut extent without adding raw ink.
        uncut = np.pad(image, ((0,0),(0,17),(0,0)), constant_values=255)
        path = self.root / "uncut.png"; cv2.imwrite(str(path), uncut)
        box = list(strip["box_crop"]); box[2] += 17
        strip.update(preview_tail={"cut": True, "destination_system_id": "absent"},
            uncut={"path": str(path), "box_crop": box, "size": [uncut.shape[1], uncut.shape[0]]},
            uncut_pixels_sha256=rp._pixels_sha256(uncut))
        _, _, sink = self.compose(record)
        self.assertEqual(sink["variants"][system["id"]], "uncut")
        self.assertTrue(sink["chains"])
        report, _ = self.verify(record, sink, staged="uncut")
        self.assertEqual(report["status"], "pass", report["issues"])
        strip.pop("ledger_canvas_box_crop")
        _, _, sink = self.compose(record)
        report, ledger = self.verify(record, sink, staged="uncut_unknown")
        self.assertEqual(report["status"], "review_required", report["issues"])
        self.assertIn("CHAIN_UNAVAILABLE:uncut", {d.get("reason") for d in ledger["display_dispositions"]})

    def test_user_exclusion_pass_pipeline_exclusion_not_counted(self):
        record = fixture(self.root / "reflow", 2)
        first, second = record["systems"]
        _, _, sink = self.compose(record, [first], sink={"excluded_system_ids": [second["id"]]})
        report, _ = self.verify(record, sink, staged="user_excluded")
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertEqual(report["user_excluded"]["displays"], 2)  # strip + occurrence inventory
        self.assertGreater(report["user_excluded"]["items"], 0)
        # Measured duplicate-display equivalence, excluded by the pipeline.
        base = json.loads(Path(record["ledger_base_path"]).read_text())
        for item in list(base["items"]):
            if item["display_id"] == f"strip:{first['id']}":
                clone = copy.deepcopy(item); clone.update(id=f"duplicate/{item['id']}", display_id="pipeline-duplicate")
                base["items"].append(clone)
        display = copy.deepcopy(next(d for d in base["displays"] if d["id"] == f"strip:{first['id']}"))
        display["id"] = "pipeline-duplicate"; base["displays"].append(display)
        base["display_dispositions"].append({"kind": "display_equivalent", "terminal": "equivalent_observation",
            "display_id": "pipeline-duplicate", "retained_display_id": f"strip:{first['id']}",
            "equivalence_map": np.eye(3).tolist(), "registration_uncertainty": 0., "evidence": {"method": "synthetic_equal"}})
        rl.write_ledger(record["ledger_base_path"], base)
        _, _, sink = self.compose(record, [first], sink={"excluded_system_ids": [second["id"]]})
        report, _ = self.verify(record, sink, staged="pipeline_duplicate")
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertEqual(report["user_excluded"]["displays"], 2)

    def test_pdf_contract_violation_fails_staged_gate(self):
        record = fixture(self.root / "reflow")
        _, _, sink = self.compose(record)
        staged = self.root / "contract"
        exported = export_composed_pages(pages=sink["pages"], formats=["pdf"], workspace=staged, logger=lambda _m: None)
        hand_pdf(Path(exported["pdf"]), commands=b"q 0 0 10 10 re W n 595.2 0 0 841.92 0 0 cm /image Do Q")
        with self.assertRaises(ExportVerificationError):
            main._verify_reflow_ledger(record, exported, staged, sink)
        self.assertEqual(record["ledger_summary"]["status"], "fail")
        self.assertGreater(record["ledger_summary"]["issue_counts"]["PDF_CONTRACT_VIOLATION"], 0)

    def test_user_exclusion_with_shared_observation_does_not_poison_kept_terminal(self):
        record = fixture(self.root / "reflow", 2)
        base = json.loads(Path(record["ledger_base_path"]).read_text())
        # The same sampled frame can contribute to two row displays. Reuse the
        # first raw witness only for matching staff hypotheses of the second.
        first, second = record["systems"]
        kept = next(d for d in base["displays"] if d["id"] == f"strip:{first['id']}")
        excluded = next(d for d in base["displays"] if d["id"] == f"strip:{second['id']}")
        oid = kept["observations"][0]
        excluded["members"][0]["observation_id"] = oid
        excluded["members"][0]["frame_ref"]["observation_id"] = oid
        obs = next(o for o in base["observations"] if o["id"] == oid)
        obs["associations"].append({"stage": "composition", "display_id": excluded["id"],
            "occurrence_id": second["id"], "role": "used", "reason": None})
        rl.write_ledger(record["ledger_base_path"], base)
        _, _, sink = self.compose(record, [first], sink={"excluded_system_ids": [second["id"]]})
        report, ledger = self.verify(record, sink, staged="shared_observation")
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertEqual(next(o for o in ledger["observations"] if o["id"] == oid)["terminal"], "preserved")

    def test_prune_then_reexport_same_status_and_hash_failure_keeps_frames(self):
        record = fixture(self.root / "reflow")
        _, _, sink = self.compose(record)
        before, _ = self.verify(record, sink, staged="before_prune")
        rp.prune_frames(record)
        self.assertTrue(record["frames_pruned"])
        self.assertFalse((Path(record["workspace"]) / "manifest" / "frames").exists())
        _, _, sink = self.compose(record)
        after, ledger = self.verify(record, sink, staged="after_prune")
        self.assertEqual(after["status"], before["status"])
        self.assertTrue(all(Path(o["frame_path"]).is_file() for o in ledger["observations"]))
        record = fixture(self.root / "bad_retention")
        base = json.loads(Path(record["ledger_base_path"]).read_text())
        Path(base["observations"][0]["frame_path"]).write_bytes(b"damaged")
        with self.assertLogs("app.pipeline.reflow_pipeline", level="WARNING"):
            rp.prune_frames(record)
        self.assertFalse(record["frames_pruned"])
        self.assertTrue((Path(record["workspace"]) / "manifest" / "frames").is_dir())

    def test_png_only_uses_pages_and_old_job_remains_unassessed(self):
        record = fixture(self.root / "reflow")
        _, _, sink = self.compose(record)
        staged = self.root/"png_only"
        exported = export_composed_pages(pages=sink["pages"], formats=["png"], workspace=staged, logger=lambda _m: None)
        main._verify_reflow_ledger(record, exported, staged, sink)
        report = json.loads((staged/"ledger_report.json").read_text())
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertNotIn("DELIVERED_PDF_UNASSESSED", record["review_reasons"])
        old = {"workspace": str(self.root / "old"), "systems": [], "source_class": {"class": sc.CLASS_LIGHT_PAPER}}
        (self.root/"old_stage").mkdir()
        report = rp.verify_delivered_ledger(old, None, self.root / "old_stage", sink={"pages": sink["pages"]})
        self.assertEqual(report["assessment"], "unassessed")
        self.assertIn("LEDGER_UNASSESSED", old["review_reasons"])

    def test_review_export_user_flags_and_job_result_size(self):
        record = fixture(self.root / "job" / "reflow", 2)
        plan, _, sink = self.compose(record)
        self.verify(record, sink, staged="initial")
        record["page_plan"] = plan
        store = JobStore(self.root)
        job = Job(id="job", source_type="file", file_path=str(self.root / "synthetic.mp4"), youtube_url=None,
            artifact_dir=str(self.root / "job"), options={"export": {"formats": ["pdf"]}}, status=JobStatus.DONE,
            result={"output_model": rp.OUTPUT_MODEL, "reflow": rp.public_record(record), "reflow_state": "done"})
        store.create(job)
        with patch("app.main.job_store", store):
            main.review_export("job", JobReviewExportRequest(keep_captures=[record["systems"][0]["strip_path"]], formats=["pdf"]))
        result = store.get("job").result
        self.assertEqual(result["reflow"]["ledger_summary"]["status"], "pass")
        self.assertGreater(result["reflow"]["ledger_verification"]["user_excluded"]["items"], 0)
        def check(obj):
            if isinstance(obj, dict):
                # The compact summary has an integer count, never the ledger list.
                self.assertFalse(isinstance(obj.get("items"), list))
                self.assertNotIn("foreground_hypothesis", obj)
                for value in obj.values(): check(value)
            elif isinstance(obj, list):
                for value in obj: check(value)
        check(result)
        size = len(json.dumps(result).encode())
        self.assertLess(size, 100_000)
        print(f"JOB_RESULT bytes={size}")

    def measure_fixture(self):
        root = self.root / "measure"
        root.mkdir()
        doc = Doc(root)
        manifests, fragments, records = [], [], []
        for k in range(2):
            image, rec = measure_strip(2)
            system = doc.add(f"sys-{k:03d}", image, rec)
            obs = []
            members = []
            for j in range(3):
                oid = f"measure-{k}-{j}"
                path = root / "manifest" / "frames" / f"{oid}.png"; path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), image)
                obs.append({"id": oid, "t_sec": float(k*5+j), "sample_kind": "coarse", "frame_path": str(path),
                    "system_regions": [{}], "source_to_crop": np.eye(3).tolist()})
                members.append({"id": oid, "timestamp": float(k*5+j), "image": image, "roi_origin": [0,0],
                    "registration_shift": [0,0], "registration_uncertainty": 0.,
                    "frame_ref": {"observation_id": oid, "crop_box": [0,0,image.shape[1],image.shape[0]]}})
            manifests.extend(obs)
            sid = system["id"]; did = f"strip:{sid}"
            fragment = rl.record_obligations(source_video="synthetic", display_id=did, occurrence_id=sid,
                members=members, evidence_dir=root / "ledger_evidence")
            fragment["observation_associations"] = [{"obs_id": o["id"], "stage": "composition", "display_id": did,
                "occurrence_id": sid, "role": "used", "reason": None} for o in obs]
            chain = {"display_id": did, "strip_id": sid,
                "stages": [{"stage": "display_to_strip", "kind": "affine", "matrix": np.eye(3).tolist()}]}
            records.append({"system_id": sid, "ledger": fragment, "ledger_chain": chain})
        inventory = assembly.inventory_observations({"observations": manifests}, root / "manifest", source_video="synthetic")
        base, chains = rp._build_base_ledger(inventory, {}, records)
        rl.write_ledger(root / "ledger_base.json", base); (root / "ledger_chains.json").write_text(json.dumps(chains))
        return {"workspace": str(root), "dev_ledger": True, "ledger_base_path": str(root / "ledger_base.json"), "systems": doc.systems,
            "source_class": {"class": sc.CLASS_LIGHT_PAPER}}, doc.context

    def test_measure_two_system_export_reports_status_and_code_counts(self):
        record, context = self.measure_fixture()
        plan, _, sink = self.compose(record, measure_reflow=True, measure_context=context)
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        self.assertTrue(sink["placements"] and sink["removed"])
        for key in ("ledger_placements", "ledger_removed", "generated_origins"):
            self.assertNotIn(key, plan["measure_reflow"])
        staged = self.root / "measure_export"
        exported = export_composed_pages(pages=sink["pages"], formats=["pdf"], workspace=staged, logger=lambda _m: None)
        t = time.perf_counter()
        report = rp.verify_delivered_ledger(record, exported["pdf"], staged, sink=sink)
        self.assertEqual(record["ledger_summary"]["status"], report["status"])
        self.assertEqual(record["ledger_summary"]["issue_counts"], dict(Counter(i["code"] for i in report["issues"])))
        delivered = json.loads((staged / "ledger.json").read_text())
        removed = [d for d in delivered["dispositions"] if d.get("reason", "").startswith("REMOVED_BY_")]
        self.assertTrue(removed)
        self.assertNotEqual(report["status"], "pass")
        print(f"MEASURE_EXPORT status={report['status']} removed_review_items={len(removed)} "
            f"base_bytes={Path(record['ledger_base_path']).stat().st_size} delivered_bytes={(staged/'ledger.json').stat().st_size} "
            f"verify_seconds={time.perf_counter()-t:.6f} issue_counts={record['ledger_summary']['issue_counts']}")

    def test_removed_dot_piecewise_has_raw_alternative_review_required(self):
        record = fixture(self.root / "reflow")
        _, _, sink = self.compose(record)
        system = record["systems"][0]
        image = cv2.imread(system["strip_path"])
        ox, oy = system["strip"]["box_crop"][:2]
        x0, y0, x1, y1 = 420-ox, 112-oy, 423-ox, 115-oy
        stage = sink["placements"][0]["stages"][0]
        stage.update(kind="piecewise", pieces=[{"src_bbox": box, "matrix": np.eye(3).tolist()} for box in
            ([0,0,image.shape[1],y0], [0,y1,image.shape[1],image.shape[0]], [0,y0,x0,y1], [x1,y0,image.shape[1],y1])])
        stage.pop("matrix")
        sink["removed"] = [{"strip_id": system["id"], "line_id": system["id"], "src_bbox_R": [x0,y0,x1,y1], "op": "remove_clef"}]
        image[y0:y1,x0:x1] = 255
        # Re-render from the written altered strip with the original placements.
        from app.pipeline import reflow_render as rr
        plan = rp.compose_systems([system])[0]
        sink["pages"] = rr.render_pages(plan, {system["id"]: image})
        report, ledger = self.verify(record, sink, staged="removed_dot")
        self.assertEqual(report["status"], "review_required", report["issues"])
        self.assertEqual(record["ledger_summary"]["issue_counts"]["REMOVED_BY_remove_clef"], 1)
        disposition = next(d for d in ledger["dispositions"] if d.get("reason") == "REMOVED_BY_remove_clef")
        self.assertTrue(Path(disposition["review_artifact"]).is_file())

    def test_removed_dot_delivered_by_replica_is_discharged(self):
        record = fixture(self.root / "reflow")
        plan, _, sink = self.compose(record)
        system = record["systems"][0]
        original = cv2.imread(system["strip_path"])
        image = original.copy()
        ox, oy = system["strip"]["box_crop"][:2]
        x0, y0, x1, y1 = 420-ox, 112-oy, 423-ox, 115-oy
        primary = sink["placements"][0]
        replica = copy.deepcopy(primary)
        replica.update(copy_index=1, line_id="replica")
        replica["stages"][1]["matrix"][1][2] += 250
        sink["placements"].append(replica)
        primary["stages"][0] = {"stage": "strip_to_line", "kind": "piecewise", "pieces": [
            {"src_bbox": box, "matrix": np.eye(3).tolist()} for box in
            ([0,0,image.shape[1],y0], [0,y1,image.shape[1],image.shape[0]], [0,y0,x0,y1], [x1,y0,image.shape[1],y1])]}
        sink["removed"] = [{"strip_id": system["id"], "line_id": system["id"], "src_bbox_R": [x0,y0,x1,y1], "op": "remove_clef"}]
        image[y0:y1,x0:x1] = 255
        placement = copy.deepcopy(plan["pages"][0]["placements"][0])
        placement.update(system_id="replica", y=placement["y"]+250)
        plan["pages"][0]["placements"].append(placement)
        from app.pipeline import reflow_render as rr
        sink["pages"] = rr.render_pages(plan, {system["id"]: image, "replica": original})
        report, ledger = self.verify(record, sink, staged="removed_replica")
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertFalse(any(d.get("reason", "").startswith("REMOVED_BY_") for d in ledger["dispositions"]))


class ReviewAccessTest(unittest.TestCase):
    setUp = LedgerIntegrationTest.setUp
    compose = LedgerIntegrationTest.compose
    measure_fixture = LedgerIntegrationTest.measure_fixture

    def request(self, url):
        path, _, query = url.partition("?")
        async def run():
            messages, received = [], False
            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await asyncio.Event().wait()
            async def send(message):
                messages.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": query.encode(), "headers": [], "client": ("127.0.0.1",1), "server": ("test",80)}
            await main.app(scope, receive, send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            body = b"".join(m.get("body",b"") for m in messages if m["type"] == "http.response.body")
            return status, json.loads(body)
        return asyncio.run(run())

    def promote(self, record, staged, *, job_id="review", revision=7):
        export = self.root / "promoted-output"
        commit = main._install_staged_export_workspace(staged_workspace=staged, target_workspace=export)
        commit.finalize()
        store = JobStore(self.root / "jobs")
        store.create(Job(id=job_id, source_type="file", file_path="synthetic.mp4", youtube_url=None,
            options={}, artifact_dir=str(self.root/job_id), status=JobStatus.DONE,
            result={"output_dir": str(export), "reflow": {"revision": revision, "systems": record["systems"]}}))
        return store, export.resolve()

    def ordered_artifact(self):
        record = fixture(self.root / "reflow", 2)
        _, pages, sink = self.compose(record)
        ledger = rp.build_delivered_ledger(record, sink)
        first = next(i for i in ledger["items"] if i["display_id"] == "strip:sys-001")
        second = next(i for i in ledger["items"] if i["display_id"] == "strip:sys-002")
        review = next(i for i in ledger["items"] if i["display_id"] == "strip:sys-001" and i["id"] != first["id"])
        unresolved = next(i for i in ledger["items"] if i["display_id"] == "strip:sys-002" and i["id"] != second["id"])
        ledger["representations"] = [r for r in ledger["representations"] if r["item_id"] != unresolved["id"]]
        ledger["dispositions"].append({"item_id": unresolved["id"], "terminal": "unresolved",
            "kind": "unresolved_alternative", "reason": "TEST_UNRESOLVED"})
        # API ordering inputs; actual pixel-verification controls are separate.
        report = {"status": "fail", "issues": [
            {"severity": "review_required", "code": "TEST_REVIEW", "item_id": review["id"]},
            {"severity": "fail", "code": "TEST_FAIL_LATE", "item_id": second["id"]},
            {"severity": "fail", "code": "TEST_FAIL_EARLY", "item_id": first["id"]},
            {"severity": "fail", "code": "TEST_FAIL_EARLY", "item_id": first["id"]},
            {"severity": "fail", "code": "PDF_CONTRACT_VIOLATION"}], "user_excluded": {"displays": 2, "items": 9}}
        staged = self.root / "review-staged"
        sink.update(job_id="review", export_revision=7)
        t = time.perf_counter()
        body = rp.write_review_hypotheses(record, ledger, report, staged, pages=pages, sink=sink)
        elapsed = time.perf_counter()-t
        rp._dump(report, staged/"ledger_report.json")
        size = (staged/"review_hypotheses.json").stat().st_size + sum(p.stat().st_size for p in (staged/"review_hypotheses").glob("*.png"))
        print(f"REVIEW_ACCESS entries={body['total']} disk_bytes={size} write_seconds={elapsed:.6f}")
        return record, staged, body

    def test_endpoint_pagination_order_crops_and_promoted_absolute_paths(self):
        record, staged, body = self.ordered_artifact()
        self.assertEqual([e["code"] for e in body["hypotheses"]],
            ["TEST_FAIL_EARLY", "TEST_FAIL_LATE", "TEST_REVIEW", "TEST_UNRESOLVED"])
        self.assertEqual(body["counts"]["by_code"]["TEST_FAIL_EARLY"], 1)
        self.assertEqual(body["counts"]["by_code"]["PDF_CONTRACT_VIOLATION"], 1)
        self.assertEqual(body["hypotheses"][-1]["primary_crop"], None)
        self.assertEqual(body["hypotheses"][-1]["page_index"], None)
        self.assertEqual(body["hypotheses"][0]["page_index"], 1)
        store, export = self.promote(record, staged)
        self.assertFalse(staged.exists())
        with patch("app.main.job_store", store), patch("app.main.DRUMSHEET_SESSION_TOKEN", ""):
            status, page = self.request("/jobs/review/review-hypotheses?offset=1&limit=2")
            self.assertEqual(status, 200, page)
            self.assertEqual((page["total"], page["offset"], page["limit"]), (4,1,2))
            self.assertEqual(page["export_revision"], 7)
            self.assertEqual([e["code"] for e in page["hypotheses"]], ["TEST_FAIL_LATE", "TEST_REVIEW"])
            _, full = self.request("/jobs/review/review-hypotheses?offset=-5&limit=900")
            self.assertEqual((full["offset"], full["limit"]), (0,500))
            _, beyond = self.request("/jobs/review/review-hypotheses?offset=999")
            self.assertEqual(beyond["offset"], 4)
            self.assertEqual(beyond["hypotheses"], [])
        for entry in full["hypotheses"]:
            raw_path = Path(entry["raw_crop"])
            self.assertTrue(raw_path.is_absolute() and raw_path.is_file())
            self.assertTrue(raw_path.is_relative_to(export))
            if entry["primary_crop"]:
                primary_path = Path(entry["primary_crop"])
                self.assertTrue(primary_path.is_absolute() and primary_path.is_file())
                raw, primary = cv2.imread(str(raw_path)), cv2.imread(str(primary_path))
                self.assertEqual(raw.shape[:2], primary.shape[:2])
                self.assertLessEqual(max(raw.shape[:2]), 480)

    def test_endpoint_unassessed_unknown_job_and_missing_report(self):
        store = JobStore(self.root / "jobs")
        artifact = self.root / "old"
        store.create(Job(id="old", source_type="file", file_path="old.mp4", youtube_url=None,
            options={}, artifact_dir=str(artifact), status=JobStatus.DONE))
        with patch("app.main.job_store", store), patch("app.main.DRUMSHEET_SESSION_TOKEN", ""):
            status, body = self.request("/jobs/old/review-hypotheses")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "unassessed")
            self.assertEqual(body["hypotheses"], [])
            self.assertEqual(body["counts"], {"hypotheses": 0, "bundles": 0, "boundaries_safe": 0,
                "boundaries_unknown": 0, "pages": 0, "by_code": {}, "user_excluded": {"displays": 0, "items": 0}})
            self.assertEqual(self.request("/jobs/missing/review-hypotheses")[0], 404)
            export = artifact/"export"; export.mkdir(parents=True)
            rp._dump({"status": "fail", "hypotheses": []}, export/"review_hypotheses.json")
            self.assertEqual(self.request("/jobs/old/review-hypotheses")[1]["status"], "unassessed")

    def test_staged_pdf_pages_extracted_once_and_crop_shows_written_dot_erasure(self):
        record = fixture(self.root / "reflow")
        system = record["systems"][0]
        image = cv2.imread(system["strip_path"])
        ox, oy = system["strip"]["box_crop"][:2]
        image[112-oy:115-oy,420-ox:423-ox] = 255
        cv2.imwrite(system["strip_path"], image)
        _, pages, sink = self.compose(record)
        staged = self.root / "written"
        result = export_composed_pages(pages=pages, formats=["pdf"], workspace=staged, logger=lambda _m: None)
        from app.pipeline import reflow_verify_page as vp
        with patch.object(vp, "decode_lossless_pdf", wraps=vp.decode_lossless_pdf) as extract:
            with self.assertRaises(ExportVerificationError):
                report = rp.verify_delivered_ledger(record, result["pdf"], staged, sink=sink)
                if report["status"] == "fail":
                    raise ExportVerificationError("LEDGER_VERIFICATION_FAILED", "legacy library finding")
        self.assertEqual(extract.call_count, 1)
        body = json.loads((staged/"review_hypotheses.json").read_text())
        entry = next(e for e in body["hypotheses"] if e["code"] == "SOURCE_FOREGROUND_MISSING_OR_CHANGED")
        raw = cv2.imread(str(staged/entry["raw_crop"])); primary = cv2.imread(str(staged/entry["primary_crop"]))
        self.assertEqual(raw.shape[:2], primary.shape[:2])
        ledger = json.loads((staged/"ledger.json").read_text())
        item = next(i for i in ledger["items"] if i["id"] == entry["item_id"])
        resolver = rl.EvidenceResolver(ledger); view = next(resolver.views(item))
        _, frame_to_display = rp._review_native_frame(resolver, item, view)
        corners = np.array([[*item["display_bbox"][:2],1], [*item["display_bbox"][2:],1]]) @ np.linalg.inv(frame_to_display).T
        lo = np.maximum(0,np.floor(corners[:,:2].min(axis=0)-24)).astype(int)
        x, y = np.round(([421,113]-lo)*entry["crop_scale"]).astype(int)
        self.assertLess(raw[y,x].max(), 30)
        self.assertGreater(primary[y,x].min(), 220)
        self.assertEqual(record["ledger_summary"]["counts"], body["counts"])

    def test_common_crop_scale_limit_and_clear_witness_selection(self):
        record = fixture(self.root / "reflow")
        _, pages, sink = self.compose(record)
        ledger = rp.build_delivered_ledger(record, sink)
        item = ledger["items"][0]
        resolver = rl.EvidenceResolver(ledger)
        views = list(resolver.views(item))
        witness = rp._review_witness(resolver, item, {"clear_observation_id": views[-1]["observation_id"]})
        self.assertEqual(witness["observation_id"], views[-1]["observation_id"])
        rep = next(r for r in ledger["representations"] if r["item_id"] == item["id"])
        raw, primary, scale = rp._review_crop_pair(resolver, item, witness, rep, pages, gap=400.)
        self.assertEqual(raw.shape[:2], primary.shape[:2])
        self.assertLessEqual(max(raw.shape[:2]), 480)
        self.assertLess(scale, 1.)

    def test_jump_episode_in_two_systems_prefers_actual_represented_system(self):
        record = fixture(self.root/"reflow", 2)
        _, pages, sink = self.compose(record)
        ledger = rp.build_delivered_ledger(record, sink)
        for system in record["systems"]:
            system["episode_ids"] = ["shared-episode"]
        display = next(d for d in ledger["displays"] if d["id"] == "strip:sys-002")
        display["id"] = "jump:shared-episode"
        group = [i for i in ledger["items"] if i["display_id"] == "strip:sys-002"]
        for item in group:
            item["display_id"] = display["id"]
        report = {"status": "review_required", "issues": [{"severity": "review_required",
            "item_id": group[0]["id"], "code": "TEST_JUMP_REVIEW"}]}
        body = rp.write_review_hypotheses(record, ledger, report, self.root/"jump-review", pages=pages, sink=sink)
        self.assertEqual(body["hypotheses"][0]["system_id"], "sys-002")
        # Measure lines carry a line id, so use the recorded display-to-strip
        # chain to recover the system rather than the first episode association.
        for chain in sink["all_chains"]["sys-002"]:
            chain["display_id"] = display["id"]
        for rep in ledger["representations"]:
            if rep["item_id"] == group[0]["id"]:
                rep["line_id"] = "measure-line"
        body = rp.write_review_hypotheses(record, ledger, report, self.root/"jump-measure-review", pages=pages, sink=sink)
        self.assertEqual(body["hypotheses"][0]["system_id"], "sys-002")

    def test_crop_cap_keeps_full_list_and_counts_with_truncated_flag(self):
        record = fixture(self.root / "reflow")
        _, pages, sink = self.compose(record)
        ledger = rp.build_delivered_ledger(record, sink)
        item = ledger["items"][0]
        report = {"status": "review_required", "issues": [{"severity": "review_required",
            "item_id": item["id"], "code": f"CAP_{k:04d}"} for k in range(2001)]}
        staged = self.root / "cap"
        t = time.perf_counter()
        body = rp.write_review_hypotheses(record, ledger, report, staged, pages=pages, sink=sink)
        self.assertTrue(body["truncated"])
        self.assertEqual(body["total"], 2001)
        self.assertEqual(sum(bool(e["raw_crop"]) for e in body["hypotheses"]), 2000)
        self.assertEqual(body["hypotheses"][-1]["raw_crop"], "")
        self.assertEqual(body["hypotheses"][-1]["primary_crop"], None)
        self.assertEqual(sum(body["counts"]["by_code"].values()), 2001)
        self.assertEqual(len(list((staged/"review_hypotheses").glob("*.png"))), 2)
        size = sum(p.stat().st_size for p in staged.rglob("*") if p.is_file())
        print(f"REVIEW_CAP entries=2001 disk_bytes={size} write_seconds={time.perf_counter()-t:.6f}")

    def test_unsupported_page_transform_keeps_raw_crop_available(self):
        record = fixture(self.root/"reflow")
        _, pages, sink = self.compose(record)
        ledger = rp.build_delivered_ledger(record, sink)
        item = ledger["items"][0]
        rep = next(r for r in ledger["representations"] if r["item_id"] == item["id"])
        rep["transforms"][1]["kind"] = "unsupported"
        report = {"status": "review_required", "issues": [{"severity": "review_required", "item_id": item["id"], "code": "TRANSFORM_UNRESOLVED"}]}
        staged = self.root/"unsupported"
        with self.assertLogs("app.pipeline.reflow_pipeline", level="WARNING"):
            body = rp.write_review_hypotheses(record, ledger, report, staged, pages=pages, sink=sink)
        entry = body["hypotheses"][0]
        self.assertTrue((staged/entry["raw_crop"]).is_file())
        self.assertIsNone(entry["primary_crop"])

    def test_counts_measure_boundaries_bundles_display_mapping_and_undelivered(self):
        record, context = self.measure_fixture()
        plan, pages, sink = self.compose(record, measure_reflow=True, measure_context=context)
        record["systems"].append({"id": "offered", "alternate_kind": "minority_content", "strip": {}})
        ledger = rp.build_delivered_ledger(record, sink)
        report = rl.verify_pages(ledger, pages)
        staged = self.root/"measure-review"
        t = time.perf_counter()
        body = rp.write_review_hypotheses(record, ledger, report, staged, pages=pages, sink=sink)
        elapsed = time.perf_counter()-t
        size = (staged/"review_hypotheses.json").stat().st_size + sum(p.stat().st_size for p in (staged/"review_hypotheses").glob("*.png"))
        print(f"REVIEW_MEASURE entries={body['total']} disk_bytes={size} write_seconds={elapsed:.6f} counts={body['counts']}")
        counts = plan["measure_reflow"]["boundary_counts"]
        self.assertEqual(body["counts"]["boundaries_safe"], counts.get("SAFE",0))
        self.assertEqual(body["counts"]["boundaries_unknown"], counts.get("UNKNOWN",0))
        self.assertEqual(body["counts"]["bundles"], 1)
        self.assertEqual(body["counts"]["pages"], len(pages))
        mapping = rp._review_system_map({"systems": [{"id": "jmp-001", "episode_ids": ["ep-1"]}, {"id": "sys-001"}]},
            {"occurrence_remaps": [{"display_id": "occ:pending", "final_system_id": "sys-001"}],
             "display_dispositions": [{"kind": "superseded_inventory", "display_id": "occ:root", "retained_display_id": "strip:sys-001"}]}, {})
        self.assertEqual(mapping["jump:ep-1"], "jmp-001")
        self.assertEqual(mapping["occ:root"], "sys-001")
        self.assertIsNone(mapping.get("occ:pending"))
        self.assertTrue(any(e["primary_crop"] is None for e in body["hypotheses"]))

    def test_initial_and_review_exports_write_promoted_artifacts_and_revisions(self):
        from test_reflow_review_export import ReflowJobFlowTest
        flow = ReflowJobFlowTest(); flow.setUp(); self.addCleanup(flow.tearDown)
        record = fixture(flow.ws)
        label = flow.root/"label.png"
        image = np.full((30,50,3),255,np.uint8); image[10:15,10:15] = 0; cv2.imwrite(str(label),image)
        record["systems"][0]["label"] = {"path": str(label), "x_in_strip": 0}
        # Both promotion paths exercise a non-blocking B finding and its crops.
        original = rp.vb.verify_plan
        def flagged(*args, **kw):
            cert = original(*args, **kw)
            cert["findings"].append({"stage": "B", "severity": "fail", "code": "PLAN_INVALID",
                "strip_id": record["systems"][0]["id"], "bbox": [10, 10, 20, 20], "detail": {"reason": "crop probe"}})
            return cert
        visible = patch.object(rp, "USER_VISIBLE_CODES", rp.USER_VISIBLE_CODES | {"PLAN_INVALID"})
        visible.start(); self.addCleanup(visible.stop)
        with patch.object(rp.vb, "verify_plan", side_effect=flagged):
            job = flow.run_job(record, lambda *_a, **_kw: [], export={"formats": ["pdf"]}, measure_reflow=False)
        self.assertEqual(job.status, JobStatus.DONE)
        exported = Path(job.result["output_dir"])
        self.assertTrue((exported/"review_hypotheses.json").is_file())
        with patch("app.main.job_store", flow.store), patch.object(rp.vb, "verify_plan", side_effect=flagged):
            initial = main.get_review_hypotheses(job.id).model_dump()
            self.assertEqual(initial["export_revision"], 1)
            self.assertGreater(initial["total"], 0)
            main.review_export(job.id, JobReviewExportRequest(keep_captures=[record["systems"][0]["strip_path"]], formats=["pdf"], measure_reflow=False))
            rebuilt = main.get_review_hypotheses(job.id).model_dump()
        self.assertEqual(rebuilt["export_revision"], 2)
        self.assertTrue((exported/"review_hypotheses.json").is_file())
        self.assertEqual(rebuilt["counts"], flow.store.get(job.id).result["reflow"]["ledger_summary"]["counts"])
        self.assertTrue(all(Path(e["raw_crop"]).is_file() for e in rebuilt["hypotheses"]))
        self.assertEqual(initial["counts"]["boundaries_safe"], 0)
        self.assertEqual(initial["counts"]["boundaries_unknown"], 0)

    def test_analyse_jumps_receives_shared_referenced_evidence_directory(self):
        root = self.root/"analysis"
        manifest, images = build([(k*.25,paper()) for k in range(8)])
        def sampled(**_kw):
            store_frames(manifest,loader(images),root)
            return manifest
        with patch.object(rp, "classify_source_class", return_value={"class": sc.CLASS_LIGHT_PAPER}), \
                patch.object(rp.ob, "build_manifest", side_effect=sampled), \
                patch.object(rp.rj, "analyse_jumps", return_value=None) as analyse:
            rp.analyse_source(video_path=self.root/"synthetic.mp4", roi=[[0,0],[800,0],[800,160],[0,160]], workspace=root, ledger=True)
        self.assertEqual(analyse.call_args.kwargs["evidence_dir"], root/"ledger_evidence")


if __name__ == "__main__":
    unittest.main()
