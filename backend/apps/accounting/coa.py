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
test fixture across the whole codebase. Only the real registration
path calls this automatically; everywhere else (tests, data
migrations, one-off scripts) seeds explicitly and deliberately.

8 Sep 2026 — every row now carries account_subtype/is_contra/
is_control_account, following the direct review with Aris (Chris's
brother, a professional accountant) against a real reference
implementation. Real, honest limitation, not a silent gap: seed_
chart_of_accounts()'s own get_or_create() only fills these fields in
for a NEW row — an org whose COA was already seeded before this
change (CV Arya Motor included) will NOT retroactively pick these up
just by re-running this command. See the dedicated data migration
(migrations/0XXX_backfill_account_subtypes.py) for how those existing
rows actually get backfilled — a deliberate, separate, explicit step,
not something this idempotent seeding function can safely do on its
own (it must never silently overwrite a field a shop's own accountant
may have since customized).
"""
from apps.accounting.models import Account

AccountType = Account.AccountType
NormalBalance = Account.NormalBalance
AccountSubtype = Account.AccountSubtype

# (code, name, account_type, normal_balance, account_subtype, is_contra,
# is_control_account) — matches Roadmap v2.2's COA Blueprint, plus
# account 3002 (new, 8 Sep 2026 — Opening Balance Equity plug), plus
# the three real control-account flags (1201/1301/2001) and the one
# real contra-account flag (1402), plus a genuine account_subtype for
# every real, standard account — a shop's own custom accounts added
# later are unaffected; this list only ever seeds the standard set.
STANDARD_COA = [
    ("1001", "Cash",                              AccountType.ASSET,     NormalBalance.DEBIT,  AccountSubtype.KAS_SETARA_KAS,    False, False),
    ("1101", "Bank",                               AccountType.ASSET,     NormalBalance.DEBIT,  AccountSubtype.KAS_SETARA_KAS,    False, False),
    ("1201", "Accounts Receivable",                AccountType.ASSET,     NormalBalance.DEBIT,  AccountSubtype.PIUTANG_USAHA,     False, True),
    ("1301", "Inventory",                          AccountType.ASSET,     NormalBalance.DEBIT,  AccountSubtype.PERSEDIAAN,        False, True),
    ("1302", "Work In Progress (WIP)",              AccountType.ASSET,     NormalBalance.DEBIT,  AccountSubtype.PERSEDIAAN,        False, False),
    ("1401", "Fixed Assets",                        AccountType.ASSET,     NormalBalance.DEBIT,  AccountSubtype.ASET_TETAP,        False, False),
    ("1402", "Accumulated Depreciation",            AccountType.ASSET,     NormalBalance.CREDIT, AccountSubtype.ASET_TETAP,        True,  False),
    ("2001", "Accounts Payable",                    AccountType.LIABILITY, NormalBalance.CREDIT, AccountSubtype.UTANG_USAHA,       False, True),
    ("2010", "Accrued Inventory (Unbilled AP)",      AccountType.LIABILITY, NormalBalance.CREDIT, AccountSubtype.UTANG_LAINNYA,     False, False),
    ("2101", "Tax Payable",                         AccountType.LIABILITY, NormalBalance.CREDIT, AccountSubtype.UTANG_PAJAK,       False, False),
    ("3001", "Owner Capital",                        AccountType.EQUITY,    NormalBalance.CREDIT, AccountSubtype.EKUITAS,           False, False),
    # 8 Sep 2026 — new. Ekuitas Saldo Awal — the real, dedicated
    # target for OpeningBalanceSession.post()'s own explicit variance
    # plug (Chris/Aris's own confirmed hybrid design). Kept
    # deliberately SEPARATE from 3001 (Owner Capital) — a real,
    # explicit capital contribution Made states himself must never be
    # silently mixed together with a rounding/data-entry variance the
    # system allocated on his behalf.
    ("3002", "Ekuitas Saldo Awal",                   AccountType.EQUITY,    NormalBalance.CREDIT, AccountSubtype.EKUITAS,           False, False),
    ("3101", "Retained Earnings",                    AccountType.EQUITY,    NormalBalance.CREDIT, AccountSubtype.EKUITAS,           False, False),
    ("4001", "Service Revenue",                      AccountType.REVENUE,   NormalBalance.CREDIT, AccountSubtype.PENDAPATAN,        False, False),
    ("4002", "Parts Revenue",                        AccountType.REVENUE,   NormalBalance.CREDIT, AccountSubtype.PENDAPATAN,        False, False),
    ("4003", "Sublet / Outsourcing Revenue",         AccountType.REVENUE,   NormalBalance.CREDIT, AccountSubtype.PENDAPATAN,        False, False),
    ("4004", "Selisih Stok Opname (Kelebihan)",       AccountType.REVENUE,   NormalBalance.CREDIT, AccountSubtype.PENDAPATAN_LAIN_LAIN, False, False),
    ("5001", "HPP Sparepart (COGS)",                 AccountType.COGS,      NormalBalance.DEBIT,  AccountSubtype.BEBAN_POKOK_PENJUALAN, False, False),
    ("5002", "HPP Sublet / Jasa Luar",                AccountType.COGS,      NormalBalance.DEBIT,  AccountSubtype.BEBAN_POKOK_PENJUALAN, False, False),
    ("5003", "HPP Pelumas & Fluida",                  AccountType.COGS,      NormalBalance.DEBIT,  AccountSubtype.BEBAN_POKOK_PENJUALAN, False, False),
    ("5004", "Selisih Stok Opname (Kekurangan)",      AccountType.COGS,      NormalBalance.DEBIT,  AccountSubtype.BEBAN_POKOK_PENJUALAN, False, False),
    ("6001", "Beban Gaji",                            AccountType.EXPENSE,   NormalBalance.DEBIT,  AccountSubtype.BEBAN_USAHA,       False, False),
    ("6002", "Beban Sewa",                            AccountType.EXPENSE,   NormalBalance.DEBIT,  AccountSubtype.BEBAN_USAHA,       False, False),
    ("6003", "Beban Listrik, Air, Telp",               AccountType.EXPENSE,   NormalBalance.DEBIT,  AccountSubtype.BEBAN_USAHA,       False, False),
    ("6004", "Beban Penyusutan",                      AccountType.EXPENSE,   NormalBalance.DEBIT,  AccountSubtype.BEBAN_USAHA,       False, False),
    ("6005", "Beban Lain-lain",                       AccountType.EXPENSE,   NormalBalance.DEBIT,  AccountSubtype.BEBAN_LAIN_LAIN,   False, False),
    ("6006", "Beban Pajak Penghasilan Final",          AccountType.EXPENSE,   NormalBalance.DEBIT,  AccountSubtype.BEBAN_LAIN_LAIN,   False, False),
]


def seed_chart_of_accounts(organization) -> int:
    """
    Seeds the standard COA for one Organization. Returns the number
    of accounts actually created (0 if it was already fully seeded).

    Idempotent — get_or_create per (organization, code), same
    guarantee the old inline version had: safe to call more than
    once without duplicating anything or overwriting a name/type a
    shop's own accountant has since customized in Settings. This
    ALSO means a pre-existing account never picks up new fields
    (account_subtype/is_contra/is_control_account) just from a
    re-run — see this module's own docstring for the dedicated data
    migration that backfills those onto already-seeded organizations.
    """
    created_count = 0
    for code, name, account_type, normal_balance, account_subtype, is_contra, is_control_account in STANDARD_COA:
        _, created = Account.objects.get_or_create(
            organization=organization, code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "normal_balance": normal_balance,
                "account_subtype": account_subtype,
                "is_contra": is_contra,
                "is_control_account": is_control_account,
            },
        )
        if created:
            created_count += 1
    return created_count
