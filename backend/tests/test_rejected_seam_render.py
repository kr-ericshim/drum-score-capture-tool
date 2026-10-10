"""A jump join the user marked wrong is disclosed on paper (SEAM_REJECT_DESIGN "Implemented").

* every printed line that starts or ends at a user-rejected seam gets a small margin mark beside
  it (left: the line starts there; right: it ends there), and each affected page one short gray
  note in the bottom margin; nothing on the page moves;
* a chart without rejected seams gets no mark and no note;
* the source-clipped page-1 notice carries no count (a clipped strip is not a printed line)."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import main
from app.pipeline import reflow_layout as rl, reflow_render as rr, reflow_pipeline as rp
from app.pipeline.export import export_composed_pages, verify_composed_export
from test_incomplete_chart_export import make_systems
from test_staff_size_mode import make_systems as make_measure_systems

SEAM = "seam-ep-0001-ep-0002"
KO_NOTE = "⇄ 앱이 화면 연결을 확정하지 못해 앞뒤 화면을 모두 담았습니다. 표시된 곳에서 마디가 겹칠 수 있습니다."
EN_NOTE = "⇄ The app could not confirm this join, so both views are kept. Measures may repeat at the marked lines."


def jump_systems(systems, end_of=1, start_of=2):
    """System ``end_of`` ends and system ``start_of`` starts at the rejected seam (1-based)."""
    for s in systems:
        s["strip"]["jump"] = {"unverified_seam_before": None, "unverified_seam_after": None}
    systems[end_of - 1]["strip"]["jump"]["unverified_seam_after"] = SEAM
    systems[start_of - 1]["strip"]["jump"]["unverified_seam_before"] = SEAM
    return systems


def ink(page, box):
    x0, y0, x1, y1 = box
    return int(np.count_nonzero(page[max(0, y0):y1, max(0, x0):x1] < 200))


class RejectedSeamRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def compose(self, systems, rejected, locale=None, **kw):
        header = {"title": "T", **({"locale": locale} if locale else {})}
        header = main._compose_header(header, None, systems if rejected else self.clear(systems))
        return header, *rp.compose_systems(systems, header=header, **kw)

    @staticmethod
    def clear(systems):
        systems = copy.deepcopy(systems)
        for s in systems:
            (s.get("strip") or {}).pop("jump", None)
        return systems

    def margin_ink(self, page, pl, side):
        if side == "left":
            return ink(page, (0, pl["y"], min(pl["x"], rl.MARGIN_X), pl["y"] + pl["h"]))
        return ink(page, (max(pl["x"] + pl["w"], rl.PAGE_W - rl.MARGIN_X), pl["y"], rl.PAGE_W, pl["y"] + pl["h"]))

    def bottom_ink(self, page):
        return ink(page, (rl.MARGIN_X + 200, rl.PAGE_H - rl.MARGIN_BOTTOM, rl.PAGE_W, rl.PAGE_H))

    def test_header_lists_every_both_views_boundary(self):
        plain = {"title": "T"}
        clean = make_systems(self.root / "c", [(0, 4), (5, 9)])
        self.assertIs(main._compose_header(plain, None, clean), plain)
        systems = jump_systems(make_systems(self.root / "h", [(0, 4), (5, 9), (10, 14)]))
        out = main._compose_header(plain, None, systems)
        self.assertEqual(out["rejected_seams"], [{"system_id": "sys-001", "boundary": "end", "seam_id": SEAM},
                                                 {"system_id": "sys-002", "boundary": "start", "seam_id": SEAM}])
        self.assertEqual(plain, {"title": "T"})

    def test_whole_systems_marks_both_edges_and_note_on_affected_pages_ko(self):
        # many systems so the chart spans pages; the seam is between systems 6 and 7
        systems = jump_systems(make_systems(self.root / "w", [(i, i + 0.9) for i in range(14)]), end_of=6, start_of=7)
        header, plan, pages = self.compose(systems, [SEAM])
        self.assertTrue(plan["validation"]["valid"])
        marks = plan["rejected_seams"]["marks"]
        self.assertEqual({(m["line_id"], m["side"]) for m in marks}, {("sys-006", "right"), ("sys-007", "left")})
        self.assertEqual(plan["rejected_seams"]["note"], KO_NOTE)
        affected = set(plan["rejected_seams"]["pages"])
        self.assertTrue(affected)
        self.assertGreater(len(pages), len(affected), "fixture must have an unaffected page")
        for p in plan["pages"]:
            page = pages[p["index"] - 1]
            for pl in p["placements"]:
                for side in ("left", "right"):
                    expect = (pl["system_id"], side) in {(m["line_id"], m["side"]) for m in marks}
                    self.assertEqual(self.margin_ink(page, pl, side) > 20, expect, (pl["system_id"], side))
            self.assertEqual(self.bottom_ink(page) > 100, p["index"] in affected, p["index"])
        output = export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=self.root / "export", logger=lambda _: None)
        self.assertTrue(verify_composed_export(output, plan=plan, pages=pages)["verified"])

    def test_en_note_and_measure_lines(self):
        systems = jump_systems(make_measure_systems(self.root / "m", n=3), end_of=2, start_of=3)
        header, plan, pages = self.compose(systems, [SEAM], locale="en", measure_reflow=True, measure_context={})
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        self.assertEqual(plan["rejected_seams"]["note"], EN_NOTE)
        marks = plan["rejected_seams"]["marks"]
        self.assertTrue(marks)
        sides = {b["boundary"] for m in marks for b in m["boundaries"]}
        self.assertEqual(sides, {"start", "end"})
        for m in marks:
            p = next(p for p in plan["pages"] if p["index"] == m["page"])
            pl = next(pl for pl in p["placements"] if pl["system_id"] == m["line_id"])
            self.assertGreater(self.margin_ink(pages[p["index"] - 1], pl, m["side"]), 20)
            self.assertGreater(self.bottom_ink(pages[p["index"] - 1]), 100)

    def test_records_mark_left_right_and_inside_line(self):
        header = {"rejected_seams": [{"system_id": "b", "boundary": "end", "seam_id": "s1"},
                                     {"system_id": "c", "boundary": "start", "seam_id": "s1"},
                                     {"system_id": "x", "boundary": "start", "seam_id": "s2"}]}
        recs = rr.rejected_seam_records(header, [("L1", ["a", "b"]), ("L2", ["c", "d"])])
        self.assertEqual({(r["line_id"], r["side"]) for r in recs}, {("L1", "right"), ("L2", "left")})
        inside = rr.rejected_seam_records(header, [("L1", ["a", "b", "c"]), ("L2", ["c", "d"])])
        # b ends mid-line L1 is not true (b is not last); c starts mid-line L1: one right mark on L1
        self.assertEqual([(r["line_id"], r["side"]) for r in inside], [("L1", "right")])
        self.assertEqual(rr.rejected_seam_records({}, [("L1", ["a"])]), [])

    def test_without_rejection_pixels_equal_except_header(self):
        systems = jump_systems(make_systems(self.root / "n", [(i, i + 0.9) for i in range(6)]), end_of=3, start_of=4)
        _, plan_a, pages_a = self.compose(systems, [])
        self.assertNotIn("rejected_seams", plan_a)
        _, plan_b, pages_b = self.compose(systems, [SEAM])
        self.assertEqual([[(pl["system_id"], pl["x"], pl["y"], pl["w"], pl["h"]) for pl in p["placements"]] for p in plan_a["pages"]],
                         [[(pl["system_id"], pl["x"], pl["y"], pl["w"], pl["h"]) for pl in p["placements"]] for p in plan_b["pages"]])
        for p in plan_a["pages"]:
            for pl in p["placements"]:
                a = pages_a[p["index"] - 1][pl["y"]:pl["y"] + pl["h"], pl["x"]:pl["x"] + pl["w"]]
                b = pages_b[p["index"] - 1][pl["y"]:pl["y"] + pl["h"], pl["x"]:pl["x"] + pl["w"]]
                self.assertTrue(np.array_equal(a, b))
        # a chart without rejected seams has nothing in the margins beside the lines
        for p in plan_a["pages"]:
            for pl in p["placements"]:
                self.assertEqual(self.margin_ink(pages_a[p["index"] - 1], pl, "left"), 0)
                self.assertEqual(self.margin_ink(pages_a[p["index"] - 1], pl, "right"), 0)

    def test_source_clipped_notice_has_no_count_and_pixels_match_below_header(self):
        systems = make_systems(self.root / "c", [(0, 4), (5, 9), (20, 24)])
        systems[0]["issues"] = ["SOURCE_CLIPPED"]
        header = main._compose_header({"title": "T"}, None, systems)
        self.assertEqual(rr.source_clipped_notice(header), "원본 영상에서 일부 표기가 잘려 있습니다. 보이는 부분만 담았습니다.")
        self.assertEqual(rr.source_clipped_notice(dict(header, locale="en")),
                         "Some notation is cut off in the source video. Only the visible part is kept.")
        self.assertFalse(any(ch.isdigit() for ch in rr.source_clipped_notice(header)))
        plan, pages = rp.compose_systems(systems, header=header)
        self.assertEqual(plan["header"]["notice"], rr.source_clipped_notice(header))
        self.assertNotIn("rejected_seams", plan)
        # the notice is one line, as before; page 1 below the header band is unchanged by the text
        runs = [r for r in rr._layout_header(header) if r["kind"] == "notice"]
        self.assertEqual(len(runs), 1)
        old = dict(rr.__dict__)
        try:
            rr.source_clipped_notice = lambda h: "원본 영상에서 잘린 줄 1개 — 보이는 부분만 담음" if (h or {}).get("source_clipped") else None
            height_old = rr.header_height(header)
            plan_old, pages_old = rp.compose_systems(systems, header=header)
        finally:
            rr.source_clipped_notice = old["source_clipped_notice"]
        self.assertEqual(rr.header_height(header), height_old)
        band = rl.MARGIN_TOP + rr.header_height(header)
        self.assertEqual(len(pages), len(pages_old))
        self.assertTrue(np.array_equal(pages[0][band:], pages_old[0][band:]))
        for a, b in zip(pages[1:], pages_old[1:]):
            self.assertTrue(np.array_equal(a, b))


if __name__ == "__main__":
    unittest.main()
