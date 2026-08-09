# =============================================================================
# === backend/apps/purchasing/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import GoodsReceivedNote, GoodsReceivedNoteLineItem, Supplier, SupplierInvoice


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Supplier
        fields = [
            "id", "name", "contact_person", "phone", "email",
            "address", "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class GoodsReceivedNoteLineItemSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    subtotal  = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model  = GoodsReceivedNoteLineItem
        fields = ["id", "part", "part_name", "quantity", "unit_cost", "subtotal", "created_at"]
        read_only_fields = fields  # frozen — GRN and its lines are never edited, same as Invoice


class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
    line_items        = GoodsReceivedNoteLineItemSerializer(many=True, read_only=True)
    total_cost        = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    supplier_name     = serializers.CharField(source="supplier.name", read_only=True)
    received_by_name  = serializers.CharField(source="received_by.full_name", read_only=True, default=None)

    class Meta:
        model  = GoodsReceivedNote
        fields = [
            "id", "number", "sequence_number", "supplier", "supplier_name",
            "supplier_invoice", "received_at", "reference", "notes",
            "received_by", "received_by_name", "line_items", "total_cost", "created_at",
        ]
        read_only_fields = fields  # frozen document — no PATCH/PUT endpoint exists at all


class GoodsReceivedNoteLineItemInputSerializer(serializers.Serializer):
    part      = serializers.UUIDField()
    quantity  = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class GoodsReceivedNoteRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/goods-received-notes/. `supplier`
    and each line's `part` are plain UUIDFields, not
    PrimaryKeyRelatedField — deliberately: PrimaryKeyRelatedField's
    default queryset has no organization filter, which would let a
    request reference another shop's Supplier/Part and have DRF
    accept it at the serializer layer, before any real tenant check
    ever runs. The view resolves both against the requesting user's
    own organization explicitly (Supplier.objects.filter(organization=...,
    pk=...) / Part.objects.filter(organization=..., pk=...)) — same
    hand-rolled tenant-scoped lookup pattern
    InvoiceCreateView._get_service_record() already established.
    """
    supplier    = serializers.UUIDField()
    received_at = serializers.DateTimeField(required=False, allow_null=True)
    reference   = serializers.CharField(required=False, allow_blank=True, default="")
    notes       = serializers.CharField(required=False, allow_blank=True, default="")
    lines       = GoodsReceivedNoteLineItemInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Minimal harus ada satu item.")
        return value


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    supplier_name         = serializers.CharField(source="supplier.name", read_only=True)
    goods_received_notes  = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model  = SupplierInvoice
        fields = [
            "id", "number", "sequence_number", "supplier", "supplier_name",
            "supplier_invoice_number", "goods_received_notes", "amount",
            "invoice_date", "due_date", "status", "notes", "created_by", "created_at",
        ]
        read_only_fields = fields


class SupplierInvoiceRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/supplier-invoices/. Same
    UUIDField-not-PrimaryKeyRelatedField reasoning as
    GoodsReceivedNoteRecordSerializer above — `supplier` and every id
    in `goods_received_note_ids` get resolved against the requesting
    user's own organization in the view, never trusted directly.
    """
    supplier                 = serializers.UUIDField()
    amount                   = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    invoice_date             = serializers.DateField()
    due_date                 = serializers.DateField(required=False, allow_null=True)
    supplier_invoice_number  = serializers.CharField(required=False, allow_blank=True, default="")
    notes                    = serializers.CharField(required=False, allow_blank=True, default="")
    goods_received_note_ids  = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )
