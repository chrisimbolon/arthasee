# =============================================================================
# === backend/apps/accounting/management/commands/seed_coa.py ===
# =============================================================================
"""
Arthasee — Seed Chart of Accounts

Idempotent by design — get_or_create per (organization, code), safe
to run repeatedly (e.g. after STANDARD_COA gains a new account later)
without duplicating anything or overwriting a name/type a shop's own
accountant has since customized in Settings.

Usage:
    python manage.py seed_coa                      # every active Organization
    python manage.py seed_coa --organization <uuid>  # one specific Organization
"""
from apps.accounting.models import Account
from apps.organizations.models import Organization
from django.core.management.base import BaseCommand, CommandError

# (code, name, account_type, normal_balance) — matches Roadmap v2.2's
# COA Blueprint exactly, including 2010 (Accrued Inventory / GR-IR
# clearing) and 2101 (Tax Payable — seeded now as a placeholder;
# Roadmap v2.2 Open Decision #4 explicitly defers wiring any posting
# rule to it until a later phase).
STANDARD_COA = [
    ("1001", "Cash",                              Account.AccountType.ASSET,     Account.NormalBalance.DEBIT),
    ("1101", "Bank",                               Account.AccountType.ASSET,     Account.NormalBalance.DEBIT),
    ("1201", "Accounts Receivable",                Account.AccountType.ASSET,     Account.NormalBalance.DEBIT),
    ("1301", "Inventory",                          Account.AccountType.ASSET,     Account.NormalBalance.DEBIT),
    ("1302", "Work In Progress (WIP)",              Account.AccountType.ASSET,     Account.NormalBalance.DEBIT),
    ("1401", "Fixed Assets",                        Account.AccountType.ASSET,     Account.NormalBalance.DEBIT),
    ("2001", "Accounts Payable",                    Account.AccountType.LIABILITY, Account.NormalBalance.CREDIT),
    ("2010", "Accrued Inventory (Unbilled AP)",      Account.AccountType.LIABILITY, Account.NormalBalance.CREDIT),
    ("2101", "Tax Payable",                         Account.AccountType.LIABILITY, Account.NormalBalance.CREDIT),
    ("3001", "Owner Capital",                        Account.AccountType.EQUITY,    Account.NormalBalance.CREDIT),
    ("3101", "Retained Earnings",                    Account.AccountType.EQUITY,    Account.NormalBalance.CREDIT),
    ("4001", "Service Revenue",                      Account.AccountType.REVENUE,   Account.NormalBalance.CREDIT),
    ("4002", "Parts Revenue",                        Account.AccountType.REVENUE,   Account.NormalBalance.CREDIT),
    ("4003", "Sublet / Outsourcing Revenue",         Account.AccountType.REVENUE,   Account.NormalBalance.CREDIT),
    ("5001", "HPP Sparepart (COGS)",                 Account.AccountType.COGS,      Account.NormalBalance.DEBIT),
    ("5002", "HPP Sublet / Jasa Luar",                Account.AccountType.COGS,      Account.NormalBalance.DEBIT),
    ("5003", "HPP Pelumas & Fluida",                  Account.AccountType.COGS,      Account.NormalBalance.DEBIT),
    ("6001", "Beban Gaji",                            Account.AccountType.EXPENSE,   Account.NormalBalance.DEBIT),
    ("6002", "Beban Sewa",                            Account.AccountType.EXPENSE,   Account.NormalBalance.DEBIT),
    ("6003", "Beban Listrik, Air, Telp",               Account.AccountType.EXPENSE,   Account.NormalBalance.DEBIT),
    ("6004", "Beban Penyusutan",                      Account.AccountType.EXPENSE,   Account.NormalBalance.DEBIT),
    ("6005", "Beban Lain-lain",                       Account.AccountType.EXPENSE,   Account.NormalBalance.DEBIT),
]


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
            created_count = 0
            for code, name, account_type, normal_balance in STANDARD_COA:
                _, created = Account.objects.get_or_create(
                    organization=org, code=code,
                    defaults={
                        "name": name,
                        "account_type": account_type,
                        "normal_balance": normal_balance,
                    },
                )
                if created:
                    created_count += 1

            already_existed = len(STANDARD_COA) - created_count
            self.stdout.write(self.style.SUCCESS(
                f"{org.name}: {created_count} account(s) created, "
                f"{already_existed} already existed."
            ))
