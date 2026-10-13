"""Small raw-evidence controls and mutations for the display-ledger-2 verifier."""
import copy
import json
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_ledger as rl
from app.pipeline.export import export_composed_pages
from test_reflow_ledger import IDENTITY, chain, dot, member, paper, place, snapshot


_legacy_verify_pdf = rl.verify_pdf


def lossless_legacy_pdf_pages(path):
    from app.pipeline import reflow_verify_page as vp
    pages = vp.decode_lossless_pdf(path, profile="lossless")
    return [{"image": cv2.cvtColor(p, cv2.COLOR_GRAY2BGR) if p.ndim == 2 else p,
             "page_index": i, "pixels_sha256": rl.pixels_hash(p), "jpeg_encoding": None}
            for i, p in enumerate(pages)]


def lossless_legacy_verify_pdf(ledger, path, *, pages_sink=None):
    """Fixture plumbing: keep the retired raw verifier over actual Flate pixels."""
    with patch.object(rl, "extract_pdf_pages", side_effect=lossless_legacy_pdf_pages), \
            patch.object(rl, "_encoded_reference", return_value=None):
        return _legacy_verify_pdf(ledger, path, pages_sink=pages_sink)


def inventory(ledger, terminal="preserved"):
    """Fixture inventory is explicit, never silently supplied by the verifier."""
    by_id = {}
    for display in ledger["displays"]:
        for ident in display["observations"]:
            by_id.setdefault(ident,{"id":ident,"terminal":terminal,"associations":[]})["associations"].append(
                {"role":"used","display_id":display["id"]})
    ledger["observations"] = list(by_id.values())
    return ledger


def control(image=None):
    ledger = inventory(snapshot(dot() if image is None else image))
    place(ledger)
    return ledger


def merge_v2(a,b):
    for key in ("items","displays","representations","dispositions","generated_origins",
                "observations","display_dispositions","occurrence_remaps"):
        a[key].extend(b[key])
    return a


def equivalent_fixture(extra=False):
    image = paper(); image[25,20:50] = 0
    owner = inventory(snapshot(image,display="retained",observations=[member(image,"owner-observation")]))
    place(owner)
    excluded = image.copy()
    if extra:
        excluded[44:47,65:68] = 0
    other = inventory(snapshot(excluded,display="excluded",observations=[member(excluded,"excluded-observation")]),"equivalent_observation")
    merge_v2(owner,other)
    owner["display_dispositions"] = [{"kind":"display_equivalent","terminal":"equivalent_observation",
        "display_id":"excluded","retained_display_id":"retained","equivalence_map":IDENTITY,
        "registration_uncertainty":0.,"evidence":{"method":"raw_registration"}}]
    return owner,image


def cursor_fixture():
    underlay = dot()
    frames = []
    for ident,x,t in (("blocked",65,0.),("clear-a",77,2.),("clear-b",88,4.)):
        image = underlay.copy(); image[12:50,x:x+2] = (190,110,60)
        occluded = np.zeros(image.shape[:2],bool); occluded[12:50,x:x+2] = True
        frames.append(member(image,ident,t,occluded=occluded))
    ledger = inventory(snapshot(underlay,observations=frames))
    for item in ledger["items"]:
        if item["class"]!="ambiguous":
            ledger["representations"].append({"item_id":item["id"],"occurrence_id":item["occurrence_id"],
                "copy_index":0,"page_index":0,"transforms":chain()})
            continue
        clear = [e for e in item["evidence"] if e["eligible"]]
        positions = {"blocked":65,"clear-a":77,"clear-b":88}
        ledger["dispositions"].append({"kind":"cursor_recovery","terminal":"recovered_beneath_overlay",
            "item_id":item["id"],"clear_observation_id":clear[0]["observation_id"],
            "raw_patch_sha256":clear[0]["raw_patch"]["sha256"],"recovery":{
                "witnesses":[{"observation_id":e["observation_id"],"cursor_x":positions[e["observation_id"]],
                              "residual_registration_px":0.} for e in clear],
                "recovered_mask":item["foreground_hypothesis"]}})
    return ledger,underlay


