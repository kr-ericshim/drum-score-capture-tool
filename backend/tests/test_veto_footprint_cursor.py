"""Step 2D-1a: measured cursor underlays and conservative touched footprints."""
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import minority_content as mc, reflow_boundaries as rb
from test_reflow_boundaries import make_strip, analyse
import test_reflow_visibility_bundles as legacy_cursor


class CursorRecoveryTest(unittest.TestCase):
    @staticmethod
    def case():
        return legacy_cursor.PositiveIdentificationTest().case(True)

    def recover(self, residuals=(.3,.3), *, args=None, **kwargs):
        with patch.object(mc,'_cursor_residual_registration',side_effect=residuals):
            return mc.recovered_cursor_event(*(args or self.case()),12,**kwargs)

    def test_two_clear_positions_with_point_three_residual_recover(self):
        result = self.recover()
        self.assertEqual(result['witnesses'],[
            {'member':0,'cursor_x':20.5,'residual_registration_px':.3},
            {'member':2,'cursor_x':180.5,'residual_registration_px':.3}])
        self.assertEqual(result['_recovered_mask'].dtype,np.dtype(bool))
        np.testing.assert_array_equal(result['_recovered_mask'],self.case()[1][1])

    def test_one_point_seven_residual_leaves_only_one_witness(self):
        self.assertIsNone(self.recover((.7,.3)))

    def test_same_cursor_position_cannot_supply_two_witnesses(self):
        args = self.case()
        args[-1][2] = args[-1][0]
        self.assertIsNone(self.recover(args=args))

    def test_positions_only_one_pixel_apart_cannot_supply_two_witnesses(self):
        args = self.case()
        args[-1][2] = args[-1][0]+1
        self.assertIsNone(self.recover(args=args))

    def test_single_witness_dot_is_left_open_by_partial_recovery(self):
        args = self.case()
        args[3][45:48,100:103] = 255
        args[2][2][45:48,100:103] = 255
        result = self.recover(args=args,allow_partial=True)
        self.assertTrue(result['partial'])
        self.assertTrue(result['_recovered_mask'].any())
        self.assertFalse(result['_recovered_mask'][44:49,100:102].any())
        self.assertTrue(result['_recovered_mask'][20:43,100:102].all())
        self.assertFalse(np.any(result['_recovered_mask'] & ~args[1][1]))
        self.assertIsNone(self.recover(args=args,allow_partial=False))

    def test_per_pixel_support_requires_distinct_positions(self):
        args = self.case()
        # Two witnesses at x=20 agree on blank; the x=180 witness alone
        # sees additional lost ink there. Global distinctness is insufficient.
        args[2][3] = args[2][0].copy()
        args[1][3] = np.zeros_like(args[1][1])
        args[-1][3] = args[-1][0]
        args[3][45:48,100:103] = 255
        args[2][0][45:48,100:103] = 255
        args[2][3][45:48,100:103] = 255
        result = self.recover((.3,.3,.3),args=args,allow_partial=True)
        self.assertTrue(result['partial'])
        self.assertFalse(result['_recovered_mask'][45:48,100:102].any())

    def test_composite_dot_also_requires_two_ink_witnesses(self):
        args = self.case()
        args[2][2][45:48,100:103] = 255
        result = self.recover(args=args,allow_partial=True)
        self.assertTrue(result['partial'])
        self.assertFalse(result['_recovered_mask'][44:49,100:102].any())
        self.assertIsNone(self.recover(args=args))

    def test_work_residual_is_divided_by_manifest_work_scale(self):
        self.assertIsNone(self.recover(native_scale=.5))
        result = self.recover((.7,.7),native_scale=2.0)
        self.assertEqual([w['residual_registration_px'] for w in result['witnesses']],[.35,.35])

    def test_residual_limit_is_inclusive_and_configurable(self):
        self.assertIsNotNone(self.recover((.5,.5)))
        self.assertIsNone(self.recover((.5001,.3)))
        self.assertIsNotNone(self.recover((.7,.7),max_residual_px=.8))

    def test_default_legacy_fields_equal_existing_fixture(self):
        args = self.case()
        # Isolate legacy event fields from the new texture qualification rule.
        result = self.recover((0,0),args=args)
        mask = result.pop('_recovered_mask')
        result.pop('witnesses')
        self.assertEqual(result,{
            'kind':'monotonic_colored_cursor_with_clear_score_recovery',
            'covered_members':[1],'clear_members':[0,2],'template_members':[0,1,2],
            'template_outlier_drop':30.0,'source_ink_contrast':60,'ink_ceiling':None,
            'color_template_checked':False,'color_feature':'RGB_minus_mean',
            'color_noise_floor':15,'color_mad_multiple':3,'gray_backdrop_adjusted':True,
            'score_registration_tolerance_px':1,'recovery_scope':'own_component_footprint',
            'positions':[[0,20.5],[1,100.5],[2,180.5]]})
        np.testing.assert_array_equal(mask,args[1][1])
        json.dumps(result)

    def test_real_ssd_accepts_aligned_and_rejects_shifted_neighbourhood(self):
        args = self.case()
        # Shared texture outside the cursor gives a well-conditioned local fit.
        rng = np.random.default_rng(8)
        texture = rng.integers(205,256,args[3].shape,dtype=np.uint8)
        for y in (15,32,62,85):
            cv2.line(texture,(5,y),(234,y),25,1,cv2.LINE_AA)
        for gray in args[2].values():
            paper = gray==255
            gray[paper] = texture[paper]
        args[3][args[3]==255] = texture[args[3]==255]
        aligned = mc.recovered_cursor_event(*args,12)
        self.assertIsNotNone(aligned)
        self.assertTrue(all(w['residual_registration_px']<=.5 for w in aligned['witnesses']))
        args[2][0] = cv2.warpAffine(args[2][0],np.array([[1,0,2],[0,1,0]],np.float32),
                                  (240,100),borderValue=255)
        self.assertIsNone(mc.recovered_cursor_event(*args,12))

    def test_ssd_receives_both_masks_and_full_height_without_changing_input(self):
        args = self.case()
        args[1][0][25:28,95:98] = True
        before = {i:g.copy() for i,g in args[2].items()}
        calls = []

        def estimate(source,other,source_mask,other_mask,box,gap):
            calls.append((source_mask.copy(),other_mask.copy(),source.shape,box))
            return 0.0

        with patch.object(mc,'_cursor_residual_registration',side_effect=estimate):
            result = mc.recovered_cursor_event(*args,12)
        self.assertIsNotNone(result)
        for source_mask,other_mask,shape,box in calls:
            np.testing.assert_array_equal(source_mask,args[1][1])
            self.assertEqual(shape,(100,240))
            self.assertEqual(box,[100,20,102,80])
        self.assertTrue(calls[0][1][25:28,95:98].all())
        for i in before:
            np.testing.assert_array_equal(args[2][i],before[i])

    def test_global_shifts_use_common_reference_and_skip_local_estimator(self):
        args = self.case()
        with patch.object(mc,'_cursor_residual_registration',side_effect=AssertionError('local estimate')):
            result = mc.recovered_cursor_event(*args,12,member_shifts={0:(4.3,2),1:(4,2),2:(4,2.3)})
        self.assertEqual([v['residual_registration_px'] for v in result['witnesses']],[.3,.3])
        self.assertIsNone(mc.recovered_cursor_event(*args,12,member_shifts={0:(.7,0),1:(0,0),2:(.3,0)}))
        self.assertIsNone(mc.recovered_cursor_event(*args,12,member_shifts={0:(np.nan,0),1:(0,0),2:(.3,0)}))

    def test_global_shifts_missing_pair_falls_back_and_native_scale_applies(self):
        args = self.case()
        with patch.object(mc,'_cursor_residual_registration',return_value=.6) as estimate:
            result = mc.recovered_cursor_event(*args,12,native_scale=2,
                                               member_shifts={0:(.6,0),1:(0,0)})
        self.assertEqual(estimate.call_count,1)
        self.assertEqual([v['residual_registration_px'] for v in result['witnesses']],[.3,.3])

    def test_partial_aggregation_skips_unqualified_member_in_either_order(self):
        for members in ([1,3],[3,1]):
            args = self.case()
            args[0].update(members=members,box=[100,20,142,80])
            args[2][3] = args[3].copy()
            args[2][3][10:90,140:142] = 120
            args[1][3] = np.zeros_like(args[1][1])
            args[1][3][20:80,140:142] = True
            args[-1][3] = 140.5
            shifts = {0:(.1,0),1:(0,0),2:(.1,0),3:(1,0)}
            with self.subTest(members=members):
                result = mc.recovered_cursor_event(*args,12,allow_partial=True,member_shifts=shifts)
                self.assertTrue(result['partial'])
                self.assertEqual(result['covered_members'],[1])
                np.testing.assert_array_equal(result['_recovered_mask'],args[1][1])
                self.assertFalse(result['_recovered_mask'][args[1][3]].any())
                self.assertIsNone(mc.recovered_cursor_event(*args,12,member_shifts=shifts))


