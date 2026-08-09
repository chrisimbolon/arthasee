# =============================================================================
# === backend/apps/payments/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import Payment, Refund, SupplierPayment


class PaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(
        source="received_by.full_name", read_only=True, default=None,
    )

    class Meta:
        model  = Payment
        fields = [
            "id", "invoice", "amount", "method", "received_at",
            "reference", "notes", "received_by", "received_by_name", "created_at",
        ]
        read_only_fields = ["id", "invoice", "received_by", "received_by_name", "created_at"]


class PaymentRecordSerializer(serializers.Serializer):
    """
    Write-only input validation for POST /api/invoices/<id>/payments/.
    """
    amount      = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method      = serializers.ChoiceField(choices=Payment.METHOD_CHOICES, default="cash")
    received_at = serializers.DateTimeField(required=False, allow_null=True)
    reference   = serializers.CharField(required=False, allow_blank=True, default="")
    notes       = serializers.CharField(required=False, allow_blank=True, default="")


class RefundSerializer(serializers.ModelSerializer):
    refunded_by_name = serializers.CharField(
        source="refunded_by.full_name", read_only=True, default=None,
    )

    class Meta:
        model  = Refund
        fields = [
            "id", "invoice", "amount", "method", "refunded_at",
            "reference", "notes", "refunded_by", "refunded_by_name", "created_at",
        ]
        read_only_fields = ["id", "invoice", "amount", "refunded_by", "refunded_by_name", "created_at"]


class RefundRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/invoices/<id>/refund/. No amount
    field — a refund always covers the invoice's full total_paid.
    """
    method    = serializers.ChoiceField(choices=Payment.METHOD_CHOICES, default="cash")
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes     = serializers.CharField(required=False, allow_blank=True, default="")


class SupplierPaymentSerializer(serializers.ModelSerializer):
    paid_by_name = serializers.CharField(source="paid_by.full_name", read_only=True, default=None)

    class Meta:
        model  = SupplierPayment
        fields = [
            "id", "supplier_invoice", "amount", "method", "paid_at",
            "reference", "notes", "paid_by", "paid_by_name", "created_at",
        ]
        read_only_fields = ["id", "supplier_invoice", "amount", "paid_by", "paid_by_name", "created_at"]


class SupplierPaymentRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/supplier-invoices/<id>/pay/. No
    amount field — mirrors RefundRecordSerializer exactly:
    SupplierPayment.record() always pays supplier_invoice.amount in
    full (Sprint 3, Task 3.3's own scope — full-payment-only).
    """
    method    = serializers.ChoiceField(choices=Payment.METHOD_CHOICES, default="bank_transfer")
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes     = serializers.CharField(required=False, allow_blank=True, default="")
