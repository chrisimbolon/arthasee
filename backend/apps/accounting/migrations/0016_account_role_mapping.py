# =============================================================================
# === backend/apps/accounting/migrations/0016_account_role_mapping.py ===
# =============================================================================
"""
6 Oct 2026 — Account Role Mapping, Batch 1 (global dependency layer).
Adds AccountRoleMapping and seeds all 14 roles, for every existing
organization, with EXACTLY the account code each role's posting rule
already hardcodes today (posting_engine.py / models.py, reconciled by
AST sweep — see AccountRole's own docstring in models.py for the
full scope correction this went through after Sansan's review).

Purely additive: no existing table altered, no existing JournalEntry/
JournalLine touched or reinterpreted. A brand-new model, seeded with
today's own values — a shop that never edits a row posts the
byte-identical journal entry it would post before this migration ran.

Real dependency confirmed: `ls backend/apps/accounting/migrations/ |
sort | tail -3` showed 0015_asset_categories as the latest migration in
this app. Named 0016_account_role_mapping.py accordingly.

Same discipline as 0015_asset_categories.py: this migration embeds its
own frozen copy of the seed data rather than importing coa.py's
STANDARD_ACCOUNT_ROLE_MAPPINGS, so a later change to that live list can
never silently alter this already-applied migration's behavior.
get_or_create throughout, defensive against a faked/retried migration.

Reverse is deliberately a no-op (migrations.RunPython.noop) — same
"never a silent destructive reversal of real financial configuration"
discipline this project holds everywhere else.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


def seed_role_mappings(apps, schema_editor):
    AccountRoleMapping = apps.get_model("accounting", "AccountRoleMapping")
    Organization = apps.get_model("organizations", "Organization")

    # (role, account_code) — frozen copy of coa.py's own
    # STANDARD_ACCOUNT_ROLE_MAPPINGS as of 6 Oct 2026. Every value here
    # is exactly the code posting_engine.py/models.py already hardcodes.
    ROLE_MAPPINGS = [
        ("CASH", "1001"),
        ("BANK", "1101"),
        ("AR", "1201"),
        ("AP", "2001"),
        ("GR_IR", "2010"),
        ("INVENTORY", "1301"),
        ("WIP", "1302"),
        ("REVENUE_SERVICE", "4001"),
        ("REVENUE_PARTS", "4002"),
        ("STOCK_OPNAME_SURPLUS", "4004"),
        ("MATERIAL_COGS", "5001"),
        ("STOCK_OPNAME_SHORTAGE", "5004"),
        ("OPENING_BALANCE_EQUITY", "3002"),
        ("RETAINED_EARNINGS", "3101"),
    ]

    for org in Organization.objects.all():
        for role, account_code in ROLE_MAPPINGS:
            AccountRoleMapping.objects.get_or_create(
                organization=org, role=role,
                defaults={"id": uuid.uuid4(), "account_code": account_code},
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0015_asset_categories"),
        ("organizations", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountRoleMapping",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(
                    choices=[
                        ("CASH", "Kas"), ("BANK", "Bank"), ("AR", "Piutang Usaha"),
                        ("AP", "Utang Usaha"), ("GR_IR", "Persediaan Belum Ditagih"),
                        ("INVENTORY", "Persediaan"), ("WIP", "Barang Dalam Proses"),
                        ("REVENUE_SERVICE", "Pendapatan Jasa"), ("REVENUE_PARTS", "Pendapatan Suku Cadang"),
                        ("STOCK_OPNAME_SURPLUS", "Selisih Stok Opname (Kelebihan)"),
                        ("MATERIAL_COGS", "HPP Sparepart (COGS)"),
                        ("STOCK_OPNAME_SHORTAGE", "Selisih Stok Opname (Kekurangan)"),
                        ("OPENING_BALANCE_EQUITY", "Ekuitas Saldo Awal"),
                        ("RETAINED_EARNINGS", "Laba Ditahan"),
                    ],
                    max_length=30, verbose_name="Peran Akun")),
                ("account_code", models.CharField(max_length=10, verbose_name="Kode Akun")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="organizations.organization")),
            ],
            options={
                "verbose_name": "Account Role Mapping",
                "verbose_name_plural": "Account Role Mappings",
                "ordering": ["role"],
                "unique_together": {("organization", "role")},
            },
        ),
        migrations.RunPython(seed_role_mappings, migrations.RunPython.noop),
    ]
