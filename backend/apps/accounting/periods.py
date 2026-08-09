# =============================================================================
# === backend/apps/accounting/periods.py ===
# =============================================================================
"""
Arthasee — Accounting Period Seeding (Task 4.3)

Same shared-utility shape as apps.accounting.coa.seed_chart_of_accounts()
— one real implementation, called from BOTH real production signup
(apps.authentication.views.RegisterView.post(), alongside the
existing COA seed) and every test fixture across the whole codebase
(via the seed_coa management command, which now rides this along for
free — see seed_coa.py's own updated docstring for why).

Chris's own explicit call: JournalEntry.post() now BLOCKS any posting
whose date falls outside every known AccountingPeriod for that
organization — "every posting must belong to a real period, no
exceptions." That makes period-seeding just as much a hard
prerequisite for a new organization as Chart-of-Accounts seeding
already was — an org with a seeded COA but no period could still
never post a single real transaction.
"""
from datetime import date

from apps.accounting.models import AccountingPeriod


def ensure_current_year_period(organization) -> AccountingPeriod:
    """
    Idempotent — get_or_create per (organization, start_date,
    end_date) for the CURRENT calendar year (Jan 1 - Dec 31, computed
    fresh from today's real date every time this runs, never
    hardcoded), same "safe to call more than once, never overwrites
    something already customized" guarantee seed_chart_of_accounts()
    already has. Open (not closed/locked) by default — a brand-new
    organization should be able to post immediately, not require
    someone to first go unlock a period nobody ever intentionally
    locked.

    Deliberately ONE period spanning the whole year, not monthly
    sub-periods — the simplest default that lets a new organization
    post anything, anytime, for the rest of the year, without ever
    hitting the new strict block. A shop that wants finer-grained
    monthly locking (lock January once reconciled, keep February
    open) can create narrower periods later through real period-
    management tooling — not built in this pass; this function's own
    job is just making the strict block livable from day one, not
    building the full period-management workflow.
    """
    today = date.today()
    year_start = date(today.year, 1, 1)
    year_end   = date(today.year, 12, 31)

    period, _ = AccountingPeriod.objects.get_or_create(
        organization=organization, start_date=year_start, end_date=year_end,
        defaults={"is_closed": False, "is_locked": False},
    )
    return period
