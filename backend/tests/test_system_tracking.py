"""Display-episode tracking on synthetic manifests."""

import unittest

import numpy as np

from app.pipeline import system_tracking as st
from reflow_fixture import STEP, build, frame, loader, page, show, strip


def track(frames):
    manifest, images = build(frames)
    return st.build_episodes(manifest, loader(images)), manifest


class BottomBarEpisodesTest(unittest.TestCase):
    def test_changes_split_episodes_and_flags(self):
        a, b, c = strip(1), strip(2), strip(3)
        frames = show(a, 0.0, 3.0, seed=1) + show(b, 3.0, 3.0, seed=2) + show(c, 6.0, 0.5, seed=3)
        out, _ = track(frames)
        eps = out["episodes"]
        self.assertEqual(len(eps), 3, [(e["t_start"], e["t_end"], e["ended_by"]) for e in eps])
        self.assertEqual([e["slot_id"] for e in eps], ["slot-00"] * 3)
        self.assertEqual(eps[0]["ended_by"], "content_change")
        self.assertTrue(eps[0]["confirmed"])
        self.assertAlmostEqual(eps[1]["t_start"], 3.0)
        self.assertIn(st.TERMINAL, eps[2]["flags"])
        self.assertIn(st.SHORT_EPISODE, eps[2]["flags"])  # 2 observations
        # playhead advance recorded as motion evidence
        adv = eps[0]["motion"]["playhead_advance"]
        self.assertIsNotNone(adv)
        self.assertGreater(adv["forward_steps"], adv["backward_steps"])
        self.assertEqual(out["layout_intervals"][0]["kind"], "bottom_bar")

    def test_single_glitch_frame_is_transient(self):
        a, b = strip(1), strip(2)
        frames = show(a, 0.0, 4.0, seed=1)
        frames[8] = (frames[8][0], frame(b, 0.5, seed=99))
        out, _ = track(frames)
        self.assertEqual(len(out["episodes"]), 1)
        self.assertEqual(len(out["transient_observations"]), 1)
        self.assertEqual(out["transient_observations"][0]["obs_id"], "obs-000008")

    def test_identical_next_system_split_by_playhead_reset(self):
        a = strip(5)
        frames = show(a, 0.0, 3.0, seed=1) + show(a, 3.0, 3.0, seed=2)
        out, _ = track(frames)
        eps = out["episodes"]
        self.assertEqual(len(eps), 2, [(e["t_start"], e["t_end"]) for e in eps])
        self.assertEqual(eps[1]["started_by"], "playhead_reset")
        self.assertTrue(eps[1]["motion"]["reset_at_start"])

    def test_no_reset_split_without_confirmation(self):
        a = strip(5)
        frames = show(a, 0.0, 3.0, seed=1)
        # one spurious low playhead reading in the middle
        frames[6] = (frames[6][0], frame(a, 0.05, seed=77))
        out, _ = track(frames)
        self.assertEqual(len(out["episodes"]), 1)


class TwoRowAndPageTest(unittest.TestCase):
    def test_preview_row_promotion_is_linked(self):
        p1 = page([11, 12])
        p2 = page([12, 13])
        frames = show(p1, 0.0, 3.0, system=0, seed=1) + show(p2, 3.0, 3.0, system=0, seed=2)
        out, manifest = track(frames)
        eps = out["episodes"]
        slots = sorted({e["slot_id"] for e in eps})
        self.assertEqual(len(slots), 2)
        promoted = [e for e in eps if e["continuity_links"]]
        self.assertEqual(len(promoted), 1, [(e["id"], e["slot_id"], e["t_start"], e["continuity_links"]) for e in eps])
        link = promoted[0]["continuity_links"][0]
        self.assertEqual(link["kind"], "preview_promotion")
        self.assertLess(link["dy_px"], 0)

    def test_page_layout_and_translation(self):
        p1 = page([21, 22, 23, 24])
        p2 = page([23, 24, 25, 26])  # moved up by two systems
        frames = show(p1, 0.0, 4.0, system=0, seed=1) + show(p2, 4.0, 4.0, system=0, seed=2)
        out, _ = track(frames)
        kinds = {iv["kind"] for iv in out["layout_intervals"]}
        self.assertEqual(kinds, {"page"})
        links = [lk for e in out["episodes"] for lk in e["continuity_links"]]
        trans = [lk for lk in links if lk["kind"] == "page_translation"]
        self.assertEqual(len(trans), 2, links)
        self.assertEqual(len({round(lk["dy_px"]) for lk in trans}), 1)


