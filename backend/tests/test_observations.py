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

    def test_handed_over_compare_work_gives_the_same_verdicts(self):
        # build_manifest hands each crop's compare_frames work to the next comparison (cur_cache ->
        # prev_cache); every verdict equals a comparison without caches, also across a different
        # staff size, a blank crop and a dark crop
        from app.pipeline import page_diff
        from app.pipeline.system_detect import normalize_polarity

        spec = groove_notes(strip_spec(height=170), seed=3)
        other = groove_notes(strip_spec(height=170, gap=10), seed=5)
        crops = [render(spec, [Overlay("line", position=p)]) for p in (0.2, 0.4, 0.6)]
        crops += [render(other, []), render(other, [Overlay("line", position=0.5)]),
                  np.full_like(crops[0], 255), render(spec, []), 255 - render(spec, []), render(spec, [])]
        norms = [normalize_polarity(c)[0] for c in crops]
        prev_cache = {}
        for a, b in zip(norms, norms[1:]):
            cur_cache = {}
            chained = page_diff.compare_frames(a, b, prev_cache=prev_cache, cur_cache=cur_cache)
            self.assertEqual(chained.to_dict(), page_diff.compare_frames(a, b).to_dict())
            prev_cache = cur_cache

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


class DecodeCompletenessTest(unittest.TestCase):
    """A decoder that stops early must not yield a manifest that claims the whole video (audit F08)."""

    ROI = [[0, 0], [1400, 0], [1400, 190], [0, 190]]

    def _manifest(self, decodable_frames: int = 0, metadata_frames: int = 180, *, pts=None, seek_pts=None,
                  fps: float = 30.0, metadata_fps=None):
        """A capture delivering ``pts`` (default: ``decodable_frames`` frames at ``fps``) in a sequential
        decode, and ``seek_pts`` (default: the ``metadata_frames`` the container claims, i.e. the stream
        really continues) after a seek, in a container claiming ``metadata_frames`` at ``metadata_fps``."""
        from unittest.mock import patch

        img = render(strip_spec())
        step = fps if fps > 0 else 30.0
        seq = list(pts) if pts is not None else [i / step for i in range(decodable_frames)]
        after_seek = list(seek_pts) if seek_pts is not None else [i / step for i in range(metadata_frames)]
        seeks = []

        class Capture:
            def __init__(self, *_args):
                self.i = -1
                self.frames = seq

            def isOpened(self):
                return True

            def set(self, key, value):
                assert key == cv2.CAP_PROP_POS_MSEC
                seeks.append(value / 1000.0)
                self.frames = after_seek
                self.i = sum(1 for t in after_seek if t < value / 1000.0 - 1e-9) - 1

            def grab(self):
                self.i += 1
                return self.i < len(self.frames)

            def retrieve(self):
                return True, img

            def get(self, key):
                if key == cv2.CAP_PROP_FPS:
                    return fps
                if key == cv2.CAP_PROP_POS_MSEC:
                    return self.frames[min(self.i, len(self.frames) - 1)] * 1000.0 if self.frames else 0.0
                return 0

            def release(self):
                pass

        mfps = fps if metadata_fps is None else metadata_fps
        info = ob.VideoInfo("memory", mfps, metadata_frames, 1400, 190, metadata_frames / mfps if mfps > 0 else 0.0)
        self.seeks = seeks
        with patch.object(ob, "probe_video", return_value=info), patch.object(ob.cv2, "VideoCapture", Capture), \
                patch.object(ob, "file_sha256", return_value="0" * 64):
            return ob.build_manifest(video_path=Path("/tmp/in_memory_not_a_video"), roi=self.ROI,
                                     store_frames=False, work_scale=1.0)

    def test_early_end_of_decode_stops_the_job(self):
        with self.assertRaises(ob.VideoDecodeIncompleteError) as ctx:
            self._manifest(45)  # 1.5 s of a 6 s video
        self.assertEqual(ctx.exception.code, "VIDEO_DECODE_INCOMPLETE")
        self.assertEqual(ctx.exception.decoded_until, round(44 / 30, 6))  # the last frame the decoder delivered

    def test_no_decodable_frame_stops_the_job(self):
        with self.assertRaises(ob.VideoDecodeIncompleteError):
            self._manifest(0)

    def test_a_few_missing_tail_frames_are_tolerated(self):
        # container frame counts often overshoot by a few frames
        m = self._manifest(175)
        self.assertEqual(m["sampling"]["sampled_until_sec"], round(175 / 30, 4))  # the real reach, not 6.0
        self.assertEqual(ob.validate_manifest(m), [])

    def test_decoder_stopping_after_the_last_grid_target_tolerance_stops_the_job(self):
        # 139 of 180 frames (last at 4.6 s): the 5.5 s grid point is within 1 s of the last served
        # sample, but the requested final frame (5.967 s) is 1.37 s past the decoder's reach
        with self.assertRaises(ob.VideoDecodeIncompleteError) as ctx:
            self._manifest(139)
        self.assertEqual(ctx.exception.decoded_until, round(138 / 30, 6))

    def test_whole_video_decoded_records_the_container_end(self):
        m = self._manifest(180)
        self.assertEqual(m["sampling"]["sampled_until_sec"], 6.0)
        self.assertEqual(ob.validate_manifest(m), [])

    def test_early_end_confirmed_by_seek_keeps_the_decoded_video(self):
        # 139 of 180 frames sequentially, and seeking past 4.6 s decodes nothing later: the stream
        # really ends at 4.6 s (e.g. a container claiming more than it holds)
        m = self._manifest(139, seek_pts=[i / 30.0 for i in range(139)])
        self.assertEqual(m["sampling"]["sampled_until_sec"], round(139 / 30, 4))  # the real reach
        note = m["sampling"]["decode_end_confirmed_by_seek"]
        self.assertEqual(note["stream_end_sec"], round(138 / 30, 6))
        self.assertEqual(len(note["probe_sec"]), 2)
        self.assertTrue(all(138 / 30 < t < 5.967 for t in note["probe_sec"]))
        self.assertEqual(len(self.seeks), 2)
        self.assertEqual(max(o["t_sec"] for o in m["observations"]), 4.5)  # nothing invented past the reach
        self.assertEqual(ob.validate_manifest(m), [])

    def test_early_end_with_later_frames_after_a_seek_stops_the_job(self):
        with self.assertRaises(ob.VideoDecodeIncompleteError):
            self._manifest(139)  # the seek decodes frames up to 5.967 s
        self.assertEqual(len(self.seeks), 1)  # the first probe already finds a later frame

    def test_vfr_recording_holding_its_last_frame_passes(self):
        # frames every 1/30 s up to 4.0 s, the last one held 2 s; the container says 6 s
        # (121 frames at an average 20.17 fps)
        pts = [i / 30.0 for i in range(121)]
        m = self._manifest(metadata_frames=121, pts=pts, seek_pts=pts, fps=121 / 6.0)
        self.assertEqual(m["sampling"]["decode_end_confirmed_by_seek"]["stream_end_sec"], 4.0)
        self.assertAlmostEqual(m["sampling"]["sampled_until_sec"], 4.0 + 6.0 / 121, places=3)
        self.assertEqual(max(o["t_sec"] for o in m["observations"]), 4.0)

    def test_container_longer_than_the_video_stream_passes(self):
        # MKV/WebM: the frame count comes from a 7.5 s container (longer audio); video ends at 5.97 s
        pts = [i / 30.0 for i in range(180)]
        m = self._manifest(metadata_frames=225, pts=pts, seek_pts=pts)
        self.assertEqual(m["sampling"]["sampled_until_sec"], 6.0)
        self.assertEqual(m["sampling"]["decode_end_confirmed_by_seek"]["stream_end_sec"], round(179 / 30, 6))
        self.assertEqual(ob.validate_manifest(m), [])

    def test_small_overshoot_and_whole_video_need_no_seek(self):
        for decodable, metadata in ((180, 185), (180, 180), (175, 180)):
            with self.subTest(decodable=decodable, metadata=metadata):
                m = self._manifest(decodable, metadata)
                self.assertEqual(self.seeks, [])
                self.assertNotIn("decode_end_confirmed_by_seek", m["sampling"])
                self.assertEqual(m["sampling"]["sampled_until_sec"], round(decodable / 30, 4))

    def test_zero_fps_container_is_unchanged(self):
        m = self._manifest(90, 0, fps=0.0)
        self.assertEqual(self.seeks, [])
        self.assertEqual(m["sampling"]["sampled_until_sec"], 0.0)
        self.assertEqual(len(m["observations"]), 1)
