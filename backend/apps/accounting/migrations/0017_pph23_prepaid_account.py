# =============================================================================
# === backend/apps/accounting/migrations/0017_pph23_prepaid_account.py ===
# =============================================================================
"""
9 Oct 2026 — PPh 23 + PPh Final UMKM tax remittance patch, backend
half. Seeds account 1205 "PPh 23 Dibayar Dimuka" (ASSET, DEBIT,
PIUTANG_LAINNYA) for every existing org — mirrors 0015_asset_
categories.py's own get_or_create idempotent seeding pattern exactly,
for the same reason: safe against being faked or retried mid-crash.

6006 "Beban Pajak Penghasilan Final" and 2101 "Tax Payable" are NOT
touched here — both already seeded by coa.py's own STANDARD_COA for
every org since before this patch; only the new 1205 code needs a
real backfill migration for orgs seeded before today.

TaxRemittance/TaxRemittanceSequence (apps.payments.models) are new
app tables, not accounting ones — Django's own makemigrations is what
actually generates those two CreateModel operations in
apps/payments/migrations/; this migration only touches apps.accounting
(the Account backfill). See the sibling payments migration this patch
also adds.
"""
import uuid

from django.db import migrations


def seed_pph23_account(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    Organization = apps.get_model("organizations", "Organization")

    for org in Organization.objects.all():
        Account.objects.get_or_create(
            organization=org, code="1205",
            defaults={
                "id": uuid.uuid4(),
                "name": "PPh 23 Dibayar Dimuka",
                "account_type": "ASSET",
                "normal_balance": "DEBIT",
                "account_subtype": "PIUTANG_LAINNYA",
                "is_contra": False,
                "is_control_account": False,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0016_account_role_mapping"),
        ("organizations", "__first__"),
    ]

    operations = [
        migrations.RunPython(seed_pph23_account, migrations.RunPython.noop),
    ]
