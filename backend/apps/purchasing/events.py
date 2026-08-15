# =============================================================================
# === backend/apps/purchasing/events.py ===
# =============================================================================
"""
Arthasee — Purchasing Domain Events (Sprint 3, Stage 2)
"""
import uuid
from dataclasses import dataclass, field
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