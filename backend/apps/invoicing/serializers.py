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
    # 15 Sep 2026 — is_overdue is a real Python property on the model
    # (models.py), not a DB field — same treatment subtotal/total/
    # balance_due above already establish for THEIR OWN properties: a
    # declared field naming the property directly, not a
    # SerializerMethodField (that's reserved for vehicle_id below,
    # which genuinely needs custom traversal logic; is_overdue needs
    # none).
    is_overdue = serializers.BooleanField(read_only=True)
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
            "customer_name_snapshot", "license_plate_snapshot", "mechanic_name_snapshot",
            "status", "deposit_amount", "due_date", "is_overdue", "line_items",
            "subtotal", "total", "balance_due",
            "created_by", "created_by_name", "created_at",
        ]
        # 15 Sep 2026 — due_date joins read_only_fields even though
        # the underlying model field itself IS writable: this
        # serializer is only ever used for the RESPONSE representation
        # (InvoiceSerializer(invoice).data) — real creation already
        # writes due_date directly via Invoice.objects.create() in
        # InvoiceCreateView.post() (views.py), never through this
        # serializer's own .save(). Matches every other frozen/
        # snapshot-style field already in this list, which follows
        # the identical "read here, write through a real dedicated
        # path" split. is_overdue is read_only for the more basic
        # reason every other derived property here already is — it's
        # not a real, settable field at all.
        read_only_fields = [
            "id", "vehicle_id", "number", "sequence_number", "year",
            "customer_name_snapshot", "license_plate_snapshot", "mechanic_name_snapshot",
            "due_date", "is_overdue", "line_items", "subtotal", "total", "balance_due",
            "created_by", "created_by_name", "created_at",
        ]

    def get_vehicle_id(self, obj):
        return obj.service_record.vehicle_id