def partition_fixture():
    image = paper(); image[25,20:50] = 0
    ledger = inventory(snapshot(image)); parent = ledger["items"][0]
    mask = rl.unpack_crop(parent["foreground_hypothesis"])
    c = rl.unpack_crop(parent["expected_contrast"])
    x0,y0,x1,y1 = parent["display_bbox"]
    cut = mask.shape[1]//2
    children = []
    for k,(a,b) in enumerate(((0,cut),(cut,mask.shape[1]))):
        child = copy.deepcopy(parent)
        child.update(id=f'{parent["id"]}/p{k}',partition_of=parent["id"],display_bbox=[x0+a,y0,x0+b,y1],
                     foreground_hypothesis=rl.pack_crop(mask[:,a:b]),expected_contrast=rl.pack_crop(c[:,a:b]))
        # Evidence is genuinely cropped to the child window.
        for e in child["evidence"]:
            for field in ("raw_patch","display_patch","contrast","usable_mask","native_usable_mask","native_occluded_mask"):
                e[field] = rl.pack_crop(rl.unpack_crop(e[field])[:,a:b])
            e["native_bbox"] = [x0+a,y0,x0+b,y1]
        children.append(child)
    parent["partitioned_into"] = [ch["id"] for ch in children]
    ledger["items"].extend(children)
    for child in children:
        ledger["representations"].append({"item_id":child["id"],"occurrence_id":child["occurrence_id"],
            "copy_index":0,"page_index":0,"transforms":chain()})
    return ledger,image


def hand_pdf(path, *, page_extra=b"", image_extra=b"", resources=None, commands=None,
             size=(595.2,841.92), inherited=False, compressed=False):
    """Classic xref with real lossless A4 gray pixels, not object-counting fixtures."""
    pixels = zlib.compress(b"\xff" * (2480 * 3508), level=9)
    w,h = size
    commands = commands if commands is not None else f"q {w} 0 0 {h} 0 0 cm /Im Do Q".encode()
    filt = b""
    if compressed:
        commands = zlib.compress(commands); filt = b" /Filter /FlateDecode"
    attr = f" /MediaBox [0 0 {w} {h}]".encode()+b" /Resources "+(resources or b"<< /XObject << /Im 4 0 R >> >>")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1"+(attr if inherited else b"")+b" >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 5 0 R"+(b"" if inherited else attr)+page_extra+b" >>",
        b"<< /Type /XObject /Subtype /Image /Width 2480 /Height 3508 /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length "+str(len(pixels)).encode()+image_extra+b" >>\nstream\n"+pixels+b"\nendstream",
        b"<< /Length "+str(len(commands)).encode()+filt+b" >>\nstream\n"+commands+b"\nendstream"]
    data = bytearray(b"%PDF-1.4\n"); offsets = [0]
    for ident,obj in enumerate(objects,1):
        offsets.append(len(data)); data.extend(f"{ident} 0 obj\n".encode()+obj+b"\nendobj\n")
    xref = len(data); data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)



RETIRED_VERIFIER = "Retired raw-projection verifier (DECISIONS 2026-10-09 staged verification): not in the product path; its loss/tamper controls live in test_verify_* now."

