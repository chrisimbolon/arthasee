# =============================================================================
# === backend/apps/inventory/migrations/0005_add_minimum_stock.py ===
# =============================================================================
from django.db import migrations, models


def backfill_existing_parts_to_five(apps, schema_editor):
    """
    Real, confirmed decision: every Part that existed BEFORE this
    migration ran gets minimum_stock=5, preserving today's exact
    global "<=5" alerting behavior for real, already-existing parts.

    This runs as a SEPARATE step, after AddField below — AddField's
    own default=0 already backfills every current row to 0 first;
    this explicitly overrides that to 5 for every row that exists at
    the moment THIS step runs. Any Part created after this migration
    completes (via the real app, post-deploy) is never touched by
    this function at all — it simply gets the model's own Python-
    level default (0) applied normally at insert time. Verified by
    hand before being written here — see the conversation this
    migration came from for the exact trace.
    """
    Part = apps.get_model("inventory", "Part")
    Part.objects.all().update(minimum_stock=5)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_alter_stockadjustment_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="part",
            name="minimum_stock",
            field=models.DecimalField(
                max_digits=10, decimal_places=2, default=0, verbose_name="Stok Minimum",
                help_text="Ambang batas peringatan stok menipis untuk part ini — 0 berarti tidak ada peringatan dari threshold ini (part yang benar-benar habis tetap muncul).",
            ),
        ),
        migrations.RunPython(backfill_existing_parts_to_five, migrations.RunPython.noop),
    ]
