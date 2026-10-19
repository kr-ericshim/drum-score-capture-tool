"""I-2: real staged files, lightweight app gate, and transactional negative controls."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app import main
from app.job_store import JobStatus
from app.pipeline import reflow_pipeline as rp, reflow_ledger as rl
from app.pipeline import reflow_verify_page as vp, reflow_verify_strip as va
from app.pipeline import export as exports
from app.schemas import JobReviewExportRequest
import test_reflow_review_export as flow_fixture
import test_ledger_integration_pipeline as fixtures
from test_export_lossless_pdf import fixture_pdf


class ExportLightGateTests(unittest.TestCase):
    def setUp(self):
        self.flow = flow_fixture.ReflowJobFlowTest()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)

    def record(self, attached_dot=False):
        record = fixtures.fixture(self.flow.ws)
        if attached_dot:
            system = record["systems"][0]
            image = cv2.imread(system["strip_path"])
            ox, oy = system["strip"]["box_crop"][:2]
            self.dot = [420-ox, 60-oy, 423-ox, 65-oy]
            self.staff_row = 62-oy
            a, b, c, d = self.dot
            image[b:d, a:c] = 0
            cv2.imwrite(system["strip_path"], image)
        return record

    def run_job(self, record, **options):
        return self.flow.run_job(record, lambda *_a, **_kw: [], export={"formats": ["pdf", "png"]}, **options)

    def erase_after_plan(self, record):
        original = exports.export_composed_pages
        def write(**kw):
            result = original(**kw)
            system = record["systems"][0]
            image = cv2.imread(system["strip_path"])
            a, b, c, d = self.dot
            image[b:d, a:c] = 255
            image[self.staff_row, a:c] = 0  # erase only the attached dot; keep the staff
            cv2.imwrite(system["strip_path"], image)
            return result
        return patch.object(exports, "export_composed_pages", side_effect=write)

    def codes(self, job):
        return {r["code"] if isinstance(r, dict) else r for r in job.result["review_reasons"]}

    def test_clean_measure_and_whole_export_install_without_A_or_raw_verifier(self):
        for measure in (False, True):
            with self.subTest(measure=measure):
                record = self.record()
                Path(record["ledger_base_path"]).unlink()  # B/C have no base-ledger dependency
                with patch.object(va, "verify_strip", side_effect=AssertionError("A is offline only")), \
                        patch.object(rl, "verify_pdf", side_effect=AssertionError("retired export verifier")), \
                        patch.object(rp, "build_delivered_ledger", side_effect=AssertionError("retired projection")):
                    job = self.run_job(record, measure_reflow=measure)
                self.assertEqual(job.status, JobStatus.DONE, job.message)
                self.assertEqual(job.result["reflow"]["ledger_summary"]["status"], "pass")
                self.assertEqual(job.result["reflow_state"], "done")
                self.assertTrue(Path(job.result["pdf"]).is_file())
                self.assertTrue(all(Path(p).is_file() for p in job.result["images"]))
                if measure:
                    self.assertEqual(job.result["reflow"]["page_plan"]["measure_reflow"]["status"], "measure_lines")
                report = json.loads((Path(job.result["output_dir"])/"ledger_report.json").read_text(encoding="utf-8"))
                print(f"LIGHT_GATE measure={measure} seconds={report['gate_seconds']:.6f} stages={report['stage_seconds']}")

    def test_dev_only_codes_stay_out_of_the_review_items(self):
        record = self.record()
        original = rp.vb.verify_plan
        def finding(*args, **kw):
            cert = original(*args, **kw)
            cert["findings"].append({"stage": "B", "severity": "fail", "code": "PLAN_INVALID", "detail": {"reason": "probe"}})
            return cert
        with patch.object(rp.vb, "verify_plan", side_effect=finding):
            job = self.run_job(record, measure_reflow=False)
        self.assertEqual(job.status, JobStatus.DONE)
        summary = job.result["reflow"]["ledger_summary"]
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["review_hypotheses"], 0)
        self.assertEqual(summary["dev_issue_counts"], {"PLAN_INVALID": 1})
        dev = json.loads((Path(job.result["output_dir"])/"verify_dev_findings.json").read_text(encoding="utf-8"))
        self.assertEqual(dev["issue_counts"], {"PLAN_INVALID": 1})
        self.assertNotIn("LEDGER_REVIEW_REQUIRED", self.codes(job))

    def test_erased_staff_attached_dot_fails_C_but_installs_for_review_with_contiguous_crop(self):
        record = self.record(attached_dot=True)
        # The crop/endpoint path is tested with this code made user-visible (it is dev-only by default).
        with self.erase_after_plan(record), patch.object(rp, "USER_VISIBLE_CODES", rp.USER_VISIBLE_CODES | {"DELIVERED_EXTRA_INK"}):
            job = self.run_job(record, measure_reflow=False)
        self.assertEqual(job.status, JobStatus.DONE, job.message)
        self.assertEqual(job.result["reflow_state"], "review_required")
        self.assertIn("LEDGER_REVIEW_REQUIRED", self.codes(job))
        output = Path(job.result["output_dir"])
        cert_c = json.loads((output/"verify_C.json").read_text(encoding="utf-8"))
        self.assertEqual(cert_c["status"], "fail")  # local loss cannot be diluted into a staff component
        self.assertTrue(any(f["code"] == "DELIVERED_EXTRA_INK" for f in cert_c["findings"]))
        with patch("app.main.job_store", self.flow.store):
            endpoint = main.get_review_hypotheses(job.id).model_dump()
        finding = next(e for e in endpoint["hypotheses"] if e["code"] == "DELIVERED_EXTRA_INK")
        self.assertTrue(Path(finding["raw_crop"]).is_file())
        self.assertTrue(Path(finding["primary_crop"]).is_file())
        raw_json = json.loads((output/"review_hypotheses.json").read_text(encoding="utf-8"))
        entry = next(e for e in raw_json["hypotheses"] if e["id"] == finding["id"])
        self.assertEqual(entry["raw_crop_kind"], "source_strip")
        # Independently reproduce an ordinary rectangular page crop. No inverse
        # mapping, discontinuous grid, or unexplained white columns is allowed.
        actual = vp.decode_lossless_pdf(job.result["pdf"], profile="lossless")[finding["page_index"]-1]
        cert_b = json.loads((output/"verify_B.json").read_text(encoding="utf-8"))
        matrix = np.asarray(cert_b["instances"][0]["transform"][1]["matrix"])
        gap = record["systems"][0]["strip"]["staff_gap_px"]
        a, b, c, d = entry["bbox"]
        pad = 2*gap*abs(matrix[0, 0])
        a, b = max(0, int(np.floor(a-pad))), max(0, int(np.floor(b-pad)))
        c, d = min(actual.shape[1], int(np.ceil(c+pad))), min(actual.shape[0], int(np.ceil(d+pad)))
        delivered_crop = cv2.imread(finding["primary_crop"], cv2.IMREAD_GRAYSCALE)
        self.assertLessEqual(max(delivered_crop.shape), 480)
        np.testing.assert_array_equal(delivered_crop, actual[b:d, a:c])
        self.assertEqual(endpoint["counts"], job.result["reflow"]["ledger_summary"]["counts"])

    def test_contract_violation_blocks_initial_export_and_names_check(self):
        record = self.record()
        original = exports.export_composed_pages
        def invalid(**kw):
            result = original(**kw)
            fixture_pdf(Path(result["pdf"]), page_extra=b" /Rotate 90")
            return result
        with patch.object(exports, "export_composed_pages", side_effect=invalid):
            job = self.run_job(record)
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "LEDGER_VERIFICATION_FAILED")
        self.assertIn("check_pdf_contract", job.message)
        self.assertFalse((Path(job.artifact_dir)/"export").exists())
        self.assertEqual(job.result["images"], [])

    def tampering_installer(self, suffix):
        original = main._install_staged_export_workspace
        def install(**kw):
            commit = original(**kw)
            path = next(p for p in kw["target_workspace"].rglob('*') if p.suffix == suffix)
            path.write_bytes(path.read_bytes()+b"tampered after check")
            return commit
        return patch.object(main, "_install_staged_export_workspace", side_effect=install)

    def test_installed_pdf_and_png_tampering_blocks_and_removes_initial_files(self):
        for suffix in (".pdf", ".png"):
            with self.subTest(suffix=suffix), self.tampering_installer(suffix):
                job = self.run_job(self.record())
                self.assertEqual(job.error_code, "LEDGER_VERIFICATION_FAILED")
                self.assertIn("INSTALLED_ARTIFACT_DIGEST", job.message)
                self.assertFalse((Path(job.artifact_dir)/"export").exists())

    def test_preinstall_tampering_is_blocked(self):
        original = main._verify_reflow_ledger
        def check(*args):
            binding = original(*args)
            Path(args[1]["pdf"]).write_bytes(b"changed between check and install")
            return binding
        with patch.object(main, "_verify_reflow_ledger", side_effect=check):
            job = self.run_job(self.record())
        self.assertEqual(job.error_code, "LEDGER_VERIFICATION_FAILED")
        self.assertIn("STAGED_ARTIFACT_DIGEST", job.message)
        self.assertFalse((Path(job.artifact_dir)/"export").exists())

    def test_B_and_C_exceptions_are_unassessed_and_files_installed(self):
        for stage, function in ((rp.vb, "verify_plan"), (rp.vp, "verify_pages")):
            with self.subTest(function=function), patch.object(stage, function, side_effect=RuntimeError("probe")):
                with self.assertLogs("app.pipeline.reflow_pipeline", level="ERROR"):
                    job = self.run_job(self.record())
                self.assertEqual(job.status, JobStatus.DONE)
                summary = job.result["reflow"]["ledger_summary"]
                self.assertEqual(summary["status"], "unassessed")
                self.assertTrue(any(e["type"] == "RuntimeError" for e in summary["exceptions"].values()))
                self.assertTrue(Path(job.result["pdf"]).is_file())
                self.assertEqual(summary["counts"]["pages"], 1)

    def test_review_export_nonblocking_finding_then_digest_failure_restores_previous_export(self):
        record = self.record()
        job = self.run_job(record, measure_reflow=False)
        request = JobReviewExportRequest(keep_captures=[record["systems"][0]["strip_path"]], formats=["pdf", "png"])
        original = rp.vb.verify_plan
        def finding(*args, **kw):
            cert = original(*args, **kw)
            cert["findings"].append({"stage": "B", "severity": "fail", "code": "PLAN_INVALID", "detail": {"reason": "probe"}})
            return cert
        with patch("app.main.job_store", self.flow.store), patch.object(rp.vb, "verify_plan", side_effect=finding), \
                patch.object(rp, "USER_VISIBLE_CODES", rp.USER_VISIBLE_CODES | {"PLAN_INVALID"}):
            response = main.review_export(job.id, request)
        self.assertTrue(response.review_required)
        self.assertTrue(Path(response.pdf).is_file())
        output = Path(job.artifact_dir)/"export"
        before = flow_fixture.digest(output)
        result_before = json.loads(json.dumps(self.flow.store.get(job.id).result))
        with patch("app.main.job_store", self.flow.store), self.tampering_installer(".pdf"):
            with self.assertRaises(HTTPException) as caught:
                main.review_export(job.id, request)
        self.assertIn("INSTALLED_ARTIFACT_DIGEST", caught.exception.detail)
        self.assertEqual(flow_fixture.digest(output), before)
        self.assertEqual(self.flow.store.get(job.id).result, result_before)

    def test_offline_tool_runs_A_B_C_and_tampered_evidence_fails(self):
        record = self.record()
        job = self.run_job(record, measure_reflow=False)
        spec = importlib.util.spec_from_file_location("verify_job", Path(__file__).parents[1]/"tools"/"verify_job.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.verify_job(self.flow.ws, artifacts=Path(job.result["output_dir"]), output=self.flow.root/"offline")
        self.assertEqual(set(report["stage_seconds"]), {"A", "B", "C"})
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertTrue((self.flow.root/"offline"/"verify_report.json").is_file())
        artifact_report = module.verify_job(Path(job.result["output_dir"]), output=self.flow.root/"artifact-offline")
        self.assertEqual(artifact_report["status"], "pass", artifact_report["issues"])
        base = json.loads(Path(record["ledger_base_path"]).read_text(encoding="utf-8"))
        obs = base["observations"][0]
        image = cv2.imread(obs["frame_path"])
        image[0, 0] = 0
        cv2.imwrite(obs["frame_path"], image)
        report = module.verify_job(self.flow.ws, artifacts=Path(job.result["output_dir"]), output=self.flow.root/"tampered")
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any(f["code"] == "EVIDENCE_INTEGRITY" for f in report["issues"]))


if __name__ == "__main__":
    unittest.main()
