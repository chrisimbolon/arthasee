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
would just call `default_dispatcher.dispatch_now(outbox_id)` for a
PENDING Outbox row instead of this module calling it directly via
transaction.on_commit(). Nothing in bus.py, handlers.py, or any
domain app's events.py would need to change.

--- dispatch_now() added for real replay ---
This method is the real form of what the paragraph above already
promised on day one — it just didn't actually exist until a genuine
production incident needed it (5 real Outbox rows stuck FAILED on
2026-08-09, only because no AccountingPeriod existed yet). See
apps.core.events.registry for how a stored Outbox row gets
reconstructed back into a live DomainEvent, and
apps.core.management.commands.replay_failed_events for the actual
command that calls this.
"""
from __future__ import annotations

import logging
import uuid

from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent
from django.db import transaction

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

    def dispatch_now(self, outbox_id: uuid.UUID) -> None:
        """
        Reconstructs and re-dispatches a stored Outbox row directly —
        no live DomainEvent or handler list needs to be supplied by
        the caller, unlike _dispatch_now() below. Given just an id:

          1. Loads the real Outbox row.
          2. Reconstructs the original DomainEvent from its
             event_type + payload, via
             apps.core.events.registry.event_class_for() — the
             payload was stripped of envelope fields at publish time
             (DomainEvent.payload()), so reconstruction is exactly
             EventClass(organization_id=..., event_id=...,
             occurred_at=..., **payload), no guessing at field names.
          3. Re-resolves the CURRENT handler list from default_bus —
             asked fresh, not cached from whenever the event was
             first published, so a handler added after the original
             failure still gets picked up on replay.
          4. Dispatches immediately via _dispatch_now(), the exact
             same code path a first-time dispatch would run —
             replay behaves identically to an original dispatch, not
             a parallel, slightly-different mechanism.

        No transaction.on_commit() involved here — there is no new
        business transaction to defer past; reconstructing a past
        event isn't itself a business action requiring that guard.

        Used by replay_failed_events (see
        apps/core/management/commands/) — the real fix for FAILED
        Outbox rows whose underlying cause has since been resolved.
        """
        from apps.core.events.bus import default_bus
        from apps.core.events.outbox import Outbox
        from apps.core.events.registry import event_class_for

        outbox_row = Outbox.objects.get(pk=outbox_id)
        event_cls = event_class_for(outbox_row.event_type)
        event = event_cls(
            organization_id=outbox_row.organization_id,
            event_id=outbox_row.event_id,
            occurred_at=outbox_row.occurred_at,
            **outbox_row.payload,
        )
        handlers = default_bus.subscribers_for(event.event_type)
        self._dispatch_now(event, handlers, outbox_id)

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
