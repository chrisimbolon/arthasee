# =============================================================================
# === backend/apps/analytics/growth.py ===
# =============================================================================
"""
Arthasee — Growth & Operational Analytics

Real aggregation logic, separate from apps.analytics.views the same
way reports.py is separate from apps.accounting.views — views stay
thin, the actual queries live here where they can be tested directly.

Deliberately cross-domain — this is why it's its own app rather than
living inside apps.accounting or apps.workorders. It reads from both
(plus apps.service for customers), and neither of those domains
should own the other's data just to build a combined dashboard.

On "predictions": the one projection method used anywhere in this
module (_simple_projection) is a plain average of recent months,
extrapolated forward — NOT a statistical model, NOT machine learning.
Chosen deliberately: there isn't yet enough real historical data for
anything more sophisticated to be honestly validated against, and a
number a shop owner can verify by hand with a calculator is more
trustworthy than a black box claiming intelligence it doesn't have.
"""
from datetime import date
from decimal import Decimal

from apps.accounting.models import Account, JournalLine
from apps.service.models import Customer
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderStage
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth


def _last_n_month_starts(n, today=None):
    """
    The last `n` calendar months, oldest first, as plain `date`
    objects — the first of each month. Deliberately generated in
    Python, not derived from query results, so every month in range
    appears in the final trend even when it has zero real activity —
    a month silently missing from a trend looks like missing data,
    not a quiet one.
    """
    today = today or date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(n):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))


def _normalize_month_key(value):
    """
    TruncMonth on a DateField (JournalEntry.posting_date) returns a
    plain date. TruncMonth on a DateTimeField (WorkOrder.created_at,
    ServiceRecord.created_at, Customer.created_at) returns a
    timezone-aware datetime instead. Without normalizing both to
    plain dates, dict lookups against a date-keyed month list would
    silently mismatch — every bucket would read as empty, with
    nothing raising an error. date objects have no .date() method;
    datetime objects do — that's the real distinguishing check.
    """
    return value.date() if hasattr(value, "date") and callable(value.date) else value


def _simple_projection(trend, field, lookback=3):
    """
    Plain average of the last `lookback` months for `field`,
    extrapolated one month forward. See module docstring for why
    this is deliberately simple rather than a real forecasting model.
    """
    recent = trend[-lookback:] if len(trend) >= lookback else trend
    if not recent:
        return Decimal("0")
    total = sum((r[field] for r in recent), Decimal("0"))
    return total / len(recent)


def revenue_trend(organization, months=12):
    """
    Real monthly revenue/COGS/expense/net-income trend — one grouped
    query, not N separate report calls. Includes a `projected_next`
    figure for net_income using the simple average-based method above
    — clearly separated from the real historical months, never mixed
    into them.
    """
    month_list = _last_n_month_starts(months)
    since = month_list[0]

    rows = (
        JournalLine.objects
        .filter(
            organization=organization,
            journal_entry__posting_date__gte=since,
            account__account_type__in=[
                Account.AccountType.REVENUE, Account.AccountType.COGS, Account.AccountType.EXPENSE,
            ],
        )
        .annotate(month=TruncMonth("journal_entry__posting_date"))
        .values("month", "account__account_type")
        .annotate(debit=Sum("debit_amount"), credit=Sum("credit_amount"))
    )

    buckets = {m: {"revenue": Decimal("0"), "cogs": Decimal("0"), "expenses": Decimal("0")} for m in month_list}
    for row in rows:
        m = _normalize_month_key(row["month"])
        if m not in buckets:
            continue
        debit = row["debit"] or Decimal("0")
        credit = row["credit"] or Decimal("0")
        account_type = row["account__account_type"]
        if account_type == Account.AccountType.REVENUE:
            buckets[m]["revenue"] += credit - debit
        elif account_type == Account.AccountType.COGS:
            buckets[m]["cogs"] += debit - credit
        elif account_type == Account.AccountType.EXPENSE:
            buckets[m]["expenses"] += debit - credit

    trend = []
    for m in month_list:
        b = buckets[m]
        net_income = b["revenue"] - b["cogs"] - b["expenses"]
        trend.append({
            "month": m.isoformat()[:7],
            "revenue": b["revenue"], "cogs": b["cogs"],
            "expenses": b["expenses"], "net_income": net_income,
        })

    return {
        "months": trend,
        "projected_next_net_income": _simple_projection(trend, "net_income"),
    }


