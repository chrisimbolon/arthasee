# =============================================================================
# === backend/apps/core/events/registry.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Event Type Registry

Maps a stored event_type string (Outbox.event_type) back to the real
DomainEvent subclass that produced it — the one piece genuinely
missing until now. Nothing before this needed to go from a stored
Outbox row BACK to a live DomainEvent instance; dispatch always
received an already-live event object at publish time, straight from
the code that just created it.

Needed for replay_failed_events (see
apps/core/management/commands/), the new command that reconstructs
and re-dispatches a FAILED Outbox row — e.g. the 5 real rows from
2026-08-09 that failed only because no AccountingPeriod existed yet
for CV Arya Motor in production.

Explicit, not auto-discovered — a hardcoded map is the same "boring
and correct" choice this project already makes elsewhere (e.g. the
fixed COA blueprint) rather than scanning every domain app's
events.py for DomainEvent subclasses at runtime.

Deliberately covers only the event types actually seen FAILED so
far — PartConsumed, WorkOrderCompleted, InvoiceIssued,
PaymentReceived — rather than guessing at every event class's exact
import path across every domain app without having verified each one
directly. event_class_for() raises a clear, actionable error for
anything not yet registered here, rather than silently mis-mapping —
extending this for a future failure in a different domain (e.g.
GoodsReceived, PurchaseReturned) is a one-line addition once that
event class's real file is confirmed the same way these four were.

Imports are deliberately lazy (inside the function, not at module
level) — matches the same reasoning dispatcher.py already uses for
its own Outbox import: avoids any startup import-ordering question
between apps/core/events/ and every domain app's own events.py.
"""
from __future__ import annotations

from apps.core.events.interfaces import DomainEvent


def event_class_for(event_type: str) -> type[DomainEvent]:
    from apps.inventory.events import PartConsumed
    from apps.invoicing.events import InvoiceIssued
    from apps.payments.events import PaymentReceived
    from apps.workorders.events import WorkOrderCompleted

    registry: dict[str, type[DomainEvent]] = {
        "PartConsumed": PartConsumed,
        "WorkOrderCompleted": WorkOrderCompleted,
        "InvoiceIssued": InvoiceIssued,
        "PaymentReceived": PaymentReceived,
    }
    try:
        return registry[event_type]
    except KeyError as exc:
        raise ValueError(
            f"No DomainEvent class registered for event_type={event_type!r} "
            f"in apps.core.events.registry.event_class_for(). Confirm the "
            f"real import path for this event class, then add it here — "
            f"deliberately not guessed at without verifying the source file."
        ) from exc
