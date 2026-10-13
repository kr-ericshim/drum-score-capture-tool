"""Jump-view strips: a measure number printed over a barline labels the measure to its right, so when a
line starts at that barline the number goes to the start of that line, not the end of the previous one
(docs/reflow/DECISIONS.md "Jump-view seam resolution", jump strips)."""

import tempfile
import unittest
from pathlib import Path

import cv2

from app.pipeline import reflow_boundaries as rb
from app.pipeline import reflow_measure as rmeas

from test_reflow_measure import INK, MW, PREFIX, TOP, Doc, measure_strip


def numbered_strip(measures: int = 10, layout: str = "jump_view"):
    img, rec = measure_strip(measures)
    for k in range(1, measures):
        text = str(k + 1)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        x = PREFIX + k * MW - tw // 2 + 1  # centred over the barline, like MuseScore's numbers
        cv2.putText(img, text, (x, TOP - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.4, INK, 1, cv2.LINE_AA)
    rec["layout"] = layout
    return img, rec


def compose(tmp: Path, layout: str):
    img, rec = numbered_strip(layout=layout)
    doc = Doc(tmp)
    s = doc.add("jmp-01-001", img, rec)
    s["layout"] = layout
    return doc.compose(measure_reflow=True)


class NumberOverBarlineTest(unittest.TestCase):
    def test_two_digit_number_centred_over_the_barline_is_found_whole(self):
        img, rec = numbered_strip()
        an = rb.analyse_strip(img, rec, system_id="jmp-01-001")
        seams = [p["seam_x"] for p in rb.propose(an)]
        barline = PREFIX + 9 * MW  # "10", one digit on each side of the barline
        seam = min(s for s in seams if s > barline)
        found = rmeas.number_over_barline(an, seam)
        self.assertIsNotNone(found)
        x0, y0, x1, y1 = found["native_box"]
        self.assertLess(x0, barline)
        self.assertGreater(x1, barline + 2)
        self.assertLessEqual(x1, seam)
        self.assertEqual(found["components"], 2)
        self.assertLess(y1, TOP)


class LineStartNumberTest(unittest.TestCase):
    def test_number_moves_to_the_start_of_the_line_it_labels(self):
        with tempfile.TemporaryDirectory() as td:
            plan, pages = compose(Path(td), "jump_view")
        mr = plan["measure_reflow"]
        self.assertEqual(mr["status"], "measure_lines")
        self.assertTrue(mr["audit"]["validation"]["valid"], mr["audit"]["validation"])
        moved = mr["audit"]["moved_measure_numbers"]
        self.assertGreater(len(mr["lines"]), 1)
        self.assertEqual(len(moved), len(mr["lines"]) - 1)  # every line after the first starts at a numbered barline
        for m in moved:
            self.assertTrue(m["moved"], m)
            self.assertLess(m["to_box_out"][0], 2 * 1.5 * 300 / 25.4)  # near the line's left edge
            self.assertGreater(m["ink_px"], 0)

    def test_page_strips_keep_their_numbers_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            plan, _pages = compose(Path(td), "bottom_bar")
        self.assertEqual(plan["measure_reflow"]["audit"]["moved_measure_numbers"], [])


if __name__ == "__main__":
    unittest.main()
