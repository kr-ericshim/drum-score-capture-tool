"""Stationary footage needs independent systems and a raw all-member notation veto."""
import copy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_strips as rs


def fixture(count=4, identical=False, inverted=True):
    observations, systems, images = [], [], {}
    for i in range(count):
        members = []
        for j in range(3):
            raw = np.zeros((120, 240, 3), np.uint8)
            # Soft textured stationary gray hardware, above a varying score.
            yy, xx = np.mgrid[:20, :60]
            blob = (155 + 8 * np.sin(xx / 6) + 4 * np.cos(yy / 4)).astype(np.uint8)
            raw[20:40, 100:160] = blob[..., None]
            for y in (60, 70, 80, 90, 100):
                cv2.line(raw, (5, y), (230, y), (255, 255, 255), 1)
            # Recurrent clef, barline, time signature and notehead are notation.
            cv2.rectangle(raw, (10, 70), (13, 90), (255, 255, 255), -1)
            cv2.rectangle(raw, (18, 70), (21, 90), (255, 255, 255), -1)
            cv2.line(raw, (45, 60), (45, 100), (255, 255, 255), 1)
            cv2.putText(raw, '4', (28, 73), cv2.FONT_HERSHEY_SIMPLEX, .4, (255, 255, 255), 1)
            cv2.ellipse(raw, (120, 80), (5, 3), 0, 0, 360, (255, 255, 255), -1)
            cv2.circle(raw, (70 + (0 if identical else 30 * i), 51), 4, (255, 255, 255), -1)
            # White singleton at the very place the footage otherwise occupies.
            if i == 1 and j == 2:
                cv2.circle(raw, (132, 28), 2, (255, 255, 255), -1)
            if not inverted:
                raw = 255 - raw
            oid = f'obs-{i}-{j}'
            observations.append({'id': oid, 'inverted': inverted, 'system_regions': [{'staff_gap_px': 10}]})
            members.append({'obs_id': oid})
            images[oid] = raw
        systems.append({'id': f'sys-{i}', 'occurrence_root': f'ep-{i}', 'observations': members})
    return {'systems': systems}, {'observations': observations}, images


