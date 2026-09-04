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

    3 Sep 2026 — this is now ALSO the real save path for onboarding's
    own Step 1 (phone/address/invoice_code) — see
    OrganizationOnboardingCompleteView's own docstring below for why
    that responsibility moved here.
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


class OrganizationOnboardingCompleteView(APIView):
    """
    POST /api/organizations/mine/complete-onboarding/ — no payload.

    3 Sep 2026 — REDESIGNED for the Opening Balance wizard becoming a
    real, mandatory Step 2 after the profile step (Chris's own
    confirmed direction). Previously this single call both saved
    phone/address/invoice_code AND flipped onboarding_completed —
    correct for a one-step gate, but a real gap once a genuine Step 2
    existed: a browser refresh mid-Step-2 would have nothing
    persisted to tell the gate "Step 1 is already done, skip straight
    to Step 2" — it would just re-show Step 1 from scratch, or worse,
    with the OLD contract, there was no Step 2 to return to at all.

    Real fix: Step 1 now saves phone/address/invoice_code via the
    existing, plain MyOrganizationView.patch() path (through
    OrganizationSettingsUpdateSerializer, already proven, no new
    serializer needed) — WITHOUT touching onboarding_completed. This
    endpoint's only remaining job is the final, explicit flag flip,
    guarded by a real check that Step 1's own data genuinely exists
    first. Called identically from BOTH of Step 2's real exit paths
    (a posted OpeningBalanceSession, or the "Bengkel Baru — Mulai
    dari Nol" path for a shop with no prior history) — which path
    happened is entirely orthogonal to this call; neither passes a
    payload, and neither needs to.

    OnboardingCompleteSerializer is now dead code, removed — its one
    real job (require + save phone/address/invoice_code in the same
    call as the flag flip) no longer matches how this flow works.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.role != "owner":
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa menyelesaikan pengaturan awal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        org = membership.organization
        # Real, server-side guard — not just trusted from frontend
        # step ordering. A Step 2 call arriving with Step 1's own
        # data genuinely missing (e.g. a stray direct API call, or a
        # future frontend bug skipping straight to Step 2) must never
        # silently complete onboarding for a shop with no real
        # profile on record — same "a real business rule deserves a
        # real server-side guarantee" reasoning the original 29 Aug
        # design already established for this exact endpoint.
        if not (org.phone and org.address and org.invoice_code):
            return Response(
                {"success": False, "message": "Lengkapi profil bengkel (Langkah 1) terlebih dahulu."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        org.onboarding_completed = True
        org.save(update_fields=["onboarding_completed"])
        return Response({
            "success":      True,
            "organization": OrganizationSerializer(org).data,
        })
