# =============================================================================
# === backend/apps/core/events/dispatcher.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Dispatcher

Synchronous, in-process dispatch only, for now — deliberately, not
an oversight: requirements/base.txt has no Celery/Redis in it yet, so
there is no async transport to dispatch onto. Everything here is
still structured around the Outbox row's lifecycle (PENDING ->
PROCESSED/FAILED) specifically so that adding a real async transport
later is a change confined to this one file: a future Celery task
would just call `default_dispatcher.dispatch_now(event_id)` for a
PENDING Outbox row instead of this module calling it directly via
transaction.on_commit(). Nothing in bus.py, handlers.py, or any
domain app's events.py would need to change.
"""
from __future__ import annotations

import logging
import uuid

from django.db import transaction

from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent

logger = logging.getLogger("arthasee.events")


class EventDispatcher:
    def dispatch_after_commit(
        self, event: DomainEvent, handlers: list[EventHandler], outbox_id: uuid.UUID,
    ) -> None:
        """
        Registers dispatch to run once the current transaction
        actually commits (or immediately, if there is no open
        transaction — Django's own on_commit behavior). This is the
        real mechanism behind "a handler failure never rolls back the
        business operation that published the event": by the time any
        handler runs, the source transaction has already succeeded
        and committed.
        """
        def _run() -> None:
            self._dispatch_now(event, handlers, outbox_id)

        transaction.on_commit(_run)

    def _dispatch_now(
        self, event: DomainEvent, handlers: list[EventHandler], outbox_id: uuid.UUID,
    ) -> None:
        # Imported here, not at module level — outbox.py needs
        # nothing from this module, but this module needing the
        # Outbox model at call time (rather than import time) avoids
        # any startup import-ordering question between the two.
        from apps.core.events.outbox import Outbox

        try:
            outbox_row = Outbox.objects.get(pk=outbox_id)
        except Outbox.DoesNotExist:
            # Should not happen — the row is created in the same
            # transaction that scheduled this callback — but a
            # dispatcher must never raise out of an on_commit hook
            # (Django logs but otherwise ignores exceptions there),
            # so this is logged loudly rather than silently vanishing.
            logger.error(
                "Outbox row %s vanished before dispatch could run for event %s.",
                outbox_id, event.event_type,
            )
            return

        if not handlers:
            # No subscribers for this event_type yet is expected and
            # fine, not a failure — most domain events won't have any
            # accounting handler wired up until Sprint 2. The event
            # is still durably recorded in Outbox either way.
            outbox_row.mark_processed()
            return

        failures = []
        for handler in handlers:
            try:
                handler.handle(event)
            except Exception:
                logger.exception(
                    "Handler %s failed on event %s (event_id=%s)",
                    type(handler).__name__, event.event_type, event.event_id,
                )
                failures.append(type(handler).__name__)

        if failures:
            outbox_row.mark_failed(f"Handler(s) failed: {', '.join(failures)}")
        else:
            outbox_row.mark_processed()


# Shared, process-wide instance — mirrors default_bus in bus.py.
default_dispatcher = EventDispatcher()
