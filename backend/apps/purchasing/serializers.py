# =============================================================================
# === backend/apps/purchasing/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import (GoodsReceivedNote, GoodsReceivedNoteLineItem,
                     PurchaseOrder, PurchaseOrderLineItem, PurchaseReturn,
                     PurchaseReturnLineItem, Supplier, SupplierInvoice)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Supplier
        fields = [
            "id", "name", "contact_person", "phone", "email",
            "address", "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class PurchaseOrderLineItemSerializer(serializers.ModelSerializer):
    part_name            = serializers.CharField(source="part.name", read_only=True)
    quantity_received     = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    quantity_outstanding  = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model  = PurchaseOrderLineItem
        fields = [
            "id", "part", "part_name", "quantity_ordered", "unit_cost",
            "quantity_received", "quantity_outstanding", "created_at",
        ]
        read_only_fields = fields  # output-only — writes go through PurchaseOrderRecordSerializer / the amend action


class PurchaseOrderSerializer(serializers.ModelSerializer):
    line_items           = PurchaseOrderLineItemSerializer(many=True, read_only=True)
    total_ordered_value  = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    supplier_name         = serializers.CharField(source="supplier.name", read_only=True)
    status_display         = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name         = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = PurchaseOrder
        fields = [
            "id", "number", "sequence_number", "supplier", "supplier_name",
            "status", "status_display", "order_date", "expected_date", "notes",
            "line_items", "total_ordered_value",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = fields  # output-only — writes go through PurchaseOrderRecordSerializer / the cancel action


class PurchaseOrderLineItemInputSerializer(serializers.Serializer):
    part             = serializers.UUIDField()
    quantity_ordered = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    unit_cost        = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class PurchaseOrderRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/purchase-orders/. Same
    UUIDField-not-PrimaryKeyRelatedField reasoning as every other
    Record serializer in this file — `supplier` and every line's
    `part` get resolved against the requesting user's own
    organization in the view.

    `status` only meaningfully accepts "DRAFT" as an override —
    anything else falls through to the real default, "ORDERED". Made
    creates and sends a PO in one action, confirmed directly; DRAFT
    is available for "still building this, haven't committed yet" but
    is never the silent default.
    """
    supplier      = serializers.UUIDField()
    order_date    = serializers.DateField()
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes         = serializers.CharField(required=False, allow_blank=True, default="")
    status        = serializers.ChoiceField(choices=["DRAFT", "ORDERED"], required=False, default="ORDERED")
    lines         = PurchaseOrderLineItemInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Purchase Order harus memiliki minimal satu item.")
        return value


class PurchaseOrderAmendQuantitySerializer(serializers.Serializer):
    """Write-only input for POST /api/purchase-order-line-items/<id>/amend/."""
    quantity_ordered = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

class GoodsReceivedNoteLineItemSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    subtotal  = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model  = GoodsReceivedNoteLineItem
        fields = [
            "id", "part", "part_name", "purchase_order_line_item",
            "quantity", "unit_cost", "subtotal", "created_at",
        ]
        read_only_fields = fields  # frozen — GRN and its lines are never edited, same as Invoice


class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
    line_items            = GoodsReceivedNoteLineItemSerializer(many=True, read_only=True)
    total_cost            = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    supplier_name          = serializers.CharField(source="supplier.name", read_only=True)
    purchase_order_number  = serializers.CharField(source="purchase_order.number", read_only=True)
    received_by_name       = serializers.CharField(source="received_by.full_name", read_only=True, default=None)

    class Meta:
        model  = GoodsReceivedNote
        fields = [
            "id", "number", "sequence_number", "supplier", "supplier_name",
            "purchase_order", "purchase_order_number", "supplier_invoice",
            "received_at", "reference", "notes",
            "received_by", "received_by_name", "line_items", "total_cost", "created_at",
        ]
        read_only_fields = fields  # frozen document — no PATCH/PUT endpoint exists at all


class GoodsReceivedNoteLineItemInputSerializer(serializers.Serializer):
    """
    purchase_order_line_item, not part — every GRN line must trace
    back to an authorized PO line now (see GoodsReceivedNote.receive()'s
    own docstring for the real, confirmed hard-block reasoning); part
    is derived from that relation inside receive() itself, never
    re-entered here.
    """
    purchase_order_line_item = serializers.UUIDField()
    quantity                 = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    unit_cost                = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class GoodsReceivedNoteRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/goods-received-notes/.
    `purchase_order` is now REQUIRED — every real delivery must trace
    back to an authorized commitment. Same UUIDField-not-
    PrimaryKeyRelatedField reasoning as every other Record serializer
    in this file.
    """
    purchase_order = serializers.UUIDField()
    received_at    = serializers.DateTimeField(required=False, allow_null=True)
    reference      = serializers.CharField(required=False, allow_blank=True, default="")
    notes          = serializers.CharField(required=False, allow_blank=True, default="")
    lines          = GoodsReceivedNoteLineItemInputSerializer(many=True)

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

class PurchaseReturnLineItemSerializer(serializers.ModelSerializer):
    """
    part_name and unit_cost both read through PurchaseReturnLineItem's
    own @property chain back to the ORIGINAL GoodsReceivedNoteLineItem
    being returned against — DRF's source traversal calls the model
    property directly, same as GoodsReceivedNoteLineItemSerializer's
    own part_name does for a real FK.
    """
    part_name = serializers.CharField(source="part.name", read_only=True)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    subtotal  = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model  = PurchaseReturnLineItem
        fields = [
            "id", "goods_received_note_line_item", "part_name",
            "quantity", "unit_cost", "subtotal", "created_at",
        ]
        read_only_fields = fields  # frozen — same discipline as GoodsReceivedNoteLineItemSerializer

class PurchaseReturnSerializer(serializers.ModelSerializer):
    line_items         = PurchaseReturnLineItemSerializer(many=True, read_only=True)
    total_value        = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    goods_received_note_number = serializers.CharField(source="goods_received_note.number", read_only=True)
    created_by_name    = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    classification_display = serializers.CharField(source="get_return_classification_display", read_only=True)

    class Meta:
        model  = PurchaseReturn
        fields = [
            "id", "number", "sequence_number", "goods_received_note",
            "goods_received_note_number", "return_date", "reason",
            "return_classification", "classification_display",
            "line_items", "total_value", "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = fields  # system-determined at creation, never user-editable — see the model field's own docstring


class PurchaseReturnLineItemInputSerializer(serializers.Serializer):
    """
    grn_line_item, not part+quantity+unit_cost — unit_cost is always
    a real snapshot from the ORIGINAL GoodsReceivedNoteLineItem being
    returned against, never re-entered by the caller. Same "history
    should not move" reasoning as PartUsage.unit_price_at_time.
    """
    grn_line_item = serializers.UUIDField()
    quantity      = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))


class PurchaseReturnRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/purchase-returns/. Same
    UUIDField-not-PrimaryKeyRelatedField reasoning as
    GoodsReceivedNoteRecordSerializer above — `goods_received_note`
    and every line's `grn_line_item` get resolved against the
    requesting user's own organization in the view, never trusted
    directly.
    """
    goods_received_note = serializers.UUIDField()
    return_date          = serializers.DateTimeField(required=False, allow_null=True)
    reason                = serializers.CharField()
    lines                 = PurchaseReturnLineItemInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Minimal harus ada satu item.")
        return value

    def validate_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("Alasan retur wajib diisi.")
        return value