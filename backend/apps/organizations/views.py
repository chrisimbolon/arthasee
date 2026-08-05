# =============================================================================
# === backend/apps/organizations/views.py ===
# =============================================================================
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (OrganizationSerializer,
                          OrganizationSettingsUpdateSerializer)


class MyOrganizationView(APIView):
    """
    GET/PATCH /api/organizations/mine/ — the current user's shop.

    PATCH added 5 Aug — real Organization Settings, letting an owner
    customize the auto-generated invoice_code (and shop display name)
    any time, rather than being stuck with whatever
    Organization._generate_invoice_code() produced at signup. See
    that method's own docstring for why registration itself never
    asks for this field at all.
    """
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

    def patch(self, request):
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Real role check — shop-wide settings like the invoice
        # prefix must only ever be changeable by the actual owner,
        # not any staff member who happens to hold a membership row.
        if membership.role != "owner":
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa mengubah pengaturan ini."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = OrganizationSettingsUpdateSerializer(
            membership.organization, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "success":      True,
            "organization": OrganizationSerializer(membership.organization).data,
        })
