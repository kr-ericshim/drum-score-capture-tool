"""Synthetic controls for immutable inventory, routing and retained evidence."""
import copy
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_ledger_assembly as assembly


IDENTITY = np.eye(3).tolist()


def affine(stage, matrix=None):
    return {"stage": stage, "kind": "affine", "matrix": IDENTITY if matrix is None else matrix}


def chain(matrix=None, display="d", strip="s"):
    return {"display_id": display, "strip_id": strip, "stages": [affine("display_to_strip", matrix)]}


def placement(stage=None, ci=0, page=0, line="l", strip="s"):
    return {"strip_id": strip, "copy_index": ci, "page_index": page, "line_id": line,
            "stages": [stage or affine("strip_to_line"), affine("line_to_page", [[1,0,10],[0,1,10],[0,0,1]])]}


def measure(a, b, *, scale=1., removed=None, line="l", ci=0, page=0, height=16):
    rec = {"cols_src_out": [a,b], "rows_src_out": [0,height], "width_out": b-a-len(removed or []),
           "removed_cols_out": removed or [], "inserted_offsets": [], "x_out": 0, "y_out": 0, "line_id": line}
    return placement(rl.measure_placement_transform(rec, native_scale=scale), ci, page, line)


def snapshot(*, copies=1, shift=0., dot=False):
    image = np.full((16,40,3), 255, np.uint8)
    image[8,4:36] = 0
    if dot:
        image[6:9,18:21] = 0
    members = [{"id": "o", "timestamp": 1., "image": image, "roi_origin": [0,0],
                "registration_shift": [shift,0], "registration_uncertainty": 0.,
                "usable": np.ones(image.shape[:2],bool), "occluded": np.zeros(image.shape[:2],bool)}]
    return rl.record_obligations(source_video="source.mp4", display_id="d", occurrence_id="occ",
                                 members=members, candidates=[[2,4,38,12]], expected_multiplicity=copies)


def observation(ident="o", *, staff=1, foreground=32, associations=None):
    return {"id": ident, "t_sec": 1., "sample_kind": "coarse", "frame_path": "/raw/frame.png",
            "pixels_sha256": "raw-hash", "foreground_px": foreground, "staff_regions": staff,
            "associations": associations or [], "terminal": None}


