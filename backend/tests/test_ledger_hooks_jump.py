"""Hook 3 raw inventory and pixel-centre geometry, independent of preservation flags."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_jump as rj
from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_strips as rs


def chain_fixture(count=2, members=2, width=220, height=160):
    observations, episodes, images, composites = [], [], {}, {}
    lines = [60., 70., 80., 90., 100.]
    for k in range(count):
        did = f"e{k}"
        image = np.full((height, width, 3), 255, np.uint8)
        for y in lines:
            cv2.line(image, (0, int(y)), (width - 1, int(y)), (30, 30, 30), 1)
        cv2.circle(image, (70 if k == 0 else width - 60, 43 + k), 2, (20, 20, 20), -1)
        if k == 0:
            cv2.circle(image, (105, 45), 2, (20, 20, 20), -1)
            cv2.circle(image, (205, 35), 3, (20, 20, 20), -1)  # discarded overlap conflict
        else:
            cv2.circle(image, (115, 47), 2, (20, 20, 20), -1)
        ids = []
        for m in range(members):
            oid = f"{did}-o{m}"
            ids.append(oid)
            images[oid] = image.copy()
            observations.append({"id": oid, "t_sec": 4*k + m, "crop_size": [width, height],
                                 "system_regions": [{"region_id": "r", "staff_y": lines,
                                                     "staff_x": [0, width - 1], "row_band": [0, 0, width, height]}]})
        composites[did] = image
        episodes.append({"id": did, "slot_id": "s", "t_start": 4*k, "t_end": 4*k + 3,
                         "staff_gap_px": 10., "staff_top_y": 60., "confirmed": True,
                         "layout": "horizontal_scroll", "observation_ids": ids, "region_ids": ["r"]*members})
    seams = [{"id": f"seam-e{k}-e{k+1}", "slot_id": "s", "a": f"e{k}", "b": f"e{k+1}",
              "verified": True, "status": "verified", "kind": "jump", "dx": 100, "dy": 2,
              "residual": 7., "residual_registration_px": 1.25} for k in range(count - 1)]
    manifest = {"source": {"path": "/synthetic/jump.mp4"}, "source_to_crop": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "observations": observations}
    tracking = {"episodes": episodes}
    jump = {"config": dict(rj.CONFIG), "seams": seams, "slots": [{"slot_id": "s", "panel": {"right": 0}}],
            "runs": [{"slot_id": "s", "panorama_chains": [{"displays": list(composites),
                                                          "break_before": None, "break_after": None}]}]}
    covered = {d: np.zeros(width, bool) for d in composites}
    return manifest, tracking, jump, images, composites, covered


class JumpLedgerHookTests(unittest.TestCase):
    def test_full_raw_inventory_includes_unsampled_shape_reject_and_occlusion(self):
        manifest, tracking, _jump, images, _composites, _covered = chain_fixture(count=1, members=13)
        ep = tracking["episodes"][0]
        images[ep["observation_ids"][0]] = np.pad(images[ep["observation_ids"][0]], ((0, 2), (0, 0), (0, 0)), constant_values=255)
        images[ep["observation_ids"][12]] = cv2.warpAffine(images[ep["observation_ids"][12]],
                                                          np.float32([[1, 0, 1.2], [0, 1, 0]]), (220, 160), borderValue=(255,)*3)
        cv2.circle(images[ep["observation_ids"][2]], (30, 125), 2, (30, 30, 30), -1)
        cv2.line(images[ep["observation_ids"][3]], (45, 0), (45, 159), (30, 100, 220), 3)
        obs_by = {o["id"]: o for o in manifest["observations"]}
        cfg = dict(rj.CONFIG, max_members=5)
        load = lambda o: images[o["id"]]
        plain = rj.display_record(ep, manifest, load, obs_by, cfg, keep_composite=True)
        rec = rj.display_record(ep, manifest, load, obs_by, cfg, keep_composite=True, ledger=True)
        self.assertNotIn("ledger", plain)
        np.testing.assert_array_equal(plain["composite"], rec["composite"])
        fragment = rec["ledger"]
        self.assertEqual(fragment["displays"][0]["observations"], ep["observation_ids"][1:])
        self.assertEqual({oid for d in fragment["displays"] for oid in d["observations"]}, set(ep["observation_ids"]))
        rejected = next(d for d in fragment["displays"] if d["id"] == "jump:e0:rejected:e0-o0")
        self.assertEqual(rejected["shape"], [162, 220])
        self.assertEqual(rejected["observations"], ["e0-o0"])
        self.assertIn({"kind": "display_unresolved", "terminal": "unresolved", "display_id": rejected["id"],
                       "reason": "crop_shape_mismatch"}, fragment["display_dispositions"])
        self.assertEqual(fragment["displays"][0]["raw_foreground_uninventoried_px"], 0)
        assocs = fragment["observation_associations"]
        self.assertEqual([a["obs_id"] for a in assocs if a["role"] == "used"], ["e0-o3", "e0-o6", "e0-o9", "e0-o12"])
        self.assertTrue(any(a["obs_id"] == "e0-o0" and a["reason"] == "crop_shape_mismatch" for a in assocs))
        self.assertTrue(any(a["obs_id"] == "e0-o2" and a["reason"] == "not_sampled_for_composite" for a in assocs))
        self.assertEqual(len({i["id"] for i in fragment["items"]}), len(fragment["items"]))
        uncertain, occluded, inventoried = {}, 0, set()
        for item in fragment["items"]:
            for evidence in item["evidence"]:
                oid = evidence["observation_id"]
                inventoried.add(oid)
                x0, y0, x1, y1 = evidence["native_bbox"]
                np.testing.assert_array_equal(rl.unpack_crop(evidence["raw_patch"]), images[oid][y0:y1, x0:x1])
                tf = evidence["transform"]
                self.assertEqual(tf["registration_shift"], [0, 0])
                self.assertEqual(tf["roi_origin"], [0, 0])
                self.assertEqual(tf["source_to_native"], manifest["source_to_crop"])
                uncertain[oid] = tf["registration_uncertainty"]
                self.assertTrue((rl.unpack_crop(evidence["native_usable_mask"]) == 255).all())
                if oid == "e0-o3":
                    occluded += int((rl.unpack_crop(evidence["native_occluded_mask"]) > 0).sum())
        self.assertEqual(inventoried, set(ep["observation_ids"]))
        self.assertGreater(occluded, 0)
        self.assertGreater(uncertain["e0-o12"], .5)
        self.assertLess(uncertain["e0-o6"], 1e-6)
        json.dumps(fragment, allow_nan=False)

    def _build(self, *, prefix=False, count=2, members=2, cuts=(120, 230), load_raw=True, referenced=False):
        fixture = chain_fixture(count=count, members=members)
        manifest, tracking, jump, images, composites, covered = fixture
        def clef(image, rec):
            if not prefix:
                return {"verified": False, "reason": "fixture_no_clef"}
            patch_image = image[:, :16].copy()
            return {"verified": True, "image": patch_image, "box": [0, 0, 16, image.shape[0]],
                    "staff_top": rec["staff_y_strip"][0], "patch_pixels_sha256": rl.pixels_hash(patch_image)}
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        if referenced:
            frames = Path(td.name) / "frames"
            frames.mkdir()
            for obs in manifest["observations"]:
                path = frames / f"{obs['id']}.png"
                self.assertTrue(cv2.imwrite(str(path), images[obs["id"]]))
                obs.update(frame_path=str(path), pixels_sha256=rl.pixels_hash(images[obs["id"]]))
        with patch.object(rj, "chunk_cuts", return_value=(list(cuts), {})), patch.object(rj, "_clef_prefix", side_effect=clef):
            built = rj.build_jump_systems(jump, tracking, manifest, Path(td.name), composites=composites, covered=covered,
                                          load=(lambda o: images[o["id"]]) if load_raw else None,
                                          evidence_dir=Path(td.name)/"ledger_evidence" if referenced else None, ledger=True)
        return fixture, built

    def test_owner_affines_and_overlap_equivalence_include_conflicts(self):
        fixture, built = self._build()
        _manifest, _tracking, jump, _images, comps, cov = fixture
        seam_of = {(s["a"], s["b"]): s for s in jump["seams"]}
        _pano, info = rj.build_panorama(list(comps), seam_of, comps, cov, 0, 10., rj.CONFIG)
        for owner in info["owners"]:
            x, y = owner["offset_x"], owner["offset_y"]
            self.assertEqual(owner["display_to_panorama"], [[1, 0, x], [0, 1, y], [0, 0, 1]])
            self.assertEqual(owner["owned_cols_display"], [u - x for u in owner["pano_cols"]])
        dispositions = [d for _occ, rec in built for d in rec["ledger"]["display_dispositions"] if d["kind"] == "display_equivalent"]
        self.assertEqual(len(dispositions), 2)
        forward = next(d for d in dispositions if d["display_id"] == "jump:e0")
        self.assertEqual(forward["equivalence_map"], [[1, 0, -100], [0, 1, -2], [0, 0, 1]])
        self.assertEqual(forward["region"], [info["owners"][0]["pano_cols"][1], 0, 220, 160])
        geometric = forward["evidence"]["geometric_registration"]
        self.assertEqual(forward["registration_uncertainty"], max(rj.PRESERVE_CONFIG["match_tol_px"], geometric["residual_px"]))
        self.assertEqual(forward["evidence"]["photometric_residuals"], [7.])
        self.assertTrue(forward["evidence"]["seams"])
        self.assertTrue(forward["evidence"]["panorama_preservation"]["conflicts"])
        self.assertFalse(forward["evidence"]["panorama_preservation"]["content_preserved"])

    def test_owned_dots_map_to_written_png_with_and_without_prefix(self):
        for prefix in (False, True):
            with self.subTest(prefix=prefix):
                fixture, built = self._build(prefix=prefix)
                _manifest, _tracking, _jump, _images, comps, _cov = fixture
                dots = {"e0": [(70, 43), (105, 45)], "e1": [(160, 44), (115, 47)]}
                hits = set()
                display_ids, item_ids, refs = [], [], []
                for _occ, rec in built:
                    written = cv2.imread(rec["path"])
                    display_ids.extend(d["id"] for d in rec["ledger"]["displays"])
                    item_ids.extend(i["id"] for i in rec["ledger"]["items"])
                    refs.extend(rec["ledger_display_refs"])
                    self.assertIsNone(rec["ledger_supersedes"])
                    for chain in rec["ledger_chain"]:
                        did = chain["display_id"].split(":", 1)[1]
                        owner = next(o for o in rec["jump"]["owners"] if o["display"] == did)
                        self.assertEqual(chain["domain_strip"], owner["strip_cols"])
                        matrix = np.array(chain["stages"][0]["matrix"])
                        for x, y in dots[did]:
                            point = matrix @ [x, y, 1]
                            if not owner["strip_cols"][0] <= point[0] < owner["strip_cols"][1]:
                                continue
                            px, py = np.rint(point[:2]).astype(int)
                            self.assertLessEqual(float(np.max(np.abs(point[:2] - [px, py]))), .5)
                            self.assertLess(int(written[py, px].max()), 100)
                            hits.add((did, x, y))
                    if rec["jump"]["clef_prefix"]:
                        generated = rec["ledger_strip_generated"][0]
                        self.assertEqual(generated["source_display_id"], "jump:e0")
                        self.assertEqual(generated["reason"], "jump_clef_prefix")
                        x0, y0, x1, y1 = generated["strip_bbox"]
                        a, b, c, d = generated["source_bbox_display"]
                        self.assertEqual((x1-x0, y1-y0), (c-a, d-b))
                        np.testing.assert_array_equal(written[y0:y1, x0:x1], comps["e0"][b:d, a:c])
                    json.dumps(rec, allow_nan=False)
                self.assertEqual(hits, {(did, x, y) for did, points in dots.items() for x, y in points})
                self.assertEqual(sorted(display_ids), ["jump:e0", "jump:e1"])
                self.assertEqual(len(item_ids), len(set(item_ids)))
                self.assertTrue(refs)
                self.assertTrue(all(r["also_in_strip"].startswith("jmp-") for r in refs))
                self.assertEqual(sum(bool(r.get("ledger_strip_generated")) for _o, r in built), 2 if prefix else 0)

    def test_without_raw_members_is_explicitly_unresolved(self):
        _fixture, built = self._build(load_raw=False)
        unresolved = [d for _occ, rec in built for d in rec["ledger"]["display_dispositions"] if d["kind"] == "display_unresolved"]
        self.assertEqual({d["display_id"] for d in unresolved}, {"jump:e0", "jump:e1"})
        self.assertTrue(all(d["reason"] == "raw_members_unavailable" for d in unresolved))
        self.assertTrue(all(not rec["ledger"]["items"] for _o, rec in built))

    def test_six_display_chain_has_unique_inventory_and_json_safe_records(self):
        _fixture, built = self._build(count=6, members=3, cuts=(120, 230, 340, 450, 560))
        merged = rj._merge_ledger([rec["ledger"] for _occ, rec in built])
        self.assertEqual(len(merged["displays"]), 6)
        self.assertEqual(sum(len(d["observations"]) for d in merged["displays"]), 18)
        self.assertEqual(len({i["id"] for i in merged["items"]}), len(merged["items"]))
        self.assertEqual(len([a for a in merged["observation_associations"] if a["role"] == "offered"]), 18)
        json.dumps([rec for _occ, rec in built], allow_nan=False)

    def test_referenced_chain_resolves_original_frames_and_preserves_evidence_root(self):
        fixture, built = self._build(count=6, members=3, cuts=(120, 230, 340, 450, 560), referenced=True)
        manifest, _tracking, _jump, images, _comps, _covered = fixture
        merged = rj._merge_ledger([rec["ledger"] for _occ, rec in built])
        self.assertEqual(len(merged["displays"]), 6)
        self.assertEqual(len(merged["items"]), 133)
        self.assertTrue(all(d["evidence_mode"] == "referenced" for d in merged["displays"]))
        self.assertTrue(all("evidence_bits" in i and "evidence" not in i for i in merged["items"]))
        self.assertEqual(merged["evidence_root"], built[0][1]["ledger"]["evidence_root"])
        for display in merged["displays"]:
            self.assertEqual(len(display["members"]), 3)
            for member in display["members"]:
                self.assertEqual(member["frame_ref"], {"observation_id": member["observation_id"], "crop_box": [0, 0, 220, 160]})
                self.assertNotIn("canvas_ref", member)
        resolver = rl.EvidenceResolver(dict(merged, observations=manifest["observations"]))
        for item in merged["items"]:
            for evidence in resolver.views(item):
                x0, y0, x1, y1 = evidence["native_bbox"]
                np.testing.assert_array_equal(rl.unpack_crop(evidence["raw_patch"]),
                                              images[evidence["observation_id"]][y0:y1, x0:x1])
        json.dumps([rec for _occ, rec in built], allow_nan=False)

    def test_one_lazy_call_restores_cross_member_protected_support(self):
        manifest, tracking, _jump, images, _comps, _covered = chain_fixture(count=1, members=4)
        ep = tracking["episodes"][0]
        for k, oid in enumerate(ep["observation_ids"]):
            cv2.rectangle(images[oid], (10+20*k, 125), (20+20*k, 135), (30, 30, 30), -1)
        with patch.object(rl, "record_obligations", wraps=rl.record_obligations) as record:
            rec = rj.display_record(ep, manifest, lambda o: images[o["id"]],
                                    {o["id"]: o for o in manifest["observations"]}, rj.CONFIG, ledger=True)
        self.assertEqual(record.call_count, 1)
        members = record.call_args.kwargs["members"]
        self.assertEqual([m["id"] for m in members], ep["observation_ids"])
        self.assertTrue(all(callable(m["image"]) and callable(m["occluded"]) for m in members))
        self.assertTrue(any(i["class"] == "protected" and i["support"]["separated_groups"] == 4 for i in rec["ledger"]["items"]))

    def test_masked_overlap_registration_measures_point_four_pixel_shift(self):
        rng = np.random.default_rng(11)
        gray = np.full((120, 240), 250., np.float32)
        for x, y in rng.integers([12, 12], [228, 108], size=(60, 2)):
            cv2.circle(gray, (int(x), int(y)), 3, 30., -1)
        gray = cv2.GaussianBlur(gray, (9, 9), 1.5)
        a = cv2.cvtColor(np.rint(gray).astype(np.uint8), cv2.COLOR_GRAY2BGR)
        b = cv2.warpAffine(a, np.float32([[1, 0, .4], [0, 1, 0]]), (240, 120), borderValue=(250,)*3)
        a[:, 85:105] = 20
        b[:, 85:105] = 245
        covered = np.zeros(240, bool)
        covered[85:105] = True
        measurement = rj._overlap_registration(a, b, (0, 0), (0, 0), (0, 240), covered, covered)
        self.assertAlmostEqual(measurement["shift_px"][0], .4, delta=.06)
        self.assertAlmostEqual(measurement["shift_px"][1], 0., delta=.06)
        self.assertAlmostEqual(measurement["residual_px"], .4, delta=.06)
        self.assertEqual(measurement["fitted_axes"], [True, True])
        self.assertFalse(measurement["search_boundary"])
        info = {"owners": [{"display": "a", "offset_x": 0, "offset_y": 0, "pano_cols": [0, 120]},
                            {"display": "b", "offset_x": 0, "offset_y": 0, "pano_cols": [120, 240]}]}
        seam = {("a", "b"): {"residual": 100., "residual_registration_px": 100.}}
        preservation = {"version": "fixture", "config": rj.PRESERVE_CONFIG,
                        "displays": [{"display": "a"}, {"display": "b"}], "conflicts": []}
        dispositions = rj._overlap_dispositions(["a", "b"], info, {"a": a, "b": b}, seam, preservation,
                                                {"a": covered, "b": covered})
        equivalent = next(d for d in dispositions["a"] if d["kind"] == "display_equivalent")
        self.assertAlmostEqual(equivalent["evidence"]["geometric_registration"]["residual_px"], .4, delta=.06)
        self.assertEqual(equivalent["registration_uncertainty"], 1.)
        self.assertEqual(equivalent["evidence"]["photometric_residuals"], [100.])

    def test_referenced_shape_reject_keeps_its_canvas_and_unresolved_disposition(self):
        manifest, tracking, _jump, images, _comps, _covered = chain_fixture(count=1, members=3)
        ep = tracking["episodes"][0]
        images["e0-o0"] = np.pad(images["e0-o0"], ((0, 2), (0, 0), (0, 0)), constant_values=255)
        with tempfile.TemporaryDirectory() as td:
            for obs in manifest["observations"]:
                path = Path(td)/f"{obs['id']}.png"
                self.assertTrue(cv2.imwrite(str(path), images[obs["id"]]))
                obs["frame_path"] = str(path)
            with patch.object(rl, "record_obligations", wraps=rl.record_obligations) as record:
                rec = rj.display_record(ep, manifest, lambda o: images[o["id"]],
                                        {o["id"]: o for o in manifest["observations"]}, rj.CONFIG,
                                        ledger=True, evidence_dir=Path(td)/"ledger_evidence")
            self.assertEqual(record.call_count, 2)
            self.assertEqual([len(call.kwargs["members"]) for call in record.call_args_list], [2, 1])
            self.assertTrue(all(callable(m["image"]) for call in record.call_args_list for m in call.kwargs["members"]))
            fragment = rec["ledger"]
            rejected = next(d for d in fragment["displays"] if d["id"] == "jump:e0:rejected:e0-o0")
            self.assertEqual(rejected["members"][0]["frame_ref"], {"observation_id": "e0-o0", "crop_box": [0, 0, 220, 162]})
            self.assertEqual(rejected["shape"], [162, 220])
            self.assertIn({"kind": "display_unresolved", "terminal": "unresolved", "display_id": rejected["id"],
                           "reason": "crop_shape_mismatch"}, fragment["display_dispositions"])
            resolver = rl.EvidenceResolver(dict(fragment, observations=manifest["observations"]))
            for item in fragment["items"]:
                for evidence in resolver.views(item):
                    x0, y0, x1, y1 = evidence["native_bbox"]
                    np.testing.assert_array_equal(rl.unpack_crop(evidence["raw_patch"]),
                                                  images[evidence["observation_id"]][y0:y1, x0:x1])
            json.dumps(fragment, allow_nan=False)

    def test_referenced_occlusion_mask_is_written_once_and_resolved(self):
        manifest, tracking, _jump, images, _comps, _covered = chain_fixture(count=1, members=3)
        cv2.line(images["e0-o0"], (45, 0), (45, 159), (30, 100, 220), 3)
        ep = tracking["episodes"][0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/"ledger_evidence"
            for obs in manifest["observations"]:
                path = Path(td)/f"{obs['id']}.png"
                self.assertTrue(cv2.imwrite(str(path), images[obs["id"]]))
                obs["frame_path"] = str(path)
            rec = rj.display_record(ep, manifest, lambda o: images[o["id"]],
                                    {o["id"]: o for o in manifest["observations"]}, rj.CONFIG, ledger=True, evidence_dir=root)
            fragment = rec["ledger"]
            member = next(m for m in fragment["displays"][0]["members"] if m["observation_id"] == "e0-o0")
            self.assertIsInstance(member["occluded_ref"], dict)
            self.assertEqual(member["usable_ref"], "all")
            path = root/member["occluded_ref"]["path"]
            self.assertEqual(path.read_bytes()[24], 1)  # PNG IHDR bit depth
            self.assertEqual(len(list(root.glob("*.png"))), 1)
            resolver = rl.EvidenceResolver(dict(fragment, observations=manifest["observations"]))
            occluded = sum(int((rl.unpack_crop(e["native_occluded_mask"]) > 0).sum())
                           for item in fragment["items"] for e in resolver.views(item) if e["observation_id"] == "e0-o0")
            self.assertGreater(occluded, 0)
            json.dumps(fragment, allow_nan=False)

    def test_native_scale_feature_detection_and_manifest_threading(self):
        manifest, tracking, jump, images, comps, _covered = chain_fixture()
        manifest["work_scale"] = {"scale": .5}
        obs_by = {o["id"]: o for o in manifest["observations"]}
        eps = {e["id"]: e for e in tracking["episodes"]}
        scales = []
        def modern(*args, memo=None, native_scale=1.0):
            scales.append(native_scale)
            return {"events": []}
        with patch.object(rs, "check_minority_content", new=modern):
            rj.audit_jump_minority(jump, eps, obs_by, comps, lambda o: images[o["id"]], manifest=manifest)
            rj.audit_display_minority(eps["e0"], comps["e0"], obs_by, lambda o: images[o["id"]])
        self.assertEqual(scales, [.5, .5, 1.])
        def legacy(*args, memo=None):
            return {"events": []}
        with patch.object(rs, "check_minority_content", new=legacy):
            self.assertEqual(rj.audit_display_minority(eps["e0"], comps["e0"], obs_by,
                                                      lambda o: images[o["id"]], manifest=manifest)["events"], [])

    def test_fully_nonowning_display_retains_raw_inventory_and_equivalence(self):
        manifest, tracking, jump, images, comps, covered = chain_fixture(count=3)
        for seam in jump["seams"]:
            seam.update(dx=0, dy=0, kind="no_shift")
        with tempfile.TemporaryDirectory() as td, \
                patch.object(rj, "stitch_cut", return_value={"x": 110, "overlap": [0, 220]}), \
                patch.object(rj, "chunk_cuts", return_value=([], {})), \
                patch.object(rj, "_clef_prefix", return_value={"verified": False}):
            built = rj.build_jump_systems(jump, tracking, manifest, Path(td), composites=comps, covered=covered,
                                          load=lambda o: images[o["id"]], ledger=True)
        rec = built[0][1]
        self.assertEqual({d["id"] for d in rec["ledger"]["displays"]}, {"jump:e0", "jump:e1", "jump:e2"})
        self.assertTrue(any(i["display_id"] == "jump:e1" for i in rec["ledger"]["items"]))
        self.assertTrue(any(d["display_id"] == "jump:e1" for d in rec["ledger"]["display_dispositions"]))
        self.assertNotIn("jump:e1", {c["display_id"] for c in rec["ledger_chain"]})

    def test_analyse_returns_json_safe_inventory_after_private_arrays_are_removed(self):
        from reflow_fixture import build, loader
        from test_reflow_jump import JUMP, VIEW_W, jump_frames, long_score
        from app.pipeline import system_tracking as stk
        score = long_score(bars=12)
        manifest, images = build(jump_frames(score, list(range(0, score.shape[1] - VIEW_W + 1, JUMP))))
        load = loader(images)
        tracking = stk.build_episodes(manifest, load)
        jump = rj.analyse_jumps(tracking, manifest, load, keep_composites=True, ledger=True)
        self.assertTrue(jump["runs"])
        expected = {d for r in jump["runs"] for c in r["panorama_chains"] for d in c["displays"]}
        self.assertEqual(set(jump["ledger_displays"]), expected)
        for key in ("_composites", "_covered", "_fixed"):
            jump.pop(key)
        json.dumps(jump, allow_nan=False)

    def test_frozen_jump_config_hash(self):
        self.assertEqual(rj.config_hash(), "2e5887c559828797")


if __name__ == "__main__":
    unittest.main()
