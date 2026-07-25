# =============================================================================
# === backend/apps/estimates/views.py ===
# =============================================================================
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from apps.core.views import TenantScopedAPIView

from .models import Estimate, EstimateLineItem
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
    PUT is narrow — only diagnosis_notes, and only while PENDING.
    Approval/rejection go through their own dedicated endpoints,
    since those carry real, one-way side effects.
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
        allowed = {k: v for k, v in request.data.items() if k == "diagnosis_notes"}
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