def assoc(ident="o", role="member", display="d", **kw):
    return {"obs_id": ident, "stage": "composition", "display_id": display, "occurrence_id": "occ",
            "role": role, "reason": None, **kw}


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def manifest(self, images):
        result = {"work_scale": {"scale": .5, "native_crop_size": [80,32]}, "detector_version": "synthetic-1",
                  "source_to_crop": list(np.eye(3).ravel()), "applied_roi": [[0,0],[40,0],[40,16],[0,16]],
                  "roi_revision": 2, "observations": []}
        for i, image in enumerate(images):
            path = self.work / f"frame-{i}.png"
            self.assertTrue(cv2.imwrite(str(path),image))
            result["observations"].append({"id": f"o-{i}", "t_sec": i*.5, "frame_path": path.name,
                                          "sample_kind": "coarse" if i % 2 == 0 else "fine", "system_regions": [{}] if i == 0 else []})
        return result

    def inventory(self, images):
        return assembly.inventory_observations(self.manifest(images), self.work, source_video="source.mp4")

    def assert_projectable(self, ledger):
        items = {i["id"]: i for i in ledger["items"]}
        for rep in ledger["representations"]:
            _, mask, _ = rl.project_item(items[rep["item_id"]], rep["transforms"])
            self.assertTrue(mask.any())

    def assert_partition_union(self, ledger):
        parent = ledger["items"][0]
        original = rl.unpack_crop(parent["foreground_hypothesis"]) > 0
        union = np.zeros(original.shape,np.uint8)
        children = [i for i in ledger["items"] if i.get("partition_of") == parent["id"]]
        self.assertEqual(parent["partitioned_into"],[i["id"] for i in children])
        self.assertFalse(any(r["item_id"] == parent["id"] for r in ledger["representations"]))
        for child in children:
            x0,y0,x1,y1 = child["display_bbox"]
            x,y = parent["display_bbox"][:2]
            mask = rl.unpack_crop(child["foreground_hypothesis"]) > 0
            union[y0-y:y1-y,x0-x:x1-x] += mask
            self.assertEqual(child["expected_multiplicity"],parent["expected_multiplicity"])
            self.assertEqual(child["occurrence_id"],parent["occurrence_id"])
            for evidence in child["evidence"]:
                for key in ("display_patch", "contrast", "usable_mask"):
                    self.assertEqual(rl.unpack_crop(evidence[key]).shape[:2],mask.shape)
                nb = evidence["native_bbox"]
                for key in ("raw_patch", "native_usable_mask", "native_occluded_mask"):
                    self.assertEqual(rl.unpack_crop(evidence[key]).shape[:2],(nb[3]-nb[1],nb[2]-nb[0]))
        np.testing.assert_array_equal(union, original.astype(np.uint8))
        return children

    def test_inventory_manifest_order_and_hashes(self):
        light = np.full((16,40,3),255,np.uint8); light[8,3:20] = 243; light[7,9] = 244
        dark = np.zeros_like(light); dark[5,2:10] = 12; dark[6,4] = 11
        manifest = self.manifest([light,dark])
        with patch.object(rl,"VERSION","live-version"):
            ledger = assembly.inventory_observations(manifest,self.work,source_video="source.mp4")
        self.assertEqual(ledger["version"],"live-version")
        self.assertEqual([o["id"] for o in ledger["observations"]],["o-0","o-1"])
        for i, (obs,image,count) in enumerate(zip(ledger["observations"],[light,dark],[17,8])):
            self.assertEqual(obs["pixels_sha256"],rl.pixels_hash(image))
            self.assertEqual(obs["frame_png_sha256"],hashlib.sha256((self.work/f"frame-{i}.png").read_bytes()).hexdigest())
            self.assertEqual(obs["foreground_px"],count)
            self.assertEqual(obs["native_crop_size"],[80,32]); self.assertEqual(obs["work_scale"],.5)
            self.assertEqual(obs["crop_size"],[40,16]); self.assertEqual(obs["staff_regions"],1-i)
            self.assertTrue(Path(obs["frame_path"]).is_absolute())
            self.assertEqual(obs["roi_revision"],2); self.assertEqual(obs["associations"],[])
        self.assertEqual(ledger["detector_version"],"synthetic-1")
        for key in ("displays","items","representations","dispositions","display_dispositions","generated_origins","occurrence_remaps"):
            self.assertEqual(ledger[key],[])

    def test_inventory_missing_file_raises_without_redecode(self):
        manifest = self.manifest([np.full((16,40,3),255,np.uint8)])
        (self.work/"frame-0.png").unlink()
        with patch.object(assembly.ob,"iter_frames_at",side_effect=AssertionError("must not decode")):
            with self.assertRaises(FileNotFoundError):
                assembly.inventory_observations(manifest,self.work,source_video="source.mp4")
        manifest["observations"][0]["frame_path"] = None
        with self.assertRaises(FileNotFoundError):
            assembly.inventory_observations(manifest,self.work,source_video="source.mp4")

    def test_inventory_300_frames_time_and_size(self):
        image = np.full((330,1900,3),255,np.uint8)
        image[60::30,:] = 0
        image[120:125,900:904] = 180
        manifest = self.manifest([image]*300)
        # Peak of the allocations made by the inventory itself (numpy reports to tracemalloc);
        # process RSS would include every earlier test of a full-suite run.
        import tracemalloc
        tracemalloc.start()
        start = time.perf_counter()
        ledger = assembly.inventory_observations(manifest,self.work,source_video="source.mp4")
        elapsed = time.perf_counter()-start
        peak_mb = tracemalloc.get_traced_memory()[1]/1_000_000
        tracemalloc.stop()
        size = len(json.dumps(ledger,separators=(",",":"),ensure_ascii=False).encode())
        print(f"\nINVENTORY_BENCH frames=300 pixels=1900x330 seconds={elapsed:.3f} json_bytes={size} traced_peak_mb={peak_mb:.1f}")
        self.assertEqual(len(ledger["observations"]),300)
        self.assertLess(elapsed,6.)
        self.assertLess(peak_mb,300.)

    def test_assembly_100_items_20_observations_benchmark(self):
        image = np.full((80,640,3),255,np.uint8)
        for row in range(10):
            for col in range(10): image[2+7*row:4+7*row,2+60*col:4+60*col] = 0
        manifest = self.manifest([image]*20)
        manifest["work_scale"] = {"scale":1.,"native_crop_size":[640,80]}
        inventory = assembly.inventory_observations(manifest,self.work,source_video="source.mp4")
        members = [{"id":f"o-{k}","timestamp":float(k),"image":image,"roi_origin":[0,0],
                    "registration_shift":[0,0],"registration_uncertainty":0.} for k in range(20)]
        ledger = assembly.merge_ledgers(inventory,rl.record_obligations(source_video="source.mp4",display_id="d",
                                       occurrence_id="occ",members=members))
        assembly.annotate(ledger,[assoc(f"o-{k}",role="used") for k in range(20)])
        start = time.perf_counter()
        assembly.assemble_representations(ledger,[chain()],[placement()])
        elapsed = time.perf_counter()-start
        assembly.finalize_terminals(ledger)
        size = len(json.dumps(ledger,separators=(",",":"),ensure_ascii=False).encode())
        self.assertEqual(len(ledger["items"]),100)
        self.assertEqual(len(ledger["representations"]),100)
        self.assertEqual(sum(len(i["evidence"]) for i in ledger["items"]),2000)
        self.assert_projectable(ledger)
        print(f"\nASSEMBLY_BENCH displays=1 items=100 observations=20 evidence_records=2000 seconds={elapsed:.3f} json_bytes={size}")

    def test_annotation_is_append_only_and_preserves_regions(self):
        ledger = {"observations":[observation()]}
        for role in ("member","offered","used","rejected_fade","rejected_registration","duration_filtered",
                     "excluded_candidate","covered_by_kept_display","transient","unassigned"):
            assembly.annotate(ledger,[assoc(role=role,region_id="r")])
        self.assertEqual(len(ledger["observations"][0]["associations"]),10)
        self.assertEqual(ledger["observations"][0]["associations"][0]["role"],"member")
        self.assertTrue(all(a["region_id"] == "r" and "obs_id" not in a for a in ledger["observations"][0]["associations"]))
        with self.assertRaises(KeyError): assembly.annotate(ledger,[assoc("missing")])
        with self.assertRaises(ValueError): assembly.annotate(ledger,[assoc(role="covered")])
        self.assertEqual(len(ledger["observations"][0]["associations"]),10)

    def test_tracking_regions_episode_transient_unattached_and_unassigned(self):
        ledger = {"observations":[observation(i) for i in ("o","t","u","n")]}
        tracking = {"episodes":[{"id":"ep","slot_id":"slot","observation_ids":["o","o"],"region_ids":["r1","r2"],
                                 "transient_observation_ids":["t"]}],
                    "transients":[{"obs_id":"t","region_id":"tr","slot_id":"slot","reason":"transient_change"},
                                  {"obs_id":"u","region_id":"ur","slot_id":"other","reason":"unconfirmed_change"}]}
        assembly.annotate_from_tracking(ledger,tracking)
        o,t,u,n = [r["associations"] for r in ledger["observations"]]
        self.assertEqual([a["region_id"] for a in o],["r1","r2"])
        self.assertEqual(len(t),1); self.assertEqual(t[0]["occurrence_id"],"ep")
        self.assertEqual(t[0]["reason"],"tracking_transient"); self.assertEqual(t[0]["region_id"],"tr")
        self.assertEqual(u[0]["reason"],"unconfirmed_change"); self.assertEqual(u[0]["slot_id"],"other")
        self.assertIsNone(u[0]["occurrence_id"]); self.assertEqual(n[0]["role"],"unassigned")
        self.assertEqual(n[0]["reason"],"no_episode")

    def test_tracking_accepts_current_tracker_key(self):
        ledger = {"observations":[observation()]}
        assembly.annotate_from_tracking(ledger,{"episodes":[],"transient_observations":[{"obs_id":"o","slot_id":"s"}]})
        self.assertEqual(ledger["observations"][0]["associations"][0]["role"],"transient")

    def test_tracking_bad_region_lengths_and_unknown_id(self):
        ledger = {"observations":[observation()]}
        with self.assertRaises(ValueError):
            assembly.annotate_from_tracking(ledger,{"episodes":[{"id":"ep","observation_ids":["o"],"region_ids":[]}]})
        with self.assertRaises(KeyError):
            assembly.annotate_from_tracking(ledger,{"transients":[{"obs_id":"missing"}]})

    def test_merge_stubs_order_and_nonmutation(self):
        full = {"source_video":"s","observations":[observation(associations=[{"role":"member"}])],"items":[{"id":"i"}]}
        before = {"source_video":"s","observations":[{"id":"o","associations":[{"role":"offered"}]}]}
        after = {"observations":[{"id":"o","associations":[{"role":"used"}]}],"occurrence_remaps":[{"root_key":"root"}]}
        originals = copy.deepcopy([before,full,after])
        with patch.object(rl,"VERSION","live-version"):
            result = assembly.merge_ledgers(before,full,after)
        self.assertEqual(result["version"],"live-version")
        self.assertEqual([a["role"] for a in result["observations"][0]["associations"]],["offered","member","used"])
        self.assertEqual(result["observations"][0]["foreground_px"],32)
        self.assertEqual([before,full,after],originals)
        self.assertEqual(result["occurrence_remaps"],[{"root_key":"root"}])

    def test_merge_duplicate_ids_source_and_orphan_stub_rejected(self):
        for key in ("observations","displays","items"):
            record = observation() if key == "observations" else {"id":"same"}
            with self.subTest(key=key), self.assertRaises(ValueError):
                assembly.merge_ledgers({key:[record]},{key:[record]})
        with self.assertRaises(ValueError): assembly.merge_ledgers({"source_video":"a"},{"source_video":"b"})
        with self.assertRaises(ValueError): assembly.merge_ledgers({"observations":[{"id":"o","associations":[]}]})

    def test_whole_system_no_partition_and_no_chain_left_alone(self):
        ledger = snapshot()
        assembly.assemble_representations(ledger,[chain()],[placement()])
        self.assertEqual(len(ledger["items"]),1); self.assertEqual(len(ledger["representations"]),1)
        self.assertEqual(ledger["representations"][0]["occurrence_id"],"occ")
        self.assert_projectable(ledger)
        untouched = snapshot(); before = copy.deepcopy(untouched)
        assembly.assemble_representations(untouched,[],[placement()])
        self.assertEqual(untouched,before)

    def test_measure_split_two_lines_partition_union(self):
        ledger = snapshot()
        assembly.assemble_representations(ledger,[chain()],[measure(0,20,line="l0"),measure(20,40,line="l1",page=1)])
        children = self.assert_partition_union(ledger)
        self.assertEqual(len(children),2); self.assertEqual(len(ledger["representations"]),2)
        self.assert_projectable(ledger)
        print(f"\nASSEMBLY_SPLIT json_bytes={len(json.dumps(ledger,separators=(',',':')).encode())}")

    def test_removed_column_is_unplaced_partition(self):
        ledger = snapshot()
        assembly.assemble_representations(ledger,[chain()],[measure(0,40,removed=[20])])
        children = self.assert_partition_union(ledger)
        unplaced = [c for c in children if not any(r["item_id"] == c["id"] for r in ledger["representations"])]
        self.assertEqual(len(unplaced),1)
        self.assertEqual(rl.unpack_crop(unplaced[0]["foreground_hypothesis"]).sum(),255)
        self.assertEqual(unplaced[0]["display_bbox"],[20,8,21,9])
        self.assert_projectable(ledger)

    def test_chained_item_without_any_placement_gets_unplaced_child(self):
        ledger = snapshot()
        assembly.assemble_representations(ledger,[chain()],[])
        self.assertEqual(len(self.assert_partition_union(ledger)),1)
        self.assertEqual(ledger["representations"],[])

    def test_two_copies_whole_system_and_split(self):
        for split in (False,True):
            ledger = snapshot(copies=2)
            placements = ([measure(0,20,ci=ci,line=f"l{ci}a",page=ci), measure(20,40,ci=ci,line=f"l{ci}b",page=ci)]
                          for ci in range(2)) if split else ([placement(ci=ci,page=ci)] for ci in range(2))
            assembly.assemble_representations(ledger,[chain()],[p for group in placements for p in group])
            self.assertEqual(len(ledger["items"]),3 if split else 1)
            self.assertEqual(len(ledger["representations"]),4 if split else 2)
            if split: self.assert_partition_union(ledger)
            self.assert_projectable(ledger)

    def test_different_copy_cuts_partition_by_combined_routing(self):
        ledger = snapshot(copies=2)
        assembly.assemble_representations(ledger,[chain()],[measure(0,20),measure(20,40),measure(0,24,ci=1),measure(24,40,ci=1)])
        self.assertEqual(len(self.assert_partition_union(ledger)),3)
        self.assertEqual(len(ledger["representations"]),6)
        self.assert_projectable(ledger)

    def test_raw_registered_evidence_is_cropped_in_native_coordinates(self):
        ledger = snapshot(shift=2.)
        assembly.assemble_representations(ledger,[chain()],[measure(0,20),measure(20,40)])
        self.assert_partition_union(ledger)
        for child in ledger["items"][1:]:
            self.assertEqual(child["evidence"][0]["native_bbox"][0],child["display_bbox"][0]-2)
        self.assert_projectable(ledger)

    def test_pre_matrix_and_display_crop_offset(self):
        ledger = snapshot()
        # Native x -> strip x-2 -> resampled 2*x+0.5, cut between native centres.
        assembly.assemble_representations(ledger,[chain([[1,0,-2],[0,1,0],[0,0,1]])],
                                         [measure(0,40,scale=2.,height=32),measure(40,80,scale=2.,height=32)])
        self.assert_partition_union(ledger)
        self.assert_projectable(ledger)

    def test_fractional_resampling_cut_owns_native_centres_once(self):
        ledger = snapshot()
        assembly.assemble_representations(ledger,[chain()],
            [measure(0,20,scale=1.5,height=32),measure(20,60,scale=1.5,height=32)])
        children = self.assert_partition_union(ledger)
        self.assertEqual(len(children),2)
        self.assertEqual(len(ledger["representations"]),2)
        self.assert_projectable(ledger)

    def test_overlapping_placements_and_pieces_raise(self):
        with self.assertRaises(ValueError):
            assembly.assemble_representations(snapshot(),[chain()],[measure(0,24),measure(20,40)])
        stage = rl.measure_placement_transform({"cols_src_out":[0,40],"rows_src_out":[0,16],"width_out":40,"x_out":0,"y_out":0})
        stage["pieces"].append(copy.deepcopy(stage["pieces"][0]))
        with self.assertRaises(ValueError): assembly.assemble_representations(snapshot(),[chain()],[placement(stage)])

    def terminal_ledger(self, kind=None, represented=False, *, role="member"):
        ledger = snapshot()
        ledger["observations"] = [observation()]
        assembly.annotate(ledger,[assoc(role=role)])
        if represented:
            assembly.assemble_representations(ledger,[chain()],[placement()])
        if kind:
            ledger["dispositions"] = [{"kind":kind,"item_id":ledger["items"][0]["id"],"review_artifact":"/raw/item.png"}]
        return ledger

    def test_terminal_derivation_each_item_disposition_and_nonmutation(self):
        mapping = {None:"preserved", "cursor_recovery":"recovered_beneath_overlay", "overlap_duplicate":"equivalent_observation",
                   "staff_scaffold":"preserved", "structural_replacement":"unresolved", "unresolved_alternative":"unresolved"}
        for kind,expected in mapping.items():
            with self.subTest(kind=kind):
                ledger = self.terminal_ledger(kind,represented=kind in (None,"staff_scaffold"))
                before = copy.deepcopy([ledger["items"],ledger["representations"]])
                counts = assembly.finalize_terminals(ledger)
                self.assertEqual(ledger["observations"][0]["terminal"],expected)
                self.assertEqual(counts[expected],1)
                self.assertEqual([ledger["items"],ledger["representations"]],before)
                after = copy.deepcopy(ledger)
                self.assertEqual(assembly.finalize_terminals(ledger),counts)
                self.assertEqual(ledger,after)

    def test_terminal_non_score_requires_detector_and_outside_episode(self):
        for associations in ([],[{"stage":"tracking","role":"unassigned","occurrence_id":None,"display_id":None}]):
            ledger = {"observations":[observation(staff=0,foreground=0,associations=associations)],"detector_version":"det-1"}
            self.assertEqual(assembly.finalize_terminals(ledger)["non_score_material"],1)
            ev = ledger["observations"][0]["evidence"]
            self.assertEqual(ev["staff_regions"],0); self.assertEqual(ev["detector_version"],"det-1")
            self.assertEqual(ev["pixels_sha256"],"raw-hash")
        for ledger in ({"observations":[observation(staff=0)]},
                       {"observations":[observation(staff=0,associations=[{"occurrence_id":"ep","role":"member"}])],"detector_version":"d"},
                       {"observations":[observation(staff=1)],"detector_version":"d"}):
            self.assertEqual(assembly.finalize_terminals(ledger)["unresolved"],1)
        ledger = {"observations":[observation(staff=0)]}
        self.assertEqual(assembly.finalize_terminals(ledger,detector_version="explicit")["non_score_material"],1)

    def test_terminal_source_limited_reason_and_measured_evidence(self):
        for reason,measurement in (("fade_transition",{"paper_drop":.4}), ("registration_out_of_range",{"shift_px":[4,2]}),
                                   ("source_clipped",{"clip_bbox":[0,0,2,4]}), ("outside_requested_range",{"requested_range":[1,2],"measured_value":3})):
            ledger = {"observations":[observation()]}
            assembly.annotate(ledger,[assoc(role="rejected_fade",reason=reason,**measurement)])
            self.assertEqual(assembly.finalize_terminals(ledger)["source_limited"],1)
            ev = ledger["observations"][0]["evidence"]
            self.assertEqual(ev["reason"],reason)
            for key,value in measurement.items(): self.assertEqual(ev[key],value)
        ledger = self.terminal_ledger()
        ledger["dispositions"] = [{"item_id":ledger["items"][0]["id"],"terminal":"source_limited","reason":"source_clipped","clip_bbox":[0,0,1,1]}]
        self.assertEqual(assembly.finalize_terminals(ledger)["source_limited"],1)

    def test_terminal_mixed_priority_unresolved_then_limited_then_preserved(self):
        for other,expected in (("unresolved","unresolved"),("source_limited","source_limited"),
                               ("recovered_beneath_overlay","preserved"),("equivalent_observation","preserved")):
            ledger = self.terminal_ledger(represented=True)
            child = copy.deepcopy(ledger["items"][0]); child["id"] = "other"; ledger["items"].append(child)
            ledger["dispositions"] = [{"item_id":"other","terminal":other}]
            self.assertEqual(assembly.finalize_terminals(ledger)[expected],1)

    def test_terminal_unplaced_partition_keeps_observation_unresolved(self):
        ledger = snapshot(); ledger["observations"] = [observation()]
        assembly.annotate(ledger,[assoc()])
        assembly.assemble_representations(ledger,[chain()],[measure(0,40,removed=[20])])
        self.assertEqual(assembly.finalize_terminals(ledger)["unresolved"],1)

    def test_terminal_evidence_is_consumed_by_current_verifier(self):
        image = np.full((16,40,3),255,np.uint8); image[8,4:36] = 0
        inventory = self.inventory([image,np.full_like(image,255)])
        raw = snapshot()
        for item in raw["items"]:
            for ev in item["evidence"]: ev["observation_id"] = "o-0"
        raw["displays"][0]["observations"] = ["o-0"]
        ledger = assembly.merge_ledgers(inventory,raw)
        assembly.annotate(ledger,[assoc("o-0")])
        assembly.assemble_representations(ledger,[chain()],[placement()])
        assembly.finalize_terminals(ledger)
        page = np.full((40,70,3),255,np.uint8); page[10:26,10:50] = image
        report = rl.verify_pages(ledger,[page])
        self.assertEqual(report["status"],"pass",report)
        self.assertEqual(report["terminal_counts"]["observations"]["preserved"],1)
        self.assertEqual(report["terminal_counts"]["observations"]["non_score_material"],1)

    def test_terminal_preserved_needs_member_or_used_association(self):
        ledger = self.terminal_ledger(represented=True,role="offered")
        self.assertEqual(assembly.finalize_terminals(ledger)["unresolved"],1)
        self.assertEqual(ledger["observations"][0]["evidence"]["reason"],"no_delivery_association")

    def test_terminal_unresolved_without_associations_gets_unassigned(self):
        ledger = {"observations":[observation()]}
        self.assertEqual(assembly.finalize_terminals(ledger)["unresolved"],1)
        self.assertEqual(ledger["observations"][0]["associations"][0]["role"],"unassigned")
        self.assertEqual(ledger["observations"][0]["evidence"]["review_artifact"],"/raw/frame.png")

    def test_retention_idempotency_dedup_and_pruning_survival(self):
        image = np.full((16,40,3),255,np.uint8); image[8,3:20] = 0
        ledger = self.inventory([image,image,np.full_like(image,255)])
        for obs in ledger["observations"][:2]: obs["terminal"] = "unresolved"
        ledger["observations"][2]["terminal"] = "non_score_material"
        workspace = self.work/"job"
        self.assertEqual(assembly.retain_evidence(ledger,workspace),1)
        self.assertEqual(assembly.retain_evidence(ledger,workspace),0)
        first,second,blank = ledger["observations"]
        self.assertEqual(first["frame_path"],second["frame_path"])
        self.assertEqual(rl.pixels_hash(cv2.imread(first["frame_path"])),first["pixels_sha256"])
        self.assertEqual(Path(blank["frame_path"]),(self.work/"frame-2.png").resolve())
        for path in self.work.glob("frame-*.png"): path.unlink()
        self.assertEqual(assembly.retain_evidence(ledger,workspace),0)
        self.assertTrue(Path(first["frame_path"]).is_file())

    def test_retention_source_and_existing_target_tampering_raises(self):
        image = np.full((16,40,3),255,np.uint8); image[8,3:20] = 0
        ledger = self.inventory([image]); source = Path(ledger["observations"][0]["frame_path"])
        source.write_bytes(source.read_bytes()+b"tampered")
        with self.assertRaises(ValueError): assembly.retain_evidence(ledger,self.work/"job")
        ledger = self.inventory([image]); assembly.retain_evidence(ledger,self.work/"job")
        cv2.imwrite(ledger["observations"][0]["frame_path"],np.full_like(image,255))
        with self.assertRaises(ValueError): assembly.retain_evidence(ledger,self.work/"job")

    def test_retention_detects_byte_tampering_and_keeps_provenance_hash(self):
        image = np.full((16,40,3),255,np.uint8); image[8,3:20] = 0
        ledger = self.inventory([image])
        original_hash = ledger["observations"][0]["frame_png_sha256"]
        assembly.retain_evidence(ledger,self.work/"job")
        obs = ledger["observations"][0]
        self.assertEqual(obs["retained_frame_png_sha256"],original_hash)
        path = Path(obs["frame_path"]); path.write_bytes(path.read_bytes()+b"tampered")
        with self.assertRaisesRegex(ValueError,"retained PNG hash mismatch"):
            assembly.retain_evidence(ledger,self.work/"job")

    def test_retention_non_score_foreground_still_retained(self):
        image = np.full((16,40,3),255,np.uint8); image[8,3:20] = 0
        ledger = self.inventory([image]); ledger["observations"][0]["terminal"] = "non_score_material"
        self.assertEqual(assembly.retain_evidence(ledger,self.work/"job"),1)

    def test_generated_staff_resolved_through_inverse_chain_and_other_kinds_copied(self):
        ledger = snapshot()
        transform = [[1,0,-2],[0,1,-4],[0,0,1]]
        generated = [{"kind":"staff_scaffold","strip_id":"s","source_bbox_S":[2,4,34,5],"page_index":0,"origin":[10,10]},
                     {"kind":"header","inputs":{"title":"test"},"generator":"header-1"}]
        original = copy.deepcopy(generated)
        assembly.resolve_generated(ledger,[chain(transform)],generated)
        rec = ledger["generated_origins"][0]
        self.assertEqual(rec["source_item_id"],ledger["items"][0]["id"])
        self.assertEqual(rec["staff_rows_display"],[8.])
        self.assertNotIn("unresolved_source",rec)
        self.assertEqual(ledger["generated_origins"][1],generated[1]); self.assertEqual(generated,original)

    def test_generated_after_partition_uses_original_raw_staff_item(self):
        ledger = snapshot()
        assembly.assemble_representations(ledger,[chain()],[measure(0,20),measure(20,40)])
        assembly.resolve_generated(ledger,[chain()],[{"kind":"staff_scaffold","strip_id":"s","source_bbox_S":[20,8,21,9]}])
        self.assertEqual(ledger["generated_origins"][0]["source_item_id"],ledger["items"][0]["id"])

    def test_generated_staff_missing_ambiguous_and_connected_dot_unresolved(self):
        origin = {"kind":"staff_scaffold","strip_id":"s","source_bbox_S":[4,8,36,9]}
        for mode in ("missing","ambiguous","dot"):
            with self.subTest(mode=mode):
                ledger = snapshot(dot=mode == "dot")
                if mode == "ambiguous":
                    other = copy.deepcopy(ledger["items"][0]); other["id"] = "other"; ledger["items"].append(other)
                assembly.resolve_generated(ledger,[] if mode == "missing" else [chain()],[origin])
                self.assertTrue(ledger["generated_origins"][0]["unresolved_source"])
                self.assertNotIn("source_item_id",ledger["generated_origins"][0])


if __name__ == "__main__":
    unittest.main()
