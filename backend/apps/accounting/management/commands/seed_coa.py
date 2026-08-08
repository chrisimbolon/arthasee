# =============================================================================
# === backend/apps/accounting/management/commands/seed_coa.py ===
# =============================================================================
"""
Arthasee — Seed Chart of Accounts (CLI)

The STANDARD_COA list and the actual seeding logic now live in
apps.accounting.coa — this command is a thin CLI wrapper around
seed_chart_of_accounts(), the same function
apps.authentication.views.RegisterView.post() calls automatically on
real signup. One implementation, two callers — not two copies of the
same list that could quietly drift apart.

Usage:
    python manage.py seed_coa                      # every active Organization
    python manage.py seed_coa --organization <uuid>  # one specific Organization
"""
from apps.accounting.coa import STANDARD_COA, seed_chart_of_accounts
from apps.organizations.models import Organization
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Seed the standard Chart of Accounts for one Organization, or every active Organization."

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
            # options["verbosity"] — not self.verbosity, that's not
            # an attribute BaseCommand sets for you automatically.
            if options["verbosity"] >= 1:
                self.stdout.write(self.style.SUCCESS(
                    f"{org.name}: {created_count} account(s) created, "
                    f"{already_existed} already existed."
                ))
