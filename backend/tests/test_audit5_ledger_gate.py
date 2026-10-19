"""Audit 5 probes: raw inventory, staged PDF gates and persistent overlay review."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app import main
from app.job_store import JobStatus
from app.pipeline import reflow_ledger as rl, reflow_pipeline as rp, reflow_strips as rs, source_class as sc
from app.pipeline.export import export_composed_pages
from app.schemas import JobReviewExportRequest
import test_reflow_ledger as ledger_fixture
import test_reflow_review_export as flow_fixture
from test_ledger_v2_verify import lossless_legacy_verify_pdf


class RawInventoryProbe(unittest.TestCase):
    def setUp(self):
        legacy = patch.object(rl, "verify_pdf", side_effect=lossless_legacy_verify_pdf)
        legacy.start()
        self.addCleanup(legacy.stop)

    def test_real_embedded_pdf_gate_reads_persisted_obligations_and_detects_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "reflow"
            staged = Path(tmp) / "staged"
            workspace.mkdir()
            staged.mkdir()
            ledger = ledger_fixture.snapshot(ledger_fixture.dot())
            ledger_fixture.place(ledger)
            rl.write_ledger(workspace / "ledger.json", ledger)
            record = {"workspace": str(workspace), "source_class": {"class": sc.CLASS_LIGHT_PAPER}, "systems": []}
            pdf = staged / "score.pdf"
            pdf = Path(export_composed_pages(pages=[ledger_fixture.a4(ledger_fixture.dot())],formats=["pdf"],
                workspace=staged,logger=lambda _m:None)["pdf"])
            report = rp.verify_delivered_ledger(record, str(pdf), staged)
            self.assertEqual(report["status"], "pass")
            self.assertFalse(record["review_required"])
            self.assertEqual(len(report["embedded_pages"]), 1)
            pdf = Path(export_composed_pages(pages=[ledger_fixture.a4(ledger_fixture.paper())],formats=["pdf"],
                workspace=staged,logger=lambda _m:None)["pdf"])
            report = rp.verify_delivered_ledger(record, str(pdf), staged)
            self.assertEqual(report["status"], "fail")
            self.assertIn("LEDGER_VERIFICATION_FAILED", record["review_reasons"])
            self.assertTrue((staged / "ledger_report.json").is_file())

    def test_blank_eligible_member_cannot_delete_obscured_only_foreground(self):
        for visibility in ("occluded", "usable"):
            with self.subTest(visibility=visibility):
                ink = ledger_fixture.dot()
                mask = np.ones(ink.shape[:2], bool) if visibility == "occluded" else np.zeros(ink.shape[:2], bool)
                members = [ledger_fixture.member(ink, "blocked", 0., **{visibility: mask}),
                           ledger_fixture.member(ledger_fixture.paper(), "blank", 2.)]
                ledger = rl.record_obligations(source_video="synthetic", display_id="d", occurrence_id="o", members=members)
                self.assertGreater(len(ledger["items"]), 0)
                self.assertTrue(all(i["class"] == "ambiguous" for i in ledger["items"]))
                self.assertEqual(ledger["displays"][0]["raw_foreground_uninventoried_px"], 0)
                ledger_fixture.place(ledger)
                self.assertEqual(rl.verify_pages(ledger, [ledger_fixture.paper()])["status"], "review_required")
                self.assertEqual(rl.verify_pages(ledger, [ink])["status"], "review_required")
                # Explicit candidate selection also cannot make omitted ink vanish.
                omitted = rl.record_obligations(source_video="synthetic", display_id="d", occurrence_id="o",
                                                members=members, candidates=[[60, 40, 70, 50]])
                self.assertGreater(omitted["displays"][0]["raw_foreground_uninventoried_px"], 0)

    def test_pruning_persists_obligations_and_moves_raw_alternative_out_of_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            frames = workspace / "manifest" / "frames"
            frames.mkdir(parents=True)
            ledger = ledger_fixture.snapshot(ledger_fixture.dot())
            item = ledger["items"][0]
            raw = rl.unpack_crop(item["evidence"][0]["raw_patch"])
            artifact = frames / "alternative.png"
            cv2.imwrite(str(artifact), raw)
            ledger["observations"][0]["terminal"] = "unresolved"
            ledger["dispositions"].append({"kind": "unresolved_alternative", "terminal":"unresolved", "item_id": item["id"],
                                           "observation_id": "obs-0", "review_artifact": str(artifact)})
            record = {"workspace": str(workspace), "ledger": ledger, "dev_ledger": True}
            rp.prune_frames(record)
            self.assertFalse(frames.exists())
            persisted = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            alternative = Path(persisted["dispositions"][0]["review_artifact"])
            self.assertTrue(alternative.is_file())
            self.assertTrue(np.array_equal(cv2.imread(str(alternative)), raw))
            self.assertEqual(rl.verify_pages(persisted, [ledger_fixture.paper()])["status"], "review_required")

    def test_static_colored_rectangle_over_staff_requires_review_and_retains_frames(self):
        image = np.full((120, 240, 3), 255, np.uint8)
        for y in (35, 47, 59, 71, 83):
            cv2.line(image, (10, y), (230, y), (0, 0, 0), 1)
        image[30:90, 90:120] = (240, 170, 100)
        _out, info = rs.compose_members([image.copy() for _ in range(4)], 12.)
        self.assertGreater(info["unrecovered_columns"], 0)
        systems = [{"id": "s", "issues": ["OVERLAY_COVERS_NOTATION"],
                    "strip": {"unrecovered_columns": info["unrecovered_columns"]}}]
        reasons = rp.source_review_reasons({"class": sc.CLASS_LIGHT_PAPER}, systems)
        self.assertIn("OVERLAY_UNRECOVERED", reasons)
        self.assertIn("OVERLAY_COVERS_NOTATION", reasons)
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp) / "manifest" / "frames"
            frames.mkdir(parents=True)
            cv2.imwrite(str(frames / "raw.png"), image)
            record = {"workspace": tmp, "systems": systems, "source_class": {"class": sc.CLASS_LIGHT_PAPER}}
            rp.prune_frames(record)
            self.assertFalse(record["frames_pruned"])
            self.assertTrue((frames / "raw.png").is_file())
            self.assertTrue(np.array_equal(cv2.imread(str(frames / "raw.png")), image))
            self.assertEqual(record["overlay_evidence_path"], str(Path(tmp) / "overlay_review_evidence.json"))
            self.assertTrue((Path(tmp) / "overlay_review_evidence.json").is_file())


class ExportGateProbe(unittest.TestCase):
    def setUp(self):
        self.flow = flow_fixture.ReflowJobFlowTest()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)

    @staticmethod
    def reason_codes(reasons):
        return {r["code"] if isinstance(r, dict) else r for r in reasons}

    def test_initial_without_raw_hooks_B_C_pass_and_unknown_source_stays_in_review(self):
        job = self.flow.run_job(self.flow.record(), lambda *_a, **_kw: [])
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.result["reflow_state"], "review_required")
        self.assertTrue(job.result["review_required"])
        self.assertNotIn("LEDGER_UNASSESSED", self.reason_codes(job.result["review_reasons"]))
        self.assertEqual(job.result["reflow"]["ledger_verification"]["assessment"], "pass")
        self.assertTrue((Path(job.artifact_dir) / "export" / "ledger_report.json").is_file())

    def test_initial_pdf_fail_blocks_install_but_review_export_remains_possible(self):
        record = self.flow.record()
        failed = {"status": "fail", "issues": [{"code": "PDF_CONTRACT_VIOLATION", "detail": "contract probe"}]}
        with patch.object(rl, "check_pdf_contract", return_value=failed) as verifier:
            job = self.flow.run_job(record, lambda *_a, **_kw: [], export={"formats": ["pdf"]})
        self.assertTrue(verifier.called)
        self.assertIn("export_staged_", str(verifier.call_args.args[0]))
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "LEDGER_VERIFICATION_FAILED")
        self.assertEqual(job.result["reflow_state"], "ledger_failed")
        self.assertFalse((Path(job.artifact_dir) / "export").exists())
        self.assertTrue((self.flow.ws / "ledger_last_attempt.json").is_file())
        with patch("app.main.job_store", self.flow.store):
            response = main.review_export(job.id, JobReviewExportRequest(keep_captures=[record["systems"][0]["strip_path"]], formats=["pdf"]))
        self.assertTrue(response.pdf)
        self.assertTrue(response.review_required)  # unknown source still needs human review
        self.assertNotIn("LEDGER_UNASSESSED", self.reason_codes(response.review_reasons))

    def test_rebuild_pdf_fail_keeps_previous_files_and_result(self):
        record = self.flow.record()
        job = self.flow.run_job(record, lambda *_a, **_kw: [])
        before = flow_fixture.digest(Path(job.artifact_dir) / "export")
        result_before = json.loads(json.dumps(job.result))
        failed = {"status": "fail", "issues": [{"code": "PDF_CONTRACT_VIOLATION", "detail": "contract probe"}]}
        with patch("app.main.job_store", self.flow.store), patch.object(rl, "check_pdf_contract", return_value=failed) as verifier:
            with self.assertRaises(HTTPException) as ctx:
                main.review_export(job.id, JobReviewExportRequest(keep_captures=[record["systems"][0]["strip_path"]], formats=["pdf"]))
        self.assertIn("LEDGER_VERIFICATION_FAILED", ctx.exception.detail)
        self.assertIn("export_staged_", str(verifier.call_args.args[0]))
        self.assertEqual(flow_fixture.digest(Path(job.artifact_dir) / "export"), before)
        self.assertEqual(self.flow.store.get(job.id).result, result_before)

    def test_rebuild_reports_unassessed_and_preserves_overlay_reasons(self):
        record = self.flow.record()
        record["source_class"] = {"class": sc.CLASS_LIGHT_PAPER}
        record["systems"][0]["issues"] = ["OVERLAY_UNRECOVERED", "OVERLAY_COVERS_NOTATION"]
        record["review_reasons"] = rp.source_review_reasons(record["source_class"], record["systems"])
        record["review_required"] = True
        job = self.flow.run_job(record, lambda *_a, **_kw: [], export={"formats": ["pdf"]})
        self.assertTrue(job.result["review_required"])
        with patch("app.main.job_store", self.flow.store), patch.object(rp.vb, "verify_plan", side_effect=RuntimeError("unassessed probe")), \
                self.assertLogs("app.pipeline.reflow_pipeline", level="ERROR"):
            response = main.review_export(job.id, JobReviewExportRequest(keep_captures=[record["systems"][1]["strip_path"]], formats=["pdf"]))
        self.assertTrue(response.review_required)
        self.assertTrue({"LEDGER_UNASSESSED", "OVERLAY_UNRECOVERED", "OVERLAY_COVERS_NOTATION"}
                        <= self.reason_codes(response.review_reasons))
        self.assertEqual(self.flow.store.get(job.id).result["reflow_state"], "review_required")
        ledger_reason = next(r for r in response.review_reasons if isinstance(r, dict) and r["code"] == "LEDGER_UNASSESSED")
        self.assertIn(" / ", ledger_reason["text"])
