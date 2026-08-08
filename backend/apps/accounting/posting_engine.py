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

Module-level imports of the four event classes are deliberate here,
not hidden behind local imports the way cross-app FK declarations are
elsewhere in this codebase — this file's entire job IS mapping these
four specific types to posting rules; the dependency is the point,
not an incidental reach into another domain.
"""
from decimal import Decimal

from apps.inventory.events import PartConsumed
from apps.invoicing.events import InvoiceIssued
from apps.payments.events import PaymentReceived
from apps.workorders.events import WorkOrderCompleted


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
        cash_or_bank = "1001" if event.method == "cash" else "1101"
        return {
            "memo": f"Payment received — {event.payment_id}",
            "lines": _lines(
                {"account_code": cash_or_bank, "side": "debit",  "amount": event.amount},
                {"account_code": "1201",       "side": "credit", "amount": event.amount},
            ),
        }

    raise NotImplementedError(
        f"No posting rule defined for event type {type(event).__name__} "
        f"({event.event_type})."
    )
