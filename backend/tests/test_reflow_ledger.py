"""Mutation and control tests using raw member evidence and delivered JPEG PDFs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.pipeline import reflow_ledger as rl
from app.pipeline.export import export_composed_pages


IDENTITY = np.eye(3).tolist()


def member(image, ident="obs-0", timestamp=0., **kw):
    return dict(id=ident, timestamp=timestamp, image=image, roi_origin=[10,20],
                registration_shift=[0,0], registration_uncertainty=0., **kw)


def chain(dx=0,dy=0,scale=1):
    return [{"stage":stage,"kind":"affine","matrix":([[scale,0,dx],[0,scale,dy],[0,0,1]] if stage=="line_to_page" else IDENTITY)} for stage in rl.STAGES]


def snapshot(image, occurrence="occ-A", display="display-A", observations=None):
    members = observations or [member(image)]
    return with_inventory(rl.record_obligations(source_video="synthetic.mp4",display_id=display,
                                 occurrence_id=occurrence,members=members),members)



def with_inventory(ledger,members):
    """Explicit v2 raw observation records for legacy passing controls."""
    display = ledger["displays"][0]
    ledger["observations"] = [{"id":str(m["id"]),"t_sec":float(m["timestamp"]),"sample_kind":"coarse",
        "frame_path":"", "pixels_sha256":rl.pixels_hash(m["image"]),
        "crop_size":[m["image"].shape[1],m["image"].shape[0]],"staff_regions":1,
        "foreground_px":int((rl._contrast(m["image"])>=rl.MIN_CONTRAST).sum()),
        "associations":[{"stage":"composition","display_id":display["id"],
                         "occurrence_id":display["occurrence_id"],"role":"used","reason":None}],
        "terminal":"preserved"} for m in members]
    return ledger


def a4(content):
    page = paper(3508,2480)
    page[:content.shape[0],:content.shape[1]] = content
    return page


def export_pdf(pages,workspace):
    return Path(export_composed_pages(pages=pages,formats=["pdf"],workspace=workspace,logger=lambda _m:None)["pdf"])

def place(ledger,dx=0,dy=0,scale=1,page=0):
    for item in ledger["items"]:
        for ci in range(item["expected_multiplicity"]):
            ledger["representations"].append({"item_id":item["id"],"occurrence_id":item["occurrence_id"],
                "copy_index":ci,"page_index":page,"transforms":chain(dx,dy,scale)})


def merge(a,b):
    for key in ("items","displays","representations","dispositions","generated_origins"):
        a[key].extend(b[key])
    by_id = {o["id"]:o for o in a.get("observations",[])}
    for obs in b.get("observations",[]):
        if obs["id"] in by_id:
            by_id[obs["id"]]["associations"].extend(obs["associations"])
        else:
            a.setdefault("observations",[]).append(obs)
    return a


def paper(h=64,w=96):
    return np.full((h,w,3),255,np.uint8)


def dot():
    a=paper()
    cv2.circle(a,(25,25),2,(0,0,0),-1)
    return a



RETIRED_VERIFIER = "Retired raw-projection verifier (DECISIONS 2026-10-09 staged verification): not in the product path; its loss/tamper controls live in test_verify_* now."

class LedgerTests(unittest.TestCase):
    def setUp(self):
        # Set TMPDIR to the worker scratchpad for a restricted worker run.
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)

    def assertCode(self,report,code):
        self.assertIn(code,[i["code"] for i in report["issues"]],report)

    def test_missing_dot(self):
        ledger=snapshot(dot()); place(ledger)
        report=rl.verify_pages(ledger,[paper()])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"SOURCE_FOREGROUND_MISSING_OR_CHANGED")
        self.assertIn("output_crop",report["issues"][0])

    def test_removed_gray_dynamic(self):
        a=paper(); cv2.putText(a,"p",(25,32),cv2.FONT_HERSHEY_SIMPLEX,.6,(170,170,170),1,cv2.LINE_AA)
        ledger=snapshot(a); place(ledger)
        report=rl.verify_pages(ledger,[paper()])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"SOURCE_FOREGROUND_MISSING_OR_CHANGED")

    def test_excluded_display_cannot_be_certified_covered(self):
        ledger=snapshot(dot()); ledger["exact_reconstruction"]=True
        ledger["covered"]=True; ledger["coverage"]={"status":"pass"}
        report=rl.verify_pages(ledger,[paper()])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"OUTPUT_MULTIPLICITY_MISMATCH")

    def test_equal_count_duplicate_plus_loss(self):
        a=dot(); b=paper(); cv2.rectangle(b,(23,22),(28,30),(0,0,0),-1)
        ledger=snapshot(a); other=snapshot(b,"occ-B","display-B")
        place(ledger); place(other,dx=40); merge(ledger,other)
        out=paper(w=150); out[:64,:96]=a
        # Two output regions, but A appears twice and B has disappeared.
        out[:64,40:136]=np.minimum(out[:64,40:136],a)
        report=rl.verify_pages(ledger,[out])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"SOURCE_FOREGROUND_MISSING_OR_CHANGED")

    def test_false_chrome_exemption_over_notation(self):
        ledger=snapshot(dot()); item=ledger["items"][0]
        ledger["dispositions"]=[{"item_id":item["id"],"kind":"chrome",
            "exclusion_mask":item["foreground_hypothesis"],"chrome_verified":True}]
        report=rl.verify_pages(ledger,[paper()])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"INVALID_EVIDENCE_OR_DISPOSITION")

    def test_overlap_owner_without_nonowner_dot(self):
        a=paper(); a[24,20:50]=0
        b=a.copy(); cv2.circle(b,(31,26),2,(0,0,0),-1)
        # Explicit matching coordinate window includes staff and non-owner dot.
        ledger=rl.record_obligations(source_video="synthetic.mp4",display_id="owner",occurrence_id="occ-A",members=[member(a)],candidates=[[18,20,52,31]])
        other=rl.record_obligations(source_video="synthetic.mp4",display_id="non-owner",occurrence_id="occ-A",members=[member(b)],candidates=[[18,20,52,31]])
        place(ledger); owner=ledger["items"][0]
        other["dispositions"]=[{"item_id":other["items"][0]["id"],"kind":"overlap_duplicate",
            "retained_item_id":owner["id"],"equivalence":"same_written_occurrence"}]
        merge(ledger,other)
        report=rl.verify_pages(ledger,[a])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"SOURCE_FOREGROUND_MISSING_OR_CHANGED")

    def test_uniform_scaling(self):
        a=dot(); ledger=snapshot(a); place(ledger,dx=12,dy=9,scale=1.5)
        out=paper(120,170)
        out[9:105,12:156]=cv2.resize(a,(144,96),interpolation=cv2.INTER_LINEAR)
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"pass")

    @unittest.skip(RETIRED_VERIFIER)

    def test_cursor_recovered_notation_retains_unwitnessed_cursor_for_review(self):
        a=dot(); covered=a.copy(); covered[:,20:31]=(190,110,60)
        occluded=np.zeros(a.shape[:2],bool); occluded[:,20:31]=True
        observations=[member(covered,"blocked",0.,occluded=occluded),member(a,"clear",2.)]
        ledger=snapshot(a,observations=observations); place(ledger)
        for item in ledger["items"]:
            ev=next(e for e in item["evidence"] if e["observation_id"]=="clear")
            if ev["supports"]:
                ledger["dispositions"].append({"item_id":item["id"],"kind":"cursor_recovery",
                    "clear_observation_id":"clear","raw_patch_sha256":ev["raw_patch"]["sha256"]})
            else:
                blocked=next(e for e in item["evidence"] if e["observation_id"]=="blocked")
                path=self.work / (item["id"] + ".png")
                cv2.imwrite(str(path),rl.unpack_crop(blocked["raw_patch"]))
                ledger["dispositions"].append({"item_id":item["id"],"kind":"unresolved_alternative",
                    "observation_id":"blocked","review_artifact":str(path)})
            self.assertEqual(item["support"]["eligible"],1)
        self.assertTrue(any(i["class"]=="credible-few" for i in ledger["items"]))
        self.assertTrue(any(i["class"]=="ambiguous" for i in ledger["items"]))
        self.assertEqual(rl.verify_pages(ledger,[a])["status"],"review_required")

    def test_genuine_repeated_occurrences(self):
        a=dot(); ledger=snapshot(a); other=snapshot(a,"occ-return","display-return")
        place(ledger); place(other,dx=60); merge(ledger,other)
        out=paper(w=160); out[:64,:96]=a; out[:64,60:156]=np.minimum(out[:64,60:156],a)
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"pass")

    def test_one_output_patch_cannot_satisfy_two_occurrences(self):
        a=dot(); ledger=snapshot(a); other=snapshot(a,"occ-B","display-B")
        place(ledger); place(other); merge(ledger,other)
        report=rl.verify_pages(ledger,[a])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"OUTPUT_PATCH_REUSED_BY_DISTINCT_OCCURRENCES")

    def test_jpeg_round_trip_delivered_pdf(self):
        from test_ledger_v2_verify import lossless_legacy_verify_pdf, lossless_legacy_pdf_pages
        a=dot(); cv2.putText(a,"p",(55,35),cv2.FONT_HERSHEY_SIMPLEX,.55,(155,155,155),1,cv2.LINE_AA)
        ledger=snapshot(a); place(ledger)
        delivered=a4(a)
        target=export_pdf([delivered],self.work/"delivered")
        report=lossless_legacy_verify_pdf(ledger,target)
        self.assertEqual(report["status"],"pass",report)
        self.assertEqual(len(report["embedded_pages"]),1)
        extracted=lossless_legacy_pdf_pages(target)
        self.assertEqual(extracted[0]["image"].shape,delivered.shape)
        self.assertNotEqual(rl.pixels_hash(a),extracted[0]["pixels_sha256"])

    def test_output_stale_content_without_source(self):
        a=dot(); ledger=snapshot(a); place(ledger)
        a[40:46,70:78]=0
        report=rl.verify_pages(ledger,[a])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"OUTPUT_FOREGROUND_WITHOUT_ORIGIN")

    def test_missing_dot_must_not_match_nearby_staff(self):
        a=dot(); ledger=snapshot(a); place(ledger)
        out=paper(); out[25,20:50]=0
        report=rl.verify_pages(ledger,[out])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"SOURCE_FOREGROUND_MISSING_OR_CHANGED")

    @unittest.skip(RETIRED_VERIFIER)

    def test_missing_dot_connected_to_long_staff_is_not_diluted(self):
        a=paper(); a[25,5:91]=0; cv2.circle(a,(40,25),2,(0,0,0),-1)
        ledger=snapshot(a); place(ledger)
        out=paper(); out[25,5:91]=0
        report=rl.verify_pages(ledger,[out])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"SOURCE_FOREGROUND_MISSING_OR_CHANGED")

    def test_uniform_shrink_jpeg_round_trip(self):
        from test_ledger_v2_verify import lossless_legacy_verify_pdf
        a=paper(100,160); cv2.circle(a,(35,40),3,(0,0,0),-1)
        cv2.putText(a,"p",(85,55),cv2.FONT_HERSHEY_SIMPLEX,.7,(140,140,140),2,cv2.LINE_AA)
        ledger=snapshot(a); place(ledger,dx=10,dy=8,scale=.75)
        out=paper(100,150); out[8:83,10:130]=cv2.resize(a,(120,75),interpolation=cv2.INTER_AREA)
        target=export_pdf([a4(out)],self.work/"shrink")
        report=lossless_legacy_verify_pdf(ledger,target)
        self.assertEqual(report["status"],"pass",report)

    def test_candidate_scope_cannot_silently_drop_other_raw_ink(self):
        a=dot(); a[45:50,70:75]=0
        ledger=rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",members=[member(a)],candidates=[[20,20,31,31]])
        place(ledger)
        report=rl.verify_pages(ledger,[dot()])
        self.assertEqual(report["status"],"review_required")
        self.assertCode(report,"RAW_FOREGROUND_INVENTORY_INCOMPLETE")

    def test_tiny_mark_registration_uncertainty_is_review(self):
        a=dot(); observations=[member(a)]; observations[0]["registration_uncertainty"]=.6
        ledger=snapshot(a,observations=observations); place(ledger)
        report=rl.verify_pages(ledger,[a])
        self.assertEqual(report["status"],"review_required")
        self.assertCode(report,"REGISTRATION_UNRESOLVED")

    def test_missing_registration_is_not_zero(self):
        a=dot(); observations=[member(a)]; observations[0].pop("registration_uncertainty")
        ledger=snapshot(a,observations=observations); place(ledger)
        self.assertEqual(rl.verify_pages(ledger,[a])["status"],"review_required")

    def test_independent_groups_and_obscured_denominator(self):
        a=dot(); observations=[]
        for i in range(4):
            frame=a.copy(); frame[0:4,0:4]=i*30  # distinct member frames
            observations.append(member(frame,f"clear-{i}",float(i*2)))
        blocked=paper(); occluded=np.ones(a.shape[:2],bool)
        observations.append(member(blocked,"blocked",9.,occluded=occluded))
        ledger=rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",members=observations,candidates=[[21,21,30,30]])
        self.assertEqual(ledger["items"][0]["class"],"protected")
        self.assertEqual(ledger["items"][0]["support"],{"eligible":4,"supporting":4,"ratio":1.,"separated_groups":4})

    def test_near_identical_consecutive_frames_count_once(self):
        a=dot(); observations=[member(a,f"obs-{i}",float(i*2)) for i in range(5)]
        ledger=snapshot(a,observations=observations)
        self.assertEqual(ledger["items"][0]["class"],"credible-few")
        self.assertEqual(ledger["items"][0]["support"]["eligible"],1)

    def test_gray_minority_not_erased_by_majority(self):
        a=paper(); a[20:25,25:29]=175
        observations=[member(a,"only",0.)]+[member(paper(),f"blank-{i}",float(i+1)) for i in range(5)]
        ledger=snapshot(a,observations=observations); place(ledger)
        self.assertEqual(ledger["items"][0]["class"],"credible-few")
        self.assertEqual(rl.verify_pages(ledger,[paper()])["status"],"fail")

    def test_majority_staff_cannot_certify_minority_dot_as_repeated(self):
        base=paper(); base[25,5:91]=0
        observations=[]
        for i in range(4):
            a=base.copy(); a[0:4,0:4]=i*30
            if i==0:
                cv2.circle(a,(40,25),2,(0,0,0),-1)
            observations.append(member(a,f"obs-{i}",float(i*2)))
        ledger=snapshot(base,observations=observations)
        affected=[item for item in ledger["items"] if item["display_bbox"][0]<=40<item["display_bbox"][2]
                  and item["display_bbox"][1]<=23<item["display_bbox"][3]]
        self.assertTrue(affected)
        for item in affected:
            self.assertEqual(item["class"],"credible-few")
            self.assertEqual(item["support"]["supporting"],1)

    def test_ambiguous_requires_review_even_if_preserved(self):
        a=dot(); ledger=snapshot(a,observations=[member(a,occluded=np.ones(a.shape[:2],bool))]); place(ledger)
        self.assertEqual(ledger["items"][0]["class"],"ambiguous")
        self.assertEqual(rl.verify_pages(ledger,[a])["status"],"review_required")

    def test_unresolved_alternative_requires_actual_artifact(self):
        a=dot(); ledger=snapshot(a); item=ledger["items"][0]; ev=item["evidence"][0]
        path=self.work/"review.png"; cv2.imwrite(str(path),rl.unpack_crop(ev["raw_patch"]))
        ledger["dispositions"]=[{"item_id":item["id"],"kind":"unresolved_alternative","terminal":"unresolved","review_artifact":str(path),"observation_id":ev["observation_id"]}]
        ledger["observations"][0]["terminal"]="unresolved"
        self.assertEqual(rl.verify_pages(ledger,[paper()])["status"],"review_required")
        cv2.imwrite(str(path),np.full(rl.unpack_crop(ev["raw_patch"]).shape,255,np.uint8))
        self.assertEqual(rl.verify_pages(ledger,[paper()])["status"],"fail")

    def test_piecewise_cut_join_displacement(self):
        a=paper(); a[20:25,23:28]=0; a[20:25,55:60]=0
        ledger=snapshot(a); place(ledger)
        for r in ledger["representations"]:
            r["transforms"][1]={"stage":"strip_to_line","kind":"piecewise","pieces":[
                {"src_bbox":[0,0,45,64],"matrix":IDENTITY},
                {"src_bbox":[45,0,96,64],"matrix":[[1,0,10],[0,1,0],[0,0,1]]}]}
        out=paper(w=106); out[:,:45]=a[:,:45]; out[:,55:]=a[:,45:]
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"pass")

    def test_piecewise_omitted_mark_fails(self):
        a=dot(); ledger=snapshot(a); place(ledger)
        ledger["representations"][0]["transforms"][1]={"stage":"strip_to_line","kind":"piecewise","pieces":[{"src_bbox":[0,0,10,64],"matrix":IDENTITY}]}
        report=rl.verify_pages(ledger,[paper()])
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"TRANSFORM_DROPS_OR_DUPLICATES_FOREGROUND")

    def test_adapter_reads_measure_column_map_not_flags(self):
        p={"cols_src_out":[10,20],"rows_src_out":[0,64],"width_out":12,"x_out":10,"y_out":0,
           "inserted_offsets":[5,6],"removed_cols_out":[],"line_id":"line-0","exact_reconstruction":False}
        transform=rl.measure_placement_transform(p)
        self.assertEqual([q["src_bbox"] for q in transform["pieces"]],[[10,0,15,64],[15,0,20,64]])
        self.assertEqual([q["matrix"][0][2] for q in transform["pieces"]],[0,2])
        a=paper(); a[20:23,17:20]=0
        ledger=snapshot(a); place(ledger)
        for rep in ledger["representations"]:
            rep["transforms"][1]=transform
        out=paper(); out[20:23,19:22]=0
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"pass")

    def test_adapter_refuses_insufficient_measure_record(self):
        p={"cols_src_out":[0,10],"rows_src_out":[0,10],"width_out":9,"x_out":0,"y_out":0,"removed_cols_out":[],"inserted_offsets":[]}
        with self.assertRaises(ValueError):
            rl.measure_placement_transform(p)

    def test_empty_ledger_does_not_pass(self):
        self.assertEqual(rl.verify_pages({},[paper()])["status"],"review_required")

    @unittest.skip(RETIRED_VERIFIER)

    def test_missing_transform_chain_does_not_pass(self):
        a=dot(); ledger=snapshot(a); place(ledger); ledger["representations"][0]["transforms"]=[]
        report=rl.verify_pages(ledger,[paper()])
        self.assertEqual(report["status"],"review_required")

    @unittest.skip(RETIRED_VERIFIER)

    def test_unknown_transform_with_preserved_ink_is_unassessed(self):
        a=dot(); ledger=snapshot(a); place(ledger); ledger["representations"][0]["transforms"]=[]
        report=rl.verify_pages(ledger,[a])
        self.assertEqual(report["status"],"review_required")
        self.assertCode(report,"TRANSFORM_UNRESOLVED")

    def test_malformed_delivered_pdf_is_unassessed(self):
        target=self.work/"bad.pdf"; target.write_bytes(b"%PDF-1.4\ninvalid\n%%EOF")
        report=rl.verify_pdf({},target)
        # Malformed/non-A4 PDFs cannot be a delivery from our A4 exporter.
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"PDF_CONTRACT_VIOLATION")

    def test_generated_staff_needs_actual_scaffold_geometry(self):
        a=paper(); a[25,10:40]=0
        ledger=snapshot(a); place(ledger)
        template=paper(7,36); template[3,2:34]=0
        out=a.copy(); out[45:52,10:46]=template
        ledger["generated_origins"]=[{"kind":"staff_scaffold","page_index":0,"origin":[10,45],"template":rl.pack_crop(template),
            "source_item_id":ledger["items"][0]["id"],"staff_rows_display":[25],"staff_rows_local":[3]}]
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"pass")
        template[1,20]=0; ledger["generated_origins"][0]["template"]=rl.pack_crop(template)
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"fail")

    def test_staff_exemption_cannot_hide_dot(self):
        a=paper(); a[24,20:50]=0; cv2.circle(a,(31,26),2,(0,0,0),-1)
        ledger=rl.record_obligations(source_video="s",display_id="d",occurrence_id="o",members=[member(a)],candidates=[[18,20,52,31]])
        item=ledger["items"][0]
        ledger["dispositions"]=[{"item_id":item["id"],"kind":"staff_scaffold","staff_rows_display":[24],"retained_item_id":item["id"],"retained_staff_rows_display":[24]}]
        report=rl.verify_pages(ledger,[paper()]); self.assertEqual(report["status"],"fail")
        self.assertCode(report,"INVALID_EVIDENCE_OR_DISPOSITION")

    @unittest.skip(RETIRED_VERIFIER)

    def test_crops_json_serializable_and_tamper_detected(self):
        a=dot(); ledger=snapshot(a); place(ledger)
        restored=json.loads(json.dumps(ledger))
        self.assertEqual(rl.verify_pages(restored,[a])["status"],"pass")
        restored["items"][0]["evidence"][0]["raw_patch"]["sha256"]="fake"
        self.assertEqual(rl.verify_pages(restored,[a])["status"],"fail")

    def test_pdf_page_tree_order_and_wrong_dpi(self):
        from test_ledger_v2_verify import lossless_legacy_pdf_pages
        a=dot(); b=paper(); b[35:39,60:64]=0
        target=export_pdf([a4(a),a4(b)],self.work/"multi")
        extracted=lossless_legacy_pdf_pages(target)
        self.assertEqual(len(extracted),2)
        self.assertLess(_lum(extracted[0]["image"])[25,25],30)
        self.assertLess(_lum(extracted[1]["image"])[36,61],30)
        # A wrong-DPI/non-A4 PDF is a proven delivery contract violation.
        Image.fromarray(cv2.cvtColor(a4(a),cv2.COLOR_BGR2RGB)).save(target,"PDF",resolution=600,quality=92)
        report=rl.verify_pdf({},target)
        self.assertEqual(report["status"],"fail")
        self.assertCode(report,"PDF_CONTRACT_VIOLATION")

    def test_blank_display_not_unqualified_pass(self):
        ledger=snapshot(paper())
        ledger["observations"][0]["terminal"]="unresolved"
        self.assertEqual(rl.verify_pages(ledger,[paper()])["status"],"review_required")


def _lum(a):
    return cv2.cvtColor(a,cv2.COLOR_BGR2GRAY)


if __name__=="__main__":
    unittest.main()
