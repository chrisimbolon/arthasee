# =============================================================================
# === backend/apps/accounting/migrations/0009_backfill_account_subtypes.py ===
# =============================================================================
"""
8 Sep 2026 — real data migration, backfilling account_subtype/
is_contra/is_control_account onto every EXISTING Account row for
every ALREADY-SEEDED organization (CV Arya Motor included).

Real, honest reason this is a separate migration, not just a re-run
of seed_coa: seed_chart_of_accounts()'s own get_or_create() only sets
these fields on a brand-new row — it can never safely retrofit them
onto an account that already exists, since blindly overwriting an
existing row risks clobbering a shop's own accountant's later
customization (a renamed account, say). A migration is the correct,
explicit, one-time tool for this — matching the exact precedent
already set when account 1402 itself was backfilled onto CV Arya
Motor's own pre-existing COA.

Deliberately ONLY touches accounts whose `code` matches a real,
known STANDARD_COA code (hardcoded below, not imported from
apps.accounting.coa — migrations must be self-contained snapshots,
never reach into application code that could itself change later and
silently break replaying this exact migration against a fresh
database). Any custom account a shop has added beyond the standard
set is left completely untouched — there is no way to safely infer
its intended subtype, and this migration must never guess.
"""
from django.db import migrations

# (code, account_subtype, is_contra, is_control_account) — the exact
# same real values as apps.accounting.coa.STANDARD_COA at the moment
# this migration was written, deliberately duplicated here rather
# than imported, per standard Django migration practice.
BACKFILL_VALUES = [
    ("1001", "KAS_SETARA_KAS", False, False),
    ("1101", "KAS_SETARA_KAS", False, False),
    ("1201", "PIUTANG_USAHA", False, True),
    ("1301", "PERSEDIAAN", False, True),
    ("1302", "PERSEDIAAN", False, False),
    ("1401", "ASET_TETAP", False, False),
    ("1402", "ASET_TETAP", True, False),
    ("2001", "UTANG_USAHA", False, True),
    ("2010", "UTANG_LAINNYA", False, False),
    ("2101", "UTANG_PAJAK", False, False),
    ("3001", "EKUITAS", False, False),
    ("3101", "EKUITAS", False, False),
    ("4001", "PENDAPATAN", False, False),
    ("4002", "PENDAPATAN", False, False),
    ("4003", "PENDAPATAN", False, False),
    ("4004", "PENDAPATAN_LAIN_LAIN", False, False),
    ("5001", "BEBAN_POKOK_PENJUALAN", False, False),
    ("5002", "BEBAN_POKOK_PENJUALAN", False, False),
    ("5003", "BEBAN_POKOK_PENJUALAN", False, False),
    ("5004", "BEBAN_POKOK_PENJUALAN", False, False),
    ("6001", "BEBAN_USAHA", False, False),
    ("6002", "BEBAN_USAHA", False, False),
    ("6003", "BEBAN_USAHA", False, False),
    ("6004", "BEBAN_USAHA", False, False),
    ("6005", "BEBAN_LAIN_LAIN", False, False),
    ("6006", "BEBAN_LAIN_LAIN", False, False),
    # 3002 (Ekuitas Saldo Awal) deliberately NOT listed here — it is
    # a genuinely NEW account (this same review), so it doesn't exist
    # on any pre-existing organization to backfill; it will be
    # created fresh, with these fields already correct, the next
    # time seed_chart_of_accounts() runs for each real organization
    # (a real, separate, one-time step — run seed_coa again after
    # this migration to actually create 3002 on every existing org).
]


def backfill_subtypes(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    for code, subtype, is_contra, is_control in BACKFILL_VALUES:
        Account.objects.filter(code=code).update(
            account_subtype=subtype, is_contra=is_contra, is_control_account=is_control,
        )


def noop_reverse(apps, schema_editor):
    """
    Real, deliberate no-op reverse — clearing these fields back to
    "" / False on every account would be a safe, mechanical undo, but
    since account_type/normal_balance were NEVER derived retroactively
    for pre-existing rows here (only the new fields are set), there is
    nothing structurally unsafe left behind by simply not reversing
    this. If a genuine rollback is ever needed, clear account_subtype/
    is_contra/is_control_account by hand via the admin or a one-off
    shell command instead of relying on migrate's own reverse.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0008_account_account_subtype_account_is_contra_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_subtypes, noop_reverse),
    ]
