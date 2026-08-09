# =============================================================================
# === backend/apps/accounting/management/commands/seed_coa.py ===
# =============================================================================
"""
Arthasee — Seed Chart of Accounts (and, as of Task 4.3, a real
Accounting Period)

UPDATED — this command's real job has widened: it's no longer just
"seed the Chart of Accounts," it's "make this organization ready to
post financial transactions at all." JournalEntry.post() now hard-
blocks any posting whose date falls outside a real AccountingPeriod
(Chris's own explicit call — see apps.accounting.periods' own module
docstring) — an organization with a seeded COA but no period could
still never post anything.

Deliberately kept the SAME command name rather than renaming it —
every test fixture across the whole codebase already calls
`call_command("seed_coa", ...)`; renaming would mean touching every
one of those call sites for a purely cosmetic reason. This way, the
whole existing suite gets a valid period for free, with zero test
file edits needed.

Usage:
    python manage.py seed_coa                      # every active Organization
    python manage.py seed_coa --organization <uuid>  # one specific Organization
"""
from apps.accounting.coa import STANDARD_COA, seed_chart_of_accounts
from apps.accounting.periods import ensure_current_year_period
from apps.organizations.models import Organization
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Seed the standard Chart of Accounts and a current-year Accounting Period for one Organization, or every active Organization."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization", type=str, default=None,
            help="UUID of a single Organization to seed. Omit to seed every active Organization.",
        )

    def handle(self, *args, **options):
        org_id = options.get("organization")

        if org_id:
            try:
                organizations = [Organization.objects.get(pk=org_id)]
            except Organization.DoesNotExist as exc:
                raise CommandError(f"No Organization found with id={org_id}") from exc
        else:
            organizations = list(Organization.objects.filter(is_active=True))
            if not organizations:
                self.stdout.write(self.style.WARNING("No active Organizations found — nothing to seed."))
                return

        for org in organizations:
            created_count = seed_chart_of_accounts(org)
            already_existed = len(STANDARD_COA) - created_count
            period = ensure_current_year_period(org)

            if options["verbosity"] >= 1:
                self.stdout.write(self.style.SUCCESS(
                    f"{org.name}: {created_count} account(s) created, "
                    f"{already_existed} already existed. "
                    f"Period {period.start_date}–{period.end_date} ready."
                ))