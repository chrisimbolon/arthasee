# =============================================================================
# === backend/apps/inventory/migrations/0007_part_taxonomy_reorder_cadence.py ===
# =============================================================================
"""
Sprint 7, Task 7.1 — adds item_type, vehicle_brand, fluid_brand,
viscosity_grade, reorder_cadence to Part.

No RunPython backfill needed — a single AddField(default=...) per
field is correct on its own, same "no backfill dance needed"
reasoning as PurchaseReturn.return_classification's own migration
(Roadmap v2.3, Phase 5, Task 5.2):

- item_type defaults to SPARE_PART, and both real existing parts
  (Busi, Filter) genuinely ARE spare parts — the default is the
  correct real value, not a placeholder.
- vehicle_brand, fluid_brand, viscosity_grade, reorder_cadence all
  default to "" (blank/unset) — the honestly correct state for
  existing parts, which have no historical brand/cadence data to
  backfill from. Same "Belum diisi" placeholder discipline as
  Vehicle's own self-registration fields (Sprint 6, Task 6.2), not a
  guess.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0006_alter_stockadjustment_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="part",
            name="item_type",
            field=models.CharField(
                choices=[("SPARE_PART", "Spare Part"), ("FLUID", "Fluida")],
                default="SPARE_PART", max_length=20, verbose_name="Jenis Item",
                help_text="Spare Part (spesifik per merk kendaraan) atau Fluida (universal lintas merk kendaraan).",
            ),
        ),
        migrations.AddField(
            model_name="part",
            name="vehicle_brand",
            field=models.CharField(
                blank=True, default="", max_length=30, verbose_name="Merk Kendaraan",
                help_text="Hanya berlaku untuk Spare Part — kosong berarti belum dikategorikan.",
                choices=[
                    ("TOYOTA", "Toyota"), ("HONDA", "Honda"), ("DAIHATSU", "Daihatsu"),
                    ("SUZUKI", "Suzuki"), ("MITSUBISHI", "Mitsubishi"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="part",
            name="fluid_brand",
            field=models.CharField(
                blank=True, default="", max_length=30, verbose_name="Merk Fluida",
                help_text="Hanya berlaku untuk Fluida — kosong berarti belum dikategorikan.",
                choices=[
                    ("SHELL", "Shell"), ("CASTROL", "Castrol"), ("REPSOL", "Repsol"),
                    ("FASTRON", "Fastron"), ("PERTAMINA_MEDITRAN", "Pertamina Meditran"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="part",
            name="viscosity_grade",
            field=models.CharField(
                blank=True, default="", max_length=20, verbose_name="Tingkat Kekentalan",
                help_text="Hanya berlaku untuk Fluida — kosong berarti belum dikategorikan.",
                choices=[
                    ("10W-40", "10W-40"), ("5W-30", "5W-30"),
                    ("SAE_90", "Oli 90 (SAE 90)"), ("SAE_140", "Oli 140 (SAE 140)"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="part",
            name="reorder_cadence",
            field=models.CharField(
                blank=True, default="", max_length=20, verbose_name="Frekuensi Pengecekan",
                help_text="Seberapa sering part ini ditinjau untuk pemesanan ulang. Kosong berarti belum dikategorikan.",
                choices=[
                    ("HARIAN", "Harian"), ("MINGGUAN", "Mingguan"),
                    ("BULANAN", "Bulanan"), ("TIGA_BULANAN", "3 Bulanan"),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="part",
            name="minimum_stock",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=10, verbose_name="Stok Minimum",
                help_text="Ambang batas peringatan stok menipis untuk part ini — 0 berarti tidak ada peringatan dari threshold ini (part yang benar-benar habis tetap muncul, kecuali untuk part dengan Frekuensi Pengecekan Harian).",
            ),
        ),
    ]
