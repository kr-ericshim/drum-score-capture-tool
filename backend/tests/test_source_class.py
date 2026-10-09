"""Source-class gate (STRATEGY Step 2A) on synthetic ROI frames."""

import unittest

import cv2
import numpy as np

from app.pipeline import source_class as sc

H, W = 200, 1200
GAP = 14
TOP = 70
X0, X1 = 40, 1160
MEASURES = 4


def _notation(seed: int) -> np.ndarray:
    """Ink coverage (0..1 float) of one drum system: five staff lines, barlines, noteheads,
    stems and beams. ``seed`` changes the notes (another page)."""
    rng = np.random.default_rng(seed)
    ink = np.zeros((H, W), np.float32)
    for k in range(5):
        y = TOP + k * GAP
        cv2.line(ink, (X0, y), (X1, y), 1.0, 2)
    mw = (X1 - X0) / MEASURES
    for m in range(MEASURES + 1):
        x = int(X0 + m * mw)
        cv2.line(ink, (x, TOP), (x, TOP + 4 * GAP), 1.0, 2)
    for m in range(MEASURES):
        xs = np.linspace(X0 + m * mw + 25, X0 + (m + 1) * mw - 25, 8)
        for x in xs:
            y = TOP + int(rng.integers(0, 9)) * GAP // 2
            cv2.ellipse(ink, (int(x), y), (6, 4), -20, 0, 360, 1.0, -1)
            cv2.line(ink, (int(x) + 5, y), (int(x) + 5, TOP - 2 * GAP), 1.0, 2)
        for b in range(2):
            cv2.line(ink, (int(xs[4 * b]) + 5, TOP - 2 * GAP), (int(xs[4 * b + 3]) + 5, TOP - 2 * GAP), 1.0, 5)
    return ink


def _compose(background: np.ndarray, ink: np.ndarray, ink_color) -> np.ndarray:
    bg = background.astype(np.float32)
    color = np.array(ink_color, np.float32).reshape(1, 1, 3)
    a = ink[..., None]
    return np.clip(bg * (1 - a) + color * a, 0, 255).astype(np.uint8)


def _flat(color) -> np.ndarray:
    return np.tile(np.array(color, np.uint8).reshape(1, 1, 3), (H, W, 1))


def _texture(t: int, lo: float, hi: float) -> np.ndarray:
    """Smooth random camera-like picture whose content moves with ``t``."""
    rng = np.random.default_rng(1000 + t)
    small = rng.random((12, 60, 3)).astype(np.float32)
    tex = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    xx = np.linspace(0, 6 * np.pi, W, dtype=np.float32)
    wave = 0.5 + 0.5 * np.sin(xx + 0.7 * t)[None, :, None]
    tex = np.clip(0.6 * tex + 0.4 * wave, 0, 1)
    return (lo + (hi - lo) * tex).astype(np.uint8)


def _frames(make, n: int = 12):
    return [make(i) for i in range(n)]


