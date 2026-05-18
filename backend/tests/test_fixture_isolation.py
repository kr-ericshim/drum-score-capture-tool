from pathlib import Path
import unittest


FORBIDDEN_RUNTIME_FIXTURE_MARKERS = (
    "backend/jobs",
    "score_capture_program/backend/jobs",
)


class TestBackendFixtureIsolation(unittest.TestCase):
    def test_backend_tests_do_not_reference_runtime_jobs_tree(self):
        tests_root = Path(__file__).resolve().parent

        offenders = []
        for test_path in sorted(tests_root.glob("test_*.py")):
            if test_path.name == Path(__file__).name:
                continue

            source = test_path.read_text(encoding="utf-8")
            for marker in FORBIDDEN_RUNTIME_FIXTURE_MARKERS:
                if marker in source:
                    offenders.append(f"{test_path.name}: {marker}")

        self.assertEqual(
            offenders,
            [],
            "Backend tests must keep immutable samples under backend/tests/fixtures "
            "or synthesize temporary job trees instead of depending on runtime artifacts.",
        )


if __name__ == "__main__":
    unittest.main()
