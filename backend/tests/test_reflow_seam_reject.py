"""Frozen seam overrides, source recovery and transactional run repairs."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import observations as ob, reflow_jump as jump, reflow_pipeline as pipeline
from app.pipeline import reflow_seam_reject as repair, system_tracking as tracking
from app.pipeline.process_control import OperationCancelled
from app.schemas import JobReviewExportRequest
from reflow_fixture import build, loader
from test_reflow_jump import JUMP, VIEW_W, long_score
from test_reflow_jump_minority import frames_with_dot, blank_spot
from test_reflow_measure import Doc, measure_strip


def frozen():
    seams = []
    for i in range(4):
        seams.append(dict(id=f's{i}', slot_id='slot', a=f'e{i}', b=f'e{i+1}', verified=False,
                          kind='unverified', resolution=dict(status='resolved', dx=100, dy=0), status='resolved'))
    run = dict(slot_id='slot', start=0, end=20, chains=[['e0','e1','e2','e3','e4']], secondary=True)
    run['panorama_chains'] = jump.panorama_chains(run, seams)
    return dict(seams=seams, runs=[run])


class OverrideTests(unittest.TestCase):
    def trimmed_panel_case(self, note=None, retained_note=False, tone=10, displays=5):
        ids=list('abcde')[:displays];comps={};covered={};eps={};obs={};seams=[]
        for k,d in enumerate(ids):
            image=np.full((60,200,3),250,np.uint8)
            for x in range(30,200,20): cv2.line(image,(x,35),(x,45),(10,10,10),2)
            if k:
                cv2.rectangle(image,(20,7),(37,15),(170,170,170),-1)
                cv2.line(image,(5,0),(5,55),(10,10,10),1)  # opaque, appearance-matched panel frame
            comps[d]=image;covered[d]=np.zeros(200,bool)
            eps[d]=dict(id=d,confirmed=True,slot_id='slot',staff_gap_px=10,t_start=k*4,t_end=k*4+3,
                        observation_ids=['o'+d],region_ids=['r'])
            obs['o'+d]=dict(id='o'+d,t_sec=k*4,crop_size=[200,60],system_regions=[])
            if k: seams.append(dict(id='s'+str(k),slot_id='slot',a=ids[k-1],b=d,verified=True,kind='jump',dx=100))
        if note is not None:
            cv2.circle(comps['b'],note,4,(tone,tone,tone),-1)
            if retained_note: cv2.circle(comps['a'],(note[0]+100,note[1]),4,(tone,tone,tone),-1)
        pairs={(s['a'],s['b']):s for s in seams}
        chain=ids[1:];pano,info=jump.build_panorama(chain,pairs,comps,covered,30,10,jump.CONFIG,left_trim=80)
        target,_=jump.coverage_ink(comps['a'],10,[],jump.CONFIG['ink_level'],jump.COVERAGE_CONFIG)
        tol=jump.PRESERVE_CONFIG['match_tol_px']
        target=cv2.dilate(target.astype(np.uint8),np.ones((2*tol+1,2*tol+1),np.uint8))>0
        ledger=jump.panorama_preservation(chain,info,pano,comps,covered,eps,obs,30,jump.CONFIG,
            chrome_info={'samples':0},analysis_chain=ids,start_trim=80,
            retained_left={'ink':target,'display':'a','dx':100,'dy':0})
        effective=copy.deepcopy(seams);effective[0]['user_rejected']=True
        run=dict(slot_id='slot',start=0,end=displays*4-1,chains=[ids])
        run['panorama_chains']=jump.panorama_chains(run,effective)
        coverage=jump.account_coverage(dict(episodes=list(eps.values())),dict(observations=list(obs.values())),
            dict(runs=[run],seams=effective,slots=[dict(slot_id='slot',panel={'right':30})]),
            exported={'chains':[[0,0],[0,1]],'overlap_conflicts':ledger['conflicts']},composites=comps)
        return ledger,coverage

    def test_rejected_start_pure_panel_trim_keeps_coverage_complete(self):
        for displays in (4,5):  # includes the minimum four-display jump run
            with self.subTest(displays=displays):
                ledger,coverage=self.trimmed_panel_case(displays=displays)
                self.assertTrue(ledger['content_preserved'],ledger['conflicts'])
                self.assertEqual(coverage['status'],'complete')
                self.assertFalse(coverage['unresolved'])
                self.assertTrue(any(e['panel_px']>0 and e['unexplained_px']==0 for e in ledger['start_trim_evidence']))

    def test_rejected_start_unexplained_notation_inside_or_crossing_trim_stays_incomplete(self):
        # Exercise the measured panel itself, its overflow, and a note crossing the trim.
        for displays in (4,5):
            for point,tone in [((20,25),10),((50,25),10),((78,25),10),((20,25),170),((50,25),170),((78,25),170)]:
                with self.subTest(point=point,tone=tone,displays=displays):
                    ledger,coverage=self.trimmed_panel_case(point,tone=tone,displays=displays)
                    self.assertFalse(ledger['content_preserved'])
                    self.assertEqual(coverage['status'],'incomplete')
                    self.assertTrue(any(c['display']=='b' for c in ledger['conflicts']))
                    self.assertTrue(any(e['unexplained_px']>6 for e in ledger['start_trim_evidence']))

    def test_rejected_start_notation_proven_on_retained_edge_is_not_lost(self):
        ledger,coverage=self.trimmed_panel_case((50,25),retained_note=True)
        self.assertTrue(ledger['content_preserved'],ledger['conflicts'])
        self.assertEqual(coverage['status'],'complete')
        self.assertTrue(any(e['retained_overlap_px']>0 and e['retained_display']=='a'
                            for e in ledger['start_trim_evidence']))

    def test_unexplained_repaired_start_cannot_publish_only_an_alternate(self):
        ledger,coverage=self.trimmed_panel_case((20,25))
        self.assertEqual(coverage['status'],'incomplete')
        rec={'jump':{'left_trim_native':80,'unverified_seam_before':'s1',
                     'owners':[{'display':'b'}],'preservation':ledger}}
        with self.assertRaises(repair.SeamRepairError) as ctx:
            repair._require_repaired_start_output([({},rec)])
        self.assertEqual(ctx.exception.code,'SEAM_REPAIR_INCOMPATIBLE')

    def test_split_keeps_original_panel_label_votes_and_real_conflicts(self):
        ids=list('abcde'); comps={};eps={};obs={};covered={};seams=[]
        for i,d in enumerate(ids):
            image=np.full((60,200,3),250,np.uint8)
            for x in range(30,200,20): cv2.line(image,(x,20),(x,40),(10,10,10),2)
            if i: cv2.rectangle(image,(34,5),(37,15),(170,170,170),-1)
            comps[d]=image;covered[d]=np.zeros(200,bool)
            eps[d]=dict(id=d,slot_id='slot',confirmed=True,staff_gap_px=10,t_start=i*4,t_end=i*4+3,
                        observation_ids=['o'+d],region_ids=['r'])
            obs['o'+d]=dict(id='o'+d,system_regions=[])
            if i: seams.append(dict(id='s'+str(i),slot_id='slot',a=ids[i-1],b=d,verified=True,kind='jump',dx=100))
        pairs={(s['a'],s['b']):s for s in seams}
        def audit(displays,context=None):
            pano,info=jump.build_panorama(displays,pairs,comps,covered,30,10,jump.CONFIG)
            return jump.panorama_preservation(displays,info,pano,comps,covered,eps,obs,30,jump.CONFIG,
                                              chrome_info={'samples':0},analysis_chain=context)
        baseline=audit(ids)
        local=audit(ids[:2])
        self.assertFalse(baseline['conflicts'])
        self.assertTrue(any(c['display']=='b' for c in local['conflicts']))  # Old, shortened vote population.
        repaired=audit(ids[:2],ids)
        self.assertFalse(repaired['conflicts'])
        self.assertEqual([c['box_crop'] for c in repaired['panel_label_recurring']],
                         [c['box_crop'] for c in baseline['panel_label_recurring'] if c['display']=='b'])
        # Dark notation beside the recurring gray label still needs actual output evidence.
        cv2.rectangle(comps['b'],(48,5),(51,15),(10,10,10),-1)
        original_conflicts=[c['box_crop'] for c in audit(ids)['conflicts'] if c['display']=='b']
        repaired_conflicts=[c['box_crop'] for c in audit(ids[:2],ids)['conflicts'] if c['display']=='b']
        self.assertTrue(original_conflicts)
        self.assertEqual(repaired_conflicts,original_conflicts)

    def test_left_trim_keeps_every_right_hand_pixel_and_owner_transform(self):
        image=np.full((60,200,3),250,np.uint8)
        image[:,:40]=170  # panel chrome
        cv2.circle(image,(48,30),3,(10,10,10),-1)  # notation immediately after its boundary
        cv2.circle(image,(196,30),3,(10,10,10),-1)  # last source pixels must stay
        pano,info=jump.build_panorama(['b'],{}, {'b':image},{'b':np.zeros(200,bool)},40,10,jump.CONFIG,left_trim=40)
        self.assertTrue(np.array_equal(pano,image[:,40:]))
        self.assertTrue(info['owner_map_complete'])
        self.assertEqual(info['owners'][0]['owned_cols_display'],[40,200])
        self.assertEqual(info['owners'][0]['offset_x'],-40)
        self.assertEqual(info['owners'][0]['panel_columns_used'],0)

    def test_rejection_precedes_verified_and_resolved_offsets(self):
        for seam in (dict(verified=True,kind='jump',dx=100),dict(verified=False,resolution=dict(status='resolved',dx=100))):
            seam['user_rejected']=True
            self.assertIsNone(jump.seam_offset(seam)); self.assertIsNone(jump._link_dx(seam))
            self.assertEqual(jump.effective_seam_status(seam),'unverified')

    def test_neighbours_and_original_evidence_unchanged(self):
        original=frozen(); saved=copy.deepcopy(original); changed=jump.apply_seam_rejections(original,['s1'])
        self.assertEqual(original,saved)
        for s in changed['seams']:
            before=next(x for x in original['seams'] if x['id']==s['id'])
            self.assertEqual({k:v for k,v in s.items() if k!='user_rejected'},before)
            self.assertEqual(jump.seam_offset(s),None if s['id']=='s1' else (100,0))
        self.assertEqual(changed['runs'][0]['secondary'],True)

    def test_adjacent_rejections_keep_singleton_and_run_ends(self):
        changed=jump.apply_seam_rejections(frozen(),['s1','s2'])
        self.assertEqual([c['displays'] for c in changed['runs'][0]['panorama_chains']],[['e0','e1'],['e2'],['e3','e4']])
        ends=jump.apply_seam_rejections(frozen(),['s0','s3'])
        self.assertEqual([c['displays'] for c in ends['runs'][0]['panorama_chains']],[['e0'],['e1','e2','e3'],['e4']])

    def test_already_unverified_is_idempotent(self):
        original=frozen(); original['seams'][1]['resolution']['status']='unverified'
        one=jump.apply_seam_rejections(original,['s1'])
        two=jump.apply_seam_rejections(one,['s1'])
        self.assertEqual(one,two)
        self.assertEqual(jump.panorama_chains(original['runs'][0],original['seams']),one['runs'][0]['panorama_chains'])
        with tempfile.TemporaryDirectory() as td:
            pipeline._dump(original,Path(td)/'jump.json')
            request=JobReviewExportRequest(keep_captures=['unused'],rejected_seam_ids=['s1'])
            checked=repair.validate_request(dict(workspace=td,systems=[],revision=1),[],[],request)
            self.assertEqual(checked['changed_runs'],[])

    def test_measure_chain_barrier_keeps_both_edge_windows(self):
        with tempfile.TemporaryDirectory() as td:
            doc=Doc(Path(td)); a=doc.add('a',*measure_strip(2)); b=doc.add('b',*measure_strip(2))
            a['strip']['jump']=dict(run=0,chain=0,unverified_seam_after='s')
            b['strip']['jump']=dict(run=0,chain=1,unverified_seam_before='s')
            decided=pipeline.resolve_dependencies(doc.systems)[0]
            from app.pipeline import reflow_measure as measure
            atoms=measure.build_atoms(decided,target_gap_px=16,context=doc.context)
            self.assertFalse(atoms['strips']['b']['join'].get('mode'))
            self.assertEqual(atoms['strips']['b']['join']['refused'],'JUMP_CHAIN_BREAK')
            self.assertNotIn('prev_tail_trim',atoms['strips']['b']['join'])
            self.assertTrue(any(u['system_id']=='a' for u in atoms['atoms']))
            self.assertTrue(any(u['system_id']=='b' for u in atoms['atoms']))

    def test_selection_rejects_partial_reversed_interrupted_and_alternate_runs(self):
        with tempfile.TemporaryDirectory() as td:
            request=JobReviewExportRequest(keep_captures=['unused'],rejected_seam_ids=['s1'])
            with self.assertRaises(repair.SeamRepairError) as ctx:
                repair.validate_request(dict(workspace=td,revision=1),[],[],request)
            self.assertEqual((ctx.exception.code,ctx.exception.status),('SEAM_UNKNOWN',422))
            pipeline._dump(frozen(),Path(td)/'jump.json')
            a=dict(id='a',strip={'jump':dict(run=0,chain=0,chunk=0)})
            b=dict(id='b',strip={'jump':dict(run=0,chain=0,chunk=1)})
            other=dict(id='other',strip={})
            alt=dict(id='alt',alternate_of='a',strip={})
            systems=[a,alt,b,other]
            r=dict(workspace=td,revision=1,systems=systems)
            request=JobReviewExportRequest(keep_captures=['unused'],rejected_seam_ids=['s1'])
            for selected in ([a],[b,a],[a,other,b],[a,alt,b]):
                with self.subTest(ids=[s['id'] for s in selected]),self.assertRaises(repair.SeamRepairError) as ctx:
                    repair.validate_request(r,systems,selected,request)
                self.assertEqual((ctx.exception.code,ctx.exception.status),('SEAM_REPAIR_SELECTION',409))
            self.assertEqual(repair.validate_request(r,systems,[a,b],request)['changed_runs'],[0])

    def test_dev_ledger_replaces_overlap_decisions_and_resolves_both_evidence_roots(self):
        from app.pipeline import reflow_ledger as ledger, reflow_ledger_assembly as assembly
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);img=np.full((40,60,3),250,np.uint8);cv2.circle(img,(20,20),4,(20,20,20),-1)
            def fragment(did,folder):
                return ledger.record_obligations(source_video='source',display_id=did,occurrence_id=did,
                    members=[dict(id=did+'-o',timestamp=0,image=img,roi_origin=[0,0],usable=True,occluded=np.zeros(img.shape[:2],bool))],evidence_dir=root/folder)
            old=fragment('jump:a','old');unchanged=fragment('jump:other','old')
            old['display_dispositions'].append(dict(display_id='jump:a',kind='old_overlap_equivalence'))
            base=assembly.merge_ledgers(old,unchanged)
            fresh=fragment('jump:a','new')
            records=[dict(system_id='jmp-01-001',ledger=fresh,ledger_chain=[dict(display_id='jump:a',strip_id='jmp-01-001')])]
            merged,chains=repair._replace_ledger(base,records,{'jmp-01-001'},pipeline)
            self.assertFalse(any(d['kind']=='old_overlap_equivalence' for d in merged['display_dispositions']))
            self.assertEqual(next(d for d in merged['displays'] if d['id']=='jump:other'),
                             {**unchanged['displays'][0], 'members': next(d for d in merged['displays'] if d['id']=='jump:other')['members']})
            resolver=ledger.EvidenceResolver(merged)
            self.assertTrue(all(list(resolver.views(item)) for item in merged['items']))
            self.assertEqual(set(chains),{'jmp-01-001'})


class BatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup); self.root=Path(self.td.name)
        self.source=self.root/'source.avi'
        writer=cv2.VideoWriter(str(self.source),cv2.VideoWriter_fourcc(*'MJPG'),10,(80,60))
        for i in range(10): writer.write(np.full((60,80,3),30+i*10,np.uint8))
        writer.release()
        frames=list(ob.iter_frames_at(self.source,[.1,.3,.5,.7]))
        self.images={}
        observations=[]
        for i,(_target,pts,frame) in enumerate(frames):
            o=dict(id=f'o{i}',t_sec=pts,applied_roi=[[4,4],[76,4],[76,56],[4,56]],crop_size=[36,26],frame_path=f'{i}.png')
            self.images[o['id']]=ob.crop_observation(frame,o['applied_roi'],o['crop_size']); observations.append(o)
        self.manifest=dict(observations=observations,source=dict(path=str(self.source),sha256=ob.file_sha256(self.source),frame_size=[80,60]))
        for o in observations: cv2.imwrite(str(self.root/o['frame_path']),self.images[o['id']])
    def recover(self):
        return ob.recover_observation_images(self.root,self.manifest,self.images,self.root/'recovery',max_bytes=1)
    def test_retained_crops_work_offline_and_decode_is_not_called(self):
        self.source.unlink()
        with patch.object(ob,'iter_frames_at',side_effect=AssertionError('unexpected decode')):
            load=self.recover()
            for o in self.manifest['observations']: self.assertTrue(np.array_equal(load(o),self.images[o['id']]))
    def test_batched_decode_parity_reuses_retained_and_opens_once(self):
        for o in self.manifest['observations'][1:]: (self.root/o['frame_path']).unlink()
        with patch.object(ob,'iter_frames_at',wraps=ob.iter_frames_at) as decode:
            load=self.recover(); self.assertEqual(decode.call_count,1)
            for o in self.manifest['observations']: self.assertTrue(np.array_equal(load(o),self.images[o['id']]))
            for o in self.manifest['observations']: load(o)
            self.assertEqual(decode.call_count,1)
        self.assertFalse((self.root/'recovery'/'o0.png').exists())
    def test_missing_source_and_wrong_hash_fail_closed(self):
        (self.root/'0.png').unlink()
        for wrong in ('hash','missing'):
            if wrong=='hash': self.manifest['source']['sha256']='0'*64
            else: self.source.unlink()
            with self.subTest(wrong=wrong),self.assertRaises(ob.SeamRepairSourceUnavailable): self.recover()
    def test_timing_and_shape_mismatch(self):
        (self.root/'0.png').unlink(); o=self.manifest['observations'][0]
        for pts,shape in ((o['t_sec']+.01,(60,80,3)),(o['t_sec'],(61,80,3))):
            with patch.object(ob,'iter_frames_at',return_value=iter([(round(o['t_sec'],6),pts,np.zeros(shape,np.uint8))])):
                with self.assertRaises(ob.SeamRepairSourceUnavailable): self.recover()
    def test_cancellation_during_decode_releases_capture(self):
        class Cap:
            released=False
            def isOpened(self): return True
            def get(self,key): return 10 if key==cv2.CAP_PROP_FPS else 0
            def grab(self): return True
            def release(self): self.released=True
        cap=Cap(); calls=[]
        def stop():
            calls.append(1)
            if len(calls)==3: raise OperationCancelled()
        with patch.object(ob.cv2,'VideoCapture',return_value=cap):
            with self.assertRaises(OperationCancelled): list(ob.iter_frames_at(self.source,[100],checkpoint=stop))
        self.assertTrue(cap.released)


class RepairExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td=tempfile.TemporaryDirectory(); cls.root=Path(cls.td.name); cls.workspace=cls.root/'reflow'; cls.workspace.mkdir()
        score=long_score(bars=12); offsets=list(range(0,score.shape[1]-VIEW_W+1,JUMP))
        dot=blank_spot(score[:,:VIEW_W],(150,600))
        manifest,images=build(frames_with_dot(score,offsets,dot)); load=loader(images)
        tr=tracking.build_episodes(manifest,load)
        j=jump.analyse_jumps(tr,manifest,load,keep_composites=True)
        for s in j['seams'][:2]:
            s.update(verified=False,status='resolved',resolution=dict(status='resolved',dx=s['dx'],dy=s.get('dy',0),evidence=['test_frozen']))
        j['runs'][0]['panorama_chains']=jump.panorama_chains(j['runs'][0],j['seams'])
        built=jump.build_jump_systems(j,tr,manifest,cls.workspace/'strips',composites=j['_composites'],covered=j['_covered'],load=load)
        systems=[]; occ=[]; chains={}
        for o,r in built:
            o['index']=len(systems)+1; systems.append(repair._public_system(o,r)); occ.append(o); chains[o['id']]=r['ledger_chain']
            for alt in r['minority_content']['alternates']:
                e,oe=pipeline.alternate_system(o,r,alt,None); systems.append(e); occ.append(oe); pipeline._alternate_ledger_chain({'displays':[]},chains,e,ledger=False)
        for o in manifest['observations']:
            o['frame_path']=f"frames/{o['id']}.png"; p=cls.workspace/'manifest'/o['frame_path']; p.parent.mkdir(parents=True,exist_ok=True); cv2.imwrite(str(p),images[o['id']])
        for name,data in [('manifest',manifest),('tracking',tr),('occurrences',dict(systems=occ)),('ledger_chains',chains)]: pipeline._dump(data,cls.workspace/f'{name}.json')
        jump.write_json(j,cls.workspace/'jump.json')
        cls.record=dict(systems=systems,workspace=str(cls.workspace),revision=1,header={'title':'Test'},source_class={},dev_ledger=False)
        cls.seams=[s['id'] for s in j['seams'][:2]]
    @classmethod
    def tearDownClass(cls): cls.td.cleanup()
    def setUp(self):
        self.td2=tempfile.TemporaryDirectory(); self.addCleanup(self.td2.cleanup); self.root2=Path(self.td2.name); self.artifact=self.root2/'job'
        shutil.copytree(self.root,self.artifact)
        # All fixture references are local to this test.
        for f in self.artifact.rglob('*.json'): f.write_text(f.read_text(encoding="utf-8").replace(str(self.root),str(self.artifact)))
        record=json.loads(json.dumps(self.record).replace(str(self.root),str(self.artifact)))
        self.store=JobStore(self.root2); self.job=Job(id='job',source_type='file',file_path=None,youtube_url=None,options={'export':{'formats':['png','pdf']},'measure_reflow':True},artifact_dir=str(self.artifact),status=JobStatus.DONE,result=dict(output_model='clean_reflow_v1',reflow=record))
        self.store.create(self.job)
    def request(self,**kw):
        paths=[s['strip_path'] for s in self.job.result['reflow']['systems'] if s['included']]
        return JobReviewExportRequest(keep_captures=paths,**kw)
    def export(self,request):
        with patch('app.main.job_store',self.store): return main.review_export('job',request)
    def test_validation_stale_unknown_not_run_duplicates_and_selection(self):
        for kw,status,code in [(dict(base_revision=0),409,'STALE_REVISION'),(dict(rejected_seam_ids=['unknown']),422,'SEAM_UNKNOWN'),(dict(rejected_seam_ids=self.seams*2),422,'SEAM_UNKNOWN')]:
            with self.subTest(kw=kw),self.assertRaises(HTTPException) as ctx: self.export(self.request(**kw))
            self.assertEqual(ctx.exception.status_code,status); self.assertIn(code,ctx.exception.detail)
        selected=[s['strip_path'] for s in self.job.result['reflow']['systems']]
        if len(selected)>1:
            with self.assertRaises(HTTPException) as ctx: self.export(JobReviewExportRequest(keep_captures=selected,rejected_seam_ids=[self.seams[0]]))
            self.assertEqual(ctx.exception.status_code,409); self.assertIn('SEAM_REPAIR_SELECTION',ctx.exception.detail)
        self.assertFalse((self.artifact/'reflow_revisions').exists())
        r=self.job.result['reflow']; j=repair.read(Path(r['workspace'])/'jump.json')
        j['runs']=[]; pipeline._dump(j,Path(r['workspace'])/'jump.json')
        with self.assertRaises(HTTPException) as ctx: self.export(self.request(rejected_seam_ids=[self.seams[0]]))
        self.assertEqual(ctx.exception.status_code,422); self.assertIn('SEAM_UNKNOWN',ctx.exception.detail)

    def test_missing_source_without_frames_keeps_previous_files_and_metadata(self):
        self.export(self.request()); before=copy.deepcopy(self.job.result)
        previous=(self.artifact/'export'/'sheet_export.pdf').read_bytes()
        shutil.rmtree(self.artifact/'reflow'/'manifest'/'frames')
        with self.assertRaises(HTTPException) as ctx: self.export(self.request(rejected_seam_ids=[self.seams[0]]))
        self.assertEqual(ctx.exception.status_code,409); self.assertIn('SEAM_REPAIR_SOURCE_UNAVAILABLE',ctx.exception.detail)
        self.assertEqual(self.job.result,before); self.assertEqual((self.artifact/'export'/'sheet_export.pdf').read_bytes(),previous)
        self.assertEqual(list((self.artifact/'reflow_revisions').iterdir()),[])
    def test_repair_persists_overrides_and_boundary_endpoints_then_clear(self):
        old_hash=self.job.result['reflow']['systems'][0]['strip']['uncut_pixels_sha256']
        self.export(self.request(rejected_seam_ids=self.seams)); r=self.job.result['reflow']; j=repair.read(Path(r['workspace'])/'jump.json')
        self.assertEqual(r['rejected_seam_ids'],sorted(self.seams)); self.assertEqual(len(j['runs'][0]['panorama_chains']),3)
        self.assertEqual(len(j['runs'][0]['panorama_chains'][1]['displays']),1)
        self.assertTrue(any(s.get('alternate_of') for s in r['systems']))
        self.assertEqual(r['coverage']['reference']['runs_exported'],[0])
        self.assertEqual(r['coverage']['reference']['chains'],[[0,0],[0,1],[0,2]])
        primary=[s for s in r['systems'] if s['included']]
        self.assertEqual([s['strip']['jump']['chain'] for s in primary],[0,1,2])
        # Without a detected panel, both rejected-side views retain all their music.
        for s in primary[1:]:
            owner=s['strip']['jump']['owners'][0]
            self.assertEqual(owner['strip_cols'][0]-owner['offset_x'],0)
        boundaries=[s for l in r['line_review'] for s in l['seams'] if s.get('boundary')]
        for sid in self.seams:
            ends=[s for s in boundaries if s['id']==sid]; self.assertEqual({s['boundary'] for s in ends},{'start','end'})
            self.assertEqual(len(ends),2); self.assertTrue(all(s['user_rejected'] and s['status']=='unverified' for s in ends))
            self.assertEqual(ends[0]['jump_time'],ends[1]['jump_time'])
        snapshot=r['original_analysis_path']; workspace=r['workspace']
        self.export(self.request()); self.assertEqual(self.job.result['reflow']['rejected_seam_ids'],sorted(self.seams))
        self.assertEqual(self.job.result['reflow']['workspace'],workspace)
        self.export(self.request(rejected_seam_ids=[])); r=self.job.result['reflow']; self.assertEqual(r['rejected_seam_ids'],[])
        self.assertEqual(r['original_analysis_path'],snapshot); self.assertEqual(r['systems'][0]['strip']['uncut_pixels_sha256'],old_hash)
    def test_rollback_write_contract_digest_install_metadata_and_cancel(self):
        self.export(self.request()); before=copy.deepcopy(self.job.result)
        old_files={str(p.relative_to(self.artifact/'export')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.artifact/'export').rglob('*') if p.is_file()}
        cases=[('app.pipeline.export.export_composed_pages',RuntimeError('write failed')),('app.pipeline.export.verify_composed_export',RuntimeError('contract failed')),('app.main._verify_reflow_ledger',RuntimeError('digest failed')),('app.main._install_verified_reflow_export',RuntimeError('install failed')),
               ('app.pipeline.reflow_seam_reject._require_repaired_start_output',repair.SeamRepairError('SEAM_REPAIR_INCOMPATIBLE','unexplained notation in panel trim'))]
        for target,error in cases:
            with self.subTest(target=target),patch(target,side_effect=error),self.assertRaises(HTTPException): self.export(self.request(rejected_seam_ids=[self.seams[0]]))
            self.assertEqual(self.job.result,before)
            now={str(p.relative_to(self.artifact/'export')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.artifact/'export').rglob('*') if p.is_file()}; self.assertEqual(now,old_files)
            self.assertEqual(list((self.artifact/'reflow_revisions').iterdir()),[])
        original_set=self.store.set_state; once=[False]
        def fail_once(*args,**kwargs):
            if not once[0]: once[0]=True; raise OSError('metadata failed')
            return original_set(*args,**kwargs)
        with patch.object(self.store,'set_state',side_effect=fail_once),self.assertRaises(HTTPException): self.export(self.request(rejected_seam_ids=[self.seams[0]]))
        self.assertEqual(self.job.result,before)
        with patch.object(ob,'recover_observation_images',side_effect=OperationCancelled()),self.assertRaises(OperationCancelled): self.export(self.request(rejected_seam_ids=[self.seams[0]]))
        self.assertEqual(self.job.result,before); self.assertEqual(list((self.artifact/'reflow_revisions').iterdir()),[])
    def test_run_filter_retains_original_index(self):
        j=repair.read(self.artifact/'reflow'/'jump.json'); tr=repair.read(self.artifact/'reflow'/'tracking.json'); m=repair.read(self.artifact/'reflow'/'manifest.json')
        j['runs'].insert(0,copy.deepcopy(j['runs'][0]))
        j['runs'][0]['secondary']=True
        load=tracking.manifest_image_loader(self.artifact/'reflow'/'manifest',m)
        comps={}; covered={}; obs_by={o['id']:o for o in m['observations']}
        for e in tr['episodes']:
            if not e['confirmed']: continue
            r=jump.display_record(e,m,load,obs_by,j['config'],keep_composite=True); comps[e['id']]=r['composite']; covered[e['id']]=r['covered']
        built=jump.build_jump_systems(j,tr,m,self.artifact/'filtered',composites=comps,covered=covered,load=load,run_indices=[1])
        self.assertTrue(built); self.assertTrue(all(r['jump']['run']==1 and o['id'].startswith('jmp-02-') for o,r in built))

    def test_rejected_chain_uses_only_panel_trim_and_selects_unique_overlap_notation(self):
        from test_reflow_jump import jump_frames
        score=long_score(bars=12);offsets=list(range(0,score.shape[1]-VIEW_W+1,JUMP))
        manifest,images=build(jump_frames(score,offsets,panel=70))
        load=loader(images);tr=tracking.build_episodes(manifest,load)
        original=jump.analyse_jumps(tr,manifest,load,keep_composites=True)
        self.assertEqual(len(original['runs']),1)
        for s in original['seams'][1:3]:
            s.update(verified=False,status='resolved',resolution=dict(status='resolved',dx=s['dx'],dy=s.get('dy',0)))
        pairs={(s['a'],s['b']):s for s in original['seams']}
        original_ids=original['runs'][0]['panorama_chains'][0]['displays']
        panel=original['slots'][0]['panel']['right']
        _pano,info=jump.build_panorama(original_ids,pairs,original['_composites'],original['_covered'],panel,14,jump.CONFIG)
        starts={o['display']:o['owned_cols_display'][0] for o in info['owners']}
        target=original['seams'][1]['b']
        comp=original['_composites'][target]
        point=blank_spot(comp,(panel+6,starts[target]-6))
        self.assertLess(point[0]+3,starts[target])
        cv2.circle(comp,point,3,(10,10,10),-1)
        ep=next(e for e in tr['episodes'] if e['id']==target)
        for oid in ep['observation_ids']:
            cv2.circle(images[oid],point,3,(10,10,10),-1)
        for count in (1,2):
            rejected=[s['id'] for s in original['seams'][1:1+count]]
            effective=jump.apply_seam_rejections(original,rejected)
            built=jump.build_jump_systems(effective,tr,manifest,self.artifact/f'panel-{count}',
                composites=original['_composites'],covered=original['_covered'],load=load)
            printed=False
            for occ,rec in built:
                jrec=rec['jump']
                if not jrec['unverified_seam_before']: continue
                owner=jrec['owners'][0];start=owner['strip_cols'][0]-owner['offset_x'];d=owner['display']
                self.assertEqual(start,panel)
                self.assertEqual(jrec['left_trim_basis'],'detected_panel')
                self.assertFalse(jrec['own_clef'])  # only the run's verified clean replica may be added
                self.assertEqual(owner['panel_columns_used'],0)
                if len(jrec['owners'])==1:
                    self.assertEqual(owner['strip_cols'][1]-owner['offset_x'],VIEW_W)
                if d==target:
                    primary=repair._public_system(dict(occ,index=1),rec)
                    self.assertTrue(primary['included'])
                    self.assertNotIn('alternate_of',primary)
                    image=cv2.imread(primary['strip_path'])
                    x=point[0]+owner['offset_x'];y=point[1]+owner['offset_y']
                    self.assertGreater(int((image[y-2:y+3,x-2:x+3].min(axis=2)<80).sum()),10)
                    printed=True
            self.assertTrue(printed,'unique overlap notation must be in a selected primary')

if __name__=='__main__': unittest.main()