class CursorResidualEstimatorTest(unittest.TestCase):
    @staticmethod
    def texture():
        image = np.full((160,320),235,np.uint8)
        for y in (48,60,72,84,96):
            cv2.line(image,(5,y),(314,y),25,1,cv2.LINE_AA)
        for x in (34,68,99,124,151,181,213,247,278):
            cv2.ellipse(image,(x,72+(x%3)*6),(5,3),-25,0,360,20,-1,cv2.LINE_AA)
            cv2.line(image,(x+4,72+(x%3)*6),(x+4,36),20,1,cv2.LINE_AA)
        return cv2.GaussianBlur(image,(3,3),.6)

    def measure(self,source,other,source_mask=None,other_mask=None):
        empty = np.zeros(source.shape,bool)
        return mc._cursor_residual_registration(source,other,empty if source_mask is None else source_mask,
            empty if other_mask is None else other_mask,[151,20,153,130],12)

    def test_pixel_aligned_gaussian_noise_sigma_six_twenty_seeds(self):
        base = self.texture().astype(float)
        for seed in range(20):
            rng = np.random.default_rng(seed)
            a,b = [np.clip(base+rng.normal(0,6,base.shape),0,255).astype(np.uint8) for _ in range(2)]
            with self.subTest(seed=seed):
                residual = self.measure(a,b)
                self.assertIsNotNone(residual)
                self.assertLessEqual(residual,.15)

    def test_known_subpixel_warps_within_point_one(self):
        base = self.texture()
        for dx,dy in ((.3,0),(0,.7)):
            warped = cv2.warpAffine(base,np.array([[1,0,dx],[0,1,dy]],np.float32),
                (base.shape[1],base.shape[0]),flags=cv2.INTER_LINEAR,borderValue=235)
            with self.subTest(shift=(dx,dy)):
                residual = self.measure(base,warped)
                self.assertIsNotNone(residual)
                self.assertAlmostEqual(residual,np.hypot(dx,dy),delta=.1)

    def test_low_texture_is_unknown_and_does_not_qualify_as_witness(self):
        blank = np.full((160,320),235,np.uint8)
        self.assertIsNone(self.measure(blank,blank))
        # The historical cursor-only fixture has no printed registration texture.
        self.assertIsNone(mc.recovered_cursor_event(*CursorRecoveryTest.case(),12,allow_partial=True))
        with patch.object(mc,'_cursor_residual_registration',return_value=None):
            self.assertIsNone(mc.recovered_cursor_event(*CursorRecoveryTest.case(),12))

    def test_masked_pixels_cannot_bias_ssd_and_inputs_are_unchanged(self):
        base = self.texture()
        source,other = base.copy(),base.copy()
        m,n = np.zeros(base.shape,bool),np.zeros(base.shape,bool)
        m[:,145:156] = True
        n[:,170:180] = True
        source[m] = 0
        other[n] = 0
        before = [v.copy() for v in (source,other,m,n)]
        self.assertAlmostEqual(self.measure(source,other,m,n),0,delta=.01)
        for value,saved in zip((source,other,m,n),before):
            np.testing.assert_array_equal(value,saved)