class StaticDarkBackgroundTest(unittest.TestCase):
    def evidence(self, **kw):
        occurrences, manifest, images = fixture(**kw)
        evidence = rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']])
        return evidence, occurrences, manifest, images

    def test_soft_gray_removed_white_scaffold_and_singleton_kept(self):
        evidence, _, manifest, images = self.evidence()
        self.assertGreater(evidence['mask'][20:40, 100:160].sum(), 800)
        self.assertFalse(evidence['mask'][26:31, 130:135].any())
        self.assertFalse(evidence['mask'][60:101].any())
        self.assertLess(evidence['info']['max_member_brightness'], rs.DARK_BG_NOTATION_MIN)
        for image in images.values():
            old, _, _, _ = rs.finish_strip(image, members=[image]*3, gap=10)
            new, inv, _, info = rs.finish_strip(image, members=[image]*3, gap=10, dark_background=evidence)
            self.assertTrue(inv)
            self.assertTrue(np.all(new[evidence['mask']] == 255))
            bright = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) >= rs.DARK_BG_NOTATION_MIN
            np.testing.assert_array_equal(new[bright], old[bright])
            self.assertEqual(info['survival']['lost'], 0)
        # The sole white mark survives final pixels, even in a single member.
        out = rs.finish_strip(images['obs-1-2'], dark_background=evidence, gap=10)[0]
        self.assertTrue(np.all(out[28, 132] == 0))

    def test_pixels_outside_evidence_mask_are_unchanged(self):
        evidence, _, _, images = self.evidence()
        for oid, image in images.items():
            with self.subTest(member=oid):
                before = image.copy()
                kwargs = dict(members=[image] * 3, gap=10,
                              staff=((60, 70, 80, 90, 100), 5, 230))
                old = rs.finish_strip(image, **kwargs)
                new = rs.finish_strip(image, dark_background=evidence, **kwargs)
                changed = np.any(old[0] != new[0], axis=2)
                self.assertGreater(changed.sum(), 0)
                self.assertFalse((changed & ~evidence['mask']).any())
                np.testing.assert_array_equal(new[0][~evidence['mask']], old[0][~evidence['mask']])
                self.assertEqual(new[1:3], old[1:3])
                self.assertTrue(new[3]['survival']['staff'])
                self.assertEqual(new[3]['dark_cleanup']['static_background']['removed_px'], int(changed.sum()))
                np.testing.assert_array_equal(image, before)

    def test_partial_blob_mask_does_not_shift_neighbouring_paper_flattening(self):
        _, _, images = fixture()
        image = images['obs-0-0'].copy()
        # A broad retained gray blob influences the background estimate. Its
        # independently witnessed subset must not alter the unmasked half or
        # surrounding paper when removed (early replacement changes 6k+ px).
        image[5:35, 80:180] = 155
        mask = np.zeros(image.shape[:2], bool)
        mask[5:35, 80:125] = True
        evidence = {'mask': mask, 'info': {}}
        kwargs = dict(members=[image] * 3, gap=10)
        old = rs.finish_strip(image, **kwargs)
        new = rs.finish_strip(image, dark_background=evidence, **kwargs)
        changed = np.any(old[0] != new[0], axis=2)
        self.assertGreater(changed.sum(), 0)
        np.testing.assert_array_equal(new[0][~mask], old[0][~mask])
        self.assertEqual(new[1:3], old[1:3])

    def test_replacement_uses_finished_paper_and_preserves_flattening_input(self):
        evidence, _, _, images = self.evidence()
        image = images['obs-0-0']
        real_flatten = rs.flatten_paper_background
        inputs = []

        def flatten(norm):
            inputs.append(norm.copy())
            out = real_flatten(norm)
            out = norm.copy() if out is None else out.copy()
            out[np.all(out == 255, axis=2)] = 247
            return out

        with patch.object(rs, 'flatten_paper_background', side_effect=flatten):
            old = rs.finish_strip(image, members=[image] * 3, gap=10)
            new = rs.finish_strip(image, members=[image] * 3, gap=10, dark_background=evidence)
        np.testing.assert_array_equal(inputs[0], inputs[1])
        np.testing.assert_array_equal(new[0][~evidence['mask']], old[0][~evidence['mask']])
        self.assertTrue(np.all(new[0][evidence['mask']] == 247))
        self.assertEqual(new[3]['dark_cleanup']['static_background']['paper'], 247)

    def test_composite_only_white_mark_vetoes_replacement(self):
        evidence, _, _, images = self.evidence()
        image = images['obs-0-0'].copy()
        # Restored minority notation may be absent from the job's raw mask.
        image[30, 110] = 255
        old = rs.finish_strip(image, gap=10)[0]
        new = rs.finish_strip(image, gap=10, dark_background=evidence)[0]
        np.testing.assert_array_equal(new[28:33, 108:113], old[28:33, 108:113])
        self.assertTrue(np.all(new[30, 110] == 0))

    def test_wrong_shape_evidence_keeps_finished_pixels_and_records(self):
        _, _, _, images = self.evidence()
        image = images['obs-0-0']
        old = rs.finish_strip(image, gap=10)
        new = rs.finish_strip(image, gap=10,
                              dark_background={'mask': np.ones((2, 3), bool), 'info': {}})
        np.testing.assert_array_equal(new[0], old[0])
        self.assertEqual(new[1:], old[1:])

    def test_repeated_identical_notation_is_not_independent_layer_evidence(self):
        evidence, *_ = self.evidence(identical=True)
        self.assertFalse(evidence['mask'].any())

    def test_fewer_than_three_systems_keep_everything(self):
        evidence, *_ = self.evidence(count=2)
        self.assertIsNone(evidence)

    def test_alternates_cannot_create_independent_votes(self):
        occurrences, manifest, images = fixture(count=4)
        for system in occurrences['systems']:
            system['occurrence_root'] = 'same-display'
        self.assertIsNone(rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']]))

    def test_light_jobs_do_not_read_frames_or_change_finish(self):
        occurrences, manifest, images = fixture(inverted=False)
        with patch.object(rs, 'sd') as unused:
            self.assertIsNone(rs.job_dark_background(occurrences, manifest,
                lambda obs: self.fail('light evidence must not load frames')))
            unused.normalize_polarity.assert_not_called()
        evidence = {'mask': np.ones((120, 240), bool), 'info': {}}
        image = images['obs-0-0']
        old = rs.finish_strip(image, gap=10)
        new = rs.finish_strip(image, gap=10, dark_background=evidence)
        np.testing.assert_array_equal(old[0], new[0])
        self.assertEqual(old[1:], new[1:])

    def test_all_member_veto_includes_unsampled_ledger_member(self):
        occurrences, manifest, images = fixture()
        raw = images['obs-0-0'].copy()
        cv2.circle(raw, (110, 30), 2, (255, 255, 255), -1)
        images['raw-extra'] = raw
        manifest['observations'].append({'id': 'raw-extra', 'inverted': True})
        system = occurrences['systems'][0]
        system['ledger_observations'] = system['observations'] + [{'obs_id': 'raw-extra'}]
        evidence = rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']])
        self.assertFalse(evidence['mask'][28:33, 108:113].any())

    def test_sharp_gray_stroke_kept_and_missing_shape_fails_closed(self):
        occurrences, manifest, images = fixture()
        for raw in images.values():
            raw[10:12, 100:160] = 210
        evidence = rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']])
        self.assertFalse(evidence['mask'][10:12, 100:160].any())
        images['obs-3-2'] = images['obs-3-2'][:100]
        self.assertIsNone(rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']]))

    def test_evidence_is_deterministic_and_does_not_mutate_inputs(self):
        occurrences, manifest, images = fixture()
        before = copy.deepcopy((occurrences, manifest))
        snapshots = {k: v.copy() for k,v in images.items()}
        for raw in images.values():
            raw.flags.writeable = False
        first = rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']])
        second = rs.job_dark_background(occurrences, manifest, lambda obs: images[obs['id']])
        np.testing.assert_array_equal(first['mask'], second['mask'])
        self.assertEqual(first['info'], second['info'])
        self.assertFalse(first['mask'].flags.writeable)
        self.assertEqual(before, (occurrences, manifest))
        for key, image in images.items():
            np.testing.assert_array_equal(image, snapshots[key])


if __name__ == '__main__':
    unittest.main()
