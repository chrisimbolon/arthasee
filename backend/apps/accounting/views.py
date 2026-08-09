# =============================================================================
# === backend/apps/accounting/views.py ===
# =============================================================================
"""
Arthasee — Accounting Views

Two genuinely different kinds of endpoint in this file now: the five
Task 4.1 reporting views (thin — parse params, call reports.py,
return the result) and Task 4.4's manual journal view (the first real
WRITE path this app exposes over HTTP, hence real input validation
via serializers.py and a real authorization check, unlike the
read-only reports above it).
"""
from datetime import date

from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from . import reports
from .models import Account, JournalEntry
from .serializers import (ManualJournalEntrySerializer,
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
    GET /api/accounting/profit-loss/?since=YYYY-MM-DD&as_of=YYYY-MM-DD

    since defaults to the start of the current AccountingPeriod
    covering as_of (Task 4.3's own concept) — ties this report to the
    same real period notion rather than requiring every caller to
    always specify a range by hand. Falls back to Jan 1 of as_of's
    year if no period is found for that date.
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

        data = reports.profit_and_loss(organization, since=since, as_of=as_of)
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


# Manual journals may legitimately touch these — real accounting
# judgment call, not always wrong (a manual AR write-off is a genuine
# real-world case) — but their balances are supposed to always match
# a real sub-ledger total (sum of Invoice.balance_due for 1201, sum
# of unpaid SupplierInvoice.amount for 2001). Touching them directly
# can silently break that invariant, so it's flagged, not blocked —
# Chris's own explicit call.
_CONTROL_ACCOUNT_CODES = {"1201", "2001"}


class ManualJournalListCreateView(TenantScopedAPIView):
    """
    GET  /api/accounting/manual-journals/  — every manual journal for this org
    POST /api/accounting/manual-journals/  — post a new one

    All the real posting logic (balance validation, period-lock
    enforcement — including Task 4.3's own locked-still-allows-manual
    rule) already lives in JournalEntry.post(source=MANUAL); this
    view's only real jobs are resolving account codes safely,
    checking who's allowed to do this, and surfacing the
    control-account warning.

    POST restricted to the org's owner — Chris's own explicit call:
    this is a genuinely powerful, books-altering capability (arbitrary
    debits/credits by account code), unlike everything else in this
    codebase, which is triggered by a real business event. Same gate
    apps.organizations.views.MyOrganizationView.patch() already uses
    for its own sensitive action — checked the exact same way
    (membership.role != "owner"), not a new or looser rule.
    super_admin has no single "their" organization (see
    TenantScopedAPIView.get_organization()'s own docstring), so it's
    already rejected upstream, before this check ever runs.
    """
    model = JournalEntry

    def get(self, request):
        entries = (
            self.get_queryset()
            .filter(source=JournalEntry.Source.MANUAL)
            .prefetch_related("lines__account")
            .select_related("created_by")
        )
        return Response({"success": True, "manual_journals": ManualJournalEntrySerializer(entries, many=True).data})

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

        response_data = {"success": True, "manual_journal": ManualJournalEntrySerializer(entry).data}
        if control_accounts_touched:
            response_data["warning"] = (
                f"Jurnal ini menyentuh akun kontrol ({', '.join(sorted(control_accounts_touched))}) "
                f"secara langsung — pastikan ini disengaja, karena saldo akun ini seharusnya selalu "
                f"sama dengan total sub-ledger (Invoice/SupplierInvoice) terkait."
            )
        return Response(response_data, status=status.HTTP_201_CREATED)
