# =============================================================================
# === backend/apps/workorders/reports.py ===
# =============================================================================
"""
Arthasee — Work Orders Reporting

29 Aug 2026 — Made's own confirmed real request, 27 Aug meeting
notes: a real monthly labor-revenue target per mechanic, tracked
against actual performance. New file, matching this codebase's own
established per-domain reports.py convention (apps.accounting,
apps.purchasing, apps.inventory each already own their own) — this
report is built purely from apps.workorders' and apps.invoicing's
own data, not a new accounting concept, so it belongs here, not in
apps.accounting.

Real, live computation — never stored, same "computed on read from
the real source of truth" discipline as every property on Invoice
(subtotal, total_paid, balance_due). A cached monthly total would go
stale the moment a late payment, a corrected invoice, or a newly
closed WorkOrder changed the real numbers underneath it.
"""
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, F, Sum
from django.db.models.functions import Coalesce


def mechanic_monthly_progress(organization, *, year=None, month=None):
    """
    For every ACTIVE mechanic, real labor-only revenue (kind="labor"
    InvoiceLineItem subtotals — Chris's own confirmed calculation
    basis, mapping to Account 4001 Service Revenue, never 4002 Parts
    Revenue) from every genuinely DONE WorkOrder assigned to them,
    whose ServiceRecord.service_date falls in the given calendar
    month — against that mechanic's own real monthly_target.

    Defaults to the current real calendar month when year/month
    aren't given — the natural default for "how is this month going
    so far," not a historical lookup.

    service_date, not WorkOrder.updated_at or Invoice.created_at, is
    the real filter basis — the same canonical "when did this
    business event actually happen" date every other report in this
    codebase already treats as authoritative (P&L, Trial Balance,
    etc.), not a technical timestamp that could lag behind by days
    if invoicing happens after the job itself closes.

    A WorkOrder that's genuinely done but not yet invoiced
    contributes 0 to its mechanic's tally — a real, honest state
    (the revenue hasn't actually been recognized yet), not a guess
    at what an eventual invoice might say.

    Traverses invoice__service_record__work_order__... — a valid
    reverse-OneToOneField chain (WorkOrder.service_record has
    related_name="work_order"), not a forward FK — confirmed against
    the real, current model definitions before writing this query,
    not assumed.
    """
    from apps.invoicing.models import InvoiceLineItem
    from apps.workorders.models import Mechanic

    today = date.today()
    year = year or today.year
    month = month or today.month

    mechanics = Mechanic.objects.filter(organization=organization, is_active=True).order_by("name")

    rows = []
    for mechanic in mechanics:
        labor_total = InvoiceLineItem.objects.filter(
            invoice__service_record__work_order__organization=organization,
            invoice__service_record__work_order__assigned_to=mechanic,
            invoice__service_record__work_order__status="DONE",
            invoice__service_record__service_date__year=year,
            invoice__service_record__service_date__month=month,
            kind="labor",
        ).aggregate(
            total=Coalesce(
                Sum(F("quantity") * F("unit_price")),
                Decimal("0"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]

        target = mechanic.monthly_target
        # Real, honest guard — a mechanic with monthly_target=0
        # (should never happen given the model's own default, but a
        # future manual edit could set it) gets a real 0% rather than
        # a ZeroDivisionError crashing the whole report for every
        # other mechanic too.
        percent_of_target = (
            (labor_total / target * Decimal("100")) if target > Decimal("0") else Decimal("0")
        )

        rows.append({
            "mechanic_id": mechanic.id,
            "mechanic_name": mechanic.name,
            "monthly_target": target,
            "labor_revenue": labor_total,
            "percent_of_target": percent_of_target,
        })

    return {"year": year, "month": month, "mechanics": rows}
