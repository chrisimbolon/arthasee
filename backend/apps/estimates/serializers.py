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


def _format_km(value):
    """Plain Indonesian thousands-separator formatting — same
    convention as money() on the frontend and _format_rupiah in
    apps.contracts.exports, just without a currency prefix."""
    return f"{value:,}".replace(",", ".")


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
    # Read-only, pulled directly from Vehicle.last_service_odometer_km
    # — already a real, correctly-maintained field (kept in sync on
    # every ServiceRecord.save()), not something this app needs to
    # compute itself. Chris's own spec: "KM Terakhir Service" comes
    # specifically from the vehicle's last completed service record,
    # which is exactly what this field already represents.
    last_service_odometer_km = serializers.IntegerField(
        source="vehicle.last_service_odometer_km", read_only=True, default=None,
    )

    class Meta:
        model  = Estimate
        fields = [
            "id", "vehicle", "vehicle_plate", "customer_name",
            "number", "sequence_number", "status",
            "diagnosis_notes", "odometer_km_intake", "last_service_odometer_km",
            "rejection_reason", "rejection_notes",
            "work_order", "line_items", "total",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle_plate", "customer_name", "number", "sequence_number", "status",
            "last_service_odometer_km",
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

    def validate_odometer_km_intake(self, value):
        """
        Chris's explicit call, 31 Jul: hard block, not a soft warning
        — cannot save if less than the vehicle's last recorded
        service odometer. self.instance is available here because
        this field is only ever written through an update (PUT) on
        an existing Estimate, never at creation — there's always a
        real vehicle to check against by the time this runs.
        """
        if value is None:
            return value
        vehicle = self.instance.vehicle if self.instance else None
        if vehicle is None:
            return value
        last_km = vehicle.last_service_odometer_km
        if last_km is not None and value < last_km:
            raise serializers.ValidationError(
                f"KM saat masuk ({_format_km(value)}) tidak boleh kurang dari "
                f"KM service terakhir ({_format_km(last_km)})."
            )
        return value
