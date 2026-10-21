# =============================================================================
# === backend/apps/service/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response

from django.core.exceptions import ValidationError as DjangoValidationError

from .models import (VEHICLE_CLASSES, Customer, CustomerFieldChange,
                     ServiceItem, ServiceRecord, Vehicle, VehicleFieldChange,
                     normalise_vehicle_class)
from .serializers import (CustomerFieldChangeSerializer, CustomerSerializer,
                          ServiceItemChangeSerializer, ServiceItemSerializer,
                          ServiceRecordSerializer,
                          VehicleFieldChangeSerializer, VehicleListSerializer,
                          VehicleSerializer)


class CustomerListView(TenantScopedAPIView):
    """
    GET/POST /api/customers/
    ?customer_type=INSTITUTIONAL filters to institutional/tender
    clients only — the real backend equivalent of what
    apps.contracts' Contract-creation picker was doing client-side
    until this view was actually reviewed. Same plain-equality-filter
    style as ?search=, no extra validation on the value: an unknown
    customer_type just yields zero results, same harmless behavior as
    a search term matching nothing.
    """
    model = Customer

    def get(self, request):
        customers = self.get_queryset().order_by("name")
        search = request.query_params.get("search")
        if search:
            customers = customers.filter(name__icontains=search)
        customer_type = request.query_params.get("customer_type")
        if customer_type:
            customers = customers.filter(customer_type=customer_type)
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
        # 13 Sep 2026 — the serializer still owns real INPUT
        # validation (is_valid()) exactly as before; the actual
        # WRITE now goes through Customer.apply_edit() instead of a
        # plain serializer.save(), so every genuine field change
        # gets its own real CustomerFieldChange row. validated_data
        # only ever contains this serializer's own real writable
        # field names (name/phone/stnk_name/customer_type) — never
        # an unknown key apply_edit() would reject.
        serializer = CustomerSerializer(customer, data=request.data, partial=True)
        if serializer.is_valid():
            customer.apply_edit(changed_by=request.user, **serializer.validated_data)
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

class CustomerHistoryView(TenantScopedAPIView):
    """
    GET /api/customers/<id>/history/

    13 Sep 2026 — real, read-only view onto Customer.apply_edit()'s
    own real audit trail. Most-recent-first (CustomerFieldChange's
    own Meta.ordering), matching the "Riwayat" tab's own real
    reading order — newest change at the top.
    """
    model = Customer

    def get(self, request, pk):
        customer = self.get_object(pk)
        changes = customer.field_changes.select_related("changed_by")
        return Response({"success": True, "changes": CustomerFieldChangeSerializer(changes, many=True).data})

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
            data = dict(serializer.validated_data)
            # 14 Sep 2026 -- real, deliberate guard: `customer`
            # reassignment is a structural ownership transfer, not a
            # simple field correction -- explicitly excluded from
            # Vehicle.apply_edit()'s own trackable field set (models.py).
            # Blocked HERE, with a real, clear message, rather than
            # letting apply_edit()'s own generic "Field tidak dikenal"
            # fire for it -- that would be technically correct but
            # confusing for any real caller that hits this.
            if "customer" in data:
                return Response(
                    {
                        "success": False,
                        "message": "Pemindahan kepemilikan kendaraan belum didukung lewat endpoint ini -- "
                                    "fitur transfer kendaraan akan dibuat terpisah.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            vehicle.apply_edit(changed_by=request.user, **data)
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


class VehicleHistoryView(TenantScopedAPIView):
    """
    GET /api/vehicles/<id>/history/

    14 Sep 2026 -- real, read-only view onto Vehicle.apply_edit()'s
    own real audit trail. Same shape as CustomerHistoryView.
    """
    model = Vehicle

    def get(self, request, pk):
        vehicle = self.get_object(pk)
        changes = vehicle.field_changes.select_related("changed_by")
        return Response({"success": True, "changes": VehicleFieldChangeSerializer(changes, many=True).data})


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


# ── Daftar Jasa — Phase 21, Task 21.3 (20 Oct 2026) ─────────────────────
# Reading the list: any active member of the shop. Changing it: the shop
# OWNER only (Chris/Made, 16 Oct: "Owner / Admin ONLY") — the same
# membership.role == "owner" check apps.organizations.views uses for shop
# settings. A model ValueError (bad price, duplicate name) is a 400 with
# the message shown as-is.
def _acting_membership(request):
    return (
        request.user.memberships.filter(is_active=True)
        .select_related("organization").order_by("id").first()
    )


def _owner_only(membership):
    if membership is None:
        return Response(
            {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if membership.role != "owner":
        return Response(
            {"success": False, "message": "Hanya pemilik bengkel yang bisa mengubah Daftar Jasa."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _edit_kwargs(data):
    """Only the keys actually sent — an absent key stays _UNSET (untouched)."""
    return {k: data[k] for k in ("name", "default_price", "is_active", "class_prices") if k in data}


class ServiceItemListView(TenantScopedAPIView):
    """
    GET  /api/service-items/?include_inactive=true
    POST /api/service-items/   (owner only)
         {"name": "Tune-up", "default_price": 300000,
          "class_prices": {"SUV": 400000, "MPV": 350000}}
    """
    model = ServiceItem

    def get(self, request):
        items = self.get_queryset().prefetch_related("class_prices").order_by("name")
        if request.query_params.get("include_inactive") != "true":
            items = items.filter(is_active=True)

        # 21 Oct 2026 (Phase 21, Task 21.4) — ?vehicle=<id>: also return each
        # jasa's price for THAT vehicle's class, for the Estimate's jasa
        # search box. Same tenant scoping as every other lookup here: a
        # vehicle from another shop is simply "not found".
        vehicle = None
        vehicle_id = request.query_params.get("vehicle")
        if vehicle_id:
            if request.user.role == "super_admin":
                vehicles = Vehicle.objects.all()
            else:
                org_ids = request.user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
                vehicles = Vehicle.objects.filter(organization_id__in=org_ids)
            try:
                vehicle = vehicles.filter(pk=vehicle_id).first()
            except (DjangoValidationError, ValueError):
                vehicle = None
            if vehicle is None:
                return Response(
                    {"success": False, "message": "Kendaraan tidak ditemukan."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        membership = _acting_membership(request)
        return Response({
            "success": True,
            "count": items.count(),
            "results": ServiceItemSerializer(items, many=True, context={"vehicle": vehicle}).data,
            "vehicle_classes": VEHICLE_CLASSES,
            "vehicle_class": normalise_vehicle_class(vehicle.body_style) if vehicle else None,
            "can_edit": bool(membership and membership.role == "owner"),
        })

    def post(self, request):
        membership = _acting_membership(request)
        blocked = _owner_only(membership)
        if blocked is not None:
            return blocked
        try:
            item = ServiceItem.record(
                organization=membership.organization,
                name=request.data.get("name"),
                default_price=request.data.get("default_price"),
                class_prices=request.data.get("class_prices") or {},
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"success": True, "service_item": ServiceItemSerializer(item).data},
            status=status.HTTP_201_CREATED,
        )


class ServiceItemDetailView(TenantScopedAPIView):
    """
    GET   /api/service-items/<id>/
    PATCH /api/service-items/<id>/   (owner only) — send only what changes;
          in class_prices, null removes that class's own price.
    No DELETE on purpose: retire a jasa with {"is_active": false}.
    """
    model = ServiceItem

    def get(self, request, pk):
        item = self.get_object(pk)
        return Response({"success": True, "service_item": ServiceItemSerializer(item).data})

    def patch(self, request, pk):
        item = self.get_object(pk)
        blocked = _owner_only(_acting_membership(request))
        if blocked is not None:
            return blocked
        try:
            item.apply_edit(changed_by=request.user, **_edit_kwargs(request.data))
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        item.refresh_from_db()
        return Response({"success": True, "service_item": ServiceItemSerializer(item).data})


class ServiceItemHistoryView(TenantScopedAPIView):
    """GET /api/service-items/<id>/history/ — read-only change log."""
    model = ServiceItem

    def get(self, request, pk):
        item = self.get_object(pk)
        changes = item.changes.select_related("changed_by")
        return Response({"success": True, "changes": ServiceItemChangeSerializer(changes, many=True).data})
