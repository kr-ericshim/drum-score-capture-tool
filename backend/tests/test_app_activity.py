import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class TestAppActivity(unittest.TestCase):
    def setUp(self):
        main.release_update_lock()
        self.addCleanup(main.release_update_lock)

    def test_update_lock_blocks_new_posts_until_released_but_allows_reads(self):
        async def ok(_request):
            return "accepted"

        post = SimpleNamespace(method="POST", url=SimpleNamespace(path="/jobs"))
        get = SimpleNamespace(method="GET", url=SimpleNamespace(path="/maintenance/activity"))
        with patch.object(main.job_store, "active_job_ids", return_value=[]), patch.object(
            main.source_prepare_store, "active_job_ids", return_value=[]
        ):
            self.assertEqual(main.acquire_update_lock(), {"locked": True})
            blocked = asyncio.run(main.count_inflight_mutations(post, ok))
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(asyncio.run(main.count_inflight_mutations(get, ok)), "accepted")
            main.release_update_lock()
            self.assertEqual(asyncio.run(main.count_inflight_mutations(post, ok)), "accepted")

    def test_update_lock_refuses_running_jobs_and_an_admitted_request(self):
        with patch.object(main.job_store, "active_job_ids", return_value=["job-1"]):
            with self.assertRaises(main.HTTPException) as error:
                main.acquire_update_lock()
            self.assertEqual(error.exception.status_code, 409)
            self.assertFalse(main.update_install_locked)

        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()

            async def held(_request):
                entered.set()
                await release.wait()
                return "done"

            post = SimpleNamespace(method="POST", url=SimpleNamespace(path="/jobs/job-1/review-export"))
            task = asyncio.create_task(main.count_inflight_mutations(post, held))
            await entered.wait()
            try:
                with self.assertRaises(main.HTTPException) as error:
                    main.acquire_update_lock()
                self.assertEqual(error.exception.status_code, 409)
                self.assertFalse(main.update_install_locked)
            finally:
                release.set()
                await task

        asyncio.run(scenario())

    def test_activity_reports_running_jobs_and_inflight_posts(self):
        seen = {}

        async def call_next(_request):
            seen["during"] = main.app_activity().inflight_requests
            return "response"

        post = SimpleNamespace(method="POST", url=SimpleNamespace(path="/jobs/job-1/review-export"))
        with patch.object(main.job_store, "active_job_ids", return_value=["job-1"]), patch.object(
            main.source_prepare_store, "active_job_ids", return_value=[]
        ):
            self.assertEqual(asyncio.run(main.count_inflight_mutations(post, call_next)), "response")
            activity = main.app_activity()

        self.assertEqual(seen["during"], 1)
        self.assertEqual(activity.inflight_requests, 0)
        self.assertEqual(activity.active_jobs, 1)
        self.assertEqual(activity.active_source_jobs, 0)

    def test_failed_post_and_reads_leave_the_counter_balanced(self):
        async def fail(_request):
            raise RuntimeError("boom")

        async def ok(_request):
            return "ok"

        post = SimpleNamespace(method="POST", url=SimpleNamespace(path="/jobs"))
        get = SimpleNamespace(method="GET", url=SimpleNamespace(path="/jobs/job-1"))
        with self.assertRaises(RuntimeError):
            asyncio.run(main.count_inflight_mutations(post, fail))
        asyncio.run(main.count_inflight_mutations(get, ok))
        self.assertEqual(main.app_activity().inflight_requests, 0)

    def test_activity_requires_the_session_token(self):
        self.assertTrue(main._requires_session_token("/maintenance/activity"))
        self.assertTrue(main._requires_session_token("/maintenance/update-lock"))
        self.assertTrue(main._requires_session_token("/maintenance/update-unlock"))


if __name__ == "__main__":
    unittest.main()
