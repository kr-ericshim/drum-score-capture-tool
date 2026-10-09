"""System occurrences in display order (reflow_occurrences)."""

import unittest

from app.pipeline import reflow_occurrences as ro
from app.pipeline import system_tracking as st
from reflow_fixture import build, loader, show, strip


def ep(eid, slot, t0, t1, *, n=None, started="content_change", ended="content_change", role="active", y=50.0, links=None,
       layout="bottom_bar"):
    n = n if n is not None else max(1, int(round((t1 - t0) / 0.25)) + 1)
    return {"id": eid, "slot_id": slot, "t_start": t0, "t_end": t1, "n_obs": n, "observation_ids": [f"{eid}-o{i}" for i in range(n)],
            "region_ids": [f"{eid}-o{i}-r0" for i in range(n)], "staff_top_y": y, "staff_gap_px": 12.0, "role": role,
            "flags": [], "started_by": started, "ended_by": ended, "continuity_links": links or [], "layout": layout}


def tracking(eps, layout=None):
    return {"episodes": eps, "layout_intervals": layout or [{"start": 0, "end": 999, "kind": "bottom_bar", "supported": True}]}


EMPTY_MANIFEST = {"observations": []}


def never_load(_obs):  # the rules under test must not need pixels
    raise AssertionError("image loaded")


