"""Size-floor exceptions preserve pixels and retain all non-crossing locks."""
import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_measure as rm
from app.pipeline import reflow_units as ru
from app.pipeline import reflow_verify_plan as vb
from test_reflow_measure import Doc, measure_strip, observations


class SizeFloor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.doc = Doc(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def wide(self):
        img, rec = measure_strip(2, clef=False)
        img = cv2.resize(img, (img.shape[1] * 5, img.shape[0]), interpolation=cv2.INTER_NEAREST)
        rec.update(staff_x_strip=[x * 5 for x in rec['staff_x_strip']],
                   box_crop=[0, 0, img.shape[1], img.shape[0]], size=[img.shape[1], img.shape[0]],
                   jump={'no_clef_copy': True})
        # Crossing ink is deliberately kept at the seam.
        cv2.line(img, (1600, 195), (2400, 195), (25, 25, 25), 1)
        s = self.doc.add('wide', img, rec, register=False)
        s['layout'] = 'jump_view'
        return s

    def compose_wide(self, reasons, classification=rb.LOCKED, **kw):
        original = rb.strip_boundaries
        def boundaries(an, **args):
            out = original(an, **args)
            for b in out:
                if b['kind'] == 'barline':
                    b['class'] = classification
                    b['reason_codes'] = reasons
            return out
        with patch.object(rb, 'strip_boundaries', side_effect=boundaries):
            return self.doc.compose(measure_reflow=True, staff_gap_mm=1.3, **kw)

    def classified_crossing(self, kind, *, width=3600):
        """Real strip analysis/registration/classification; never inject reason codes."""
        img = np.full((250, width, 3), 252, np.uint8)
        ink = (25, 25, 25)
        lines = [92 + 16 * i for i in range(5)]
        for y in lines:
            cv2.line(img, (20, y), (width - 20, y), ink, 1, cv2.LINE_AA)
        bar = width // 2
        for x in (bar, width - 20):
            cv2.rectangle(img, (x, lines[0]), (x + 1, lines[-1]), ink, -1)
        # Measure content away from the seam, preserving a genuine two-measure unit.
        for x in (bar // 2, bar + bar // 2):
            cv2.ellipse(img, (x, 132), (7, 5), -20, 0, 360, ink, -1, cv2.LINE_AA)
            cv2.line(img, (x + 7, 132), (x + 7, 60), ink, 1, cv2.LINE_AA)
        if kind in ('extension', 'extension_nearby_beam'):
            cv2.line(img, (bar - 200, 190), (bar + 250, 202), ink, 1, cv2.LINE_AA)
            if kind == 'extension_nearby_beam':
                # A beam tip 8 px RIGHT of the proposed seam does not cross it.
                # Regression for the real _7gP seam's nearby next-measure notes.
                cv2.rectangle(img, (bar + 43, 60), (bar + 300, 63), ink, -1)
                for x in (bar + 80, bar + 300):
                    cv2.line(img, (x, 60), (x, 132), ink, 1, cv2.LINE_AA)
                    cv2.ellipse(img, (x - 7, 132), (7, 5), 0, 0, 360, ink, -1, cv2.LINE_AA)
        elif kind == 'broken_extension':
            cv2.line(img, (bar - 200, 190), (bar + 30, 196), ink, 1, cv2.LINE_AA)
            cv2.line(img, (bar + 40, 196), (bar + 250, 202), ink, 1, cv2.LINE_AA)
        elif kind == 'hairpin':
            for y in (194, 198):
                cv2.line(img, (bar - 200, y), (bar + 250, 196), ink, 1)
        elif kind == 'tie':
            cv2.ellipse(img, (bar, 184), (150, 8), 0, 0, 180, ink, 1, cv2.LINE_AA)
        elif kind == 'beam':
            for x in (bar - 80, bar + 90):
                cv2.ellipse(img, (x, 132), (7, 5), -20, 0, 360, ink, -1, cv2.LINE_AA)
                cv2.line(img, (x + 7, 132), (x + 7, 60), ink, 1, cv2.LINE_AA)
            cv2.rectangle(img, (bar - 73, 60), (bar + 97, 63), ink, -1)
        elif kind == 'text':
            # Separate letters with whitespace at the seam, but within the real
            # classifier's text-group reach. TEXT_GROUP alone must not authorize it.
            for i, letter in enumerate('crescendo'):
                cv2.putText(img, letter, (bar - 56 + 24 * i, 209), cv2.FONT_HERSHEY_SIMPLEX,
                            0.65, ink, 1, cv2.LINE_AA)
        elif kind == 'blob':
            cv2.line(img, (bar - 200, 195), (bar + 250, 195), ink, 1)
            cv2.ellipse(img, (bar - 90, 195), (7, 5), 0, 0, 360, ink, -1)
        elif kind == 'stem':
            cv2.line(img, (bar - 200, 195), (bar + 250, 195), ink, 1)
            cv2.line(img, (bar - 90, 195), (bar - 90, 208), ink, 1)
        else:
            raise ValueError(kind)
        rec = {'staff_y_strip': lines, 'staff_gap_px': 16., 'staff_x_strip': [20, width - 20],
               'box_crop': [0, 0, width, 250], 'size': [width, 250], 'issues': [],
               'envelope_flags': [], 'jump': {'no_clef_copy': True}}
        s = self.doc.add('crossing', img, rec)
        s['layout'] = 'jump_view'
        s['strip']['jump']['members'] = [
            {'obs_id': o['id'], 'region_id': o['system_regions'][0]['region_id'], 'offset_x': 0}
            for o in self.doc.obs]
        return s

    def assert_real_forced(self, kind):
        self.classified_crossing(kind)
        plan, pages = self.doc.compose(measure_reflow=True, staff_gap_mm=1.3)
        m = plan['measure_reflow']
        self.assertEqual(m['status'], 'measure_lines', m)
        self.assertEqual(len(m.get('forced_breaks', [])), 1, m.get('boundaries'))
        evidence = m['forced_breaks'][0]['evidence']
        self.assertTrue(evidence['verified'])
        self.assertTrue(all(c['thin_stroke'] for c in evidence['components']))
        self.assertFalse(m['oversize_units'])
        self.assertTrue(m['audit']['native_accounting']['exact_reconstruction'])
        self.assertEqual(m['audit']['render_mismatched_px'], 0)
        self.assertTrue(pages)

    def test_real_classifier_extension_crossing_allowed(self):
        self.assert_real_forced('extension')

    def test_real_classifier_nearby_non_crossing_beam_does_not_veto_stroke(self):
        self.assert_real_forced('extension_nearby_beam')

    def test_real_classifier_broken_extension_crossing_allowed(self):
        self.assert_real_forced('broken_extension')

    def test_real_classifier_hairpin_crossing_allowed(self):
        self.assert_real_forced('hairpin')

    def test_real_classifier_tie_crossing_allowed(self):
        self.assert_real_forced('tie')

    def assert_real_refused(self, kind, check):
        s = self.classified_crossing(kind)
        plan, pages = self.doc.compose(measure_reflow=True, staff_gap_mm=1.3)
        m = plan['measure_reflow']
        self.assertEqual(m['status'], 'measure_lines', m)
        self.assertNotIn('forced_breaks', m)
        b = m['boundaries'][0]
        # The reproduced bug: reason whitelist alone would authorize this seam.
        self.assertTrue(ru._floor_break_reason_filter(dict(b, kind='barline')), b)
        evidence = b['floor_break_evidence']
        self.assertFalse(evidence['verified'])
        self.assertTrue(any(not c['checks'][check] for c in evidence['components']), evidence)
        self.assertIn('LINE_BELOW_MIN_SIZE', s['issues'])
        self.assertEqual(plan['validation']['issues'][0]['code'], 'LINE_BELOW_MIN_SIZE')
        self.assertLess(plan['validation']['issues'][0]['effective_staff_gap_mm'], 1.2)
        self.assertTrue(pages)

    def test_real_classifier_beam_with_stems_crossing_refused(self):
        self.assert_real_refused('beam', 'low_height')

    def test_real_classifier_word_crossing_refused(self):
        self.assert_real_refused('text', 'long_stroke')

    def test_real_classifier_notehead_on_thin_line_refused(self):
        self.assert_real_refused('blob', 'no_filled_blob')

    def test_real_classifier_remote_vertical_stem_refused(self):
        self.assert_real_refused('stem', 'no_stem')

    def test_crossing_only_forced_break_keeps_every_pixel(self):
        s = self.wide()
        plan, pages = self.compose_wide(['TIE_SLUR_OR_LINE_CROSSES', 'TEXT_GROUP_CROSSES'])
        m = plan['measure_reflow']
        self.assertEqual(m['status'], 'measure_lines', m)
        self.assertEqual(len(m['forced_breaks']), 1)
        self.assertFalse(m['oversize_units'])
        self.assertIn('FORCED_LINE_BREAK', s['issues'])
        b = next(b for b in m['boundaries'] if b['id'] == m['forced_breaks'][0]['boundary_id'])
        self.assertEqual(b['class'], rb.LOCKED)
        self.assertTrue(b['is_cut'])
        account = m['audit']['native_accounting']
        self.assertTrue(account['exact_reconstruction'])
        for key in ('lost_px', 'duplicated_px', 'mismatched_px', 'protected_lost_px', 'protected_duplicated_px'):
            self.assertEqual(account[key], 0)
        self.assertEqual(m['audit']['render_mismatched_px'], 0)
        self.assertTrue(pages)
        self.assertNotIn('issues', plan['validation'])

    def test_unknown_crossing_only_also_eligible(self):
        self.wide()
        plan, _ = self.compose_wide(['POSSIBLE_BROKEN_STROKE'], rb.UNKNOWN)
        self.assertEqual(len(plan['measure_reflow']['forced_breaks']), 1)

    def test_other_blocker_never_forced_and_small_output_reported(self):
        for blocker in ('USER_LOCK', 'REPEAT_BOUNDARY', 'CUTS_BARLINE_OR_REPEAT_GROUP',
                        'INSUFFICIENT_CLEARANCE', 'MINORITY_CONTENT', 'OUTSIDE_STAFF', 'NEW_UNKNOWN_REASON'):
            with self.subTest(blocker=blocker):
                if not self.doc.systems:
                    s = self.wide()
                plan, pages = self.compose_wide(['TIE_SLUR_OR_LINE_CROSSES', blocker])
                self.assertNotIn('forced_breaks', plan['measure_reflow'])
                findings = plan['validation']['issues']
                self.assertEqual(findings[0]['code'], 'LINE_BELOW_MIN_SIZE')
                self.assertLess(findings[0]['effective_staff_gap_mm'], 1.2)
                self.assertTrue(plan['validation']['valid'])  # retained output stays exportable
                self.assertTrue(plan['validation']['review_required'])
                self.assertIn('LINE_BELOW_MIN_SIZE', s['issues'])
                self.assertTrue(pages)

    def test_no_eligible_seam(self):
        s = self.wide()
        plan, _ = self.compose_wide(['NO_REGISTRATION_CONTEXT'], rb.UNKNOWN)
        self.assertNotIn('forced_breaks', plan['measure_reflow'])
        self.assertIn('LINE_BELOW_MIN_SIZE', s['issues'])
        self.assertTrue(plan['measure_reflow']['audit']['validation']['review_required'])

    def test_keep_together_unit_never_split(self):
        self.wide()
        plan, _ = self.compose_wide(['TIE_SLUR_OR_LINE_CROSSES'],
                                   measure_locks=[{'type': 'keep_together', 'targets': ['wide/u0', 'wide/u0']}])
        self.assertNotIn('forced_breaks', plan['measure_reflow'])
        self.assertTrue(plan['validation']['review_required'])

    def test_no_oversize_plan_and_pages_unchanged(self):
        img, rec = measure_strip(4)
        self.doc.add('normal', img, rec)
        a, pa = self.doc.compose(measure_reflow=True)
        with patch.object(rm, '_floor_breaks', return_value=[]):
            b, pb = self.doc.compose(measure_reflow=True)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertTrue(all(np.array_equal(x, y) for x, y in zip(pa, pb)))
        self.assertNotIn('forced_breaks', a['measure_reflow'])
        self.assertNotIn('issues', a['validation'])

    def test_real_classifier_nonoversize_crossing_plan_and_pages_unchanged(self):
        self.classified_crossing('beam', width=1800)
        a, pa = self.doc.compose(measure_reflow=True, staff_gap_mm=1.3)
        with patch.object(ru, 'floor_break_evidence', side_effect=AssertionError('nonoversize geometry invoked')):
            b, pb = self.doc.compose(measure_reflow=True, staff_gap_mm=1.3)
        self.assertEqual(a['measure_reflow']['status'], 'measure_lines')
        self.assertFalse(a['measure_reflow']['oversize_units'])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(len(pa), len(pb))
        self.assertTrue(all(np.array_equal(x, y) for x, y in zip(pa, pb)))
        self.assertTrue(all('floor_break_evidence' not in b for b in a['measure_reflow']['boundaries']))

    def test_whole_system_fallback_below_floor_and_clears_on_resize(self):
        img, rec = measure_strip(2)
        s = self.doc.add('fallback', img, rec, register=False)
        with patch.object(rm, 'compose', side_effect=rm.MeasurePlanUnavailable('TEST_FALLBACK')):
            plan, pages = self.doc.compose(measure_reflow=True, staff_gap_mm=1.0)
        self.assertEqual(plan['measure_reflow']['status'], 'fallback_whole_systems')
        self.assertAlmostEqual(plan['validation']['issues'][0]['effective_staff_gap_mm'], 1.0)
        self.assertIn('LINE_BELOW_MIN_SIZE', s['issues'])
        self.assertTrue(pages)
        plan, _ = self.doc.compose(staff_gap_mm=1.3)
        self.assertNotIn('LINE_BELOW_MIN_SIZE', s['issues'])
        self.assertNotIn('issues', plan['validation'])

    def test_minimum_cuts_prefer_full_scale(self):
        # Three eligible seams, but only the middle seam is needed to make full-size pieces.
        img = np.full((250, 3600, 3), 252, np.uint8)
        ink = (25, 25, 25)
        lines = [92 + 16 * i for i in range(5)]
        for y in lines:
            cv2.line(img, (20, y), (3580, y), ink, 1, cv2.LINE_AA)
        for x in (965, 1765, 2565, 3580):
            cv2.rectangle(img, (x, lines[0]), (x + 1, lines[-1]), ink, -1)
        cv2.line(img, (100, 190), (3500, 202), ink, 1, cv2.LINE_AA)
        rec = {'staff_y_strip': lines, 'staff_gap_px': 16., 'staff_x_strip': [20, 3580],
               'box_crop': [0, 0, 3600, 250], 'layout': 'jump_view'}
        an = rb.analyse_strip(img, rec, system_id='s',
                              observations=[o['system_regions'][0] for o in observations(img, 's')])
        boundaries = rb.strip_boundaries(an)
        self.assertEqual([b['seam_x'] for b in boundaries], [1000, 1800, 2600])
        built = {'doc': {'measure_units': [{'id': 'u'}], 'boundaries': boundaries},
                 'analyses': {'s': an},
                 'atoms': [{'id': 'u', 'unit_id': 'u', 'system_id': 's', 'strip_key': 'small',
                            'break_before': 'system_start', 'oversize': {'native_cols': [0, 3600]}}],
                 'strips': {'s': {'scale': 1., 'prefix_free': True, 'record': {}, 'replica': None},
                            'small': {'scale': .55}}}
        self.assertEqual(rm._floor_breaks(built, 1.3, 2117, []), [boundaries[1]['id']])

    def test_empty_or_foreign_reason_cannot_authorize_floor_cut(self):
        b = {'kind': 'barline', 'class': rb.UNKNOWN, 'reason_codes': []}
        self.assertFalse(ru.floor_break_eligible(b))
        b.update(reason_codes=['TEXT_GROUP_CROSSES'], kind='preview_tail')
        self.assertFalse(ru.floor_break_eligible(b))
        b.update(kind='barline')
        self.assertFalse(ru.floor_break_eligible(b))  # a whitelist without pixel evidence is insufficient

    def test_independent_verifier_requires_matching_explicit_authorization(self):
        s = self.wide()
        evidence = ru.floor_break_evidence(rb.analyse_strip(cv2.imread(s['strip_path']), s['strip']), 2000)
        b = {'id': 'b', 'system_id': 's', 'class': rb.LOCKED,
             'seam_x': 2000, 'reason_codes': ['TEXT_GROUP_CROSSES'], 'floor_break_evidence': evidence}
        record = {'boundary_id': 'b', 'system_id': 's', 'reasons': ['TEXT_GROUP_CROSSES'], 'evidence': evidence}
        self.assertTrue(vb._authorized_floor_break(b, [record]))
        self.assertFalse(vb._authorized_floor_break(b, []))
        for change in ({'system_id': 'foreign'}, {'boundary_id': 'foreign'}, {'reasons': []},
                       {'evidence': {}}, {'evidence': dict(evidence, verified=False)}):
            self.assertFalse(vb._authorized_floor_break(b, [dict(record, **change)]))
        self.assertFalse(vb._authorized_floor_break(dict(b, reason_codes=['TEXT_GROUP_CROSSES', 'USER_LOCK']),
                                                    [dict(record, reasons=['TEXT_GROUP_CROSSES', 'USER_LOCK'])]))
        self.assertFalse(vb._authorized_floor_break(dict(b, floor_break_evidence={}), [record]))
        tampered = copy.deepcopy(evidence)
        tampered['components'][0]['max_vertical_run_px'] = 100
        self.assertFalse(vb._authorized_floor_break(dict(b, floor_break_evidence=tampered),
                                                    [dict(record, evidence=tampered)]))
        plain = vb.plan_records({'measure_reflow': {}}, {})
        self.assertNotIn('forced_breaks', plain)
        changed = vb.plan_records({'measure_reflow': {'forced_breaks': [record]}}, {})
        self.assertEqual(changed['forced_breaks'], [record])

    def test_review_copy_includes_actual_size_and_job_review_flag(self):
        from app import main
        s = {'id': 'small', 'strip_path': 'small.png', 'issues': ['LINE_BELOW_MIN_SIZE'],
             'effective_staff_gap_mm': .816845}
        result = main._reflow_capture_fields({'systems': [s]})
        self.assertTrue(result['review_required'])
        texts = result['capture_diagnostics']['small.png']['warning_reasons']
        self.assertTrue(any('0.817 mm' in t for t in texts))
        self.assertNotIn('{mm}', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
