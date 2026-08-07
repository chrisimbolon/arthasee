# =============================================================================
# === backend/apps/core/events/interfaces.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Interfaces

Abstract contract every domain event must satisfy. Deliberately zero
Django ORM imports here — a DomainEvent is a plain, framework-agnostic
Python object the instant a business action happens (WorkOrder.close(),
Invoice.save(), etc. — Sprint 2 territory, defined in each domain
app's own events.py, never here — see Roadmap v2.2, Principle 2:
Infrastructure Isolation). The Outbox model (see outbox.py) is what
actually persists a durable record of one, and only after
EventBus.publish() decides it's worth keeping.
"""
from __future__ import annotations

import abc
import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone


@dataclass(frozen=True)
class DomainEvent(abc.ABC):
    """
    Base for every domain event (WorkOrderCompleted, PartConsumed,
    InvoiceIssued, PaymentReceived, ...).

    Frozen on purpose: an event is a fact about something that
    already happened. Nothing downstream — a handler, a retry, a
    future audit-log viewer — should ever be able to mutate one after
    the fact.

    organization_id is a plain UUID, not a live FK to Organization —
    events must stay serializable and framework-agnostic. This is
    also part of the tenant-isolation guarantee itself: every event
    MUST declare which tenant it belongs to at construction time, not
    have it inferred later by whatever happens to consume it.

    Concrete subclasses only need to declare their own payload fields
    plus a fixed `event_type` — event_id/occurred_at are supplied
    automatically, so a caller writes:

        PartConsumed(organization_id=org.id, part_id=part.id, quantity=qty)

    and never has to think about the envelope fields below.
    """
    organization_id: uuid.UUID
    event_id: uuid.UUID = field(default_factory=uuid.uuid4, kw_only=True)
    occurred_at: datetime = field(default_factory=timezone.now, kw_only=True)

    # Every concrete subclass must override this with a short, stable,
    # human-readable string ("WorkOrderCompleted", "PartConsumed") —
    # used as the EventBus routing key and stored verbatim on the
    # Outbox row and JournalEntry.event_type, so an audit-log viewer
    # can filter on it directly without knowing Python class names.
    event_type: str = field(init=False, default="", kw_only=True)

    def __post_init__(self):
        if type(self) is DomainEvent:
            raise TypeError(
                "DomainEvent is abstract and cannot be instantiated directly "
                "— subclass it in your domain app's own events.py."
            )
        if not self.event_type:
            raise NotImplementedError(
                f"{type(self).__name__} must override event_type with a "
                f"non-empty string."
            )

    def payload(self) -> dict:
        """
        Every field on the dataclass except the envelope fields above
        is considered payload — the domain-specific data a handler
        actually needs (part_id, quantity, invoice_id, amount, ...).
        Subclasses never need to override this.
        """
        envelope_keys = {"organization_id", "event_id", "occurred_at", "event_type"}
        return {
            k: v for k, v in dataclasses.asdict(self).items()
            if k not in envelope_keys
        }
