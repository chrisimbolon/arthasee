# =============================================================================
# === backend/apps/purchasing/reports.py ===
# =============================================================================
"""
Arthasee — Purchasing Reports

Supplier Reliability lives here, not in apps.accounting.reports,
deliberately — it's built entirely from real Purchasing documents
(PurchaseOrder.expected_date, GoodsReceivedNote.received_at,
PurchaseReturn), never from a posted journal entry. Keeping it here
matches the same Domain Ownership principle already established
throughout this codebase: Purchasing owns its own documents;
Accounting only ever listens to events published FROM Purchasing,
never reaches directly into its models. A report built purely from
Purchasing's own data belongs in Purchasing's own reports module,
not Accounting's.

--- Real bug fixed: UTC-vs-local date extraction ---
Found via a genuinely flaky-looking test failure that turned out not
to be flaky at all — it reliably failed whenever run between roughly
00:00 and 07:00 WIB (Batam's own timezone, UTC+7). Root cause:
`g.received_at.date()` extracted the UTC calendar date directly from
an aware datetime, not the LOCAL one — at 03:05 WIB, UTC is still
20:05 the PREVIOUS day, silently rolling a real "today" delivery back
to "yesterday" for comparison purposes. Since expected_date/since/
as_of are all plain, timezone-naive dates entered by staff as real
LOCAL calendar dates (via a date picker, no timezone attached), the
correct comparison requires converting received_at to local time
FIRST via timezone.localtime() — not comparing a UTC date against a
local one. This is a real, live correctness bug in production, not
just a test artifact: any GRN genuinely received in that early-
morning window would have been misjudged the same way for a real
shop owner checking this report, not just inside a test.
"""
from decimal import Decimal

from django.utils import timezone

from .models import PurchaseOrder, PurchaseReturn, Supplier


def supplier_reliability(organization, *, since, as_of) -> dict:
    """
    Per-supplier delivery and return reliability. Two metrics, both
    built entirely from data that already exists. Deliberately
    scoped to EXCLUDE price-creep tracking (comparing a part's own
    unit_cost over time from the same supplier) — that's a genuinely
    different kind of analysis, a real cost-history comparison, not
    a simple aggregation like these two, and deserves its own
    dedicated design pass rather than being folded in here.

    On-time delivery is judged ONLY for POs that are BOTH fully
    received (a still-open PO hasn't finished happening yet — can't
    be scored) AND have a real expected_date set (no promised date
    means nothing to judge against). "Delivered on" is the LATEST
    GRN's own received_at among every GRN against that PO — the date
    everything ordered actually finished arriving, not the date of
    the first partial delivery — converted to LOCAL time before
    extracting the date, matching since/as_of/expected_date's own
    plain-local-date semantics (see module docstring for the real
    bug this fixes). Verified by hand against a mixed scenario (no-
    date PO, still-open PO, on-time PO, and a partial-then-late PO)
    before being written here — the partial case specifically
    confirms the LATEST delivery is what's judged, not the first.

    Return rate is total returned value against total received
    value, traced GRN -> PurchaseOrder -> Supplier. Division-by-zero
    guarded — a supplier with zero received value in the period
    returns 0%, not a crash. A cancelled PO can never have any real
    GRNs against it (PurchaseOrder.cancel() only ever allows
    cancelling DRAFT/ORDERED, zero real receipts) — so it correctly
    contributes nothing to either metric without needing any
    special-case handling here.

    Suppliers with zero real activity in the selected period are
    excluded entirely — same "don't clutter with nothing to show"
    discipline as apps.accounting.reports.aging_ar()/aging_ap() only
    listing invoices that are actually outstanding.
    """
    suppliers = Supplier.objects.filter(organization=organization, is_active=True)

    rows = []
    for supplier in suppliers:
        pos = PurchaseOrder.objects.filter(
            organization=organization, supplier=supplier,
            order_date__gte=since, order_date__lte=as_of,
        ).prefetch_related("goods_received_notes")

        total_pos_judged = 0
        on_time_pos = 0
        total_received_value = Decimal("0")

        for po in pos:
            grns = list(po.goods_received_notes.all())
            if grns:
                total_received_value += sum((g.total_cost for g in grns), Decimal("0"))

            if po.status != PurchaseOrder.Status.FULLY_RECEIVED or po.expected_date is None:
                continue  # can't judge an open PO, or one with no promised date

            # timezone.localtime() converts the aware UTC datetime to
            # the project's real configured local timezone BEFORE
            # extracting the calendar date — see module docstring for
            # the real bug this fixes. A naive `.date()` call here
            # would extract the UTC date instead, silently rolling a
            # real local "today" delivery back to "yesterday" for any
            # GRN received between roughly 00:00-07:00 WIB.
            last_delivery = max(timezone.localtime(g.received_at).date() for g in grns)
            total_pos_judged += 1
            if last_delivery <= po.expected_date:
                on_time_pos += 1

        if total_pos_judged == 0 and total_received_value == Decimal("0"):
            continue  # no real activity for this supplier in this period

        total_returned_value = Decimal("0")
        returns = PurchaseReturn.objects.filter(
            organization=organization, goods_received_note__purchase_order__supplier=supplier,
            return_date__date__gte=since, return_date__date__lte=as_of,
        )
        for ret in returns:
            total_returned_value += ret.total_value

        on_time_rate = None
        if total_pos_judged > 0:
            on_time_rate = (Decimal(on_time_pos) / Decimal(total_pos_judged)) * Decimal("100")

        return_rate = Decimal("0")
        if total_received_value != Decimal("0"):
            return_rate = (total_returned_value / total_received_value) * Decimal("100")

        rows.append({
            "supplier_id": str(supplier.id),
            "supplier_name": supplier.name,
            "total_pos_judged": total_pos_judged,
            "on_time_pos": on_time_pos,
            "on_time_rate": on_time_rate,
            "total_received_value": total_received_value,
            "total_returned_value": total_returned_value,
            "return_rate": return_rate,
        })

    # Worst on-time rate first — a supplier with nothing judged
    # (on_time_rate is None) sorts last, since there's nothing
    # actionable to flag about them yet. Ties broken by higher
    # return_rate first.
    rows.sort(key=lambda r: (
        r["on_time_rate"] is None,
        r["on_time_rate"] if r["on_time_rate"] is not None else Decimal("0"),
        -r["return_rate"],
    ))

    return {"since": since, "as_of": as_of, "suppliers": rows}
