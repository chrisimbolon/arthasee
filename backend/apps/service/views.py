# =============================================================================
# === backend/apps/service/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from django.db.models import ProtectedError, Q
from rest_framework import status
from rest_framework.response import Response

from .models import (Customer, Part, PartUsage, ServiceRecord, StockAdjustment,
                     Vehicle)
from .serializers import (CustomerSerializer, PartSerializer,
                          PartUsageSerializer, ServiceRecordSerializer,
                          StockAdjustmentSerializer, VehicleListSerializer,
                          VehicleSerializer)


class CustomerListView(TenantScopedAPIView):
    """GET/POST /api/customers/"""
    model = Customer

    def get(self, request):
        customers = self.get_queryset().order_by("name")
        search = request.query_params.get("search")
        if search:
            customers = customers.filter(name__icontains=search)
        serializer = CustomerSerializer(customers, many=True)
        return Response({"success": True, "count": customers.count(), "results": serializer.data})

    def post(self, request):
        org = self._resolve_org(request)
        if org is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = CustomerSerializer(data=request.data)
        if serializer.is_valid():
            customer = serializer.save(organization=org)
            return Response(
                {"success": True, "customer": CustomerSerializer(customer).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _resolve_org(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        return membership.organization if membership else None


class CustomerDetailView(TenantScopedAPIView):
    """GET/PUT/DELETE /api/customers/<id>/"""
    model = Customer

    def get(self, request, pk):
        return Response({"success": True, "customer": CustomerSerializer(self.get_object(pk)).data})

    def put(self, request, pk):
        customer = self.get_object(pk)
        serializer = CustomerSerializer(customer, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "customer": CustomerSerializer(customer).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        customer = self.get_object(pk)
        try:
            customer.delete()
        except ProtectedError:
            return Response(
                {
                    "success": False,
                    "message": "Pelanggan ini punya kendaraan tercatat — tidak bisa dihapus. "
                                "Riwayat servis tidak boleh hilang.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"success": True, "message": "Pelanggan berhasil dihapus"})


class VehicleListView(TenantScopedAPIView):
    """
    GET/POST /api/vehicles/
    ?due_for_service=true filters to vehicles that have crossed the
    5,000 km threshold — the actual practical payoff of the flag,
    without needing real notification delivery built first.
    ?registration_expiring_soon=true — same idea, Sprint 1's new flag.
    """
    model = Vehicle

    def get(self, request):
        vehicles = self.get_queryset().select_related("customer")
        due_only     = request.query_params.get("due_for_service") == "true"
        expiring_only = request.query_params.get("registration_expiring_soon") == "true"
        if due_only or expiring_only:
            # Filtered in Python, not the DB — both flags are plain
            # Python properties (see models.py), and this list is
            # realistically small enough per shop that this is simpler
            # and clearer than duplicating the threshold logic as a
            # queryset annotation. Same reasoning as the pre-existing
            # due_for_service filter, just extended to cover both.
            vehicles = [
                v for v in vehicles
                if (not due_only or v.is_due_for_service)
                and (not expiring_only or v.is_registration_expiring_soon)
            ]
        serializer = VehicleListSerializer(vehicles, many=True)
        count = len(vehicles) if isinstance(vehicles, list) else vehicles.count()
        return Response({"success": True, "count": count, "results": serializer.data})

    def post(self, request):
        serializer = VehicleSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            vehicle = serializer.save()
            return Response(
                {"success": True, "vehicle": VehicleSerializer(vehicle).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class VehicleDetailView(TenantScopedAPIView):
    """GET/PUT/DELETE /api/vehicles/<id>/"""
    model = Vehicle

    def get(self, request, pk):
        vehicle = self.get_object(pk)
        return Response({"success": True, "vehicle": VehicleSerializer(vehicle).data})

    def put(self, request, pk):
        vehicle = self.get_object(pk)
        serializer = VehicleSerializer(vehicle, data=request.data, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "vehicle": VehicleSerializer(vehicle).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        vehicle = self.get_object(pk)
        try:
            vehicle.delete()
        except ProtectedError:
            return Response(
                {
                    "success": False,
                    "message": "Kendaraan ini punya riwayat servis — tidak bisa dihapus. "
                                "Riwayat servis tidak boleh hilang.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"success": True, "message": "Kendaraan berhasil dihapus"})


class ServiceRecordListView(TenantScopedAPIView):
    """
    GET/POST /api/vehicles/<vehicle_id>/service-records/
    Nested under vehicle — a service record only ever makes sense in
    the context of one vehicle's history.
    """
    model = ServiceRecord

    def get(self, request, vehicle_id):
        records = self.get_queryset().filter(vehicle_id=vehicle_id)
        serializer = ServiceRecordSerializer(records, many=True)
        return Response({"success": True, "count": records.count(), "results": serializer.data})

    def post(self, request, vehicle_id):
        payload = dict(request.data)
        payload["vehicle"] = vehicle_id
        serializer = ServiceRecordSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            record = serializer.save(created_by=request.user)
            return Response(
                {"success": True, "service_record": ServiceRecordSerializer(record).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


# =============================================================================
# === Sprint 1: Inventory ===
# =============================================================================

class PartListView(TenantScopedAPIView):
    """
    GET/POST /api/parts/
    ?search= filters by name or SKU — same shape as CustomerListView's
    search param, kept consistent rather than inventing a new
    convention for the same kind of lookup.
    ?low_stock=true — parts at or below 5 units, a simple built-in
    threshold rather than a per-part configurable reorder point,
    matching Sprint 1's roadmap scope ("count only, revisit if he
    asks for reorder points").
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
