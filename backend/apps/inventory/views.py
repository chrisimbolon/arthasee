# =============================================================================
# === backend/apps/inventory/views.py ===
# =============================================================================
from django.db.models import ProtectedError, Q
from rest_framework import status
from rest_framework.response import Response

from apps.core.views import TenantScopedAPIView

from .models import Part, PartUsage, StockAdjustment
from .serializers import PartSerializer, PartUsageSerializer, StockAdjustmentSerializer


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
    """GET/PUT/DELETE /api/parts/<id>/"""
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
    Nested under service record from apps.service — a cross-app
    nesting, same as the model's own cross-app FK.
    """
    model = PartUsage

    def get(self, request, service_record_id):
        usages = self.get_queryset().filter(service_record_id=service_record_id).select_related("part")
        serializer = PartUsageSerializer(usages, many=True)
        return Response({"success": True, "count": usages.count(), "results": serializer.data})

    def post(self, request, service_record_id):
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


class StockAdjustmentListView(TenantScopedAPIView):
    """GET/POST /api/parts/<part_id>/adjustments/"""
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
