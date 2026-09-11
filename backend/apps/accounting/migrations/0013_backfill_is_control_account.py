# =============================================================================
# Task 18.1 — NEW FILE: backend/apps/accounting/migrations/0013_backfill_is_control_account.py
# =============================================================================
# Real data migration, no schema change — is_control_account already
# exists as a column; this recomputes its VALUE for every existing
# row with a real subtype set, reporting any row whose value would
# actually FLIP before doing so. Guards against a real backward-
# compat risk: if any shop already used Task 17.1's own API to mark
# a custom account is_control_account=True on a subtype OUTSIDE the
# three now-derived codes, this would silently un-protect it —
# printed here so it's visible at migrate time, not lost silently.
#
# Update the dependency below to match your real latest accounting
# migration if it differs from 0012.
# =============================================================================
from django.db import migrations

IS_CONTROL_SUBTYPES = {"PIUTANG_USAHA", "PERSEDIAAN", "UTANG_USAHA"}


def report_and_recompute_control_accounts(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")

    accounts_with_subtype = Account.objects.exclude(account_subtype="")
    flips = []
    for account in accounts_with_subtype.iterator():
        correct_value = account.account_subtype in IS_CONTROL_SUBTYPES
        if account.is_control_account != correct_value:
            flips.append((account.organization_id, account.code, account.is_control_account, correct_value))

    if flips:
        print("\n" + "=" * 78)
        print("Task 18.1 backfill — is_control_account is changing for these accounts:")
        for org_id, code, old, new in flips:
            print(f"  organization={org_id}  code={code}  {old} -> {new}")
        print(
            "If any of these used to be True and are now False, that account "
            "was previously protected as a custom control account outside the "
            "standard AR/Inventory/AP set — review whether that protection was "
            "actually relied on before proceeding."
        )
        print("=" * 78 + "\n")

    accounts_with_subtype.filter(account_subtype__in=IS_CONTROL_SUBTYPES).update(is_control_account=True)
    accounts_with_subtype.exclude(account_subtype__in=IS_CONTROL_SUBTYPES).update(is_control_account=False)


def noop_reverse(apps, schema_editor):
    # Deliberate no-op — reversing this would mean guessing each
    # account's PRE-backfill is_control_account value, which this
    # migration never stores anywhere. A genuinely lossy, one-way
    # data migration — same category as any other backfill that
    # recomputes a derived value from source data.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0012_journalentry_reverses_alter_journalentry_source"),
    ]

    operations = [
        migrations.RunPython(report_and_recompute_control_accounts, noop_reverse),
    ]
