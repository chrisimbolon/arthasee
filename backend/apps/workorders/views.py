# =============================================================================
# === backend/apps/workorders/views.py ===
# =============================================================================
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from apps.core.views import TenantScopedAPIView
from apps.inventory.models import StockAdjustment

from .models import WorkOrder, WorkOrderJobLine, WorkOrderMaterialLine
from .serializers import (
    WorkOrderJobLineSerializer, WorkOrderListSerializer, WorkOrderMaterialLineSerializer, WorkOrderSerializer,
)

# Statuses a WorkOrder can still be actively edited in — once it's
# DONE or CANCELLED, it's frozen, matching ServiceRecord's own
# append-only philosophy from that point forward.
OPEN_STATUSES = ("OPEN", "IN_PROGRESS", "QC")


class WorkOrderListView(TenantScopedAPIView):
    """GET/POST /api/vehicles/<vehicle_id>/work-orders/"""
    model = WorkOrder

    def get(self, request, vehicle_id):
        orders = self.get_queryset().filter(vehicle_id=vehicle_id).select_related("vehicle__customer")
        serializer = WorkOrderListSerializer(orders, many=True)
        return Response({"success": True, "count": orders.count(), "results": serializer.data})

    def post(self, request, vehicle_id):
        payload = dict(request.data)
        payload["vehicle"] = vehicle_id
        serializer = WorkOrderSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            order = serializer.save(created_by=request.user)
            return Response(
                {"success": True, "work_order": WorkOrderSerializer(order).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class WorkOrderDetailView(TenantScopedAPIView):
    """
    GET/PUT /api/work-orders/<id>/
    PUT is deliberately narrow — only odometer_km_intake, received_by,
    notes are writable, and only while the order is still open. Status
    changes go through the dedicated status/close/cancel endpoints
    below, since those carry real side effects PUT shouldn't hide.
    """
    model = WorkOrder

    def get(self, request, pk):
        order = self.get_object(pk)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})

    def put(self, request, pk):
        order = self.get_object(pk)
        if order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan — tidak bisa diubah."},
                status=status.HTTP_409_CONFLICT,
            )
        allowed = {k: v for k, v in request.data.items() if k in ("odometer_km_intake", "received_by", "notes")}
        serializer = WorkOrderSerializer(order, data=allowed, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "work_order": WorkOrderSerializer(order).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class WorkOrderStatusUpdateView(TenantScopedAPIView):
    """
    PATCH /api/work-orders/<id>/status/
    Only moves between OPEN/IN_PROGRESS/QC — plain pipeline progress,
    no side effects. DONE and CANCELLED are handled by the dedicated
    close/cancel endpoints below, since those actually do things
    (freeze into a ServiceRecord, reverse stock) that a bare status
    write must never trigger implicitly.
    """
    model = WorkOrder

    def patch(self, request, pk):
        order = self.get_object(pk)
        new_status = request.data.get("status")
        if new_status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Gunakan endpoint /close/ atau /cancel/ untuk status ini."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})


class WorkOrderCloseView(TenantScopedAPIView):
    """POST /api/work-orders/<id>/close/ — freezes into a ServiceRecord."""
    model = WorkOrder

    def post(self, request, pk):
        order = self.get_object(pk)
        try:
            order.close(closed_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})


class WorkOrderCancelView(TenantScopedAPIView):
    """POST /api/work-orders/<id>/cancel/ — reverses any stock deducted."""
    model = WorkOrder

    def post(self, request, pk):
        order = self.get_object(pk)
        try:
            order.cancel()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})


class WorkOrderJobLineListView(TenantScopedAPIView):
    """GET/POST /api/work-orders/<work_order_id>/job-lines/"""
    model = WorkOrderJobLine

    def get(self, request, work_order_id):
        lines = self.get_queryset().filter(work_order_id=work_order_id)
        serializer = WorkOrderJobLineSerializer(lines, many=True)
        return Response({"success": True, "count": lines.count(), "results": serializer.data})

    def post(self, request, work_order_id):
        work_order = self._get_open_work_order(request, work_order_id)
        if work_order is None:
            return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        if work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = dict(request.data)
        payload["work_order"] = work_order_id
        serializer = WorkOrderJobLineSerializer(data=payload)
        if serializer.is_valid():
            line = serializer.save()
            return Response(
                {"success": True, "job_line": WorkOrderJobLineSerializer(line).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_open_work_order(self, request, work_order_id):
        user = request.user
        if user.role == "super_admin":
            qs = WorkOrder.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = WorkOrder.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=work_order_id).first()


class WorkOrderJobLineToggleView(TenantScopedAPIView):
    """PATCH /api/work-orders/job-lines/<id>/toggle/ — flips is_done."""
    model = WorkOrderJobLine

    def patch(self, request, pk):
        line = self.get_object(pk)
        if line.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        line.is_done = not line.is_done
        line.save(update_fields=["is_done"])
        return Response({"success": True, "job_line": WorkOrderJobLineSerializer(line).data})


class WorkOrderMaterialLineListView(TenantScopedAPIView):
    """
    GET/POST /api/work-orders/<work_order_id>/material-lines/
    POST is where real-time stock deduction actually happens — see
    WorkOrderMaterialLine.save() in models.py.
    """
    model = WorkOrderMaterialLine

    def get(self, request, work_order_id):
        lines = self.get_queryset().filter(work_order_id=work_order_id).select_related("part")
        serializer = WorkOrderMaterialLineSerializer(lines, many=True)
        return Response({"success": True, "count": lines.count(), "results": serializer.data})

    def post(self, request, work_order_id):
        work_order = self._get_work_order(request, work_order_id)
        if work_order is None:
            return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        if work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = dict(request.data)
        payload["work_order"] = work_order_id
        serializer = WorkOrderMaterialLineSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            line = serializer.save()
            return Response(
                {"success": True, "material_line": WorkOrderMaterialLineSerializer(line).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_work_order(self, request, work_order_id):
        user = request.user
        if user.role == "super_admin":
            qs = WorkOrder.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = WorkOrder.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=work_order_id).first()


class WorkOrderMaterialLineDetailView(TenantScopedAPIView):
    """
    DELETE /api/work-orders/material-lines/<id>/
    Removing a material line before the WorkOrder closes must reverse
    the stock it already deducted — otherwise deleting a mistaken
    entry would leave stock permanently short for no reason. Reuses
    the same StockAdjustment mechanism as WorkOrder.cancel(), tagged
    "correction" rather than "work_order_cancelled" since this is a
    single-line fix, not a whole order being abandoned.
    """
    model = WorkOrderMaterialLine

    def delete(self, request, pk):
        line = self.get_object(pk)
        if line.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan — baris tidak bisa dihapus."},
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            StockAdjustment.objects.create(
                organization=line.organization, part=line.part,
                quantity_change=line.quantity, reason="correction",
                notes=f"Baris material dihapus dari WO {line.work_order.number}",
            )
            line.delete()
        return Response({"success": True, "message": "Baris material dihapus, stok dikembalikan."})
