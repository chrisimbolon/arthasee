# =============================================================================
# === backend/apps/core/management/commands/replay_failed_events.py ===
# =============================================================================
"""
Arthasee — Replay Failed Outbox Events

The real fix for the exact failure mode this project hit for real on
2026-08-09: a domain event's handler failed (no AccountingPeriod
existed yet for CV Arya Motor), the Outbox row was marked FAILED,
and — until this command existed — nothing could ever revisit it.
The underlying business action (the work order, the invoice, the
payment) already succeeded at the time and is never touched by this
command; only the deferred accounting posting is retried.

Safe to run more than once: a row that dispatches cleanly is marked
PROCESSED and won't be picked up by a future run (this command only
ever targets status=FAILED). A row that fails again for a DIFFERENT
reason is left FAILED with the new last_error overwriting the old
one — visible on the next run of this same command, or a manual
Outbox check.

Dry run by default — reports exactly what WOULD be replayed without
touching anything. Requires --confirm to actually replay, so this is
safe to run cold in production to see the real scope of a failure
before committing to fixing it.
"""
from django.core.management.base import BaseCommand

from apps.core.events.dispatcher import default_dispatcher
from apps.core.models import Outbox


class Command(BaseCommand):
    help = "Replay FAILED Outbox events through the real dispatch path."

    def add_arguments(self, parser):
        parser.add_argument(
            "--event-id", action="append", default=None,
            help="Replay only this specific Outbox row id (repeatable "
                 "flag). Omit to target every FAILED row.",
        )
        parser.add_argument(
            "--confirm", action="store_true",
            help="Actually replay. Without this flag, only reports what "
                 "would be replayed — no data is touched.",
        )

    def handle(self, *args, **options):
        qs = Outbox.objects.filter(status=Outbox.Status.FAILED).order_by("created_at")
        if options["event_id"]:
            qs = qs.filter(id__in=options["event_id"])

        rows = list(qs)
        if not rows:
            self.stdout.write(self.style.WARNING("No FAILED Outbox rows match."))
            return

        self.stdout.write(f"{len(rows)} FAILED row(s) targeted:")
        for row in rows:
            self.stdout.write(
                f"  {row.id} | {row.event_type} | {row.created_at} | {row.last_error}"
            )

        if not options["confirm"]:
            self.stdout.write(self.style.WARNING(
                "Dry run only — nothing replayed. Re-run with --confirm to "
                "actually replay."
            ))
            return

        succeeded = 0
        still_failed = 0
        for row in rows:
            default_dispatcher.dispatch_now(row.id)
            row.refresh_from_db()
            if row.status == Outbox.Status.PROCESSED:
                succeeded += 1
                self.stdout.write(self.style.SUCCESS(
                    f"Processed — {row.id} ({row.event_type})"
                ))
            else:
                still_failed += 1
                self.stdout.write(self.style.ERROR(
                    f"Still failed — {row.id} ({row.event_type}): {row.last_error}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"Done. Processed: {succeeded}, Still failed: {still_failed}"
        ))
