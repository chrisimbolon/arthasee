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

--- 2026-08-22: registry completed to cover every real event type ---
Originally shipped covering only the 4 event types that had actually
FAILED back on 2026-08-09 (PartConsumed, WorkOrderCompleted,
InvoiceIssued, PaymentReceived) — deliberately not guessed beyond
that without verifying each event class's real import path first.

A second, real production incident (2026-08-22, StockOpnameCompleted
failing on missing COA accounts 4004/5004) surfaced 4 MORE failed
event types this registry had never covered: GoodsReceived,
SupplierInvoiceReceived, SupplierPaymentMade, and StockOpnameCompleted
itself — replay_failed_events raised KeyError trying to reconstruct
them. Rather than guess at their import paths in the moment, they're
sourced from apps.accounting.posting_engine.py's own real, applied
module-level imports — the one place in this codebase that already
imports every single event type the whole system's posting engine
handles, verified rather than assumed. PurchaseReturned is included
too, for the same reason, even though it hasn't failed yet — this
registry's whole job is to never be caught short again the way it
was on both 08-09 and 08-22.

--- 1 Sep 2026: InternalCashMutationRecorded added ---
Same sourcing discipline as every entry below: confirmed against
apps.accounting.posting_engine.py's own real, applied import before
being added here, not guessed at — same as QuickPurchaseRecorded/
OperatingExpenseRecorded were on 28 Aug. Added proactively, before
this event has ever failed once, precisely because this registry's
whole job (per the 08-09/08-22 history above) is to never again be
the reason a real event type can't be replayed.
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

    Covers every event type apps.accounting.posting_engine.py itself
    handles — sourced directly from that file's own real, applied
    module-level imports, not guessed. Raises a clear, actionable
    error for anything not yet registered, rather than silently
    mis-mapping — extending this for a genuinely new event type is a
    one-line addition once that event class's real file is confirmed
    the same way every entry below was.
    """
    from apps.inventory.events import PartConsumed, StockOpnameCompleted
    from apps.invoicing.events import InvoiceIssued
    from apps.payments.events import (InternalCashMutationRecorded,
                                      OperatingExpenseRecorded,
                                      PaymentReceived, SupplierPaymentMade)
    from apps.purchasing.events import (GoodsReceived, PurchaseReturned,
                                        QuickPurchaseRecorded,
                                        SupplierInvoiceReceived)
    from apps.workorders.events import WorkOrderCompleted

    registry: dict[str, type[DomainEvent]] = {
        "PartConsumed": PartConsumed,
        "WorkOrderCompleted": WorkOrderCompleted,
        "InvoiceIssued": InvoiceIssued,
        "PaymentReceived": PaymentReceived,
        "GoodsReceived": GoodsReceived,
        "SupplierInvoiceReceived": SupplierInvoiceReceived,
        "SupplierPaymentMade": SupplierPaymentMade,
        "PurchaseReturned": PurchaseReturned,
        "StockOpnameCompleted": StockOpnameCompleted,
        # 28 Aug 2026 — real gap found live: both were real, already-
        # posting event types (confirmed via apps.accounting.
        # posting_engine.py's own real, applied imports — same
        # sourcing discipline this registry has used since 08-22),
        # just never added here, since neither had ever needed
        # replay before now. A live, first-time dispatch never
        # touches this registry at all (it already has the real
        # event object in memory) — only replay does, which is
        # exactly what surfaced this.
        "QuickPurchaseRecorded": QuickPurchaseRecorded,
        "OperatingExpenseRecorded": OperatingExpenseRecorded,
        # 1 Sep 2026 — added proactively this time, not in response
        # to a real failure (see module docstring).
        "InternalCashMutationRecorded": InternalCashMutationRecorded,
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
