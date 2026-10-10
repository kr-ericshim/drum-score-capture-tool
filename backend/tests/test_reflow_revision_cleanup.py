"""Repair revisions survive pruning and a concurrent publish wins over stale cleanup."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_pipeline


class RevisionCleanupTests(unittest.TestCase):
    def test_every_prune_mode_keeps_committed_revisions_and_pending_candidates(self):
        for keep_review in (False, True):
            for keep_ledger in (False, True):
                with self.subTest(keep_review=keep_review, keep_ledger=keep_ledger), tempfile.TemporaryDirectory() as td:
                    root=Path(td)
                    kept={}
                    for revision in ('revision-2-committed','revision-3-candidate'):
                        for relative in ('strips/primary.png','labels/label.png','ledger_evidence/raw.png','recovery/crop.png'):
                            p=root/'reflow_revisions'/revision/relative
                            p.parent.mkdir(parents=True,exist_ok=True)
                            p.write_bytes((revision+relative).encode())
                            kept[p]=p.read_bytes()
                    frames=root/'reflow'/'manifest'/'frames'
                    frames.mkdir(parents=True);(frames/'obs.png').write_bytes(b'cache')
                    report=main.prune_job_workspace(root,keep_review=keep_review,keep_ledger=keep_ledger)
                    self.assertGreater(report['removed'],0)
                    self.assertFalse(frames.exists())
                    for p,data in kept.items():self.assertEqual(p.read_bytes(),data)
                    # The normal decoded-frame prune also leaves revision output assets intact.
                    revision=root/'reflow_revisions'/'revision-2-committed'
                    raw=revision/'manifest'/'frames';raw.mkdir(parents=True)
                    (raw/'obs.png').write_bytes(b'frame')
                    with patch.dict('os.environ',{},clear=True):
                        reflow_pipeline.prune_frames({'workspace':str(revision),'dev_ledger':False})
                    self.assertFalse(raw.exists())
                    for p,data in kept.items():self.assertEqual(p.read_bytes(),data)

    def test_publish_after_first_cleanup_status_check_keeps_current_result_and_strips(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);artifact=root/'revision-race';old=artifact/'reflow_revisions'/'revision-2'/'strips'/'old.png'
            old.parent.mkdir(parents=True);old.write_bytes(b'old strip')
            frame=artifact/'reflow'/'manifest'/'frames'/'obs.png'
            frame.parent.mkdir(parents=True);frame.write_bytes(b'cache')
            store=JobStore(root)
            store.create(Job(id='revision-race',source_type='file',file_path=None,youtube_url=None,options={},
                             artifact_dir=str(artifact),status=JobStatus.ERROR,
                             result={'reflow':{'revision':2,'systems':[{'strip_path':str(old)}]}}))
            underlying=threading.RLock();waiting=threading.Event()

            class ObservedLock:
                def __enter__(self):
                    waiting.set()  # cleanup has checked ERROR and is about to wait for the export lock
                    underlying.acquire()
                    return self
                def __exit__(self,*_args):underlying.release()

            outcomes=[];errors=[]
            def clean():
                try:outcomes.append(main._cleanup_ended_job_workspace('revision-race'))
                except BaseException as exc:errors.append(exc)

            with patch.object(main,'job_store',store),patch.object(main,'review_locks',{'revision-race':ObservedLock()}), \
                 patch.object(main,'prune_job_workspace',wraps=main.prune_job_workspace) as prune:
                underlying.acquire()
                worker=threading.Thread(target=clean,daemon=True)
                worker.start()
                try:
                    self.assertTrue(waiting.wait(5),'ended cleanup must wait for the same per-job export lock')
                    prune.assert_not_called()
                    # A repair publishes while it owns that lock, after cleanup's first status check.
                    new=artifact/'reflow_revisions'/'revision-3'/'strips'/'new.png'
                    new.parent.mkdir(parents=True);new.write_bytes(b'published strip')
                    committed={'reflow':{'revision':3,'systems':[{'strip_path':str(new)}]}}
                    store.set_state('revision-race',JobStatus.DONE,result=committed)
                finally:
                    underlying.release()
                    worker.join(10)
                self.assertFalse(worker.is_alive())
                self.assertFalse(errors,errors)
                self.assertEqual(outcomes,[None])
                prune.assert_not_called()
                job=store.get('revision-race')
                self.assertEqual(job.status,JobStatus.DONE)
                self.assertEqual(job.result,committed)
                self.assertEqual(old.read_bytes(),b'old strip')
                self.assertEqual(new.read_bytes(),b'published strip')
                self.assertTrue(frame.is_file())


if __name__=='__main__':unittest.main()
