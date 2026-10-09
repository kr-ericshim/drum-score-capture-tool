"""A4 composer (reflow_layout / reflow_render) and export_composed_pages."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_render as rr
from app.pipeline import system_detect as sd
from app.pipeline.export import export_composed_pages


def strip_image(width=1800, gap=16.0, top=60, height=220, mark=True):
    img = np.full((height, width, 3), 250, np.uint8)
    for k in range(5):
        y = int(round(top + k * gap))
        cv2.line(img, (10, y), (width - 10, y), (0, 0, 0), 2)
    for x in range(200, width - 100, 300):
        cv2.line(img, (x, top), (x, int(top + 4 * gap)), (0, 0, 0), 2)
        cv2.circle(img, (x + 60, int(top + gap)), 6, (0, 0, 0), -1)
    if mark:
        cv2.putText(img, "Fine", (width - 160, height - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    return img


class TestReflowLayout(unittest.TestCase):
    def test_uniform_staff_gap_and_order(self):
        # source widths proportional to the staff gap, so every strip fits the line at 1.5 mm
        units = [{"id": f"s{i}", "width": int(110 * g), "height": int(14 * g), "staff_gap_px": g} for i, g in enumerate([16.0, 12.0, 20.0, 16.5])]
        plan = rl.plan_pages(units, header_height_px=150)
        target = 1.5 * rl.MM
        self.assertAlmostEqual(plan["staff_gap_px"], round(target, 3), places=2)
        pls = [pl for p in plan["pages"] for pl in p["placements"]]
        self.assertEqual([pl["system_id"] for pl in pls], ["s0", "s1", "s2", "s3"])
        for u, pl in zip(units, pls):
            self.assertAlmostEqual(u["staff_gap_px"] * pl["scale"], target, places=4)
            # isotropic: width and height scale alike (integer rounding only)
            self.assertLess(abs(pl["w"] / u["width"] - pl["h"] / u["height"]), 0.01)
        self.assertTrue(plan["validation"]["content_accounted_for"])
        self.assertEqual(plan["validation"]["overflow_count"], 0)

    def test_wide_strip_is_a_layout_conflict_never_a_smaller_staff(self):
        # Audit probe: a 3000 px strip with a 16 px source gap used to shrink the whole
        # document to ~0.8 mm (and a 10 px gap to 0.6 mm). The chosen size must hold.
        units = [{"id": "wide", "width": 2600, "height": 200, "staff_gap_px": 16.0},
                 {"id": "normal", "width": 1500, "height": 200, "staff_gap_px": 16.0}]
        plan = rl.plan_pages(units)
        self.assertAlmostEqual(plan["staff_gap_mm"], 1.5, places=3)  # pre-fix: 1.1077 mm (document scaled down)
        self.assertAlmostEqual(plan["staff_gap_px"], round(1.5 * rl.MM, 3), places=3)
        pls = {pl["system_id"]: pl for p in plan["pages"] for pl in p["placements"]}
        for u in units:
            self.assertAlmostEqual(u["staff_gap_px"] * pls[u["id"]]["scale"], 1.5 * rl.MM, places=3)
        self.assertEqual([c["system_id"] for c in plan["conflicts"]], ["wide"])
        conflict = plan["conflicts"][0]
        self.assertEqual(conflict["kind"], "too_wide")
        fit = conflict["largest_fitting_staff_gap_mm"]
        self.assertTrue(1.0 <= fit < 1.5, fit)
        self.assertFalse(plan["validation"]["valid"])
        with self.assertRaises(rl.LayoutConflictError):
            rr.render_pages(plan, {"wide": np.full((200, 2600, 3), 255, np.uint8), "normal": np.full((200, 1500, 3), 255, np.uint8)})
        # an explicit user choice of the offered size resolves it, at exactly that size
        chosen = rl.plan_pages(units, staff_gap_mm=fit)
        self.assertEqual(chosen["conflicts"], [])
        self.assertTrue(chosen["validation"]["valid"])
        self.assertAlmostEqual(chosen["staff_gap_mm"], fit, places=4)

    def test_strip_too_wide_even_at_the_smallest_size_offers_no_size(self):
        plan = rl.plan_pages([{"id": "huge", "width": 3000, "height": 200, "staff_gap_px": 10.0}])
        self.assertAlmostEqual(plan["staff_gap_mm"], 1.5, places=3)
        self.assertIsNone(plan["conflicts"][0]["largest_fitting_staff_gap_mm"])
        self.assertFalse(plan["validation"]["valid"])

    def test_widow_move_rechecks_capacity(self):
        # Audit probe: heights [400, 400, 400, 2700-2900] produced overflow_count 1 after
        # the widow line was moved onto a page without room for it.
        units = [{"id": f"s{i}", "width": 1800, "height": h, "staff_gap_px": 16.0} for i, h in enumerate([400, 400, 400, 2700])]
        plan = rl.plan_pages(units)
        self.assertEqual(plan["validation"]["overflow_count"], 0)
        self.assertEqual(plan["conflicts"], [])
        self.assertTrue(plan["validation"]["valid"])
        self.assertEqual([len(p["placements"]) for p in plan["pages"]], [3, 1])

    def test_invalid_plan_is_refused_before_rendering(self):
        units = [{"id": "a", "width": 1800, "height": 300, "staff_gap_px": 16.0}]
        plan = rl.plan_pages(units)
        plan["pages"][0]["placements"][0]["y"] = rl.PAGE_H - 10  # pushed off the page
        plan["validation"] = rl.validate_plan(plan, ["a"])
        self.assertFalse(plan["validation"]["valid"])
        with self.assertRaises(rl.LayoutConflictError):
            rr.render_pages(plan, {"a": strip_image(height=300)})

    def test_pages_never_split_a_strip_and_number_from_page_two(self):
        units = [{"id": f"s{i}", "width": 1800, "height": 300, "staff_gap_px": 16.0} for i in range(30)]
        plan = rl.plan_pages(units, header_height_px=200)
        self.assertGreater(len(plan["pages"]), 2)
        self.assertIsNone(plan["pages"][0]["page_number"])
        self.assertTrue(plan["pages"][0]["header"])
        self.assertEqual([p["page_number"] for p in plan["pages"][1:]], list(range(2, len(plan["pages"]) + 1)))
        for p in plan["pages"]:
            for pl in p["placements"]:
                self.assertLessEqual(pl["y"] + pl["h"], rl.PAGE_H - rl.MARGIN_BOTTOM)
        self.assertTrue(plan["validation"]["content_accounted_for"])
        self.assertEqual(plan["validation"]["overlap_count"], 0)

    def test_single_line_last_page_takes_a_line_from_previous_page(self):
        # find a count that leaves exactly one line on the last page
        for n in range(5, 40):
            units = [{"id": f"s{i}", "width": 1800, "height": 400, "staff_gap_px": 16.0} for i in range(n)]
            plan = rl.plan_pages(units)
            if len(plan["pages"]) >= 2:
                self.assertNotEqual(len(plan["pages"][-1]["placements"]), 1)
        self.assertTrue(plan["validation"]["order_preserved"])


class TestReflowRender(unittest.TestCase):
    def test_render_keeps_staff_gap_uniform_and_draws_header_only_on_page_one(self):
        # widths proportional to the gap: every strip fits the line at 1.5 mm
        strips = {f"s{i}": strip_image(gap=g, width=int(110 * g)) for i, g in enumerate([16.0, 13.0, 19.0] * 6)}
        records = [{"system_id": k, "staff_gap_px": g} for k, g in zip(strips, [16.0, 13.0, 19.0] * 6)]
        plan, pages = rr.compose(records, strips, header={"title": "테스트 Title", "performer": "Drummer"})
        self.assertEqual(len(pages), len(plan["pages"]))
        self.assertGreaterEqual(len(pages), 2)
        target = plan["staff_gap_px"]
        for page in pages:
            self.assertEqual(page.shape, (rl.PAGE_H, rl.PAGE_W, 3))
            staves = sd.find_staves(sd.ink_mask(page))
            self.assertTrue(staves)
            for st in staves:
                self.assertLessEqual(abs(st["gap"] - target), 1.0)
        top_band = pages[0][rl.MARGIN_TOP:rl.MARGIN_TOP + plan["header_band_px"]]
        self.assertTrue((top_band < 128).any(), "title drawn on page 1")
        self.assertFalse((pages[1][rl.MARGIN_TOP - 40:rl.MARGIN_TOP - 2] < 128).any(), "no header on page 2")
        # page number bottom-left on page 2, nothing at the bottom of page 1
        bottom = slice(rl.PAGE_H - rl.MARGIN_BOTTOM, rl.PAGE_H)
        left = slice(0, rl.PAGE_W // 4)
        self.assertTrue((pages[1][bottom, left] < 160).any())
        self.assertFalse((pages[0][bottom] < 160).any())
        self.assertFalse((pages[1][bottom, rl.PAGE_W // 4:] < 160).any(), "no footer text")

    def test_paper_maps_to_white(self):
        strips = {"a": strip_image()}
        plan, pages = rr.compose([{"system_id": "a", "staff_gap_px": 16.0}], strips)
        pl = plan["pages"][0]["placements"][0]
        region = pages[0][pl["y"]:pl["y"] + pl["h"], pl["x"]:pl["x"] + pl["w"]]
        self.assertEqual(int(np.percentile(region, 50)), 255)


class TestExportComposedPages(unittest.TestCase):
    def test_same_rasters_in_png_jpg_pdf_at_300_dpi(self):
        pages = [np.full((rl.PAGE_H, rl.PAGE_W, 3), 255, np.uint8) for _ in range(3)]
        for i, p in enumerate(pages):
            cv2.putText(p, f"page {i + 1}", (300, 600), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 0, 0), 6)
        with tempfile.TemporaryDirectory() as td:
            out = export_composed_pages(pages=pages, formats=["png", "jpg", "pdf"], workspace=Path(td), logger=lambda _m: None)
            pngs = [p for p in out["images"] if p.endswith(".png")]
            jpgs = [p for p in out["images"] if p.endswith(".jpg")]
            self.assertEqual(len(pngs), 3)
            self.assertEqual(len(jpgs), 3)
            self.assertEqual(len(out["preview_images"]), 3)
            for k, (png, jpg) in enumerate(zip(pngs, jpgs)):
                a = cv2.imread(png)
                self.assertTrue(np.array_equal(a, pages[k]))
                b = cv2.imread(jpg)
                self.assertEqual(a.shape, b.shape)
                self.assertLess(float(np.abs(a.astype(int) - b.astype(int)).mean()), 2.0)
                with Image.open(png) as im:
                    self.assertAlmostEqual(im.info["dpi"][0], 300, places=0)
            pdf = Path(out["pdf"]).read_bytes()
            # 2480 x 3508 px at 300 dpi = 595.2 x 841.92 pt (A4)
            self.assertIn(b"595.2", pdf)
            self.assertEqual(pdf.count(b"/Subtype /Image"), 3)

    def test_rejects_empty_input(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                export_composed_pages(pages=[], formats=["png"], workspace=Path(td), logger=lambda _m: None)
            with self.assertRaises(RuntimeError):
                export_composed_pages(pages=[np.zeros((10, 10), np.uint8)], formats=["png"], workspace=Path(td), logger=lambda _m: None)


if __name__ == "__main__":
    unittest.main()
