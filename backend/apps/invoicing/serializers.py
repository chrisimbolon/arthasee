# =============================================================================
# === backend/apps/invoicing/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import Invoice, InvoiceLineItem


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    subtotal  = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    part_name = serializers.CharField(source="part.name", read_only=True, default=None)

    class Meta:
        model  = InvoiceLineItem
        fields = ["id", "kind", "description", "quantity", "unit_price", "part", "part_name", "subtotal"]
        read_only_fields = ["id", "subtotal", "part_name"]


class InvoiceSerializer(serializers.ModelSerializer):
    line_items      = InvoiceLineItemSerializer(many=True, read_only=True)
    subtotal        = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total           = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    balance_due     = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    # Not on the model itself — Invoice only has a direct FK to
    # ServiceRecord, not Vehicle. The frontend's "back to vehicle"
    # link needs the Vehicle's id specifically (that's what
    # /dashboard/vehicle-detail?id= expects), not the ServiceRecord's
    # — using service_record's own id there was the actual bug this
    # field exists to fix.
    vehicle_id = serializers.SerializerMethodField()

    class Meta:
        model  = Invoice
        fields = [
            "id", "service_record", "vehicle_id", "number", "sequence_number", "year",
            "customer_name_snapshot", "license_plate_snapshot",
            "status", "deposit_amount", "line_items",
            "subtotal", "total", "balance_due",
            "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = [
            "id", "vehicle_id", "number", "sequence_number", "year",
            "customer_name_snapshot", "license_plate_snapshot",
            "line_items", "subtotal", "total", "balance_due",
            "created_by", "created_by_name", "created_at",
        ]

    def get_vehicle_id(self, obj):
        return obj.service_record.vehicle_id
