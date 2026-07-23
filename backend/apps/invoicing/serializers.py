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

    class Meta:
        model  = Invoice
        fields = [
            "id", "service_record", "number", "sequence_number", "year",
            "customer_name_snapshot", "license_plate_snapshot",
            "status", "deposit_amount", "line_items",
            "subtotal", "total", "balance_due",
            "created_by", "created_by_name", "created_at",
        ]
        # Everything financial is read-only via this serializer —
        # invoices are created through InvoiceCreateView's own
        # snapshot logic, not a generic ModelSerializer.save(), and
        # nothing here supports editing an invoice after creation
        # except the dedicated status field (see InvoiceStatusUpdateView).
        read_only_fields = [
            "id", "number", "sequence_number", "year",
            "customer_name_snapshot", "license_plate_snapshot",
            "line_items", "subtotal", "total", "balance_due",
            "created_by", "created_by_name", "created_at",
        ]
