# =============================================================================
# === backend/apps/accounting/management/commands/ensure_accounting_periods.py ===
# =============================================================================
"""
Arthasee — Daily Accounting Period Rollover (60-Day Lead-Time)

Same real cron pattern already proven on the production droplet —
send_service_reminders, snapshot_risk_daily, mark_overdue_payments —
a plain management command, no Celery, no new infrastructure.

Why this exists: ensure_current_month_period() only ever runs once,
at signup. Nothing else creates a period after that. Left alone,
every posting for every organization would hit the exact same
strict-block failure Chris hit in August — on the 1st of every future
MONTH, guaranteed, not hypothetical. This risk is now real every 30
days instead of once a year, which is exactly why this command
matters more, not less, under monthly closing.

Design: runs daily, checks 60 days ahead of today rather than
reacting only once the current period actually runs out. That turns
"must not fail on exactly one specific day of the month" into "has
weeks of slack" — a holiday-season cron outage of a few days can
never cause a real gap, even now that rollover happens monthly.
Costs nothing: an unused future period sitting idle is harmless, same
"safe to call more than once" spirit as seed_chart_of_accounts() and
ensure_period_for_org() already have.

Covers every organization in one run, same as send_service_reminders
— no request/session to scope from when cron-driven.

--- 26 Aug 2026: yearly -> monthly ---
Made's own confirmed requirement (monthly closing, via his tax &
accounting consultant) moved period seeding from one period per year
to one real period per month. ensure_period_for_org() itself now
requires an explicit (year, month), not just a year — this command's
own target date resolves BOTH from the same 60-day lookahead.

Note: this creates one period LEAD_TIME_DAYS ahead, nothing more —
it doesn't backfill multiple months if the command hasn't run in a
long time. Real monitoring on the cron job itself is still the actual
safety net here, same as it is for send_service_reminders.
"""
from datetime import date, timedelta

from apps.accounting.models import AccountingPeriod
from apps.accounting.periods import ensure_period_for_org
from apps.organizations.models import Organization
from django.core.management.base import BaseCommand

LEAD_TIME_DAYS = 60


class Command(BaseCommand):
    help = "Ensure every organization has an AccountingPeriod covering 60 days from today."

    def handle(self, *args, **options):
        target_date = date.today() + timedelta(days=LEAD_TIME_DAYS)
        target_year = target_date.year
        target_month = target_date.month

        created_count = 0
        already_existed_count = 0

        for org in Organization.objects.all():
            period, created = self._ensure_and_report(org, target_year, target_month)
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"Created — {org.name} → {period.start_date} to {period.end_date}"
                ))
            else:
                already_existed_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created: {created_count}, Already covered: {already_existed_count} "
            f"(checked {LEAD_TIME_DAYS} days ahead, target {target_year}-{target_month:02d})"
        ))

    def _ensure_and_report(self, organization, year, month):
        """
        ensure_period_for_org() itself doesn't return a created/existed
        distinction — this pre-check exists purely so the command can
        report an honest count, without changing that function's
        return signature for every other caller's sake.
        """
        existed_before = AccountingPeriod.objects.filter(
            organization=organization, year=year, month=month,
        ).exists()
        period = ensure_period_for_org(organization, year, month)
        return period, not existed_before
