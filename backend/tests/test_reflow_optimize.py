import copy
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_optimize as opt, reflow_measure as rm, reflow_layout as rl, reflow_lines as old
from test_reflow_measure import measure_strip


def atoms(widths):
    return [{"id": f"a{k}", "system_id": "s", "width": w, "kind": "measure", "measure_count": 1,
             "measure_estimate": 1, "break_before": "system_start" if k == 0 else "safe_cut",
             "boundary_class": "SAFE", "boundary_id": f"b{k}", "replica_width": 0,
             "join_legal": False, "gaps": [], "slot_before": None, "native_scale": 1., "policy": "A"}
            for k, w in enumerate(widths)]


class CapTests(unittest.TestCase):
    def test_min_form_A_and_B(self):
        self.assertEqual(opt.directional_caps(100, 10, "A"), (4, 1))
        self.assertEqual(opt.directional_caps(100, 10, "B"), (6, 2))
        self.assertEqual(opt.directional_caps(10, 100, "A"), (3, 0))
        self.assertEqual(opt.directional_caps(10, 100, "B"), (5, 0))

    def test_round_down_without_one_pixel_promotion(self):
        self.assertEqual(opt.directional_caps(2, 2, "A"), (0, 0))
        self.assertEqual(opt.directional_caps(100, 2.499999, "A")[0], 0)
        self.assertEqual(opt.directional_caps(100, 2.5, "A")[0], 1)

    def test_room_and_negative_clamps(self):
        self.assertEqual(opt.directional_caps(-1, 10, "A"), (0, 0))
        self.assertEqual(opt.directional_caps(100, -1, "A"), (0, 0))
        self.assertEqual(opt.directional_caps(100, 10, "B", expand_room=.9, contract_room=.9), (0, 0))
        self.assertEqual(opt.directional_caps(100, 10, "A", locked=True), (0, 0))
        self.assertEqual(opt.directional_caps(2, 10, "B")[1], 0)

    def test_barline_budget_is_combined_both_sides(self):
        self.assertEqual(opt.directional_caps(20, 10, "A", barline=True), (7, 2))
        self.assertEqual(opt.directional_caps(20, 10, "B", barline=True), (10, 3))
        self.assertEqual(opt.directional_caps(20, 10, "B", barline=True, contract_room=1.9), (10, 1))

    def test_protected_barline_separates_halves_but_not_their_budget(self):
        a=atoms([50,50])
        a[0]['gaps']=[{'id':'left','kind':'spread','column_kind':'staff_only','natural':18,
                       'run_out':[4,18],'col_out':10,'max_expand':99,'max_contract':99}]
        a[1]['slot_before']={'id':'right','kind':'barline_corridor','boundary_id':'b1',
                            'natural':20,'native_corridor':[23,43],'seam_out':33,
                            'room_out':[4,4],'max_expand':99,'max_contract':99}
        mask=np.ones((50,100),bool);mask[:,2:20]=False;mask[:,23:43]=False
        built={'atoms':a,'doc':{'boundaries':[{'id':'b1','system_id':'s','kind':'barline','class':'SAFE','barline_box':[20,0,23,50]}]},
               'strips':{'s':{'scale':1.,'gap_src':10.,'nonstaff_out':mask}}}
        prepared=opt.prepare_built(built,'B',native_protection={'s':{'nonstaff':mask}})
        left,right=prepared['atoms'][0]['gaps'][0],prepared['atoms'][1]['slot_before']
        self.assertEqual(left['cap_unit_id'],right['cap_unit_id'])
        self.assertEqual(left['package_native_width'],38)  # protected stroke excluded
        self.assertEqual(left['max_expand']+right['max_expand'],10)  # NOT 6+10
        self.assertEqual(left['max_contract']+right['max_contract'],3)
        self.assertEqual(opt.package_distortion([4,3],[left,right],True),1.5*(.7**3))

    def test_corridors_merge_without_crossing_systems(self):
        slots = [{"id": "a", "system_id": "s", "native_corridor": [10, 20]},
                 {"id": "b", "system_id": "s", "native_corridor": [20, 30]},
                 {"id": "c", "system_id": "t", "native_corridor": [10, 30]}]
        groups = opt.merge_corridors(slots)
        self.assertEqual([[g["id"] for g in x] for x in groups], [["a", "b"], ["c"]])

    def fixture(self, scale=1.):
        a = atoms([100])[0]
        a['gaps'] = [{"id": "g1", "kind": "spread", "column_kind": "staff_only", "natural": 20*scale,
                      "run_out": [int(12*scale), int(28*scale)], "col_out": int(20*scale),
                      "max_expand": 10, "max_contract": 4},
                     {"id": "g2", "kind": "spread", "column_kind": "staff_only", "natural": 20*scale,
                      "run_out": [int(22*scale), int(38*scale)], "col_out": int(30*scale),
                      "max_expand": 10, "max_contract": 4}]
        return {"atoms": [a], "doc": {"boundaries": []}, "strips": {
            "s": {"scale": scale, "gap_src": 10., "nonstaff_out": np.zeros((20, 120), bool)}}}

    def test_splitting_a_physical_gap_never_doubles_budget(self):
        built = self.fixture()
        before = copy.deepcopy(built['atoms'])
        gs = opt.prepare_built(built, "A")['atoms'][0]['gaps']
        self.assertEqual(sum(g['max_expand'] for g in gs), 4)
        self.assertEqual(sum(g['representative'] for g in gs), 1)
        self.assertEqual(built['atoms'], before)

    def test_native_rounding_precedes_output_rounding(self):
        gs = opt.prepare_built(self.fixture(scale=.5), "A")['atoms'][0]['gaps']
        self.assertEqual(sum(g['max_expand'] for g in gs), 2)
        self.assertEqual(sum(g['max_contract'] for g in gs), 0)

    def test_native_interior_corridor_keeps_current_0_6_gap_eligibility(self):
        built = self.fixture()
        built['atoms'][0]['gaps'] = built['atoms'][0]['gaps'][:1]
        mask=np.ones((20,120),bool);mask[:,18:22]=False
        gs=opt.prepare_built(built,'B',native_protection={'s':{'nonstaff':mask}})['atoms'][0]['gaps']
        self.assertEqual(gs[0]['corridor_native_width'],4)
        self.assertEqual(gs[0]['max_expand'],0)
        self.assertIn('CORRIDOR_BELOW_0_6_STAFF_GAP',gs[0]['blocked_by'])

    def test_beam_or_uncertain_foreground_locks_entire_corridor(self):
        for key, val in [('column_kind', 'level_beam'), ('uncertain_foreground', True)]:
            built = self.fixture()
            built['atoms'][0]['gaps'][0][key] = val
            gs = opt.prepare_built(built, 'B')['atoms'][0]['gaps']
            self.assertEqual(sum(g['max_expand']+g['max_contract'] for g in gs), 0)

    def test_text_run_whitespace_is_locked(self):
        built = self.fixture()
        native = {'s': {'nonstaff': np.zeros((80, 120), bool),
                        'staff': {'lines': [30,40,50,60,70]},
                        'regions': [{'box': [10, 0, 18, 10]}, {'box': [22, 0, 38, 10]}]}}
        gs = opt.prepare_built(built, 'A', native_protection=native)['atoms'][0]['gaps']
        self.assertEqual(sum(g['max_expand']+g['max_contract'] for g in gs), 0)
        self.assertIn('LYRICS_OR_TEXT_RUN', gs[0]['blocked_by'])

    def image_fixture(self):
        from app.pipeline import reflow_boundaries as rb
        built = self.fixture()
        st = built['strips']['s']
        st['image'] = np.full((80, 120, 3), 255, np.uint8)
        for y in [30, 40, 50, 60, 70]:
            st['image'][y] = 0
        st['top_out'] = 30
        st['record'] = {'staff_y_strip': [30, 40, 50, 60, 70],
                        'staff_x_strip': [0, 119], 'staff_gap_px': 10,
                        'box_crop': [100, 200, 220, 280]}
        return built

    def analyse_fixture(self, built):
        from app.pipeline import reflow_boundaries as rb
        st = built['strips']['s']
        st['nonstaff_out'] = rb.analyse_strip(st['image'], st['record']).nonstaff
        return opt.prepare_built(built, 'B')['atoms'][0]['gaps']

    def test_staff_antialias_and_weak_row_variation_do_not_lock(self):
        built = self.image_fixture()
        st = built['strips']['s']
        for y in [30, 40, 50, 60, 70]:
            st['image'][y-1:y+2, 15:36] = 230
            st['image'][y, 15:36] = 0
        gs = self.analyse_fixture(built)
        self.assertGreater(sum(g['max_expand'] for g in gs), 0)
        self.assertFalse(any('EVIDENCED_FOREGROUND' in g['blocked_by'] for g in gs))

    def test_250_gray_haze_does_not_lock(self):
        built = self.image_fixture()
        built['strips']['s']['image'][:20] = 250
        gs = self.analyse_fixture(built)
        self.assertGreater(sum(g['max_expand'] for g in gs), 0)

    def test_unrecorded_paper_tone_does_not_lock(self):
        built = self.image_fixture()
        built['strips']['s']['image'][1, 15] = 230
        gs = self.analyse_fixture(built)
        self.assertGreater(sum(g['max_expand'] for g in gs), 0)

    def test_recorded_uncertain_mark_on_staff_locks_even_at_251_gray(self):
        built = self.image_fixture()
        st = built['strips']['s']
        st['image'][31, 15] = 251
        st['record']['uncertain_marks'] = [{'bbox': [15, 31, 16, 32], 'disposition': 'alternate'}]
        gs = self.analyse_fixture(built)
        self.assertEqual(sum(g['max_expand']+g['max_contract'] for g in gs), 0)
        self.assertIn('EVIDENCED_FOREGROUND', gs[0]['blocked_by'])

    def test_real_one_pixel_stroke_locks(self):
        built = self.image_fixture()
        built['strips']['s']['image'][1:12, 15] = 0
        gs = self.analyse_fixture(built)
        self.assertEqual(sum(g['max_expand']+g['max_contract'] for g in gs), 0)

    def test_recorded_crop_boxes_rebased_for_selected_strip(self):
        built = self.image_fixture()
        st = built['strips']['s']
        for field in ['minority', 'contrast', 'chrome', 'protected']:
            with self.subTest(field=field):
                record = dict(st['record'])
                box = [115, 201, 116, 212]
                if field == 'minority':
                    record['minority_content'] = {'events': [{'box_crop': box}]}
                elif field == 'contrast':
                    record['finishing'] = {'dark_cleanup': {'flagged_boxes_crop': [box]}}
                elif field == 'chrome':
                    record['screen_chrome'] = {'touched_box_crop': [box]}
                else:
                    record['protected_regions'] = [{'box_crop': box}]
                st['record'] = record
                gs = self.analyse_fixture(built)
                self.assertEqual(sum(g['max_expand']+g['max_contract'] for g in gs), 0)
                st['record'] = {k:v for k,v in record.items() if k not in
                                ('minority_content', 'finishing', 'screen_chrome', 'protected_regions')}

    def test_join_drops_only_legacy_clear_columns_without_recorded_marks(self):
        built = self.image_fixture()
        a = built['atoms'][0]
        st = built['strips']['s']
        st['nonstaff_out'] = np.zeros((80, 120), bool)
        st['declef'] = {'image': st['image'], 'nonstaff_out': st['nonstaff_out']}
        a.update(join_legal=True, join_trim=4,
                 join={'mode': 'declef', 'trim': 4, 'lead_trim': 4, 'clear_cols': [12,13,14,15]})
        st['image'][1, 15] = 250
        self.assertTrue(opt.prepare_built(built, 'A')['atoms'][0]['join_legal'])
        st['record']['uncertain_marks'] = [{'bbox': [15, 1, 16, 2]}]
        self.assertFalse(opt.prepare_built(built, 'A')['atoms'][0]['join_legal'])

    def test_off_strip_recorded_box_does_not_lock_other_columns(self):
        built = self.image_fixture()
        built['strips']['s']['record']['uncertain_marks'] = [{'bbox': [-20, 1, -10, 2]}]
        self.assertGreater(sum(g['max_expand'] for g in self.analyse_fixture(built)), 0)

    def test_uncut_record_moves_uncertain_boxes_with_staff(self):
        system = {'strip': {'box_crop': [100, 200, 220, 280],
                            'uncut': {'box_crop': [90, 190, 240, 290]},
                            'uncertain_marks': [{'bbox': [15, 31, 16, 32]}]}}
        record = rm._analysis_record(system, 'uncut')
        self.assertEqual(opt.recorded_regions(record)[0]['box'], [25, 41, 26, 42])
        self.assertEqual(system['strip']['uncertain_marks'][0]['bbox'], [15, 31, 16, 32])


