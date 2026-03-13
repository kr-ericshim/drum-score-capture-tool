import unittest

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


if __name__ == "__main__":
    unittest.main()
