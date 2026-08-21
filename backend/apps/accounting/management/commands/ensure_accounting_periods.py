# =============================================================================
# === backend/apps/accounting/management/commands/ensure_accounting_periods.py ===
# =============================================================================
"""
Arthasee — Daily Accounting Period Rollover (60-Day Lead-Time)

Same real cron pattern already proven on the production droplet —
send_service_reminders, snapshot_risk_daily, mark_overdue_payments —
a plain management command, no Celery, no new infrastructure.

Why this exists: ensure_current_year_period() only ever ran once, at
signup. Nothing else created a period. Left alone, every posting for
every organization would hit the exact same strict-block failure
Chris hit in August — on January 1 of every future year, guaranteed,
not hypothetical.

Design: runs daily, checks 60 days ahead of today rather than
reacting only once the current period actually runs out. That turns
"must not fail on exactly one specific day of the year" into "has
weeks of slack" — a holiday-season cron outage of a few days can
never cause a real gap. Costs nothing: an unused future period
sitting idle is harmless, same "safe to call more than once" spirit
as seed_chart_of_accounts() and ensure_current_year_period() already
have.

Covers every organization in one run, same as send_service_reminders
— no request/session to scope from when cron-driven.

Note: this creates one period LEAD_TIME_DAYS ahead, nothing more —
it doesn't backfill multiple years if the command hasn't run in a
long time. Real monitoring on the cron job itself is still the
actual safety net here, same as it is for send_service_reminders.
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.accounting.models import AccountingPeriod
from apps.accounting.periods import ensure_period_for_org
from apps.organizations.models import Organization

LEAD_TIME_DAYS = 60


class Command(BaseCommand):
    help = "Ensure every organization has an AccountingPeriod covering 60 days from today."

    def handle(self, *args, **options):
        target_date = date.today() + timedelta(days=LEAD_TIME_DAYS)
        target_year = target_date.year

        created_count = 0
        already_existed_count = 0

        for org in Organization.objects.all():
            period, created = self._ensure_and_report(org, target_year)
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"Created — {org.name} → {period.start_date} to {period.end_date}"
                ))
            else:
                already_existed_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created: {created_count}, Already covered: {already_existed_count} "
            f"(checked {LEAD_TIME_DAYS} days ahead, target year {target_year})"
        ))

    def _ensure_and_report(self, organization, year):
        """
        ensure_period_for_org() itself doesn't return a created/existed
        distinction — this pre-check exists purely so the command can
        report an honest count, without changing that function's
        return signature for every other caller's sake.
        """
        existed_before = AccountingPeriod.objects.filter(
            organization=organization, start_date__year=year,
        ).exists()
        period = ensure_period_for_org(organization, year)
        return period, not existed_before
