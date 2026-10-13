"""Source limits are declared on paper without inventing conversion loss."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import main
from app.pipeline import reflow_layout as rl, reflow_render as rr, reflow_pipeline as rp
from app.pipeline.export import export_composed_pages, verify_composed_export
from test_incomplete_chart_export import make_systems, incomplete
from test_staff_size_mode import make_systems as make_measure_systems


class SourceClippedRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.systems = make_systems(self.root / 'strips', [(0, 4), (5, 9), (20, 24)])
        self.systems[0]['issues'] = ['SOURCE_CLIPPED']
        self.systems[0]['source_clipped'] = {'sides': ['bottom'], 'columns': [10, 1600]}
        self.systems[2]['issues'] = ['SOURCE_CLIPPED', 'UNCERTAIN_MARK_KEPT', 'TRANSLUCENT_PLATE_GRAY']

    def tearDown(self):
        self.tmp.cleanup()

    def test_api_exposes_flags_metadata_and_review_outcome(self):
        record = {'systems': self.systems, 'review_required': True,
                  'review_reasons': ['SOURCE_CLIPPED', 'UNCERTAIN_MARK_KEPT', 'TRANSLUCENT_PLATE_GRAY']}
        fields = main._reflow_capture_fields(record)
        self.assertTrue(fields['review_required'])
        self.assertEqual(fields['review_reasons'], record['review_reasons'])
        first = fields['capture_diagnostics'][self.systems[0]['strip_path']]
        self.assertEqual(first['source_clipped'], self.systems[0]['source_clipped'])
        last = fields['capture_diagnostics'][self.systems[2]['strip_path']]
        self.assertEqual(len(last['warning_reasons']), 3)
        self.assertTrue(all(' / ' in x for x in last['warning_reasons']))
        self.assertEqual(main._finished_reflow_state(dict(fields, reflow=record)), 'review_required')
        self.assertEqual(main._finished_reflow_state(dict(fields, coverage=incomplete((10, 18)))), 'incomplete')

    def test_source_limited_chart_has_local_marks_summary_and_no_incomplete_flag(self):
        original = {'title': 'ドラム譜 드럼 악보'}
        header = main._compose_header(original, None, self.systems)
        self.assertEqual(original, {'title': 'ドラム譜 드럼 악보'})
        plan, pages = rp.compose_systems(self.systems, header=header)
        self.assertTrue(plan['validation']['valid'])
        self.assertNotIn('incomplete', plan)
        self.assertNotIn('incomplete', header)
        self.assertEqual(plan['header']['notice'], '원본 영상에서 일부 표기가 잘려 있습니다. 보이는 부분만 담았습니다.')
        markers = [(p, m) for p in plan['pages'] for m in p.get('markers', [])]
        self.assertEqual(len(markers), 2)
        for page, mark in markers:
            line = next(pl for pl in page['placements'] if pl['system_id'] == mark['after']) if 'after' in mark else next(pl for pl in page['placements'] if pl['system_id'] in mark['system_ids'])
            self.assertGreaterEqual(mark['y'], line['y'] + line['h'])
            self.assertEqual(mark['text'], '† 원본 영상에서 잘림')
            box = pages[page['index'] - 1][mark['y']:mark['y'] + mark['h'], mark['x']:mark['x'] + mark['w']]
            self.assertGreater(np.count_nonzero(box < 128), 30)
        output = export_composed_pages(pages=pages, formats=['png', 'pdf'], workspace=self.root / 'export', logger=lambda _: None)
        self.assertTrue(verify_composed_export(output, plan=plan, pages=pages)['verified'])

    def test_combined_long_notice_keeps_source_summary_and_every_missing_interval(self):
        coverage = incomplete(*[(100 + 10 * i, 104 + 10 * i) for i in range(24)])
        header = main._compose_header({'title': 'T'}, coverage, self.systems)
        plan, _ = rp.compose_systems(self.systems, header=header)
        self.assertIn('원본 영상에서 일부 표기가 잘려 있습니다.', plan['header']['notice'])
        self.assertIn('전체 목록은 악보 끝', plan['header']['notice'])
        self.assertTrue(plan['incomplete']['appendix']['complete'])
        self.assertEqual(plan['incomplete']['appendix']['listed'], 24)
        self.assertEqual(len(plan['incomplete']['markers']), 24)
        self.assertEqual(len(plan['source_limited']['markers']), 2)
        runs = rr._layout_header(header)
        drawn_notice = ' '.join(r['text'] for r in runs if r['kind'] == 'notice')
        self.assertIn('원본 영상에서 일부 표기가 잘려 있습니다.', drawn_notice)
        self.assertNotIn('…', drawn_notice)
        self.assertTrue(plan['validation']['valid'])

    def test_source_marker_stays_with_its_line_at_page_break(self):
        units = [{'id': str(i), 'width': 1000, 'height': 1400, 'staff_gap_px': rl.DEFAULT_STAFF_GAP_MM * rl.MM} for i in range(4)]
        header = {'source_clipped': [{'system_id': '1'}]}
        marks, records = rr.layout_markers(header, [(u['id'], [u['id']]) for u in units])
        plan = rl.plan_pages(units, header_height_px=rr.header_height(header), markers=marks)
        self.assertTrue(plan['validation']['valid'])
        marker_page = next(p for p in plan['pages'] if p.get('markers'))
        self.assertIn('1', [p['system_id'] for p in marker_page['placements']])

    def test_measure_lines_receive_marks_for_source_systems(self):
        systems = make_measure_systems(self.root / 'measure', n=3)
        systems[1]['issues'] = ['SOURCE_CLIPPED']
        header = main._compose_header({'title': 'T', 'locale': 'en'}, None, systems)
        plan, _ = rp.compose_systems(systems, header=header, measure_reflow=True, measure_context={})
        self.assertEqual(plan['measure_reflow']['status'], 'measure_lines')
        self.assertNotIn('incomplete', plan)
        marks = [m for p in plan['pages'] for m in p.get('markers', [])]
        self.assertTrue(marks)
        self.assertTrue(all('sys-002' in m['system_ids'] for m in marks))
        self.assertEqual(marks[0]['text'], '† Cut off in source video')

    def test_cjk_title_has_nonzero_cmap_glyphs_and_is_rendered(self):
        text = 'ドラム譜 드럼 악보'
        font = rr._resolve_score_header_title_font(rr.TITLE_PX, text)
        self.assertTrue(rr.font_covers_text(font, text), getattr(font, 'path', None))
        self.assertFalse(rr.font_covers_text(font, '\U0010ffff'))
        header = {'title': text}
        run = next(r for r in rr._layout_header(header) if r['kind'] == 'title')
        self.assertEqual(run['text'], text)
        self.assertTrue(rr.font_covers_text(run['font'], run['text']))
        plan, pages = rp.compose_systems(self.systems, header=header)
        title_pixels = pages[0][rl.MARGIN_TOP:rl.MARGIN_TOP + rr.header_height(header)]
        self.assertGreater(np.count_nonzero(title_pixels < 128), 100)

    def test_dev_set_titles_with_hanzi_do_not_crash_the_header(self):
        # Real titles that crashed export when a fallback face carried a cmap format 14 subtable.
        for text in ['Throne 【Bring Me The Horizon】 by Tarn Softwhip Drum Cover 鼓譜 Drumtabs ドラム楽譜',
                     "Funkin' Fusion by Ninja Drummist Drum Cover 鼓譜 Drumtabs ドラム楽譜"]:
            run = next(r for r in rr._layout_header({'title': text}) if r['kind'] == 'title')
            self.assertTrue(run['text'])
        self.assertFalse(rr._cmap_has_glyph(b'', 0x9f13))
        self.assertFalse(rr._cmap_has_glyph(b'\x00\x0e\x00', 0x9f13))

    def test_font_chain_skips_unavailable_and_missing_glyph_faces(self):
        ascii_font = next((Path(p) for p in ['/System/Library/Fonts/Supplemental/Arial.ttf', 'C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'] if Path(p).exists()), None)
        if ascii_font is None:
            self.skipTest('No Latin-only fixture system font available')
        with patch.object(rr, '_iter_score_header_title_font_paths', return_value=[Path('/nonexistent.ttf'), ascii_font]):
            font = rr._resolve_score_header_title_font(30, 'ドラム譜 드럼 악보')
        self.assertNotEqual(str(font.path), str(ascii_font))
        self.assertTrue(rr.font_covers_text(font, 'ドラム譜 드럼 악보'))

    def test_no_font_available_falls_back_without_crashing(self):
        original = rr.ImageFont.truetype
        def unavailable(path, *args, **kwargs):
            if isinstance(path, (str, Path)):
                raise OSError('font unavailable')
            return original(path, *args, **kwargs)
        with patch.object(rr.ImageFont, 'truetype', side_effect=unavailable):
            font = rr._resolve_score_header_title_font(30, 'ドラム譜 드럼 악보')
        self.assertIsNotNone(font)
