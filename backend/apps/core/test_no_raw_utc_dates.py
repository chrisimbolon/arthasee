"""
Structural guard: application code must never extract a date straight from
`timezone.now()` — that returns the UTC calendar day, which at Asia/Jakarta
(UTC+7) is still "yesterday" between 00:00 and 07:00 local time.

Route every such extraction through `apps.accounting.periods.safe_local_date()`.

Why this is a test and not a checklist (Roadmap Principle #13): this exact bug
was found and "fixed everywhere" in Phase 18, then found again in three more
places by a later sweep. "Fixed" is not the same as "swept" — so the sweep is
now a test that fails the moment anyone reintroduces the pattern.

Uses the AST, not a text search, so comments and docstrings that merely
*describe* the bug never trigger it. Test files and migrations are skipped.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase


def _is_raw_utc_date_call(node: ast.AST) -> bool:
    """True for `<something>.now().date()` where `now` is django's timezone.now."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "date"
        and not node.args
        and not node.keywords
        and isinstance(node.func.value, ast.Call)
    ):
        return False

    now_func = node.func.value.func
    # timezone.now().date()  /  django.utils.timezone.now().date()
    if isinstance(now_func, ast.Attribute) and now_func.attr == "now":
        base = now_func.value
        base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
        return base_name == "timezone"
    # `from django.utils.timezone import now`  ->  now().date()
    if isinstance(now_func, ast.Name) and now_func.id == "now":
        return True
    return False


class NoRawUtcDateExtractionTests(SimpleTestCase):
    def test_no_raw_timezone_now_date_in_application_code(self):
        apps_dir = Path(__file__).resolve().parent.parent  # backend/apps
        offenders = []

        for path in sorted(apps_dir.rglob("*.py")):
            if "migrations" in path.parts or "__pycache__" in path.parts:
                continue
            if path.name == "tests.py" or path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if _is_raw_utc_date_call(node):
                    offenders.append(f"{path.relative_to(apps_dir)}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            "Raw `timezone.now().date()` found — it returns the UTC day, not the "
            "shop's local day. Use apps.accounting.periods.safe_local_date("
            "timezone.now()) instead. Offenders: " + ", ".join(offenders),
        )
