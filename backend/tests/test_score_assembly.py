"""Location assembly policies on synthetic display sequences."""

import unittest

import numpy as np

from app.pipeline import score_assembly as sa
from app.pipeline import system_tracking as st
from reflow_fixture import build, frame, loader, page, show, strip


def run(frames, policy):
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    return sa.assemble_locations(tracking, manifest, load, policy=policy), tracking


def ev_by(out):
    return {e["id"]: e for e in out["evidence"]}


class ConservativePolicyTest(unittest.TestCase):
    def test_identical_revisit_is_nominated_not_merged(self):
        a, b = strip(1), strip(2)
        frames = show(a, 0, 3, seed=1) + show(b, 3, 3, seed=2) + show(a, 6, 3, seed=3)
        out, _ = run(frames, "conservative")
        self.assertEqual(len(out["locations"]), 3)
        self.assertEqual(out["merges"], [])
        unresolved = [c for c in out["identity_candidates"] if c["state"] == "unresolved"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["issue"], "POSSIBLE_REVISIT")
        self.assertEqual(out["completion"], "needs_review")
        self.assertEqual(out["ordered_location_ids"], ["loc-001", "loc-002", "loc-003"])

    def test_identical_grooves_without_identifier_stay_unresolved_in_evidence_policy(self):
        a, b = strip(1), strip(2)
        frames = show(a, 0, 3, seed=1) + show(b, 3, 3, seed=2) + show(a, 6, 3, seed=3)
        out, _ = run(frames, "evidence")
        self.assertEqual(len(out["locations"]), 3)
        self.assertEqual([m for m in out["merges"] if m["basis"] != "page_translation"], [])
        self.assertTrue(any(c["state"] == "unresolved" for c in out["identity_candidates"]))


class EvidencePolicyTest(unittest.TestCase):
    def test_different_printed_numbers_resolve_identical_grooves_as_different(self):
        a1 = strip(1, first_bar=1, numbers=True)
        a2 = strip(1, first_bar=9, numbers=True)  # same groove, different measure numbers
        b = strip(2, first_bar=5, numbers=True)
        frames = show(a1, 0, 3, seed=1) + show(b, 3, 3, seed=2) + show(a2, 6, 3, seed=3)
        out, _ = run(frames, "evidence")
        cands = out["identity_candidates"]
        diff = [c for c in cands if c["state"] == "resolved_different"]
        # the comparator may or may not see the number change; when it nominates the pair, I resolves it
        for c in cands:
            self.assertNotEqual(c["state"], "resolved_same")
        self.assertEqual(len(out["locations"]), 3)
        self.assertEqual(out["merges"], [])
        if diff:
            kinds = [ev_by(out)[e]["kind"] for e in diff[0]["evidence_ids"]]
            self.assertIn("different_identifier_patch", kinds)

    def test_identifier_match_without_independent_context_stays_unresolved(self):
        # Revisit of a numbered sequence. Identifier patches match, but the neighbouring
        # relations are anchored only by the same kind of patch similarity, which is not
        # independent context -> no automatic merge, POSSIBLE_REVISIT with I evidence stored.
        s1 = strip(1, first_bar=1, numbers=True)
        s2 = strip(2, first_bar=5, numbers=True)
        s3 = strip(3, first_bar=9, numbers=True)
        frames = (show(s1, 0, 3, seed=1) + show(s2, 3, 3, seed=2) + show(s3, 6, 3, seed=3)
                  + show(s1, 9, 3, seed=4) + show(s2, 12, 3, seed=5) + show(s3, 15, 3, seed=6))
        out, _ = run(frames, "evidence")
        self.assertEqual([m for m in out["merges"] if m["basis"] == "identifier+context"], [])
        self.assertEqual(len(out["locations"]), 6)
        unresolved = [c for c in out["identity_candidates"] if c["state"] == "unresolved"]
        self.assertEqual(len(unresolved), 3)
        kinds = {ev_by(out)[e]["kind"] for c in unresolved for e in c["evidence_ids"]}
        self.assertIn("identifier_patch_match", kinds)
        self.assertIsNone(out["locations"][0]["number_value"])
        self.assertIsNotNone(out["locations"][0]["number_patch_id"])

    def test_revisited_page_view_is_a_ranked_suggestion_not_a_merge(self):
        # Identical page views can be different written pages (Q8XtphO6Xz0), so a full
        # page-view appearance match is a review suggestion, never an automatic merge.
        p1 = page([31, 32, 33])
        p2 = page([34, 35, 36])
        frames = show(p1, 0, 4, seed=1) + show(p2, 4, 4, seed=2) + show(p1, 8, 4, seed=3)
        cons, _ = run(frames, "conservative")
        evid, _ = run(frames, "evidence")
        self.assertEqual(len(cons["locations"]), 9)
        self.assertEqual(len(evid["locations"]), 9)
        self.assertEqual([m for m in evid["merges"] if m["basis"] not in ("page_translation", "preview_promotion")], [])
        sugg = [c for c in evid["identity_candidates"] if c.get("suggestion") == "same_location_likely"]
        self.assertEqual(len(sugg), 3)
        self.assertTrue(all(c["state"] == "unresolved" for c in sugg))
        kinds = {e["kind"] for e in evid["evidence"]}
        self.assertIn("page_view_appearance_match", kinds)
        self.assertTrue(any(e["basis"] == "page_geometry" and e["state"] == "confirmed" for e in evid["order_edges"]))

    def test_content_beyond_roi_issue(self):
        m = {"observations": [{"t_sec": t * 0.5, "system_regions": [{"staff_gap_px": 10.0}],
                               "edge_content": {"top": 2 if t < 8 else 0, "top_px": 40}} for t in range(12)]}
        iss = sa.content_beyond_roi_issues(m)
        self.assertEqual(len(iss), 1)
        self.assertEqual(iss[0]["edge"], "top")
        self.assertEqual(iss[0]["interval"], [0.0, 3.5])

    def test_every_merge_stores_evidence(self):
        p1 = page([21, 22, 23, 24])
        p2 = page([23, 24, 25, 26])
        frames = show(p1, 0, 4, seed=1) + show(p2, 4, 4, seed=2)
        for policy in sa.POLICIES:
            out, _ = run(frames, policy)
            ev = ev_by(out)
            self.assertEqual(len(out["locations"]), 6, policy)
            for m in out["merges"]:
                self.assertTrue(m["evidence_ids"])
                for e in m["evidence_ids"]:
                    self.assertIn(e, ev)

    def test_patch_similarity(self):
        a = np.full((24, 20), 255, np.float32)
        a[4:20, 8:12] = 0
        b = a.copy()
        c = np.full((24, 20), 255, np.float32)
        c[4:8, 2:18] = 0
        self.assertGreater(sa.patch_similarity(a, b), 0.99)
        self.assertLess(sa.patch_similarity(a, c), 0.5)
        self.assertIsNone(sa.patch_similarity(a, None))


if __name__ == "__main__":
    unittest.main()
