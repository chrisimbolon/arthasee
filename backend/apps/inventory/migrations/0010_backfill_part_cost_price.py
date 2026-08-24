# =============================================================================
# === backend/apps/inventory/migrations/0010_backfill_part_cost_price.py ===
# =============================================================================
"""
Real data migration, not hand-guessed schema — backfills Part.cost_price
for every existing part FROM ITS OWN REAL GRN HISTORY, matching exactly
what GoodsReceivedNoteLineItem.save() will do going forward (Made's own
confirmed "Last Cost" call): the most recent GoodsReceivedNoteLineItem,
by created_at, per part.

Deliberately generalized to EVERY part with real GRN history, not
hardcoded to the 4 parts known at the time this was written (Busi,
Filter, Kanvas Rem, Oli Mesin) — a future part that already has real
GRN history by the time this runs gets backfilled correctly too, same
logic, no special-casing.

A part with NO real GRN history at all is deliberately left at
cost_price=0 (the field's own real default) — that's the honest,
correct state for a genuinely never-received part, not something to
backfill from a guess. WorkOrderMaterialLine's own soft-fallback rule
already handles that 0 case correctly at consumption time.

Reverse is deliberately a no-op — reversing this migration should
never silently reset cost_price back to 0 for every part; that would
be real, destructive data loss for a value reflecting genuine GRN
history this migration didn't invent, just surfaced.
"""
from django.db import migrations


def backfill_cost_price_from_latest_grn(apps, schema_editor):
    Part = apps.get_model("inventory", "Part")
    GoodsReceivedNoteLineItem = apps.get_model("purchasing", "GoodsReceivedNoteLineItem")

    for part in Part.objects.all():
        latest_line = (
            GoodsReceivedNoteLineItem.objects
            .filter(part=part)
            .order_by("-created_at")
            .first()
        )
        if latest_line is not None:
            part.cost_price = latest_line.unit_cost
            part.save(update_fields=["cost_price"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0009_part_cost_price"),
        # Confirmed real, latest applied purchasing migration —
        # directly verified via your own earlier `migrate` output
        # ("Applying purchasing.0006_supplierpartcode... OK"), not
        # guessed. GoodsReceivedNoteLineItem's table has existed
        # since long before this, but depending on the real latest
        # migration is the safe, correct choice regardless.
        ("purchasing", "0006_supplierpartcode"),
    ]

    operations = [
        migrations.RunPython(backfill_cost_price_from_latest_grn, noop_reverse),
    ]