def mechanic_utilization(organization):
    """
    "How many mechanics are actually working right now" — Made's own
    real question, the exact gap he flagged in Sansan's mockup
    ("kenapa mechanic hanya 3 yg kerja? 3 dari 6"). Counts a mechanic
    as working through EITHER real path: directly assigned to a
    WorkOrder that's genuinely IN_PROGRESS (the common case, routine
    jobs), OR assigned to a currently-open WorkOrderStage (started,
    not yet completed) whose PARENT WorkOrder is also still
    IN_PROGRESS — deliberately not QC, since a WorkOrder in QC is
    being inspected, not actively worked (Made does QC personally on
    simple jobs, per WorkOrder.close()'s own real business rule).
    """
    total_active = Mechanic.objects.filter(organization=organization, is_active=True).count()

    from_workorder = WorkOrder.objects.filter(
        organization=organization, status="IN_PROGRESS", assigned_to__isnull=False,
    ).values_list("assigned_to_id", flat=True)

    from_stage = WorkOrderStage.objects.filter(
        organization=organization, assigned_to__isnull=False,
        started_at__isnull=False, completed_at__isnull=True,
        work_order__status="IN_PROGRESS",
    ).values_list("assigned_to_id", flat=True)

    working_ids = set(from_workorder) | set(from_stage)
    return {"mechanics_working": len(working_ids), "mechanics_total": total_active}


def work_order_queue_status(organization):
    """
    Real queue breakdown — Made's own literal questions: how many
    vehicles are waiting (never started), how many are actively being
    worked, how many have cleared out. CANCELLED excluded — it's
    neither a real queue position nor a completed job.
    """
    counts = dict(
        WorkOrder.objects.filter(organization=organization)
        .exclude(status="CANCELLED")
        .values_list("status")
        .annotate(count=Count("id"))
    )
    return {
        "open": counts.get("OPEN", 0),
        "in_progress": counts.get("IN_PROGRESS", 0),
        "qc": counts.get("QC", 0),
        "done": counts.get("DONE", 0),
    }


def job_volume_trend(organization, months=12):
    """
    Real monthly work-order volume — created vs completed shown
    separately, so a growing backlog (created rising, completed flat)
    is honestly visible, not hidden behind one combined number.

    "Completed" is measured from ServiceRecord.created_at, not
    WorkOrder.updated_at — updated_at changes on any field edit, not
    specifically on completion. ServiceRecord only ever gets created
    inside WorkOrder.close(), at the exact real moment a job finishes
    — a precise signal, not an approximation.
    """
    month_list = _last_n_month_starts(months)
    since = month_list[0]

    created_rows = {
        _normalize_month_key(m): c for m, c in
        WorkOrder.objects.filter(organization=organization, created_at__date__gte=since)
        .annotate(month=TruncMonth("created_at"))
        .values_list("month")
        .annotate(count=Count("id"))
    }
    completed_rows = {
        _normalize_month_key(m): c for m, c in
        WorkOrder.objects.filter(
            organization=organization, status="DONE", service_record__isnull=False,
            service_record__created_at__date__gte=since,
        )
        .annotate(month=TruncMonth("service_record__created_at"))
        .values_list("month")
        .annotate(count=Count("id"))
    }

    return [
        {"month": m.isoformat()[:7], "created": created_rows.get(m, 0), "completed": completed_rows.get(m, 0)}
        for m in month_list
    ]


def customer_growth_trend(organization, months=12):
    """New customers per month, straight off Customer.created_at."""
    month_list = _last_n_month_starts(months)
    since = month_list[0]

    rows = {
        _normalize_month_key(m): c for m, c in
        Customer.objects.filter(organization=organization, created_at__date__gte=since)
        .annotate(month=TruncMonth("created_at"))
        .values_list("month")
        .annotate(count=Count("id"))
    }

    trend = [{"month": m.isoformat()[:7], "new_customers": rows.get(m, 0)} for m in month_list]
    return {
        "months": trend,
        "total_customers": Customer.objects.filter(organization=organization).count(),
    }