class ContinuityAssignmentTest(unittest.TestCase):
    """Continuity links are verified and one-to-one; appearance alone never joins displays."""

    def _rec(self, eid, slot, t0, t1, role, y, started="content_change"):
        return {"id": eid, "slot_id": slot, "t_start": t0, "t_end": t1, "staff_top_y": y, "role": role,
                "started_by": started, "observation_ids": [f"{eid}-o"], "region_ids": [f"{eid}-r"], "continuity_links": []}

    def _link(self, records):
        from unittest.mock import patch
        same = st.Comparison("same", "same", "no_note_change", (0.0, 0.0))
        with patch.object(st, "_member_window", return_value=(np.full((10, 10, 3), 255, np.uint8), 12.0, (0, 0))), \
                patch.object(st, "compare_content", return_value=same):
            st._link_continuity(records, [], lambda _o: None, {"observations": []})
        return {r["id"]: r for r in records}

    def test_single_preview_promotion_is_accepted(self):
        recs = self._link([self._rec("old", "slot-01", 0.0, 4.0, "preview", 160.0), self._rec("new", "slot-00", 4.25, 8.0, "active", 40.0)])
        self.assertEqual([lk["from"] for lk in recs["new"]["continuity_links"]], ["old"])
        self.assertEqual(recs["new"]["continuity_links"][0]["kind"], "preview_promotion")

    def test_two_identical_previews_competing_for_one_row_are_not_linked(self):
        recs = self._link([self._rec("p1", "slot-01", 0.0, 4.0, "preview", 160.0), self._rec("p2", "slot-02", 0.0, 4.0, "preview", 280.0),
                           self._rec("new", "slot-00", 4.25, 8.0, "active", 40.0)])
        self.assertEqual(recs["new"]["continuity_links"], [])
        self.assertEqual(sorted(lk["rejected"] for lk in recs["new"]["continuity_candidates"]), ["competing_match", "competing_match"])

    def test_unverified_row_shift_is_not_linked(self):
        # same content in another slot, but no preview promotion and no shared page translation
        recs = self._link([self._rec("a", "slot-01", 0.0, 4.0, "active", 160.0), self._rec("b", "slot-00", 4.25, 8.0, "active", 40.0)])
        self.assertEqual(recs["b"]["continuity_links"], [])
        self.assertEqual(recs["b"]["continuity_candidates"][0]["rejected"], "unverified_row_shift")


class LayoutTest(unittest.TestCase):
    def test_horizontal_scroll_is_unsupported(self):
        a = strip(9, width=2800)
        frames = []
        for i in range(48):
            img = frame(a, 0.5, shift_x=40 * i, seed=i)[:, :1400]
            frames.append((i * STEP, np.ascontiguousarray(img)))
        out, _ = track(frames)
        kinds = [iv["kind"] for iv in out["layout_intervals"]]
        self.assertIn("horizontal_scroll", kinds)
        hs = [iv for iv in out["layout_intervals"] if iv["kind"] == "horizontal_scroll"][0]
        self.assertFalse(hs["supported"])
        self.assertEqual(hs["issue"], "UNSUPPORTED_HORIZONTAL_SCROLL")

    def test_clean_content_removes_translucent_background(self):
        a = strip(4)
        img = frame(a, 0.5)
        dark = 255 - img
        noisy = dark.copy()
        noisy[:, 600:900] = np.clip(noisy[:, 600:900].astype(int) + 70, 0, 255).astype(np.uint8)  # lighter band behind (dark theme)
        c1, c2 = st.clean_content(dark), st.clean_content(noisy)
        self.assertEqual(st.compare_content(c1, c2, 14.0).state, "same")


if __name__ == "__main__":
    unittest.main()


class ViewTransitionTest(unittest.TestCase):
    def test_identical_row_across_page_change_is_split(self):
        # Regression for Q8XtphO6Xz0 L10/L12: the bottom row of the next page is identical,
        # the top row changes, and the page change itself shows 2 garbled frames.
        p1 = page([51, 52])
        p2 = page([53, 52])  # same bottom system groove on the next page
        frames = show(p1, 0.0, 3.0, seed=1)
        t = 3.0
        for k in range(2):  # transition frames: both rows smeared
            img = frame(p1, 0.5, seed=90 + k)
            img = np.ascontiguousarray(np.roll(img, 37 * (k + 1), axis=1))
            frames.append((t, img))
            t += STEP
        frames += show(p2, t, 3.0, seed=2)
        out, _ = track(frames)
        bottom = sorted({e["slot_id"] for e in out["episodes"]})[-1]
        eps = [e for e in out["episodes"] if e["slot_id"] == bottom and e["confirmed"]]
        self.assertEqual(len(eps), 2, [(e["t_start"], e["t_end"], e["started_by"]) for e in out["episodes"]])
        self.assertEqual(eps[1]["started_by"], "view_transition")
