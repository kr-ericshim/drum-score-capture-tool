"""W-H: uncertainty is bundled; explanations require geometry and recovery."""
import base64
import unittest
import cv2
import numpy as np
from app.pipeline import minority_content as mc, reflow_strips as rs, reflow_boundaries as rb
from test_reflow_visibility_marks import paper, system_case


class ReviewBundleTest(unittest.TestCase):
    def test_single_pixel_strokes_once_each_have_one_bundle_with_every_raw_patch(self):
        images = [paper() for _ in range(12)]
        images[5][110:122,420] = 0
        images[6][110:122,425] = 0
        system, manifest, load = system_case(images)
        _, rec = rs.build_strip(system, manifest, load, chrome=False)
        self.assertIn(rs.UNCERTAIN_MARK_KEPT,rec['issues'])
        alts = rec['minority_content']['alternates']
        self.assertEqual(len(alts),1)
        for x in (420,425):
            patches = alts[0]['evidence_patches']
            self.assertTrue(any(self.stroke(v,x) for v in patches))
        self.assertTrue(all(e['classification']==rs.UNCERTAIN_MARK_KEPT for e in rec['minority_content']['events']))

    @staticmethod
    def stroke(v,x):
        raw = cv2.imdecode(np.frombuffer(base64.b64decode(v['raw_png_base64']),np.uint8),cv2.IMREAD_COLOR)
        a,b = v['box_crop'][:2]
        return 0 <= x-a < raw.shape[1] and 0 <= 110-b < 122-b <= raw.shape[0] and bool((raw[110-b:122-b,x-a]<100).all())

    def test_excluded_candidate_bundle_stays_on_excluded_system(self):
        from pathlib import Path
        import tempfile
        images=[paper() for _ in range(12)]; images[5][110:122,420]=0
        system,manifest,load=system_case(images); system['included']=False
        with tempfile.TemporaryDirectory() as d:
            records=rs.build_strips({'systems':[system]},manifest,load,Path(d))
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['system_id'],system['id'])
            self.assertEqual(len(records[0]['minority_content']['alternates']),1)

    def test_written_bundle_png_evidence_is_exact_and_hashed(self):
        from pathlib import Path
        import tempfile,hashlib
        images=[paper() for _ in range(12)];images[5][110:122,420]=0
        system,manifest,load=system_case(images)
        with tempfile.TemporaryDirectory() as d:
            rec=rs.build_strips({'systems':[system]},manifest,load,Path(d))[0]
            evidence=rec['minority_content']['alternates'][0]['evidence_patches'][0]
            raw_path=Path(evidence['raw_path'])
            self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(),evidence['raw_png_sha256'])
            self.assertNotIn('raw_png_base64',evidence)
            raw=cv2.imread(str(raw_path));x0,y0,x1,y1=evidence['box_crop']
            self.assertTrue(np.array_equal(raw,images[5][y0:y1,x0:x1]))


