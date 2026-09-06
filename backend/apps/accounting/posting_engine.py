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

2 Sep 2026 — every memo string that used to embed a raw ID
(event.payment_id, event.quick_purchase_id, etc.) now embeds the
real, frozen display name each event carries as of that date's memo
fix (customer_name/supplier_name/account_name — see each event
class's own docstring in payments/events.py and purchasing/events.py
for where each one comes from). This memo IS what JournalEntry.memo
stores, which is what both the Jurnal audit page AND the Kas Harian
dashboard display — a real UX gap, not cosmetic: an owner-facing memo
built from a UUID was never actually readable by an owner.
InternalCashMutationRecorded needed no change — its own memo already
carried no ID, and Kas Harian builds its title separately anyway
(see that event's own docstring).
"""
from decimal import Decimal

from apps.inventory.events import PartConsumed, StockOpnameCompleted
from apps.invoicing.events import InvoiceIssued
from apps.payments.events import (InternalCashMutationRecorded,
                                  OperatingExpenseRecorded, PaymentReceived,
                                  SupplierPaymentMade)
from apps.purchasing.events import (GoodsReceived, PurchaseReturned,
                                    QuickPurchaseRecorded,
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
    Drops any entry whose amount is exactly zero — a real,
    legitimate "nothing to post for this line" case, same
    "$0 -> post nothing" precedent as WorkOrderCompleted's own
    labor-only jobs.

    6 Sep 2026 — real, defensive fix, found via a design-review
    trace (Sansan's own "negative transaction" question), not a live
    incident: this used to filter zero AND negative amounts
    identically (`amount > 0`), meaning a negative amount would be
    silently DROPPED rather than rejected — a negative Invoice could
    have produced a partial or empty journal entry while the
    operational record itself still showed a negative total. Every
    real posting rule in this file was checked directly: none of
    them ever intentionally produces a negative amount — every real
    "reversal" concept here works by swapping which account is
    debited vs credited, never by passing a negative number through.
    A negative amount reaching this function is therefore always a
    genuine upstream bug (e.g. a negative Invoice that should have
    been rejected at creation, per this project's own confirmed
    policy: negative transactions belong in a dedicated Credit Note/
    Return flow, never the standard posting engine) — this now fails
    loudly instead of silently swallowing it, with zero change to
    the zero-or-positive behavior every existing caller already
    depends on.

    Sprint 7, Task 7.3 also leans on the zero-filtering half of this
    directly for StockOpnameCompleted's own single-entry, up-to-4-line
    shape — a shortage-only session naturally collapses to 2 lines, a
    surplus-only session to the other 2, a session with both to all
    4 — unaffected by this change, since every value passed there is
    already `abs(...)`, always >= 0.
    """
    result = []
    for entry in entries:
        if entry["amount"] < Decimal("0"):
            raise ValueError(
                f"Refusing to post a negative amount ({entry['amount']}) for "
                f"account {entry['account_code']} — negative transactions must "
                f"go through a dedicated Credit Note/Return flow, never the "
                f"standard posting engine. This indicates an upstream "
                f"validation gap, not a legitimate zero-value line."
            )
        if entry["amount"] > Decimal("0"):
            result.append(entry)
    return result


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
            # 2 Sep 2026 — real name, not event.payment_id. See
            # module docstring.
            "memo": f"Payment received — {event.customer_name}",
            "lines": _lines(
                {"account_code": cash_or_bank_account_code(event.method), "side": "debit",  "amount": event.amount},
                {"account_code": "1201",                                   "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, OperatingExpenseRecorded):
        # 27 Aug 2026 — Made's own confirmed real request: a guided
        # alternative to the generic Manual Adjusting Journal for a
        # recurring operating cost (salary, rent, utilities). The
        # debit account is DYNAMIC, chosen by Made per entry — unlike
        # every other rule in this file, which posts to one fixed
        # account. account_code is frozen into the event's own
        # payload at creation time (same "frozen event payload"
        # discipline PurchaseReturned's own debit_account_code
        # already established), never re-derived here.
        return {
            # 2 Sep 2026 — real name, not event.operating_expense_id.
            "memo": f"Operating expense — {event.account_name}",
            "lines": _lines(
                {"account_code": event.account_code,                             "side": "debit",  "amount": event.amount},
                {"account_code": cash_or_bank_account_code(event.method), "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, InternalCashMutationRecorded):
        # 1 Sep 2026 — Made's own confirmed real request: a real
        # internal cash movement (till -> bank, or bank -> till), a
        # pure asset swap with ZERO income-statement impact. Both
        # account codes come straight from the event's own frozen
        # payload — from_account_code/to_account_code were already
        # validated as real Cash/Bank codes inside
        # InternalCashMutation.record() before this event was ever
        # published, so no re-validation happens here, same
        # discipline every other event in this file follows.
        return {
            "memo": f"Internal cash mutation — {event.internal_cash_mutation_id}",
            "lines": _lines(
                {"account_code": event.to_account_code,   "side": "debit",  "amount": event.amount},
                {"account_code": event.from_account_code, "side": "credit", "amount": event.amount},
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

    if isinstance(event, QuickPurchaseRecorded):
        # Made's own confirmed exception, 25 Aug 2026 — a real,
        # immediate spot purchase, paid on the spot: Dr Inventory
        # (1301) same as GoodsReceived, but credits Cash/Bank
        # directly rather than Accrued Inventory (2010) — there is
        # no "unbilled" gap to track here, since nothing about this
        # purchase is ever on credit. Same cash_or_bank_account_code()
        # helper PaymentReceived/SupplierPaymentMade already use, not
        # a second copy of that mapping.
        return {
            # 2 Sep 2026 — real name, not event.quick_purchase_id.
            "memo": f"Quick purchase — {event.supplier_name}",
            "lines": _lines(
                {"account_code": "1301",                                          "side": "debit",  "amount": event.amount},
                {"account_code": cash_or_bank_account_code(event.payment_method), "side": "credit", "amount": event.amount},
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
            # 2 Sep 2026 — real name, not event.supplier_payment_id.
            "memo": f"Supplier payment made — {event.supplier_name}",
            "lines": _lines(
                {"account_code": "2001",                                   "side": "debit",  "amount": event.amount},
                {"account_code": cash_or_bank_account_code(event.method),  "side": "credit", "amount": event.amount},
            ),
        }

    if isinstance(event, StockOpnameCompleted):
        # ONE JournalEntry, up to 4 lines — Chris and Made's own
        # confirmed call (Sprint 7, Task 7.3), not one entry per
        # counted part and not two separate entries for shortage vs
        # surplus. _lines() drops whichever pair is zero: a
        # shortage-only session collapses to 2 lines, a surplus-only
        # session to the other 2, a session with both to all 4 — the
        # existing filter does this for free, no special-casing
        # needed here beyond listing all 4 candidate lines.
        return {
            "memo": f"Stock opname completed — session {event.stock_opname_session_id}",
            "lines": _lines(
                {"account_code": "5004", "side": "debit",  "amount": event.shortage_amount},
                {"account_code": "1301", "side": "credit", "amount": event.shortage_amount},
                {"account_code": "1301", "side": "debit",  "amount": event.surplus_amount},
                {"account_code": "4004", "side": "credit", "amount": event.surplus_amount},
            ),
        }

    raise NotImplementedError(
        f"No posting rule defined for event type {type(event).__name__} "
        f"({event.event_type})."
    )
