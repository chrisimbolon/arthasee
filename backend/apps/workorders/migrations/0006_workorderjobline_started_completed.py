# =============================================================================
# === backend/apps/workorders/migrations/0006_workorderjobline_started_completed.py
# =============================================================================
"""
IMPORTANT — do not run `manage.py makemigrations` for this change and
apply the auto-generated result directly. Django would generate a
bare RemoveField(is_done) + two AddField()s with no data-preservation
step, which would silently wipe out which real job lines are already
marked done in production today (Arya Motor's live data).

This migration is hand-written specifically to preserve that data:
add the new fields, backfill them from is_done via RunPython, THEN
remove is_done — in that exact order. Verify the dependency below
matches your actual last workorders migration (should be
0005_workorder_assigned_to as of 4 Aug — check your own
apps/workorders/migrations/ folder and adjust if it's moved on).
"""
from django.db import migrations, models


def backfill_completed_at_from_is_done(apps, schema_editor):
    WorkOrderJobLine = apps.get_model("workorders", "WorkOrderJobLine")
    # Real production data preservation — Chris's own explicit
    # concern, 4 Aug: is_done is being dropped as a stored field
    # (Option B), but real job lines in Arya Motor's live data are
    # already marked done today. created_at is the best available
    # stand-in for both started_at and completed_at — same "closest
    # honest signal available" reasoning already used by
    # backfill_stage_timestamps for already-DONE WorkOrders. Not
    # perfect (the real start/complete moment was never tracked, so
    # it can't be recovered), but far better than silently losing
    # which items were done at all.
    for line in WorkOrderJobLine.objects.filter(is_done=True):
        line.started_at = line.created_at
        line.completed_at = line.created_at
        line.save(update_fields=["started_at", "completed_at"])


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op, not a real reversal — going back to a
    # bare is_done boolean would itself lose the real started_at/
    # completed_at data this migration exists to preserve. If this
    # ever needs reversing, that's a real decision to make
    # deliberately, not something a generic reverse should silently
    # do.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("workorders", "0005_workorder_assigned_to"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorderjobline", name="started_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Mulai"),
        ),
        migrations.AddField(
            model_name="workorderjobline", name="completed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Selesai"),
        ),
        migrations.RunPython(backfill_completed_at_from_is_done, noop_reverse),
        migrations.RemoveField(
            model_name="workorderjobline", name="is_done",
        ),
    ]
