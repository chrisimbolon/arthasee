"""Guard: every app keeps its tests in a tests/ package (22 Oct 2026).

Test files used to pile up at each app's top level (tests.py + test_*.py side
by side). They now live in apps/<app>/tests/. This fails the suite if a new
test file lands at the top level again.
"""
from pathlib import Path

from django.test import SimpleTestCase

APPS_DIR = Path(__file__).resolve().parents[2]


class TestLayoutTests(SimpleTestCase):
    def test_no_test_files_at_app_top_level(self):
        stray = sorted(
            str(p.relative_to(APPS_DIR))
            for p in APPS_DIR.glob("*/test*.py")
        )
        self.assertEqual(
            stray, [],
            "Put test files in apps/<app>/tests/ (with an __init__.py), not at the app's top level.",
        )

    def test_every_tests_folder_is_a_package(self):
        missing = sorted(
            str(d.relative_to(APPS_DIR))
            for d in APPS_DIR.glob("*/tests")
            if d.is_dir() and not (d / "__init__.py").exists()
        )
        self.assertEqual(missing, [], "Each tests/ folder needs an __init__.py or Django won't find it.")
