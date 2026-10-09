"""Observation manifest: exact source timestamps, ROI provenance, regions."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import observations as ob
from drum_score_fixture import Overlay, groove_notes, render, strip_spec


FPS = 10.0


def _write_video(path: Path, segments, *, fps: float = FPS, size=(1400, 300), top=80):
    """segments: list of (spec, seconds). The strip is pasted at y=top of a gray frame."""
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    if not writer.isOpened():
        raise unittest.SkipTest("no video writer available")
    index = 0
    for spec, seconds in segments:
        n = int(round(seconds * fps))
        for k in range(n):
            frame = np.full((h, w, 3), 90, np.uint8)
            strip = render(spec, [Overlay("line", position=(k + 0.5) / n, color=(220, 120, 40))])
            frame[top : top + strip.shape[0], : strip.shape[1]] = strip
            # frame index burned in outside the ROI
            cv2.putText(frame, str(index), (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            writer.write(frame)
            index += 1
    writer.release()
    return index


class RoiGeometryTest(unittest.TestCase):
    def test_rectangle_roi_is_translation_matching_rectify(self):
        roi = [[10.4, 20.2], [500.0, 20.2], [500.0, 220.9], [10.4, 220.9]]
        m, box = ob.roi_source_to_crop(roi)
        self.assertEqual(box, (11, 21, 500, 220))
        self.assertEqual(m[:6], [1.0, 0.0, -11.0, 0.0, 1.0, -21.0])
        frame = np.zeros((300, 600, 3), np.uint8)
        frame[21, 11] = 255
        crop = ob.crop_roi(frame, roi)
        self.assertEqual(crop.shape[:2], (199, 489))
        self.assertEqual(int(crop[0, 0, 0]), 255)
        self.assertEqual(ob.crop_box_to_source(m, [0, 0, 10, 10]), [11.0, 21.0, 21.0, 31.0])

    def test_quad_roi_is_perspective(self):
        roi = [[10, 10], [400, 20], [390, 200], [5, 190]]
        m, box = ob.roi_source_to_crop(roi)
        self.assertNotEqual(m[6:8], [0.0, 0.0])
        x, y = ob.crop_to_source_point(m, 0, 0)
        self.assertAlmostEqual(x, 10, delta=0.5)
        self.assertAlmostEqual(y, 10, delta=0.5)


class ManifestBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.video = root / "clip.avi"
        a = groove_notes(strip_spec(height=170), seed=1)
        b = groove_notes(strip_spec(height=170), seed=2)
        cls.frames = _write_video(cls.video, [(a, 3.0), (b, 3.0)])
        cls.roi = [[0, 80], [1400, 80], [1400, 250], [0, 250]]
        cls.out = root / "m"
        cls.manifest = ob.build_manifest(video_path=cls.video, roi=cls.roi, out_dir=cls.out, video_id="clip")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_schema_and_validation(self):
        m = self.manifest
        self.assertEqual(m["schema_version"], ob.SCHEMA_VERSION)
        self.assertEqual(ob.validate_manifest(m), [])
        self.assertEqual(len(m["source"]["sha256"]), 64)
        path = self.out / "clip.json"
        ob.write_manifest(m, path)
        self.assertEqual(ob.load_manifest(path)["video_id"], "clip")
        bad = dict(m, schema_version=99)
        self.assertTrue(ob.validate_manifest(bad))

    def test_timestamps_are_frame_pts(self):
        obs = self.manifest["observations"]
        ts = [o["t_sec"] for o in obs]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(len(set(ts)), len(ts))
        for o in obs:
            # every timestamp is an exact frame time k / fps
            k = o["t_sec"] * FPS
            self.assertAlmostEqual(k, round(k), places=3)
            self.assertEqual(o["time_basis"], "source_pts")
            self.assertTrue((self.out / o["frame_path"]).exists())

    def test_frame_content_matches_timestamp(self):
        # The stored crop of the observation at t=4.0 is the second strip (b).
        obs = {o["t_sec"]: o for o in self.manifest["observations"]}
        img_early = ob.load_observation_image(self.out, obs[1.0])
        img_late = ob.load_observation_image(self.out, obs[4.0])
        self.assertGreater(float(np.abs(img_early.astype(int) - img_late.astype(int)).mean()), 1.0)
        redecoded = ob.load_observation_image(self.out, dict(obs[4.0], frame_path=None), self.manifest)
        self.assertLess(float(np.abs(redecoded.astype(int) - img_late.astype(int)).mean()), 0.5)

    def test_fine_samples_around_change(self):
        m = self.manifest
        self.assertTrue(any(abs(c["t_prev"] - 2.5) < 1e-6 and abs(c["t_next"] - 3.0) < 1e-6 for c in m["acquisition_changes"]),
                        m["acquisition_changes"])
        fine = [o["t_sec"] for o in m["observations"] if o["sample_kind"] == "fine"]
        self.assertTrue(fine)
        self.assertTrue(all(1.7 <= t <= 3.8 for t in fine), fine)
        coarse = [o["t_sec"] for o in m["observations"] if o["sample_kind"] == "coarse"]
        self.assertEqual(coarse[:4], [0.0, 0.5, 1.0, 1.5])

    def test_regions_slots_roles_playhead(self):
        m = self.manifest
        self.assertEqual(len(m["slots"]), 1)
        for o in m["observations"]:
            self.assertEqual(len(o["system_regions"]), 1)
            r = o["system_regions"][0]
            self.assertEqual(r["slot_id"], "slot-00")
            self.assertEqual(r["role"], "active")
            self.assertAlmostEqual(r["staff_gap_px"], 14, delta=1.0)
            self.assertEqual(r["region_id"], o["id"] + "-r0")
            self.assertIsNotNone(r["playhead_x"])
        # playhead moves right within the first strip
        first = [o["system_regions"][0]["playhead_x"] for o in m["observations"] if o["t_sec"] < 2.4]
        self.assertGreater(first[-1], first[0])


class WorkScaleTest(unittest.TestCase):
    """A source with staves much larger than the page needs (4K) is analysed at a reduced size;
    source_to_crop carries the scale so every record maps back to source pixels."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.video = root / "big.avi"
        k = 2.5
        strip = cv2.resize(render(groove_notes(strip_spec(height=170), seed=1)), None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        w, h = strip.shape[1], strip.shape[0] + 300
        writer = cv2.VideoWriter(str(cls.video), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (w, h))
        if not writer.isOpened():
            raise unittest.SkipTest("no video writer available")
        for _ in range(int(2 * FPS)):
            frame = np.full((h, w, 3), 90, np.uint8)
            frame[200:200 + strip.shape[0]] = strip
            writer.write(frame)
        writer.release()
        cls.roi = [[0, 200], [w, 200], [w, 200 + strip.shape[0]], [0, 200 + strip.shape[0]]]
        cls.out = root / "m"
        cls.manifest = ob.build_manifest(video_path=cls.video, roi=cls.roi, out_dir=cls.out, video_id="big")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_scaled_crops_and_mapping(self):
        m = self.manifest
        ws = m["work_scale"]
        self.assertGreater(ws["probe_gap_px"], ob.WORK_SCALE_TRIGGER_GAP_PX)
        self.assertLess(ws["scale"], 0.7)
        native, work = ws["native_crop_size"], ws["crop_size"]
        self.assertEqual(native, [self.roi[1][0], self.roi[2][1] - self.roi[0][1]])
        self.assertEqual(work, list(ob.scaled_size(tuple(native), ws["scale"])))
        for o in m["observations"]:
            self.assertEqual(o["crop_size"], work)
            for r in o["system_regions"]:
                self.assertAlmostEqual(r["staff_gap_px"], ob.WORK_GAP_PX, delta=1.5)
        # crop pixel centres map back to source pixel centres
        s2c = m["source_to_crop"]
        x, y = ob.crop_to_source_point(s2c, -0.5, -0.5)
        self.assertAlmostEqual(x, self.roi[0][0] - 0.5, places=6)
        self.assertAlmostEqual(y, self.roi[0][1] - 0.5, places=6)
        x, y = ob.crop_to_source_point(s2c, work[0] - 0.5, work[1] - 0.5)
        self.assertAlmostEqual(x, self.roi[1][0] - 0.5, places=6)
        self.assertAlmostEqual(y, self.roi[2][1] - 0.5, places=6)
        x, y = ob.source_to_crop_point(s2c, *ob.crop_to_source_point(s2c, 123.0, 45.0))
        self.assertAlmostEqual(x, 123.0, places=6)
        self.assertAlmostEqual(y, 45.0, places=6)

    def test_redecoded_observation_has_the_work_size(self):
        o = self.manifest["observations"][3]
        stored = ob.load_observation_image(self.out, o)
        self.assertEqual([stored.shape[1], stored.shape[0]], o["crop_size"])
        redecoded = ob.load_observation_image(self.out, dict(o, frame_path=None), self.manifest)
        self.assertEqual(redecoded.shape, stored.shape)
        self.assertLess(float(np.abs(redecoded.astype(int) - stored.astype(int)).mean()), 0.5)

    def test_native_sizes_are_not_scaled(self):
        # the ManifestBuildTest clip (staff space 14 px) and an explicit scale of 1 stay native
        m = ob.build_manifest(video_path=self.video, roi=self.roi, out_dir=None, video_id="big", work_scale=1.0,
                              max_duration=0.6)
        self.assertEqual(m["work_scale"]["crop_size"], m["work_scale"]["native_crop_size"])
        self.assertEqual(m["source_to_crop"][:6], [1.0, 0.0, 0.0, 0.0, 1.0, -200.0])


class ChangeDetectionTest(unittest.TestCase):
    def test_dark_theme_pair_compares_same(self):
        spec = groove_notes(strip_spec(height=170), seed=3)
        a = 255 - render(spec, [Overlay("line", position=0.3)])
        b = 255 - render(spec, [Overlay("line", position=0.6)])
        v = ob.compare_crops(a, b)
        self.assertFalse(ob.is_apparent_change(v), (v.verdict, v.reason))

    def test_small_change_is_not_resampled(self):
        from app.pipeline.page_diff import FrameDiffVerdict

        self.assertFalse(ob.is_apparent_change(FrameDiffVerdict("ambiguous", "small_change")))
        self.assertTrue(ob.is_apparent_change(FrameDiffVerdict("ambiguous", "playhead_reset")))
        self.assertTrue(ob.is_apparent_change(FrameDiffVerdict("different", "note_sized_change")))
        self.assertFalse(ob.is_apparent_change(FrameDiffVerdict("same", "no_note_change")))


class RoleAssignmentTest(unittest.TestCase):
    def test_two_rows_active_and_preview(self):
        o = {"system_regions": [{"playhead_x": 0.4}, {"playhead_x": None}]}
        ob.assign_roles(o)
        self.assertEqual([r["role"] for r in o["system_regions"]], ["active", "preview"])

    def test_page_rows_visible_and_unknown(self):
        o = {"system_regions": [{"playhead_x": None}, {"playhead_x": 0.2}, {"playhead_x": None}]}
        ob.assign_roles(o)
        self.assertEqual([r["role"] for r in o["system_regions"]], ["visible", "active", "visible"])
        o = {"system_regions": [{"playhead_x": None}, {"playhead_x": None}]}
        ob.assign_roles(o)
        self.assertEqual([r["role"] for r in o["system_regions"]], ["unknown", "unknown"])


if __name__ == "__main__":
    unittest.main()
