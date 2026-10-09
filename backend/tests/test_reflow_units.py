"""reflow_units: unit contract, ownership at SAFE seams, tails, exclusions, locks, validation."""

import copy
import unittest

import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_units as ru
from app.pipeline import system_detect as sd
from drum_score_fixture import render
import reflow_fixture as rf
from test_reflow_boundaries import bar_x, make_strip, observations_of


def system(sid, img, rec, *, obs="auto", included=True, **kw):
    return dict(system_id=sid, included=included, image=img, record=dict(rec, system_id=sid),
                observations=observations_of(img) if obs == "auto" else obs, **kw)


def build(systems, locks=()):
    return ru.build_document(job_id="job-test", revision=3, systems=systems, locks=locks, sources={"source_sha256": "x"})


class Units(unittest.TestCase):
    def test_split_only_at_safe_boundaries(self):
        img, rec = make_strip(tie_at=2)
        doc, _ = build([system("sys-001", img, rec)])
        self.assertEqual(doc["audit"]["validation"]["status"], "valid", doc["audit"]["validation"]["errors"])
        us = doc["measure_units"]
        self.assertEqual([u["kind"] for u in us], ["measure", "locked_group", "measure"])
        self.assertEqual([u["measure_count"] for u in us], [1, None, 1])
        self.assertEqual(len(us[1]["internal_boundary_ids"]), 1)
        self.assertIsNotNone(us[0]["prefix"])
        self.assertTrue(us[0]["prefix"]["clef_detected"])
        # milestone 2: the synthetic percussion clef is an isolated clef-only patch (replicable)
        self.assertTrue(us[0]["prefix"]["verified"])
        self.assertEqual(us[0]["prefix"]["replica"]["kind"], "percussion_clef")
        cut = [b for b in doc["boundaries"] if b["is_cut"]]
        self.assertEqual(len(cut), 2)
        for b in cut:
            self.assertEqual(b["class"], rb.SAFE)
        locked = [b for b in doc["boundaries"] if not b["is_cut"]]
        self.assertEqual(locked[0]["left_unit_id"], us[1]["id"])
        self.assertEqual(doc["stats"]["boundaries"], {"SAFE": 2, "LOCKED": 1, "UNKNOWN": 0})

    def test_lyrics_are_owned_by_one_unit(self):
        img, rec = make_strip(lyrics=True)
        doc, _ = build([system("sys-001", img, rec)])
        us = doc["measure_units"]
        self.assertEqual(len(us), 4)
        self.assertTrue(all(u["text_refs"] for u in us))
        for u in us:
            for t in u["text_refs"]:
                self.assertTrue(u["box"][0] <= t[0] and t[2] <= u["box"][2])

    def test_no_safe_boundary_keeps_the_whole_system(self):
        img, rec = make_strip()
        doc, _ = build([system("sys-001", img, rec, obs=None)])
        us = doc["measure_units"]
        self.assertEqual(len(us), 1)
        self.assertEqual(us[0]["kind"], "system")
        self.assertIsNone(us[0]["measure_count"])
        self.assertEqual(us[0]["box"], [0, 0, img.shape[1], img.shape[0]])
        self.assertEqual(doc["audit"]["validation"]["status"], "valid")

    def test_alternates_and_unchecked_are_out_of_the_denominator(self):
        img, rec = make_strip()
        doc, _ = build([system("sys-001", img, rec), system("sys-001-alt1", img, rec),
                        system("sys-002", img, rec, included=False)])
        self.assertEqual(doc["included_occurrence_ids"], ["sys-001"])
        self.assertEqual(doc["excluded_occurrence_ids"], ["sys-001-alt1", "sys-002"])
        self.assertTrue(all(u["occurrence_id"] == "sys-001" for u in doc["measure_units"]))
        self.assertEqual(doc["stats"]["measures_known"], 4)

    def test_returns_keep_distinct_ids(self):
        img, rec = make_strip()
        doc, _ = build([system("sys-004", img, rec), system("sys-016", img, rec)])
        ids = [u["id"] for u in doc["measure_units"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len({b["id"] for b in doc["boundaries"]}), len(doc["boundaries"]))
        self.assertEqual(doc["audit"]["validation"]["status"], "valid")

    def test_cut_preview_tail_is_owned_by_the_destination(self):
        uncut, rec = make_strip()
        cut = 1300
        strip = uncut[:, :cut].copy()
        rec = dict(rec, size=[cut, uncut.shape[0]], box_crop=[0, 0, cut, uncut.shape[0]],
                   preview_tail={"cut": True, "verified": True, "cut_x": cut, "destination_system_id": "sys-002"},
                   uncut={"box_crop": [0, 0, uncut.shape[1], uncut.shape[0]], "size": [uncut.shape[1], uncut.shape[0]]})
        doc, _ = build([system("sys-001", strip, rec, obs=observations_of(uncut), uncut_image=uncut)])
        self.assertEqual(doc["audit"]["validation"]["status"], "valid", doc["audit"]["validation"]["errors"])
        tail = next(u for u in doc["measure_units"] if u["kind"] == "preview_tail")
        self.assertEqual(tail["owner_occurrence_id"], "sys-002")
        self.assertEqual(tail["box"][0], cut)
        tb = next(b for b in doc["boundaries"] if b["kind"] == "preview_tail")
        self.assertEqual(tb["class"], rb.LOCKED)
        self.assertEqual(tb["owned_by"], "sys-002")
        self.assertTrue(tb["is_cut"])
        assets = doc["audit"]["accounting"]["assets"]
        unc = next(a for a in assets if a["asset_role"] == "uncut")
        self.assertTrue(unc["exact_reconstruction"])
        self.assertTrue(unc["cut_strip_consistency"]["consistent"])
        self.assertEqual(doc["stats"]["units"]["preview_tail"], 1)

    def test_document_root_contract(self):
        img, rec = make_strip()
        doc, _ = build([system("sys-001", img, rec)])
        for f in ru.ROOT_FIELDS:
            self.assertIn(f, doc)
        self.assertEqual(doc["config_hash"], rb.config_hash())
        self.assertEqual(doc["lines"], [])
        self.assertEqual(doc["justification_slots"], [])
        again, _ = build([system("sys-001", img, rec)])
        self.assertEqual(doc["analysis_hash"], again["analysis_hash"])
        img2 = img.copy()
        img2[5, 5] = 0
        changed, _ = build([system("sys-001", img2, rec)])
        self.assertNotEqual(doc["analysis_hash"], changed["analysis_hash"])


class Locks(unittest.TestCase):
    def setUp(self):
        self.img, self.rec = make_strip()
        self.obs = observations_of(self.img)

    def doc(self, locks):
        return build([system("sys-001", self.img, self.rec, obs=self.obs)], locks=locks)[0]

    def test_boundary_lock_keeps_the_measures_together(self):
        base = self.doc([])
        bid = base["boundaries"][1]["id"]
        doc = self.doc([{"id": "l1", "type": "boundary_lock", "targets": [bid]}])
        b = next(x for x in doc["boundaries"] if x["id"] == bid)
        self.assertEqual(b["class"], rb.LOCKED)
        self.assertFalse(b["is_cut"])
        self.assertEqual([u["kind"] for u in doc["measure_units"]], ["measure", "locked_group", "measure"])
        self.assertEqual(doc["locks"][0]["created_revision"], 3)
        self.assertEqual(doc["audit"]["conflicts"], [])

    def test_conflicts_are_structured(self):
        base = self.doc([])
        b0, b1 = base["boundaries"][0]["id"], base["boundaries"][1]["id"]
        u = [x["id"] for x in base["measure_units"]]
        doc = self.doc([
            {"id": "stale", "type": "boundary_lock", "targets": ["sys-001/bar@99999"]},
            {"id": "lk", "type": "boundary_lock", "targets": [b1]},
            {"id": "fb", "type": "forced_line_break", "targets": [b1]},
            {"id": "kt", "type": "keep_together", "targets": [u[3], u[0]]},
            {"id": "kt2", "type": "keep_together", "targets": [u[0], u[3]]},
            {"id": "fb0", "type": "forced_line_break", "targets": [b0]},
        ])
        codes = sorted(c["code"] for c in doc["audit"]["conflicts"])
        self.assertEqual(codes.count("STALE_LOCK_TARGET"), 1)
        self.assertIn("UNSAFE_FORCED_BREAK", codes)
        self.assertIn("KEEP_TOGETHER_ORDER", codes)
        self.assertGreaterEqual(codes.count("CONTRADICTORY_LOCKS"), 2)
        for c in doc["audit"]["conflicts"]:
            self.assertTrue(c["lock_ids"] and "target_ids" in c)
        self.assertEqual(len(doc["locks"]), 6)  # nothing silently dropped


class Validation(unittest.TestCase):
    def test_tampered_documents_are_invalid(self):
        img, rec = make_strip()
        doc, _ = build([system("sys-001", img, rec)])
        self.assertEqual(ru.validate_document(doc), [])
        bad = copy.deepcopy(doc)
        bad["measure_units"][1]["box"][0] -= 3
        self.assertTrue(any("gap or overlap" in e for e in ru.validate_document(bad)))
        bad = copy.deepcopy(doc)
        bad["boundaries"][0]["is_cut"] = False
        self.assertTrue(ru.validate_document(bad))
        bad = copy.deepcopy(doc)
        bad["boundaries"][0]["class"] = rb.UNKNOWN
        self.assertTrue(any("non-SAFE" in e for e in ru.validate_document(bad)))
        bad = copy.deepcopy(doc)
        del bad["ragged_exceptions"]
        self.assertTrue(ru.validate_document(bad))


class FixtureRegistration(unittest.TestCase):
    def test_barlines_register_across_fixture_observations(self):
        spec = rf.strip(5)
        frames = rf.show(spec, 0.0, 1.5)
        manifest, images = rf.build(frames)
        obs_by = {o["id"]: o for o in manifest["observations"]}
        record = {"member_obs_ids": list(obs_by)}
        occ = {"observations": [{"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]}
                                for o in manifest["observations"] if o["system_regions"]]}
        regions = rb.member_regions(record, occ, obs_by)
        self.assertGreaterEqual(len(regions), 3)
        clean = render(spec)
        det = sd.detect(clean)["staves"][0]
        rec = {"system_id": "sys-001", "staff_y_strip": det["lines"], "staff_gap_px": det["gap"], "staff_x_strip": det["x"],
               "box_crop": [0, 0, clean.shape[1], clean.shape[0]], "layout": "bottom_bar"}
        an = rb.analyse_strip(clean, rec, observations=regions)
        self.assertTrue(an.bars)
        for b in an.bars:
            self.assertGreaterEqual(b["registration"]["agree"], 3, b)


if __name__ == "__main__":
    unittest.main()
