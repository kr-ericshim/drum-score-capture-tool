"""Step 2D hooks: raw inventory, measured maps and cursor proof transport."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import minority_content as mc, reflow_ledger as rl
from app.pipeline import reflow_occurrences as ro, reflow_strips as rs
from app.pipeline import reflow_ledger_assembly as assembly, reflow_render as rr, reflow_layout as layout
from app.pipeline import reflow_boundaries as rb
from reflow_fixture import loader
from test_audit5_hiding import fixture
import test_reflow_strips as strip_fixtures
from test_reflow_strips import full_frames, preview_frames, system_image
from test_reflow_visibility_marks import paper, system_case


def public_record(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def store_frames(manifest, load, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for obs in manifest["observations"]:
        path = directory / f"{obs['id']}.png"
        if not cv2.imwrite(str(path), load(obs)):
            raise RuntimeError("cannot store synthetic frame")
        obs["frame_path"] = str(path.resolve())


class OccurrenceLedgerTest(unittest.TestCase):
    def case(self, gray=None):
        tracking, manifest, images = fixture(gray)
        manifest["video_id"] = "synthetic"
        for obs in manifest["observations"]:
            obs["system_regions"][0]["envelope_bbox"] = [40, 50, 870, 158]
            obs["source_to_crop"] = np.eye(3).tolist()
        return ro.build_occurrences(tracking, manifest, loader(images), ledger=True), manifest, images

    def test_every_candidate_and_remap_including_hidden_fragment(self):
        occ, manifest, images = self.case()
        ledger = occ["ledger"]
        self.assertEqual({d["id"] for d in ledger["displays"]}, {"occ:left", "occ:short", "occ:right"})
        self.assertEqual(len(ledger["occurrence_remaps"]), 3)
        self.assertEqual(len(ledger["observation_associations"]), len(manifest["observations"]))
        short = next(d for d in ledger["displays"] if d["id"] == "occ:short")
        self.assertEqual(short["observations"], ["short-0", "short-1"])
        self.assertTrue(any(i["display_id"] == "occ:short" for i in ledger["items"]))
        self.assertFalse(any(i["display_id"] == "occ:left" for i in ledger["items"]))
        equivalence = next(d for d in ledger["display_dispositions"] if d["display_id"] == "occ:short")
        self.assertEqual(equivalence["kind"], "display_equivalent")
        kept = next(s for s in occ["systems"] if f"strip:{s['id']}" == equivalence["retained_display_id"])
        _, rec = rs.build_strip(kept, manifest, loader(images), chrome=False, ledger=True)
        origin = int(round(80 - ro.WINDOW_ABOVE_GAPS * 12))
        projected = np.array(equivalence["equivalence_map"]) @ [264.5, 95.5 - origin, 1]
        x, y = np.floor(projected[:2]).astype(int)
        b = rec["ledger_canvas_box_crop"]
        canvas = images[kept["observations"][0]["obs_id"]][b[1]:b[3], b[0]:b[2]]
        self.assertTrue((canvas[y, x] < 40).all())
        self.assertTrue(np.allclose(projected[:2], [264.5 - b[0], 95.5 - b[1]]))
        json.dumps(occ)

    def test_listed_exclusion_is_inventory_and_unresolved(self):
        occ, _, _ = self.case(190)
        disposition = next(d for d in occ["ledger"]["display_dispositions"] if d["display_id"] == "occ:short")
        self.assertEqual(disposition["reason"], "excluded_without_equivalence")
        self.assertEqual(disposition["terminal"], "unresolved")
        remap = next(r for r in occ["ledger"]["occurrence_remaps"] if r["root_key"] == "short")
        self.assertFalse(remap["included"])
        self.assertIsNotNone(remap["final_system_id"])
        display = next(d for d in occ["ledger"]["displays"] if d["id"] == "occ:short")
        self.assertTrue(display["inventory_only"])

    def test_unavailable_canvas_origin_is_unresolved(self):
        with patch.object(ro, "_ledger_strip_origin", return_value=None):
            occ, _, _ = self.case()
        d = next(d for d in occ["ledger"]["display_dispositions"] if d["display_id"] == "occ:short")
        self.assertEqual(d["reason"], "equivalence_map_unavailable")

    def test_preview_inventory_survives_without_changing_composite_members(self):
        tracking, manifest, images = fixture()
        e = copy.deepcopy(tracking["episodes"][0])
        e.update(id="preview", role="preview", t_start=0, t_end=0,
                 n_obs=1, observation_ids=["preview-o"], region_ids=["preview-r"])
        obs = copy.deepcopy(manifest["observations"][0])
        obs.update(id="preview-o", t_sec=0)
        obs["system_regions"][0]["region_id"] = "preview-r"
        obs["system_regions"][0]["envelope_bbox"] = [40, 50, 870, 158]
        manifest["observations"].append(obs)
        images["preview-o"] = images["left-0"].copy()
        tracking["episodes"].append(e)
        tracking["episodes"][0]["continuity_links"] = [{"from": "preview", "to": "left", "kind": "preview_promotion"}]
        occ = ro.build_occurrences(tracking, manifest, loader(images), ledger=True)
        system = next(s for s in occ["systems"] if s["main_episode_id"] == "left")
        self.assertNotIn("preview-o", [m["obs_id"] for m in system["observations"]])
        self.assertIn("preview-o", [m["obs_id"] for m in system["ledger_observations"]])
        for o in manifest["observations"]:
            o["system_regions"][0]["envelope_bbox"] = [40, 50, 870, 158]
        _, rec = rs.build_strip(system, manifest, loader(images), chrome=False, ledger=True)
        self.assertIn("preview-o", rec["ledger"]["displays"][0]["observations"])
        self.assertEqual(rec["ledger_supersedes"], f"occ:{system['occurrence_root']}")


class StripLedgerTest(unittest.TestCase):
    def test_compose_output_bit_identical_and_all_measured(self):
        images = [paper() for _ in range(8)]
        images[1] = (images[1].astype(float) * .7).astype(np.uint8)
        images[2] = np.roll(images[2], 3, axis=1)
        keys = list(range(len(images)))
        original, ordinary = rs.compose_members(images, 12, keys=keys)
        enriched, info = rs.compose_members(images, 12, keys=keys, ledger_members=True)
        self.assertTrue(np.array_equal(original, enriched))
        self.assertEqual(info["members_used"], ordinary["members_used"])
        self.assertEqual(len(info["_ledger_members"]), len(images))
        self.assertTrue(info["_ledger_members"][1]["faded"])
        self.assertFalse(info["_ledger_members"][1]["used"])
        self.assertEqual(info["_ledger_members"][info["reference_index"]]["phase_shift"], [0, 0])
        self.assertGreater(np.hypot(*info["_ledger_members"][2]["phase_shift"]), 2)
        self.assertTrue(all(e["overlay_mask"].dtype == bool for e in info["_ledger_members"]))

    def test_all_members_nonpicked_fade_and_actual_uncertainty(self):
        images = [paper() for _ in range(40)]
        images[3] = (images[3].astype(float) * .7).astype(np.uint8)
        images[1] = np.roll(images[1], 3, axis=1)
        system, manifest, load = system_case(images)
        _, rec = rs.build_strip(system, manifest, load, chrome=False, ledger=True)
        ledger = rec["ledger"]
        self.assertEqual(ledger["displays"][0]["observations"], [o["id"] for o in manifest["observations"]])
        associations = ledger["observation_associations"]
        ids = [o["id"] for o in manifest["observations"]]
        self.assertTrue(any(a["obs_id"] == ids[3] and a["role"] == "rejected_fade" and a["paper_drop"] > 10 for a in associations))
        self.assertTrue(any(a["obs_id"] == ids[1] and a["role"] == "offered" and a["reason"] == "not_sampled_for_composite" for a in associations))
        b = rec["ledger_canvas_box_crop"]
        reference = load(next(o for o in manifest["observations"] if o["id"] == rec["pixel_reference_obs_id"]))[b[1]:b[3], b[0]:b[2]]
        shifted = images[1][b[1]:b[3], b[0]:b[2]]
        gray = rs._alignment_gray(reference)
        window = cv2.createHanningWindow((reference.shape[1], reference.shape[0]), cv2.CV_32F)
        base, _ = cv2.phaseCorrelate(gray.copy(), gray.copy(), window)
        shift, _ = cv2.phaseCorrelate(gray.copy(), rs._alignment_gray(shifted), window)
        expected = float(np.hypot(*(np.array(shift) - base)))
        evidence = next(e for i in ledger["items"] for e in i["evidence"] if e["observation_id"] == ids[1])
        self.assertAlmostEqual(evidence["transform"]["registration_uncertainty"], expected, places=8)
        self.assertEqual(evidence["transform"]["registration_shift"], [0, 0])
        registration = next(m for m in rec["member_registration"] if m["obs_id"] == ids[1])
        self.assertAlmostEqual(registration["residual_shift_px"], expected, places=8)
        self.assertAlmostEqual(registration["registration_uncertainty"], expected, places=8)
        self.assertEqual(len(rec["member_registration"]), 40)
        radius, source = rb._veto_uncertainty({}, {"obs_id": ids[1]}, rec,
            {"veto_uncertainty_min_px": 1, "veto_uncertainty_unknown_px": 99})
        self.assertEqual(radius, max(1, int(np.ceil(expected))))
        self.assertEqual(source, "member_registration.residual_shift_px")
        json.dumps(public_record(rec))

    def test_shape_rejection_has_association_and_no_item_evidence(self):
        system, manifest, load = system_case([paper() for _ in range(8)])
        obs_by = {o["id"]: o for o in manifest["observations"]}
        box = [20, 0, 780, 160]
        crops = [load(o)[0:160, 20:780] for o in manifest["observations"]]
        rejected = manifest["observations"][0]["id"]
        def mismatch(obs):
            image = load(obs)
            return image[:, :600] if obs["id"] == rejected else image
        pairs = [((o["id"], tuple(box)), c) for o, c in zip(manifest["observations"][1:], crops[1:])]
        _, info = rs.compose_members(crops[1:], 12, keys=[k for k, _ in pairs], ledger_members=True)
        ledger = rs._strip_ledger(system, manifest, obs_by, mismatch, box, crops[1:], pairs, info, 12, None, {})
        self.assertIn(rejected, ledger["displays"][0]["observations"])
        self.assertTrue(any(a["obs_id"] == rejected and a["role"] == "rejected_registration" and a["reason"] == "crop_shape_mismatch"
                            for a in ledger["observation_associations"]))
        self.assertFalse(any(e["observation_id"] == rejected for i in ledger["items"] for e in i["evidence"]))
        _, record = rs.build_strip(system, manifest, mismatch, chrome=False, ledger=True)
        self.assertTrue(any(a["obs_id"] == rejected and a["role"] == "rejected_registration" and a["reason"] == "crop_shape_mismatch"
            for a in record["ledger"]["observation_associations"]))
        self.assertFalse(any(e["observation_id"] == rejected for i in record["ledger"]["items"] for e in i["evidence"]))

    def check_written_dot(self, trim):
        images = [paper() for _ in range(6)]
        for image in images:
            image[112:115, 420:423] = 0
        system, manifest, load = system_case(images)
        system["occurrence_root"] = "dot"
        with tempfile.TemporaryDirectory() as td:
            if trim:
                records = rs.build_strips({"systems": [system]}, manifest, load, Path(td), ledger=True)
            else:
                with patch.object(rs, "trim_blank_rows", side_effect=lambda im, **_kw: (im, [0, 0])):
                    records = rs.build_strips({"systems": [system]}, manifest, load, Path(td), ledger=True)
            rec = records[0]
            origin = rec["ledger_canvas_box_crop"]
            dot = [421.5 - origin[0], 113.5 - origin[1], 1]
            position = np.array(rec["ledger_chain"]["stages"][0]["matrix"]) @ dot
            x, y = np.floor(position[:2]).astype(int)
            written = cv2.imread(rec["path"])
            self.assertTrue((written[y, x] < 40).all())
            self.assertTrue(np.allclose(position[:2], [421.5 - rec["box_crop"][0], 113.5 - rec["box_crop"][1]], atol=.5))
            self.assertEqual(rec["ledger_supersedes"], "occ:dot")
            self.assertEqual(bool(rec["blank_rows_trimmed"][0]), trim)
            json.dumps(rec)

    def test_written_dot_after_blank_row_trim(self):
        self.check_written_dot(True)

    def test_written_dot_without_trim(self):
        self.check_written_dot(False)

    def test_preview_cut_region_and_written_dot_mapping(self):
        current, following = system_image(7), system_image(8)
        current[143:146, 850:853] = 0
        frames = preview_frames(current, following) + full_frames(following, t0=3)
        manifest, load, systems = strip_fixtures.PreviewDestinationTest()._systems(frames, 12)
        with tempfile.TemporaryDirectory() as td:
            rec, dest = rs.build_strips({"systems": systems}, manifest, load, Path(td), ledger=True)
            self.assertTrue(rec["preview_tail"]["cut"])
            d = rec["ledger"]["display_dispositions"][0]
            self.assertNotIn("frame", d)
            self.assertEqual(d["retained_display_id"], "strip:sys-002")
            origin = rec["ledger_canvas_box_crop"]
            mapped = np.array(rec["ledger_chain"]["stages"][0]["matrix"]) @ [851.5-origin[0], 144.5-origin[1], 1]
            x, y = np.floor(mapped[:2]).astype(int)
            self.assertTrue((cv2.imread(rec["path"])[y, x] < 40).all())
            self.assertEqual(d["region"][0], rec["preview_tail"]["cut_x"] - origin[0])
            check = rec["preview_tail"]["checks"][0]
            rx, ry = check["removed_pixels"]["refined_px"]
            self.assertEqual(d["equivalence_map"][0][2], origin[0] + check["dest_x0"] - rec["preview_tail"]["next_staff_x"] + rx - dest["ledger_canvas_box_crop"][0])
            self.assertEqual(d["equivalence_map"][1][2], origin[1] + check["dest_dy_px"] + ry - dest["ledger_canvas_box_crop"][1])
            json.dumps(rec)

    def test_restore_uncut_updates_map_and_removes_tail_disposition(self):
        current, following = system_image(7), system_image(8)
        manifest, load, systems = strip_fixtures.PreviewDestinationTest()._systems(preview_frames(current, following) + full_frames(following, t0=3), 12)
        _, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:], chrome=False, ledger=True)
        self.assertTrue(rec["preview_tail"]["cut"])
        rs.restore_uncut(rec, reason="test_destination_missing")
        self.assertEqual(rec["ledger"]["display_dispositions"], [])
        origin = rec["ledger_canvas_box_crop"]
        self.assertEqual(rec["ledger_chain"]["stages"][0]["matrix"][1][2], origin[1] - rec["box_crop"][1])

    def test_cursor_partial_mask_and_witnesses_producer_contract(self):
        images = [paper() for _ in range(12)]
        for i, image in enumerate(images):
            x = 80 + i * 50
            image[15:135, x:x+2] = (200, 60, 200)
        system, manifest, _ = system_case([paper() for _ in images])
        by = {o["id"]: images[i] for i, o in enumerate(manifest["observations"])}
        load = loader(by)
        calls = []
        def partial(event, masks, grays, reference, positions, gap, *, allow_partial=False, **kwargs):
            # Inject W-E's new proof contract; the synthetic donors agree exactly.
            calls.append(allow_partial)
            i = event["members"][0]
            mask = mc.event_member_mask(event, i, masks[i]).copy()
            mask[::2] = False
            clear = [j for j in grays if j != i and j in positions and abs(positions[j] - positions[i]) > 2 * gap
                and np.array_equal(grays[j][mask].astype(np.int16), reference[mask].astype(np.int16))]
            if len(clear) < 2 or not mask.any():
                return None
            return {"kind": "synthetic_partial_recovery", "clear_members": clear, "_recovered_mask": mask,
                "witnesses": [{"member": j, "cursor_x": positions[j], "residual_registration_px": 0.0} for j in clear]}
        with patch.object(mc, "recovered_cursor_event", partial):
            _, rec = rs.build_strip(system, manifest, load, chrome=False, ledger=True)
        self.assertTrue(calls and all(calls))
        dispositions = rec["ledger"]["dispositions"]
        self.assertTrue(dispositions)
        partial_items = 0
        for d in dispositions:
            self.assertGreaterEqual(len(d["recovery"]["witnesses"]), 2)
            item = next(i for i in rec["ledger"]["items"] if i["id"] == d["item_id"])
            mask = rl.unpack_crop(d["recovery"]["recovered_mask"]) > 0
            hypothesis = rl.unpack_crop(item["foreground_hypothesis"]) > 0
            self.assertFalse((mask & ~hypothesis).any())
            partial_items += int(mask.sum() < hypothesis.sum())
            self.assertFalse(mask[(-item["display_bbox"][1]) % 2::2].any())
            ev = next(e for e in item["evidence"] if e["observation_id"] == d["clear_observation_id"])
            self.assertEqual(d["raw_patch_sha256"], ev["raw_patch"]["sha256"])
        self.assertGreater(partial_items, 0)
        self.assertNotIn("_recovered_mask", json.dumps(public_record(rec)))

    def test_moving_cursor_live_api_disposition_with_measured_witnesses(self):
        base = paper()
        base[110:113, 420:423] = 0
        xs = (40, 100, 160, 220, 280, 340, 420, 500, 560, 620, 680, 740)
        images = []
        for x in xs:
            image = base.copy()
            image[15:135, x:x+2] = (200, 60, 200)
            images.append(image)
        system, manifest, _ = system_case([paper() for _ in xs])
        by = {o["id"]: images[i] for i, o in enumerate(manifest["observations"])}
        _, rec = rs.build_strip(system, manifest, loader(by), chrome=False, ledger=True)
        dispositions = rec["ledger"]["dispositions"]
        self.assertTrue(dispositions)
        for d in dispositions:
            self.assertEqual(d["terminal"], "recovered_beneath_overlay")
            witnesses = d["recovery"]["witnesses"]
            self.assertGreaterEqual(len(witnesses), 2)
            self.assertGreater(np.ptp([w["cursor_x"] for w in witnesses]), 1)
            self.assertTrue(all(0 <= w["residual_registration_px"] <= .5 for w in witnesses))
            item = next(i for i in rec["ledger"]["items"] if i["id"] == d["item_id"])
            evidence = {e["observation_id"]: e for e in item["evidence"]}
            self.assertTrue(all(evidence[w["observation_id"]]["eligible"] for w in witnesses))
            mask = rl.unpack_crop(d["recovery"]["recovered_mask"]) > 0
            hypothesis = rl.unpack_crop(item["foreground_hypothesis"]) > 0
            self.assertTrue(mask.any())
            self.assertFalse((mask & ~hypothesis).any())
            self.assertEqual(d["raw_patch_sha256"], evidence[d["clear_observation_id"]]["raw_patch"]["sha256"])
        json.dumps(public_record(rec))


class ReferencedStripTest(unittest.TestCase):
    def test_lazy_members_one_call_and_frame_refs(self):
        system, manifest, load = system_case([paper() for _ in range(8)])
        original = rl.record_obligations
        calls = []
        def collect(**kwargs):
            calls.append(kwargs)
            self.assertTrue(all(callable(m["image"]) and callable(m["usable"]) and callable(m["occluded"]) for m in kwargs["members"]))
            return original(**kwargs)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_frames(manifest, load, root / "manifest")
            with patch.object(rl, "record_obligations", side_effect=collect):
                rec = rs.build_strips({"systems": [system]}, manifest, load, root / "strips", ledger=True)[0]
            self.assertEqual(len(calls), 1)
            self.assertEqual(Path(rec["ledger"]["evidence_root"]), (root / "ledger_evidence").resolve())
            display = rec["ledger"]["displays"][0]
            self.assertEqual(display["evidence_mode"], "referenced")
            self.assertEqual(len(display["members"]), 8)
            self.assertTrue(all(m["frame_ref"]["crop_box"] == rec["ledger_canvas_box_crop"] for m in display["members"]))
            self.assertTrue(all("evidence_bits" in i and "evidence" not in i for i in rec["ledger"]["items"]))
            inventory = assembly.inventory_observations(manifest, root / "manifest", source_video="synthetic")
            ledger = assembly.merge_ledgers(inventory, rec["ledger"])
            view = next(rl.EvidenceResolver(ledger).views(ledger["items"][0]))
            self.assertEqual(view["transform"]["roi_origin"], rec["ledger_canvas_box_crop"][:2])
            json.dumps(rec)

    def test_hidden_fragment_streaming_frame_and_canvas_refs(self):
        for dark in (False, True):
            with self.subTest(dark=dark), tempfile.TemporaryDirectory() as td:
                tracking, manifest, images = fixture(inverted=dark)
                manifest["video_id"] = "synthetic"
                root = Path(td)
                store_frames(manifest, loader(images), root / "manifest")
                original = rl.record_obligations
                calls = []
                def collect(**kwargs):
                    calls.append(kwargs)
                    self.assertTrue(all(callable(m["image"]) and callable(m["usable"]) and callable(m["occluded"]) for m in kwargs["members"]))
                    return original(**kwargs)
                with patch.object(rl, "record_obligations", side_effect=collect):
                    occ = ro.build_occurrences(tracking, manifest, loader(images), evidence_dir=root / "ledger_evidence", ledger=True)
                self.assertEqual(len(calls), 1)
                display = next(d for d in occ["ledger"]["displays"] if d["id"] == "occ:short")
                self.assertEqual(display["evidence_mode"], "referenced")
                self.assertTrue(all(("canvas_ref" if dark else "frame_ref") in m for m in display["members"]))
                inventory = assembly.inventory_observations(manifest, root / "manifest", source_video="synthetic")
                ledger = assembly.merge_ledgers(inventory, occ["ledger"])
                item = next(i for i in ledger["items"] if i["display_id"] == "occ:short")
                views = list(rl.EvidenceResolver(ledger).views(item))
                self.assertEqual(len(views), 2)
                self.assertTrue(all(v["supports"] for v in views))
                json.dumps(occ)

    def test_cursor_native_scale_and_common_reference_shifts(self):
        images = [paper() for _ in range(12)]
        for i, image in enumerate(images):
            x = 40 + i * 60
            image[15:135, x:x+2] = (200, 60, 200)
        system, manifest, _ = system_case([paper() for _ in images])
        manifest["work_scale"] = {"scale": .5}
        by = {o["id"]: images[i] for i, o in enumerate(manifest["observations"])}
        original = mc.recovered_cursor_event
        calls = []
        def capture(*args, **kwargs):
            calls.append((kwargs["native_scale"], dict(kwargs["member_shifts"])))
            return original(*args, **kwargs)
        with patch.object(mc, "recovered_cursor_event", side_effect=capture):
            _, rec = rs.build_strip(system, manifest, loader(by), chrome=False, ledger=True)
        self.assertTrue(calls)
        self.assertTrue(all(scale == .5 for scale, _shifts in calls))
        shifts = calls[0][1]
        self.assertEqual(set(shifts), set(range(12)))
        registrations = {m["obs_id"]: m for m in rec["member_registration"]}
        for index, shift in shifts.items():
            oid = manifest["observations"][index]["id"]
            self.assertAlmostEqual(float(np.hypot(*shift)), registrations[oid]["residual_shift_px"], places=8)

    def test_referenced_render_pass_and_written_dot_erasure_fail(self):
        images = [paper() for _ in range(8)]
        for image in images:
            image[112:115, 420:423] = 0
        system, manifest, load = system_case(images)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_frames(manifest, load, root / "manifest")
            rec = rs.build_strips({"systems": [system]}, manifest, load, root / "strips", ledger=True)[0]
            inventory = assembly.inventory_observations(manifest, root / "manifest", source_video="synthetic")
            ledger = assembly.merge_ledgers(inventory, rec["ledger"])
            assembly.annotate(ledger, rec["ledger"]["observation_associations"])
            image = cv2.imread(rec["path"])
            sid = system["id"]
            pl = {"system_id": sid, "x": layout.MARGIN_X, "y": layout.MARGIN_TOP,
                  "w": image.shape[1], "h": image.shape[0]}
            plan = {"pages": [{"placements": [pl]}], "conflicts": [], "header_band_px": 0}
            plan["validation"] = layout.validate_plan(plan, [sid])
            placements = rr.whole_system_ledger_placements(plan, {sid: image.shape[:2]})
            assembly.assemble_representations(ledger, [rec["ledger_chain"]], placements)
            assembly.finalize_terminals(ledger)
            pages = rr.render_pages(plan, {sid: image})
            clean = rl.verify_pages(ledger, pages)
            self.assertEqual(clean["status"], "pass", [(i["code"], i.get("detail")) for i in clean["issues"]])
            del pages
            x, y = rec["box_crop"][:2]
            image[112-y:115-y, 420-x:423-x] = 255
            self.assertTrue(cv2.imwrite(rec["path"], image))
            pages = rr.render_pages(plan, {sid: cv2.imread(rec["path"])})
            erased = rl.verify_pages(ledger, pages)
            self.assertEqual(erased["status"], "fail")
            self.assertTrue(any(i["code"] == "SOURCE_FOREGROUND_MISSING_OR_CHANGED" for i in erased["issues"]))

    def test_referenced_cursor_hashes_resolve_and_masks_are_persisted(self):
        base = paper()
        base[110:113, 420:423] = 0
        xs = (40, 100, 160, 220, 280, 340, 420, 500, 560, 620, 680, 740)
        images = []
        for x in xs:
            image = base.copy()
            image[15:135, x:x+2] = (200, 60, 200)
            images.append(image)
        system, manifest, _ = system_case([paper() for _ in xs])
        by = {o["id"]: images[i] for i, o in enumerate(manifest["observations"])}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_frames(manifest, loader(by), root / "manifest")
            rec = rs.build_strips({"systems": [system]}, manifest, loader(by), root / "strips", ledger=True)[0]
            self.assertTrue(rec["ledger"]["dispositions"])
            inventory = assembly.inventory_observations(manifest, root / "manifest", source_video="synthetic")
            ledger = assembly.merge_ledgers(inventory, rec["ledger"])
            resolver = rl.EvidenceResolver(ledger)
            for d in ledger["dispositions"]:
                item = next(i for i in ledger["items"] if i["id"] == d["item_id"])
                views = {e["observation_id"]: e for e in resolver.views(item)}
                self.assertEqual(d["raw_patch_sha256"], views[d["clear_observation_id"]]["raw_patch"]["sha256"])
                self.assertTrue(all(views[w["observation_id"]]["eligible"] for w in d["recovery"]["witnesses"]))
                self.assertGreaterEqual(len(d["recovery"]["witnesses"]), 2)
            self.assertTrue(list((root / "ledger_evidence").glob("*.png")))
            self.assertTrue(all("canvas_ref" not in m for m in ledger["displays"][0]["members"]))
            json.dumps(rec)

    def test_referenced_40_member_json_budget(self):
        with tempfile.TemporaryDirectory() as td:
            rec = benchmark(evidence_dir=Path(td) / "ledger_evidence")
            self.assertLessEqual(len(json.dumps(rec["ledger"], indent=2).encode()), 1_500_000)


def benchmark(*, evidence_dir=None):
    image = np.full((300, 1800, 3), 255, np.uint8)
    for y in (100, 114, 128, 142, 156):
        cv2.line(image, (30, y), (1770, y), (0, 0, 0), 1)
    for x in range(100, 1750, 90):
        cv2.line(image, (x, 85), (x, 156), (0, 0, 0), 2)
    observations, members = [], []
    for k in range(40):
        oid, rid = f"obs-{k:06d}", f"region-{k}"
        observations.append({"id": oid, "t_sec": k*.25, "system_regions": [{"region_id": rid,
            "staff_y": [100, 114, 128, 142, 156], "staff_gap_px": 14, "staff_x": [30, 1770],
            "bbox": [0, 0, 1800, 300], "envelope_bbox": [30, 75, 1770, 165]}], "source_to_crop": np.eye(3).tolist()})
        members.append({"obs_id": oid, "region_id": rid})
    manifest = {"video_id": "synthetic-benchmark", "observations": observations}
    if evidence_dir is not None:
        store_frames(manifest, lambda _obs: image, Path(evidence_dir).parent / "manifest")
    start = time.perf_counter()
    _, record = rs.build_strip({"id": "sys-benchmark", "observations": members}, manifest, lambda _obs: image,
                              chrome=False, evidence_dir=evidence_dir, ledger=True)
    runtime = time.perf_counter() - start
    encoded = json.dumps(record["ledger"], separators=(",", ":")).encode()
    indented = json.dumps(record["ledger"], ensure_ascii=False, indent=2).encode()
    evidence_bytes = sum(p.stat().st_size for p in Path(evidence_dir).glob("*.png")) if evidence_dir is not None else 0
    frame_bytes = sum(Path(o["frame_path"]).stat().st_size for o in observations) if evidence_dir is not None else 0
    print(f"BENCHMARK mode={'referenced' if evidence_dir is not None else 'embedded'} members=40 source=1800x300 canvas={record['ledger']['displays'][0]['shape']} items={len(record['ledger']['items'])} json_bytes={len(encoded)} json_indent2_bytes={len(indented)} evidence_png_bytes={evidence_bytes} frame_png_bytes={frame_bytes} build_strip_sec={runtime:.6f}")
    return record


if __name__ == "__main__":
    unittest.main()
