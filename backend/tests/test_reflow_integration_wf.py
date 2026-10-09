"""Direct-compose clipping and raw self-check integration regressions."""
import unittest
from unittest.mock import patch

import numpy as np

from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_pipeline as rp
from reflow_fixture import build, loader, show, strip


class RawSelfCheckIntegrationTest(unittest.TestCase):
    def test_self_checks_receive_raw_episode_and_midpoint_windows(self):
        manifest, images = build(show(strip(4), 0, 4, seed=1))
        load = loader(images)
        from app.pipeline import system_tracking as st
        tracking = st.build_episodes(manifest, load)
        seen = []
        original_checks = ro._self_checks
        original_raw = ro._raw_window_of

        def checks(*args):
            with_alts, _systems, _roots, *_rest = args
            ep_window, rep_window = args[-3:-1]
            for candidate, _included in with_alts:
                main = candidate['main']
                mid = len(main['observation_ids']) // 2
                obs_by = {o['id']: o for o in manifest['observations']}
                expected = original_raw(obs_by, load, main['observation_ids'][mid], main['region_ids'][mid])
                np.testing.assert_array_equal(rep_window(candidate)[0], expected[0])
                expected_first = original_raw(obs_by, load, main['observation_ids'][0], main['region_ids'][0])
                np.testing.assert_array_equal(ep_window(main, 'first')[0], expected_first[0])
                seen.append(main['id'])
            return original_checks(*args)

        # Make the cleaned-window path visibly different. All other consumers keep that path.
        original_clean = ro._window_of
        def cleaned(*args):
            win, extent, gap, region = original_clean(*args)
            return np.full_like(win, 255), extent, gap, region

        with patch.object(ro, '_window_of', side_effect=cleaned), patch.object(ro, '_self_checks', side_effect=checks):
            ro.build_occurrences(tracking, manifest, load)
        self.assertTrue(seen)


class DirectComposeHeaderTest(unittest.TestCase):
    def test_source_clipping_reaches_both_compose_branches_without_duplicate_entries(self):
        system = {'id': 's', 'issues': ['SOURCE_CLIPPED'], 'source_clipped': {'sides': ['left'], 'columns': [0, 10]}}
        clipped = [{'system_id': 's', 'sides': ['left'], 'columns': [0, 10]}]
        for measure in (False, True):
            header = {'title': 'T', 'source_clipped': clipped}
            with patch.object(rp, 'resolve_dependencies', return_value=([{'system': system, 'strip_path': 'unused.png', 'label': None, 'variant': 'strip'}], {})):
                if measure:
                    target = 'app.pipeline.reflow_measure.compose'
                    result = ({'measure_reflow': {}, 'pages': []}, [])
                else:
                    target = 'app.pipeline.reflow_pipeline._compose_whole_systems'
                    result = ({'pages': []}, [])
                with patch(target, return_value=result) as compose, patch('cv2.imread', return_value=np.full((10, 10, 3), 255, np.uint8)):
                    # Whole-system preparation requires a strip path/record.
                    system.update(strip_path='unused.png', strip={'system_id': 's', 'staff_gap_px': 10, 'size': [10, 10]})
                    rp.compose_systems([system], header=header, measure_reflow=measure, measure_context={})
                self.assertEqual(compose.call_args.kwargs['header']['source_clipped'], clipped)
                self.assertEqual(header, {'title': 'T', 'source_clipped': clipped})
