# =============================================================================
# === backend/apps/workorders/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import WorkOrder, WorkOrderJobLine, WorkOrderMaterialLine


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class WorkOrderJobLineSerializer(serializers.ModelSerializer):
    class Meta:
        model  = WorkOrderJobLine
        fields = ["id", "work_order", "description", "is_done", "created_at"]
        read_only_fields = ["id", "created_at"]


class WorkOrderMaterialLineSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    unit      = serializers.CharField(source="part.unit", read_only=True)
    subtotal  = serializers.SerializerMethodField()

    class Meta:
        model  = WorkOrderMaterialLine
        fields = [
            "id", "work_order", "part", "part_name", "unit",
            "quantity", "unit_price_at_time", "subtotal", "created_at",
        ]
        read_only_fields = ["id", "part_name", "unit", "unit_price_at_time", "subtotal", "created_at"]

    def get_subtotal(self, obj):
        return obj.quantity * obj.unit_price_at_time

    def validate_part(self, part):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return part
        if part.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Part tidak ditemukan.")
        return part


class WorkOrderSerializer(serializers.ModelSerializer):
    job_lines       = WorkOrderJobLineSerializer(many=True, read_only=True)
    material_lines   = WorkOrderMaterialLineSerializer(many=True, read_only=True)
    vehicle_plate    = serializers.CharField(source="vehicle.plate_number", read_only=True)
    customer_name    = serializers.CharField(source="vehicle.customer.name", read_only=True)
    created_by_name  = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = WorkOrder
        fields = [
            "id", "vehicle", "vehicle_plate", "customer_name",
            "number", "sequence_number", "status",
            "odometer_km_intake", "received_by", "notes",
            "service_record", "job_lines", "material_lines",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle_plate", "customer_name", "number", "sequence_number", "status",
            "service_record", "job_lines", "material_lines",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]

    def validate_vehicle(self, vehicle):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return vehicle
        if vehicle.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Kendaraan tidak ditemukan.")
        return vehicle


class WorkOrderListSerializer(WorkOrderSerializer):
    """Lighter version for list views — no nested lines, same
    reasoning as VehicleListSerializer's own trimmed-down shape."""
    class Meta(WorkOrderSerializer.Meta):
        fields = [f for f in WorkOrderSerializer.Meta.fields if f not in ("job_lines", "material_lines")]
