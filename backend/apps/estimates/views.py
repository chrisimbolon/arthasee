# =============================================================================
# === backend/apps/estimates/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from django.db import transaction
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from .models import Estimate, EstimateLineItem
from .pdf import build_quotation_pdf
from .serializers import EstimateLineItemSerializer, EstimateSerializer

OPEN_STATUS = "PENDING"


class EstimateListView(TenantScopedAPIView):
    """GET/POST /api/vehicles/<vehicle_id>/estimates/"""
    model = Estimate

    def get(self, request, vehicle_id):
        estimates = self.get_queryset().filter(vehicle_id=vehicle_id).select_related("vehicle__customer")
        serializer = EstimateSerializer(estimates, many=True)
        return Response({"success": True, "count": estimates.count(), "results": serializer.data})

    def post(self, request, vehicle_id):
        # Chris's own explicit ask, 1 Aug QA: a real gap surfaced live
        # on vehicle-detail — "Buat Estimasi" stayed enabled even
        # while a WorkOrder for the same vehicle was already
        # IN_PROGRESS, which let SA spin up a second, independent job
        # for a car already mid-repair. A second PENDING Estimate for
        # the same vehicle is the milder version of the identical
        # problem (Estimate.approve() would eventually create its own
        # second WorkOrder), so both are checked here, not just the
        # WorkOrder case. This is the real enforcement layer — the
        # frontend disables both buttons proactively too, but a slow
        # double-click or a second browser tab must still be caught
        # here, not just hidden in the UI.
        #
        # Local imports: apps.estimates has no other reason to depend
        # on apps.workorders at module level, matching the same
        # cross-app convention Estimate.approve() itself already
        # established (see models.py) rather than introducing a new
        # module-level dependency between the two apps.
        from apps.workorders.models import WorkOrder
        from apps.workorders.views import \
            OPEN_STATUSES as WORKORDER_OPEN_STATUSES

        if WorkOrder.objects.filter(vehicle_id=vehicle_id, status__in=WORKORDER_OPEN_STATUSES).exists():
            return Response(
                {"success": False, "message": "Kendaraan ini sedang dikerjakan — selesaikan atau batalkan work order aktifnya dulu sebelum membuat estimasi baru."},
                status=status.HTTP_409_CONFLICT,
            )
        if Estimate.objects.filter(vehicle_id=vehicle_id, status="PENDING").exists():
            return Response(
                {"success": False, "message": "Kendaraan ini sudah punya estimasi yang menunggu persetujuan."},
                status=status.HTTP_409_CONFLICT,
            )

        payload = dict(request.data)
        payload["vehicle"] = vehicle_id
        serializer = EstimateSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            # Estimate.save() calls EstimateSequence.next_number(),
            # which uses select_for_update() — that requires an
            # active transaction. Same exact gap that once slipped
            # through in WorkOrderListView.post() before it was
            # caught in production; wrapped here from the start this
            # time, though the regression test still caught it once
            # (see EstimateRealTransactionTests) because this specific
            # wrap was still missing on first pass.
            with transaction.atomic():
                estimate = serializer.save(created_by=request.user)
            return Response(
                {"success": True, "estimate": EstimateSerializer(estimate).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class EstimateDetailView(TenantScopedAPIView):
    """
    GET/PUT /api/estimates/<id>/
    PUT is narrow — only diagnosis_notes and odometer_km_intake, and
    only while PENDING. Approval/rejection go through their own
    dedicated endpoints, since those carry real, one-way side
    effects. odometer_km_intake's own hard-block validation (can't
    be less than Vehicle.last_service_odometer_km) lives in the
    serializer, not here — this view stays a thin pass-through.
    """
    model = Estimate

    def get(self, request, pk):
        estimate = self.get_object(pk)
        return Response({"success": True, "estimate": EstimateSerializer(estimate).data})

    def put(self, request, pk):
        estimate = self.get_object(pk)
        if estimate.status != OPEN_STATUS:
            return Response(
                {"success": False, "message": "Estimasi ini sudah diputuskan — tidak bisa diubah."},
                status=status.HTTP_409_CONFLICT,
            )
        allowed = {k: v for k, v in request.data.items() if k in ("diagnosis_notes", "odometer_km_intake")}
        serializer = EstimateSerializer(estimate, data=allowed, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "estimate": EstimateSerializer(estimate).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class EstimateApproveView(TenantScopedAPIView):
    """POST /api/estimates/<id>/approve/ — promotes into a real WorkOrder."""
    model = Estimate

    def post(self, request, pk):
        estimate = self.get_object(pk)
        try:
            estimate.approve(approved_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "estimate": EstimateSerializer(estimate).data})


class EstimateRejectView(TenantScopedAPIView):
    """POST /api/estimates/<id>/reject/ — records why, creates nothing downstream."""
    model = Estimate

    def post(self, request, pk):
        estimate = self.get_object(pk)
        reason = request.data.get("reason", "OTHER")
        notes = request.data.get("notes", "")
        try:
            estimate.reject(reason=reason, notes=notes)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "estimate": EstimateSerializer(estimate).data})


