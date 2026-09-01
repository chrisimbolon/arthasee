# =============================================================================
# === backend/apps/accounting/management/commands/ensure_accounting_periods.py ===
# =============================================================================
"""
Arthasee — Daily Accounting Period Rollover (60-Day Lead-Time, Gap-Filling)

Same real cron pattern already proven on the production droplet —
send_service_reminders, snapshot_risk_daily, mark_overdue_payments —
a plain management command, no Celery, no new infrastructure.

Why this exists: ensure_current_month_period() only ever runs once,
at signup. Nothing else creates a period after that. Left alone,
every posting for every organization would hit a strict-block
failure the moment "today" moves past the last period any org has —
now a real risk every 30 days under monthly closing, not once a
year.

--- 1 Sep 2026: real production gap found and fixed ---
The original version of this command (written 26 Aug 2026, when
ensure_period_for_org() first became month-granular) only ever
computed ONE target month — today + LEAD_TIME_DAYS — and called
ensure_period_for_org() once for it. That was correct back when
periods were yearly (one call always covered the whole year, so
there was never a gap to fill), but was never revisited when periods
became monthly. Running daily, it correctly created "today's month"
whenever today+60 happened to land there, and correctly skipped
duplicates — but never touched any month strictly BETWEEN the day it
happened to run and its own 60-day-out target. Confirmed live on CV
Arya Motor: August and October existed, September (the current
month) did not, blocking every real posting on Sep 1 2026.

Fix: this command now ensures EVERY month from today's month through
the 60-day lookahead month, inclusive, not just the single lookahead
point. Same idempotent, "safe to call more than once, unused future
period is harmless" primitive (ensure_period_for_org's own
get_or_create) — just applied as a range instead of two endpoints.

Covers every organization in one run, same as send_service_reminders
— no request/session to scope from when cron-driven.

Note: this still only ever looks forward from "today" — it won't
retroactively backfill a month that's already in the past by the
time the command finally runs after an extended outage. Real
monitoring on the cron job itself remains the actual safety net,
same as it is for send_service_reminders.
"""
from datetime import date, timedelta

from apps.accounting.models import AccountingPeriod
from apps.accounting.periods import ensure_period_for_org
from apps.organizations.models import Organization
from django.core.management.base import BaseCommand

LEAD_TIME_DAYS = 60


class Command(BaseCommand):
    help = "Ensure every organization has AccountingPeriods covering today through 60 days ahead — no gaps."

    def handle(self, *args, **options):
        today = date.today()
        target_date = today + timedelta(days=LEAD_TIME_DAYS)

        months_to_ensure = self._month_range(today, target_date)

        created_count = 0
        already_existed_count = 0

        for org in Organization.objects.all():
            for year, month in months_to_ensure:
                period, created = self._ensure_and_report(org, year, month)
                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"Created — {org.name} → {period.start_date} to {period.end_date}"
                    ))
                else:
                    already_existed_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created: {created_count}, Already covered: {already_existed_count} "
            f"(ensured every month from {today.year}-{today.month:02d} "
            f"through {target_date.year}-{target_date.month:02d}, {LEAD_TIME_DAYS} days ahead)"
        ))

    @staticmethod
    def _month_range(start_date, end_date):
        """Every distinct (year, month) from start_date through end_date, inclusive."""
        months = []
        year, month = start_date.year, start_date.month
        while (year, month) <= (end_date.year, end_date.month):
            months.append((year, month))
            month += 1
            if month == 13:
                month = 1
                year += 1
        return months

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
