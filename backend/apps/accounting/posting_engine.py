# =============================================================================
# === backend/apps/accounting/posting_engine.py ===
# =============================================================================
"""
Arthasee — Posting Engine

Pure mapping from a DomainEvent to WHICH accounts it touches and how
much — deliberately account-CODE-based (plain strings), not real
Account model instances, and deliberately free of any Account/
Organization ORM queries. Keeps "what does this event mean,
accounting-wise" fully testable in isolation, independent of any
specific organization's actual seeded Chart of Accounts.
journal_generator.py is what turns these codes into real Account rows
for a specific organization and actually posts them.

Module-level imports of the event classes are deliberate here, not
hidden behind local imports the way cross-app FK declarations are
elsewhere in this codebase — this file's entire job IS mapping these
specific types to posting rules; the dependency is the point, not an
incidental reach into another domain.
"""
from decimal import Decimal

from apps.inventory.events import PartConsumed
from apps.invoicing.events import InvoiceIssued
from apps.payments.events import PaymentReceived, SupplierPaymentMade
from apps.purchasing.events import (GoodsReceived, PurchaseReturned,
                                    SupplierInvoiceReceived)
from apps.workorders.events import WorkOrderCompleted


def cash_or_bank_account_code(method: str) -> str:
    """
    Which account a given payment method maps to — shared between
    PaymentReceived's own posting rule, SupplierPaymentMade's own
    posting rule (below), AND
    apps.accounting.cancellations.reverse_for_refund_event()'s refund
    reversal (Task 2.3, Half B). One real definition, not multiple
    copies that could quietly drift apart if the mapping ever gets
    more nuanced (a dedicated QRIS account, say).
    """
    return "1001" if method == "cash" else "1101"


def _lines(*entries):
    """
    Drops any entry whose amount is exactly zero. Real requirement,
    not a cosmetic filter — JournalLine's own DB constraint
    (journalline_exactly_one_side) requires exactly one side to be
    POSITIVE, not merely set; a $0 credit line satisfies neither
    branch of that constraint and would raise IntegrityError if
    passed through to JournalEntry.post() as-is.
    """
    return [e for e in entries if e["amount"] > Decimal("0")]


def resolve(event) -> dict:
    """
    Returns {"memo": str, "lines": [{"account_code": ..., "side":
    "debit"|"credit", "amount": Decimal}, ...]}. "lines" may be an
    empty list — e.g. a labor-only WorkOrderCompleted with amount=0 —
    callers (journal_generator.post_for_event) must treat an empty
    list as "nothing to post," not an error.

    Raises NotImplementedError for any event type with no rule wired
    yet — deliberately loud rather than a silent no-op, so a future
    new domain event without a posting rule fails obviously instead
    of vanishing into Outbox with nothing downstream ever noticing.
    """
    if isinstance(event, PartConsumed):
        return {
            "memo": f"Part consumed — material line {event.material_line_id}",
            "lines": _lines(
                {"account_code": "1302", "side": "debit",  "amount": event.amount},
                {"account_code": "1301", "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, WorkOrderCompleted):
        return {
            "memo": f"Work order completed — {event.work_order_id}",
            "lines": _lines(
                {"account_code": "5001", "side": "debit",  "amount": event.amount},
                {"account_code": "1302", "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, InvoiceIssued):
        return {
            "memo": f"Invoice issued — {event.invoice_id}",
            "lines": _lines(
                {"account_code": "1201", "side": "debit",  "amount": event.total},
                {"account_code": "4001", "side": "credit", "amount": event.service_amount},
                {"account_code": "4002", "side": "credit", "amount": event.parts_amount},
            ),
        }

    if isinstance(event, PaymentReceived):
        return {
            "memo": f"Payment received — {event.payment_id}",
            "lines": _lines(
                {"account_code": cash_or_bank_account_code(event.method), "side": "debit",  "amount": event.amount},
                {"account_code": "1201",                                   "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, GoodsReceived):
        return {
            "memo": f"Goods received — GRN {event.goods_received_note_id}",
            "lines": _lines(
                {"account_code": "1301", "side": "debit",  "amount": event.amount},
                {"account_code": "2010", "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, PurchaseReturned):
        # debit_account_code was determined and frozen ONCE, inside
        # PurchaseReturn.create_return()'s own transaction — "2010"
        # for a return before any supplier invoice existed (Case A),
        # "2001" for a return after an unpaid invoice existed
        # (Case B). Deliberately NOT re-derived here from current
        # GRN/SupplierInvoice state — that state could theoretically
        # have moved on by the time this event is actually processed
        # (asynchronously, after commit). The credit side is always
        # Inventory (1301) in both cases — goods physically leaving
        # is goods physically leaving, regardless of billing status;
        # only the liability being reduced ever changes.
        return {
            "memo": f"Purchase return — {event.purchase_return_id}",
            "lines": _lines(
                {"account_code": event.debit_account_code, "side": "debit",  "amount": event.amount},
                {"account_code": "1301",                    "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, SupplierInvoiceReceived):
        return {
            "memo": f"Supplier invoice received — {event.supplier_invoice_id}",
            "lines": _lines(
                {"account_code": "2010", "side": "debit",  "amount": event.amount},
                {"account_code": "2001", "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, SupplierPaymentMade):
        return {
            "memo": f"Supplier payment made — {event.supplier_payment_id}",
            "lines": _lines(
                {"account_code": "2001",                                   "side": "debit",  "amount": event.amount},
                {"account_code": cash_or_bank_account_code(event.method),  "side": "credit", "amount": event.amount},
            ),
        }

    raise NotImplementedError(
        f"No posting rule defined for event type {type(event).__name__} "
        f"({event.event_type})."
    )
