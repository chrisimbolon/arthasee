# =============================================================================
# === backend/apps/accounting/migrations/0015_asset_categories.py ===
# =============================================================================
"""
4 Oct 2026 — Fixed-asset categories. Adds AssetCategory, adds Asset.category,
backfills every existing org with the two seeded categories (Peralatan,
Kendaraan) and the three new Account rows Kendaraan needs (1403/1404/6007),
and points every existing Asset row at Peralatan — the category whose
accounts (1401/1402/6004) are the exact ones every Asset already posted to
before this feature existed, so this backfill changes nothing about any
already-posted journal entry's meaning.

Real dependency confirmed: `ls backend/apps/accounting/migrations/ | sort |
tail -3` showed 0014_openingbalancesession_confirmed_zero_at_and_more as the
latest migration in this app — that's what this migration now depends on.
Named 0015_asset_categories.py accordingly.

The AssetCategory CreateModel's own `organization` field below is written
to match TenantScopedModel exactly (apps/core/models.py, confirmed 4 Oct
2026): ForeignKey to "organizations.Organization", on_delete=CASCADE, not
nullable, no related_name override — the same shape Account/Asset/every
other real model in this app already gets from that same abstract base.

Three real correctness points, worth reading before touching this file:

1. Historical models (via apps.get_model(), used throughout the data
   migration below) carry ONLY fields — no custom save()/property/method
   logic, even if the live model defines one. This matters here because
   Account.save() normally DERIVES account_type/normal_balance/
   is_control_account from account_subtype — that derivation will NOT run
   on a historical model. Every new Account row below supplies all of
   those fields explicitly instead, pre-derived by hand from the live
   SUBTYPE_CLASSIFICATION mapping (ASET_TETAP -> ASSET/DEBIT, is_contra
   flips the accumulated-depreciation row to CREDIT; BEBAN_USAHA ->
   EXPENSE/DEBIT) — the exact same values coa.py's own STANDARD_COA
   entries for 1403/1404/6007 carry, traced and confirmed directly
   against the real SUBTYPE_CLASSIFICATION dict before this shipped.
   Migrations are a frozen snapshot in time, deliberately never importing
   live app code — this migration embeds its own frozen copy of that
   data rather than importing coa.py's STANDARD_ASSET_CATEGORIES, so a
   later change to that live list can never silently alter this
   already-applied migration's behavior.

2. Three-step field addition, the standard safe Django pattern for adding
   a required FK to a table with existing rows: AddField as nullable ->
   RunPython backfill -> AlterField to non-nullable. Skipping straight to
   a non-nullable AddField would fail immediately against Arya's own
   existing Asset rows.

3. Reverse is deliberately a no-op (migrations.RunPython.noop) — reversing
   would mean deleting real seeded Account/AssetCategory rows and nulling
   out Asset.category, an inherently lossy operation for data that may
   already have real depreciation posted against it by the time anyone
   reverses. Same "never a silent destructive reversal" discipline this
   whole project holds for posted financial data everywhere else.

get_or_create is used throughout the data migration (not direct .create())
as a defensive, idempotent safeguard — protects against this migration
being faked, or retried after a crash mid-run, same discipline every real
seeding function in this codebase already follows.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


def seed_categories_and_backfill(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    AssetCategory = apps.get_model("accounting", "AssetCategory")
    Asset = apps.get_model("accounting", "Asset")
    Organization = apps.get_model("organizations", "Organization")

    # Pre-derived explicitly — see point 1 above for why this can't rely on
    # Account.save()'s normal derivation. Matches coa.py's STANDARD_COA
    # entries for these same three codes, field for field.
    NEW_ACCOUNTS = [
        # code,   name,                              account_type, normal_balance, account_subtype, is_contra, is_control_account
        ("1403", "Fixed Assets (Kendaraan)",          "ASSET",   "DEBIT",  "ASET_TETAP", False, False),
        ("1404", "Akumulasi Penyusutan (Kendaraan)",  "ASSET",   "CREDIT", "ASET_TETAP", True,  False),
        ("6007", "Beban Penyusutan (Kendaraan)",      "EXPENSE", "DEBIT",  "BEBAN_USAHA", False, False),
    ]
    # (name, fixed_asset_account_code, accumulated_depreciation_account_code,
    #  depreciation_expense_account_code, default_useful_life_months, is_default)
    NEW_CATEGORIES = [
        ("Peralatan", "1401", "1402", "6004", None, True),
        ("Kendaraan", "1403", "1404", "6007", 60,   False),
    ]

    for org in Organization.objects.all():
        for code, name, account_type, normal_balance, account_subtype, is_contra, is_control_account in NEW_ACCOUNTS:
            Account.objects.get_or_create(
                organization=org, code=code,
                defaults={
                    "id": uuid.uuid4(), "name": name, "account_type": account_type,
                    "normal_balance": normal_balance, "account_subtype": account_subtype,
                    "is_contra": is_contra, "is_control_account": is_control_account,
                },
            )

        peralatan = None
        for name, fixed_code, accum_code, expense_code, default_life, is_default in NEW_CATEGORIES:
            category, _ = AssetCategory.objects.get_or_create(
                organization=org, name=name,
                defaults={
                    "id": uuid.uuid4(),
                    "fixed_asset_account_code": fixed_code,
                    "accumulated_depreciation_account_code": accum_code,
                    "depreciation_expense_account_code": expense_code,
                    "default_useful_life_months": default_life,
                    "is_default": is_default,
                },
            )
            if is_default:
                peralatan = category

        # Every pre-existing Asset row (Arya's lift, tools, vehicles — all
        # of it) backfilled onto Peralatan, which carries the exact same
        # account codes (1401/1402/6004) every one of those rows already
        # posted its real acquisition/depreciation entries to. This changes
        # nothing about what any already-posted JournalLine means.
        Asset.objects.filter(organization=org, category__isnull=True).update(category=peralatan)


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0014_openingbalancesession_confirmed_zero_at_and_more"),
        ("organizations", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetCategory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100, verbose_name="Nama Kategori")),
                ("fixed_asset_account_code", models.CharField(
                    help_text="Akun yang didebit saat aset dalam kategori ini diperoleh.",
                    max_length=10, verbose_name="Kode Akun Aset Tetap")),
                ("accumulated_depreciation_account_code", models.CharField(
                    help_text="Akun kontra-aset yang dikredit setiap bulan saat aset dalam kategori ini disusutkan.",
                    max_length=10, verbose_name="Kode Akun Akumulasi Penyusutan")),
                ("depreciation_expense_account_code", models.CharField(
                    help_text="Akun beban yang didebit setiap bulan saat aset dalam kategori ini disusutkan.",
                    max_length=10, verbose_name="Kode Akun Beban Penyusutan")),
                ("default_useful_life_months", models.PositiveIntegerField(
                    blank=True, null=True,
                    help_text="Hanya nilai awal (prefill) pada form — selalu bisa diubah manual per aset.",
                    verbose_name="Umur Manfaat Default (Bulan)")),
                ("is_default", models.BooleanField(
                    default=False,
                    help_text="Kategori yang dipakai untuk aset lama/legacy yang belum dikategorikan — "
                              "satu per organisasi, ditentukan oleh seeding, bukan oleh pengguna.",
                    verbose_name="Kategori Default")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                # Matches TenantScopedModel exactly (apps/core/models.py,
                # confirmed): CASCADE, not nullable, no related_name override.
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="organizations.organization")),
            ],
            options={
                "verbose_name": "Asset Category",
                "verbose_name_plural": "Asset Categories",
                "ordering": ["name"],
                "unique_together": {("organization", "name")},
            },
        ),
        migrations.AddField(
            model_name="asset",
            name="category",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assets",
                to="accounting.assetcategory", verbose_name="Kategori Aset",
            ),
        ),
        migrations.RunPython(seed_categories_and_backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="asset",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="assets",
                to="accounting.assetcategory", verbose_name="Kategori Aset",
            ),
        ),
    ]
