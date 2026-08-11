# =============================================================================
# === backend/apps/analytics/views.py ===
# =============================================================================
"""
Arthasee — Analytics Views

Thin on purpose — same discipline as apps.accounting.views: resolve
the acting organization, parse the one real query param (months),
call the matching function in growth.py, return the result.
"""
from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from . import growth


def _parse_months(request, default=12, minimum=1, maximum=36):
    raw = request.query_params.get("months")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


class RevenueTrendView(TenantScopedAPIView):
    """GET /api/analytics/revenue-trend/?months=12"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = growth.revenue_trend(organization, months=_parse_months(request))
        return Response({"success": True, **data})


class MechanicUtilizationView(TenantScopedAPIView):
    """GET /api/analytics/mechanic-utilization/"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = growth.mechanic_utilization(organization)
        return Response({"success": True, **data})


class WorkOrderQueueStatusView(TenantScopedAPIView):
    """GET /api/analytics/queue-status/"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = growth.work_order_queue_status(organization)
        return Response({"success": True, **data})


class JobVolumeTrendView(TenantScopedAPIView):
    """GET /api/analytics/job-volume-trend/?months=12"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        months = _parse_months(request)
        data = growth.job_volume_trend(organization, months=months)
        return Response({"success": True, "months": data})


class CustomerGrowthTrendView(TenantScopedAPIView):
    """GET /api/analytics/customer-growth-trend/?months=12"""

    def get(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = growth.customer_growth_trend(organization, months=_parse_months(request))
        return Response({"success": True, **data})
