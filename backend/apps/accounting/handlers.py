# =============================================================================
# === backend/apps/accounting/handlers.py ===
# =============================================================================
"""
Arthasee — Accounting Event Handlers

Two handlers, two bounded concerns — matching EventHandler's own
"one handler = one bounded concern" framing:

  - AccountingEventHandler posts NEW economic facts (PartConsumed,
    WorkOrderCompleted, InvoiceIssued, PaymentReceived, and — Sprint
    3 — GoodsReceived, SupplierInvoiceReceived, SupplierPaymentMade,
    and — Retur Pembelian v1 — PurchaseReturned, and — Sprint 7,
    Task 7.3 — StockOpnameCompleted, and — 25 Aug 2026, Made's own
    confirmed HARIAN/MINGGUAN spot-purchase exception —
    QuickPurchaseRecorded, and — 27 Aug 2026 — OperatingExpenseRecorded,
    and — 1 Sep 2026, Made's own confirmed real internal cash-
    movement request — InternalCashMutationRecorded) via
    posting_engine.py/journal_generator.py.
  - CancellationEventHandler reverses PREVIOUSLY posted facts
    (InvoiceCancelled, InvoiceRefunded) via cancellations.py — routed
    by event_type, since the two reversal shapes are genuinely
    different (see cancellations.py's own module docstring).

PurchaseReturned is registered here, not in
CancellationEventHandler, even though it undoes GoodsReceived's own
posting at the account level — architecturally it's a genuinely NEW
posting rule living in posting_engine.py (same as GoodsReceived
itself), not a reversal-of-a-specific-prior-entry the way
InvoiceCancelled/InvoiceRefunded are. Same category, same handler.

StockOpnameCompleted is the same story — it's a NEW posting rule
(the netted result of a physical count), not a reversal of any prior
specific journal entry, even though its whole purpose is correcting
the books. Same category as GoodsReceived/PurchaseReturned, same
handler.

InternalCashMutationRecorded is the same story again — a genuinely
NEW posting rule (a pure asset swap between Cash and Bank), not a
reversal of anything. Same category, same handler.

No purchasing-domain CANCELLATION events exist yet — "un-receive
goods entirely" or "cancel a supplier invoice" were never scoped;
add them to CancellationEventHandler if that's ever needed later,
same as InvoiceCancelled/InvoiceRefunded were added when Task 2.3
needed them.
"""
from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent

from . import cancellations, journal_generator


class AccountingEventHandler(EventHandler):
    handles = (
        "PartConsumed", "WorkOrderCompleted", "InvoiceIssued", "PaymentReceived",
        "GoodsReceived", "SupplierInvoiceReceived", "SupplierPaymentMade",
        "PurchaseReturned", "StockOpnameCompleted", "QuickPurchaseRecorded",
        "OperatingExpenseRecorded", "InternalCashMutationRecorded",
        # 15 Oct 2026 -- real, live bug fix: TaxRemittanceRecorded
        # (9 Oct 2026, the PPh 23 + PPh Final UMKM patch) was wired
        # into events.py, posting_engine.py, and
        # apps/core/events/registry.py, but never added HERE -- the
        # fourth of the four real places a new event must be
        # registered (see this module's own docstring), and the one
        # EventRegistryCompletenessTests does not check. Confirmed
        # live: an event with zero subscribed handlers is marked
        # PROCESSED, not FAILED (apps/core/events/dispatcher.py's
        # own _dispatch_now()) -- so every real TaxRemittance
        # recorded before this fix silently posted NO journal entry,
        # with no FAILED Outbox row for replay_failed_events to ever
        # find. See TaxRemittanceTests.test_outbox_row_actually_posts_a_journal_entry
        # in apps/payments/tests.py for the regression guard.
        "TaxRemittanceRecorded",
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
