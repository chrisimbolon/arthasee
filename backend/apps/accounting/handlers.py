# =============================================================================
# === backend/apps/accounting/handlers.py ===
# =============================================================================
"""
Arthasee — Accounting Event Handlers

Two handlers, two bounded concerns — matching EventHandler's own
"one handler = one bounded concern" framing:

  - AccountingEventHandler posts NEW economic facts (PartConsumed,
    WorkOrderCompleted, InvoiceIssued, PaymentReceived, and — Sprint
    3 — GoodsReceived, SupplierInvoiceReceived, SupplierPaymentMade)
    via posting_engine.py/journal_generator.py.
  - CancellationEventHandler reverses PREVIOUSLY posted facts
    (InvoiceCancelled, InvoiceRefunded) via cancellations.py — routed
    by event_type, since the two reversal shapes are genuinely
    different (see cancellations.py's own module docstring).

No purchasing-domain reversal events exist yet — "un-receive goods"
or "cancel a supplier invoice" were never scoped for Sprint 3; add
them to CancellationEventHandler if that's ever needed later, same
as InvoiceCancelled/InvoiceRefunded were added when Task 2.3 needed
them.
"""
from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent

from . import cancellations, journal_generator


class AccountingEventHandler(EventHandler):
    handles = (
        "PartConsumed", "WorkOrderCompleted", "InvoiceIssued", "PaymentReceived",
        "GoodsReceived", "SupplierInvoiceReceived", "SupplierPaymentMade",
    )

    def handle(self, event: DomainEvent) -> None:
        journal_generator.post_for_event(event)


class CancellationEventHandler(EventHandler):
    handles = ("InvoiceCancelled", "InvoiceRefunded")

    def handle(self, event: DomainEvent) -> None:
        if event.event_type == "InvoiceCancelled":
            cancellations.reverse_for_event(event)
        elif event.event_type == "InvoiceRefunded":
            cancellations.reverse_for_refund_event(event)