class OccurrenceRulesTest(unittest.TestCase):
    def run_occ(self, eps, **kw):
        return ro.build_occurrences(tracking(eps, **kw), EMPTY_MANIFEST, never_load)

    def test_playhead_reset_split_is_one_display(self):
        eps = [ep("e1", "slot-00", 0.0, 4.0, ended="playhead_reset"), ep("e2", "slot-00", 4.25, 8.0, started="playhead_reset", ended="end_of_source")]
        out = self.run_occ(eps)
        self.assertEqual(len(out["systems"]), 1)
        self.assertEqual(out["systems"][0]["episode_ids"], ["e1", "e2"])
        self.assertTrue(out["systems"][0]["terminal_display"])

    def test_returns_are_placed_again_in_video_order(self):
        eps = [ep("a1", "slot-00", 0.0, 4.0, started="first_observation"), ep("b", "slot-00", 4.25, 8.0), ep("a2", "slot-00", 8.25, 12.0)]
        out = self.run_occ(eps)
        self.assertEqual([s["episode_ids"] for s in out["systems"]], [["a1"], ["b"], ["a2"]])
        self.assertTrue(all(s["included"] for s in out["systems"]))
        self.assertTrue(out["systems"][0]["first_display"])

    def test_preview_promotion_is_one_display_ordered_when_shown(self):
        link = {"from": "p", "to": "b", "kind": "preview_promotion"}
        eps = [ep("a", "slot-00", 0.0, 4.0, y=40.0), ep("p", "slot-01", 0.0, 4.0, role="preview", y=160.0),
               ep("b", "slot-00", 4.25, 8.0, y=40.0, links=[link])]
        out = self.run_occ(eps)
        self.assertEqual([s["main_episode_id"] for s in out["systems"]], ["a", "b"])
        self.assertEqual(sorted(out["systems"][1]["episode_ids"]), ["b", "p"])
        # the preview row's observations are not used for the strip
        self.assertTrue(all(o["episode_id"] == "b" for o in out["systems"][1]["observations"]))

    def test_transition_fragment_without_evidence_is_listed_not_hidden(self):
        # A view transition alone is no evidence: without pixels to show that a kept
        # display draws its content, the short display stays a restorable excluded item.
        eps = [ep("t1", "slot-00", 0.0, 6.0, y=40.0, ended="view_transition"), ep("t2", "slot-02", 0.0, 6.0, y=400.0, ended="view_transition"),
               ep("curl", "slot-00", 6.2, 6.6, y=40.0, started="view_transition"),
               ep("n1", "slot-00", 7.0, 13.0, y=40.0), ep("n2", "slot-02", 7.1, 13.0, y=400.0)]
        out = ro.build_occurrences(tracking(eps, layout=[{"start": 0, "end": 99, "kind": "page", "supported": True}]),
                                   EMPTY_MANIFEST, never_load)
        self.assertEqual([s["main_episode_id"] for s in out["systems"] if s["included"]], ["t1", "t2", "n1", "n2"])
        curl = [s for s in out["systems"] if s["main_episode_id"] == "curl"]
        self.assertEqual(len(curl), 1)
        self.assertFalse(curl[0]["included"])
        self.assertIn("SHORT_DISPLAY", curl[0]["issues"])
        self.assertFalse(out["fragments"][0]["hidden"])
        self.assertTrue(out["fragments"][0]["view_transition"])
        self.assertEqual(out["exclusions"]["short_listed_excluded"], [curl[0]["id"]])
        self.assertEqual(out["exclusions"]["hidden"], 0)

    def test_competing_continuity_links_keep_displays_separate(self):
        # Two identical preview rows both "continue" into one active row: joining all
        # links collapsed three displays into one before the fix.
        eps = [ep("a", "slot-00", 0.0, 4.0, y=40.0, started="first_observation"),
               ep("p1", "slot-01", 0.0, 4.0, role="preview", y=160.0), ep("p2", "slot-02", 0.0, 4.0, role="preview", y=280.0),
               ep("b", "slot-00", 4.25, 8.0, y=40.0, links=[{"from": "p1", "to": "b", "kind": "preview_promotion"},
                                                            {"from": "p2", "to": "b", "kind": "preview_promotion"}])]
        out = self.run_occ(eps)
        self.assertEqual(len(out["systems"]), 4)
        self.assertEqual(out["joins"], [])
        b = next(s for s in out["systems"] if s["main_episode_id"] == "b")
        self.assertEqual(b["episode_ids"], ["b"])
        sugg = {(x["system_id"], x["of_system_id"]) for x in out["continuity_suggestions"]}
        ids = {s["main_episode_id"]: s["id"] for s in out["systems"]}
        self.assertEqual(sugg, {(ids["b"], ids["p1"]), (ids["b"], ids["p2"])})

    def test_unverified_row_shift_link_does_not_join(self):
        eps = [ep("a", "slot-01", 0.0, 4.0, y=160.0, started="first_observation"),
               ep("b", "slot-00", 4.25, 8.0, y=40.0, links=[{"from": "a", "to": "b", "kind": "row_shift"}])]
        out = self.run_occ(eps)
        self.assertEqual(len(out["systems"]), 2)
        self.assertEqual(out["continuity_suggestions"][0]["basis"], "continuity_unverified_row_shift")

    def test_page_view_rows_top_to_bottom_even_if_lower_row_starts_first(self):
        eps = [ep("low", "slot-02", 0.0, 6.0, y=400.0), ep("top", "slot-00", 0.4, 6.0, y=40.0)]
        out = self.run_occ(eps, layout=[{"start": 0, "end": 99, "kind": "page", "supported": True}])
        self.assertEqual([s["main_episode_id"] for s in out["systems"]], ["top", "low"])

    def test_horizontal_scroll_episodes_are_not_placed(self):
        eps = [ep("h", "slot-00", 0.0, 6.0, layout="horizontal_scroll")]
        out = ro.build_occurrences(tracking(eps, layout=[{"start": 0, "end": 6, "kind": "horizontal_scroll", "supported": False,
                                                          "issue": "UNSUPPORTED_HORIZONTAL_SCROLL"}]), EMPTY_MANIFEST, never_load)
        self.assertEqual(out["systems"], [])
        self.assertEqual(out["unsupported_intervals"][0]["issue"], "UNSUPPORTED_HORIZONTAL_SCROLL")


