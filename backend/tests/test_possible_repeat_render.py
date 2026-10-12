"""Content-family repeats are marked locally only when both parts are printed."""
import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app import main
from app.pipeline import reflow_layout as rl, reflow_ledger as ledger
from app.pipeline import reflow_measure as rm, reflow_pipeline as rp, reflow_render as rr
from test_incomplete_chart_export import incomplete, make_systems
from test_staff_size_mode import make_systems as make_measure_systems


KO_NOTICE = '‡ 앞 줄과 같은 화면일 수 있음 — 확인 필요'
EN_NOTICE = '‡ May repeat the line above — please check'


class PossibleRepeatRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.systems = make_systems(self.root / 'strips', [(0, 4), (5, 9), (10, 14)])
        self.systems[1].update(issues=['POSSIBLE_SAME_DISPLAY'], possible_repeat_of='sys-001')
        self.pair = {'system_id': 'sys-002', 'of_system_id': 'sys-001'}

    def test_compose_header_includes_only_flagged_pairs_both_composed(self):
        original = {'title': 'T', 'possible_repeats': [self.pair]}
        before = copy.deepcopy(original)
        header = main._compose_header(original, None, self.systems)
        self.assertEqual(header['possible_repeats'], [self.pair])
        self.assertEqual(original, before)
        for selected in (self.systems[:1], self.systems[1:], self.systems[2:]):
            with self.subTest(selected=[s['id'] for s in selected]):
                self.assertNotIn('possible_repeats', main._compose_header(original, None, selected))
        self.systems[1]['issues'] = []
        self.assertNotIn('possible_repeats', main._compose_header(original, None, self.systems))

    def test_layout_marks_each_holder_once_and_requires_the_previous_system(self):
        units = [('line-1', ['sys-001']), ('line-2', ['sys-002', 'sys-003']), ('line-3', ['sys-002'])]
        for locale, text in (('ko', KO_NOTICE), ('en', EN_NOTICE)):
            header = {'locale': locale, 'possible_repeats': [self.pair]}
            marks, records = rr.layout_markers(header, units)
            self.assertEqual([m['after'] for m in marks], ['line-2', 'line-3'])
            self.assertEqual(len(records), 2)
            for mark in marks:
                self.assertEqual(mark['kind'], 'possible_repeat')
                self.assertTrue(mark['keep_with_previous'])
                self.assertEqual(mark['h'], rr.MARKER_H)
                self.assertEqual(mark['text'], text)
                self.assertEqual(mark['system_ids'], ['sys-002'])
            self.assertEqual(rr.layout_markers(header, units[1:]), ([], []))
            self.assertEqual(rr.layout_markers(header, units[:1]), ([], []))

    def test_both_local_markers_stay_with_their_line_at_a_page_break(self):
        units = [{'id': str(i), 'width': 1000, 'height': 1400,
                  'staff_gap_px': rl.DEFAULT_STAFF_GAP_MM * rl.MM} for i in range(4)]
        header = {'source_clipped': [{'system_id': '1'}],
                  'possible_repeats': [{'system_id': '1', 'of_system_id': '0'}]}
        marks, _ = rr.layout_markers(header, [(u['id'], [u['id']]) for u in units])
        self.assertEqual({m['kind'] for m in marks}, {'source_clipped', 'possible_repeat'})
        plan = rl.plan_pages(units, header_height_px=rr.header_height(header), markers=marks)
        self.assertTrue(plan['validation']['valid'], plan['validation'])
        page = next(p for p in plan['pages'] if p.get('markers'))
        self.assertEqual(len(page['markers']), 2)
        line = next(p for p in page['placements'] if p['system_id'] == '1')
        self.assertTrue(all(m['y'] >= line['y'] + line['h'] for m in page['markers']))

    def test_direct_compose_recomputes_pairs_after_either_part_is_unticked(self):
        header = {'possible_repeats': [self.pair]}
        for selected, count in ((self.systems, 1), (self.systems[:1], 0), (self.systems[1:], 0)):
            with self.subTest(selected=[s['id'] for s in selected]):
                plan, _ = rp.compose_systems(selected, header=header, all_systems=self.systems)
                marks = [m for p in plan['pages'] for m in p.get('markers', [])]
                self.assertEqual(len(marks), count)
                self.assertNotIn('notice', plan['header'])
                self.assertNotIn('incomplete', plan)
        self.assertEqual(header, {'possible_repeats': [self.pair]})

    def test_render_is_unboxed_left_aligned_and_records_an_independent_template(self):
        header = {'possible_repeats': [self.pair], 'locale': 'en'}
        strips = {s['id']: np.full((100, 1000, 3), 255, np.uint8) for s in self.systems}
        records = [{'system_id': s['id'], 'staff_gap_px': 16} for s in self.systems]
        generated = []
        plan, pages = rr.compose(records, strips, header=header, generated=generated)
        page = next(p for p in plan['pages'] if p.get('markers'))
        mark = page['markers'][0]
        crop = pages[page['index'] - 1][mark['y']:mark['y'] + mark['h'], mark['x']:mark['x'] + mark['w']]
        self.assertTrue(np.any(crop < 128))
        self.assertTrue(np.all(crop[0] == 255) and np.all(crop[-1] == 255))
        self.assertTrue(np.all(crop[:, -1] == 255))
        origin = next(r for r in generated if r['kind'] == 'possible_repeat_notice')
        self.assertEqual(origin['inputs']['text'], EN_NOTICE)
        self.assertEqual(origin['inputs']['xy'][0], mark['x'])
        template = ledger.unpack_crop(origin['template'])
        x, y = origin['origin']
        h, w = template.shape[:2]
        np.testing.assert_array_equal(template, pages[origin['page_index']][y:y + h, x:x + w])
        self.assertTrue(rr.font_covers_text(rr._resolve_score_header_font(rr.MARKER_PX), KO_NOTICE))

    def test_repeat_markers_do_not_become_missing_interval_records(self):
        header = main._compose_header({}, incomplete((4.2, 4.8)), self.systems)
        plan, _ = rp.compose_systems(self.systems, header=header)
        self.assertEqual(len(plan['incomplete']['markers']), 1)
        self.assertTrue(any(m.get('kind') == 'possible_repeat' for p in plan['pages'] for m in p.get('markers', [])))

    def test_measure_and_optimizer_paths_mark_each_line_holding_the_flagged_system(self):
        systems = make_measure_systems(self.root / 'measure', n=3)
        systems[1].update(issues=['POSSIBLE_SAME_DISPLAY'], possible_repeat_of='sys-001')
        header = main._compose_header({'title': 'T', 'locale': 'en'}, None, systems)
        decided, _ = rp.resolve_dependencies(systems)
        for policy in ('legacy', 'A1'):
            with self.subTest(policy=policy):
                if policy == 'legacy':
                    plan, _ = rp.compose_systems(systems, header=header, measure_reflow=True, measure_context={})
                    self.assertEqual(plan['measure_reflow']['status'], 'measure_lines')
                else:
                    plan, _ = rm.compose(decided, header=header, staff_gap_mm=1.5, context={}, policy=policy)
                self.assertTrue(plan['validation']['valid'], plan['validation'])
                holders = {pl['system_id'] for p in plan['pages'] for pl in p['placements'] if 'sys-002' in pl['system_ids']}
                marks = [m for p in plan['pages'] for m in p.get('markers', [])]
                self.assertTrue(holders)
                self.assertEqual({m['id'] for m in marks}, {f'possible-repeat-{lid}' for lid in holders})
                self.assertTrue(all(m['kind'] == 'possible_repeat' and m['text'] == EN_NOTICE for m in marks))
                generated = plan['measure_reflow']['generated_origins']
                self.assertEqual(sum(r['kind'] == 'possible_repeat_notice' for r in generated), len(holders))


class NumberStepNoticeRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.systems = make_systems(self.root / 'strips', [(0, 4), (5, 9), (10, 14)])
        self.systems[1]['issues'] = ['NUMBER_STEP_UNRESOLVED']
        self.notice = {'system_id': 'sys-002'}

    def test_headers_recompute_notice_from_composed_systems_and_leave_input_unchanged(self):
        original = {'number_steps_unresolved': [self.notice]}
        for selected, count in ((self.systems, 1), (self.systems[1:], 1), (self.systems[:1], 0)):
            with self.subTest(selected=[s['id'] for s in selected]):
                header = main._compose_header(original, None, selected)
                self.assertEqual(header.get('number_steps_unresolved', []), [self.notice] if count else [])
                plan, _ = rp.compose_systems(selected, header=original, all_systems=self.systems)
                marks = [m for p in plan['pages'] for m in p.get('markers', [])]
                self.assertEqual(len(marks), count)
                self.assertTrue(all(m['kind'] == 'number_step' for m in marks))
                self.assertNotIn('incomplete', plan)
        self.assertEqual(original, {'number_steps_unresolved': [self.notice]})
        self.assertIn('NUMBER_STEP_UNRESOLVED', dict(main.REFLOW_ISSUE_REASONS))

    def test_each_holder_gets_the_requested_bilingual_notice_and_rendered_template(self):
        units = [('line-1', ['sys-001']), ('line-2', ['sys-002', 'sys-003']), ('line-3', ['sys-002'])]
        texts = (('ko', '‡ 이 줄에 마디 번호가 다른 화면이 합쳐졌을 수 있음 — 확인 필요'),
                 ('en', '‡ Displays with different measure numbers may be merged here — please check'))
        for locale, text in texts:
            with self.subTest(locale=locale):
                header = {'locale': locale, 'number_steps_unresolved': [self.notice]}
                marks, records = rr.layout_markers(header, units)
                self.assertEqual([m['after'] for m in marks], ['line-2', 'line-3'])
                self.assertEqual(len(records), 2)
                self.assertTrue(all(m['text'] == text and m['keep_with_previous'] for m in marks))
                generated = []
                strips = {s['id']: np.full((100, 1000, 3), 255, np.uint8) for s in self.systems}
                plan, pages = rr.compose([{'system_id': s['id'], 'staff_gap_px': 16} for s in self.systems],
                                         strips, header=header, generated=generated)
                origin = next(r for r in generated if r['kind'] == 'number_step_notice')
                self.assertEqual(origin['inputs']['text'], text)
                template = ledger.unpack_crop(origin['template'])
                x, y = origin['origin']
                h, w = template.shape[:2]
                np.testing.assert_array_equal(template, pages[origin['page_index']][y:y + h, x:x + w])
                self.assertTrue(rr.font_covers_text(rr._resolve_score_header_font(rr.MARKER_PX), text))
                self.assertTrue(np.any(template < 128))
                self.assertNotIn('incomplete', plan)

    def test_number_and_repeat_notices_stay_with_the_line_at_page_break(self):
        units = [{'id': str(i), 'width': 1000, 'height': 1400,
                  'staff_gap_px': rl.DEFAULT_STAFF_GAP_MM * rl.MM} for i in range(4)]
        header = {'number_steps_unresolved': [{'system_id': '1'}],
                  'possible_repeats': [{'system_id': '1', 'of_system_id': '0'}]}
        marks, _ = rr.layout_markers(header, [(u['id'], [u['id']]) for u in units])
        plan = rl.plan_pages(units, header_height_px=rr.header_height(header), markers=marks)
        self.assertTrue(plan['validation']['valid'], plan['validation'])
        page = next(p for p in plan['pages'] if p.get('markers'))
        self.assertEqual({m['kind'] for m in page['markers']}, {'number_step', 'possible_repeat'})
        line = next(p for p in page['placements'] if p['system_id'] == '1')
        self.assertTrue(all(m['y'] >= line['y'] + line['h'] for m in page['markers']))

    def test_number_notice_is_independent_of_missing_intervals_and_measure_layout(self):
        header = main._compose_header({}, incomplete((4.2, 4.8)), self.systems)
        plan, _ = rp.compose_systems(self.systems, header=header)
        self.assertEqual(len(plan['incomplete']['markers']), 1)
        self.assertTrue(any(m.get('kind') == 'number_step' for p in plan['pages'] for m in p.get('markers', [])))
        systems = make_measure_systems(self.root / 'measure', n=3)
        systems[1]['issues'] = ['NUMBER_STEP_UNRESOLVED']
        header = main._compose_header({'locale': 'en'}, None, systems)
        decided, _ = rp.resolve_dependencies(systems)
        for policy in ('legacy', 'A1'):
            with self.subTest(policy=policy):
                if policy == 'legacy':
                    plan, _ = rp.compose_systems(systems, header=header, measure_reflow=True, measure_context={})
                else:
                    plan, _ = rm.compose(decided, header=header, staff_gap_mm=1.5, context={}, policy=policy)
                holders = {pl['system_id'] for p in plan['pages'] for pl in p['placements'] if 'sys-002' in pl['system_ids']}
                marks = [m for p in plan['pages'] for m in p.get('markers', [])]
                self.assertEqual({m['id'] for m in marks}, {f'number-step-{lid}' for lid in holders})
                self.assertEqual(sum(r['kind'] == 'number_step_notice'
                                     for r in plan['measure_reflow']['generated_origins']), len(holders))


if __name__ == '__main__':
    unittest.main()
