# =============================================================================
# === backend/apps/estimates/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import Estimate, EstimateLineItem


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class EstimateLineItemSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True, default=None)
    subtotal  = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model  = EstimateLineItem
        fields = ["id", "estimate", "kind", "description", "quantity", "unit_price", "part", "part_name", "subtotal", "created_at"]
        read_only_fields = ["id", "part_name", "subtotal", "created_at"]

    def validate_part(self, part):
        if part is None:
            return part
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return part
        if part.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Part tidak ditemukan.")
        return part


class EstimateSerializer(serializers.ModelSerializer):
    line_items      = EstimateLineItemSerializer(many=True, read_only=True)
    vehicle_plate    = serializers.CharField(source="vehicle.plate_number", read_only=True)
    customer_name    = serializers.CharField(source="vehicle.customer.name", read_only=True)
    created_by_name  = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    total            = serializers.SerializerMethodField()

    class Meta:
        model  = Estimate
        fields = [
            "id", "vehicle", "vehicle_plate", "customer_name",
            "number", "sequence_number", "status",
            "diagnosis_notes", "rejection_reason", "rejection_notes",
            "work_order", "line_items", "total",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle_plate", "customer_name", "number", "sequence_number", "status",
            "rejection_reason", "rejection_notes",
            "work_order", "line_items", "total",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]

    def get_total(self, obj):
        return sum((li.subtotal for li in obj.line_items.all()), Decimal("0"))

    def validate_vehicle(self, vehicle):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return vehicle
        if vehicle.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Kendaraan tidak ditemukan.")
        return vehicle
