# =============================================================================
# === backend/apps/purchasing/events.py ===
# =============================================================================
"""
Arthasee — Purchasing Domain Events (Sprint 3, Stage 2)
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.core.events.interfaces import DomainEvent


@dataclass(frozen=True)
class GoodsReceived(DomainEvent):
    """
    Fired once per GoodsReceivedNote — aggregated total across every
    line item, same shape as WorkOrderCompleted, not PartConsumed's
    per-line shape. See GoodsReceivedNote.receive()'s own docstring
    for why.

    Posting rule (Roadmap v2.2): Dr Inventory (1301) / Cr Accrued
    Inventory - Unbilled AP (2010), both for `amount` — the real
    GR/IR clearing pattern this whole procurement flow was built
    around.
    """
    goods_received_note_id: uuid.UUID
    supplier_id: uuid.UUID
    amount: Decimal
    line_item_count: int
    event_type: str = field(init=False, default="GoodsReceived", kw_only=True)


@dataclass(frozen=True)
class SupplierInvoiceReceived(DomainEvent):
    """
    Fired when a SupplierInvoice is recorded — see
    SupplierInvoice.record(). amount is the supplier's own stated
    total, NOT derived from any linked GoodsReceivedNotes — deliberate
    consequence of this app's "no 3-way matching" scope, not an
    oversight (see that method's own docstring). A mismatch between
    what was accrued and what the supplier actually billed shows up
    as a real, visible balance on Accrued Inventory (2010) — this
    event doesn't try to hide or auto-correct that.

    Posting rule: Dr Accrued Inventory - Unbilled AP (2010) / Cr
    Accounts Payable (2001), both for `amount` — clears the GRNI
    liability into a real payable owed to the supplier.
    """
    supplier_invoice_id: uuid.UUID
    supplier_id: uuid.UUID
    amount: Decimal
    event_type: str = field(init=False, default="SupplierInvoiceReceived", kw_only=True)

@dataclass(frozen=True)
class PurchaseReturned(DomainEvent):
    """
    Fired once per PurchaseReturn — aggregated total across every
    line item, same "one document, one accounting fact" shape as
    GoodsReceived, which this event is the deliberate mirror of.

    Now covers Case A AND Case B — see PurchaseReturn.create_return()'s
    own docstring for the real classification logic. In BOTH cases the
    credit side is always Inventory (1301), since goods physically
    leaving is goods physically leaving regardless of billing status
    — only the debit side changes depending on which liability is
    being reduced. debit_account_code is frozen at creation time
    inside create_return()'s own transaction — "2010" (Case A,
    reversing an un-invoiced receipt) or "2001" (Case B, reducing a
    real unpaid payable) — and posting_engine.py trusts this value
    directly rather than re-deriving it from current GRN/
    SupplierInvoice state, which could theoretically have moved on by
    the time this event is actually processed (asynchronously, after
    commit, via the real event bus).

    Case C (return after the supplier invoice has been PAID) still
    has no posting rule at all — deliberately deferred, blocked
    outright at the model layer before this event would ever fire.
    """
    purchase_return_id: uuid.UUID
    goods_received_note_id: uuid.UUID
    amount: Decimal
    line_item_count: int
    debit_account_code: str
    event_type: str = field(init=False, default="PurchaseReturned", kw_only=True)


@dataclass(frozen=True)
class QuickPurchaseRecorded(DomainEvent):
    """
    Made's own confirmed exception, 25 Aug meeting — a real,
    immediate, over-the-counter spot purchase for HARIAN/MINGGUAN
    parts, paid on the spot: no PurchaseOrder, no GoodsReceivedNote.
    His own words: "harga sekedar numpang lewat, tipe harian harus
    tetap terpotret dari inventory."

    payment_method is captured here, at creation time (see
    QuickPurchase.record()), not re-derived later — same "capture
    once, don't recompute from a shifting database" discipline
    PurchaseReturned's own debit_account_code already established,
    for the same reason: by the time this event is actually
    processed (asynchronously, after commit), live state could
    theoretically have moved on.

    Posting rule, Made's own confirmed COA mapping: Dr Inventory
    (1301) / Cr Cash (1001) or Bank (1101) depending on
    payment_method — via the SAME cash_or_bank_account_code() helper
    PaymentReceived/SupplierPaymentMade already use, not a second
    copy of that mapping. Never Accounts Payable (2001) — this is
    deliberately never a credit purchase; that's the entire point of
    the "paid on the spot" real-world event this describes.

    transaction_date, added 29 Aug 2026 — real bug found live, same
    class of bug as OperatingExpenseRecorded's own fix a day earlier:
    without this, journal_generator.post_for_event() fell back to
    occurred_at (when the event was PUBLISHED, i.e. "now"), silently
    ignoring purchased_at whenever it genuinely differed from today.
    Confirmed live: the QuickPurchase form itself had no date field
    at all, meaning EVERY real submission defaulted to "now" — and
    with August 2026 closed, this made the entire QuickPurchase
    feature non-functional for real use the moment the month closed.
    Frozen here, same discipline as payment_method above — the real
    business date, not re-derived from anything that could shift.

    supplier_name, added 2 Sep 2026 — real UX gap found on the Kas
    Harian dashboard: every memo across the whole posting matrix was
    built from a raw ID (event.quick_purchase_id), meaningless in a
    friendly, owner-facing view. Frozen from supplier.name at
    QuickPurchase.record() time, same discipline as
    payments.events.SupplierPaymentMade.supplier_name — no existing
    snapshot field on QuickPurchase for this (unlike Invoice's own
    customer_name_snapshot), so this is a live read at record() time,
    captured once, never re-derived later from a Supplier row that
    could itself be renamed after the fact.
    """
    quick_purchase_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str
    payment_method: str  # "cash" or "bank" — QuickPurchase.PaymentMethod's own real values
    amount: Decimal
    line_item_count: int
    transaction_date: date
    event_type: str = field(init=False, default="QuickPurchaseRecorded", kw_only=True)
