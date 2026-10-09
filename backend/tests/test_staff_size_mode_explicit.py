"""Modern explicit mode wins; requests that predate the field keep their inference."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import main
from app.pipeline import reflow_pipeline as rp
from app.schemas import JobReviewExportRequest, JobReviewExportResponse
import test_staff_size_mode as fixtures
from test_staff_size_mode import opts


class ExplicitStaffSizeModeTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.InitialJobModeTest()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_initial_explicit_product_default_is_locked(self):
        kw, job = self.fixture.run_job(opts(staff_gap_mm=1.5, staff_gap_mm_explicit=True))
        self.assertFalse(kw['auto_staff_size'])
        self.assertTrue(job.result['reflow']['staff_gap_mm_explicit'])

    def test_review_flag_wins_at_default_and_another_size_and_survives_rebuild(self):
        _, job = self.fixture.run_job(opts())
        paths = [s['strip_path'] for s in job.result['reflow']['systems']]
        real = rp.compose_systems
        with patch.object(main, 'job_store', self.fixture.store), patch.object(rp, 'compose_systems', wraps=real) as compose:
            for size, explicit in [(1.5, True), (1.4, False), (1.5, False)]:
                response = main.review_export(job.id, JobReviewExportRequest(keep_captures=paths, formats=['png'], staff_gap_mm=size, staff_gap_mm_explicit=explicit))
                self.assertEqual(compose.call_args.kwargs['auto_staff_size'], not explicit)
                self.assertEqual(compose.call_args.kwargs['staff_gap_mm'], size)
                self.assertEqual(self.fixture.store.get(job.id).result['reflow']['staff_gap_mm_explicit'], explicit)
                main.review_export(job.id, JobReviewExportRequest(keep_captures=paths, formats=['png']))
                self.assertEqual(compose.call_args.kwargs['auto_staff_size'], not explicit)

    def test_old_review_client_keeps_legacy_default_inference(self):
        _, job = self.fixture.run_job(opts())
        paths = [s['strip_path'] for s in job.result['reflow']['systems']]
        with patch.object(main, 'job_store', self.fixture.store), patch.object(rp, 'compose_systems', wraps=rp.compose_systems) as compose:
            for size, auto in [(1.5, True), (1.4, False)]:
                main.review_export(job.id, JobReviewExportRequest(keep_captures=paths, formats=['png'], staff_gap_mm=size))
                self.assertEqual(compose.call_args.kwargs['auto_staff_size'], auto)

    def test_review_response_preserves_review_required_on_background_task_result(self):
        _, job = self.fixture.run_job(opts())
        result = job.result
        result['reflow']['review_required'] = True
        result['reflow']['review_reasons'] = ['SOURCE_CLIPPED']
        result['reflow']['systems'][0]['issues'] = ['SOURCE_CLIPPED']
        self.fixture.store.set_state(job.id, job.status, result=result)
        paths = [system['strip_path'] for system in result['reflow']['systems']]
        with patch.object(main, 'job_store', self.fixture.store):
            response = main.review_export(job.id, JobReviewExportRequest(keep_captures=paths, formats=['png']))
        decoded = JobReviewExportResponse.model_validate(response.model_dump())
        self.assertTrue(decoded.review_required)
        codes = {r['code'] if isinstance(r, dict) else r for r in decoded.review_reasons}
        self.assertIn('SOURCE_CLIPPED', codes)
        self.assertFalse({'LEDGER_UNASSESSED', 'DELIVERED_PDF_UNASSESSED'} & codes)  # actual PNG pixels were checked
        # B/C findings of this fixture are developer-only codes (DECISIONS "User-visible findings"),
        # so the ledger adds no review reason; the source-limited reason above is preserved.
        summary = self.fixture.store.get(job.id).result['reflow']['ledger_summary']
        self.assertEqual(summary['status'], 'pass')
        self.assertNotIn('LEDGER_REVIEW_REQUIRED', codes)
        saved = self.fixture.store.get(job.id).result
        self.assertTrue(saved['review_required'])
        self.assertEqual(saved['review_reasons'], decoded.review_reasons)
        self.assertIn('source_limited', saved['reflow']['page_plan'])
