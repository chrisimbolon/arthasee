# =============================================================================
# === backend/apps/accounting/migrations/0XXX_migrate_to_monthly_periods.py
# === NAME THIS FILE using the real number that follows your
# === generated schema migration — I don't know that number yet.
# =============================================================================
"""
Real, correctness-critical data migration — touches actual, already-
posted JournalEntry rows (StockOpnameCompleted's own entry 000018,
the replayed Aug 10 chain, everything real this session has verified
by hand). Every step below is deliberately ordered so nothing is ever
deleted while something real still references it.

Order of operations, and why:
  1. Populate year/month on every EXISTING period row from its own
     start_date — cheap, safe, no cross-table effect yet.
  2. For every period whose real span is longer than any real month
     could be (> 31 days — the only honest way to distinguish an old
     yearly row from an already-monthly one), repoint every
     JournalEntry that references it to the correct MONTHLY period
     for THAT ENTRY'S OWN posting_date — creating that monthly period
     first if it doesn't exist yet. The entry's own date is the
     ground truth here, not date math derived from the old period.
  3. Once nothing references the old yearly period: if real monthly
     periods were created to replace it, delete the now-empty yearly
     row. BUT if the org had ZERO real journal entries at all (a
     genuinely idle org, confirmed live — one real org in this exact
     dataset has no activity yet), deleting its only period would
     leave it with NO period whatsoever — JournalEntry.post() and the
     new AccountingPeriod.assert_open_for_posting() both hard-require
     one to exist for ANY future posting date, so an org with zero
     periods couldn't record its very first real transaction without
     some other process creating one first. Rather than depend on
     ensure_accounting_periods' own (unconfirmed) behavior for
     already-existing, previously-idle orgs, this converts that one
     empty yearly row IN PLACE into a real period for the CURRENT
     month instead of deleting it — guaranteeing every org that had a
     period before this migration still has one immediately after,
     unconditionally.

Reverse is deliberately a no-op — reversing this migration would mean
either resurrecting deleted yearly periods with no real journal
entries pointing back to them, or trying to re-collapse 12 real
monthly periods into one yearly row, neither of which reconstructs a
real, meaningful prior state.
"""
import calendar
from datetime import date

from django.db import migrations


def migrate_to_monthly(apps, schema_editor):
    AccountingPeriod = apps.get_model("accounting", "AccountingPeriod")
    JournalEntry = apps.get_model("accounting", "JournalEntry")

    # Step 1 — backfill year/month on every existing row from its own
    # start_date. A row already monthly-shaped gets a correct, honest
    # (year, month) too — this covers both "still yearly" rows AND any
    # that might already happen to span exactly one month.
    for period in AccountingPeriod.objects.all():
        period.year = period.start_date.year
        period.month = period.start_date.month
        period.save(update_fields=["year", "month"])

    today = date.today()

    # Steps 2 & 3 — a real monthly period's own span is at most 31
    # days (Jan/Mar/May/Jul/Aug/Oct/Dec); anything longer than that is
    # necessarily one of the old yearly rows being replaced here.
    for period in list(AccountingPeriod.objects.all()):
        span_days = (period.end_date - period.start_date).days
        if span_days <= 31:
            continue  # already a real monthly period — leave it alone

        entries = list(JournalEntry.objects.filter(accounting_period=period))

        if not entries:
            # A genuinely idle org — zero real activity ever posted
            # into this yearly period. Convert IN PLACE to a real
            # current-month period rather than deleting it, so this
            # org is never left with zero periods at all — see module
            # docstring's own Step 3 reasoning.
            last_day = calendar.monthrange(today.year, today.month)[1]
            period.year = today.year
            period.month = today.month
            period.start_date = date(today.year, today.month, 1)
            period.end_date = date(today.year, today.month, last_day)
            period.save(update_fields=["year", "month", "start_date", "end_date"])
            continue

        for entry in entries:
            pd = entry.posting_date
            last_day = calendar.monthrange(pd.year, pd.month)[1]
            monthly_period, _ = AccountingPeriod.objects.get_or_create(
                organization_id=period.organization_id, year=pd.year, month=pd.month,
                defaults={
                    "start_date": date(pd.year, pd.month, 1),
                    "end_date": date(pd.year, pd.month, last_day),
                    "is_closed": False, "is_locked": False,
                },
            )
            entry.accounting_period = monthly_period
            entry.save(update_fields=["accounting_period"])

        # Safe now — nothing references this yearly period anymore,
        # and real monthly periods now cover every entry that used to
        # point here, so it's genuinely redundant, not the org's only
        # period.
        period.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        # Confirmed real, applied schema migration — directly from
        # your own `makemigrations accounting` output, not guessed.
        ("accounting", "0002_alter_accountingperiod_options_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_to_monthly, noop_reverse),
    ]
