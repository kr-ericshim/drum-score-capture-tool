"""2C-0 raw minority evidence, conditional plates and source edges."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from app.pipeline import reflow_strips as rs, reflow_jump as rj, reflow_pipeline as rp, source_class as sc
from reflow_fixture import build, loader
from test_source_class import _frames, _compose, _texture, _notation, _flat


def paper():
    im = np.full((160, 800, 3), 255, np.uint8)
    for y in (50, 62, 74, 86, 98):
        cv2.line(im, (20, y), (780, y), (0, 0, 0), 1)
    for x in (100, 300, 500, 700):
        cv2.line(im, (x, 35), (x, 98), (0, 0, 0), 2)
    return im


def review_images(rec):
    """Inspect every lossless raw variant retained inside the single review bundle."""
    import base64
    from app.pipeline import system_detect as sd
    for image, alternate in zip(rec["_alternate_images"],rec["minority_content"]["alternates"]):
        yield image, alternate
        for patch in alternate.get("evidence_patches",[]):
            raw=cv2.imdecode(np.frombuffer(base64.b64decode(patch["raw_png_base64"]),np.uint8),cv2.IMREAD_COLOR)
            yield sd.normalize_polarity(raw)[0], patch


def system_case(images):
    manifest, by = build([(i * .25, im) for i, im in enumerate(images)])
    observations = [{"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]}
                    for o in manifest["observations"]]
    sys = {"id": "sys-001", "observations": observations, "first_display": True, "terminal_display": True}
    return sys, manifest, loader(by)


class MinorityVisibilityTest(unittest.TestCase):
    def check_mark(self, x0, y0, x1, y1, seen=(5,), n=12):
        images = [paper() for _ in range(n)]
        for i in seen:
            images[i][y0:y1, x0:x1] = 0
        sys, manifest, load = system_case(images)
        img, rec = rs.build_strip(sys, manifest, load, chrome=False)
        self.assertIn(rs.UNCERTAIN_MARK_KEPT, rec["issues"])
        events = [e for e in rec["minority_content"]["events"]
                  if e["box_crop"][0] <= x0 < e["box_crop"][2] and e["box_crop"][1] <= y0 < e["box_crop"][3]]
        self.assertTrue(events, rec["minority_content"])
        self.assertEqual(events[0]["seen"], len(seen))
        self.assertEqual(events[0]["eligible"], n)
        alt = rec["minority_content"]["alternates"][events[0]["alternate"]]
        alt_im = rec["_alternate_images"][events[0]["alternate"]]
        ax, ay = alt["box_crop"][:2]
        self.assertTrue((alt_im[y0-ay:y1-ay, x0-ax:x1-ax] < 100).all())
        self.assertTrue(rec["uncertain_marks"])

    def test_single_member_one_pixel_vertical_stroke_kept_and_flagged(self):
        self.check_mark(420, 110, 421, 122)

    def test_one_pixel_horizontal_stroke_touching_staff_kept(self):
        self.check_mark(420, 63, 432, 64)

    def test_member_omitted_by_composite_sampling_is_still_checked(self):
        self.check_mark(420, 110, 421, 122, seen=(1,), n=40)

    def test_multi_member_thin_stroke_records_denominator(self):
        self.check_mark(420, 110, 421, 122, seen=(4,5,6))

    def test_two_pixel_speckle_may_be_dropped_but_is_counted(self):
        images = [paper() for _ in range(12)]
        images[5][110:112, 420] = 0
        sys, manifest, load = system_case(images)
        _im, rec = rs.build_strip(sys, manifest, load, chrome=False)
        self.assertNotIn(rs.UNCERTAIN_MARK_KEPT, rec["issues"])
        self.assertGreaterEqual(rec["minority_content"]["speckle_dropped"], 1)

    def check_ineligible_mark_is_preserved(self, images, eligibility):
        baseline_sys, baseline_manifest, baseline_load = system_case([paper() for _ in images])
        baseline, _ = rs.build_strip(baseline_sys, baseline_manifest, baseline_load, chrome=False)
        sys, manifest, load = system_case(images)
        primary, rec = rs.build_strip(sys, manifest, load, chrome=False)
        self.assertTrue(np.array_equal(primary, baseline))
        self.assertIn(rs.UNCERTAIN_MARK_KEPT, rec["issues"])
        self.assertEqual(rec["minority_content"]["skipped_members"], 1)
        self.assertEqual(rec["minority_content"]["checked_members"], 11)
        self.assertEqual(rec["members_used"], 11)
        events = [event for event in rec["minority_content"]["events"]
                  if eligibility in event.get("eligibility", [])]
        self.assertTrue(events)
        for event in events:
            self.assertEqual(event["eligible"], 11)
        self.assertEqual(len(rec["minority_content"]["alternates"]), 1)
        self.assertTrue(any(
            (im[110-alt["box_crop"][1]:122-alt["box_crop"][1], 420-alt["box_crop"][0]] < 100).all()
            for im, alt in review_images(rec)
            if alt["box_crop"][0] <= 420 < alt["box_crop"][2]
            and alt["box_crop"][1] <= 110 and alt["box_crop"][3] >= 122
        ))

    def test_fade_is_ineligible_but_keeps_uncertain_raw_evidence(self):
        images = [paper() for _ in range(12)]
        images[5][110:122, 420] = 0
        images[5] = (images[5].astype(float) * .7).astype(np.uint8)
        self.check_ineligible_mark_is_preserved(images, "INELIGIBLE_FADE")

    def test_overlay_mask_without_recovery_cannot_explain_a_raw_stroke(self):
        images = [paper() for _ in range(12)]
        images[5][110:122, 420] = 0
        sys, manifest, load = system_case(images)
        mask = np.zeros(images[0].shape[:2], bool); mask[110:122, 420] = True
        def overlay(im, *args, **kw):
            return mask.copy() if (im[110:122,420] < 100).any() else np.zeros(im.shape[:2],bool)
        with patch.object(rs, "_overlay_mask2d_of", side_effect=overlay):
            rec = rs.check_minority_content(sys, paper(), [0,0,800,160],
                                           {o["id"]:o for o in manifest["observations"]}, load, 12)
        self.assertTrue(rec["events"])
        self.assertEqual(rec["events"][0]["classification"], rs.UNCERTAIN_MARK_KEPT)


    def test_misregistered_member_is_ineligible_but_keeps_uncertain_raw_evidence(self):
        images = [paper() for _ in range(12)]
        images[5] = np.roll(images[5], 3, axis=1)
        images[5][110:122,420] = 0
        self.check_ineligible_mark_is_preserved(images, "INELIGIBLE_REGISTRATION")

    def test_tracker_to_strip_keeps_thin_single_observation(self):
        from app.pipeline import system_tracking as st, reflow_occurrences as ro
        images = [paper() for _ in range(12)]; images[5][110:122,420] = 0
        _sys, manifest, load = system_case(images)
        tracking = st.build_episodes(manifest, load)
        occ = ro.build_occurrences(tracking, manifest, load)
        included = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(included),1)
        _im, rec = rs.build_strip(included[0], manifest, load, chrome=False)
        self.assertIn(rs.UNCERTAIN_MARK_KEPT,rec["issues"])
        self.assertTrue(rec["_alternate_images"])

    def test_alternate_only_mark_does_not_expand_blank_primary_margins(self):
        images = [paper() for _ in range(12)]
        sys, manifest, load = system_case(images)
        baseline, _rec = rs.build_strip(sys,manifest,load,chrome=False)
        images[5][145:157,420] = 0
        sys, manifest, load = system_case(images)
        primary, rec = rs.build_strip(sys,manifest,load,chrome=False)
        self.assertTrue(np.array_equal(primary,baseline))
        self.assertIn(rs.UNCERTAIN_MARK_KEPT,rec["issues"])
        alt = rec["minority_content"]["alternates"][0]
        img = rec["_alternate_images"][0]
        ax,ay=alt["box_crop"][:2]
        self.assertTrue((img[145-ay:157-ay,420-ax] < 100).all())

    def test_screen_fixed_position_alone_does_not_remove_an_alternate(self):
        records=[]; images={}
        for j in range(3):
            sid=f"sys-{j}"
            event={"box_crop":[100,120,103,121],"area_px":3,"seen":1,"eligible":8,
                   "box_strip":[100,120,103,121],"alternate":0}
            records.append({"system_id":sid,"staff_gap_px":12,"issues":[rs.UNCERTAIN_MARK_KEPT],
                            "minority_content":{"events":[event],"alternates":[{"events":[0]}]}})
            images[sid]=[np.zeros((3,3,3),np.uint8)]
        spots=rs.drop_screen_fixed_minority(records,images)
        self.assertTrue(spots)
        for r in records:
            self.assertEqual(len(r["minority_content"]["events"]),1)
            self.assertEqual(len(r["minority_content"]["alternates"]),1)
            self.assertIn(rs.UNCERTAIN_MARK_KEPT,r["issues"])
            self.assertEqual(len(images[r["system_id"]]),1)
            self.assertTrue(r["minority_content"]["screen_fixed_suspicions"])

    def test_nearby_distinct_minority_strokes_keep_both_observation_variants(self):
        images=[paper() for _ in range(12)]
        images[5][110:122,420]=0; images[6][110:122,425]=0
        sys,manifest,load=system_case(images)
        _im,rec=rs.build_strip(sys,manifest,load,chrome=False)
        self.assertIn(rs.UNCERTAIN_MARK_KEPT,rec["issues"])
        for x in (420,425):
            kept=False
            for im,a in review_images(rec):
                ax,ay=a["box_crop"][:2]
                kept |= bool((im[110-ay:122-ay,x-ax] < 100).all())
            self.assertTrue(kept,f"missing minority stroke at {x}")
        self.assertEqual(len(rec["minority_content"]["alternates"]),1)
        self.assertGreaterEqual(len(rec["minority_content"]["alternates"][0]["evidence_patches"]),2)

    def test_staff_scaffold_does_not_hide_distinct_horizontal_variants(self):
        images=[paper() for _ in range(12)]
        images[5][63,420:432]=0; images[6][63,425:437]=0
        sys,manifest,load=system_case(images)
        _im,rec=rs.build_strip(sys,manifest,load,chrome=False)
        for x0,x1 in ((420,432),(425,437)):
            kept=False
            for im,a in review_images(rec):
                ax,ay=a["box_crop"][:2]
                kept |= bool((im[63-ay,x0-ax:x1-ax] < 100).all())
            self.assertTrue(kept,f"missing horizontal variant {x0}:{x1}")

    def test_gray_thin_minority_stroke_on_opaque_paper_is_preserved(self):
        for dark in (False,True):
            images=[(255-paper()) if dark else paper() for _ in range(12)]
            images[5][110:122,420]=120 if dark else 135
            sys,manifest,load=system_case(images)
            _im,rec=rs.build_strip(sys,manifest,load,chrome=False)
            self.assertIn(rs.UNCERTAIN_MARK_KEPT,rec["issues"])
            kept=False
            for im,a in review_images(rec):
                ax,ay=a["box_crop"][:2]
                kept |= bool((im[110-ay:122-ay,420-ax] < 180).all())
            self.assertTrue(kept,f"gray stroke lost, dark={dark}")


class PlateVisibilityTest(unittest.TestCase):
    def test_translucent_gray_is_counted_and_flagged(self):
        im = np.full((80, 200, 3), 30, np.uint8)
        shade = np.tile(np.linspace(30, 80, 100), (80,1)).astype(np.uint8)
        im[:,100:] = np.maximum(im[:,100:], shade[...,None])
        im[5:71,40:46] = 125
        _out,_inv,_flat,info = rs.finish_strip(im, members=[im.copy() for _ in range(5)], gap=12)
        self.assertGreaterEqual(info["dark_cleanup"]["translucent_glyphlike"], 1)
        self.assertIn(rs.TRANSLUCENT_PLATE_GRAY, info["issues"])

    def test_dim_video_plate_class_is_conditional(self):
        frames = _frames(lambda i: _compose(_texture(i,5,40), _notation(i//3), (250,250,250)))
        rec = sc.classify_frames(frames)
        self.assertIn(sc.FLAG_TRANSLUCENT, rec["flags"])
        self.assertTrue(rec["review_required"])
        self.assertIn(rs.TRANSLUCENT_PLATE_GRAY, rp.source_review_reasons(rec, []))

    def test_unknown_or_future_source_class_never_passes_by_fallthrough(self):
        for cls in (None, sc.CLASS_UNKNOWN, "future_class"):
            self.assertIn("SOURCE_CLASS_UNKNOWN", rp.source_review_reasons({"class": cls}, []))

    def test_clean_paper_has_no_conditional_reason(self):
        self.assertEqual(rp.source_review_reasons({"class": sc.CLASS_LIGHT_PAPER}, []), [])

    def test_system_finishing_diagnostic_sets_result_review_reason(self):
        reasons = rp.source_review_reasons({"class": sc.CLASS_DARK_PAPER}, [{"issues": [rs.TRANSLUCENT_PLATE_GRAY]}])
        self.assertEqual(reasons, [rs.TRANSLUCENT_PLATE_GRAY])

    def test_opaque_dark_paper_control_has_no_translucent_flag(self):
        rec = sc.classify_frames(_frames(lambda i:_compose(_flat((12,12,12)),_notation(i//3),(245,245,245))))
        self.assertEqual(rec["flags"],[])
        self.assertFalse(rec["review_required"])

    def test_static_dim_texture_is_still_conditional(self):
        im = _compose(_texture(0,5,40),_notation(0),(250,250,250))
        rec = sc.classify_frames([im.copy() for _ in range(12)])
        self.assertIn(sc.FLAG_TRANSLUCENT,rec["flags"])
        self.assertTrue(rec["review_required"])

    def test_unknown_classifier_result_explicitly_requires_review(self):
        rec = sc.classify_frames([np.full((100,200,3),255,np.uint8) for _ in range(5)])
        self.assertEqual(rec["class"],sc.CLASS_UNKNOWN)
        self.assertTrue(rec["review_required"])
        self.assertIn("SOURCE_CLASS_UNKNOWN",rec["review_reasons"])


class SourceEdgeVisibilityTest(unittest.TestCase):
    def manifest(self, transform=None):
        return {"source": {"frame_size": [800,160]}, "source_to_crop": transform or [1,0,0,0,1,0,0,0,1]}

    def cut_image(self):
        im = paper()
        im[150:,420:423] = 0; im[151:,440:444] = 0
        return im

    def test_bottom_cut_row_flagged_and_columns_in_strip_pixels(self):
        rec = rs.source_clipping(self.cut_image(), [20,0,780,160], self.manifest())
        self.assertEqual(rec, {"sides": ["bottom"], "columns": [400,424]})

    def test_paper_below_content_does_not_flag(self):
        im = self.cut_image(); im[155:] = 255
        self.assertIsNone(rs.source_clipping(im, [20,0,780,160], self.manifest()))

    def test_roi_inside_video_does_not_flag(self):
        manifest = self.manifest(); manifest["source"]["frame_size"] = [800,1080]
        self.assertIsNone(rs.source_clipping(self.cut_image(), [20,0,780,160], manifest))

    def test_other_system_not_flagged_by_bottom_glyphs(self):
        self.assertIsNone(rs.source_clipping(self.cut_image(), [20,0,780,120], self.manifest()))

    def test_long_horizontal_frame_border_is_not_notation(self):
        im = paper(); im[-1] = 0
        self.assertIsNone(rs.source_clipping(im, [0,0,800,160], self.manifest()))

    def test_build_strip_carries_source_clipped_issue(self):
        sys, manifest, load = system_case([self.cut_image() for _ in range(8)])
        manifest.update(self.manifest())
        _im, rec = rs.build_strip(sys, manifest, load, chrome=False)
        self.assertIn(rs.SOURCE_CLIPPED, rec["issues"])
        self.assertEqual(rec["source_clipped"]["sides"], ["bottom"])

    def test_work_scaled_source_coordinates(self):
        raw = cv2.resize(self.cut_image(), (400,80), interpolation=cv2.INTER_NEAREST)
        manifest = self.manifest([.5,0,-.25,0,.5,-.25,0,0,1]); manifest["work_scale"]={"scale":.5}
        rec = rs.source_clipping(raw, [0,0,400,80], manifest)
        self.assertEqual(rec["sides"], ["bottom"])

    def test_paper_margin_strip_has_no_source_clipped_issue(self):
        im = self.cut_image(); im[155:] = 255
        sys, manifest, load = system_case([im.copy() for _ in range(8)])
        manifest.update(self.manifest())
        _im, rec = rs.build_strip(sys,manifest,load,chrome=False)
        self.assertNotIn(rs.SOURCE_CLIPPED,rec["issues"])
        self.assertNotIn("source_clipped",rec)

    def test_source_clipped_alternate_carries_issue_and_mapped_columns(self):
        sys={"id":"s","index":0,"slot_id":"slot","layout":"bottom_bar","episode_ids":[],"observations":[]}
        rec={"box_crop":[20,0,780,160],"staff_gap_px":12,"staff_y_strip":[50,62,74,86,98],
             "source_clipped":{"sides":["bottom"],"columns":[400,424]}}
        alt={"suffix":"alt1","box_crop":[10,0,790,160],"size":[780,160],"path":"unused.png", 
             "t_start":0,"t_end":1,"obs_ids":[],"region_ids":[],"finishing":{"issues":[rs.TRANSLUCENT_PLATE_GRAY]}}
        entry,_=rp.alternate_system(sys,rec,alt,None)
        self.assertIn(rs.SOURCE_CLIPPED,entry["issues"])
        self.assertIn(rs.UNCERTAIN_MARK_KEPT,entry["issues"])
        self.assertIn(rs.TRANSLUCENT_PLATE_GRAY,entry["issues"])
        self.assertEqual(entry["strip"]["source_clipped"]["columns"],[410,434])

    def test_even_one_native_paper_row_below_ink_disproves_clipping(self):
        im=self.cut_image(); im[-1]=255
        self.assertIsNone(rs.source_clipping(im,[20,0,780,160],self.manifest()))