class LedgerV2VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def codes(self,report):
        return {i["code"] for i in report["issues"]}

    def assertCode(self,report,code):
        self.assertIn(code,self.codes(report),report)

    def test_1_version_and_missing_observation_inventory(self):
        ledger = snapshot(dot()); ledger["observations"] = []; place(ledger)
        self.assertEqual(rl.VERSION,"display-ledger-2")
        for key in ("observations","display_dispositions","occurrence_remaps"):
            self.assertEqual(ledger[key],[])
        for version in ("display-ledger-1",rl.VERSION):
            with self.subTest(version=version):
                ledger["version"] = version
                report = rl.verify_pages(ledger,[dot()])
                self.assertEqual(report["status"],"review_required")
                self.assertCode(report,"OBSERVATION_INVENTORY_MISSING")
                self.assertEqual(len(report["matches"]),1)
                self.assertEqual(rl.verify_pages(ledger,[paper()])["status"],"fail")
        ledger["version"] = rl.VERSION; inventory(ledger)
        self.assertEqual(rl.verify_pages(ledger,[dot()])["status"],"pass")

    @unittest.skip(RETIRED_VERIFIER)

    def test_2_typed_terminals_valid_and_missing_evidence(self):
        ledger = control(); obs = ledger["observations"][0]
        self.assertEqual(rl.verify_pages(ledger,[dot()])["status"],"pass")
        obs["associations"] = []
        self.assertCode(rl.verify_pages(ledger,[dot()]),"PRESERVED_NOT_DELIVERED")
        for terminal in (None,"invented"):
            obs["terminal"] = terminal
            self.assertCode(rl.verify_pages(ledger,[dot()]),"OBSERVATION_WITHOUT_TERMINAL")
        obs.update(terminal="non_score_material",staff_regions=0,detector_version="fixture-v1",pixels_sha256=rl.pixels_hash(paper()))
        self.assertEqual(rl.verify_pages(ledger,[dot()])["status"],"pass")
        for key in ("staff_regions","detector_version","pixels_sha256"):
            broken = copy.deepcopy(ledger); broken["observations"][0].pop(key)
            self.assertCode(rl.verify_pages(broken,[dot()]),"TERMINAL_EVIDENCE_MISSING")
        obs["associations"] = [{"role":"offered","display_id":"display-A"}]
        self.assertCode(rl.verify_pages(ledger,[dot()]),"TERMINAL_EVIDENCE_MISSING")
        for reason in rl.SOURCE_LIMIT_REASONS:
            obs.update(terminal="source_limited",reason=reason,measured_value=.2)
            report = rl.verify_pages(ledger,[dot()]); self.assertEqual(report["status"],"review_required")
            self.assertNotIn("TERMINAL_EVIDENCE_MISSING",self.codes(report))
        obs.pop("measured_value")
        obs.update(reason="registration_out_of_range",t_sec=3.)
        self.assertCode(rl.verify_pages(ledger,[dot()]),"TERMINAL_EVIDENCE_MISSING")
        obs.update(measured_value=.2,reason="invented")
        self.assertCode(rl.verify_pages(ledger,[dot()]),"TERMINAL_EVIDENCE_MISSING")
        path = self.work/"unresolved.png"; cv2.imwrite(str(path),dot())
        obs.update(terminal="unresolved",review_artifact=str(path),pixels_sha256=rl.pixels_hash(dot()))
        report = rl.verify_pages(ledger,[dot()]); self.assertCode(report,"OBSERVATION_UNRESOLVED")
        self.assertNotIn("TERMINAL_EVIDENCE_MISSING",self.codes(report))
        obs.pop("review_artifact")
        self.assertCode(rl.verify_pages(ledger,[dot()]),"TERMINAL_EVIDENCE_MISSING")
        equivalent,image = equivalent_fixture()
        self.assertEqual(rl.verify_pages(equivalent,[image])["status"],"pass")
        equivalent["display_dispositions"] = []
        self.assertCode(rl.verify_pages(equivalent,[image]),"TERMINAL_EVIDENCE_MISSING")
        recovery,image = cursor_fixture()
        for obs in recovery["observations"]:
            obs["terminal"] = "recovered_beneath_overlay"
        report = rl.verify_pages(recovery,[image]); self.assertEqual(report["status"],"pass",report)
        recovery["dispositions"][0].pop("recovery")
        self.assertCode(rl.verify_pages(recovery,[image]),"TERMINAL_EVIDENCE_MISSING")
        report = rl.verify_pages(control(),[dot()])
        self.assertEqual(report["terminal_counts"]["items"]["preserved"],1)
        self.assertEqual(report["terminal_counts"]["observations"]["preserved"],1)
        ambiguous = control(); ambiguous["items"][0]["class"] = "ambiguous"
        self.assertEqual(rl.verify_pages(ambiguous,[dot()])["terminal_counts"]["items"]["unresolved"],1)

    def test_2_item_disposition_terminals_and_evidence(self):
        image = paper(); image[25,20:50] = 0
        cases = [
            ("staff_scaffold",{"staff_rows_display":[25],"retained_staff_rows_display":[25],"retained_item_id":"self"}),
            ("chrome",{}),("preview_inset",{}),("structural_replacement",{}),
            ("unresolved_alternative",{}),("source_limited",{"reason":"source_clipped","measured_value":3})]
        for kind,fields in cases:
            with self.subTest(kind=kind):
                ledger = control(image); item = ledger["items"][0]
                d = dict(item_id=item["id"],kind=kind,terminal=rl.DISPOSITION_TERMINAL[kind],**fields)
                if kind=="staff_scaffold":
                    d["retained_item_id"] = item["id"]
                elif kind in ("chrome","preview_inset","structural_replacement"):
                    d["exclusion_mask"] = rl.pack_crop(np.zeros_like(rl.unpack_crop(item["foreground_hypothesis"])))
                elif kind=="unresolved_alternative":
                    path = self.work/f"{kind}.png"; cv2.imwrite(str(path),rl.unpack_crop(item["evidence"][0]["raw_patch"]))
                    d.update(review_artifact=str(path),observation_id="obs-0")
                ledger["dispositions"] = [d]
                report = rl.verify_pages(ledger,[image]); self.assertNotEqual(report["status"],"fail",report)
                self.assertNotIn("TERMINAL_EVIDENCE_MISSING",self.codes(report))
                d.pop("terminal")
                self.assertCode(rl.verify_pages(ledger,[image]),"TERMINAL_EVIDENCE_MISSING")
                d["terminal"] = "wrong"
                self.assertEqual(rl.verify_pages(ledger,[image])["status"],"fail")
                d["terminal"] = rl.DISPOSITION_TERMINAL[kind]
                for key in ("exclusion_mask","staff_rows_display","review_artifact","measured_value"):
                    d.pop(key,None)
                self.assertCode(rl.verify_pages(ledger,[image]),"TERMINAL_EVIDENCE_MISSING")
        ledger = control(); item = ledger["items"][0]
        owner = copy.deepcopy(item); owner["id"] += ":owner"; ledger["items"].append(owner)
        ledger["representations"][0]["item_id"] = owner["id"]
        d = {"item_id":item["id"],"kind":"overlap_duplicate","terminal":"equivalent_observation",
             "retained_item_id":owner["id"],"equivalence":"same_written_occurrence"}
        ledger["dispositions"] = [d]
        self.assertEqual(rl.verify_pages(ledger,[dot()])["status"],"pass")
        d.pop("retained_item_id")
        self.assertCode(rl.verify_pages(ledger,[dot()]),"TERMINAL_EVIDENCE_MISSING")

    def test_3_cursor_recovery_full_insufficient_partial_and_delivered_overlay(self):
        ledger,image = cursor_fixture()
        report = rl.verify_pages(ledger,[image]); self.assertEqual(report["status"],"pass",report)
        self.assertNotIn("AMBIGUOUS_EVIDENCE",self.codes(report))
        for mutation in ("one","same","residual","missing","ineligible","hash"):
            with self.subTest(mutation=mutation):
                broken = copy.deepcopy(ledger); d = broken["dispositions"][0]; w = d["recovery"]["witnesses"]
                if mutation=="one": d["recovery"]["witnesses"] = w[:1]
                elif mutation=="same": w[1]["cursor_x"] = w[0]["cursor_x"]
                elif mutation=="residual": w[1]["residual_registration_px"] = .6
                elif mutation=="missing": d.pop("recovery")
                elif mutation=="ineligible":
                    target = next(i for i in broken["items"] if i["id"]==d["item_id"])
                    next(e for e in target["evidence"] if e["observation_id"]==w[1]["observation_id"])["eligible"] = False
                elif mutation=="hash": d["raw_patch_sha256"] = "wrong"
                report = rl.verify_pages(broken,[image]); self.assertEqual(report["status"],"review_required",report)
                self.assertCode(report,"CURSOR_RECOVERY_INSUFFICIENT")
                self.assertCode(report,"AMBIGUOUS_EVIDENCE")
        partial = copy.deepcopy(ledger); d = partial["dispositions"][0]
        mask = rl.unpack_crop(d["recovery"]["recovered_mask"]); full = mask>0
        yy,xx = np.nonzero(full); mask[yy[:len(yy)//2],xx[:len(xx)//2]] = 0
        d["recovery"]["recovered_mask"] = rl.pack_crop(mask)
        report = rl.verify_pages(partial,[image]); self.assertEqual(report["status"],"review_required")
        issue = next(i for i in report["issues"] if i["code"]=="PARTIAL_RECOVERY_REMAINDER")
        self.assertEqual(issue["pixels"],int((full & ~(mask>0)).sum()))
        delivered = copy.deepcopy(ledger); item = next(i for i in delivered["items"] if i["id"]==d["item_id"])
        delivered["representations"].append({"item_id":item["id"],"occurrence_id":item["occurrence_id"],"copy_index":0,"page_index":0,"transforms":chain()})
        self.assertCode(rl.verify_pages(delivered,[image]),"OVERLAY_DELIVERED")

    def test_4_display_equivalence_inventory_unresolved_and_unaccounted(self):
        ledger,image = equivalent_fixture()
        self.assertEqual(rl.verify_pages(ledger,[image])["status"],"pass")
        ledger,image = equivalent_fixture(extra=True)
        report = rl.verify_pages(ledger,[image]); self.assertEqual(report["status"],"fail")
        self.assertCode(report,"EQUIVALENCE_CONTAINMENT_FAILED")
        mismatch = next(i for i in report["issues"] if i["code"]=="EQUIVALENCE_CONTAINMENT_FAILED")
        self.assertLessEqual(max(rl.unpack_crop(mismatch["mismatch_crop"]).shape[:2]),96)
        self.assertNotIn("OUTPUT_MULTIPLICITY_MISMATCH",self.codes(report))
        ledger = control(); ledger["representations"] = []
        self.assertCode(rl.verify_pages(ledger,[paper()]),"DISPLAY_UNACCOUNTED")
        ledger["display_dispositions"] = [{"kind":"display_unresolved","terminal":"unresolved","display_id":"display-A","reason":"registration unavailable"}]
        ledger["observations"][0]["terminal"] = "unresolved"
        report = rl.verify_pages(ledger,[paper()]); self.assertEqual(report["status"],"review_required")
        self.assertCode(report,"DISPLAY_UNRESOLVED")
        self.assertNotIn("OUTPUT_MULTIPLICITY_MISMATCH",self.codes(report))
        self.assertEqual(report["terminal_counts"]["items"]["unresolved"],1)
        retained = inventory(snapshot(dot(),display="strip:s",observations=[member(dot(),"raw")]))
        place(retained)
        occ = snapshot(dot(),display="occ:r",observations=[member(dot(),"raw")]); occ["observations"] = []; merge_v2(retained,occ)
        retained["display_dispositions"] = [{"kind":"superseded_inventory","terminal":"equivalent_observation","display_id":"occ:r","retained_display_id":"strip:s"}]
        self.assertEqual(rl.verify_pages(retained,[dot()])["status"],"pass")
        retained["displays"][1]["observations"].append("dropped")
        self.assertCode(rl.verify_pages(retained,[dot()]),"INVENTORY_MEMBER_DROPPED")
        ledger,image = equivalent_fixture(); ledger["representations"] = []
        self.assertCode(rl.verify_pages(ledger,[paper()]),"PRESERVED_NOT_DELIVERED")

    def test_4_preview_tail_region_and_crossing_item(self):
        image = dot(); image[44:47,65:68] = 0
        ledger = inventory(snapshot(dot(),display="retained",observations=[member(dot(),"owner")]))
        place(ledger)
        other = inventory(snapshot(image,display="preview",observations=[member(image,"preview-obs")]))
        # Only the tail dot is delivered; the leading dot is already in retained.
        place(other,dx=10)
        other["representations"] = [r for r in other["representations"] if next(i for i in other["items"] if i["id"]==r["item_id"])["display_bbox"][0]>50]
        merge_v2(ledger,other)
        ledger["display_dispositions"] = [{"kind":"display_equivalent","terminal":"equivalent_observation","display_id":"preview","retained_display_id":"retained","equivalence_map":IDENTITY,"registration_uncertainty":0.,"region":[0,0,50,64],"evidence":{"method":"preview_tail"}}]
        out = paper(w=116); out[:,:96] = dot(); out[44:47,75:78] = 0
        self.assertEqual(rl.verify_pages(ledger,[out])["status"],"pass")
        ledger["display_dispositions"][0]["region"][2] = 25
        # A crossing item stays represented and gets a typed review issue.
        first = next(i for i in ledger["items"] if i["display_id"]=="preview" and i["display_bbox"][0]<50)
        ledger["representations"].append({"item_id":first["id"],"occurrence_id":first["occurrence_id"],"copy_index":0,"page_index":0,"transforms":chain()})
        report = rl.verify_pages(ledger,[out]); self.assertEqual(report["status"],"review_required",report)
        self.assertCode(report,"EQUIVALENCE_REGION_SPLITS_ITEM")

    def test_5_partition_exact_gap_overlap(self):
        ledger,image = partition_fixture()
        report = rl.verify_pages(ledger,[image]); self.assertEqual(report["status"],"pass",report)
        self.assertNotIn("OUTPUT_MULTIPLICITY_MISMATCH",self.codes(report))
        broken = copy.deepcopy(ledger); ch = broken["items"][1]; mask = rl.unpack_crop(ch["foreground_hypothesis"])
        yy,xx = np.nonzero(mask); mask[yy[0],xx[0]] = 0; ch["foreground_hypothesis"] = rl.pack_crop(mask)
        self.assertCode(rl.verify_pages(broken,[image]),"PARTITION_MISMATCH")
        broken = copy.deepcopy(ledger); child = copy.deepcopy(broken["items"][1]); child["id"] += "-duplicate"
        broken["items"].append(child); broken["items"][0]["partitioned_into"].append(child["id"])
        self.assertCode(rl.verify_pages(broken,[image]),"PARTITION_MISMATCH")

    def test_6_real_exporter_pdf_and_each_contract_violation(self):
        # Small synthetic content on the exporter's real A4/300 dpi canvases.
        pages = [paper(3508,2480),paper(3508,2480)]
        pages[0][24:27,24:27] = 0; pages[1][40:44,40:44] = 0
        out = export_composed_pages(pages=pages,formats=["pdf"],workspace=self.work/"export",logger=lambda _m:None)
        contract = rl.check_pdf_contract(out["pdf"])
        self.assertEqual(contract["status"],"pass",contract); self.assertEqual(len(contract["pages"]),2)
        ledger = control(pages[0]); other = inventory(snapshot(pages[1],display="second",occurrence="second",observations=[member(pages[1],"second-obs")]))
        place(other,page=1); merge_v2(ledger,other)
        report = lossless_legacy_verify_pdf(ledger,out["pdf"]); self.assertEqual(report["status"],"pass",report)
        self.assertEqual(len(report["embedded_pages"]),2)
        mutations = {
            "text":{"commands":b"q 595.2 0 0 841.92 0 0 cm /Im Do Q BT ET"},
            "clip":{"commands":b"q 0 0 10 10 re W n 595.2 0 0 841.92 0 0 cm /Im Do Q"},
            "clip_star":{"commands":b"q 0 0 10 10 re W* n 595.2 0 0 841.92 0 0 cm /Im Do Q"},
            "two_images":{"resources":b"<< /XObject << /Im 4 0 R /second 4 0 R >> >>"},
            "size":{"size":(500,800)},"rotate":{"page_extra":b" /Rotate 90"},
            "annots":{"page_extra":b" /Annots []"},"smask":{"image_extra":b" /SMask 4 0 R"},
            "mask":{"image_extra":b" /Mask []"},"decode":{"image_extra":b" /Decode [0 1]"},
            "crop":{"page_extra":b" /CropBox [0 0 500 800]"},"trim":{"page_extra":b" /TrimBox [0 0 500 800]"},
            "encoding":{"image_extra":b" /BitsPerComponent 4"},
            "colorspace":{"image_extra":b" /ColorSpace /Indexed"},
            "filter":{"image_extra":b" /Filter /DCTDecode"},
            "form":{"image_extra":b" /Subtype /Form"},
            "matrix":{"commands":b"q 595.22 0 0 841.92 0 0 cm /Im Do Q"}}
        path = self.work/"mutation.pdf"
        for name,kwargs in mutations.items():
            with self.subTest(name=name):
                hand_pdf(path,**kwargs)
                report = rl.check_pdf_contract(path); self.assertEqual(report["status"],"fail",report)
                self.assertCode(report,"PDF_CONTRACT_VIOLATION")
                with patch.object(rl,"extract_pdf_pages",side_effect=AssertionError("pixel extraction must not run")):
                    self.assertEqual(rl.verify_pdf({},path)["status"],"fail")
        for kwargs in ({"inherited":True,"compressed":True},{"page_extra":b" /CropBox [0 0 595.2 841.92] /TrimBox [0 0 595.2 841.92]"}):
            hand_pdf(path,**kwargs); self.assertEqual(rl.check_pdf_contract(path)["status"],"pass")

    def test_7_output_accounting_sums_and_reverse_issue(self):
        ledger = control(); out = dot(); template = paper(8,10); template[2:5,3:6] = 0
        out[43:51,60:70] = template
        ledger["generated_origins"] = [{"kind":"header","page_index":0,"origin":[60,43],"template":rl.pack_crop(template),"generator":"fixture","inputs":{"title":"T"}}]
        for stale in (False,True):
            image = out.copy()
            if stale: image[52:55,15:18] = 0
            report = rl.verify_pages(ledger,[image]); count = report["accounting"][0]
            self.assertEqual(count["foreground_px"],sum(count[k] for k in ("explained_by_source_px","explained_by_generated_px","unexplained_px")))
            self.assertGreater(count["explained_by_source_px"],0); self.assertGreater(count["explained_by_generated_px"],0)
            self.assertEqual(count["unexplained_px"],9 if stale else 0)
            self.assertEqual(report["status"],"fail" if stale else "pass")
            if stale: self.assertCode(report,"OUTPUT_FOREGROUND_WITHOUT_ORIGIN")

    def test_8_production_flags_cannot_change_control_or_dot_loss(self):
        ledger = control()
        for image,status in ((dot(),"pass"),(paper(),"fail")):
            reference = rl.verify_pages(ledger,[image]); self.assertEqual(reference["status"],status)
            for value in (False,True):
                mutated = copy.deepcopy(ledger)
                for record in [mutated,*mutated["items"]]:
                    record.update(exact_reconstruction=value,covered=value,clean_mask=[[value]],nonstaff_out=value)
                self.assertEqual(rl.verify_pages(mutated,[image]),reference)

    def test_9_generated_kinds_and_section_label_source(self):
        template = paper(8,10); template[2:5,3:6] = 0
        for kind in ("incomplete_marker","source_clipped_notice","possible_repeat_notice","number_step_notice","section_label"):
            with self.subTest(kind=kind):
                ledger = control(); out = dot(); out[43:51,60:70] = template
                origin = {"kind":kind,"page_index":0,"origin":[60,43],"template":rl.pack_crop(template),"generator":"fixture","inputs":{"source":{"observation_id":"obs-0","roi":[1,2,3,4]}}}
                ledger["generated_origins"] = [origin]
                report = rl.verify_pages(ledger,[out]); self.assertEqual(report["status"],"review_required" if kind=="section_label" else "pass",report)
                if kind=="section_label": self.assertCode(report,"SECTION_LABEL_SOURCE_UNLEDGERED")
                for key in ("generator","inputs"):
                    broken = copy.deepcopy(ledger); broken["generated_origins"][0].pop(key)
                    self.assertCode(rl.verify_pages(broken,[out]),"INVALID_GENERATED_ORIGIN")
                origin["origin"] = [23,23]
                self.assertCode(rl.verify_pages(ledger,[out]),"INVALID_GENERATED_ORIGIN")
                origin["origin"] = [-1,43]
                self.assertCode(rl.verify_pages(ledger,[out]),"INVALID_GENERATED_ORIGIN")
                origin["origin"] = [60,43]
                self.assertCode(rl.verify_pages(ledger,[dot()]),"INVALID_GENERATED_ORIGIN")
                if kind=="section_label":
                    origin["inputs"] = {"title":"A"}
                    self.assertCode(rl.verify_pages(ledger,[out]),"INVALID_GENERATED_ORIGIN")

    def test_fixture_size_and_runtime(self):
        fixtures = [control(),cursor_fixture()[0],equivalent_fixture()[0],partition_fixture()[0]]
        sizes = [len(json.dumps(f,separators=(",",":")).encode()) for f in fixtures]
        start = time.perf_counter()
        for _ in range(20): rl.verify_pages(fixtures[0],[dot()])
        print(f"W-A1 fixture compact JSON bytes={sizes}; dot verification mean_ms={(time.perf_counter()-start)*50:.3f}")


if __name__=="__main__":
    unittest.main()
