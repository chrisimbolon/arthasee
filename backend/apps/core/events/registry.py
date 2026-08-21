# =============================================================================
# === backend/apps/core/events/registry.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Event Type Registry & Reconstruction

Maps a stored event_type string (Outbox.event_type) back to the real
DomainEvent subclass that produced it, and reconstructs a genuinely
usable, correctly-typed event instance from a stored Outbox row.

Needed for replay_failed_events (see
apps/core/management/commands/) — the command that reconstructs and
re-dispatches a FAILED Outbox row. Nothing before this ever needed
to go from a stored row BACK to a live event; dispatch always
received an already-live event object straight from the code that
just constructed it.

--- reconstruct_event() and the Decimal/UUID/date round-trip bug ---
Real production incident, found via the FIRST actual replay attempt
(2026-08-09's 5 FAILED rows): a naive `EventClass(**outbox_row.payload)`
raised `TypeError: '>' not supported between instances of 'str' and
'decimal.Decimal'` deep inside posting_engine.py — not a bug in that
file, which correctly expects real Decimal values.

The real cause: Outbox.payload is a JSONField, and JSON has no native
Decimal (or UUID, or date/datetime) type. DjangoJSONEncoder writes
each of those out as a plain string at publish time (see
apps.core.events.base's own module docstring) — and Django's
JSONField reads it back exactly that way: a str, not the original
type. A live, first-time dispatch never hits this, since it always
receives the ORIGINAL, still-real DomainEvent object, never
round-tripped through JSON. Replay is the first code path in this
whole system that ever needed to rebuild an event FROM storage, and
it's what actually exposed this gap.

reconstruct_event() fixes this generically, not by patching each
event class one at a time: it inspects the event class's own real
field types via typing.get_type_hints() (which resolves the string
annotations `from __future__ import annotations` produces back into
real type objects), and converts each payload string value back to
its real type only where the field's declared type says it should be
one of the types DjangoJSONEncoder is known to stringify. A field
genuinely meant to stay a string is never touched.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, get_type_hints

from apps.core.events.interfaces import DomainEvent

# The exact set of types DjangoJSONEncoder stringifies on write (see
# apps.core.events.base's own docstring) — kept in sync with that,
# not a general-purpose type-coercion list.
_ROUND_TRIP_TYPES = (Decimal, uuid.UUID, datetime, date)


def event_class_for(event_type: str) -> type[DomainEvent]:
    """
    Explicit, not auto-discovered — a hardcoded map is the same
    "boring and correct" choice this project already makes elsewhere
    (e.g. the fixed COA blueprint) rather than scanning every domain
    app's events.py for DomainEvent subclasses at runtime.

    Deliberately covers only the event types actually seen FAILED so
    far — PartConsumed, WorkOrderCompleted, InvoiceIssued,
    PaymentReceived — rather than guessing at every event class's
    exact import path across every domain app without having
    verified each one directly. Raises a clear, actionable error for
    anything not yet registered, rather than silently mis-mapping —
    extending this for a future failure in a different domain is a
    one-line addition once that event class's real file is confirmed
    the same way these four were.
    """
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


def _coerce(hint: Any, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if hint is Decimal:
        return Decimal(value)
    if hint is uuid.UUID:
        return uuid.UUID(value)
    if hint is datetime:
        return datetime.fromisoformat(value)
    if hint is date:
        return date.fromisoformat(value)
    return value


def reconstruct_event(outbox_row) -> DomainEvent:
    """
    Turns one stored Outbox row back into a genuinely usable,
    correctly-typed DomainEvent instance — see module docstring for
    why this needs real type coercion, not a blind
    EventClass(**payload) splat.

    organization_id and occurred_at come directly from Outbox's own
    typed columns (a real FK id and a real DateTimeField respectively)
    — never JSON-encoded, so they're already correctly typed and need
    no coercion. Only outbox_row.payload (the JSONField) round-tripped
    through JSON and needs it.
    """
    event_cls = event_class_for(outbox_row.event_type)
    hints = get_type_hints(event_cls)

    payload = {
        key: _coerce(hints.get(key), value)
        for key, value in outbox_row.payload.items()
    }

    return event_cls(
        organization_id=outbox_row.organization_id,
        event_id=outbox_row.event_id,
        occurred_at=outbox_row.occurred_at,
        **payload,
    )