class PositiveIdentificationTest(unittest.TestCase):
    def case(self, recovered=True):
        ref=np.full((100,240),255,np.uint8)
        ref[45:48,100:103]=0 if recovered else 255
        images=[]; masks={}; grays={}
        for i,x in enumerate((20,100,180)):
            im=np.repeat(ref[...,None],3,axis=-1)
            im[45:48,100:103]=0
            im[10:90,x:x+2]=(200,60,200)
            images.append(im);grays[i]=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
            masks[i]=np.zeros(ref.shape,bool)
        masks[1][20:80,100:102]=True
        ev={'members':[1],'box':[100,20,102,80]}
        return ev,masks,grays,ref,mc.cursor_positions(images,12)

    # These frames are aligned by construction. In production reflow_strips
    # supplies the composer's measured shifts; this near-blank fixture has too
    # little texture for the fallback estimator, which then correctly refuses.
    ALIGNED={0:(0.0,0.0),1:(0.0,0.0),2:(0.0,0.0)}

    def test_cursor_over_dot_is_explained_only_with_clear_dot_recovery(self):
        args=self.case(True)
        self.assertIsNotNone(mc.recovered_cursor_event(*args,12,member_shifts=self.ALIGNED))
        self.assertIsNone(mc.recovered_cursor_event(*self.case(False),12,member_shifts=self.ALIGNED))
        self.assertIsNone(mc.recovered_cursor_event(*args,12))

    def test_strip_audit_colored_cursor_does_not_hide_an_unrecovered_dot(self):
        base=paper();base[110:113,420:423]=0
        xs=(40,100,160,220,280,340,420,500,560,620,680,740)
        images=[]
        for x in xs:
            im=base.copy();im[15:135,x:x+2]=(200,60,200);images.append(im)
        system,manifest,base_load=system_case([paper() for _ in xs])
        by={o['id']:images[i] for i,o in enumerate(manifest['observations'])}
        load=lambda obs:by[obs['id']]
        obs_by={o['id']:o for o in manifest['observations']}
        lost=rs.check_minority_content(system,paper(),[0,0,800,160],obs_by,load,12)
        self.assertTrue(any(e['box_crop'][0]<=420<e['box_crop'][2] and
                            e['box_crop'][1]<=110<e['box_crop'][3] for e in lost['events']))
        recovered=rs.check_minority_content(system,base,[0,0,800,160],obs_by,load,12)
        self.assertTrue(any(e['classification']=='EXPLAINED_CURSOR' for e in recovered['explained_events']))
        self.assertFalse(any(e['box_crop'][0]<=420<e['box_crop'][2] and
                             e['box_crop'][1]<=110<e['box_crop'][3] for e in recovered['events']))

    def test_real_single_pixel_stroke_near_cursor_does_not_follow_its_template(self):
        xs=(40,100,160,220,280,420,500,560,620,680,720,760)
        images=[]
        for i,x in enumerate(xs):
            im=paper();im[15:135,x:x+2]=(200,60,200)
            if i==5:im[140:153,x]=0
            images.append(im)
        system,manifest,_=system_case([paper() for _ in xs])
        by={o['id']:images[i] for i,o in enumerate(manifest['observations'])}
        audit=rs.check_minority_content(system,paper(),[0,0,800,160],
            {o['id']:o for o in manifest['observations']},lambda o:by[o['id']],12)
        self.assertTrue(any(e['box_crop'][0]<=420<e['box_crop'][2] and
                            e['box_crop'][1]<=140<e['box_crop'][3] for e in audit['events']))

    def test_translucent_background_geometry_is_not_page_turn_evidence(self):
        from unittest.mock import patch
        images=[]
        for _ in range(12):
            im=255-paper();free=(im[:,:,0]==0)
            checker=(np.indices(free.shape).sum(axis=0)//12)%2
            im[free & (checker==0)]=20;im[free & (checker==1)]=80
            images.append(im)
        system,manifest,_=system_case([paper() for _ in images])
        by={o['id']:images[i] for i,o in enumerate(manifest['observations'])}
        with patch.object(mc,'transition_evidence',side_effect=AssertionError('video geometry is not paper geometry')):
            audit=rs.check_minority_content(system,images[0],[0,0,800,160],
                {o['id']:o for o in manifest['observations']},lambda o:by[o['id']],12)
        self.assertFalse(audit['paper_opaque'])
        self.assertEqual(audit['ineligible_observations'],[])

    def test_brightening_video_behind_plate_is_not_a_score_fade(self):
        images=[]
        for i in range(12):
            im=255-paper();free=(im[:,:,0]==0)
            checker=(np.indices(free.shape).sum(axis=0)//12)%2
            delta=20 if i==5 else 0
            im[free & (checker==0)]=20+delta;im[free & (checker==1)]=80+delta
            if i==5:im[140:153,420]=255
            images.append(im)
        system,manifest,_=system_case([paper() for _ in images])
        by={o['id']:images[i] for i,o in enumerate(manifest['observations'])}
        audit=rs.check_minority_content(system,images[0],[0,0,800,160],
            {o['id']:o for o in manifest['observations']},lambda o:by[o['id']],12)
        self.assertFalse(audit['paper_opaque'])
        self.assertIn(5,audit['_eligible_masks'])
        self.assertTrue(any(e['box_crop'][0]<=420<e['box_crop'][2] and
                            e['box_crop'][1]<=140<e['box_crop'][3] for e in audit['events']))

    def test_unknown_ink_elsewhere_does_not_cancel_a_recovered_cursor_footprint(self):
        event,masks,grays,reference,positions=self.case(True)
        reference[45:48,100:103]=255
        for gray in grays.values():
            gray[45:48,100:103]=255
            gray[45:48,110:113]=0
        # Keep a simple, known moving colored continuation in the test image.
        for i,x in enumerate((20,100,180)):
            grays[i][10:90,x:x+2]=120
        self.assertIsNotNone(mc.recovered_cursor_event(event,masks,grays,reference,positions,12,
                                                       member_shifts=self.ALIGNED))

    def test_added_beams_do_not_identify_an_intact_staff_as_a_warp(self):
        ref=cv2.cvtColor(paper(),cv2.COLOR_BGR2GRAY)
        changed=ref.copy()
        for y in (10,105,125):cv2.line(changed,(20,y),(780,y+22),0,2)
        self.assertIsNone(mc.transition_evidence(changed,ref,12))

    def test_gray_dot_with_similar_luma_but_different_cursor_color_is_uncertain(self):
        ref=np.full((100,240),255,np.uint8);images={};grays={};masks={}
        for i,x in enumerate((20,100,180)):
            im=np.full((100,240,3),255,np.uint8);im[10:90,x:x+2]=(100,60,110)
            if i==1:im[45:48,x:x+2]=50
            images[i]=im;grays[i]=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);masks[i]=np.zeros(ref.shape,bool)
        masks[1][20:80,100:102]=True
        pos=mc.cursor_positions(list(images.values()),12)
        event={'members':[1],'box':[100,20,102,80]}
        self.assertIsNone(mc.recovered_cursor_event(event,masks,grays,ref,pos,12,colors=images))

    def test_nonmonotonic_or_static_colored_mark_is_not_cursor_evidence(self):
        for xs in ((20,140,80),(80,80,80)):
            ims=[]
            for x in xs:
                im=np.full((100,240,3),255,np.uint8);im[10:90,x:x+2]=(200,60,200);ims.append(im)
            self.assertEqual(mc.cursor_positions(ims,12),{})

    def test_warped_staff_is_positive_transition_but_small_mark_is_not(self):
        ref=cv2.cvtColor(paper(),cv2.COLOR_BGR2GRAY)
        warped=cv2.warpAffine(ref,np.array([[1,0,0],[.04,1,-16]],np.float32),(800,160),borderValue=255)
        self.assertIsNotNone(mc.transition_evidence(warped,ref,12))
        mark=ref.copy();mark[110:122,420]=0
        self.assertIsNone(mc.transition_evidence(mark,ref,12))

    def test_positive_transition_leaves_the_observation_denominator(self):
        images=[paper() for _ in range(12)]
        images[5]=cv2.warpAffine(images[5],np.array([[1,0,0],[.04,1,-16]],np.float32),
                                 (800,160),borderValue=(255,255,255))
        system,manifest,base_load=system_case([paper() for _ in range(12)])
        warped_id=manifest['observations'][5]['id']
        load=lambda obs:images[5] if obs['id']==warped_id else base_load(obs)
        audit=rs.check_minority_content(system,paper(),[0,0,800,160],
                                       {o['id']:o for o in manifest['observations']},load,12)
        self.assertEqual(len(audit['ineligible_observations']),1)
        self.assertEqual(audit['checked_members'],11)
        self.assertNotIn(5,audit['_eligible_masks'])
        self.assertEqual(audit['events'],[])
        self.assertTrue(audit['ineligible_observations'][0]['raw_png_base64'])

    def test_static_tilted_ink_is_not_page_warp_evidence(self):
        ref=cv2.cvtColor(paper(),cv2.COLOR_BGR2GRAY)
        for y in (15,30,45):
            cv2.line(ref,(40,y),(700,y+20),0,1)
        changed=ref.copy();changed[110:150,400:500]=180
        self.assertIsNone(mc.transition_evidence(changed,ref,12))

    def test_page_shadow_diagonal_geometry_is_required(self):
        ref=np.full((160,800),255,np.uint8)
        shadow=ref.copy();cv2.fillPoly(shadow,[np.array([[0,0],[180,0],[0,150]],np.int32)],170)
        self.assertEqual(mc.transition_evidence(shadow,ref,12)['kind'],'diagonal_page_shadow')
        rectangle=ref.copy();rectangle[30:60,300:700]=170
        self.assertIsNone(mc.transition_evidence(rectangle,ref,12))


class CorridorOwnershipTest(unittest.TestCase):
    def classify(self,event):
        im=paper();rec={'system_id':'s','layout':'bottom_bar','box_crop':[0,0,800,160],
            'staff_gap_px':12,'staff_y_strip':[50,62,74,86,98],'staff_x_strip':[20,780],
            'minority_content':{'events':[event]}}
        return rb.classify_seam(rb.analyse_strip(im,rec),330)

    def test_bbox_overlap_elsewhere_and_explained_event_do_not_block(self):
        e={'box_strip':[300,0,400,160],'foreground_support':[{'obs_id':'own','spans_crop':[[110,390,391]]}]}
        self.assertNotIn('UNRESOLVED_MINORITY_CONTENT',self.classify(e)['reasons'])
        e['foreground_support'][0]['spans_crop']=[[110,330,331]]
        self.assertIn('UNRESOLVED_MINORITY_CONTENT',self.classify(e)['reasons'])
        e['classification']='EXPLAINED_CURSOR'
        self.assertNotIn('UNRESOLVED_MINORITY_CONTENT',self.classify(e)['reasons'])

    def test_small_black_stroke_inside_gray_background_uses_its_own_support(self):
        gray=np.full((3,200),150,np.uint8);gray[:,90]=0
        owner={'obs_id':'own','spans_crop':[[y,300,500] for y in (110,111,112)]}
        ink=mc.ink_like_support([owner],lambda _: (gray,(300,110)),45)
        self.assertEqual(ink[0]['spans_crop'],[[110,390,391],[111,390,391],[112,390,391]])
        event={'ink_like':True,'foreground_support':[owner],'ink_like_foreground_support':ink}
        self.assertNotIn('UNRESOLVED_MINORITY_CONTENT',self.classify(event)['reasons'])
        gray[:,90]=150;gray[:,30]=0
        event['ink_like_foreground_support']=mc.ink_like_support([owner],lambda _: (gray,(300,110)),45)
        self.assertIn('UNRESOLVED_MINORITY_CONTENT',self.classify(event)['reasons'])

    def test_translucent_background_without_ink_contrast_does_not_block(self):
        e={'box_strip':[325,0,335,160],'ink_like':False}
        self.assertNotIn('UNRESOLVED_MINORITY_CONTENT',self.classify(e)['reasons'])
        e['ink_like']=True
        self.assertIn('UNRESOLVED_MINORITY_CONTENT',self.classify(e)['reasons'])
