# =============================================================================
# === backend/apps/inventory/migrations/0001_initial.py ===
# Moves Part, PartUsage, StockAdjustment from apps.service into this
# app WITHOUT losing or recreating any existing data.
#
# Two things happen here, deliberately kept separate:
#   1. SeparateDatabaseAndState — tells Django's migration STATE that
#      these three models now belong to `inventory`, without issuing
#      any real SQL. The `db_table` on each is set to the table name
#      that already exists (service_part, etc.) so this step is 100%
#      bookkeeping, zero risk to data.
#   2. Three real AlterModelTable operations — these DO issue actual
#      SQL (`ALTER TABLE ... RENAME TO ...`), moving the physical
#      table names to match the new app going forward. Postgres
#      table renames are near-instant metadata operations, not a
#      data copy — but this is still the one part of this migration
#      that touches the real database, worth knowing which line it is.
#
# Must run AFTER apps.service's own migration that first created
# these tables (0003), and after organizations' initial migration
# (Part/PartUsage/StockAdjustment all inherit TenantScopedModel's FK
# to Organization).
# =============================================================================
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0001_initial"),
        ("service", "0003_vehicle_body_style_vehicle_bpkb_number_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Part",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="organizations.organization")),
                        ("name", models.CharField(max_length=200, verbose_name="Nama Part")),
                        ("sku", models.CharField(blank=True, max_length=50, verbose_name="Kode/SKU")),
                        ("unit", models.CharField(default="pcs", max_length=20, verbose_name="Satuan")),
                        ("current_stock", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Stok Saat Ini")),
                        ("unit_price", models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="Harga Satuan")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "verbose_name": "Part",
                        "verbose_name_plural": "Parts",
                        "ordering": ["name"],
                        "db_table": "service_part",
                    },
                ),
                migrations.CreateModel(
                    name="PartUsage",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="organizations.organization")),
                        ("quantity", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Jumlah")),
                        ("unit_price_at_time", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Harga Saat Digunakan")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("part", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="usages", to="inventory.part", verbose_name="Part")),
                        ("service_record", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="part_usages", to="service.servicerecord", verbose_name="Catatan Servis")),
                    ],
                    options={
                        "verbose_name": "Part Usage",
                        "verbose_name_plural": "Part Usages",
                        "ordering": ["-created_at"],
                        "db_table": "service_partusage",
                    },
                ),
                migrations.CreateModel(
                    name="StockAdjustment",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="organizations.organization")),
                        ("quantity_change", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Perubahan Jumlah")),
                        ("reason", models.CharField(choices=[("restock", "Restock / Pembelian"), ("correction", "Koreksi Stok"), ("damage", "Rusak / Hilang")], default="restock", max_length=20, verbose_name="Alasan")),
                        ("notes", models.TextField(blank=True, verbose_name="Catatan")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                        ("part", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="adjustments", to="inventory.part", verbose_name="Part")),
                    ],
                    options={
                        "verbose_name": "Stock Adjustment",
                        "verbose_name_plural": "Stock Adjustments",
                        "ordering": ["-created_at"],
                        "db_table": "service_stockadjustment",
                    },
                ),
            ],
        ),
        # The one part of this migration that touches the real
        # database — three metadata-only table renames.
        migrations.AlterModelTable(name="part", table="inventory_part"),
        migrations.AlterModelTable(name="partusage", table="inventory_partusage"),
        migrations.AlterModelTable(name="stockadjustment", table="inventory_stockadjustment"),
    ]
