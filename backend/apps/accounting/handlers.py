# =============================================================================
# === backend/apps/accounting/handlers.py ===
# =============================================================================
"""
Arthasee — Accounting Event Handlers

Two handlers, two bounded concerns — matching EventHandler's own
"one handler = one bounded concern" framing:

  - AccountingEventHandler posts NEW economic facts (PartConsumed,
    WorkOrderCompleted, InvoiceIssued, PaymentReceived) via
    posting_engine.py/journal_generator.py.
  - CancellationEventHandler reverses PREVIOUSLY posted facts
    (InvoiceCancelled, and InvoiceRefunded once Task 2.3 Half B
    lands) via cancellations.py.

Deliberately not one handler branching internally — "post a new
fact" and "reverse an old one" are different enough operations
(different files, different DB-query shapes) that keeping them as
separate handler classes keeps each one simple and single-purpose,
even though both end up subscribed to the same bus.
"""
from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent

from . import cancellations, journal_generator


class AccountingEventHandler(EventHandler):
    handles = ("PartConsumed", "WorkOrderCompleted", "InvoiceIssued", "PaymentReceived")

    def handle(self, event: DomainEvent) -> None:
        journal_generator.post_for_event(event)


class CancellationEventHandler(EventHandler):
    handles = ("InvoiceCancelled",)  # InvoiceRefunded added when Task 2.3 Half B lands

    def handle(self, event: DomainEvent) -> None:
        cancellations.reverse_for_event(event)
