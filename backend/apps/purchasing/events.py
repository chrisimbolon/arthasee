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

    Posting rule (v1, Case A only — see
    PurchaseReturn.create_return()'s own docstring for the full
    reasoning): Dr Accrued Inventory - Unbilled AP (2010) / Cr
    Inventory (1301), both for `amount` — the exact reverse of
    GoodsReceived's own posting, undoing a receipt that's being
    returned before any supplier invoice ever cleared Accrued
    Inventory into a real payable.
    """
    purchase_return_id: uuid.UUID
    goods_received_note_id: uuid.UUID
    amount: Decimal
    line_item_count: int
    event_type: str = field(init=False, default="PurchaseReturned", kw_only=True)