# =============================================================================
# === backend/apps/service/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response

from .models import Customer, ServiceRecord, Vehicle
from .serializers import (CustomerSerializer, ServiceRecordSerializer,
                          VehicleListSerializer, VehicleSerializer)


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
    ?due_for_service=true and ?registration_expiring_soon=true filter
    the list — both computed Python properties, filtered in Python
    rather than the DB for the same reasoning as before (small
    per-shop lists, simpler than duplicating threshold logic as a
    queryset annotation).
    """
    model = Vehicle

    def get(self, request):
        vehicles = self.get_queryset().select_related("customer")
        due_only     = request.query_params.get("due_for_service") == "true"
        expiring_only = request.query_params.get("registration_expiring_soon") == "true"
        if due_only or expiring_only:
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
