# =============================================================================
# === backend/apps/service/migrations/0004_move_inventory_models_out.py ===
# The other half of the move — tells apps.service's migration state
# these models no longer live here. State-only (no real SQL): the
# tables themselves were already renamed and reassigned by
# apps.inventory's 0001_initial migration, which this one depends on
# — it MUST run after that, or Django would briefly have no owner (or
# two owners) for the same table in its migration state.
# =============================================================================
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("service", "0003_vehicle_body_style_vehicle_bpkb_number_and_more"),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Children before parent, mirroring the FK direction —
                # PartUsage/StockAdjustment both reference Part.
                migrations.DeleteModel(name="PartUsage"),
                migrations.DeleteModel(name="StockAdjustment"),
                migrations.DeleteModel(name="Part"),
            ],
        ),
    ]
