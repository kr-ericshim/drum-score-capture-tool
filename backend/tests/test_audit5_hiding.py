"""Raw-evidence regressions for short-display hiding and independent coverage."""

import copy
import unittest

import cv2
import numpy as np

from app.pipeline import reflow_occurrences as ro


def fixture(gray=None, *, marked_indices=(0, 1), short_count=2, inverted=False):
    """A duplicate short middle display; its only extra evidence is the audit stroke."""
    base = np.full((200, 900, 3), 255, np.uint8)
    for y in (80, 92, 104, 116, 128):
        cv2.line(base, (40, y), (860, y), (20, 20, 20), 1)
    cv2.rectangle(base, (260, 91), (268, 98), (20, 20, 20), -1)
    manifest = {"observations": []}
    images, episodes = {}, []
    for eid, times, started, ended in (
        ("left", np.linspace(0, 4, 9), "first_observation", "view_transition"),
        ("short", np.linspace(4.25, 5.45 if short_count > 2 else 4.5, short_count), "view_transition", "view_transition"),
        ("right", np.linspace(5.75, 9.75, 9), "view_transition", "end_of_source"),
    ):
        os_, rs = [], []
        for k, t in enumerate(times):
            oid, rid = f"{eid}-{k}", f"{eid}-{k}-r"
            image = base.copy()
            if eid == "short" and gray is not None and k in marked_indices:
                image[145:157, 600] = gray
            images[oid] = 255 - image if inverted else image
            region = {"region_id": rid, "bbox": [0, 0, 900, 200],
                      "staff_y": [80, 92, 104, 116, 128], "staff_gap_px": 12,
                      "staff_x": [40, 860]}
            manifest["observations"].append({"id": oid, "t_sec": float(t), "sample_kind": "coarse",
                                              "system_regions": [region]})
            os_.append(oid)
            rs.append(rid)
        episodes.append({"id": eid, "slot_id": "slot-00", "t_start": float(times[0]),
                         "t_end": float(times[-1]), "n_obs": len(times), "observation_ids": os_,
                         "region_ids": rs, "staff_top_y": 80, "staff_gap_px": 12,
                         "role": "active", "started_by": started, "ended_by": ended,
                         "continuity_links": [], "layout": "bottom_bar"})
    tracking = {"episodes": episodes, "layout_intervals": []}
    return tracking, manifest, images


