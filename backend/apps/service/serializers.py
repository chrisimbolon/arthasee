# =============================================================================
# === backend/apps/service/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import Customer, ServiceRecord, Vehicle


class CustomerSerializer(serializers.ModelSerializer):
    vehicle_count = serializers.IntegerField(source="vehicles.count", read_only=True)

    class Meta:
        model  = Customer
        fields = ["id", "name", "phone", "stnk_name", "vehicle_count", "created_at", "updated_at"]
        read_only_fields = ["id", "vehicle_count", "created_at", "updated_at"]


class ServiceRecordSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = ServiceRecord
        fields = [
            "id", "vehicle", "service_date", "odometer_km",
            "issue_description", "parts_replaced", "notes",
            "created_by", "created_by_name", "created_at",
        ]
        # Append-only, same as every audit-style record elsewhere —
        # nothing here is editable after creation, including via API.
        read_only_fields = ["id", "created_by", "created_by_name", "created_at"]

    def validate_vehicle(self, vehicle):
        """Same cross-tenant guard as VehicleSerializer.validate_customer
        — a vehicle id from another shop must never be accepted here."""
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return vehicle
        org_ids = request.user.memberships.filter(is_active=True).values_list(
            "organization_id", flat=True
        )
        if vehicle.organization_id not in org_ids:
            raise serializers.ValidationError("Kendaraan tidak ditemukan.")
        return vehicle


class VehicleSerializer(serializers.ModelSerializer):
    customer_name       = serializers.CharField(source="customer.name", read_only=True)
    is_due_for_service   = serializers.BooleanField(read_only=True)
    service_records      = ServiceRecordSerializer(many=True, read_only=True)

    class Meta:
        model  = Vehicle
        fields = [
            "id", "customer", "customer_name",
            "plate_number", "manufacture_year", "vehicle_type", "model",
            "current_odometer_km", "last_service_date", "last_service_odometer_km",
            "is_due_for_service", "service_records",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "customer_name", "last_service_date", "last_service_odometer_km",
            "is_due_for_service", "service_records", "created_at", "updated_at",
        ]

    def validate_customer(self, customer):
        """
        Without this, a request could pass any customer id, including
        one belonging to a completely different shop — Vehicle would
        then silently resolve to THAT shop's organization via
        _resolve_organization(), a real cross-tenant leak. Same class
        of check DevelopIndo's validate_project() did for Units.
        """
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return customer
        org_ids = request.user.memberships.filter(is_active=True).values_list(
            "organization_id", flat=True
        )
        if customer.organization_id not in org_ids:
            raise serializers.ValidationError("Pelanggan tidak ditemukan.")
        return customer


class VehicleListSerializer(VehicleSerializer):
    """
    Lighter version for list views — no nested service_records, so
    listing 50 vehicles doesn't drag along every historical service
    record for each one.
    """
    class Meta(VehicleSerializer.Meta):
        fields = [f for f in VehicleSerializer.Meta.fields if f != "service_records"]
