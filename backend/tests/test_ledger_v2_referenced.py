"""Round-2 referenced evidence, streaming, supersede and fractional-cut controls."""
import copy
import gc
import hashlib
import json
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from app.pipeline import reflow_ledger as rl, reflow_ledger_assembly as assembly
import test_reflow_ledger as legacy
import test_ledger_v2_verify as verifier
import test_ledger_v2_assembly as routing


def size(ledger):
    return len(json.dumps(ledger,separators=(",",":"),ensure_ascii=False).encode())


def paired(make,root):
    calls = []
    original = rl.record_obligations
    def capture(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)
    with patch.object(rl,"record_obligations",side_effect=capture):
        embedded,image = make()
    referenced = copy.deepcopy(embedded)
    referenced["displays"],referenced["items"] = [],[]
    for kwargs in calls:
        fragment = original(**kwargs,evidence_dir=root)
        referenced["displays"].extend(fragment["displays"])
        referenced["items"].extend(fragment["items"])
        referenced["evidence_root"] = fragment["evidence_root"]
    parents = {i["id"]:i for i in referenced["items"]}
    for item in embedded["items"]:
        if item.get("partitioned_into"):
            parents[item["id"]]["partitioned_into"] = item["partitioned_into"]
        if item.get("partition_of"):
            child = copy.deepcopy(item); child.pop("evidence",None)
            child["evidence_bits"] = dict(parents[item["partition_of"]]["evidence_bits"])
            referenced["items"].append(child)
    return embedded,referenced,image



RETIRED_VERIFIER = "Retired raw-projection verifier (DECISIONS 2026-10-09 staged verification): not in the product path; its loss/tamper controls live in test_verify_* now."

class ReferencedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def test_missing_inventory_reverse_accounting_is_unassessed_but_loss_still_fails(self):
        for ledger in ({}, {"version":rl.VERSION}, verifier.control()):
            ledger.pop("observations",None)
            report = rl.verify_pages(ledger,[legacy.dot()])
            self.assertEqual(report["status"],"review_required",report)
            self.assertGreater(report["accounting"][0]["foreground_px"],0)
            self.assertTrue(all(i["severity"]=="review_required" for i in report["issues"] if i["code"]=="OUTPUT_FOREGROUND_WITHOUT_ORIGIN"))
        ledger = verifier.control(); ledger["observations"] = []
        report = rl.verify_pages(ledger,[legacy.paper()])
        self.assertEqual(report["status"],"fail")
        self.assertIn("SOURCE_FOREGROUND_MISSING_OR_CHANGED",verifier.LedgerV2VerifyTests.codes(self,report))
        self.assertEqual(rl.verify_pages({},[])["status"],"fail")

    def test_embedded_referenced_clean_dot_loss_cursor_and_equivalence_reports_identical(self):
        for name,make in (("clean",lambda:(verifier.control(),legacy.dot())),
                          ("cursor",verifier.cursor_fixture),("equivalence",verifier.equivalent_fixture),
                          ("minority",lambda:verifier.equivalent_fixture(extra=True)),("partition",verifier.partition_fixture)):
            with self.subTest(name=name):
                embedded,referenced,image = paired(make,self.work/name)
                self.assertTrue(all("evidence" not in i for i in referenced["items"]))
                self.assertEqual(rl.verify_pages(referenced,[image]),rl.verify_pages(embedded,[image]))
                if name=="clean":
                    self.assertEqual(rl.verify_pages(referenced,[legacy.paper()]),rl.verify_pages(embedded,[legacy.paper()]))

    def test_masks_polarity_registration_and_callable_embedded_views_match(self):
        for dark in (False,True):
            raw = legacy.dot()
            if dark: raw = 255-raw
            usable = np.ones(raw.shape[:2],bool); usable[:3] = False
            occluded = np.zeros_like(usable); occluded[44:48,60:63] = True
            members = [legacy.member(raw,"b",2.,usable=usable,occluded=occluded),legacy.member(raw.copy(),"a",0.)]
            members[0]["registration_shift"] = [.25,-.125]
            kwargs = dict(source_video="s",display_id="d",occurrence_id="o",members=members)
            embedded = rl.record_obligations(**kwargs)
            referenced = rl.record_obligations(**kwargs,evidence_dir=self.work/f"masks-{dark}")
            resolver = rl.EvidenceResolver(referenced,self.work/f"masks-{dark}")
            for a,b in zip(embedded["items"],referenced["items"]):
                self.assertEqual(list(resolver.views(b)),a["evidence"])
                self.assertEqual(b["expected_contrast"],a["expected_contrast"])
            streamed = [dict(m,image=lambda image=m["image"]:image.copy(),
                             usable=lambda mask=m.get("usable",True):mask,
                             occluded=lambda mask=m.get("occluded",False):mask) for m in members]
            self.assertEqual(rl.record_obligations(**dict(kwargs,members=streamed)),embedded)
            mask_only = [dict(m,image=members[i]["image"]) for i,m in enumerate(streamed)]
            self.assertEqual(rl.record_obligations(**dict(kwargs,members=mask_only)),embedded)
            refs = referenced["displays"][0]["members"][0]
            for key in ("usable_ref","occluded_ref"):
                with Image.open(Path(referenced["evidence_root"])/refs[key]["path"]) as image:
                    self.assertEqual(image.mode,"1")

    def frame_fixture(self, *, resize=False):
        frame = legacy.paper(100,140); frame[24:88,31:127] = legacy.dot()
        path = self.work/"frame.png"; self.assertTrue(cv2.imwrite(str(path),frame))
        manifest = {"observations":[{"id":"raw","t_sec":0.,"sample_kind":"coarse","frame_path":path.name,"system_regions":[{}]}]}
        inventory = assembly.inventory_observations(manifest,self.work,source_video="s")
        raw = frame[24:88,31:127]
        if resize: raw = cv2.resize(raw,(48,32),interpolation=cv2.INTER_AREA)
        member = legacy.member(raw,"raw",frame_ref={"observation_id":"raw","crop_box":[31,24,127,88]})
        fragment = rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",members=[member],evidence_dir=self.work/"evidence")
        ledger = assembly.merge_ledgers(inventory,fragment)
        assembly.annotate(ledger,[{"obs_id":"raw","stage":"composition","display_id":"d","occurrence_id":"o","role":"used","reason":None}])
        legacy.place(ledger); assembly.finalize_terminals(ledger)
        return ledger,raw,path

    def test_frame_ref_crop_resize_retention_pruning_and_missing_evidence(self):
        for resize in (False,True):
            ledger,raw,path = self.frame_fixture(resize=resize)
            self.assertFalse(list((self.work/"evidence").glob("*.png")))
            self.assertEqual(rl.verify_pages(ledger,[raw])["status"],"pass")
            self.assertEqual(assembly.retain_evidence(ledger,self.work/"job"),1)
            path.unlink()
            self.assertEqual(rl.verify_pages(ledger,[raw])["status"],"pass")
            retained = Path(ledger["observations"][0]["frame_path"]); retained.unlink()
            report = rl.verify_pages(ledger,[raw])
            self.assertEqual(report["status"],"review_required",report)
            self.assertIn("EVIDENCE_UNAVAILABLE",{i["code"] for i in report["issues"]})

    def test_streaming_refuses_changed_pixels_and_grayscale_frame_inventory_resolves(self):
        calls = 0
        def changing():
            nonlocal calls
            calls += 1
            image = legacy.dot(); image[10,10] = calls
            return image
        with self.assertRaisesRegex(ValueError,"pixels changed"):
            rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",
                members=[legacy.member(changing)],evidence_dir=self.work/"changing")
        path = self.work/"gray.png"
        image = cv2.cvtColor(legacy.dot(),cv2.COLOR_BGR2GRAY); cv2.imwrite(str(path),image)
        inventory = assembly.inventory_observations({"observations":[{"id":"g","t_sec":0.,"sample_kind":"coarse",
            "frame_path":path.name,"system_regions":[{}]}]},self.work,source_video="s")
        raw = cv2.imread(str(path))
        fragment = rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",
            members=[legacy.member(raw,"g",frame_ref={"observation_id":"g","crop_box":[0,0,96,64]})],evidence_dir=self.work/"gray")
        ledger = assembly.merge_ledgers(inventory,fragment)
        verifier.inventory(ledger); ledger["observations"][0].update(inventory["observations"][0],terminal="preserved",
            associations=[{"role":"used","display_id":"d"}])
        legacy.place(ledger)
        self.assertEqual(rl.verify_pages(ledger,[raw])["status"],"pass")

    def test_retention_keeps_referenced_blank_frame_and_tampering_never_passes(self):
        ledger,raw,_path = self.frame_fixture()
        ledger["observations"][0].update(terminal="non_score_material",foreground_px=0)
        self.assertEqual(assembly.retain_evidence(ledger,self.work/"job"),1)
        embedded,referenced,image = paired(lambda:(verifier.control(),legacy.dot()),self.work/"canvas")
        ref = referenced["displays"][0]["members"][0]["canvas_ref"]
        path = Path(referenced["evidence_root"])/ref["path"]
        path.write_bytes(path.read_bytes()+b"tampered")
        report = rl.verify_pages(referenced,[image])
        self.assertEqual(report["status"],"review_required",report)
        self.assertIn("EVIDENCE_UNAVAILABLE",{i["code"] for i in report["issues"]})

    @unittest.skip(RETIRED_VERIFIER)

    def test_malformed_reference_bits_and_mask_shapes_fail_without_report_crash(self):
        _embedded,ledger,image = paired(lambda:(verifier.control(),legacy.dot()),self.work/"invalid")
        ledger["items"][0]["evidence_bits"]["eligible"] = "not-hex"
        report = rl.verify_pages(ledger,[image])
        self.assertEqual(report["status"],"fail")
        self.assertIn("INVALID_EVIDENCE_OR_DISPOSITION",{i["code"] for i in report["issues"]})

    def test_missing_reference_with_typed_preserved_disposition_stays_unassessed(self):
        image = legacy.paper(); image[25,20:50] = 0
        _embedded,ledger,_image = paired(lambda:(verifier.control(image),image),self.work/"staff")
        item = ledger["items"][0]
        ledger["dispositions"] = [{"kind":"staff_scaffold","terminal":"preserved","item_id":item["id"],
            "staff_rows_display":[25],"retained_staff_rows_display":[25],"retained_item_id":item["id"]}]
        self.assertEqual(rl.verify_pages(ledger,[image])["status"],"pass")
        ref = ledger["displays"][0]["members"][0]["canvas_ref"]
        (Path(ledger["evidence_root"])/ref["path"]).unlink()
        report = rl.verify_pages(ledger,[image])
        self.assertEqual(report["status"],"review_required",report)
        self.assertIn("EVIDENCE_UNAVAILABLE",{i["code"] for i in report["issues"]})

    def test_partitioned_references_share_parent_members_without_copied_patches(self):
        original = rl.record_obligations
        with patch.object(rl,"record_obligations",side_effect=lambda **kw:original(**kw,evidence_dir=self.work/"partition")):
            ledger = routing.snapshot()
        before = set((self.work/"partition").iterdir())
        assembly.assemble_representations(ledger,[routing.chain()],[routing.measure(0,20),routing.measure(20,40)])
        resolver = rl.EvidenceResolver(ledger)
        parent = ledger["items"][0]
        self.assertEqual(len(parent["partitioned_into"]),2)
        for child in ledger["items"][1:]:
            self.assertNotIn("evidence",child)
            self.assertIs(resolver.members(child),resolver.members(parent))
            self.assertEqual(child["evidence_bits"],parent["evidence_bits"])
            view = next(resolver.views(child))
            self.assertEqual(rl.unpack_crop(view["display_patch"]).shape[:2],rl.unpack_crop(child["foreground_hypothesis"]).shape)
            self.assertTrue(rl.project_item(child,next(r["transforms"] for r in ledger["representations"] if r["item_id"]==child["id"]))[1].any())
        self.assertEqual(set((self.work/"partition").iterdir()),before)

    def test_superseded_inventory_membership_preserves_occurrence_members_without_composition_use(self):
        ledger,image = legacy.snapshot(legacy.dot()),legacy.dot()
        legacy.place(ledger)
        display = ledger["displays"][0]; old = display["id"]; display["id"] = "strip:s"
        for item in ledger["items"]: item["display_id"] = display["id"]
        occ = {"id":"occ:r","observations":display["observations"],"inventory_only":True,"shape":display["shape"]}
        ledger["displays"].append(occ)
        ledger["display_dispositions"] = [{"kind":"display_unresolved","terminal":"unresolved","display_id":"occ:r","reason":"candidate pending"},
            {"kind":"superseded_inventory","terminal":"equivalent_observation","display_id":"occ:r","retained_display_id":"strip:s"}]
        ledger["observations"][0].update(terminal=None,associations=[{"stage":"occurrence","display_id":"occ:r","role":"member","occurrence_id":"occ-A"},
            {"stage":"composition","display_id":"strip:s","role":"offered","reason":"not_sampled"}])
        self.assertEqual(assembly.finalize_terminals(ledger)["preserved"],1)
        self.assertEqual(ledger["observations"][0]["associations"][1]["role"],"offered")
        self.assertEqual(rl.verify_pages(ledger,[image])["status"],"pass")
        direct = copy.deepcopy(ledger)
        direct["display_dispositions"].insert(0,{"kind":"display_unresolved","terminal":"unresolved","display_id":"occ:r","reason":"candidate pending"})
        self.assertEqual(rl.verify_pages(direct,[image])["status"],"pass")
        merged = assembly.merge_ledgers(direct)
        self.assertFalse(any(d["kind"]=="display_unresolved" for d in merged["display_dispositions"]))
        broken = copy.deepcopy(ledger); broken["displays"][0]["observations"] = []
        self.assertEqual(rl.verify_pages(broken,[image])["status"],"fail")
        broken["observations"][0]["terminal"] = None
        self.assertEqual(assembly.finalize_terminals(broken)["unresolved"],1)
        offered = copy.deepcopy(ledger); offered["observations"][0].update(terminal=None,associations=[{"stage":"composition","display_id":"strip:s","role":"offered"}])
        self.assertEqual(assembly.finalize_terminals(offered)["unresolved"],1)

    def test_scaled_cut_sweep_282_cases_assign_centres_once_and_project(self):
        count = 0
        for scale in (1.2,1.25,1.5,1.75,2.,2.5):
            for cut in range(1,48):
                with self.subTest(scale=scale,cut=cut):
                    ledger = routing.snapshot()
                    width,height = int(np.ceil(40*scale)),int(np.ceil(16*scale))
                    assembly.assemble_representations(ledger,[routing.chain()],
                        [routing.measure(0,cut,scale=scale,height=height),routing.measure(cut,width,scale=scale,height=height)])
                    original = rl.unpack_crop(ledger["items"][0]["foreground_hypothesis"])>0
                    union = np.zeros_like(original,np.int32)
                    targets = ledger["items"][1:] if ledger["items"][0].get("partitioned_into") else ledger["items"]
                    ox,oy = ledger["items"][0]["display_bbox"][:2]
                    for target in targets:
                        mask = rl.unpack_crop(target["foreground_hypothesis"])>0
                        x0,y0,x1,y1 = target["display_bbox"]
                        union[y0-oy:y1-oy,x0-ox:x1-ox] += mask
                    np.testing.assert_array_equal(union,original.astype(np.int32))
                    for rep in ledger["representations"]:
                        item = next(i for i in ledger["items"] if i["id"]==rep["item_id"])
                        self.assertTrue(rl.project_item(item,rep["transforms"])[1].any())
                    count += 1
        self.assertEqual(count,282)
        print(f"SCALED_CUT_SWEEP cases={count} assembly_and_projection=OK")

    def test_chain_domain_routes_foreign_overlap_only_to_its_owner_and_unplaced_stays(self):
        ledger = routing.snapshot()
        a,b = routing.chain(strip="a"),routing.chain(strip="b")
        a["domain_strip"],b["domain_strip"] = [0,20],[20,40]
        assembly.assemble_representations(ledger,[a,b],[routing.placement(strip="a"),routing.placement(strip="b",page=1)])
        self.assertEqual(len(ledger["items"][0]["partitioned_into"]),2)
        for rep in ledger["representations"]:
            item = next(i for i in ledger["items"] if i["id"]==rep["item_id"])
            yy,xx = np.nonzero(rl.unpack_crop(item["foreground_hypothesis"]))
            xs = xx+item["display_bbox"][0]
            self.assertTrue((xs<20).all() if rep["page_index"]==0 else (xs>=20).all())
        missing = routing.snapshot(); a["domain_strip"] = [0,20]
        assembly.assemble_representations(missing,[a],[routing.placement(strip="a")])
        child = next(i for i in missing["items"][1:] if not any(r["item_id"]==i["id"] for r in missing["representations"]))
        self.assertGreaterEqual(child["display_bbox"][0],20)

    def test_cursor_underlay_witnesses_are_eligible_and_need_not_support_cursor_ink(self):
        ledger,image = verifier.cursor_fixture()
        for d in ledger["dispositions"]:
            item = next(i for i in ledger["items"] if i["id"]==d["item_id"])
            witnesses = [e for e in item["evidence"] if e["observation_id"] in {w["observation_id"] for w in d["recovery"]["witnesses"]}]
            self.assertTrue(all(e["eligible"] and not e["supports"] for e in witnesses))
        self.assertEqual(rl.verify_pages(ledger,[image])["status"],"pass")

    def test_40_member_1800x300_size_and_equivalence_limit(self):
        image = legacy.paper(300,1800)
        for row in range(8):
            for col in range(10): image[15+30*row:18+30*row,15+175*col:18+175*col] = 0
        members = [legacy.member(image,f"o-{i}",float(i)) for i in range(40)]
        kwargs = dict(source_video="s",display_id="d",occurrence_id="o",members=members)
        start = time.perf_counter(); embedded = rl.record_obligations(**kwargs); old_seconds = time.perf_counter()-start
        start = time.perf_counter(); referenced = rl.record_obligations(**kwargs,evidence_dir=self.work/"size"); new_seconds = time.perf_counter()-start
        verifier.inventory(embedded); verifier.inventory(referenced); legacy.place(embedded); legacy.place(referenced)
        self.assertGreaterEqual(len(referenced["items"]),60)
        self.assertLessEqual(size(referenced),1_500_000)
        self.assertEqual(rl.verify_pages(embedded,[image]),rl.verify_pages(referenced,[image]))
        print(f"SIZE_40 members=40 canvas=1800x300 items={len(referenced['items'])} old_bytes={size(embedded)} new_bytes={size(referenced)} old_record_sec={old_seconds:.3f} new_record_sec={new_seconds:.3f}")

    def test_streaming_60_members_memory_below_two_canvases_plus_accumulators(self):
        shape = (330,1900,3)
        calls = 0
        def load():
            nonlocal calls
            calls += 1
            raw = np.full(shape,255,np.uint8); raw[60:63,800:803] = 0
            return raw
        members = [legacy.member(load,"s-%d"%i,float(i)) for i in range(60)]
        gc.collect(); tracemalloc.start(); start = time.perf_counter()
        ledger = rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",members=members,evidence_dir=self.work/"stream")
        _current,peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        seconds = time.perf_counter()-start
        canvas_bytes = int(np.prod(shape))
        # Union, clear union, discovered; pass-local contrast/foreground/free and
        # native masks are the permitted full-canvas accumulators/masks.
        accumulator_bytes = shape[0]*shape[1]*7
        limit = canvas_bytes*2+accumulator_bytes
        self.assertEqual(calls,120)
        self.assertEqual(len(ledger["displays"][0]["members"]),60)
        self.assertLess(peak,limit)
        print(f"STREAM_60 members=60 canvas=1900x330 calls={calls} peak_tracemalloc_bytes={peak} canvas_bytes={canvas_bytes} accumulator_budget_bytes={accumulator_bytes} limit_bytes={limit} seconds={seconds:.3f} json_bytes={size(ledger)}")

    def test_round1_100_item_and_assembly_split_old_vs_new_bytes(self):
        image = legacy.paper(80,640)
        for row in range(10):
            for col in range(10): image[2+7*row:4+7*row,2+60*col:4+60*col] = 0
        members = [legacy.member(image,f"o-{i}",float(i)) for i in range(20)]
        kwargs = dict(source_video="s",display_id="d",occurrence_id="o",members=members)
        ledgers = [rl.record_obligations(**kwargs),rl.record_obligations(**kwargs,evidence_dir=self.work/"100")]
        for ledger in ledgers:
            verifier.inventory(ledger); assembly.assemble_representations(ledger,[routing.chain()],[routing.placement()]); assembly.finalize_terminals(ledger)
        self.assertEqual(len(ledgers[1]["items"]),100)
        print(f"SIZE_100 items=100 members=20 old_bytes={size(ledgers[0])} new_bytes={size(ledgers[1])}")
        original = rl.record_obligations
        split = [routing.snapshot()]
        with patch.object(rl,"record_obligations",side_effect=lambda **kw:original(**kw,evidence_dir=self.work/"split")):
            split.append(routing.snapshot())
        for ledger in split:
            assembly.assemble_representations(ledger,[routing.chain()],[routing.measure(0,20),routing.measure(20,40,page=1)])
        print(f"SIZE_SPLIT items={len(split[1]['items'])} old_bytes={size(split[0])} new_bytes={size(split[1])}")

    def test_round1_small_verifier_and_full_inventory_assembly_size_probes(self):
        for name,make in (("dot",lambda:(verifier.control(),legacy.dot())),("cursor",verifier.cursor_fixture),
                          ("equivalent",verifier.equivalent_fixture),("partition",verifier.partition_fixture)):
            old,new,_image = paired(make,self.work/name)
            print(f"SIZE_WA1_{name.upper()} old_bytes={size(old)} new_bytes={size(new)}")
        image = legacy.paper(80,640)
        for row in range(10):
            for col in range(10): image[2+7*row:4+7*row,2+60*col:4+60*col] = 0
        probe = routing.AssemblyTests(); probe.setUp(); self.addCleanup(probe.doCleanups)
        manifest = probe.manifest([image]*20)
        manifest["work_scale"] = {"scale":1.,"native_crop_size":[640,80]}
        inventory = assembly.inventory_observations(manifest,probe.work,source_video="source.mp4")
        members = [{"id":f"o-{k}","timestamp":float(k),"image":image,"roi_origin":[0,0],
                    "registration_shift":[0,0],"registration_uncertainty":0.} for k in range(20)]
        ledgers = []
        for referenced in (False,True):
            fragment = rl.record_obligations(source_video="source.mp4",display_id="d",occurrence_id="occ",
                members=members,evidence_dir=self.work/"full-assembly" if referenced else None)
            ledger = assembly.merge_ledgers(inventory,fragment)
            assembly.annotate(ledger,[routing.assoc(f"o-{k}",role="used") for k in range(20)])
            assembly.assemble_representations(ledger,[routing.chain()],[routing.placement()])
            assembly.finalize_terminals(ledger); ledgers.append(ledger)
        page = legacy.paper(100,660); page[10:90,10:650] = image
        self.assertEqual(rl.verify_pages(ledgers[0],[page]),rl.verify_pages(ledgers[1],[page]))
        print(f"SIZE_WA2_FULL_ASSEMBLY items=100 observations=20 old_bytes={size(ledgers[0])} new_bytes={size(ledgers[1])}")

    def test_round1_strip_and_six_display_chain_size_probes(self):
        import test_ledger_hooks_strips as strips
        import test_ledger_hooks_jump as jump
        original = rl.record_obligations
        calls = []
        def capture(**kw):
            calls.append(kw)
            return original(**kw)
        with patch.object(rl,"record_obligations",side_effect=capture):
            record = strips.benchmark()
        self.assertEqual(len(calls),1)
        referenced = original(**dict(calls[0],evidence_dir=self.work/"strip-probe"))
        referenced["observation_associations"] = record["ledger"].get("observation_associations",[])
        self.assertEqual(len(referenced["items"]),len(record["ledger"]["items"]))
        print(f"SIZE_WB_STRIP members=40 old_bytes={size(record['ledger'])} new_bytes={size(referenced)} new_indent2_bytes={len(json.dumps(referenced,indent=2).encode())}")
        # Capture actual episode raw members; regroup the round-1 producer's
        # per-member calls into the one-display call required by section 9.1.
        calls.clear()
        probe = jump.JumpLedgerHookTests(); self.addCleanup(probe.doCleanups)
        with patch.object(rl,"record_obligations",side_effect=capture):
            _fixture,built = probe._build(count=6,members=3,cuts=(120,230,340,450,560))
        grouped = {}
        for call in calls:
            if call["display_id"] not in grouped:
                grouped[call["display_id"]] = dict(call,members=[])
            grouped[call["display_id"]]["members"].extend(call["members"])
        fragments = [original(**dict(kw,evidence_dir=self.work/"jump-probe")) for kw in grouped.values()]
        referenced = assembly.merge_ledgers(*fragments)
        embedded = jump.rj._merge_ledger([r["ledger"] for _o,r in built])
        for name in ("display_dispositions","observation_associations"):
            referenced[name] = embedded.get(name,[])
        self.assertEqual(len(referenced["displays"]),6)
        self.assertEqual(sum(len(d["members"]) for d in referenced["displays"]),18)
        print(f"SIZE_WC_CHAIN displays=6 members=18 old_bytes={size(embedded)} new_bytes={size(referenced)} old_items={len(embedded['items'])} new_items={len(referenced['items'])} regrouped_per_display=True")


if __name__=="__main__":
    unittest.main()
