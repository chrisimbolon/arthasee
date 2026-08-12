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
    """
    parts = Part.objects.filter(organization=organization)

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
        "out_of_stock_count": parts.filter(current_stock__lte=0).count(),
        "low_stock_count": parts.filter(
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
