# =============================================================================
# === backend/apps/letters/views.py ===
# =============================================================================
"""
Corrected 6 Aug after seeing the real apps.core.views.TenantScopedAPIView
— simpler than assumed: get_queryset() (scoped across every org the
user is an active member of) + get_object(), nothing more. List views
below now properly extend TenantScopedAPIView like everything else in
this codebase, instead of the manual membership-lookup workaround
used before I had this file in front of me.

_get_active_organization() is kept for CREATE only — TenantScopedAPIView
has no equivalent for resolving which SINGLE organization a new row
should belong to (its own get_queryset() deliberately spans every org
a user belongs to, correct for reading, but a POST still needs one
real answer). Mirrors the exact same first-active-membership pattern
already used in the one view I have direct, confirmed source for —
MyOrganizationView.
"""
from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from .models import IncomingLetter, OutgoingLetter
from .serializers import (IncomingLetterSerializer,
                          OutgoingLetterCreateSerializer,
                          OutgoingLetterSerializer)


def _get_active_organization(request):
    membership = request.user.memberships.filter(
        is_active=True
    ).select_related("organization").first()
    return membership.organization if membership else None


class OutgoingLetterListView(TenantScopedAPIView):
    """GET /api/letters/outgoing/ — list, properly scoped via the
    real TenantScopedAPIView.get_queryset(). POST — the standalone
    "Buat Surat" path, Chris's own confirmed shape: recipient/subject
    only, source hard-set to STANDALONE server-side, never
    client-settable."""
    model = OutgoingLetter

    def get(self, request):
        letters = self.get_queryset()
        return Response({"success": True, "letters": OutgoingLetterSerializer(letters, many=True).data})

    def post(self, request):
        org = _get_active_organization(request)
        if org is None:
            return Response({"success": False, "message": "Anda belum tergabung dalam bengkel manapun."}, status=status.HTTP_404_NOT_FOUND)
        if not org.invoice_code:
            # Same real, loud-failure discipline as Invoice.save()'s
            # own check — a Surat Keluar number embeds the shop's
            # invoice_code exactly the way Made's real example does,
            # so the same missing-code failure mode applies here too.
            return Response(
                {"success": False, "message": f"'{org.name}' belum memiliki kode invoice — atur di Pengaturan Bengkel sebelum membuat surat."},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = OutgoingLetterCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        letter = serializer.save(organization=org, source="STANDALONE", created_by=request.user)
        return Response(
            {"success": True, "letter": OutgoingLetterSerializer(letter).data},
            status=status.HTTP_201_CREATED,
        )


class OutgoingLetterDetailView(TenantScopedAPIView):
    """GET /api/letters/outgoing/<id>/"""
    model = OutgoingLetter

    def get(self, request, pk):
        letter = self.get_object(pk)
        return Response({"success": True, "letter": OutgoingLetterSerializer(letter).data})


class IncomingLetterListView(TenantScopedAPIView):
    """GET /api/letters/incoming/ — list, newest received first,
    properly scoped via get_queryset(). Optional ?vehicle=<id> filter
    — Made's own explicit ask: a linked letter should surface
    directly in that vehicle's own history, not just live in a
    separate mailroom list a real click away. Frontend uses this on
    vehicle-detail rather than fetching every incoming letter in the
    org and filtering client-side. POST — upload + metadata, Made's
    own confirmed "not a blind file drop" shape."""
    model = IncomingLetter

    def get(self, request):
        letters = self.get_queryset().select_related("customer", "vehicle").order_by("-received_date", "-created_at")
        vehicle_id = request.query_params.get("vehicle")
        if vehicle_id:
            letters = letters.filter(vehicle_id=vehicle_id)
        return Response({"success": True, "letters": IncomingLetterSerializer(letters, many=True).data})

    def post(self, request):
        org = _get_active_organization(request)
        if org is None:
            return Response({"success": False, "message": "Anda belum tergabung dalam bengkel manapun."}, status=status.HTTP_404_NOT_FOUND)
        serializer = IncomingLetterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        letter = serializer.save(organization=org, created_by=request.user)
        return Response(
            {"success": True, "letter": IncomingLetterSerializer(letter).data},
            status=status.HTTP_201_CREATED,
        )


class IncomingLetterDetailView(TenantScopedAPIView):
    """GET /api/letters/incoming/<id>/"""
    model = IncomingLetter

    def get(self, request, pk):
        letter = self.get_object(pk)
        return Response({"success": True, "letter": IncomingLetterSerializer(letter).data})
