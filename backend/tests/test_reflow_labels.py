"""Section labels outside the score region (reflow_labels): suggestion, acquisition, placement."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_labels as rlab
from app.pipeline import reflow_pipeline

W, H = 960, 540
ROI = [[0, 380], [W, 380], [W, H], [0, H]]  # bottom score band
LABEL_AT = (90, 210)


def video_frame(t: float, label: str, seed: int) -> np.ndarray:
    """Dark 'drum video' with moving bright blobs, a constant logo and a section label."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 18, np.uint8)
    for _ in range(25):  # moving video content
        x, y = int(rng.integers(0, W)), int(rng.integers(0, 370))
        cv2.circle(img, (x, y), int(rng.integers(4, 30)), (int(rng.integers(60, 230)),) * 3, -1)
    cv2.putText(img, "DRUMMATE", (720, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (235, 235, 235), 2)  # logo: never changes
    if label:
        cv2.putText(img, label, LABEL_AT, cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 2)
    img[380:] = 245  # the score band itself (light), inside the ROI
    return img


def label_at(t: float) -> str:
    return "Intro" if t < 10 else "Verse 1" if t < 20 else "Chorus" if t < 30 else "Verse 2"


class LabelPatchTest(unittest.TestCase):
    def test_only_text_that_stays_in_every_sample_is_kept(self):
        crops = [video_frame(0, "Verse 1", seed)[150:250, 40:400] for seed in range(5)]
        found = rlab.label_patch(crops)
        self.assertIsNotNone(found)
        img = found["image"]
        ink = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 128
        self.assertGreater(int(ink.sum()), 300)  # the text strokes
        # nothing outside the text box: moving blobs did not survive
        self.assertLessEqual(img.shape[0], 60)
        self.assertFalse(found["light_text"] is False)

    def test_no_label_in_the_region_gives_none(self):
        crops = [video_frame(0, "", seed)[150:250, 40:400] for seed in range(5)]
        self.assertIsNone(rlab.label_patch(crops))


class SuggestLabelRegionTest(unittest.TestCase):
    def samples(self, label_fn):
        ts = np.linspace(1, 38, 24)
        return [(float(t), video_frame(t, label_fn(t), 100 + i), video_frame(t + 1.5, label_fn(t + 1.5), 500 + i)) for i, t in enumerate(ts)]

    def test_changing_label_is_suggested_and_the_constant_logo_is_not(self):
        out = rlab.suggest_label_region(self.samples(label_at), ROI)
        self.assertEqual(out["status"], "suggested", out)
        x0, y0 = out["label_roi"][0]
        x1, y1 = out["label_roi"][2]
        self.assertLessEqual(x0, LABEL_AT[0])
        self.assertGreaterEqual(x1, LABEL_AT[0] + 120)
        self.assertLessEqual(y0, LABEL_AT[1] - 20)
        self.assertGreaterEqual(y1, LABEL_AT[1])
        self.assertLess(x1, 700)  # the logo at x 720.. is not part of it
        self.assertLessEqual(y1, 380)  # never into the score region

    def test_only_constant_text_is_not_a_label(self):
        out = rlab.suggest_label_region(self.samples(lambda _t: ""), ROI)
        self.assertEqual(out["status"], "not_found")


class AcquireAndPlaceTest(unittest.TestCase):
    def test_labels_attach_to_their_occurrence_placed_at_section_starts(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            video = td / "v.avi"
            fps = 10
            vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, (W, H))
            self.assertTrue(vw.isOpened())
            for k in range(fps * 30):
                t = k / fps
                vw.write(video_frame(t, label_at(t), k))
            vw.release()
            obs, systems = [], []
            for si, (a, b) in enumerate([(1, 9), (11, 15), (16, 19), (21, 29)]):  # Intro | Verse 1 | Verse 1 | Chorus
                members = []
                for j, t in enumerate(np.linspace(a, b, 6)):
                    oid = f"o{si}-{j}"
                    obs.append({"id": oid, "t_sec": float(t)})
                    members.append({"obs_id": oid, "region_id": f"{oid}-r0"})
                systems.append({"id": f"sys-00{si + 1}", "observations": members})
            manifest = {"observations": obs, "source_to_crop": [1, 0, 0, 0, 1, -380, 0, 0, 1]}
            label_roi = [[40, 150], [400, 150], [400, 250], [40, 250]]
            out = rlab.acquire_labels(systems, manifest, video, label_roi, td / "labels")
            by = out["by_system"]
            self.assertEqual(sorted(by), ["sys-001", "sys-002", "sys-003", "sys-004"])
            self.assertEqual([by[s]["placed"] for s in sorted(by)], [True, True, False, True])
            self.assertEqual(by["sys-003"]["repeats_system_id"], "sys-002")
            self.assertTrue(Path(by["sys-001"]["path"]).is_file())
            bx = by["sys-002"]["bbox_source"]
            self.assertTrue(40 <= bx[0] <= LABEL_AT[0] and bx[3] <= 250)

            # placement: the label patch sits above its strip at the source scale
            strip = np.full((160, 900, 3), 250, np.uint8)
            for k in range(5):
                cv2.line(strip, (10, 50 + 14 * k), (890, 50 + 14 * k), (0, 0, 0), 1)
            strip_path = td / "strip.png"
            cv2.imwrite(str(strip_path), strip)
            lab = dict(by["sys-002"], x_in_strip=80)
            sysrec = {"id": "sys-002", "strip_path": str(strip_path), "strip": {"staff_gap_px": 14.0}, "label": lab}
            plan, pages = reflow_pipeline.compose_systems([sysrec])
            pl = plan["pages"][0]["placements"][0]
            self.assertIn("label_box_px", pl)
            lbx = pl["label_box_px"]
            self.assertEqual(lbx[0], 80)
            self.assertGreater(pl["strip_offset_px"][1], lbx[3])  # strip below the label
            sc = pl["scale"]
            page = pages[0]
            y0, y1 = pl["y"] + int(lbx[1] * sc), pl["y"] + int(lbx[3] * sc)
            x0, x1 = pl["x"] + int(lbx[0] * sc), pl["x"] + int(lbx[2] * sc) + 1
            self.assertGreater(int((page[y0:y1, x0:x1] < 128).sum()), 100)  # label ink on the page
            # a repeated label is kept on record but not placed again while its section start is placed
            sysrec3 = {"id": "sys-003", "strip_path": str(strip_path), "strip": {"staff_gap_px": 14.0}, "label": by["sys-003"]}
            plan23, _ = reflow_pipeline.compose_systems([sysrec, sysrec3])
            pls = {p_["system_id"]: p_ for pg in plan23["pages"] for p_ in pg["placements"]}
            self.assertIn("label_box_px", pls["sys-002"])
            self.assertNotIn("label_box_px", pls["sys-003"])
            # Audit round 2, P1: composing sys-003 alone (section start sys-002 excluded) silently
            # omitted its "Verse 1" label. The label now goes above the first placed system of its section.
            plan3, _ = reflow_pipeline.compose_systems([sysrec3], all_systems=[sysrec, sysrec3])
            pl3 = plan3["pages"][0]["placements"][0]
            self.assertIn("label_box_px", pl3)
            self.assertEqual(pl3["label_section"], "sys-002")
            self.assertEqual(plan3["dependencies"]["labels_moved"],
                             [{"section": "sys-002", "placed_on": "sys-003", "reason": "section_start_excluded"}])
            self.assertEqual(plan3["dependencies"]["labels_unplaced"], [])
            # a section with no placed system is reported, never dropped silently
            sysrec1 = {"id": "sys-001", "strip_path": str(strip_path), "strip": {"staff_gap_px": 14.0}, "label": by["sys-001"]}
            plan1, _ = reflow_pipeline.compose_systems([sysrec1], all_systems=[sysrec1, sysrec, sysrec3])
            self.assertEqual(plan1["dependencies"]["labels_unplaced"],
                             [{"section": "sys-002", "systems": ["sys-002", "sys-003"], "reason": "no_placed_system_of_this_section"}])


if __name__ == "__main__":
    unittest.main()
