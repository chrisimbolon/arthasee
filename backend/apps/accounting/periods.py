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

--- Updated for the daily rollover command (ensure_accounting_periods) ---
ensure_period_for_org() is the one real implementation now;
ensure_current_year_period() is a thin wrapper over it so the
existing signup call site never needed to change. Added because
ensure_current_year_period() alone can never create a *future*
year's period — date.today().year is always the current year by
definition — and the rollover command needs to create next year's
period proactively, ~60 days before it's actually needed.
"""
from datetime import date

from apps.accounting.models import AccountingPeriod


def ensure_period_for_org(organization, year: int) -> AccountingPeriod:
    """
    Idempotent — get_or_create per (organization, start_date, end_date)
    for the given calendar year (Jan 1 - Dec 31). Same "safe to call
    more than once, never overwrites something already customized"
    guarantee seed_chart_of_accounts() already has. Open (not
    closed/locked) by default.

    Deliberately ONE period spanning the whole year, not monthly
    sub-periods — Chris's own confirmed call to keep yearly periods
    for v1 (monthly locking parked as a future feature once Made
    hires a dedicated accountant — see Roadmap Open Decisions).
    """
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    period, _ = AccountingPeriod.objects.get_or_create(
        organization=organization, start_date=year_start, end_date=year_end,
        defaults={"is_closed": False, "is_locked": False},
    )
    return period


def ensure_current_year_period(organization) -> AccountingPeriod:
    """
    Unchanged call signature and behavior for every existing caller
    (real production signup, every test fixture) — now just a thin
    wrapper over ensure_period_for_org() so there's one real
    implementation instead of two copies that could drift apart.
    """
    return ensure_period_for_org(organization, date.today().year)
