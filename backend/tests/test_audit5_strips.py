"""Audit 5: full-ROI and rejected-member hypotheses survive the real strip path."""
import base64
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_strips as rs, system_tracking as st, reflow_occurrences as ro
from test_reflow_visibility_marks import paper, system_case


class Audit5StripsTest(unittest.TestCase):
    @staticmethod
    def run_path(images):
        _, manifest, load = system_case(images)
        tracking = st.build_episodes(manifest, load)
        occurrences = ro.build_occurrences(tracking, manifest, load)
        systems = [s for s in occurrences['systems'] if s['included']]
        return manifest, load, [(s, *rs.build_strip(s, manifest, load, chrome=False)) for s in systems]

    def assert_raw_stroke(self, records, images, index, x, y=110):
        found = []
        for _, _, rec in records:
            m = rec['minority_content']
            for e in m['events']:
                owners = [o for o in e.get('foreground_support', [])
                          if any(row == y and a <= x < b for row, a, b in o['spans_crop'])]
                if not owners:
                    continue
                self.assertIn(rs.UNCERTAIN_MARK_KEPT, rec['issues'])
                self.assertEqual(e['classification'], rs.UNCERTAIN_MARK_KEPT)
                self.assertEqual(len(m['alternates']), 1)
                for p in m['alternates'][0]['evidence_patches']:
                    if p['event_index'] != m['events'].index(e):
                        continue
                    a,b,c,d = p['box_crop']
                    if not (a <= x < c and b <= y and y+12 <= d):
                        continue
                    raw = cv2.imdecode(np.frombuffer(base64.b64decode(p['raw_png_base64']), np.uint8), cv2.IMREAD_COLOR)
                    self.assertTrue(np.array_equal(raw, images[index][b:d,a:c]))
                    self.assertTrue((raw[y-b:y+12-b,x-a] == 0).all())
                    self.assertIn(p['obs_id'], e['obs_ids'])
                    self.assertEqual(p['t_sec'], index*.25)
                    found.append((rec,e))
        self.assertTrue(found, f'no exact raw hypothesis for member {index} at x={x}')
        return found

    def test_left_edge_unsampled_stroke_retained_through_tracking_occurrences_strip(self):
        self.edge_case(10)

    def test_right_edge_unsampled_stroke_retained_through_tracking_occurrences_strip(self):
        self.edge_case(790)

    def edge_case(self, x):
        images = [paper() for _ in range(40)]
        _,_,baseline = self.run_path(images)
        images[1][110:122,x] = 0
        manifest,_,records = self.run_path(images)
        self.assertEqual(len(records), 1)
        self.assertTrue(np.array_equal(records[0][1], baseline[0][1]))
        matches = self.assert_raw_stroke(records, images, 1, x)
        rec,e = matches[0]
        self.assertEqual(e['disposition'], 'OUTSIDE_PROPOSED_CROP_KEPT')
        self.assertEqual(e['eligible'], 40)
        self.assertEqual(rec['minority_content']['full_roi_inventory']['checked_members'], 40)
        self.assertNotIn(manifest['observations'][1]['id'], rec['member_obs_ids'])

    def test_fade_member_is_bundled_but_excluded_from_composition_and_denominator(self):
        images = [paper() for _ in range(12)]
        _,_,baseline = self.run_path(images)
        images[5][110:122,420] = 0
        images[5] = (images[5].astype(float)*.7).astype(np.uint8)
        _,_,records = self.run_path(images)
        self.assertEqual(len(records), 1)
        self.assertTrue(np.array_equal(records[0][1], baseline[0][1]))
        rec,e = self.assert_raw_stroke(records, images, 5, 420)[0]
        self.assertEqual(e['eligible'], 11)
        self.assertEqual(e['eligibility'], ['INELIGIBLE_FADE'])
        self.assertEqual(rec['members_used'], 11)
        self.assertEqual(rec['minority_content']['checked_members'], 11)
        self.assertEqual(rec['minority_content']['skipped_members'], 1)

    def test_shifted_member_attempts_local_registration_but_retains_original_raw_stroke(self):
        images = [paper() for _ in range(12)]
        _,_,baseline = self.run_path(images)
        images[5] = np.roll(images[5], 3, axis=1)
        images[5][110:122,420] = 0
        _,_,records = self.run_path(images)
        self.assertEqual(len(records), 1)
        self.assertTrue(np.array_equal(records[0][1], baseline[0][1]))
        rec,e = self.assert_raw_stroke(records, images, 5, 420)[0]
        self.assertEqual(e['eligible'], 11)
        self.assertEqual(e['eligibility'], ['INELIGIBLE_REGISTRATION'])
        self.assertTrue(e['local_registration'][0]['registered'])
        self.assertEqual(e['local_registration'][0]['attempted_shift_px'], [-3,0])
        self.assertEqual(rec['members_used'], 11)

    def test_normal_persistent_mark_unchanged_and_without_uncertainty(self):
        images = [paper() for _ in range(12)]
        for im in images:
            im[110:122,420] = 0
        _,_,records = self.run_path(images)
        self.assertEqual(len(records),1)
        _,primary,rec = records[0]
        x,y=rec['box_crop'][:2]
        self.assertTrue((primary[110-y:122-y,420-x] == 0).all())
        self.assertEqual(rec['minority_content']['events'], [])
        self.assertEqual(rec['minority_content']['alternates'], [])

    def test_fade_without_new_foreground_does_not_create_uncertainty(self):
        images=[paper() for _ in range(12)]
        images[5]=(images[5].astype(float)*.7).astype(np.uint8)
        _,_,records=self.run_path(images)
        self.assertEqual(records[0][2]['minority_content']['events'], [])
        self.assertEqual(records[0][2]['members_used'],11)
        self.assertTrue(records[0][2]['minority_content']['rejected_observations'][0]['raw_png_base64'])

    def test_rejected_member_staff_proximity_does_not_explain_a_new_thin_stroke(self):
        for rejected in ('fade', 'shift'):
            with self.subTest(rejected=rejected):
                images=[paper() for _ in range(12)]
                if rejected=='shift':
                    images[5]=np.roll(images[5],3,axis=1)
                images[5][63,420:432]=0
                if rejected=='fade':
                    images[5]=(images[5].astype(float)*.7).astype(np.uint8)
                _,_,records=self.run_path(images)
                rec=records[0][2]
                self.assertTrue(any(any(y==63 and a<=420 and b>=432 for y,a,b in o['spans_crop'])
                    for e in rec['minority_content']['events'] for o in e['foreground_support']))
                self.assertIn(rs.UNCERTAIN_MARK_KEPT,rec['issues'])

    def test_external_two_pixel_speckle_is_counted(self):
        images=[paper() for _ in range(40)];images[1][110:112,10]=0
        _,_,records=self.run_path(images)
        m=records[0][2]['minority_content']
        self.assertEqual(m['events'],[])
        self.assertGreaterEqual(m['full_roi_inventory']['speckle_dropped'],1)

    def test_external_evidence_persists_with_exact_png_hash(self):
        import hashlib
        images=[paper() for _ in range(40)];images[1][110:122,790]=0
        system,manifest,load=system_case(images)
        with tempfile.TemporaryDirectory() as d:
            rec=rs.build_strips({'systems':[system]},manifest,load,Path(d))[0]
            patch=rec['minority_content']['alternates'][0]['evidence_patches'][0]
            path=Path(patch['raw_path'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),patch['raw_png_sha256'])
            a,b,c,d=patch['box_crop']
            self.assertTrue(np.array_equal(cv2.imread(str(path)),images[1][b:d,a:c]))

    def test_row_boundary_crossing_is_recorded_as_unresolved_ownership(self):
        im=np.full((260,800,3),255,np.uint8)
        im[:160]=paper()
        for y in (170,182,194,206,218):
            cv2.line(im,(20,y),(780,y),(0,0,0),1)
        im[125:145,10]=0
        system,manifest,load=system_case([im.copy() for _ in range(3)])
        for obs in manifest['observations']:
            self.assertEqual(len(obs['system_regions']),2)
        inventory=rs.inventory_before_crop(system,[20,0,786,134],
            {o['id']:o for o in manifest['observations']},load,12)
        events=[e for e in inventory['events'] if e['box_crop'][0]==10]
        self.assertTrue(events)
        self.assertTrue(all(e['disposition']=='ROW_OWNERSHIP_UNRESOLVED' for e in events))
        self.assertEqual(events[0]['box_crop'],[10,125,11,145])


if __name__ == '__main__':
    unittest.main()
