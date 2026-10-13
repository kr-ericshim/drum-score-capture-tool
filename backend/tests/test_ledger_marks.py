"""Clear-mark delivery controls, independent of production cleanup masks."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_ledger as rl


def source():
    image = np.full((92,200,3),255,np.uint8)
    for y in (25,35,45,55,65): image[y:y+1,15:185] = 0
    image[38:42,80:85] = 0
    image[31:40,83:85] = 0
    image[48:50,108:110] = 0
    return image


def ledger(image, observations=None):
    observations = observations or [image,image,image]
    members = [dict(id=f"obs-{i}",timestamp=float(i),image=im,roi_origin=[0,0],
        registration_shift=[0,0],registration_uncertainty=0.) for i,im in enumerate(observations)]
    value = rl.record_obligations(source_video="marks.mp4",display_id="strip:s",occurrence_id="occ",members=members)
    value["observations"] = [dict(id=m["id"],t_sec=m["timestamp"],pixels_sha256=rl.pixels_hash(m["image"]),
        staff_regions=1,frame_path="",associations=[dict(stage="composition",display_id="strip:s",occurrence_id="occ",role="used")],terminal="preserved") for m in members]
    return value


def place(value,scale=1.):
    stages = [dict(stage=s,kind="affine",matrix=np.eye(3).tolist()) for s in rl.STAGES]
    stages[2]["matrix"] = [[scale,0,20+(scale-1)/2],[0,scale,20+(scale-1)/2],[0,0,1]]
    for item in value["items"]:
        value["representations"].append(dict(item_id=item["id"],occurrence_id="occ",copy_index=0,page_index=0,line_id="line",transforms=copy.deepcopy(stages)))


def page(image,scale=1.,offset=0):
    canvas = np.full((180,280,3),255,np.uint8)
    if scale!=1.: image = cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    h,w = image.shape[:2]
    canvas[20+offset:20+offset+h,20+offset:20+offset+w] = image
    return canvas


class MarkTests(unittest.TestCase):
    def codes(self,report): return {i["code"] for i in report["issues"]}

    def test_clean_marks_and_jpeg75_pass(self):
        image = source(); value = ledger(image); place(value)
        delivered = page(image)
        self.assertEqual(rl.verify_pages(value,[delivered])["status"],"pass")
        encoded = cv2.imencode(".jpg",delivered,[cv2.IMWRITE_JPEG_QUALITY,75])[1]
        report = rl.verify_pages(value,[cv2.imdecode(encoded,cv2.IMREAD_COLOR)])
        self.assertEqual(report["status"],"pass",report["issues"])

    def test_erased_dot_fails(self):
        image = source(); value = ledger(image); place(value)
        image[48:50,108:110] = 255
        self.assertIn("SOURCE_FOREGROUND_MISSING_OR_CHANGED",self.codes(rl.verify_pages(value,[page(image)])))

    def test_moved_note_one_staff_space_fails(self):
        image = source(); value = ledger(image); place(value)
        image[38:42,80:85] = 255; image[31:40,83:85] = 255
        image[48:52,80:85] = 0; image[41:50,83:85] = 0
        self.assertEqual(rl.verify_pages(value,[page(image)])["status"],"fail")

    def test_added_two_by_two_dot_fails(self):
        image = source(); value = ledger(image); place(value)
        image[74:76,160:162] = 0
        self.assertIn("OUTPUT_FOREGROUND_WITHOUT_ORIGIN",self.codes(rl.verify_pages(value,[page(image)])))

    def test_placement_two_pixels_fails_one_passes(self):
        image = source(); value = ledger(image); place(value)
        self.assertEqual(rl.verify_pages(value,[page(image,offset=1)])["status"],"pass")
        report = rl.verify_pages(value,[page(image,offset=2)])
        self.assertIn("PLACEMENT_MISMATCH",self.codes(report))
        self.assertTrue(all(i["offset"]==[2,2] for i in report["issues"] if i["code"]=="PLACEMENT_MISMATCH"))

    def test_area_shrink_to_1_2_mm_passes(self):
        image = source(); value = ledger(image); place(value,.75)
        for rep in value["representations"]:
            rep["transforms"][2]["resample"] = {"source_size":[200,92],"output_size":[150,69],"interpolation":"area"}
        report = rl.verify_pages(value,[page(image,.75)])
        self.assertEqual(report["status"],"pass",report["issues"])

    def test_faint_only_has_no_obligation(self):
        image = np.full((40,60,3),255,np.uint8); image[20:22,20:22] = 210
        value = ledger(image); place(value)
        report = rl.verify_pages(value,[page(np.full_like(image,255))])
        self.assertEqual(report["status"],"pass",report)
        self.assertTrue(all(m["kind"]=="faint_only" for m in report["matches"]))

    def test_two_of_three_support_and_one_is_minority(self):
        image = np.full((40,60,3),255,np.uint8); image[20:22,20:22] = 0
        blank = np.full_like(image,255)
        value = ledger(image,[image,image,blank]); place(value)
        self.assertEqual(rl.verify_pages(value,[page(image)])["status"],"pass")
        q = rl.qualify_marks(ledger(image,[image,blank,blank]))
        self.assertTrue(all(m["minority"] for v in q.values() for m in v["marks"]))

    def test_inventory_histogram_and_compact_marks(self):
        image = source(); started = time.perf_counter(); value = ledger(image)
        size = len(json.dumps(value,separators=(",",":")).encode())
        self.assertTrue(all("core" in mark for item in value["items"] for mark in item["marks"]))
        print(f"MARK_BENCH items={len(value['items'])} json_bytes={size} seconds={time.perf_counter()-started:.4f}")

    def test_failed_cleanup_retains_ledger_frames(self):
        from app import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); work = root/"reflow"; frames = work/"manifest"/"frames"; frames.mkdir(parents=True)
            evidence = work/"ledger_evidence"; evidence.mkdir()
            im = source(); frame = frames/"kept.png"; cv2.imwrite(str(frame),im)
            cv2.imwrite(str(evidence/"mask.png"),im)
            cv2.imwrite(str(frames/"unused.png"),im)
            (work/"ledger_base.json").write_text(json.dumps({"observations":[{"frame_path":str(frame)}]}))
            main.prune_job_workspace(root,keep_review=True,keep_ledger=True)
            self.assertTrue(frame.exists()); self.assertTrue((evidence/"mask.png").exists())
            self.assertFalse((frames/"unused.png").exists())


if __name__=="__main__": unittest.main()
