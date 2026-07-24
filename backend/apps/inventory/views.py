# =============================================================================
# === backend/apps/inventory/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from apps.service.models import ServiceRecord
from django.db.models import ProtectedError, Q
from rest_framework import status
from rest_framework.response import Response

from .models import Part, PartUsage, StockAdjustment
from .serializers import (PartSerializer, PartUsageSerializer,
                          StockAdjustmentSerializer)


class PartListView(TenantScopedAPIView):
    """
    GET/POST /api/parts/
    ?search= filters by name or SKU.
    ?low_stock=true — parts at or below 5 units.
    """
    model = Part
    LOW_STOCK_THRESHOLD = 5

    def get(self, request):
        parts = self.get_queryset().order_by("name")
        search = request.query_params.get("search")
        if search:
            parts = parts.filter(Q(name__icontains=search) | Q(sku__icontains=search))
        if request.query_params.get("low_stock") == "true":
            parts = parts.filter(current_stock__lte=self.LOW_STOCK_THRESHOLD)
        serializer = PartSerializer(parts, many=True)
        return Response({"success": True, "count": parts.count(), "results": serializer.data})

    def post(self, request):
        org = self._resolve_org(request)
        if org is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = PartSerializer(data=request.data)
        if serializer.is_valid():
            part = serializer.save(organization=org)
            return Response(
                {"success": True, "part": PartSerializer(part).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _resolve_org(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        return membership.organization if membership else None


class PartDetailView(TenantScopedAPIView):
    """
    GET/PUT/DELETE /api/parts/<id>/
    PUT deliberately cannot touch current_stock (read_only in the
    serializer) — only name/sku/unit/unit_price are editable this
    way. Stock only ever moves through PartUsage or StockAdjustment.
    """
    model = Part

    def get(self, request, pk):
        part = self.get_object(pk)
        return Response({"success": True, "part": PartSerializer(part).data})

    def put(self, request, pk):
        part = self.get_object(pk)
        serializer = PartSerializer(part, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "part": PartSerializer(part).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        part = self.get_object(pk)
        try:
            part.delete()
        except ProtectedError:
            return Response(
                {
                    "success": False,
                    "message": "Part ini sudah pernah digunakan atau memiliki riwayat stok — tidak bisa dihapus.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"success": True, "message": "Part berhasil dihapus"})


class PartUsageListView(TenantScopedAPIView):
    """
    GET/POST /api/service-records/<service_record_id>/part-usages/
    Nested under service record — mirrors ServiceRecordListView's own
    nesting under vehicle, same "this only makes sense in context"
    reasoning.

    The 201 response includes a top-level `warnings` list (empty if
    none) surfaced from the serializer's soft negative-stock check —
    the frontend can display this without it being a hard failure.
    """
    model = PartUsage

    def get(self, request, service_record_id):
        usages = self.get_queryset().filter(service_record_id=service_record_id).select_related("part")
        serializer = PartUsageSerializer(usages, many=True)
        return Response({"success": True, "count": usages.count(), "results": serializer.data})

    def post(self, request, service_record_id):
        service_record = self._get_service_record(request, service_record_id)
        if service_record is None:
            return Response(
                {"success": False, "message": "Catatan servis tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # A ServiceRecord that already has an Invoice is frozen — the
        # Invoice already snapshotted whatever PartUsage existed at
        # its own creation time. Letting more usage attach afterward
        # would silently drift real stock and the invoice's own
        # printed numbers apart — exactly the class of bug every
        # snapshot in this codebase (PartUsage.unit_price_at_time,
        # Invoice's customer_name_snapshot, etc.) exists to prevent.
        # This was previously only enforced by the frontend hiding a
        # button — a real gap, since the endpoint itself never
        # checked. getattr() is the correct, idiomatic way to probe a
        # reverse OneToOneField without a try/except: Django's
        # RelatedObjectDoesNotExist is deliberately a subclass of
        # AttributeError specifically so this works.
        if getattr(service_record, "invoice", None) is not None:
            return Response(
                {
                    "success": False,
                    "message": "Catatan servis ini sudah memiliki invoice — tidak bisa menambah part lagi.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        payload = dict(request.data)
        payload["service_record"] = service_record_id
        context = {"request": request}
        serializer = PartUsageSerializer(data=payload, context=context)
        if serializer.is_valid():
            usage = serializer.save()
            return Response(
                {
                    "success": True,
                    "part_usage": PartUsageSerializer(usage).data,
                    "warnings": context.get("warnings", []),
                },
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_service_record(self, request, service_record_id):
        # Deliberately not self.get_queryset() — that filters by
        # self.model, which is PartUsage here, not ServiceRecord.
        # Same tenant-scoping logic as TenantScopedAPIView, applied
        # to the actual model this lookup needs — same pattern
        # already used in apps.invoicing.views and apps.workorders.views
        # for the same reason.
        user = request.user
        if user.role == "super_admin":
            qs = ServiceRecord.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = ServiceRecord.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=service_record_id).first()


class StockAdjustmentListView(TenantScopedAPIView):
    """
    GET/POST /api/parts/<part_id>/adjustments/
    Nested under part — every adjustment only ever makes sense
    against one specific part's running total.
    """
    model = StockAdjustment

    def get(self, request, part_id):
        adjustments = self.get_queryset().filter(part_id=part_id)
        serializer = StockAdjustmentSerializer(adjustments, many=True)
        return Response({"success": True, "count": adjustments.count(), "results": serializer.data})

    def post(self, request, part_id):
        payload = dict(request.data)
        payload["part"] = part_id
        serializer = StockAdjustmentSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            adjustment = serializer.save(created_by=request.user)
            return Response(
                {"success": True, "adjustment": StockAdjustmentSerializer(adjustment).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