class EstimateLineItemListView(TenantScopedAPIView):
    """GET/POST /api/estimates/<estimate_id>/line-items/"""
    model = EstimateLineItem

    def get(self, request, estimate_id):
        lines = self.get_queryset().filter(estimate_id=estimate_id).select_related("part")
        serializer = EstimateLineItemSerializer(lines, many=True)
        return Response({"success": True, "count": lines.count(), "results": serializer.data})

    def post(self, request, estimate_id):
        estimate = self._get_estimate(request, estimate_id)
        if estimate is None:
            return Response({"success": False, "message": "Estimasi tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        if estimate.status != OPEN_STATUS:
            return Response(
                {"success": False, "message": "Estimasi ini sudah diputuskan."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = dict(request.data)
        payload["estimate"] = estimate_id
        serializer = EstimateLineItemSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            line = serializer.save()
            return Response(
                {"success": True, "line_item": EstimateLineItemSerializer(line).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_estimate(self, request, estimate_id):
        user = request.user
        if user.role == "super_admin":
            qs = Estimate.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = Estimate.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=estimate_id).first()


class EstimateLineItemDetailView(TenantScopedAPIView):
    """DELETE /api/estimates/line-items/<id>/ — only while the parent Estimate is PENDING."""
    model = EstimateLineItem

    def delete(self, request, pk):
        line = self.get_object(pk)
        if line.estimate.status != OPEN_STATUS:
            return Response(
                {"success": False, "message": "Estimasi ini sudah diputuskan — baris tidak bisa dihapus."},
                status=status.HTTP_409_CONFLICT,
            )
        line.delete()
        return Response({"success": True, "message": "Baris dihapus."})


class EstimateQuotationPdfView(TenantScopedAPIView):
    """
    GET /api/estimates/<id>/quotation.pdf
    Made's own urgent ask, 30 Jul follow-up meeting: SA/cashier need
    a real, downloadable PDF so they can forward it themselves via
    their own WhatsApp — deliberately NOT the same thing as the
    still-on-hold automated WhatsApp integration. This is a plain
    file download; nothing here sends anything anywhere on its own.

    Returns a raw HttpResponse, not a DRF Response, same reasoning
    already established for ContractExportTerminView — this is a
    real file, not JSON, and DRF's own finalize_response() passes
    any HttpResponseBase through unchanged.

    Available regardless of estimate.status, on purpose — Made's own
    confirmed real trigger is "estimasi diterbitkan," not "estimasi
    disetujui." The quotation is meant to go out the moment it's
    issued, not gated behind approval.
    """
    model = Estimate

    def get(self, request, pk):
        estimate = self.get_object(pk)
        pdf_bytes = build_quotation_pdf(estimate, org_name=estimate.organization.name)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        # Sanitized the same way ContractExportTerminView's own
        # filename is — a real plate number could in principle carry
        # a character a filesystem chokes on, and there's no reason
        # to trust that blindly just because it hasn't happened yet.
        safe_plate = "".join(c if c.isalnum() or c in " -_" else "_" for c in estimate.vehicle.plate_number)
        response["Content-Disposition"] = f'attachment; filename="Estimasi_{estimate.number}_{safe_plate}.pdf"'
        return response
