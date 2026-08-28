# =============================================================================
# === backend/apps/payments/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import OperatingExpense, Payment, Refund, SupplierPayment


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


class OperatingExpenseSerializer(serializers.ModelSerializer):
    """
    27 Aug 2026 — Made's own confirmed real request. Entirely read-
    only from this serializer's own point of view — always created
    via the real OperatingExpense.record(), never a generic
    serializer.save().
    """
    account_code    = serializers.CharField(source="account.code", read_only=True)
    account_name    = serializers.CharField(source="account.name", read_only=True)
    mechanic_name   = serializers.CharField(source="mechanic.name", read_only=True, default=None)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = OperatingExpense
        fields = [
            "id", "number", "sequence_number", "account", "account_code", "account_name",
            "amount", "method", "paid_at", "mechanic", "mechanic_name",
            "reference", "notes", "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = fields


class OperatingExpenseRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/operating-expenses/. account_code,
    not an Account UUID — same real-code-as-identifier reasoning
    ManualJournalLineInputSerializer's own account_code field already
    established: a real business-meaningful code, not an opaque
    reference, resolved against the acting organization in the view
    via Account.resolve(), never trusted as a bare lookup.

    Deliberately only cash/bank here, not Payment's own full
    METHOD_CHOICES — matches OperatingExpense.method's own real,
    confirmed 2-option field exactly.
    """
    account_code = serializers.CharField(max_length=10)
    amount       = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method       = serializers.ChoiceField(choices=[("cash", "Tunai"), ("bank", "Transfer Bank")], default="cash")
    paid_at      = serializers.DateTimeField(required=False, allow_null=True)
    mechanic     = serializers.UUIDField(required=False, allow_null=True)
    reference    = serializers.CharField(required=False, allow_blank=True, default="")
    notes        = serializers.CharField(required=False, allow_blank=True, default="")
