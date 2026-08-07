# =============================================================================
# === backend/apps/core/events/handlers.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Handler Interface

Abstract base every consumer implements. One handler = one bounded
concern reacting to one or more event types — e.g. the future
apps.accounting.handlers.AccountingEventHandler reacting to
WorkOrderCompleted / PartConsumed / InvoiceIssued / PaymentReceived
(Sprint 2), never a grab-bag handler spanning unrelated domains.
"""
from __future__ import annotations

import abc

from apps.core.events.interfaces import DomainEvent


class EventHandler(abc.ABC):
    """
    handles: which event_type string(s) this handler reacts to. A
    tuple, not a single string — several related events (e.g.
    InvoiceIssued AND InvoiceCancelled) can legitimately share one
    handler class when the underlying logic is the same shape.
    """
    handles: tuple[str, ...] = ()

    @abc.abstractmethod
    def handle(self, event: DomainEvent) -> None:
        """
        Do the actual work for one event. Must be idempotent wherever
        realistically possible — a retry path (manual re-processing
        of a FAILED Outbox row, or a future Celery retry) may call
        this more than once for the same event.

        Raise on genuine failure rather than swallowing errors —
        EventDispatcher (see dispatcher.py) is what decides how a
        raised exception affects the Outbox row's status; a handler
        silently eating its own exception would make a real failure
        invisible in the audit trail.
        """
        raise NotImplementedError


def register(bus, handler: EventHandler) -> EventHandler:
    """
    Small convenience wrapper for the subscription call site each
    domain app's apps.py.ready() will use in Sprint 2, e.g.:

        from apps.core.events.bus import default_bus
        from apps.core.events.handlers import register
        from apps.accounting.handlers import AccountingEventHandler
        register(default_bus, AccountingEventHandler())

    Returns the handler unchanged so the call can be written as a
    single expression at import time if preferred.
    """
    bus.subscribe(handler)
    return handler
