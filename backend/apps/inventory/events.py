# =============================================================================
# === backend/apps/inventory/events.py ===
# =============================================================================
"""
Arthasee — Inventory Domain Events

Owned by apps.inventory per Roadmap v2.2 / Sprint Plan v1.1 (Task
2.1) — but PUBLISHED from apps.workorders.models.WorkOrderMaterialLine
.save(), not from anywhere inside this app. That's deliberate, not a
layering violation: WorkOrderMaterialLine is the SOLE executor of
real-time stock deduction for the whole system today (see that
model's own module docstring in apps/workorders/models.py).
apps.inventory.models.PartUsage.save() contains an equivalent
F()-based deduction, but WorkOrder.close() always creates PartUsage
rows via bulk_create() specifically to SKIP that side effect — the
deduction already happened via WorkOrderMaterialLine, so PartUsage at
close time is a frozen historical snapshot, not a second real event.

A domain event describes what actually happened in the business, not
which app's code happened to trigger it — inventory still owns the
shape and meaning of "a part was consumed," even though workorders is
the one place that fact currently originates from.

⚠️ Flagged, not silently assumed: if apps.inventory.models.PartUsage
is ever created directly, OUTSIDE WorkOrder.close()'s bulk_create()
path, that code path also deducts real stock via its own F()
expression in PartUsage.save() — and would need its OWN publish()
call for PartConsumed, or that stock movement would silently never
reach the ledger. Not wired here because no live API endpoint
creating PartUsage directly has been confirmed to exist in
production — only direct-ORM test setup in apps.invoicing.tests.
Needs a direct answer before Sprint 2 is considered complete.

--- Sprint 7, Task 7.3: StockOpnameCompleted (added here) ---
UNLIKE PartConsumed above, this event IS published from directly
inside this app — StockOpnameSession.complete(), in this same app's
models.py — since a Stock Opname session's whole lifecycle (start,
record counts, complete) genuinely lives in apps.inventory, not
borrowed from another app's trigger point the way PartConsumed is.
"""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.events.interfaces import DomainEvent


@dataclass(frozen=True)
class PartConsumed(DomainEvent):
    """
    Fired the moment a part's stock is actually, physically deducted
    — WorkOrderMaterialLine.save() today (see this module's own
    docstring for why, and for the one unconfirmed gap).

    Posting rule (Roadmap v2.2): Dr WIP (1302) / Cr Inventory (1301),
    both for `amount`.

    material_line_id is included alongside the envelope's own
    event_id specifically for audit-trail readability — a future
    Audit Log Viewer (Phase 4) can show "this journal entry came from
    material line X on work order Y" without needing to cross-
    reference Outbox.payload by hand. event_id alone is already
    sufficient for the accounting handler's own idempotency; this is
    a human-readability addition, not a second identity mechanism.
    """
    part_id: uuid.UUID
    work_order_id: uuid.UUID
    material_line_id: uuid.UUID
    quantity: Decimal
    unit_price_at_time: Decimal
    amount: Decimal
    event_type: str = field(init=False, default="PartConsumed", kw_only=True)


@dataclass(frozen=True)
class StockOpnameCompleted(DomainEvent):
    """
    Fired once per completed StockOpnameSession — a real physical
    count reconciliation, not a per-part event. Sprint 7, Task 7.3.
    Chris and Made's own confirmed call: ONE session, ONE netted
    posting — never one journal entry per counted part.

    shortage_amount / surplus_amount are Rupiah totals, already
    netted across every counted part in this session and frozen at
    completion time inside StockOpnameSession.complete()'s own
    transaction (Roadmap Principle #9) — valued at Part.unit_price,
    the same basis apps.inventory.reports.stock_summary() already
    uses for every other Inventory-adjacent figure in this system
    (see Roadmap Open Decision #5 for the known, accepted gap against
    the ledger's true cost basis — deliberately not a new, third
    valuation basis introduced just for this event).

    Posting rule (Roadmap v2.5): a SINGLE JournalEntry, up to 4 lines
    — Dr Inventory Shrinkage (5004) / Cr Inventory (1301) for
    shortage_amount, Dr Inventory (1301) / Cr Inventory Opname
    Surplus (4004) for surplus_amount. posting_engine.py's own
    _lines() helper drops whichever pair is zero — a shortage-only
    session naturally collapses to 2 lines, a surplus-only session to
    the other 2, a session with both to all 4.

    This event is deliberately never published if BOTH totals are
    zero (every counted part matched exactly) — see
    StockOpnameSession.complete()'s own guard. A zero-variance
    session is a real, valid outcome, not a gap.
    """
    stock_opname_session_id: uuid.UUID
    shortage_amount: Decimal
    surplus_amount: Decimal
    line_item_count: int
    event_type: str = field(init=False, default="StockOpnameCompleted", kw_only=True)
