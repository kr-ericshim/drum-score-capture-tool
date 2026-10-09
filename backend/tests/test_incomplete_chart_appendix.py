"""Every unresolved interval of an incomplete chart appears on paper (STRATEGY Step 2A).

When the interval list does not fit the page-1 notice (reflow_render.NOTICE_MAX_LINES), the notice
gives the number of intervals and points to the end of the chart, where every interval is listed
after the last line (reflow_render.appendix_rows, reflow_layout.append_trailing_rows). The appendix
counts in the plan's page count and the export still verifies."""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_pipeline
from app.pipeline import reflow_render as rr
from app.pipeline.export import ExportVerificationError, export_composed_pages, verify_composed_export

from test_incomplete_chart_export import make_systems


def spans(n, start=100.0):
    return [[start + 10.0 * i, start + 10.0 * i + 4.0] for i in range(n)]


def header_unknown(n, locale=None):
    """``n`` unresolved intervals whose place in the output order is unknown (no markers)."""
    inc = {"unresolved": spans(n)}
    if locale:
        inc["locale"] = locale
    return {"title": "T", "incomplete": inc}


def appendix_rows(plan):
    return [(p["index"], row) for p in plan["pages"] for row in p.get("appendix", [])]


class NoticeAndAppendixTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.systems = make_systems(self.root / "strips", [(0, 4), (5, 9), (20, 24), (25, 29)])

    def tearDown(self):
        self.td.cleanup()

    def test_a_short_list_stays_in_the_notice_without_an_appendix(self):
        plan, _ = reflow_pipeline.compose_systems(self.systems, header=header_unknown(2))
        self.assertIn(rr.time_range(100.0, 104.0), plan["header"]["notice"])
        self.assertIn(rr.time_range(110.0, 114.0), plan["header"]["notice"])
        self.assertEqual(appendix_rows(plan), [])
        self.assertNotIn("appendix", plan["incomplete"])

    def test_24_unknown_intervals_are_all_listed_at_the_end(self):
        header = header_unknown(24)
        plan, pages = reflow_pipeline.compose_systems(self.systems, header=header)
        self.assertTrue(plan["validation"]["valid"])
        notice = plan["header"]["notice"]
        self.assertIn("24", notice)
        self.assertIn("악보 끝", notice)
        rows = appendix_rows(plan)
        text = " ".join(r["text"] for _p, r in rows)
        for a, b in spans(24):
            self.assertIn(rr.time_range(a, b), text)
        self.assertTrue(plan["incomplete"]["appendix"]["complete"])
        self.assertEqual(plan["incomplete"]["appendix"]["listed"], 24)
        # after the last line, inside the printable area, and inked
        last_line = max((p["index"], pl["y"] + pl["h"]) for p in plan["pages"] for pl in p["placements"])
        first_page, first_row = rows[0]
        self.assertGreaterEqual((first_page, first_row["y"]), last_line)
        for page, row in rows:
            self.assertLessEqual(row["y"] + row["h"], rl.PAGE_H - rl.MARGIN_BOTTOM)
            box = pages[page - 1][row["y"]:row["y"] + row["h"], row["x"]:row["x"] + row["w"]]
            self.assertGreater(int((box < 128).sum()), 50)
        out = export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=self.root / "export", logger=lambda _m: None)
        facts = verify_composed_export(out, plan=plan, pages=pages)
        self.assertTrue(facts["verified"])
        self.assertEqual(facts["pdf_pages"], len(plan["pages"]))

    def test_english_notice(self):
        plan, _ = reflow_pipeline.compose_systems(self.systems, header=header_unknown(24, locale="en"))
        self.assertIn("24 video intervals", plan["header"]["notice"])
        self.assertIn("end of the chart", plan["header"]["notice"])
        self.assertTrue(appendix_rows(plan)[0][1]["text"].startswith("Video intervals that could not be recovered (24)"))

    def test_a_long_list_continues_on_added_pages_that_count(self):
        n = 900
        plan, pages = reflow_pipeline.compose_systems(self.systems, header=header_unknown(n))
        line_pages = [p["index"] for p in plan["pages"] if p["placements"]]
        appendix_pages = sorted({page for page, _ in appendix_rows(plan)})
        self.assertGreater(max(appendix_pages), max(line_pages))  # added pages
        self.assertTrue(all(p["placements"] or p["index"] > max(line_pages) for p in plan["pages"]))
        self.assertEqual(len(pages), len(plan["pages"]))
        self.assertTrue(plan["incomplete"]["appendix"]["complete"])
        self.assertTrue(plan["validation"]["valid"])
        added = plan["pages"][-1]
        self.assertEqual(added["page_number"], added["index"])
        out = export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=self.root / "export", logger=lambda _m: None)
        facts = verify_composed_export(out, plan=plan, pages=pages)
        self.assertEqual(facts["pdf_pages"], len(plan["pages"]))

    def test_measure_lines_keep_the_appendix(self):
        from test_reflow_staff_size import measure_strip
        import cv2
        ms = []
        for i in range(3):
            img, rec = measure_strip()
            p = self.root / f"m{i}.png"
            cv2.imwrite(str(p), img)
            ms.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p), "issues": [],
                       "t_start": float(i * 10), "t_end": i * 10 + 4.0, "layout": "bottom_bar",
                       "strip": dict(rec, system_id=f"sys-00{i + 1}")})
        plan, pages = reflow_pipeline.compose_systems(ms, header=header_unknown(24), measure_reflow=True, measure_context={})
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        self.assertTrue(plan["validation"]["valid"])
        self.assertTrue(plan["incomplete"]["appendix"]["complete"])
        self.assertEqual(len(pages), len(plan["pages"]))

    def test_an_appendix_only_page_before_a_line_is_refused(self):
        plan, pages = reflow_pipeline.compose_systems(self.systems, header=header_unknown(24))
        out = export_composed_pages(pages=pages, formats=["png"], workspace=self.root / "export", logger=lambda _m: None)
        bad = dict(plan, pages=[{"index": 0, "placements": [], "appendix": [{"id": "x", "x": 0, "y": 0, "w": 1, "h": 1}]}]
                   + plan["pages"])
        with self.assertRaises(ExportVerificationError) as ctx:
            verify_composed_export(out, plan=bad, pages=pages + [np.zeros((1, 1, 3), np.uint8)])
        self.assertEqual(ctx.exception.code, "EMPTY_EXPORT")


if __name__ == "__main__":
    unittest.main()
