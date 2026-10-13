"""Identity comparison around overlays and video background (reflow_occurrences-5).

Pale highlight boxes are masked column-wide: a cursor-highlighted view of a display is the same
display (C4l line 27 and 6MPX line 14 were printed twice when the ink under the box was compared).
Known limit: ink in the box columns but outside the box is masked too. A dot on paper beside
video texture is still compared."""

import unittest

import cv2
import numpy as np

from app.pipeline import page_diff, reflow_occurrences as ro, system_tracking as st
from drum_score_fixture import render, strip_spec, system_top
from reflow_fixture import STEP, build, loader


class TintedInkIdentityTest(unittest.TestCase):
    def setUp(self):
        self.spec = strip_spec(width=400, height=144, gap=12, margin_x=35,
                               show_bar_numbers=False)
        self.spec.notes = {(0, 1, 5): [1.5], (0, 3, 2): [3.5]}
        self.image = render(self.spec)
        self.top = system_top(self.spec, 0)
        self.box = (220, self.top - 30, 36, 86)

    def window(self, image):
        return image, (48, 48), 12.0, {"staff_y": [self.top + i * 12 for i in range(5)],
                                     "staff_x": [35, 365]}

    def tint(self, image, color=(255, 205, 190), strength=.30):
        image = image.copy()
        x, y, w, h = self.box
        box = image[y:y + h, x:x + w]
        box[:] = np.rint((1 - strength) * box + strength * np.array(color)).astype(np.uint8)
        self.assertTrue(page_diff._tinted_highlight_boxes(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), gap=12))
        return image

    def test_highlighted_note_of_the_same_display_stays_same(self):
        # the playback highlight darkens or tints the current notes; the display is unchanged
        for color, strength in (((255, 150, 120), .50), ((150, 120, 255), .40), ((120, 255, 150), .30)):
            with self.subTest(color=color, strength=strength):
                b = self.tint(self.image, color, strength)
                same, info = ro.same_written_display(self.window(self.image), self.window(b))
                self.assertTrue(same, info)

    def test_identical_stem_under_tint_stays_same_across_hues(self):
        a = self.image.copy()
        cv2.line(a, (238, self.top - 25), (238, self.top + 18), (195, 195, 195), 1)
        for color in ((255, 205, 190), (195, 255, 210), (180, 195, 255)):
            with self.subTest(color=color):
                b = self.tint(a, color)
                same, info = ro.same_written_display(self.window(a), self.window(b))
                self.assertTrue(same, info)

    def test_dot_on_paper_beside_video_texture_is_still_compared(self):
        a = self.image.copy()
        rng = np.random.default_rng(7)
        a[:18, :180] = rng.integers(215, 250, (18, 180), dtype=np.uint8)[..., None]
        b = a.copy()
        cv2.circle(b, (230, 10), 2, (0, 0, 0), -1)
        same, info = ro.same_written_display(self.window(a), self.window(b))
        self.assertFalse(same, info)

    def test_solid_overlay_columns_keep_the_existing_mask(self):
        a = self.image.copy()
        b = a.copy()
        b[20:112, 220:256] = (255, 110, 40)
        x, y = ro._written_images(a, b, 12, ro.WRITTEN_INK_THRESHOLD)
        self.assertTrue(np.all(x[:, 217:259] == 255))
        self.assertTrue(np.all(y[:, 217:259] == 255))

    def occurrences(self, a, b, *, continuity=False):
        manifest, images = build([(i * STEP, a if i < 12 else b) for i in range(24)])
        episodes = []
        for k, obs in enumerate((manifest["observations"][:12], manifest["observations"][12:])):
            members = [st._Member(o["id"], o["system_regions"][0]["region_id"], o["t_sec"],
                                  o["system_regions"][0]["staff_y"][0], 12, "active", None) for o in obs]
            ep = st._Episode("slot-00", members, started_by="first_observation" if k == 0 else "content_change",
                             ended_by="content_change" if k == 0 else "end_of_source")
            episodes.append(st._episode_record(f"ep-{k}", ep, 6))
        if continuity:
            episodes[1]["continuity_links"] = [{"from": "ep-0", "to": "ep-1", "kind": "page_translation"}]
        return ro.build_occurrences({"episodes": episodes}, manifest, loader(images))


if __name__ == "__main__":
    unittest.main()
