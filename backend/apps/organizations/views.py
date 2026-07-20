# =============================================================================
# === backend/apps/organizations/views.py ===
# =============================================================================
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import OrganizationSerializer


class MyOrganizationView(APIView):
    """GET /api/organizations/mine/ — the current user's shop."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({
            "success":      True,
            "organization": OrganizationSerializer(membership.organization).data,
            "role":         membership.role,
        })
