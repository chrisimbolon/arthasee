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
of Task 5.2).
"""
from datetime import date

from apps.core.models import Outbox
from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from . import reports
from .models import Account, JournalEntry
from .serializers import (FailedPostingSerializer, JournalEntrySerializer,
                          ManualJournalRecordSerializer)


def _parse_date(value, default=None):
    if not value:
        return default
    return date.fromisoformat(value)


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
            from apps.accounting.models import AccountingPeriod
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
            from apps.accounting.models import AccountingPeriod
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

        membership = request.user.memberships.filter(organization=organization, is_active=True).first()
        if membership is None or membership.role != "owner":
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