class VetoFootprintTest(unittest.TestCase):
    @staticmethod
    def analysis(event, *, image=None, record=None):
        image = np.full((120,240,3),255,np.uint8) if image is None else image
        gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        ink = gray<200
        _,labels,stats,_ = cv2.connectedComponentsWithStats(ink.astype(np.uint8),connectivity=8)
        rec = {'box_crop':[10,20,250,140],'minority_content':{'events':[event]}}
        rec.update(record or {})
        return rb.StripAnalysis('test',image,rec,gray,
            {'lines':[40,52,64,76,88],'gap':12,'thick':1,'x':[20,220]},
            ink,np.zeros_like(ink),ink,ink,band=(34,95),comps=labels,comp_stats=stats)

    @staticmethod
    def event(x, y=105):
        return {'foreground_support':[{'obs_id':'own','spans_crop':[[y+20,x+10,x+11]]}]}

    def classify(self,event,**kwargs):
        an = self.analysis(event,record=kwargs.pop('record',None),image=kwargs.pop('image',None))
        return rb.classify_seam(an,120,**kwargs)

    def hits(self,result):
        return result['evidence'].get('unresolved_foreground',[])

    def test_one_pixel_outside_with_two_pixel_uncertainty_vetoes(self):
        event = self.event(123)
        event['local_registration'] = [{'obs_id':'other','attempted_shift_px':[9,0]},
                                       {'obs_id':'own','attempted_shift_px':[2,0]}]
        result = self.classify(event)
        self.assertIn('UNRESOLVED_MINORITY_CONTENT',result['reasons'])
        self.assertEqual(self.hits(result)[0],{'event':0,'obs_id':'own','span_crop':[125,133,134],
            'uncertainty_px':2,'uncertainty_source':'local_registration.attempted_shift_px','touched_by':'corridor'})

    def test_four_pixels_outside_with_one_pixel_uncertainty_does_not_veto(self):
        result = self.classify(self.event(126),record={'max_rel_shift_px':.3})
        self.assertNotIn('UNRESOLVED_MINORITY_CONTENT',result['reasons'])

    def test_outside_corridor_inside_trim_vetoes(self):
        result = self.classify(self.event(140),trim_ranges=[[138,142]],record={'max_rel_shift_px':.3})
        self.assertEqual(self.hits(result)[0]['touched_by'],'trim')

    def test_connected_hairpin_reaching_corridor_vetoes(self):
        image = np.full((120,240,3),255,np.uint8)
        cv2.line(image,(118,103),(142,108),(0,0,0),1)
        result = self.classify(self.event(143,109),image=image,record={'max_rel_shift_px':.3})
        self.assertEqual(self.hits(result)[0]['touched_by'],'connected_component')

    def test_grouped_text_extends_possible_location(self):
        image = np.full((120,240,3),255,np.uint8)
        image[101:107,119:123] = 0
        image[101:107,137:141] = 0
        result = self.classify(self.event(143),image=image,record={'max_rel_shift_px':.3})
        self.assertEqual(self.hits(result)[0]['touched_by'],'connected_component')

    def test_legacy_box_uses_two_pixel_halo(self):
        result = self.classify({'box_strip':[123,100,124,108]},record={'max_rel_shift_px':0})
        hit = self.hits(result)[0]
        self.assertEqual(hit['uncertainty_px'],2)
        self.assertEqual(hit['uncertainty_source'],'legacy_box_unknown')
        self.assertEqual(hit['touched_by'],'corridor')

    def test_unknown_uncertainty_is_two_and_member_shift_takes_precedence(self):
        result = self.classify(self.event(123))
        self.assertEqual(self.hits(result)[0]['uncertainty_source'],'unknown')
        event = self.event(123)
        event['foreground_support'][0]['registration_shift'] = [.6,.8]
        result = self.classify(event,record={'max_rel_shift_px':20})
        self.assertEqual(self.hits(result),[])
        result = self.classify(self.event(124),record={'member_registration':[
            {'obs_id':'own','residual_shift_px':[0,3]}],'max_rel_shift_px':0})
        self.assertEqual(self.hits(result)[0]['uncertainty_source'],'member_registration.residual_shift_px')

    def test_vertical_uncertainty_maps_crop_to_strip(self):
        result = self.classify(self.event(120,y=-1))
        self.assertEqual(self.hits(result)[0]['touched_by'],'corridor')
        result = self.classify(self.event(120,y=-4),record={'max_rel_shift_px':.3})
        self.assertEqual(self.hits(result),[])

    def test_strip_coordinate_support_and_non_ink_keep_contract(self):
        event = {'support_coordinate_space':'strip','foreground_support':[
            {'obs_id':'own','spans_crop':[[105,123,124]]}]}
        self.assertTrue(self.hits(self.classify(event)))
        event['classification'] = 'EXPLAINED_CURSOR'
        self.assertEqual(self.hits(self.classify(event)),[])
        event.pop('classification')
        event['ink_like'] = False
        self.assertEqual(self.hits(self.classify(event)),[])

    def test_proposal_includes_full_height_scaffold_trim_run(self):
        image,record = make_strip()
        an = analyse(image,record)
        proposal = rb.propose(an)[0]
        self.assertTrue(proposal['trim_ranges'])
        a,z = proposal['trim_ranges'][0]
        self.assertFalse(an.nonstaff[:,a:z].any())
        self.assertLessEqual(a,proposal['seam_x'])
        self.assertGreater(z,proposal['seam_x'])


if __name__ == '__main__':
    unittest.main()
