# =============================================================================
# === backend/apps/service/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import Customer, ServiceRecord, Vehicle


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class CustomerSerializer(serializers.ModelSerializer):
    vehicle_count = serializers.IntegerField(source="vehicles.count", read_only=True)

    class Meta:
        model  = Customer
        fields = ["id", "name", "phone", "stnk_name", "vehicle_count", "created_at", "updated_at"]
        read_only_fields = ["id", "vehicle_count", "created_at", "updated_at"]


class ServiceRecordSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    part_usages      = serializers.SerializerMethodField()

    class Meta:
        model  = ServiceRecord
        fields = [
            "id", "vehicle", "service_date", "odometer_km",
            "issue_description", "parts_replaced", "notes", "part_usages",
            "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_by_name", "created_at", "part_usages"]

    def get_part_usages(self, obj):
        # part_usages is PartUsage's related_name — that model now
        # lives in apps.inventory, but the related accessor works
        # identically regardless of which app defines the model on
        # the other end of the FK. No change needed here beyond this
        # comment reflecting where it actually lives now.
        return [
            {
                "id": pu.id, "part": pu.part_id, "part_name": pu.part.name,
                "quantity": pu.quantity, "unit": pu.part.unit,
                "unit_price_at_time": pu.unit_price_at_time,
            }
            for pu in obj.part_usages.select_related("part").all()
        ]

    def validate_vehicle(self, vehicle):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return vehicle
        if vehicle.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Kendaraan tidak ditemukan.")
        return vehicle


class VehicleSerializer(serializers.ModelSerializer):
    customer_name              = serializers.CharField(source="customer.name", read_only=True)
    is_due_for_service          = serializers.BooleanField(read_only=True)
    is_registration_expiring_soon = serializers.BooleanField(read_only=True)
    service_records             = ServiceRecordSerializer(many=True, read_only=True)

    class Meta:
        model  = Vehicle
        fields = [
            "id", "customer", "customer_name",
            "plate_number", "manufacture_year", "vehicle_type", "body_style", "model",
            "chassis_number", "engine_number", "bpkb_number", "color", "registration_expiry",
            "current_odometer_km", "last_service_date", "last_service_odometer_km",
            "is_due_for_service", "is_registration_expiring_soon", "service_records",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "customer_name", "last_service_date", "last_service_odometer_km",
            "is_due_for_service", "is_registration_expiring_soon", "service_records",
            "created_at", "updated_at",
        ]

    def validate_customer(self, customer):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return customer
        if customer.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Pelanggan tidak ditemukan.")
        return customer


class VehicleListSerializer(VehicleSerializer):
    class Meta(VehicleSerializer.Meta):
        fields = [f for f in VehicleSerializer.Meta.fields if f != "service_records"]