class SourceClassTest(unittest.TestCase):
    def assertClass(self, frames, expected):
        result = sc.classify_frames(frames)
        self.assertEqual(result["version"], sc.VERSION)
        self.assertEqual(result["class"], expected, {k: v for k, v in result["evidence"].items() if k != "per_frame"})
        return result

    def test_light_paper(self):
        frames = _frames(lambda i: _compose(_flat((250, 250, 250)), _notation(i // 3), (25, 25, 25)))
        r = self.assertClass(frames, sc.CLASS_LIGHT_PAPER)
        ev = r["evidence"]
        self.assertEqual(ev["score_frames"], 12)
        self.assertEqual(ev["live_frames"], 0)
        self.assertEqual(ev["light_ink_frac"], 0.0)
        self.assertEqual(len(ev["per_frame"]), 12)

    def test_dark_paper(self):
        frames = _frames(lambda i: _compose(_flat((12, 12, 12)), _notation(i // 3), (245, 245, 245)))
        r = self.assertClass(frames, sc.CLASS_DARK_PAPER)
        self.assertEqual(r["evidence"]["light_ink_frac"], 1.0)

    def test_dark_plate_with_dim_video_behind_stays_dark_paper(self):
        # a dark semi-opaque plate: the video shows through dimly and moves (bF69-like)
        frames = _frames(lambda i: _compose(_texture(i, 5, 40), _notation(i // 3), (250, 250, 250)))
        self.assertClass(frames, sc.CLASS_DARK_PAPER)

    def test_light_notation_over_moving_video_is_refused(self):
        def make(i):
            frame = _compose(_texture(i, 10, 245), _notation(i // 4), (255, 255, 255))
            return frame
        r = self.assertClass(_frames(make), sc.CLASS_LIVE)
        ev = r["evidence"]
        self.assertGreaterEqual(ev["live_frame_frac"], sc.LIVE_FRAME_FRAC)
        self.assertIn("reason", ev)

    def test_dark_notation_over_moving_video_is_refused(self):
        frames = _frames(lambda i: _compose(_texture(i, 30, 250), _notation(i // 4), (0, 0, 0)))
        self.assertClass(frames, sc.CLASS_LIVE)

    def test_paper_with_moving_cursor_and_highlight_band_stays_paper(self):
        mw = (X1 - X0) / MEASURES

        def make(i):
            frame = _compose(_flat((250, 250, 250)), _notation(i // 4), (25, 25, 25))
            # translucent highlight over one beat, moving with playback
            x = int(X0 + 20 + (i % 8) * mw / 2)
            band = frame[TOP - 10: TOP + 4 * GAP + 10, x: x + 40].astype(np.float32)
            frame[TOP - 10: TOP + 4 * GAP + 10, x: x + 40] = (0.6 * band + 0.4 * np.array([240, 200, 140])).astype(np.uint8)
            # thin player cursor line with a marker
            cx = int(X0 + 60 + i * 80)
            cv2.line(frame, (cx, TOP - 30), (cx, TOP + 4 * GAP + 30), (80, 60, 230), 2)
            cv2.circle(frame, (cx, TOP - 30), 6, (80, 60, 230), -1)
            return frame
        self.assertClass(_frames(make), sc.CLASS_LIGHT_PAPER)

    def test_paper_with_measure_wide_colored_band_stays_paper(self):
        mw = (X1 - X0) / MEASURES

        def make(i):
            frame = _compose(_flat((250, 250, 250)), _notation(i // 4), (25, 25, 25))
            x = int(X0 + (i % MEASURES) * mw)
            region = frame[TOP - 20: TOP + 4 * GAP + 20, x: int(x + mw)].astype(np.float32)
            # a saturated band: multiply blend, notes stay dark
            frame[TOP - 20: TOP + 4 * GAP + 20, x: int(x + mw)] = (region * np.array([1.0, 0.75, 0.45])).astype(np.uint8)
            return frame
        self.assertClass(_frames(make), sc.CLASS_LIGHT_PAPER)

    def test_frames_without_staves_do_not_decide(self):
        frames = _frames(lambda i: _texture(i, 0, 255))
        r = self.assertClass(frames, sc.CLASS_UNKNOWN)
        self.assertEqual(r["evidence"]["score_frames"], 0)

    def test_intro_without_score_does_not_vote(self):
        # live-video intro (no staves) then an opaque page: still paper
        frames = [_texture(i, 0, 255) for i in range(6)]
        frames += [_compose(_flat((250, 250, 250)), _notation(i), (25, 25, 25)) for i in range(10)]
        r = self.assertClass(frames, sc.CLASS_LIGHT_PAPER)
        self.assertEqual(r["evidence"]["score_frames"], 10)

    def test_gray_frames_and_wide_frames(self):
        gray = [cv2.cvtColor(_compose(_flat((250, 250, 250)), _notation(i), (25, 25, 25)), cv2.COLOR_BGR2GRAY)
                for i in range(6)]
        self.assertClass(gray, sc.CLASS_LIGHT_PAPER)
        wide = [cv2.resize(f, (W * 2, H * 2), interpolation=cv2.INTER_LINEAR) for f in gray]
        self.assertClass(wide, sc.CLASS_LIGHT_PAPER)

    def test_evidence_is_json_safe(self):
        import json

        frames = _frames(lambda i: _compose(_texture(i, 10, 245), _notation(i), (255, 255, 255)), n=5)
        json.dumps(sc.classify_frames(frames, times=[float(i) for i in range(5)]))


class SourceClassVideoTest(unittest.TestCase):
    """classify_source on a real (small, temporary) video file and the analyse_source hook."""

    def _write_video(self, path, make, n=30, fps=10.0):
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H + 100))
        if not writer.isOpened():
            self.skipTest("no mp4v encoder")
        for i in range(n):
            frame = np.full((H + 100, W, 3), 90, np.uint8)  # picture above the score band
            frame[100:] = make(i)
            writer.write(frame)
        writer.release()

    def test_classify_source_on_video_file(self):
        import tempfile
        from pathlib import Path

        roi = [[0, 100], [W, 100], [W, H + 100], [0, H + 100]]
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.mp4"
            self._write_video(live, lambda i: _compose(_texture(i, 10, 245), _notation(i // 10), (255, 255, 255)))
            r = sc.classify_source(live, roi, 0.0, None, samples=8)
            self.assertEqual(r["class"], sc.CLASS_LIVE, r["evidence"].get("reason"))
            self.assertEqual(r["evidence"]["frames"], 8)
            paper = Path(tmp) / "paper.mp4"
            self._write_video(paper, lambda i: _compose(_flat((250, 250, 250)), _notation(i // 10), (25, 25, 25)))
            r = sc.classify_source(paper, roi, 0.0, 100.0, samples=8)  # end past the video is clamped
            self.assertEqual(r["class"], sc.CLASS_LIGHT_PAPER, r["evidence"].get("reason"))
            self.assertEqual(r["evidence"]["frames"], 8)

    def test_analyse_source_refuses_live_source_before_sampling(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from app.pipeline import observations as ob
        from app.pipeline import reflow_pipeline as rp

        verdict = {"class": sc.CLASS_LIVE, "evidence": {"reason": "test"}, "version": sc.VERSION}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sc, "classify_source", return_value=verdict), \
                mock.patch.object(ob, "build_manifest", side_effect=AssertionError("must not sample")):
            with self.assertRaises(rp.UnsupportedSourceError) as ctx:
                rp.analyse_source(video_path=Path(tmp) / "v.mp4", roi=[[0, 0], [10, 0], [10, 10], [0, 10]],
                                  workspace=Path(tmp) / "ws")
            self.assertEqual(ctx.exception.code, "UNSUPPORTED_SOURCE")
            self.assertEqual(ctx.exception.source_class["class"], sc.CLASS_LIVE)
            self.assertTrue((Path(tmp) / "ws" / "source_class.json").is_file())

    def test_analyse_source_continues_when_gate_accepts_or_fails(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from app.pipeline import observations as ob
        from app.pipeline import reflow_pipeline as rp

        class Reached(Exception):
            pass

        paper = {"class": sc.CLASS_LIGHT_PAPER, "evidence": {"reason": "test"}, "version": sc.VERSION}
        for patch in (mock.patch.object(sc, "classify_source", return_value=paper),
                      mock.patch.object(sc, "classify_source", side_effect=RuntimeError("cannot open video"))):
            with tempfile.TemporaryDirectory() as tmp, patch, \
                    mock.patch.object(ob, "build_manifest", side_effect=Reached()):
                with self.assertRaises(Reached):
                    rp.analyse_source(video_path=Path(tmp) / "v.mp4", roi=[[0, 0], [10, 0], [10, 10], [0, 10]],
                                      workspace=Path(tmp) / "ws")


if __name__ == "__main__":
    unittest.main()
