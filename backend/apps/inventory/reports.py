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

--- 26 Aug 2026: movement_history() now surfaces real per-purchase
price ---
Real gap found live: Chris intentionally bought the same part
(Kanvas Rem) at two different real prices (via two separate GRNs) to
test how Arthasee handles a price change over time — and Movement
History showed the real quantity trail but NO price trail at all,
even though the real per-purchase price was never actually lost.
Part.cost_price is a single, global "Last Cost" (Made's own confirmed
design — NOT tracked per-supplier, NOT a running average) — the only
way to see what was actually paid on any PARTICULAR past purchase is
to look at that purchase's own real, immutable unit_cost, which
already lives on GoodsReceivedNoteLineItem/QuickPurchaseLineItem and
always has.

StockAdjustment itself never stores unit_cost — only a plain notes
string referencing its source document (see either line-item model's
own save()). Rather than add a new FK/migration to fix this, this
enrichment reads that already-real data directly: for a
reason="restock" adjustment whose notes match the exact,
system-generated "GRN {number}" or "Quick Purchase {number}" format
those two models themselves always write, the matching line item's
own real unit_cost is looked up and attached. A manual restock (via
the plain "Sesuaikan Stok" UI, no GRN/QP origin at all) correctly
shows unit_cost=None — an honest "we don't know the price for this
one," matching reality, since that manual action never asks for a
price at all.
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

    Each restock row now also carries the real unit_cost it actually
    happened at, when that's knowable — see module docstring for the
    full 26 Aug 2026 reasoning. Import kept local to this function,
    not module-level — apps.purchasing already imports FROM
    apps.inventory (Part, StockAdjustment) in several places; keeping
    this reach the other direction scoped to just the one function
    that needs it avoids inviting a real circular-import question at
    module load time.
    """
    from apps.purchasing.models import (GoodsReceivedNoteLineItem,
                                        QuickPurchaseLineItem)

    usages = PartUsage.objects.filter(part=part).select_related("service_record")
    adjustments = StockAdjustment.objects.filter(part=part).select_related("created_by")

    # Keyed by the exact document number each restock's own notes
    # field already, always contains — both "GRN {number}" and
    # "Quick Purchase {number}" are fixed, system-generated formats
    # written by GoodsReceivedNoteLineItem.save() /
    # QuickPurchaseLineItem.save() themselves, never user-typed text,
    # so matching against them here is a safe, reliable lookup, not
    # fragile string-guessing at arbitrary input.
    grn_costs = {
        li.goods_received_note.number: li.unit_cost
        for li in GoodsReceivedNoteLineItem.objects.filter(part=part).select_related("goods_received_note")
    }
    quick_purchase_costs = {
        li.quick_purchase.number: li.unit_cost
        for li in QuickPurchaseLineItem.objects.filter(part=part).select_related("quick_purchase")
    }

    rows = []
    for u in usages:
        rows.append({
            "type": "usage",
            "date": u.created_at,
            "quantity_change": -u.quantity,
            "reason": "Dipakai pada servis",
            "service_record_id": str(u.service_record_id),
            "notes": "",
            "unit_cost": None,
        })
    for a in adjustments:
        unit_cost = None
        if a.reason == "restock":
            if a.notes.startswith("GRN "):
                unit_cost = grn_costs.get(a.notes[len("GRN "):])
            elif a.notes.startswith("Quick Purchase "):
                unit_cost = quick_purchase_costs.get(a.notes[len("Quick Purchase "):])
            # Anything else (a manual "Sesuaikan Stok" restock, no
            # GRN/QP origin) correctly leaves unit_cost as None — that
            # action never asks for a price, so there genuinely isn't
            # one to show, and pretending otherwise would be dishonest.
        rows.append({
            "type": "adjustment",
            "date": a.created_at,
            "quantity_change": a.quantity_change,
            "reason": a.get_reason_display(),
            "service_record_id": None,
            "notes": a.notes,
            "unit_cost": unit_cost,
            "created_by_name": a.created_by.full_name if a.created_by else None,
        })

    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows
