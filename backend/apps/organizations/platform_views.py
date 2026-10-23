# =============================================================================
# === backend/apps/organizations/platform_views.py ===
# =============================================================================
"""
GET /api/platform/overview/ — the super admin's read-only health view of
every shop (Phase 22, 24 Oct 2026). See platform_health.py for what is
computed and the privacy rule.

Deliberately NOT a TenantScopedAPIView: this is the one endpoint whose
whole job is to look across shops, and it is gated on the role itself
(IsSuperAdmin) instead of on memberships. Read-only: GET only.
"""
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .platform_health import platform_overview


class IsSuperAdmin(BasePermission):
    message = "Halaman ini hanya untuk super admin platform."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "role", None) == "super_admin")


class PlatformOverviewView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        return Response({"success": True, **platform_overview()})