class Audit5HidingTest(unittest.TestCase):
    def run_fixture(self, *args, **kwargs):
        tr, manifest, images = fixture(*args, **kwargs)
        out = ro.build_occurrences(tr, manifest, lambda obs: images[obs["id"]])
        return out, tr, manifest, images

    def assert_reviewable(self, out):
        frag = out["fragments"][0]
        self.assertFalse(frag["hidden"], frag)
        self.assertEqual(frag["evidence"]["basis"], "all_raw_polarity_normalized_members")
        self.assertEqual(frag["evidence"]["reason"], "unexplained_component")
        short = next(s for s in out["systems"] if s["main_episode_id"] == "short")
        self.assertFalse(short["included"])
        self.assertIn("UNCERTAIN_MARK_KEPT", short["issues"])
        self.assertTrue(short["observations"])
        self.assertEqual(sum(s["included"] for s in out["systems"]), 2)

    def test_gray_135_stroke_is_kept_and_flagged(self):
        self.assert_reviewable(self.run_fixture(135)[0])

    def test_gray_190_stroke_is_kept_and_flagged(self):
        self.assert_reviewable(self.run_fixture(190)[0])

    def test_black_stroke_control_is_kept_and_flagged(self):
        self.assert_reviewable(self.run_fixture(0)[0])

    def test_dark_polarity_gray_stroke_is_kept(self):
        self.assert_reviewable(self.run_fixture(190, inverted=True)[0])

    def test_once_only_nonrepresentative_observation_is_checked(self):
        out = self.run_fixture(190, marked_indices=(1,), short_count=7)[0]
        self.assert_reviewable(out)
        self.assertEqual(out["fragments"][0]["evidence"]["observations_checked"], 7)

    def test_genuine_duplicate_short_display_is_still_hidden(self):
        out = self.run_fixture()[0]
        self.assertEqual(len(out["systems"]), 2)
        frag = out["fragments"][0]
        self.assertTrue(frag["hidden"], frag)
        self.assertEqual(frag["reasons"], ["same_as_neighbour_display"])
        self.assertEqual(out["self_checks"]["hidden_fragment_uncovered"], 0)
        self.assertTrue(out["self_checks"]["hidden_fragment_coverage"][0]["covered"])

    def test_gray_recovered_only_in_a_neighbour_member_allows_hiding(self):
        tr, manifest, images = fixture(190)
        # Neither neighbour's first/middle/last witness has the mark.
        images["left-1"][145:157, 600] = 190
        out = ro.build_occurrences(tr, manifest, lambda obs: images[obs["id"]])
        self.assertTrue(out["fragments"][0]["hidden"], out["fragments"])
        self.assertEqual(out["self_checks"]["hidden_fragment_uncovered"], 0)

    def test_secondary_joined_member_mark_is_checked_and_reviewable(self):
        tr, manifest, images = fixture()
        extra = copy.deepcopy(tr["episodes"][1])
        extra.update(id="preview", slot_id="slot-01", role="preview", n_obs=1,
                     t_start=4.25, t_end=4.25, observation_ids=["preview-o"], region_ids=["preview-r"])
        observation = copy.deepcopy(manifest["observations"][9])
        observation.update(id="preview-o", t_sec=4.25)
        observation["system_regions"][0]["region_id"] = "preview-r"
        manifest["observations"].append(observation)
        images["preview-o"] = images["short-0"].copy()
        images["preview-o"][145:157, 600] = 190
        tr["episodes"].append(extra)
        tr["episodes"][1]["continuity_links"] = [{"from": "preview", "to": "short", "kind": "preview_promotion"}]
        out = ro.build_occurrences(tr, manifest, lambda obs: images[obs["id"]])
        self.assert_reviewable(out)
        short = next(s for s in out["systems"] if s["main_episode_id"] == "short")
        self.assertIn("preview-o", [o["obs_id"] for o in short["observations"]])

    def test_gray_mark_in_colored_cursor_column_is_not_skipped(self):
        tr, manifest, images = fixture(190)
        for oid in ("short-0", "short-1"):
            images[oid][80:130, 600] = (200, 80, 20)
        out = ro.build_occurrences(tr, manifest, lambda obs: images[obs["id"]])
        self.assert_reviewable(out)

    def test_unused_neighbour_preview_cannot_prove_recovery(self):
        tr, manifest, images = fixture(190)
        preview = copy.deepcopy(tr["episodes"][0])
        preview.update(id="preview", slot_id="slot-01", role="preview", n_obs=1,
                       t_start=0, t_end=0, observation_ids=["preview-o"], region_ids=["preview-r"])
        observation = copy.deepcopy(manifest["observations"][0])
        observation["id"] = "preview-o"
        observation["system_regions"][0]["region_id"] = "preview-r"
        manifest["observations"].append(observation)
        images["preview-o"] = images["short-0"].copy()
        tr["episodes"].append(preview)
        tr["episodes"][0]["continuity_links"] = [{"from": "preview", "to": "left", "kind": "preview_promotion"}]
        out = ro.build_occurrences(tr, manifest, lambda obs: images[obs["id"]])
        self.assert_reviewable(out)
        left = next(s for s in out["systems"] if s["main_episode_id"] == "left")
        self.assertIn("preview", left["episode_ids"])
        self.assertNotIn("preview-o", [o["obs_id"] for o in left["observations"]])

    def test_self_check_rejects_forged_hidden_coverage(self):
        out, tr, manifest, images = self.run_fixture(190)
        frag = copy.deepcopy(out["fragments"][0])
        frag.update(hidden=True, represented_by=[out["systems"][0]["id"]],
                    evidence={"reason": "covered_by_kept_display"})
        systems = [s for s in out["systems"] if s["included"]]
        cands = [{"main": e, "episodes": [e], "t_start": e["t_start"], "t_end": e["t_end"]}
                 for e in (tr["episodes"][0], tr["episodes"][2])]
        obs_by = ro._obs_index(manifest)
        raw = lambda o, r: ro._raw_window_of(obs_by, lambda obs: images[obs["id"]], o, r)
        def ep_window(e, where):
            k = where if isinstance(where, int) else (0 if where == "first" else -1)
            return raw(e["observation_ids"][k], e["region_ids"][k])
        check = ro._self_checks([(c, True) for c in cands], systems, {}, tr["episodes"], [frag], set(),
                                tr["episodes"], .25, ep_window, lambda c: ep_window(c["main"], "first"),
                                lambda _: None)
        self.assertEqual(check["hidden_fragment_uncovered"], 1)
        self.assertGreater(check["score_time_uncovered_sec"], 0)
        self.assertEqual(check["score_time_uncovered_at_view_transitions_sec"], 0)
        self.assertFalse(check["hidden_fragment_coverage"][0]["covered"])


if __name__ == "__main__":
    unittest.main()
