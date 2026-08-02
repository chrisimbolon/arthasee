# =============================================================================
# === backend/apps/customers/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from apps.workorders.models import WorkOrder
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TrackingLink
from .serializers import PublicTrackingSerializer, TrackingLinkSerializer

# Mirrors WorkOrder.STATUS_CHOICES' own labels — duplicated rather
# than imported, since this is customer-facing copy and the two are
# allowed to diverge on wording without that being a bug (e.g. if
# Made ever wants friendlier public-facing status text later).
STATUS_LABEL = {
    "OPEN": "Terbuka", "IN_PROGRESS": "Dikerjakan", "QC": "Pemeriksaan Kualitas",
    "DONE": "Selesai", "CANCELLED": "Dibatalkan",
}


class TrackingLinkListView(TenantScopedAPIView):
    """
    GET/POST /api/work-orders/<work_order_id>/tracking-links/
    Internal, authenticated — Made/SA generates a link here, then
    copies it into WhatsApp by hand. Deliberately manual, matching
    the same "no automated sending" discipline already established
    for Estimasi/Invoice PDF downloads — B3 (automated WhatsApp) is
    still on hold.
    """
    model = TrackingLink

    def get(self, request, work_order_id):
        links = self.get_queryset().filter(work_order_id=work_order_id)
        return Response({"success": True, "results": TrackingLinkSerializer(links, many=True).data})

    def post(self, request, work_order_id):
        work_order = get_object_or_404(WorkOrder, pk=work_order_id)
        # Same tenant-scoping discipline as everywhere else — a user
        # from a different org must never be able to mint a tracking
        # link for a WorkOrder they can't even see.
        if request.user.role != "super_admin":
            org_ids = request.user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            if work_order.organization_id not in org_ids:
                return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        link = TrackingLink.objects.create(
            organization=work_order.organization, work_order=work_order, created_by=request.user,
        )
        return Response({"success": True, "tracking_link": TrackingLinkSerializer(link).data}, status=status.HTTP_201_CREATED)


class TrackingLinkRevokeView(TenantScopedAPIView):
    """POST /api/tracking-links/<id>/revoke/ — leaked link, wrong
    person, contract ended, whatever the real reason. The WorkOrder
    itself is never touched; only this one link stops working."""
    model = TrackingLink

    def post(self, request, pk):
        link = self.get_object(pk)
        link.is_revoked = True
        link.save(update_fields=["is_revoked"])
        return Response({"success": True, "tracking_link": TrackingLinkSerializer(link).data})


class PublicTrackingView(APIView):
    """
    GET /api/track/<token>/

    The ONLY unauthenticated endpoint in this entire codebase. Every
    other view in this project assumes a real, logged-in CustomUser;
    this one deliberately doesn't, since the entire point of Fase 2
    v1 is zero-login tracking. AllowAny is safe here specifically
    BECAUSE this view returns a hand-built, whitelisted payload (see
    PublicTrackingSerializer) rather than ever serializing a real
    model instance wholesale — there's no path for an internal-only
    field to leak here just by existing on WorkOrder/Vehicle/Invoice.
    """
    permission_classes = [AllowAny]

    def get(self, request, token):
        link = TrackingLink.objects.filter(token=token, is_revoked=False).select_related(
            "work_order__vehicle", "work_order__assigned_to",
        ).first()
        if link is None:
            # Deliberately the same generic message whether the token
            # never existed or was revoked — a public endpoint must
            # never confirm or deny which case it is.
            return Response(
                {"success": False, "message": "Link tidak ditemukan atau sudah tidak berlaku."},
                status=status.HTTP_404_NOT_FOUND,
            )

        link.record_view()
        work_order = link.work_order
        vehicle = work_order.vehicle

        # getattr probe, same pattern already proven throughout this
        # codebase (WorkOrder.mark_started(), Invoice.save()'s own
        # mechanic lookup) — a reverse OneToOneField raises
        # RelatedObjectDoesNotExist rather than returning None when
        # nothing points back to it.
        service_record = getattr(work_order, "service_record", None)
        invoice = getattr(service_record, "invoice", None) if service_record else None

        invoice_payload = None
        # Chris's own explicit scope call, 2 Aug: only shown once the
        # job is genuinely DONE and a real invoice exists — never a
        # mid-repair estimate, and never any contract/termin
        # financials (institutional clients pay via TerminPeriod
        # schedules, not a flat invoice — showing this here would be
        # confusing or simply wrong against their real payment plan).
        if work_order.status == "DONE" and invoice is not None:
            invoice_payload = {
                "number": invoice.number,
                "mechanic_name_snapshot": invoice.mechanic_name_snapshot,
                "total": invoice.total,
                "status": invoice.get_status_display(),
            }

        payload = {
            "work_order_number": work_order.number,
            "status": STATUS_LABEL.get(work_order.status, work_order.status),
            "vehicle_plate": vehicle.plate_number,
            "vehicle_model": vehicle.model,
            "mechanic_name": work_order.assigned_to.name if work_order.assigned_to_id else None,
            "stages": list(work_order.stages.order_by("sequence").all()),
            "invoice": invoice_payload,
        }
        return Response({"success": True, "tracking": PublicTrackingSerializer(payload).data})
