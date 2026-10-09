"""Dev source obligations are opt-in; the app's B/C gate stays independent."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.schemas import JobCreate, JobOptions
from app.pipeline import reflow_pipeline as rp, reflow_strips as rs, reflow_occurrences as ro
from app.pipeline import reflow_jump as rj, reflow_ledger as rl, reflow_ledger_assembly as assembly
from app.pipeline import export as exports, source_class as sc, system_tracking as stk
from reflow_fixture import build, loader
from test_ledger_integration_pipeline import store_frames
from test_reflow_visibility_marks import paper, system_case
from test_audit5_hiding import fixture as hidden_fixture
from test_ledger_hooks_jump import chain_fixture


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class DevLedgerOptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"REFLOW_DEV_LEDGER": "0"})
        env.start()
        self.addCleanup(env.stop)

    def analyse(self, root, *, dev=False, env=False):
        image = paper()
        image[112:115, 420:423] = 0
        manifest, images = build([(k*.25, image.copy()) for k in range(8)])
        def sampled(**_kw):
            store_frames(manifest, loader(images), root)
            return manifest
        with patch.dict(os.environ, {"REFLOW_DEV_LEDGER": "1" if env else "0"}), \
                patch.object(rp, "classify_source_class", return_value={"class": sc.CLASS_LIGHT_PAPER}), \
                patch.object(rp.ob, "build_manifest", side_effect=sampled):
            return rp.analyse_source(video_path=self.root/"synthetic.mp4", roi=[[0,0],[800,0],[800,160],[0,160]],
                                     workspace=root, ledger=JobOptions(detect={"roi": [[0,0],[800,0],[800,160],[0,160]]}, dev_ledger=dev).dev_ledger)

    def compose(self, record, *, measure=False, name="export"):
        sink = {}
        plan, pages = rp.compose_systems(record["systems"], workspace=Path(record["workspace"]),
            all_systems=record["systems"], measure_reflow=measure, ledger_sink=sink)
        staged = Path(record["workspace"])/name
        result = exports.export_composed_pages(pages=pages, formats=["pdf", "png"], workspace=staged, logger=lambda _m: None)
        return sink, staged, result

    def test_main_threads_job_option_to_analysis(self):
        for dev in (False, True):
            root = self.root/f"job-{dev}"
            root.mkdir()
            video = root/"source.mp4"
            video.write_bytes(b"fixture")
            store = JobStore(root)
            payload = JobCreate(source_type="file", file_path=str(video), options={
                "detect": {"roi": [[0,0],[800,0],[800,160],[0,160]]}, "dev_ledger": dev})
            store.create(Job(id="probe", source_type="file", file_path=str(video), youtube_url=None,
                options=payload.options.model_dump(), artifact_dir=str(root/"artifacts"), status=JobStatus.QUEUED))
            with patch.object(main, "job_store", store), \
                    patch.object(main, "_analyze_roi_health", return_value={"diagnostics": []}), \
                    patch.object(rp, "analyse_source", side_effect=rp.NoSystemsError("probe")) as analyse:
                main._execute_job("probe", payload)
            self.assertEqual(analyse.call_args.kwargs["ledger"], dev)

    def test_default_analysis_skips_all_source_hooks_and_light_gate_passes(self):
        self.assertFalse(JobOptions(detect={"roi": [[0,0],[800,0],[800,160],[0,160]]}).dev_ledger)
        with patch.object(assembly, "inventory_observations", side_effect=AssertionError("dev inventory")), \
                patch.object(assembly, "annotate_from_tracking", side_effect=AssertionError("dev tracking")), \
                patch.object(rp, "_build_base_ledger", side_effect=AssertionError("dev base")), \
                patch.object(rs, "_strip_ledger", side_effect=AssertionError("dev strip hook")), \
                patch.object(rl, "record_obligations", side_effect=AssertionError("dev obligations")):
            record = self.analyse(self.root/"default")
        workspace = Path(record["workspace"])
        self.assertFalse(record["dev_ledger"])
        self.assertFalse((workspace/"ledger_base.json").exists())
        self.assertFalse((workspace/"ledger_evidence").exists())
        self.assertTrue(json.loads((workspace/"ledger_chains.json").read_text()))
        for measure in (False, True):
            sink, staged, result = self.compose(record, measure=measure, name=f"export-{measure}")
            report = rp.verify_light_deliverable(record, result, staged, sink=sink)
            self.assertEqual(report["status"], "pass", report)
            self.assertFalse(report["exceptions"])
            self.assertEqual(set(report["stage_seconds"]), {"B", "C"})
            self.assertTrue(sink["placements"])
        with patch.object(assembly, "retain_evidence", side_effect=AssertionError("dev retention")), \
                patch.object(rp, "persist_ledger_evidence", side_effect=AssertionError("dev retention")):
            rp.prune_frames(record)
        self.assertTrue(record["frames_pruned"])
        self.assertFalse((workspace/"ledger_evidence").exists())

    def test_stage_C_erased_delivered_dot_is_user_visible_without_source_ledger(self):
        record = self.analyse(self.root/"erased")
        sink, staged, result = self.compose(record)
        # Replace the delivered raster after composition, keeping the committed source strip.
        sid = record["systems"][0]["id"]
        strip = record["systems"][0]["strip"]
        dot = [420-strip["box_crop"][0], 112-strip["box_crop"][1], 423-strip["box_crop"][0], 115-strip["box_crop"][1]]
        cert = rp.vb.verify_plan(rp.strip_snapshots({sid: cv2.imread(sink["strip_paths"][sid])}), sink["plan"], sink,
                                 {sid: cv2.imread(sink["strip_paths"][sid])}, systems=sink["systems"])
        inst = cert["instances"][0]
        matrix = np.eye(3)
        for transform in inst["transform"]:
            matrix = np.asarray(transform["matrix"]) @ matrix
        a, b = np.floor((matrix @ [dot[0], dot[1], 1])[:2]-2).astype(int)
        c, d = np.ceil((matrix @ [dot[2], dot[3], 1])[:2]+2).astype(int)
        page = sink["pages"][inst["page_index"]].copy()
        page[b:d, a:c] = 255
        changed = exports.export_composed_pages(pages=[page], formats=["pdf", "png"], workspace=staged, logger=lambda _m: None)
        report = rp.verify_light_deliverable(record, changed, staged, sink=sink)
        self.assertEqual(report["status"], "review_required", report)
        self.assertTrue(any(i["stage"] == "C" and i["code"] == "DELIVERED_FEATURE_MISSING" for i in report["issues"]), report)
        self.assertIn("DELIVERED_FEATURE_MISSING", rp.USER_VISIBLE_CODES)

    def test_dev_option_and_env_create_base_and_offline_tool_runs(self):
        for env in (False, True):
            record = self.analyse(self.root/f"dev-{env}", dev=not env, env=env)
            self.assertTrue(record["dev_ledger"])
            self.assertTrue(Path(record["ledger_base_path"]).is_file())
            sink, staged, result = self.compose(record)
            rp.verify_light_deliverable(record, result, staged, sink=sink)
            rp.prune_frames(record)
            spec = importlib.util.spec_from_file_location("dev_verify_job", Path(__file__).parents[1]/"tools"/"verify_job.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            report = module.verify_job(Path(record["workspace"]), artifacts=staged, output=self.root/f"offline-{env}")
            self.assertEqual(set(report["stage_seconds"]), {"A", "B", "C"})
            self.assertFalse(report["exceptions"], report)
            self.assertEqual(report["status"], "pass", report["issues"])

    def test_analysis_pixels_occurrences_jump_and_plan_hashes_match(self):
        records = [self.analyse(self.root/f"hash-{dev}", dev=dev) for dev in (False, True)]
        for filename in ("occurrences.json", "jump.json"):
            values = [json.loads((Path(r["workspace"])/filename).read_text()) for r in records]
            # analyse_jumps includes elapsed wall time, which is intentionally variable.
            if filename == "jump.json":
                for v in values:
                    v.pop("seconds", None)
            self.assertEqual(digest(values[0]), digest(values[1]), filename)
        pngs = [hashlib.sha256(Path(r["systems"][0]["strip_path"]).read_bytes()).hexdigest() for r in records]
        self.assertEqual(*pngs)
        plans = [self.compose(r)[0]["plan"] for r in records]
        self.assertEqual(digest(plans[0]), digest(plans[1]))

    def test_hidden_occurrence_hooks_are_optional_and_public_outputs_match(self):
        tracking, manifest, images = hidden_fixture()
        on = ro.build_occurrences(tracking, manifest, loader(images), ledger=True)
        with patch.object(rl, "record_obligations", side_effect=AssertionError("hidden dev obligations")):
            off = ro.build_occurrences(tracking, manifest, loader(images), ledger=False)
        on.pop("ledger")
        self.assertNotIn("ledger", off)
        self.assertEqual(digest(on), digest(off))

    def test_jump_registration_public_hash_matches_without_display_ledger(self):
        from test_reflow_jump import JUMP, VIEW_W, jump_frames, long_score
        score = long_score(bars=12)
        manifest, images = build(jump_frames(score, list(range(0, score.shape[1]-VIEW_W+1, JUMP))))
        load = loader(images)
        tracking = stk.build_episodes(manifest, load)
        on = rj.analyse_jumps(tracking, manifest, load, ledger=True)
        with patch.object(rj, "_display_ledger", side_effect=AssertionError("dev display hook")):
            off = rj.analyse_jumps(tracking, manifest, load, ledger=False,
                evidence_dir=self.root/"disabled-jump-evidence")
        self.assertTrue(on["runs"])
        self.assertNotIn("ledger_displays", off)
        self.assertFalse((self.root/"disabled-jump-evidence").exists())
        on.pop("ledger_displays")
        for value in (on, off):
            value.pop("seconds")
        self.assertEqual(digest(on), digest(off))

    def test_jump_obligations_are_optional_and_panorama_pixels_match(self):
        manifest, tracking, jump, images, composites, covered = chain_fixture()
        results = []
        for dev in (False, True):
            directory = self.root/f"jump-{dev}"
            with patch.object(rj, "chunk_cuts", return_value=([120,230], {})):
                if dev:
                    results.append(rj.build_jump_systems(jump, tracking, manifest, directory,
                        composites=composites, covered=covered, load=lambda o: images[o["id"]], ledger=True))
                else:
                    with patch.object(rj, "_display_ledger", side_effect=AssertionError("dev jump hook")), \
                            patch.object(rl, "record_obligations", side_effect=AssertionError("dev jump obligations")):
                        results.append(rj.build_jump_systems(jump, tracking, manifest, directory,
                            composites=composites, covered=covered, load=lambda o: images[o["id"]], ledger=False,
                            evidence_dir=directory/"ledger_evidence"))
                    self.assertFalse((directory/"ledger_evidence").exists())
        self.assertEqual(len(results[0]), len(results[1]))
        for (off_occ, off), (on_occ, on) in zip(*results):
            self.assertNotIn("ledger", off)
            self.assertIn("ledger", on)
            self.assertEqual(off["ledger_chain"], on["ledger_chain"])
            self.assertEqual(off["jump"], on["jump"])
            self.assertEqual(hashlib.sha256(Path(off["path"]).read_bytes()).hexdigest(),
                             hashlib.sha256(Path(on["path"]).read_bytes()).hexdigest())

    def test_shifted_faded_unsampled_members_keep_strip_and_bundle_pixels(self):
        images = [paper() for _ in range(40)]
        images[1][112:115, 420:423] = 0  # member outside the sampled composite
        images[2] = cv2.warpAffine(images[2], np.float32([[1,0,4],[0,1,0]]), (800,160), borderValue=(255,255,255))
        images[3] = np.minimum(images[3], 190).astype(np.uint8)
        system, manifest, load = system_case(images)
        outputs = [rs.build_strip(system, manifest, load, chrome=False, ledger=dev) for dev in (False, True)]
        self.assertEqual(hashlib.sha256(outputs[0][0].tobytes()).hexdigest(), hashlib.sha256(outputs[1][0].tobytes()).hexdigest())
        self.assertEqual(outputs[0][1]["member_registration"], outputs[1][1]["member_registration"])
        off, on = outputs[0][1], outputs[1][1]
        self.assertEqual(len(off["_alternate_images"]), len(on["_alternate_images"]))
        for a, b in zip(off["_alternate_images"], on["_alternate_images"]):
            self.assertEqual(hashlib.sha256(a.tobytes()).hexdigest(), hashlib.sha256(b.tobytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
