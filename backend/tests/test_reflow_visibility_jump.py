"""2C-0 jump record diagnostics and thin-stroke accounting."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app.pipeline import reflow_jump as rj, reflow_strips as rs
from test_reflow_jump_coverage import five_display_run, manifest_for, jump_record, run_seams, paper, STAFF

class JumpVisibilityTest(unittest.TestCase):
    def test_finishing_diagnostics_reach_jump_strip_record(self):
        eps = five_display_run()
        tracking = {"episodes":eps, "layout_intervals":[]}
        manifest = manifest_for(eps)
        jump = jump_record(tracking, run_seams(eps))
        comps = {e["id"]:paper(range(100,900,140)) for e in eps}
        covered = {e["id"]:np.zeros(1000,bool) for e in eps}
        codes = [rs.LOW_CONTRAST_KEPT, rs.CONTENT_LOST_IN_FINISHING, rs.UNCERTAIN_MARK_KEPT]
        def finish(im, **kw):
            return im.copy(), False, False, {"issues":codes.copy(), "survival":{"lost":1}}
        with tempfile.TemporaryDirectory() as td, patch.object(rs,"finish_strip",side_effect=finish):
            built = rj.build_jump_systems(jump, tracking, manifest, Path(td), composites=comps, covered=covered)
        self.assertTrue(built)
        for _occ,rec in built:
            for code in codes:
                self.assertIn(code,rec["issues"])
            self.assertEqual(rec["finishing"]["issues"],codes)

    def test_one_pixel_horizontal_mark_touching_staff_is_not_fringe(self):
        mask = np.zeros((160,800),bool); mask[63,420:432] = True
        scaffold = np.zeros_like(mask); scaffold[62,20:780] = True
        miss = np.ones(800,bool)
        bad,px,explained = rj._uncovered_components(mask,miss,scaffold,[[62]],12,rj.COVERAGE_CONFIG)
        self.assertEqual(px,12)
        self.assertEqual(len(bad),1)
        self.assertNotIn("staff_line_remnant",explained)

    def test_two_pixel_speckle_remains_explained(self):
        mask = np.zeros((160,800),bool); mask[110:112,420] = True
        bad,px,explained = rj._uncovered_components(mask,np.ones(800,bool),np.zeros_like(mask),[],12,rj.COVERAGE_CONFIG)
        self.assertEqual((bad,px),([],0))
        self.assertEqual(explained,{"speckle":1})
