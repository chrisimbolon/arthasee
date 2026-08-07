# =============================================================================
# === backend/apps/core/events/bus.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Publish / Subscribe

The one object domain apps actually talk to. Producers never know
who (if anyone) consumes an event — they just call
default_bus.publish(event) and move on; consumers subscribe
independently, in their own apps.py.ready(), with zero coupling back
to the producer (Roadmap v2.2, "Loose Coupling").

Transport is deliberately swappable later (see the canonical visual's
own "Technology Options" panel: In-Process today, Redis/RabbitMQ/
Kafka/NATS later once real cross-process fan-out is actually needed)
— nothing about this file's public API (subscribe/publish) needs to
change for that swap; only what happens inside publish() would.
"""
from __future__ import annotations

import threading
from collections import defaultdict

from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent


class EventBus:
    """
    In-process pub/sub registry. One instance (default_bus, below) is
    shared process-wide — every domain app's ready() subscribes its
    handler(s) to this same instance at Django startup.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, handler: EventHandler) -> None:
        with self._lock:
            for event_type in handler.handles:
                self._subscribers[event_type].append(handler)

    def subscribers_for(self, event_type: str) -> list[EventHandler]:
        return list(self._subscribers.get(event_type, []))

    def publish(self, event: DomainEvent):
        """
        Two things happen here, in order, and only the first one is
        guaranteed synchronous:

        1. An Outbox row is written NOW, inside whatever transaction
           the caller is already in (WorkOrder.close()-style
           transaction.atomic() blocks, Sprint 2). This is the
           "Transactional Safety" / "Outbox ensures reliable
           delivery" guarantee from the canonical visual — the event
           is durably recorded even if every handler for it fails, or
           there are no handlers at all yet.

        2. Actual handler dispatch is deferred to run AFTER that
           transaction commits (see dispatcher.py's use of
           transaction.on_commit()) — so a handler never reacts to an
           event whose own source transaction later rolls back, and a
           handler's own failure can never roll back the business
           operation that published the event. If no transaction is
           active, Django runs the on_commit callback immediately, so
           behavior degrades gracefully outside a transaction too.

        Returns the created Outbox row (mostly useful for tests and
        the future Sprint 4 Audit Log Viewer, which will read Outbox
        directly).
        """
        from apps.core.events.dispatcher import default_dispatcher
        from apps.core.events.outbox import Outbox

        outbox_row = Outbox.objects.create(
            organization_id=event.organization_id,
            event_id=event.event_id,
            event_type=event.event_type,
            payload=event.payload(),
            occurred_at=event.occurred_at,
        )
        default_dispatcher.dispatch_after_commit(
            event, self.subscribers_for(event.event_type), outbox_row.id,
        )
        return outbox_row


# Shared, process-wide instance. Domain apps import this directly
# (see EventHandler.register's own docstring for the subscribe-side
# call shape) rather than constructing their own EventBus — there is
# exactly one real event bus in this system.
default_bus = EventBus()
