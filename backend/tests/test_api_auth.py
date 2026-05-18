import asyncio
import unittest
from types import SimpleNamespace

from app import main


class TestApiAuth(unittest.TestCase):
    def test_session_token_is_not_required_for_health(self):
        self.assertFalse(main._requires_session_token("/health"))

    def test_session_token_is_required_for_jobs_and_job_files(self):
        self.assertTrue(main._requires_session_token("/jobs"))
        self.assertTrue(main._requires_session_token("/jobs-files/job-1/export/page_1.png"))

    def test_header_token_matches_expected_value(self):
        self.assertTrue(main._has_valid_session_token({"x-drumsheet-token": "secret"}, "secret"))
        self.assertFalse(main._has_valid_session_token({"x-drumsheet-token": "wrong"}, "secret"))
        self.assertFalse(main._has_valid_session_token({}, "secret"))

    def test_query_token_does_not_authenticate_protected_paths(self):
        previous_token = main.DRUMSHEET_SESSION_TOKEN
        main.DRUMSHEET_SESSION_TOKEN = "secret"
        try:
            request = SimpleNamespace(
                method="GET",
                url=SimpleNamespace(path="/jobs"),
                headers={},
                query_params={"token": "secret"},
            )

            async def call_next(_request):
                raise AssertionError("request should not reach protected handler")

            response = asyncio.run(main.enforce_session_token(request, call_next))
            self.assertEqual(response.status_code, 401)
        finally:
            main.DRUMSHEET_SESSION_TOKEN = previous_token

    def test_header_token_authenticates_protected_paths(self):
        previous_token = main.DRUMSHEET_SESSION_TOKEN
        main.DRUMSHEET_SESSION_TOKEN = "secret"
        try:
            request = SimpleNamespace(
                method="GET",
                url=SimpleNamespace(path="/jobs"),
                headers={"X-DrumSheet-Token": "secret"},
                query_params={},
            )

            async def call_next(_request):
                return main.JSONResponse(status_code=204, content=None)

            response = asyncio.run(main.enforce_session_token(request, call_next))
            self.assertEqual(response.status_code, 204)
        finally:
            main.DRUMSHEET_SESSION_TOKEN = previous_token


if __name__ == "__main__":
    unittest.main()
