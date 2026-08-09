# =============================================================================
# === backend/apps/accounting/views.py ===
# =============================================================================
"""
Arthasee — Financial Reporting Views (Task 4.1)

Thin on purpose — every view here does exactly three things: resolve
the acting organization, parse query params into real dates, call the
matching function in reports.py. All the actual accounting logic
lives there, not here, same division of responsibility as every
other *View/*.record() pair in this codebase.
"""
from datetime import date

from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from . import reports


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