class ObjectiveAndPlanningTests(unittest.TestCase):
    def test_distortion_and_hard_side_caps(self):
        self.assertAlmostEqual(opt.distortion([1, 2], [2, 2]), (.125+1)/2+.5)
        self.assertEqual(opt.distortion([0], [0]), 0)
        with self.assertRaises(ValueError): opt.distortion([1], [0])
        with self.assertRaises(ValueError): opt.distortion([3], [2])

    def test_objective_exact_formula_and_size_plateau(self):
        line = {'target_width': 1000, 'achieved_width': 900, 'D_line': .25, 'measure_count': 2}
        cost = 1+.5+4+.2+.05*.25
        self.assertAlmostEqual(opt.objective([line], 2, 10, 1.5), (cost+4)/10)
        self.assertAlmostEqual(opt.objective([line], 2, 10, 1.6), (cost+4)/10)
        self.assertAlmostEqual(opt.objective([line], 2, 10, 1.4), (cost+4)/10+.5)
        with self.assertRaises(ValueError): opt.objective([line], 2, 0, 1.5)

    def test_17_size_grid(self):
        self.assertEqual(len(opt.SIZE_GRID), 17)
        self.assertEqual((opt.SIZE_GRID[0], opt.SIZE_GRID[-1]), (1.2, 1.6))
        self.assertTrue(all(abs(b-a-.025)<1e-9 for a,b in zip(opt.SIZE_GRID, opt.SIZE_GRID[1:])))

    def test_three_near_best_paths(self):
        plans = opt.plan_candidates(atoms([25]*8), 100)
        self.assertEqual(len(plans), 3)
        self.assertEqual([x['measure_count'] for x in plans[0]['lines']], [4, 4])
        self.assertEqual(sorted(p['cost'] for p in plans), [p['cost'] for p in plans])

    def test_dense_single_or_two_measures_are_allowed(self):
        plan = opt.plan_candidates(atoms([70]*3), 100)[0]
        self.assertEqual([x['measure_count'] for x in plan['lines']], [1,1,1])

    def test_unknown_and_locked_cuts_cannot_be_used(self):
        for cls in ['UNKNOWN', 'LOCKED']:
            a = atoms([70,70]); a[1]['boundary_class'] = cls
            self.assertEqual(opt.plan_candidates(a, 100), [])

    def test_missing_boundary_proof_defaults_to_unknown(self):
        a=atoms([70,70]);a[1].pop('boundary_class')
        self.assertEqual(opt.plan_candidates(a,100),[])

    def test_prefix_and_user_locks_are_hard(self):
        a = atoms([70,70]); a[1]['replica_width'] = None
        self.assertEqual(opt.plan_candidates(a, 100), [])
        self.assertEqual(opt.plan_candidates(atoms([70,70]), 100, locks=[{'type':'keep_together','targets':['a0','a1']}]), [])
        plans = opt.plan_candidates(atoms([30,30]), 100, locks=[{'type':'forced_line_break','targets':['b1']}])
        self.assertEqual([len(x['atom_ids']) for x in plans[0]['lines']], [1,1])

    def test_short_line_has_numerical_feasibility_even_final(self):
        plan = opt.plan_candidates(atoms([25,25]), 100)[0]
        e = plan['ragged_exceptions'][0]['feasibility']
        self.assertEqual((e['required_width_px'], e['W_min_px'], e['W_max_px']), (100,50,50))
        self.assertEqual(e['number_of_corridors'], 0)
        self.assertIn('blocking_protected_regions', e)
        self.assertIn('best_alternative_grouping_and_size', e)
        self.assertTrue(plan['ragged_exceptions'][0]['final_line'])

    def test_canvas_full_but_staff_inset_is_truthfully_short(self):
        a = atoms([100])
        plan = opt.plan_candidates(a,100)[0]
        line = plan['lines'][0];line['staff_top_px']=10
        image=np.full((65,100,3),255,np.uint8)
        for y in [10,20,30,40,50]:image[y,6:]=0
        opt.finalize_endpoint_flags(plan,{'atoms':a},{line['id']:image},10/rl.MM)
        self.assertFalse(line['justified'])
        self.assertFalse(line['full_target_achieved'])
        self.assertEqual(line['staff_endpoints_px'],[6,100])
        self.assertEqual(line['feasibility']['required_width_with_prefix_px'],106)
        self.assertEqual(len(plan['ragged_exceptions']),1)

    def test_legacy_policy_preserves_old_result(self):
        a = atoms([25]*8)
        self.assertEqual(old.plan_document(copy.deepcopy(a),100), old.plan_document(copy.deepcopy(a),100,policy='legacy'))

    def test_join_and_clef_replica_natural_width_matches_legacy(self):
        a = atoms([80, 60, 50])
        a[1].update(break_before='system_start', join_legal=True, join_trim=25,
                    join={'mode': 'declef', 'trim': 25})
        a[2]['replica_width'] = 12
        for i, j, expected in [(0, 2, 115), (2, 3, 62), (1, 3, 110)]:
            bounded = opt.evaluate_line(a, i, j, 200)
            legacy = old._line_eval(a, i, j, 200, True)
            self.assertEqual(bounded['natural_width'], expected)
            self.assertEqual(bounded['natural_width'], legacy['natural'])

    def test_fixed_size_and_real_left_margin(self):
        with tempfile.TemporaryDirectory() as td:
            img, rec = measure_strip()
            path = Path(td)/'s.png'; cv2.imwrite(str(path), img)
            system = {'id': 's', 'strip': rec, 'layout': 'bottom_bar'}
            decided = [{'system':system, 'strip_path':str(path), 'variant':'strip'}]
            plan, pages = rm.compose(decided, header={'title':'T'}, staff_gap_mm=1.5, context=None,
                                      auto_staff_size=False, policy='A1')
        self.assertTrue(pages)
        self.assertEqual(plan['staff_gap_mm'], 1.5)
        self.assertEqual(plan['staff_size']['reason'], 'EXPLICIT_SIZE_FIXED')
        self.assertEqual(len(plan['staff_size']['candidates']), 1)
        self.assertTrue(all(pl['x']==rl.MARGIN_X for p in plan['pages'] for pl in p['placements']))
        self.assertEqual(plan['measure_reflow']['justified_edge']['x_offset_px'], 0)
        self.assertTrue(plan['measure_reflow']['audit']['validation']['valid'])
        self.assertTrue(all(x['feasibility']['best_alternative_grouping_and_size'] is not None
                            for x in plan['measure_reflow']['ragged_exceptions']))


if __name__ == '__main__': unittest.main()
