# =============================================================================
# === backend/apps/accounting/periods.py ===
# =============================================================================
"""
Arthasee — Accounting Period Seeding (Task 4.3, updated 26 Aug 2026
for monthly closing — Made's own confirmed requirement, via his tax
& accounting consultant)

Same shared-utility shape as apps.accounting.coa.seed_chart_of_accounts()
— one real implementation, called from BOTH real production signup
(apps.authentication.views.RegisterView.post(), alongside the
existing COA seed) and every test fixture across the whole codebase.

Chris's own explicit call: JournalEntry.post() blocks any posting
whose date falls outside every known AccountingPeriod for that
organization — "every posting must belong to a real period, no
exceptions." Period-seeding is just as much a hard prerequisite for a
new organization as Chart-of-Accounts seeding already was.

--- 26 Aug 2026: yearly -> monthly ---
Made needs to lock the books, calculate net profit, and run tax
compliance monthly, not just annually — his own confirmed
requirement. ensure_period_for_org() now takes an explicit
(year, month) and creates ONE CALENDAR MONTH period, not a full year.
Existing real data was migrated to match — see
migrations/0003_migrate_to_monthly_periods.py for exactly how every
already-posted JournalEntry was repointed before the old yearly rows
were removed.

--- 28 Aug 2026: signup now seeds the WHOLE current year's months ---
Real gap found live: switching signup to seed only the CURRENT
month broke a wide swath of test fixtures across apps.estimates,
apps.customers, apps.service, apps.invoicing, and apps.inventory —
all of them close a real WorkOrder or otherwise post a real
transaction dated slightly in the past (or simply "today," on a
different day than whenever seed_coa originally ran), which then has
no covering period. This isn't just a test-fixture problem — a real
shop with a few days' data-entry lag across a month boundary would
hit the exact same hard block for a completely legitimate reason.

ensure_current_month_period() now seeds EVERY month of the CURRENT
YEAR at signup, not just the current one — restores "any date this
calendar year just works," the same real guarantee the old single
yearly period gave for free, while each of the 12 months still stays
a genuinely separate, independently closeable period (Made's own
requirement is fully intact — this only affects how early they're
CREATED, not whether they can each be closed on their own). Matches
the exact "an unused future period sitting idle is harmless" spirit
ensure_accounting_periods' own docstring already established for its
60-day lookahead.
"""
import calendar
from datetime import date

from apps.accounting.models import AccountingPeriod


def ensure_period_for_org(organization, year: int, month: int) -> AccountingPeriod:
    """
    Idempotent — get_or_create per (organization, year, month). Same
    "safe to call more than once, never overwrites something already
    customized" guarantee seed_chart_of_accounts() already has. Open
    (not closed/locked) by default.
    """
    last_day = calendar.monthrange(year, month)[1]
    period, _ = AccountingPeriod.objects.get_or_create(
        organization=organization, year=year, month=month,
        defaults={
            "start_date": date(year, month, 1),
            "end_date": date(year, month, last_day),
            "is_closed": False, "is_locked": False,
        },
    )
    return period


def ensure_current_month_period(organization) -> AccountingPeriod:
    """
    Unchanged call-site shape for real production signup and every
    test fixture — but now seeds every month of the CURRENT YEAR, not
    just the one "today" happens to fall in (see module docstring's
    28 Aug 2026 note for the real gap this fixes). Still returns the
    CURRENT month's own period specifically — every existing caller
    that does something with the return value (e.g. reads its
    start_date/end_date) keeps getting exactly what it expects.
    """
    today = date.today()
    current_period = None
    for month in range(1, 13):
        period = ensure_period_for_org(organization, today.year, month)
        if month == today.month:
            current_period = period
    return current_period
