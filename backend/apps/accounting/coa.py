# =============================================================================
# === backend/apps/accounting/coa.py ===
# =============================================================================
"""
Arthasee — Chart of Accounts seeding

The one real, shared implementation behind both:
  - `python manage.py seed_coa` (management command — CLI/bulk use,
    for backfilling existing orgs or re-running after STANDARD_COA
    gains a new account)
  - apps.authentication.views.RegisterView.post() (real production
    signup — every new Organization created through the actual
    registration flow gets this called automatically, inside the
    same atomic transaction as the rest of signup)

Deliberately NOT hooked into Organization.save() itself — that would
fire for every Organization ever created anywhere, including every
test fixture across the whole suite (apps.workorders.tests,
apps.invoicing.tests, apps.payments.tests, apps.accounting.tests all
create Organization rows directly via the ORM, never through real
signup). Only the real registration path calls this automatically;
everywhere else (tests, data migrations, one-off scripts) seeds
explicitly and deliberately, matching the decision made when
AccountingEventHandler first went live.
"""
from apps.accounting.models import Account

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
    # PPh Final Pasal 4(2) — CV. Arya Motor's own confirmed real
    # obligation (2% on gross revenue, self-remitted monthly, paid by
    # the 8th — per direct discussion with their tax consultant, not
    # a general assumption for every future organization on this
    # platform). Deliberately NOT wired to any automatic posting rule
    # — Made computes and posts this by hand each month via the
    # Manual Adjusting Journal (Task 4.4/5.3), reviewed and confirmed
    # before submission, same as a real accountant would. This is
    # the correct architectural fit for a periodic, human-reviewed
    # figure — not a gap to be automated away, at least not yet
    # (revisit after a real first month's workflow is observed).
    ("6006", "Beban Pajak Penghasilan Final",          Account.AccountType.EXPENSE,   Account.NormalBalance.DEBIT),    
]


def seed_chart_of_accounts(organization) -> int:
    """
    Seeds the standard COA for one Organization. Returns the number
    of accounts actually created (0 if it was already fully seeded).

    Idempotent — get_or_create per (organization, code), same
    guarantee the old inline version had: safe to call more than
    once without duplicating anything or overwriting a name/type a
    shop's own accountant has since customized in Settings.
    """
    created_count = 0
    for code, name, account_type, normal_balance in STANDARD_COA:
        _, created = Account.objects.get_or_create(
            organization=organization, code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "normal_balance": normal_balance,
            },
        )
        if created:
            created_count += 1
    return created_count
