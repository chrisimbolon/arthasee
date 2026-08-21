# =============================================================================
# === backend/apps/inventory/reports.py ===
# =============================================================================
"""
Arthasee — Inventory Reports

Real aggregation logic, separate from apps.inventory.views — same
separation already proven by apps.accounting.reports and
apps.analytics.growth: views stay thin, the actual queries live here
where they can be tested directly.
"""
from decimal import Decimal

from django.db.models import F, Sum

from .models import Part, PartUsage, StockAdjustment


def stock_summary(organization):
    """
    Real counts and a real total stock value — for one organization.

    total_stock_value uses Part.unit_price (retail/selling basis) —
    the only current, per-part price that actually exists on the
    model. This is a DIFFERENT basis than what genuinely posts to
    the ledger's own Inventory account (1301), which mixes unit_price
    via PartConsumed and unit_cost via GoodsReceived — see Roadmap
    v2.3, Open Decision #5. This figure must never be read as
    reconciling to the Trial Balance's own Inventory line; the
    response carries an explicit `total_stock_value_basis` string for
    exactly that reason, same discipline as the P&L's own
    gross_profit_note.

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

    total_value = parts.aggregate(
        total=Sum(F("current_stock") * F("unit_price"))
    )["total"] or Decimal("0")

    return {
        "total_parts": parts.count(),
        "total_stock_value": total_value,
        "total_stock_value_basis": (
            "Dihitung dari harga jual (unit_price) per part — bukan basis yang sama "
            "dengan saldo akun Inventory (1301) di neraca saldo."
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