def manifest_eps(frames_by_ep, *, step=0.24):
    """Real rendered frames per hand-made episode: [(eid, slot, t0, spec_or_frames, started, ended)]."""
    from reflow_fixture import frame
    pairs, meta = [], []
    for eid, slot, t0, spec, n, started, ended in frames_by_ep:
        ts = [t0 + i * step for i in range(n)]
        imgs = spec if isinstance(spec, list) else [frame(spec, (i + 0.5) / n, seed=hash(eid) % 1000 + i) for i in range(n)]
        meta.append((eid, slot, ts, started, ended, len(pairs)))
        pairs += list(zip(ts, imgs))
    manifest, images = build(pairs)
    obs = manifest["observations"]
    eps = []
    for eid, slot, ts, started, ended, k0 in meta:
        os_ = obs[k0:k0 + len(ts)]
        r0 = os_[0]["system_regions"][0]
        eps.append({"id": eid, "slot_id": slot, "t_start": ts[0], "t_end": ts[-1], "n_obs": len(ts),
                    "observation_ids": [o["id"] for o in os_], "region_ids": [o["system_regions"][0]["region_id"] for o in os_],
                    "staff_top_y": r0["staff_y"][0], "staff_gap_px": r0["staff_gap_px"], "role": "active", "flags": [],
                    "started_by": started, "ended_by": ended, "continuity_links": [], "layout": "bottom_bar"})
    return manifest, images, eps


class ShortDisplayEvidenceTest(unittest.TestCase):
    """Short displays are hidden only with positive evidence (pixels), never by a transition flag alone."""

    def test_short_first_system_ending_at_a_view_transition_stays_recoverable(self):
        # Audit probe: a 0-1.2 s first system with six observations ending at a view
        # transition was hidden (no review item, no strip) before the fix.
        a, b = strip(11), strip(12)
        manifest, images, eps = manifest_eps([
            ("a", "slot-00", 0.0, a, 6, "first_observation", "view_transition"),
            ("b", "slot-00", 1.5, b, 28, "view_transition", "end_of_source"),
        ])
        self.assertAlmostEqual(eps[0]["t_end"], 1.2, places=3)
        out = ro.build_occurrences(tracking(eps), manifest, loader(images))
        first = [s for s in out["systems"] if s["main_episode_id"] == "a"]
        self.assertEqual(len(first), 1, out["fragments"])
        self.assertFalse(first[0]["included"])  # excluded by default ...
        self.assertTrue(first[0]["first_display"])
        self.assertEqual(len(first[0]["observations"]), 6)  # ... with its observations, so a strip is built
        self.assertEqual(out["systems"][0]["main_episode_id"], "a")  # in video order
        self.assertFalse(out["fragments"][0]["hidden"])
        self.assertEqual(out["exclusions"]["short_listed_excluded"], [first[0]["id"]])

    def test_short_unique_system_between_two_systems_at_a_transition_is_listed(self):
        x, a, b = strip(21), strip(22), strip(23)
        manifest, images, eps = manifest_eps([
            ("x", "slot-00", 0.0, x, 20, "first_observation", "view_transition"),
            ("a", "slot-00", 5.0, a, 6, "view_transition", "view_transition"),
            ("b", "slot-00", 6.6, b, 20, "view_transition", "end_of_source"),
        ])
        out = ro.build_occurrences(tracking(eps), manifest, loader(images))
        short = [s for s in out["systems"] if s["main_episode_id"] == "a"]
        self.assertEqual(len(short), 1)
        self.assertFalse(short[0]["included"])
        frag = out["fragments"][0]
        self.assertFalse(frag["hidden"])
        self.assertIn(frag["evidence"]["reason"], ("unexplained_component", "unexplained_content"))

    def test_flicker_of_the_same_image_is_hidden_with_evidence(self):
        x, b = strip(31), strip(32)
        manifest, images, eps = manifest_eps([
            ("x", "slot-00", 0.0, x, 20, "first_observation", "view_transition"),
            ("x2", "slot-00", 4.9, x, 2, "view_transition", "view_transition"),
            ("b", "slot-00", 5.5, b, 20, "view_transition", "end_of_source"),
        ])
        out = ro.build_occurrences(tracking(eps), manifest, loader(images))
        self.assertEqual([s["main_episode_id"] for s in out["systems"]], ["x", "b"])
        frag = out["fragments"][0]
        self.assertTrue(frag["hidden"])
        self.assertEqual(frag["reasons"], ["same_as_neighbour_display"])
        self.assertEqual(frag["represented_by"], [out["systems"][0]["id"]])
        self.assertEqual(len(frag["observations"]), 2)
        self.assertEqual(out["exclusions"]["hidden_by_reason"], {"same_as_neighbour_display": 1})

    def test_fade_frame_drawing_part_of_the_next_system_is_hidden(self):
        x, b = strip(41), strip(42)
        faded = b.copy()
        for key in list(faded.notes)[::2]:  # half of the notes not drawn yet
            del faded.notes[key]
        manifest, images, eps = manifest_eps([
            ("x", "slot-00", 0.0, x, 20, "first_observation", "view_transition"),
            ("f", "slot-00", 4.9, faded, 2, "view_transition", "view_transition"),
            ("b", "slot-00", 5.5, b, 20, "view_transition", "end_of_source"),
        ])
        out = ro.build_occurrences(tracking(eps), manifest, loader(images))
        frag = out["fragments"][0]
        self.assertTrue(frag["hidden"], frag)
        self.assertEqual(frag["reasons"], ["covered_by_kept_display"])

    def test_short_display_with_one_extra_note_is_listed(self):
        x, b = strip(51), strip(52)
        varied = b.copy()
        free = [(0, bar, slot) for bar in range(4) for slot in range(8) if (0, bar, slot) not in varied.notes]
        varied.notes[free[len(free) // 2]] = [3.5]
        manifest, images, eps = manifest_eps([
            ("x", "slot-00", 0.0, x, 20, "first_observation", "view_transition"),
            ("v", "slot-00", 4.9, varied, 2, "view_transition", "view_transition"),
            ("b", "slot-00", 5.5, b, 20, "view_transition", "end_of_source"),
        ])
        out = ro.build_occurrences(tracking(eps), manifest, loader(images))
        frag = out["fragments"][0]
        self.assertFalse(frag["hidden"], frag)


def _free_x(imgs, cy, rad):
    """A column where none of ``imgs`` has ink within ``rad`` px of row ``cy``."""
    import cv2
    import numpy as np
    ink = np.zeros(imgs[0].shape[:2], bool)
    for im in imgs:
        ink |= cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) < 200
    return next(cx for cx in range(200, 1300, 7) if not ink[cy - rad:cy + rad, cx - rad:cx + rad].any())


class SmallMarkHidingTest(unittest.TestCase):
    """Audit round 2, P0: a unique dot of radius 1-4 px in a short middle display was hidden
    (``same_as_neighbour_display``: page_diff ``ambiguous/small_change`` counted as the same), and
    staff lines plus a dot were hidden as ``no_content_beyond_staff_lines``."""

    def _run(self, mids):
        from reflow_fixture import frame
        x, b = strip(31), strip(32)
        xs = [frame(x, (i + 0.5) / 20, seed=i) for i in range(20)]
        bs = [frame(b, (i + 0.5) / 20, seed=50 + i) for i in range(20)]
        manifest, images, eps = manifest_eps([
            ("x", "slot-00", 0.0, xs, 20, "first_observation", "view_transition"),
            ("x2", "slot-00", 4.9, mids, 2, "view_transition", "view_transition"),
            ("b", "slot-00", 5.5, bs, 20, "view_transition", "end_of_source"),
        ])
        out = ro.build_occurrences(tracking(eps), manifest, loader(images))
        self.assertEqual(len(out["fragments"]), 1)
        return out, out["fragments"][0], xs

    def _geometry(self):
        from reflow_fixture import frame
        from app.pipeline import observations as obm
        r = obm.analyse_crop(frame(strip(31), 0.5, seed=0))["regions"][0]
        return r["staff_gap_px"], r["staff_y"]

    def test_unique_dot_of_radius_1_to_4_keeps_the_short_display_listed(self):
        import cv2
        from reflow_fixture import frame
        g, sy = self._geometry()
        rows = {"above": int(sy[0] - 2.5 * g), "staff_space": int(round((sy[1] + sy[2]) / 2)), "below": int(sy[4] + 2.0 * g)}
        x = strip(31)
        for where, cy in rows.items():
            for radius in (1, 2, 3, 4):
                with self.subTest(where=where, radius=radius):
                    mids = [frame(x, 0.5, seed=99 + k) for k in range(2)]
                    xs = [frame(x, (i + 0.5) / 20, seed=i) for i in range(20)]
                    cx = _free_x(xs + mids, cy, 5 if where == "staff_space" else 10)
                    for im in mids:
                        cv2.circle(im, (cx, cy), radius, (20, 20, 20), -1)
                    out, frag, _ = self._run(mids)
                    self.assertFalse(frag["hidden"], frag["evidence"])
                    self.assertEqual(frag["reasons"], ["short_unique_display"])
                    ev = frag["evidence"]
                    self.assertEqual(ev["reason"], "unexplained_component")
                    bx = ev["component_box"]  # the dot itself (window rows start 4 gaps above the top line)
                    self.assertTrue(bx[0] <= cx < bx[2], (cx, bx))
                    listed = [s for s in out["systems"] if s["main_episode_id"] == "x2"]
                    self.assertEqual(len(listed), 1)
                    self.assertFalse(listed[0]["included"])

    def test_the_same_display_without_the_dot_is_still_hidden(self):
        from reflow_fixture import frame
        mids = [frame(strip(31), 0.5, seed=99 + k) for k in range(2)]
        _out, frag, _ = self._run(mids)
        self.assertTrue(frag["hidden"], frag["evidence"])

    def test_staff_lines_with_a_dot_are_not_empty(self):
        import cv2
        import numpy as np
        from reflow_fixture import frame
        g, sy = self._geometry()
        for radius in (0, 1, 2, 4):
            with self.subTest(radius=radius):
                mids = []
                for _k in range(2):
                    im = np.full_like(frame(strip(31), 0.5), 255)
                    for y in sy:
                        cv2.line(im, (60, int(round(y))), (1340, int(round(y))), (20, 20, 20), 2)
                    if radius:
                        cv2.circle(im, (200, int(sy[0] - 2.5 * g)), radius, (20, 20, 20), -1)
                    mids.append(im)
                _out, frag, _ = self._run(mids)
                if radius:
                    self.assertFalse(frag["hidden"], frag["evidence"])
                    self.assertEqual(frag["evidence"]["reason"], "unexplained_component")
                else:
                    self.assertTrue(frag["hidden"], frag["evidence"])  # staff lines only

    def test_tracker_small_change_is_not_sameness_for_hiding(self):
        import cv2
        from reflow_fixture import build, frame
        g, sy = self._geometry()
        a = frame(strip(31), 0.5, seed=1)
        b = a.copy()
        cy = int(sy[0] - 2.5 * g)
        cv2.circle(b, (_free_x([a], cy, 10), cy), 2, (20, 20, 20), -1)
        manifest, images = build([(0.0, a), (0.25, b)])
        obs = {o["id"]: o for o in manifest["observations"]}
        wa = ro._window_of(obs, loader(images), "obs-000000", obs["obs-000000"]["system_regions"][0]["region_id"])
        wb = ro._window_of(obs, loader(images), "obs-000001", obs["obs-000001"]["system_regions"][0]["region_id"])
        # page_diff itself does not see a 2-px dot (its verdict may even be "same"); only the
        # component accounting decides whether a display may be hidden
        self.assertTrue(ro._same_display_content(wa, wb))
        self.assertFalse(ro.shown_by_kept_display([wb], [wa])["shown"])
        self.assertTrue(ro.shown_by_kept_display([wa], [wb])["shown"])  # removing a dot hides nothing


class SimilarStripTest(unittest.TestCase):
    """"Looks similar" needs the whole display to match, text included."""

    def _strip(self, spec, seed):
        from reflow_fixture import frame
        return frame(spec, 0.5, seed=seed)

    def test_same_notation_with_a_different_measure_number_is_not_similar(self):
        # aOED/bF69 false suggestions: identical grooves, different measure numbers.
        a = self._strip(strip(5, numbers=True, first_bar=21), 1)
        b = self._strip(strip(5, numbers=True, first_bar=29), 2)
        same, info = ro._same_whole_display(a, b, 14.0)
        self.assertFalse(same, info)

    def test_the_same_display_again_is_similar(self):
        a = self._strip(strip(5, numbers=True, first_bar=21), 1)
        b = self._strip(strip(5, numbers=True, first_bar=21), 2)
        same, info = ro._same_whole_display(a, b, 14.0)
        self.assertTrue(same, info)

    def test_corpus_strips_identical_grooves_with_different_numbers_are_not_similar(self):
        # Strips of the earlier e2e run (development data, not held out): the wrong
        # suggestions (aOED sys-008~006, bF69 sys-016~007, sys-022~021, sys-023~007)
        # differ in measure numbers / lyrics / one notehead; a GT return (aOED sys-016~004) matches.
        from pathlib import Path
        import cv2
        root = Path.home() / "Documents/drum-score-corpus/reflow/e2e"
        cases = [("aOED5zskhGk", "sys-008", "sys-006", False), ("bF69tpnUk5w", "sys-016", "sys-007", False),
                 ("bF69tpnUk5w", "sys-022", "sys-021", False), ("bF69tpnUk5w", "sys-023", "sys-007", False),
                 ("aOED5zskhGk", "sys-016", "sys-004", True), ("aOED5zskhGk", "sys-023", "sys-011", True)]
        if not all((root / v / "strips" / f"strip_{a}.png").is_file() for v, a, _b, _e in cases):
            self.skipTest("corpus strips not available")
        for vid, a, b, expect in cases:
            same, info = ro._same_whole_display(cv2.imread(str(root / vid / "strips" / f"strip_{a}.png")),
                                                cv2.imread(str(root / vid / "strips" / f"strip_{b}.png")), 16.0)
            self.assertEqual(same, expect, (vid, a, b, info))

    def test_suggestions_from_strips_point_later_to_earlier(self):
        import tempfile
        from pathlib import Path
        import cv2
        with tempfile.TemporaryDirectory() as td:
            imgs = [self._strip(strip(5, numbers=True, first_bar=1), 1), self._strip(strip(6, numbers=True, first_bar=5), 2),
                    self._strip(strip(5, numbers=True, first_bar=1), 3), self._strip(strip(5, numbers=True, first_bar=9), 4)]
            systems, strip_of = [], {}
            for i, im in enumerate(imgs):
                sid = f"sys-00{i + 1}"
                pth = Path(td) / f"{sid}.png"
                cv2.imwrite(str(pth), im)
                strip_of[sid] = str(pth)
                systems.append({"id": sid, "order_t": i * 5.0, "staff_top_y_crop": 50.0, "staff_gap_px": 14.0})
            out = ro.suggest_similar_strips(systems, strip_of)
        self.assertEqual([(x["system_id"], x["of_system_id"], x["reason"]) for x in out], [("sys-003", "sys-001", "looks_similar")])


class OccurrencePipelineTest(unittest.TestCase):
    """Real tracker on rendered frames: A, B, A again."""

    def test_return_is_kept_and_suggested_as_duplicate(self):
        a, b = strip(1), strip(2)
        frames = show(a, 0.0, 3.0, seed=1) + show(b, 3.0, 3.0, seed=2) + show(a, 6.0, 3.0, seed=3)
        manifest, images = build(frames)
        load = loader(images)
        trk = st.build_episodes(manifest, load)
        out = ro.build_occurrences(trk, manifest, load)
        included = [s for s in out["systems"] if s["included"]]
        self.assertEqual(len(included), 3, [(s["t_start"], s["t_end"]) for s in out["systems"]])
        self.assertEqual([round(s["t_start"]) for s in included], [0, 3, 6])
        dups = ro.suggest_duplicates(included, manifest, load)
        self.assertEqual([(d["system_id"], d["of_system_id"]) for d in dups], [(included[2]["id"], included[0]["id"])])


if __name__ == "__main__":
    unittest.main()
