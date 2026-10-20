# =============================================================================
# === backend/apps/workorders/events.py ===
# =============================================================================
"""
Arthasee — Work Orders Domain Events

Owned and published from the same app — unlike PartConsumed
(apps.inventory.events, but published from here), WorkOrderCompleted
genuinely originates in this domain: the event describes WorkOrder.close()
itself freezing into a ServiceRecord, not a fact borrowed from
elsewhere.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.core.events.interfaces import DomainEvent


@dataclass(frozen=True)
class WorkOrderCompleted(DomainEvent):
    """
    Fired the moment a WorkOrder freezes into a ServiceRecord — see
    WorkOrder.close() for exactly where.

    Posting rule (Roadmap v2.2): Dr COGS Sparepart (5001) / Cr WIP
    (1302), both for `amount` — the total cost of every
    WorkOrderMaterialLine consumed on this job (quantity ×
    unit_price_at_time, summed across all of them).

    Deliberately published even when amount is zero (a labor-only
    job, no parts consumed at all) — Chris's own explicit call: the
    event itself is a real, useful audit-trail fact ("this job closed
    on this date") independent of whether there's a nonzero COGS line
    to post. The future accounting handler is what decides whether a
    zero-amount event still produces a journal entry —
    JournalEntry.post() itself already refuses to write anything with
    zero total value (see apps.accounting.models), so the handler
    will need its own explicit zero-amount skip; this event class
    doesn't pretend the zero case doesn't happen by hiding it.

    material_line_count is included for the same human-readability
    reason material_line_id is on PartConsumed — distinguishing "a
    real labor-only job, genuinely zero materials" from "something's
    wrong" when eyeballing a future Audit Log Viewer. Not required
    for idempotency (event_id already covers that).
    """
    work_order_id: uuid.UUID
    service_record_id: uuid.UUID
    amount: Decimal
    material_line_count: int
    event_type: str = field(init=False, default="WorkOrderCompleted", kw_only=True)


@dataclass(frozen=True)
class MaterialLineReversed(DomainEvent):
    """
    20 Oct 2026 (Phase 21, Task 21.2b) -- the exact mirror of
    PartConsumed. Fired when a WorkOrderMaterialLine's part goes back to
    stock while its WorkOrder is still open: the line is deleted
    (WorkOrderMaterialLineDetailView.delete()) or the whole WorkOrder is
    cancelled (WorkOrder.cancel()). Both go through
    WorkOrderMaterialLine.return_to_stock().

    Posting rule: Dr Inventory (1301) / Cr WIP (1302), both for
    `amount` -- the SAME quantity x unit_price_at_time (cost) the
    original PartConsumed posted, so the two cancel out exactly.

    Why it exists (finding F6, 16 Oct 2026): before this, both paths put
    the stock back with a StockAdjustment, which posts nothing. The
    original PartConsumed (Dr WIP / Cr Inventory) was never reversed, so
    every removed part left WIP overstated and Inventory understated.
    Read-only production audit, 19 Oct 2026: never triggered yet at any
    shop, so no data correction was needed -- code fix only.

    transaction_date: frozen at creation (Cheat Sheet section 4), the
    shop's local calendar day of the removal.
    reason: the StockAdjustment reason that went with it --
    "correction", "customer_cancelled_part" or "work_order_cancelled".
    """
    part_id: uuid.UUID
    work_order_id: uuid.UUID
    material_line_id: uuid.UUID
    quantity: Decimal
    unit_price_at_time: Decimal
    amount: Decimal
    reason: str
    transaction_date: date
    event_type: str = field(init=False, default="MaterialLineReversed", kw_only=True)
