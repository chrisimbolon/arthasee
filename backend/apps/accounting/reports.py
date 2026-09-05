# =============================================================================
# === backend/apps/accounting/reports.py ===
# =============================================================================
"""
Arthasee — Financial Reporting (Task 4.1)

Real report-computation logic, separated from apps.accounting.views
the same way posting_engine.py / journal_generator.py / cancellations.py
are already separated from handlers.py — views stay thin (parse query
params, call a function, return a Response), the actual accounting
logic lives here where it can be tested directly against real ledger
data without going through HTTP.
"""
from datetime import date, timedelta
from decimal import Decimal

from apps.accounting.models import (Account, AccountingPeriod, JournalEntry,
                                    JournalLine, OpeningBalancePayable,
                                    OpeningBalanceReceivable,
                                    OpeningBalanceSession)
from apps.invoicing.models import Invoice
from apps.purchasing.models import SupplierInvoice
from django.db.models import F, Sum, Window


def trial_balance(organization, *, as_of=None) -> dict:
    """
    Every active Account's balance as of a point in time.
    total_debit/total_credit are re-derived from each account's OWN
    normal_balance (a debit-normal account's positive balance IS a
    debit-column entry, and vice versa) — not a separate query, so
    is_balanced is a genuine structural proof the ledger is
    internally consistent, not just a label attached after the fact.
    """
    as_of = as_of or date.today()
    accounts = Account.objects.filter(organization=organization, is_active=True).order_by("code")

    rows = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for account in accounts:
        balance = account.balance(as_of=as_of)
        rows.append({
            "code": account.code,
            "name": account.name,
            "account_type": account.account_type,
            "normal_balance": account.normal_balance,
            "balance": balance,
        })
        if account.normal_balance == Account.NormalBalance.DEBIT:
            total_debit += balance
        else:
            total_credit += balance

    return {
        "as_of": as_of,
        "accounts": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": total_debit == total_credit,
    }


def _period_totals(organization, account_type, *, since, as_of):
    """
    Shared by profit_and_loss() and balance_sheet()'s own current-
    year-earnings computation — every account of a given type
    (REVENUE, COGS, EXPENSE), for a real date RANGE, not a
    cumulative-since-inception balance.

    exclude_closing_entries=True, 28 Aug 2026 — real bug found live:
    a closed period's own closing entry is dated inside that same
    period's range. Without this, re-querying an already-closed
    month's own P&L would sum the closing entry's reversing
    debits/credits together with the real original activity,
    netting Revenue/COGS/Expense back toward zero — see
    Account.balance()'s own docstring for the full story.
    """
    accounts = Account.objects.filter(
        organization=organization, account_type=account_type, is_active=True,
    ).order_by("code")
    rows = []
    total = Decimal("0")
    for account in accounts:
        amount = account.balance(since=since, as_of=as_of, exclude_closing_entries=True)
        rows.append({"code": account.code, "name": account.name, "amount": amount})
        total += amount
    return rows, total


def profit_and_loss(organization, *, since, as_of) -> dict:
    """
    ⚠️ "gross_profit" here reflects Service + Parts revenue against
    COGS only — NOT a true job-level gross margin. Mechanic labor is
    posted as period opex (account 6001), not job-costed COGS
    (Roadmap v2.2, Open Decision #1 — a deliberate scope call made
    when the roadmap was first written, not an oversight here). The
    caveat ships as a real field in this response
    (gross_profit_note), specifically so a future frontend can't
    silently drop it — the roadmap's own Task 4.1 note explicitly
    required this stay visible in the UI.
    """
    revenue, total_revenue = _period_totals(organization, Account.AccountType.REVENUE, since=since, as_of=as_of)
    cogs, total_cogs       = _period_totals(organization, Account.AccountType.COGS,    since=since, as_of=as_of)
    expenses, total_expenses = _period_totals(organization, Account.AccountType.EXPENSE, since=since, as_of=as_of)

    gross_profit = total_revenue - total_cogs
    net_income   = gross_profit - total_expenses

    return {
        "since": since,
        "as_of": as_of,
        "revenue": revenue,
        "total_revenue": total_revenue,
        "cogs": cogs,
        "total_cogs": total_cogs,
        "gross_profit": gross_profit,
        "gross_profit_note": (
            "Termasuk margin Jasa & Sparepart saja — biaya tenaga kerja "
            "mekanik dicatat sebagai beban operasional (6001), bukan HPP "
            "per pekerjaan."
        ),
        "expenses": expenses,
        "total_expenses": total_expenses,
        "net_income": net_income,
    }

def profit_and_loss_comparison(organization, *, since, as_of) -> dict:
    """
    Wraps profit_and_loss() twice — once for the requested period,
    once for an equal-length period immediately preceding it — and
    computes real deltas. Callers get real period-over-period
    comparison, not a raw second report they'd have to diff
    themselves.

    The "comparable prior period" is derived from the CURRENT
    period's own actual length (as_of - since, inclusive), never
    assumed to be "the previous calendar month" — a user comparing
    Aug 1-15 gets compared against Jul 17-31 (also 15 days), not an
    unequal, misleading comparison. Verified by hand across a full
    calendar month, an uneven half-month range, and a year boundary
    before this was written.

    change_pct is None when the prior period's value was exactly
    zero — an honest "can't compute a percentage from zero" rather
    than a division error or a fabricated infinite/undefined number.
    Uses abs(prior_val) as the denominator so a swing from a loss to
    a profit (or vice versa) still produces an interpretable
    magnitude rather than a sign-flipped, confusing percentage —
    verified by hand: -100k -> +50k correctly reads as +150%, not a
    nonsensical negative.
    """
    duration_days = (as_of - since).days + 1  # inclusive span
    prior_as_of = since - timedelta(days=1)
    prior_since = prior_as_of - timedelta(days=duration_days - 1)

    current = profit_and_loss(organization, since=since, as_of=as_of)
    prior   = profit_and_loss(organization, since=prior_since, as_of=prior_as_of)

    def _delta(curr_val, prior_val):
        change = curr_val - prior_val
        change_pct = None
        if prior_val != Decimal("0"):
            change_pct = (change / abs(prior_val)) * Decimal("100")
        return {"change": change, "change_pct": change_pct}

    return {
        "current": current,
        "prior": prior,
        "revenue_delta":      _delta(current["total_revenue"], prior["total_revenue"]),
        "gross_profit_delta": _delta(current["gross_profit"],  prior["gross_profit"]),
        "net_income_delta":   _delta(current["net_income"],    prior["net_income"]),
    }

def cash_conversion_cycle(organization, *, since, as_of) -> dict:
    """
    CCC = DIO + DSO - DPO, all in days — how long cash is tied up
    between paying for inventory and collecting cash from a
    customer. Lower is healthier; a negative CCC means suppliers are
    effectively financing operations (DPO exceeds DIO+DSO).

    Inventory for DIO deliberately includes BOTH 1301 (Spare Parts)
    and 1302 (Work In Progress) — Chris's own explicit call: total
    stock valuation on hand covers parts sitting on the shelf AND
    labor/parts already committed to an open job, both real capital
    tied up before a sale completes.

    COGS and Revenue are summed via the SAME _period_totals() helper
    already used by profit_and_loss() — not hardcoded account codes
    — so this automatically covers every real COGS/Revenue account
    (5001/5002/5003, 4001/4002 today) without needing an update if a
    new one is ever added to the Chart of Accounts.

    "Average" balance = (opening + closing) / 2, where opening is
    the balance as of the day BEFORE `since` (the true cumulative
    balance immediately prior to this period — NOT a balance that
    already includes this period's own activity) and closing is the
    balance as of `as_of` itself.

    Division-by-zero is handled explicitly, not left to crash —
    Chris's own explicit requirement: a period with zero COGS or
    zero Revenue (e.g. a brand-new organization's first few days)
    returns 0 days for the affected metric rather than raising
    ZeroDivisionError. Full formula and this exact edge case both
    verified by hand before being written here.
    """
    days_in_period = (as_of - since).days + 1  # inclusive span, same convention as profit_and_loss_comparison()
    opening_as_of = since - timedelta(days=1)

    def _avg_balance(account):
        opening = account.balance(as_of=opening_as_of)
        closing = account.balance(as_of=as_of)
        return (opening + closing) / Decimal("2")

    part_inventory = Account.resolve(organization, "1301")
    wip            = Account.resolve(organization, "1302")
    ar             = Account.resolve(organization, "1201")
    ap             = Account.resolve(organization, "2001")

    avg_inventory = _avg_balance(part_inventory) + _avg_balance(wip)
    avg_ar        = _avg_balance(ar)
    avg_ap        = _avg_balance(ap)

    _, total_cogs    = _period_totals(organization, Account.AccountType.COGS,    since=since, as_of=as_of)
    _, total_revenue = _period_totals(organization, Account.AccountType.REVENUE, since=since, as_of=as_of)

    def _days(avg_balance, denominator):
        if denominator == Decimal("0"):
            return Decimal("0")
        return (avg_balance / denominator) * Decimal(days_in_period)

    dio = _days(avg_inventory, total_cogs)
    dso = _days(avg_ar, total_revenue)
    dpo = _days(avg_ap, total_cogs)
    ccc = dio + dso - dpo

    return {
        "since": since,
        "as_of": as_of,
        "days_in_period": days_in_period,
        "avg_inventory": avg_inventory,
        "avg_ar": avg_ar,
        "avg_ap": avg_ap,
        "total_cogs": total_cogs,
        "total_revenue": total_revenue,
        "dio": dio,
        "dso": dso,
        "dpo": dpo,
        "ccc": ccc,
    }

def _unclosed_earnings_start(organization, as_of):
    """
    4 Sep 2026 — real fix, found via a careful design-review trace,
    not a live incident: the previous version of this function
    (_current_period_start) only ever returned the start date of the
    ONE AccountingPeriod covering `as_of` — correct for a shop that
    closes every period promptly, silently wrong the moment MORE
    THAN ONE period sits open at once. That's now a real, common
    state — Opening Balance onboarding can backdate a shop's real
    history by months, and nothing forces every earlier period
    closed before reaching the current one. balance_sheet()'s own
    current_year_earnings would then only capture the CURRENT
    period's own slice of Revenue/COGS/Expense, silently dropping
    every earlier unclosed period's real net income out of Equity —
    breaking Assets == Liabilities + Equity the moment real activity
    spans more than the single most-recent open month.

    Real fix: find the most recently CLOSED period (by end_date) for
    this org, strictly before as_of, and return the day right after
    it — the true start of ALL unclosed activity, not just whatever
    the current period alone covers. Returns None (all-time) if this
    org has never closed a single period — every unclosed-until-now
    real posting genuinely belongs in current_year_earnings in that
    case, same honest "no period found -> full history" fallback the
    old function already had for the rarer historical-as_of case.
    """
    most_recently_closed = AccountingPeriod.objects.filter(
        organization=organization, is_closed=True, end_date__lt=as_of,
    ).order_by("-end_date").first()
    if most_recently_closed is None:
        return None
    return most_recently_closed.end_date + timedelta(days=1)


def balance_sheet(organization, *, as_of=None) -> dict:
    """
    Folds current-period net income into Equity explicitly — nothing
    in this system performs period-end closing entries (zeroing
    Revenue/COGS/Expense into Retained Earnings), so unclosed net
    income has nowhere else to go. Without this, Assets would not
    equal Liabilities + Equity the moment there's been any real
    activity at all — not a bug, just unclosed books; this makes the
    report balance honestly rather than pretending the gap doesn't
    exist.

    period_start comes from the most recently CLOSED period's own
    end_date + 1 day (_unclosed_earnings_start(), fixed 4 Sep 2026 —
    see that function's own docstring for the real gap this closed:
    the old version only used the CURRENT period's own start,
    silently dropping earlier unclosed periods' real net income out
    of Equity whenever more than one period sits open at once — a
    real, common state now that Opening Balance onboarding can
    backdate a shop's history by months). Falls back to since=None
    (all-time net income) when this org has never closed a single
    period — every unclosed-until-now posting genuinely belongs in
    current_year_earnings in that case.
    """
    as_of = as_of or date.today()

    assets = Account.objects.filter(organization=organization, account_type=Account.AccountType.ASSET, is_active=True).order_by("code")
    asset_rows = [
        {"code": a.code, "name": a.name, "balance": a.balance(as_of=as_of), "normal_balance": a.normal_balance}
        for a in assets
    ]
    # 29 Aug 2026 — real bug found and fixed BEFORE it ever shipped:
    # a contra-asset account (1402 Accumulated Depreciation,
    # normal_balance=CREDIT, the first asset-type account in this
    # whole COA with a credit normal balance) correctly returns a
    # POSITIVE number from Account.balance() for its own real credit
    # balance — but blindly summing every asset row together, as
    # this line originally did, would have ADDED that positive
    # number to total_assets instead of subtracting it, inflating
    # total assets the moment depreciation ever posted anything —
    # the exact opposite of what a contra-asset means. Fixed
    # generally, not special-cased to 1402 specifically — any future
    # credit-normal asset account is handled correctly by the same
    # rule. trial_balance() above never had this bug — it already
    # branches on normal_balance before choosing a column.
    total_assets = sum(
        (
            (r["balance"] if r["normal_balance"] == Account.NormalBalance.DEBIT else -r["balance"])
            for r in asset_rows
        ),
        Decimal("0"),
    )

    liabilities = Account.objects.filter(organization=organization, account_type=Account.AccountType.LIABILITY, is_active=True).order_by("code")
    liability_rows = [{"code": a.code, "name": a.name, "balance": a.balance(as_of=as_of)} for a in liabilities]
    total_liabilities = sum((r["balance"] for r in liability_rows), Decimal("0"))

    equity = Account.objects.filter(organization=organization, account_type=Account.AccountType.EQUITY, is_active=True).order_by("code")
    equity_rows = [{"code": a.code, "name": a.name, "balance": a.balance(as_of=as_of)} for a in equity]
    total_equity_accounts = sum((r["balance"] for r in equity_rows), Decimal("0"))

    period_start = _unclosed_earnings_start(organization, as_of)
    period = AccountingPeriod.objects.filter(
        organization=organization, start_date__lte=as_of, end_date__gte=as_of,
    ).first()
    if period is not None and period.is_closed:
        # 28 Aug 2026 — real double-count found live: a closed
        # period's own income already lives in 3101 via its real
        # closing entry (see AccountingPeriod.close()'s own
        # docstring). If as_of falls WITHIN that closed period's own
        # range, re-deriving its P&L here AGAIN — even with
        # _period_totals()'s own exclude_closing_entries fix, which
        # only hides the closing entry itself, not the real activity
        # it summarized — would double-count that same income
        # alongside what 3101 already, correctly reflects. Nothing
        # "unclosed" remains to show separately once the covering
        # period has actually been closed.
        total_revenue = total_cogs = total_expenses = Decimal("0")
    else:
        _, total_revenue  = _period_totals(organization, Account.AccountType.REVENUE, since=period_start, as_of=as_of)
        _, total_cogs     = _period_totals(organization, Account.AccountType.COGS,    since=period_start, as_of=as_of)
        _, total_expenses = _period_totals(organization, Account.AccountType.EXPENSE, since=period_start, as_of=as_of)
    current_year_earnings = total_revenue - total_cogs - total_expenses

    total_equity = total_equity_accounts + current_year_earnings
    total_liabilities_and_equity = total_liabilities + total_equity

    return {
        "as_of": as_of,
        "assets": asset_rows,
        "total_assets": total_assets,
        "liabilities": liability_rows,
        "total_liabilities": total_liabilities,
        "equity": equity_rows,
        "current_year_earnings": current_year_earnings,
        "total_equity": total_equity,
        "total_liabilities_and_equity": total_liabilities_and_equity,
        "is_balanced": total_assets == total_liabilities_and_equity,
    }


def _age_bucket(age_days: int) -> str:
    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    return "90+"


def aging_ar(organization, *, as_of=None) -> dict:
    """
    Reads the real sub-ledger (Invoice rows), not the GL — AR (1201)
    is a single control account; individual invoice detail only
    exists in apps.invoicing.Invoice. Ages from created_at — Invoice
    has no separate "issued_at" timestamp (only issued_event_id, a
    reference, not a date), so created_at is the closest real proxy
    for "when this became a receivable" (Chris's own explicit call).

    3 Sep 2026 — Opening Balance onboarding. A legacy receivable from
    before the shop used Arthasee is real, outstanding money owed —
    Made's own Piutang card must reflect it from Day 1, not just
    invoices Arthasee itself created (Sansan's own signed-off Option
    B: OpeningBalanceReceivable is a lightweight, dedicated row, not
    forced through the full Invoice schema — see that model's own
    docstring). Only rows belonging to a POSTED session count — a
    DRAFT session's line items are still wizard scratch data, not a
    real financial fact yet.

    Aged from the session's own start_date, not any invoice-style
    timestamp — the one honest anchor this lightweight model actually
    has: "the day the shop told Arthasee this was already owed,"
    since there's no earlier real date on record for a legacy debt.

    Every row now carries a "source" field ("invoice" or
    "opening_balance") — a real, honest distinction a future consumer
    needs before treating every row as linkable to an Invoice detail
    page; an opening-balance row has no such page. Purely additive —
    existing consumers that don't read this key are unaffected.
    """
    as_of = as_of or date.today()
    invoices = Invoice.objects.filter(organization=organization, status="ISSUED")

    rows = []
    buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "90+": Decimal("0")}
    total_outstanding = Decimal("0")

    for invoice in invoices:
        balance_due = invoice.balance_due
        if balance_due <= Decimal("0"):
            continue  # fully covered by payments already, not really outstanding
        age_days = (as_of - invoice.created_at.date()).days
        bucket = _age_bucket(age_days)
        rows.append({
            "id": str(invoice.id),
            "number": invoice.number,
            "customer_name": invoice.customer_name_snapshot,
            "balance_due": balance_due,
            "age_days": age_days,
            "bucket": bucket,
            "source": "invoice",
        })
        buckets[bucket] += balance_due
        total_outstanding += balance_due

    opening_receivables = (
        OpeningBalanceReceivable.objects
        .filter(organization=organization, session__status=OpeningBalanceSession.Status.POSTED)
        .select_related("customer", "session")
    )
    for ar_line in opening_receivables:
        if ar_line.balance_due <= Decimal("0"):
            continue
        age_days = (as_of - ar_line.session.start_date).days
        bucket = _age_bucket(age_days)
        rows.append({
            "id": str(ar_line.id),
            "number": ar_line.reference or "Saldo Awal",
            "customer_name": ar_line.customer.name,
            "balance_due": ar_line.balance_due,
            "age_days": age_days,
            "bucket": bucket,
            "source": "opening_balance",
        })
        buckets[bucket] += ar_line.balance_due
        total_outstanding += ar_line.balance_due

    return {
        "as_of": as_of,
        "invoices": rows,
        "buckets": buckets,
        "total_outstanding": total_outstanding,
    }


def aging_ap(organization, *, as_of=None) -> dict:
    """
    Reads SupplierInvoice rows directly, same reasoning as
    aging_ar() above. Ages from due_date when set, falling back to
    invoice_date when it isn't (due_date is nullable on
    SupplierInvoice).

    3 Sep 2026 — mirrors aging_ar()'s own Opening Balance union
    exactly, inverted for legacy supplier debt (OpeningBalancePayable
    — Sansan's own signed-off Option B, same lightweight-row
    reasoning). Ages from due_date when the owner actually entered
    one at onboarding, falling back to the session's own start_date
    otherwise — the same due_date-or-fallback shape SupplierInvoice
    rows already use, just substituting the one real anchor date this
    lightweight model actually has for invoice_date. Same "source"
    field addition and same POSTED-only filter as aging_ar().
    """
    as_of = as_of or date.today()
    invoices = SupplierInvoice.objects.filter(organization=organization, status="UNPAID").select_related("supplier")

    rows = []
    buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "90+": Decimal("0")}
    total_outstanding = Decimal("0")

    for invoice in invoices:
        reference_date = invoice.due_date or invoice.invoice_date
        age_days = (as_of - reference_date).days
        bucket = _age_bucket(age_days)
        rows.append({
            "id": str(invoice.id),
            "number": invoice.number,
            "supplier_name": invoice.supplier.name,
            "amount": invoice.amount,
            "age_days": age_days,
            "bucket": bucket,
            "source": "invoice",
        })
        buckets[bucket] += invoice.amount
        total_outstanding += invoice.amount

    opening_payables = (
        OpeningBalancePayable.objects
        .filter(organization=organization, session__status=OpeningBalanceSession.Status.POSTED)
        .select_related("supplier", "session")
    )
    for ap_line in opening_payables:
        if ap_line.balance_due <= Decimal("0"):
            continue
        reference_date = ap_line.due_date or ap_line.session.start_date
        age_days = (as_of - reference_date).days
        bucket = _age_bucket(age_days)
        rows.append({
            "id": str(ap_line.id),
            "number": ap_line.reference or "Saldo Awal",
            "supplier_name": ap_line.supplier.name,
            "amount": ap_line.balance_due,
            "age_days": age_days,
            "bucket": bucket,
            "source": "opening_balance",
        })
        buckets[bucket] += ap_line.balance_due
        total_outstanding += ap_line.balance_due

    return {
        "as_of": as_of,
        "supplier_invoices": rows,
        "buckets": buckets,
        "total_outstanding": total_outstanding,
    }

def dashboard_financial_summary(organization, *, as_of=None) -> dict:
    """
    Purpose-built for the owner-facing overview dashboard — Made's
    own real question, quoted directly: "Berapa banyak pelanggan
    yang belum bayar? Siapa saja? (Piutang)" and "Bengkel kita
    berhutang ke siapa saja dan berapa jumlahnya? (Utang)".

    AR's "overdue" callout reuses aging_ar()'s own buckets directly
    (everything outside "0-30") — safe to do, because Invoice ages
    from created_at, which can never be in the future relative to
    as_of, so that bucket boundary means what it looks like it means.
    3 Sep 2026 — this also means the AR side of this function picks
    up Opening Balance receivables automatically, for free, the
    moment aging_ar() itself unions them in — no separate code
    needed here.

    AP's callout is deliberately NOT built the same way. aging_ap()
    ages from due_date, which CAN be in the future — a real,
    different risk verified by hand before this was written: a
    SupplierInvoice due a week from now has a NEGATIVE age_days,
    which still satisfies "<= 30" and would silently land in that
    same "0-30" bucket, mixing "not due yet" with "overdue by up to
    a month." Made's own framing is explicitly forward-looking
    ("due within the current week"), so this builds a fresh,
    explicit due_date <= as_of + 7 days filter instead of reusing
    aging_ap()'s bucket at all. Because of that, Opening Balance
    payables need the identical union applied a SECOND time, here,
    explicitly — they are NOT automatically covered by aging_ap()'s
    own fix, since this function's AP side never calls aging_ap() at
    all.

    Both detail lists are capped at 5 rows, sorted by what matters
    most (AR: highest balance first; AP: soonest due first) — this
    is a dashboard summary widget, not the full aging report; the
    full Piutang (AR) / Utang (AP) tabs already exist for everything
    beyond the headline.
    """
    as_of = as_of or date.today()

    ar_data = aging_ar(organization, as_of=as_of)
    ar_overdue_rows = [row for row in ar_data["invoices"] if row["bucket"] != "0-30"]
    ar_overdue_rows.sort(key=lambda r: r["balance_due"], reverse=True)
    ar_overdue_total = sum((row["balance_due"] for row in ar_overdue_rows), Decimal("0"))
    ar_overdue_customers = sorted({row["customer_name"] for row in ar_overdue_rows})

    ap_week_cutoff = as_of + timedelta(days=7)
    unpaid = SupplierInvoice.objects.filter(organization=organization, status="UNPAID").select_related("supplier")
    ap_total_outstanding = Decimal("0")
    ap_due_soon_rows = []
    for invoice in unpaid:
        ap_total_outstanding += invoice.amount
        reference_date = invoice.due_date or invoice.invoice_date
        if reference_date <= ap_week_cutoff:
            ap_due_soon_rows.append({
                "id": str(invoice.id), "number": invoice.number,
                "supplier_name": invoice.supplier.name,
                "amount": invoice.amount, "due_date": reference_date,
                "source": "invoice",
            })

    opening_payables = (
        OpeningBalancePayable.objects
        .filter(organization=organization, session__status=OpeningBalanceSession.Status.POSTED)
        .select_related("supplier", "session")
    )
    for ap_line in opening_payables:
        ap_total_outstanding += ap_line.balance_due
        reference_date = ap_line.due_date or ap_line.session.start_date
        if reference_date <= ap_week_cutoff:
            ap_due_soon_rows.append({
                "id": str(ap_line.id), "number": ap_line.reference or "Saldo Awal",
                "supplier_name": ap_line.supplier.name,
                "amount": ap_line.balance_due, "due_date": reference_date,
                "source": "opening_balance",
            })

    ap_due_soon_rows.sort(key=lambda r: r["due_date"])
    ap_due_soon_total = sum((r["amount"] for r in ap_due_soon_rows), Decimal("0"))

    return {
        "as_of": as_of,
        "ar_total_outstanding": ar_data["total_outstanding"],
        "ar_overdue_total": ar_overdue_total,
        "ar_overdue_count": len(ar_overdue_rows),
        "ar_overdue_customers": ar_overdue_customers,
        "ar_overdue_invoices": ar_overdue_rows[:5],
        "ap_total_outstanding": ap_total_outstanding,
        "ap_due_soon_total": ap_due_soon_total,
        "ap_due_soon_count": len(ap_due_soon_rows),
        "ap_due_soon_invoices": ap_due_soon_rows[:5],
    }


# 1 Sep 2026 — Kas Harian. Made's own confirmed real request: a
# plain-language daily cash view, distinct from the Jurnal & Audit
# Log page (see the real Ringkasan/Jurnal UX discussion this task
# came out of — Jurnal stays exactly as-is, audit-grade and
# untouched; this is the "5-second glance" version, reusing the same
# already-posted ledger data, never a second, duplicate cash ledger).
#
# Every event type actually capable of touching Cash (1001) or Bank
# (1101) is mapped to a real, friendly category label here — the
# ONLY place in this codebase that maps event_type -> a human label
# for cash purposes, so the Kas Harian page and any future consumer
# share one real definition, not a second copy that could drift.
_CASH_BANK_CODES = ("1001", "1101")

_CASH_ACTIVITY_CATEGORY_LABELS = {
    "PaymentReceived": "Servis & Part",
    "SupplierPaymentMade": "Pembayaran Supplier",
    "OperatingExpenseRecorded": "Biaya Operasional",
    "QuickPurchaseRecorded": "Pembelian Stok",
    "InternalCashMutationRecorded": "Mutasi Kas",
}


def daily_cash_activity(organization, *, on_date=None) -> dict:
    """
    Every real cash/bank-touching JournalEntry for one calendar day,
    grouped into plain-language rows an owner can actually read —
    "Rp736.000 masuk dari pembayaran Yono," not "Dr 1001 / Cr 1201."
    Reads the already-posted ledger directly (JournalEntry/
    JournalLine) — no second cash ledger table, Chris's own
    confirmed call: the GL is the one real source of truth, this is
    just a friendlier lens on it.

    InternalCashMutationRecorded is handled as a special case,
    deliberately: every OTHER event in this file's own category map
    touches exactly one Cash/Bank line per entry (money genuinely
    entering or leaving the business), but a mutation's own 2-line
    entry (Dr 1101 / Cr 1001, or the reverse) touches Cash/Bank on
    BOTH sides — it's an internal transfer, not a real inflow or
    outflow. Emitting it as two separate in/out rows would double-
    count it and misrepresent it as real revenue/expense activity;
    emitting it as ONE "mutation" row (direction="mutation", no sign)
    is both mathematically correct (net_cash excludes it entirely,
    matching real position) and matches what an owner actually did —
    moved money, not earned or spent it.

    Every other qualifying entry emits one row per Cash/Bank line it
    actually contains — in practice always exactly one, since no
    other event in this system's posting matrix currently posts to
    two Cash/Bank accounts in the same entry.
    """
    on_date = on_date or date.today()

    entries = (
        JournalEntry.objects
        .filter(organization=organization, posting_date=on_date, lines__account__code__in=_CASH_BANK_CODES)
        .distinct()
        .prefetch_related("lines__account")
        .order_by("-created_at")
    )

    activities = []
    total_in = Decimal("0")
    total_out = Decimal("0")

    for entry in entries:
        category = _CASH_ACTIVITY_CATEGORY_LABELS.get(entry.event_type, "Lainnya")
        cash_bank_lines = [l for l in entry.lines.all() if l.account.code in _CASH_BANK_CODES]

        if entry.event_type == "InternalCashMutationRecorded":
            # See docstring above — one row, no sign, excluded from
            # total_in/total_out on purpose.
            debit_line = next((l for l in cash_bank_lines if l.debit_amount > Decimal("0")), None)
            credit_line = next((l for l in cash_bank_lines if l.credit_amount > Decimal("0")), None)
            if debit_line is None or credit_line is None:
                continue  # malformed/partial data — skip rather than misreport
            activities.append({
                "journal_entry_id": str(entry.id),
                "entry_number": entry.entry_number,
                "posting_date": entry.posting_date,
                "created_at": entry.created_at,
                "event_type": entry.event_type,
                "category": category,
                "memo": entry.memo,
                "direction": "mutation",
                "from_account_code": credit_line.account.code,
                "from_account_name": credit_line.account.name,
                "to_account_code": debit_line.account.code,
                "to_account_name": debit_line.account.name,
                "amount": debit_line.debit_amount,
            })
            continue

        for line in cash_bank_lines:
            if line.debit_amount > Decimal("0"):
                direction, amount = "in", line.debit_amount
                total_in += amount
            else:
                direction, amount = "out", line.credit_amount
                total_out += amount
            activities.append({
                "journal_entry_id": str(entry.id),
                "entry_number": entry.entry_number,
                "posting_date": entry.posting_date,
                "created_at": entry.created_at,
                "event_type": entry.event_type,
                "category": category,
                "memo": entry.memo,
                "direction": direction,
                "account_code": line.account.code,
                "account_name": line.account.name,
                "amount": amount,
            })

    activities.sort(key=lambda a: a["created_at"], reverse=True)

    return {
        "date": on_date,
        "activities": activities,
        "total_in": total_in,
        "total_out": total_out,
        "net_cash": total_in - total_out,
        "in_count": sum(1 for a in activities if a["direction"] == "in"),
        "out_count": sum(1 for a in activities if a["direction"] == "out"),
        "mutation_count": sum(1 for a in activities if a["direction"] == "mutation"),
    }


# =============================================================================
# General Ledger (Buku Besar) — 4 Sep 2026
# =============================================================================
"""
Sansan's own "From Journal to General Ledger" architecture proposal,
reviewed against the real codebase before being built (two visual
specs corrected during that review — see the design conversation for
the full reasoning): an account-centric view of the same real,
already-posted ledger, with a genuine running balance, not a second
source of truth alongside trial_balance()/the Jurnal page.

Real, deliberate engineering choice: the running balance is computed
via a Postgres window function (Window(Sum(...))), not a Python
cumulative loop. A high-volume account (Cash, say) can accumulate
thousands of lines across a year — a window function computes the
cumulative sum ONCE, in the database, over the full filtered date
range; only the requested page is ever pulled into Python. A naive
loop would need every prior row in memory just to add them up, and
get slower every month that passes. Opening balance itself reuses
Account.balance(as_of=...) directly — already-proven, already-tested
code, not reinvented here.

total_count/total_debit/total_credit are computed from a SEPARATE,
un-annotated queryset, not derived from the windowed one — counting
or aggregating a queryset that already carries a window annotation
would force Postgres to materialize the full window computation just
to answer a count, real, avoidable overhead this sidesteps entirely.
"""

def general_ledger(organization, *, account_code, since=None, as_of=None, page=1, page_size=50) -> dict:
    """
    One account's own real activity, ordered chronologically, with a
    genuine running balance column — Buku Besar's own real data
    source. Raises ValueError (via Account.resolve()) if account_code
    doesn't resolve to a real, seeded Account for this organization —
    same real error shape every other account-code lookup in this
    codebase already produces.

    since=None means "from this account's own inception" — opening_
    balance is Decimal("0") in that case, matching trial_balance()'s
    own all-time convention. When since IS given, opening_balance is
    the real cumulative balance as of the day BEFORE it — the true
    starting point this range's own running balance builds from, not
    a range that silently starts from zero and misrepresents the
    account's real position.
    """
    as_of = as_of or date.today()
    account = Account.resolve(organization, account_code)

    base_qs = JournalLine.objects.filter(account=account, journal_entry__posting_date__lte=as_of)
    if since is not None:
        base_qs = base_qs.filter(journal_entry__posting_date__gte=since)

    opening_balance = account.balance(as_of=since - timedelta(days=1)) if since is not None else Decimal("0")

    totals = base_qs.aggregate(total_debit=Sum("debit_amount"), total_credit=Sum("credit_amount"))
    total_debit = totals["total_debit"] or Decimal("0")
    total_credit = totals["total_credit"] or Decimal("0")

    sign = 1 if account.normal_balance == Account.NormalBalance.DEBIT else -1
    closing_balance = opening_balance + (total_debit - total_credit) * sign

    total_count = base_qs.count()

    # Window() requires the queryset's own order_by() to match the
    # window's internal order_by exactly — a real Django requirement
    # for any query containing a window function, not a style choice.
    windowed_qs = (
        base_qs
        .annotate(delta=(F("debit_amount") - F("credit_amount")) * sign)
        .annotate(cumulative=Window(
            expression=Sum("delta"),
            order_by=[F("journal_entry__posting_date").asc(), F("created_at").asc(), F("id").asc()],
        ))
        .select_related("journal_entry")
        .order_by("journal_entry__posting_date", "created_at", "id")
    )

    offset = (page - 1) * page_size
    page_lines = list(windowed_qs[offset:offset + page_size])

    rows = []
    for line in page_lines:
        entry = line.journal_entry
        rows.append({
            "line_id": str(line.id),
            "posting_date": entry.posting_date,
            "entry_number": entry.entry_number,
            "event_type": entry.event_type,
            "source": entry.source,
            # line.description first — a manual journal can carry a
            # real per-line description distinct from the entry's
            # own memo; falls back to the entry-level memo for every
            # domain-event posting, where individual lines rarely
            # carry their own separate text.
            "memo": line.description or entry.memo,
            "debit": line.debit_amount,
            "credit": line.credit_amount,
            "running_balance": opening_balance + line.cumulative,
            "reference_event_id": str(entry.reference_event_id) if entry.reference_event_id else None,
        })

    return {
        "account": {
            "code": account.code, "name": account.name,
            "account_type": account.account_type, "normal_balance": account.normal_balance,
        },
        "since": since,
        "as_of": as_of,
        "opening_balance": opening_balance,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "closing_balance": closing_balance,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "rows": rows,
    }
