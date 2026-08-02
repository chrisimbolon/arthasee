# =============================================================================
# === backend/apps/workorders/management/commands/backfill_stage_timestamps.py
# =============================================================================
"""
Chris's own catch, 3 Aug — the going-forward fix landed in
WorkOrder.close() (see that method's own comment), but it only runs
at the moment a WorkOrder actually closes. It can't reach back and
fix a WorkOrder that was already DONE before this fix shipped —
confirmed live: WO #23's own "Overhaul" stage still showed "Menunggu"
on the public tracking page after the code fix was deployed, because
close() was never called again for it.

This command is the other half of that fix: a one-time pass over
every existing DONE WorkOrder, backfilling any stage still missing
its own started_at/completed_at — same first-time-wins rule as
close() itself, never overwrites a real existing timestamp.

Run once after deploying the close() fix:
    python manage.py backfill_stage_timestamps
Safe to run more than once (idempotent) — a second run finds nothing
left to change, since every field it touches is only ever filled from
None, never overwritten.
"""
from apps.workorders.models import WorkOrder, WorkOrderStage
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        "One-time backfill: fills started_at/completed_at for any "
        "WorkOrderStage still open on an already-DONE WorkOrder, "
        "using that WorkOrder's own updated_at as the closest real "
        "signal available for when it actually finished."
    )

    def handle(self, *args, **options):
        done_orders = WorkOrder.objects.filter(status="DONE").prefetch_related("stages")
        orders_touched = 0
        stages_touched = 0

        with transaction.atomic():
            for wo in done_orders:
                # updated_at is the closest real, honest signal
                # available for "when this WorkOrder actually
                # finished" — close() itself is the last thing to
                # touch this field for a DONE WorkOrder that hasn't
                # been modified since. Not perfect (a WorkOrder edited
                # after closing would drift updated_at forward), but
                # far better than stamping every backfilled stage with
                # today's date regardless of when the real work
                # happened.
                backfill_time = wo.updated_at
                stages_to_update = []
                for stage in wo.stages.all():
                    changed = False
                    if stage.started_at is None:
                        stage.started_at = backfill_time
                        changed = True
                    if stage.completed_at is None:
                        stage.completed_at = backfill_time
                        changed = True
                    if changed:
                        stages_to_update.append(stage)

                if stages_to_update:
                    WorkOrderStage.objects.bulk_update(stages_to_update, ["started_at", "completed_at"])
                    orders_touched += 1
                    stages_touched += len(stages_to_update)

        self.stdout.write(self.style.SUCCESS(
            f"Backfilled {stages_touched} stage(s) across {orders_touched} already-DONE work order(s)."
        ))
