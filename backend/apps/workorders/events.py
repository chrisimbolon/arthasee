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
