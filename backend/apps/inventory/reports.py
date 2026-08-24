# =============================================================================
# === backend/apps/inventory/reports.py ===
# =============================================================================
"""
Arthasee — Inventory Reports

Real aggregation logic, separate from apps.inventory.views — same
separation already proven by apps.accounting.reports and
apps.analytics.growth: views stay thin, the actual queries live here
where they can be tested directly.

--- 24 Aug 2026: NILAI STOK valuation basis fixed to cost_price ---
Real ledger-consistency fix, same incident as
apps.workorders.models.WorkOrderMaterialLine.save() and
apps.purchasing.models.GoodsReceivedNoteLineItem.save() — see either
file's own docstring for the full story. total_stock_value now uses
Part.cost_price (real GRN "Last Cost"), not Part.unit_price (selling
price) — the SAME basis Account 1301 now actually posts at on BOTH
sides (GoodsReceived debits at cost, PartConsumed now credits at
cost too, after the WorkOrderMaterialLine fix).

The disclaimer stays, deliberately reworded rather than removed
outright — same "honest caveat over overclaiming" discipline this
project already uses (gross_profit_note, projected_months_used).
Perfect 1:1 reconciliation with 1301 still isn't guaranteed for every
single part: a brand-new part with cost_price still at 0 (no real
GRN received yet) falls back to unit_price via the SAME soft-fallback
rule WorkOrderMaterialLine itself uses — so for that one part, this
KPI and the ledger could still diverge until its first real GRN
lands. Stating that plainly is more honest than declaring perfect
reconciliation this KPI can't actually promise for every part, every
time.
"""
from decimal import Decimal

from django.db.models import F, Sum

from .models import Part, PartUsage, StockAdjustment


def stock_summary(organization):
    """
    Real counts and a real total stock value — for one organization.

    total_stock_value uses Part.cost_price (real GRN "Last Cost"
    basis) — the same basis Account 1301 now posts at on both sides,
    after the 24 Aug 2026 ledger-consistency fix (see module
    docstring). A part with no real GRN history yet (cost_price still
    0) falls back to unit_price for this aggregate, same soft-
    fallback rule WorkOrderMaterialLine itself uses — see
    total_stock_value_basis's own honest caveat about this below.

    low_stock_count and out_of_stock_count are deliberately mutually
    exclusive (low_stock_count excludes anything already at or below
    zero) — a part that's completely out shouldn't double-count in
    both buckets of a summary meant to read cleanly at a glance.

    total_parts and total_stock_value deliberately count EVERY part,
    HARIAN included — those are honest catalog/value totals, not
    reorder signals, so there's nothing to exclude.

    out_of_stock_count and low_stock_count, by contrast, are real
    reorder signals — Sprint 7, Task 7.1's own guard, applied here to
    match PartListView's ?low_stock=true filter exactly. A HARIAN
    part (e.g. an expensive, on-demand sensor deliberately kept at
    zero stock) must never surface as "needs reordering" in EITHER
    place — this was a real, found gap: PartListView already had the
    HARIAN exclusion, but this independent aggregate query did not,
    which would have left the dashboard's own "Stok Habis" card
    disagreeing with the parts list about the exact same part.
    """
    parts = Part.objects.filter(organization=organization)
    reorder_relevant = parts.exclude(reorder_cadence=Part.ReorderCadence.HARIAN)

    # Real per-row fallback (cost_price if set, else unit_price) via
    # a conditional expression — can't do this with a plain Sum(F()*F())
    # the way the old unit_price-only version could, since the basis
    # genuinely varies per row now. Small enough part count for this
    # shop that a plain Python sum over the queryset is simpler and
    # just as fast as building a Case/When expression for it.
    total_value = sum(
        (p.current_stock * (p.cost_price or p.unit_price) for p in parts),
        Decimal("0"),
    )

    return {
        "total_parts": parts.count(),
        "total_stock_value": total_value,
        "total_stock_value_basis": (
            "Dihitung dari Harga Beli (HPP) per part — basis yang sama dengan akun "
            "Inventory (1301) di neraca saldo. Part yang belum pernah menerima GRN "
            "masih menggunakan harga jual sementara sampai GRN pertamanya tercatat."
        ),
        "out_of_stock_count": reorder_relevant.filter(current_stock__lte=0).count(),
        "low_stock_count": reorder_relevant.filter(
            minimum_stock__gt=0, current_stock__gt=0, current_stock__lte=F("minimum_stock"),
        ).count(),
    }


def movement_history(part):
    """
    Real chronological merge of PartUsage (always consumption) and
    StockAdjustment (either direction) for one Part — "what happened
    to this part's stock over time," not a reconstructed running
    balance. Deliberately does NOT compute a per-row balance-after
    figure by walking backward from current_stock — that would be a
    real, avoidable source of off-by-one bugs for a feature that's
    genuinely more useful as an honest "here's what happened" than a
    reconstructed ledger.
    """
    usages = PartUsage.objects.filter(part=part).select_related("service_record")
    adjustments = StockAdjustment.objects.filter(part=part).select_related("created_by")

    rows = []
    for u in usages:
        rows.append({
            "type": "usage",
            "date": u.created_at,
            "quantity_change": -u.quantity,
            "reason": "Dipakai pada servis",
            "service_record_id": str(u.service_record_id),
            "notes": "",
        })
    for a in adjustments:
        rows.append({
            "type": "adjustment",
            "date": a.created_at,
            "quantity_change": a.quantity_change,
            "reason": a.get_reason_display(),
            "service_record_id": None,
            "notes": a.notes,
            "created_by_name": a.created_by.full_name if a.created_by else None,
        })

    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows
