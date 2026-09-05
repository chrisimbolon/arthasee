# =============================================================================
# === backend/apps/accounting/views.py ===
# =============================================================================
"""
Arthasee — Accounting Views

Three kinds of endpoint in this file: the five Task 4.1 reporting
views (thin — parse params, call reports.py, return the result),
Task 4.4's manual journal view (a real WRITE path, validated input,
owner-only), and Task 5.2's two read-only audit views (general
journal-entry listing, and the failed-postings view — the real point
of Task 5.2). 28 Aug 2026 adds a fourth kind — real month-end period
control (list/close/reopen), Made's own confirmed requirement via his
tax & accounting consultant. 1 Sep 2026 adds DailyCashActivityView —
Kas Harian, a point-in-day reporting view following the exact same
thin-view-calls-reports.py shape as every other read-only view here.

3 Sep 2026 adds a fifth kind — Opening Balance onboarding. Session
create/read/post follow the owner-only, real-model-method-owns-the-
logic discipline AccountingPeriodCloseView already established; the
six line-item endpoints underneath are open to any authenticated
member of the org (data entry during onboarding doesn't need to be
owner-only — only CREATING the session and the final, irreversible
POST do, matching the stakes of each action rather than gating
everything uniformly).

4 Sep 2026 adds a sixth kind — General Ledger (Buku Besar), an
account-centric view of the same real, already-posted ledger. Same
thin-view-calls-reports.py shape as every other read-only view here;
the one real addition is calling trace_forward.resolve_references()
on the result before returning it, batched once per response, not
per row.
"""
from datetime import date

from apps.core.models import Outbox
from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from . import reports, trace_forward
from .models import (Account, AccountingPeriod, Asset, DepreciationRun,
                     JournalEntry, OpeningBalanceAssetLine,
                     OpeningBalanceCashLine, OpeningBalanceOtherLine,
                     OpeningBalancePartLine, OpeningBalancePayable,
                     OpeningBalanceReceivable, OpeningBalanceSession)
from .serializers import (AccountingPeriodSerializer, AssetRecordSerializer,
                          AssetSerializer, DepreciationRunSerializer,
                          FailedPostingSerializer, JournalEntrySerializer,
                          ManualJournalRecordSerializer,
                          OpeningBalanceAssetLineRecordSerializer,
                          OpeningBalanceAssetLineSerializer,
                          OpeningBalanceCashLineRecordSerializer,
                          OpeningBalanceCashLineSerializer,
                          OpeningBalanceOtherLineRecordSerializer,
                          OpeningBalanceOtherLineSerializer,
                          OpeningBalancePartLineRecordSerializer,
                          OpeningBalancePartLineSerializer,
                          OpeningBalancePayableRecordSerializer,
                          OpeningBalancePayableSerializer,
                          OpeningBalanceReceivableRecordSerializer,
                          OpeningBalanceReceivableSerializer,
                          OpeningBalanceSessionRecordSerializer,
                          OpeningBalanceSessionSerializer)


def _parse_date(value, default=None):
    if not value:
        return default
    return date.fromisoformat(value)


def _require_owner(request, organization):
    """
    Shared authorization gate, 28 Aug 2026 — the two new period
    write actions (close/reopen) need the exact same owner-only check
    ManualJournalListCreateView.post() already established. Factored
    out here rather than copy-pasted a third time.
    """
    membership = request.user.memberships.filter(organization=organization, is_active=True).first()
    return membership is not None and membership.role == "owner"


class TrialBalanceView(TenantScopedAPIView):
    """GET /api/accounting/trial-balance/?as_of=YYYY-MM-DD"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        as_of = _parse_date(request.query_params.get("as_of"))
        data = reports.trial_balance(organization, as_of=as_of)
        return Response({"success": True, **data})


class ProfitLossView(TenantScopedAPIView):
    """
    GET /api/accounting/profit-loss/?since=YYYY-MM-DD&as_of=YYYY-MM-DD&compare=1

    compare=1 wraps the response with a real period-over-period
    comparison (reports.profit_and_loss_comparison()) instead of the
    plain single-period report. Same since/as_of parsing either way
    — existing callers that never pass compare get byte-identical
    behavior to before this was added.
    """

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        as_of = _parse_date(request.query_params.get("as_of"), default=date.today())
        since = _parse_date(request.query_params.get("since"))
        if since is None:
            period = AccountingPeriod.objects.filter(
                organization=organization, start_date__lte=as_of, end_date__gte=as_of,
            ).first()
            since = period.start_date if period else date(as_of.year, 1, 1)

        compare = request.query_params.get("compare") in ("1", "true", "True")
        if compare:
            data = reports.profit_and_loss_comparison(organization, since=since, as_of=as_of)
        else:
            data = reports.profit_and_loss(organization, since=since, as_of=as_of)
        return Response({"success": True, **data})

class CashConversionCycleView(TenantScopedAPIView):
    """
    GET /api/accounting/cash-conversion-cycle/?since=YYYY-MM-DD&as_of=YYYY-MM-DD
    Same since/as_of defaulting as ProfitLossView — falls back to the
    current AccountingPeriod's own start date, then Jan 1, if since
    isn't explicitly passed.
    """

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        as_of = _parse_date(request.query_params.get("as_of"), default=date.today())
        since = _parse_date(request.query_params.get("since"))
        if since is None:
            period = AccountingPeriod.objects.filter(
                organization=organization, start_date__lte=as_of, end_date__gte=as_of,
            ).first()
            since = period.start_date if period else date(as_of.year, 1, 1)

        data = reports.cash_conversion_cycle(organization, since=since, as_of=as_of)
        return Response({"success": True, **data})

class BalanceSheetView(TenantScopedAPIView):
    """GET /api/accounting/balance-sheet/?as_of=YYYY-MM-DD"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        as_of = _parse_date(request.query_params.get("as_of"))
        data = reports.balance_sheet(organization, as_of=as_of)
        return Response({"success": True, **data})


class AgingARView(TenantScopedAPIView):
    """GET /api/accounting/aging-ar/?as_of=YYYY-MM-DD"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        as_of = _parse_date(request.query_params.get("as_of"))
        data = reports.aging_ar(organization, as_of=as_of)
        return Response({"success": True, **data})


class AgingAPView(TenantScopedAPIView):
    """GET /api/accounting/aging-ap/?as_of=YYYY-MM-DD"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        as_of = _parse_date(request.query_params.get("as_of"))
        data = reports.aging_ap(organization, as_of=as_of)
        return Response({"success": True, **data})

class DashboardFinancialSummaryView(TenantScopedAPIView):
    """
    GET /api/accounting/dashboard-financial-summary/?as_of=YYYY-MM-DD
    A point-in-time snapshot, not a period report — no `since`, same
    as balance-sheet/trial-balance/aging-ar/aging-ap. Purpose-built
    for the owner-facing Ringkasan dashboard, not the Laporan
    Keuangan reports page.
    """

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        as_of = _parse_date(request.query_params.get("as_of"))
        data = reports.dashboard_financial_summary(organization, as_of=as_of)
        return Response({"success": True, **data})


class GeneralLedgerView(TenantScopedAPIView):
    """
    GET /api/accounting/general-ledger/?account=1001&since=&as_of=&page=1&page_size=50

    4 Sep 2026 — Buku Besar. account query param is required (a
    plain account CODE, resolved via Account.resolve() the same way
    every other real posting in this codebase resolves one — never a
    bare Account UUID lookup). page/page_size are bounded defensively
    (page >= 1, 1 <= page_size <= 200) — a real ceiling against an
    abusive or accidental page_size request, not just an unbounded
    passthrough.

    trace_forward.resolve_references() runs once per response,
    mutating the already-built rows list in place — this is the one
    real addition beyond every other thin reporting view in this
    file, kept as an explicit, separate call rather than folded
    silently into reports.general_ledger() itself, since that
    function's own job is computing ledger data, not resolving
    cross-app references back to source documents.
    """

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        account_code = request.query_params.get("account")
        if not account_code:
            return Response(
                {"success": False, "message": "Parameter 'account' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        since = _parse_date(request.query_params.get("since"))
        as_of = _parse_date(request.query_params.get("as_of"), default=date.today())

        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(max(int(request.query_params.get("page_size", 50)), 1), 200)
        except (TypeError, ValueError):
            return Response(
                {"success": False, "message": "Parameter page/page_size tidak valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = reports.general_ledger(
                organization, account_code=account_code, since=since, as_of=as_of,
                page=page, page_size=page_size,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        trace_forward.resolve_references(data["rows"])
        return Response({"success": True, **data})


class DailyCashActivityView(TenantScopedAPIView):
    """
    GET /api/accounting/daily-cash-activity/?date=YYYY-MM-DD
    1 Sep 2026 — Kas Harian. A single-DAY snapshot, not a range —
    `date` defaults to today, same "no `since`" shape as
    DashboardFinancialSummaryView above. Purpose-built for the
    /dashboard/accounting/kas-harian page and the Ringkasan "Kas
    Hari Ini" card; deliberately separate from JournalEntryListView
    — that view is the full audit-grade Jurnal page (every source,
    every event type, date-range filterable); this one is the
    friendly, Cash/Bank-only, single-day lens reports.py's own
    daily_cash_activity() builds specifically for a shop owner.
    """

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        on_date = _parse_date(request.query_params.get("date"), default=date.today())
        data = reports.daily_cash_activity(organization, on_date=on_date)
        return Response({"success": True, **data})


_CONTROL_ACCOUNT_CODES = {"1201", "2001"}


class ManualJournalListCreateView(TenantScopedAPIView):
    """
    GET  /api/accounting/manual-journals/  — every manual journal for this org
    POST /api/accounting/manual-journals/  — post a new one

    POST restricted to the org's owner. Uses the now-shared
    JournalEntrySerializer (Task 5.2 rename) rather than a
    manual-only copy.
    """
    model = JournalEntry

    def get(self, request):
        entries = (
            self.get_queryset()
            .filter(source=JournalEntry.Source.MANUAL)
            .prefetch_related("lines__account")
            .select_related("created_by")
        )
        return Response({"success": True, "manual_journals": JournalEntrySerializer(entries, many=True).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _require_owner(request, organization):
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa memposting jurnal manual."},
                status=status.HTTP_403_FORBIDDEN,
            )

        input_serializer = ManualJournalRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        lines = []
        control_accounts_touched = set()
        for line in data["lines"]:
            try:
                account = Account.resolve(organization, line["account_code"])
            except ValueError as e:
                return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            if account.code in _CONTROL_ACCOUNT_CODES:
                control_accounts_touched.add(account.code)
            lines.append({"account": account, "debit": line.get("debit"), "credit": line.get("credit")})

        try:
            entry = JournalEntry.post(
                organization=organization,
                posting_date=data["posting_date"],
                source=JournalEntry.Source.MANUAL,
                memo=data["reason"],
                created_by=request.user,
                lines=lines,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_data = {"success": True, "manual_journal": JournalEntrySerializer(entry).data}
        if control_accounts_touched:
            response_data["warning"] = (
                f"Jurnal ini menyentuh akun kontrol ({', '.join(sorted(control_accounts_touched))}) "
                f"secara langsung — pastikan ini disengaja, karena saldo akun ini seharusnya selalu "
                f"sama dengan total sub-ledger (Invoice/SupplierInvoice) terkait."
            )
        return Response(response_data, status=status.HTTP_201_CREATED)


class JournalEntryListView(TenantScopedAPIView):
    """
    GET /api/accounting/journal-entries/?source=&since=&as_of=
    Task 5.2 — every real posted JournalEntry for this org, both
    sources, filterable. The general case
    ManualJournalListCreateView.get() only ever covered the
    MANUAL-only slice.
    """
    model = JournalEntry

    def get(self, request):
        entries = self.get_queryset().prefetch_related("lines__account").select_related("created_by")

        source = request.query_params.get("source")
        if source in (JournalEntry.Source.MANUAL, JournalEntry.Source.DOMAIN_EVENT):
            entries = entries.filter(source=source)

        since = request.query_params.get("since")
        if since:
            entries = entries.filter(posting_date__gte=since)
        as_of = request.query_params.get("as_of")
        if as_of:
            entries = entries.filter(posting_date__lte=as_of)

        entries = entries.order_by("-posting_date", "-entry_number")
        return Response({"success": True, "journal_entries": JournalEntrySerializer(entries, many=True).data})


class JournalEntryDetailView(TenantScopedAPIView):
    """
    GET /api/accounting/journal-entries/<uuid:pk>/

    4 Sep 2026 — the real, missing single-entry detail endpoint Buku
    Besar's own inline row expansion needs (mirroring the Journal
    page's own existing expand pattern, not a new drawer paradigm —
    see that design conversation for the full reasoning).
    general_ledger()'s own row shape deliberately carries only the
    ONE line touching the specific account being viewed, never every
    line on the entry — this is what fetches the real, full, balanced
    entry by its real id. Reuses JournalEntrySerializer as-is — it
    already nests every line via "lines", the exact same shape
    JournalEntryListView/ManualJournalListCreateView.get() already
    return; no second serializer invented for this one view.
    """
    model = JournalEntry

    def get(self, request, pk):
        entry = (
            self.get_queryset()
            .filter(pk=pk)
            .prefetch_related("lines__account")
            .select_related("created_by")
            .first()
        )
        if entry is None:
            return Response(
                {"success": False, "message": "Entri jurnal tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "journal_entry": JournalEntrySerializer(entry).data})


class FailedPostingsView(TenantScopedAPIView):
    """
    GET /api/accounting/failed-postings/?since=&as_of=
    Task 5.2 — the real point of this task. A failed domain-event
    posting never produces a JournalEntry (that's what "failed"
    means) — the only trace is an Outbox row with status=FAILED.
    Gives a shop owner a real way to SEE that, instead of discovering
    it because a report looks wrong.

    since/as_of filter on occurred_at's own DATE component —
    occurred_at is a real DateTimeField, not a plain date, so this
    uses __date__gte/__date__lte rather than a naive comparison.
    """
    model = Outbox

    def get(self, request):
        failures = self.get_queryset().filter(status=Outbox.Status.FAILED)

        since = request.query_params.get("since")
        if since:
            failures = failures.filter(occurred_at__date__gte=since)
        as_of = request.query_params.get("as_of")
        if as_of:
            failures = failures.filter(occurred_at__date__lte=as_of)

        failures = failures.order_by("-occurred_at")
        return Response({"success": True, "failed_postings": FailedPostingSerializer(failures, many=True).data})


class AccountingPeriodListView(TenantScopedAPIView):
    """
    GET /api/accounting/periods/
    28 Aug 2026 — every real AccountingPeriod for this org, newest
    first. The real data source for the period-control UI (Sansan's
    own 3-button diagram) — a real shop owner needs to see every
    month's own open/closed/locked state at a glance before deciding
    which one to close.
    """
    model = AccountingPeriod

    def get(self, request):
        periods = (
            self.get_queryset()
            .select_related("closed_by", "reopened_by")
            .order_by("-year", "-month")
        )
        return Response({"success": True, "periods": AccountingPeriodSerializer(periods, many=True).data})


class AccountingPeriodCloseView(TenantScopedAPIView):
    """
    POST /api/accounting/periods/<id>/close/
    Owner-only — Made's own confirmed requirement. Same authorization
    split as ManualJournalListCreateView.post(): this view enforces
    WHO can call it, period.close() itself enforces WHETHER it's
    allowed to happen at all (the real hard guard against
    re-closing).
    """
    model = AccountingPeriod

    def post(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _require_owner(request, organization):
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa menutup periode akuntansi."},
                status=status.HTTP_403_FORBIDDEN,
            )

        period = self.get_object(pk)
        try:
            closing_entry, net_income = period.close(closed_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "period": AccountingPeriodSerializer(period).data,
            "net_income": net_income,
            "closing_entry": JournalEntrySerializer(closing_entry).data if closing_entry else None,
        })


class AccountingPeriodReopenView(TenantScopedAPIView):
    """
    POST /api/accounting/periods/<id>/reopen/
    Same owner-only gate as close() — Made's own confirmed
    requirement ("heavily guarded, owner-only"). period.reopen()
    itself enforces the real state check (must currently be closed).
    """
    model = AccountingPeriod

    def post(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _require_owner(request, organization):
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa membuka kembali periode akuntansi."},
                status=status.HTTP_403_FORBIDDEN,
            )

        period = self.get_object(pk)
        try:
            period.reopen(reopened_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"success": True, "period": AccountingPeriodSerializer(period).data})


class AssetListCreateView(TenantScopedAPIView):
    """
    GET  /api/accounting/assets/  — every real fixed asset for this org
    POST /api/accounting/assets/  — record a new one

    29 Aug 2026 — real fixed asset register, Made's own confirmed
    request. All real logic — including the real acquisition
    journal entry, posted in the same transaction — lives in
    Asset.record(); this view is thin, same discipline as every
    other real write path in this codebase.
    """
    model = Asset

    def get(self, request):
        assets = self.get_queryset().order_by("-acquisition_date")
        return Response({"success": True, "assets": AssetSerializer(assets, many=True).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = AssetRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            asset = Asset.record(
                organization=organization, name=data["name"],
                acquisition_date=data["acquisition_date"], cost=data["cost"],
                useful_life_months=data["useful_life_months"], method=data.get("method", "cash"),
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "asset": AssetSerializer(asset).data},
            status=status.HTTP_201_CREATED,
        )


class DepreciationRunDetailView(TenantScopedAPIView):
    """
    GET /api/accounting/periods/<period_id>/depreciation-run/

    29 Aug 2026 — surfaces the itemized per-asset breakdown for one
    period's own DepreciationRun (Chris's own confirmed granularity
    call: one consolidated Dr 6004 / Cr 1402 entry on the Jurnal
    page, but a real, retrievable breakdown underneath — this is
    that underneath). Returns depreciation_run: null (not a 404)
    when no run exists yet for this period — a real, honest "hasn't
    been closed yet" state, not an error.
    """
    model = DepreciationRun

    def get(self, request, period_id):
        run = (
            self.get_queryset()
            .filter(accounting_period_id=period_id)
            .prefetch_related("entries__asset")
            .first()
        )
        if run is None:
            return Response({"success": True, "depreciation_run": None})
        return Response({"success": True, "depreciation_run": DepreciationRunSerializer(run).data})


# =============================================================================
# Opening Balance — new-workshop onboarding (3 Sep 2026)
# =============================================================================

def _get_draft_session_or_response(organization):
    """
    Shared helper for every line-item endpoint below — resolves the
    org's one real OpeningBalanceSession and confirms it's still
    DRAFT (line items can never be added/removed once POSTED — as
    immutable as any other posted history in this codebase). Returns
    (session, None) on success, or (None, Response) with the real
    error already built — callers do:

        session, error = _get_draft_session_or_response(organization)
        if error:
            return error
    """
    session = OpeningBalanceSession.objects.filter(organization=organization).first()
    if session is None:
        return None, Response(
            {"success": False, "message": "Sesi saldo awal belum dibuat — buat sesi terlebih dahulu."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if session.status != OpeningBalanceSession.Status.DRAFT:
        return None, Response(
            {"success": False, "message": "Sesi saldo awal ini sudah diposting — tidak bisa diubah lagi."},
            status=status.HTTP_409_CONFLICT,
        )
    return session, None


class OpeningBalanceSessionView(TenantScopedAPIView):
    """
    GET  /api/accounting/opening-balance/  — the org's one real
         session, fully nested with every line item across all six
         categories plus live total_debit/total_credit/is_balanced —
         returns opening_balance_session: null (not a 404) when none
         exists yet, same real, honest "hasn't happened yet" state
         DepreciationRunDetailView's own null response already
         establishes above.
    POST /api/accounting/opening-balance/  — creates the org's one
         real session (start_date only — every line item is added
         afterward via its own endpoint below). Owner-only — this
         establishes the entire accounting foundation for the shop,
         same real stakes as closing a period.

    prefetch_related() on GET covers all six line-item relations
    (plus customer/supplier for the two categories that need a
    real name) — required so OpeningBalanceSessionSerializer's own
    total_debit/total_credit computation doesn't N+1 query; see that
    serializer's own docstring for why this is explicitly the view's
    job, not something the serializer can own itself.
    """
    model = OpeningBalanceSession

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session = (
            OpeningBalanceSession.objects
            .filter(organization=organization)
            .prefetch_related(
                "cash_lines", "part_lines", "asset_lines",
                "receivable_lines__customer", "payable_lines__supplier", "other_lines",
            )
            .first()
        )
        if session is None:
            return Response({"success": True, "opening_balance_session": None})
        return Response({"success": True, "opening_balance_session": OpeningBalanceSessionSerializer(session).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _require_owner(request, organization):
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa memulai sesi saldo awal."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if OpeningBalanceSession.objects.filter(organization=organization).exists():
            return Response(
                {"success": False, "message": "Sesi saldo awal untuk organisasi ini sudah pernah dibuat."},
                status=status.HTTP_409_CONFLICT,
            )

        input_serializer = OpeningBalanceSessionRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        session = OpeningBalanceSession.objects.create(
            organization=organization, start_date=data["start_date"], created_by=request.user,
        )
        return Response(
            {"success": True, "opening_balance_session": OpeningBalanceSessionSerializer(session).data},
            status=status.HTTP_201_CREATED,
        )


class OpeningBalancePostView(TenantScopedAPIView):
    """
    POST /api/accounting/opening-balance/post/
    The real, final, irreversible action — owner-only, same stakes
    as AccountingPeriodCloseView. All real logic lives in
    OpeningBalanceSession.post() itself (models.py) — this view is
    thin, same discipline as every other real write path here.
    """
    model = OpeningBalanceSession

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _require_owner(request, organization):
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa memposting saldo awal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        session = OpeningBalanceSession.objects.filter(organization=organization).first()
        if session is None:
            return Response(
                {"success": False, "message": "Sesi saldo awal belum dibuat."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            session.post(posted_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        session.refresh_from_db()
        return Response({"success": True, "opening_balance_session": OpeningBalanceSessionSerializer(session).data})


class OpeningBalanceCashLineView(TenantScopedAPIView):
    """
    PUT /api/accounting/opening-balance/cash/
    Real upsert, not create — mirrors SupplierPartCode.set_code()'s
    own real update_or_create precedent, matching the model's own
    unique_together(session, account_code): a second PUT for the
    same account_code updates the existing amount rather than
    erroring or silently creating a duplicate row.
    """
    model = OpeningBalanceCashLine

    def put(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        input_serializer = OpeningBalanceCashLineRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        line, _ = OpeningBalanceCashLine.objects.update_or_create(
            organization=organization, session=session, account_code=data["account_code"],
            defaults={"amount": data["amount"]},
        )
        return Response({"success": True, "cash_line": OpeningBalanceCashLineSerializer(line).data})


class OpeningBalancePartLineListCreateView(TenantScopedAPIView):
    """POST /api/accounting/opening-balance/parts/ — add one itemized opening-stock line."""
    model = OpeningBalancePartLine

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        input_serializer = OpeningBalancePartLineRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        line = OpeningBalancePartLine.objects.create(
            organization=organization, session=session,
            part_name=data["part_name"], sku=data.get("sku", ""), unit=data.get("unit", "pcs"),
            quantity=data["quantity"], cost_price=data["cost_price"],
        )
        return Response(
            {"success": True, "part_line": OpeningBalancePartLineSerializer(line).data},
            status=status.HTTP_201_CREATED,
        )


class OpeningBalancePartLineDetailView(TenantScopedAPIView):
    """
    DELETE /api/accounting/opening-balance/parts/<pk>/ — remove one
    line while the session is still DRAFT. Looked up via a direct,
    self-contained queryset filter (organization + session scoped)
    rather than self.get_object(pk) — deliberate: this codebase's
    real get_object() behavior on a miss (None vs. raising Http404)
    wasn't available to verify while writing this, so a directly
    controlled lookup is the safer choice here.
    """
    model = OpeningBalancePartLine

    def delete(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        line = OpeningBalancePartLine.objects.filter(organization=organization, session=session, pk=pk).first()
        if line is None:
            return Response({"success": False, "message": "Baris tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        line.delete()
        return Response({"success": True})


class OpeningBalanceAssetLineListCreateView(TenantScopedAPIView):
    """POST /api/accounting/opening-balance/assets/ — add one legacy fixed-asset line."""
    model = OpeningBalanceAssetLine

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        input_serializer = OpeningBalanceAssetLineRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        line = OpeningBalanceAssetLine.objects.create(
            organization=organization, session=session, name=data["name"],
            current_book_value=data["current_book_value"],
            remaining_useful_life_months=data["remaining_useful_life_months"],
        )
        return Response(
            {"success": True, "asset_line": OpeningBalanceAssetLineSerializer(line).data},
            status=status.HTTP_201_CREATED,
        )


class OpeningBalanceAssetLineDetailView(TenantScopedAPIView):
    """DELETE /api/accounting/opening-balance/assets/<pk>/ — same shape as the Part detail view above."""
    model = OpeningBalanceAssetLine

    def delete(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        line = OpeningBalanceAssetLine.objects.filter(organization=organization, session=session, pk=pk).first()
        if line is None:
            return Response({"success": False, "message": "Baris tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        line.delete()
        return Response({"success": True})


class OpeningBalanceReceivableListCreateView(TenantScopedAPIView):
    """
    POST /api/accounting/opening-balance/receivables/ — add one
    legacy customer receivable. customer is resolved against this
    org's own real Customer rows — never trusted as a bare
    cross-tenant lookup, same discipline as every other real FK
    resolution in this codebase.
    """
    model = OpeningBalanceReceivable

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        input_serializer = OpeningBalanceReceivableRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        from apps.service.models import Customer
        customer = Customer.objects.filter(organization=organization, pk=data["customer"]).first()
        if customer is None:
            return Response({"success": False, "message": "Pelanggan tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        line = OpeningBalanceReceivable.objects.create(
            organization=organization, session=session, customer=customer,
            balance_due=data["balance_due"], due_date=data.get("due_date"),
            reference=data.get("reference", ""),
        )
        return Response(
            {"success": True, "receivable_line": OpeningBalanceReceivableSerializer(line).data},
            status=status.HTTP_201_CREATED,
        )


class OpeningBalanceReceivableDetailView(TenantScopedAPIView):
    """DELETE /api/accounting/opening-balance/receivables/<pk>/"""
    model = OpeningBalanceReceivable

    def delete(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        line = OpeningBalanceReceivable.objects.filter(organization=organization, session=session, pk=pk).first()
        if line is None:
            return Response({"success": False, "message": "Baris tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        line.delete()
        return Response({"success": True})


class OpeningBalancePayableListCreateView(TenantScopedAPIView):
    """Mirrors OpeningBalanceReceivableListCreateView exactly, inverted for suppliers."""
    model = OpeningBalancePayable

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        input_serializer = OpeningBalancePayableRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        from apps.purchasing.models import Supplier
        supplier = Supplier.objects.filter(organization=organization, pk=data["supplier"]).first()
        if supplier is None:
            return Response({"success": False, "message": "Supplier tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        line = OpeningBalancePayable.objects.create(
            organization=organization, session=session, supplier=supplier,
            balance_due=data["balance_due"], due_date=data.get("due_date"),
            reference=data.get("reference", ""),
        )
        return Response(
            {"success": True, "payable_line": OpeningBalancePayableSerializer(line).data},
            status=status.HTTP_201_CREATED,
        )


class OpeningBalancePayableDetailView(TenantScopedAPIView):
    """DELETE /api/accounting/opening-balance/payables/<pk>/"""
    model = OpeningBalancePayable

    def delete(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        line = OpeningBalancePayable.objects.filter(organization=organization, session=session, pk=pk).first()
        if line is None:
            return Response({"success": False, "message": "Baris tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        line.delete()
        return Response({"success": True})


class OpeningBalanceOtherLineListCreateView(TenantScopedAPIView):
    """
    POST /api/accounting/opening-balance/other/ — the deliberate,
    honest escape hatch (Owner Capital itself lands here, along with
    Loans, Tax Payable, or any other non-itemizable category).
    account_code is NOT validated against a real Account at this
    layer — same "collect first, validate everything together at
    post() time" shape as the model's own OpeningBalanceOtherLine
    docstring establishes; a genuinely invalid code only ever
    surfaces as a real, clear error from
    OpeningBalanceSession.post() itself.
    """
    model = OpeningBalanceOtherLine

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        input_serializer = OpeningBalanceOtherLineRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        line = OpeningBalanceOtherLine.objects.create(
            organization=organization, session=session, account_code=data["account_code"],
            side=data["side"], amount=data["amount"], description=data.get("description", ""),
        )
        return Response(
            {"success": True, "other_line": OpeningBalanceOtherLineSerializer(line).data},
            status=status.HTTP_201_CREATED,
        )


class OpeningBalanceOtherLineDetailView(TenantScopedAPIView):
    """DELETE /api/accounting/opening-balance/other/<pk>/"""
    model = OpeningBalanceOtherLine

    def delete(self, request, pk):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        session, error = _get_draft_session_or_response(organization)
        if error:
            return error

        line = OpeningBalanceOtherLine.objects.filter(organization=organization, session=session, pk=pk).first()
        if line is None:
            return Response({"success": False, "message": "Baris tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        line.delete()
        return Response({"success": True})
