# =============================================================================
# === backend/apps/payments/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import Payment, Refund


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
        # amount is read-only here too, but for a DIFFERENT reason
        # than the others — it's not merely server-managed metadata,
        # it's structurally computed (invoice.total_paid) and can
        # never be supplied by a caller at all. See
        # RefundRecordSerializer below, which has no amount field.
        read_only_fields = ["id", "invoice", "amount", "refunded_by", "refunded_by_name", "created_at"]


class RefundRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/invoices/<id>/refund/. No amount
    field — deliberately, per Task 2.3 Half B's own scope: a refund
    always covers the invoice's full total_paid, never a caller-
    supplied partial figure (Refund.record() computes it). Only HOW
    the money went back is a real choice here, and it's genuinely
    independent of whichever method(s) the original payment(s) used.
    """
    method    = serializers.ChoiceField(choices=Payment.METHOD_CHOICES, default="cash")
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes     = serializers.CharField(required=False, allow_blank=True, default="")
