# =============================================================================
# === backend/apps/payments/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import Payment


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

    Deliberately a plain Serializer, not a ModelSerializer — `invoice`
    and `received_by` are supplied by the view (from the URL and
    request.user), never accepted from the request body. min_value
    here catches a zero/negative amount before it ever reaches
    Payment.record() — that method still checks it again too (defense
    in depth, same layered-validation style already used throughout
    this codebase, e.g. Invoice.save()'s own checks existing
    alongside view-level ones).
    """
    amount      = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method      = serializers.ChoiceField(choices=Payment.METHOD_CHOICES, default="cash")
    received_at = serializers.DateTimeField(required=False, allow_null=True)
    reference   = serializers.CharField(required=False, allow_blank=True, default="")
    notes       = serializers.CharField(required=False, allow_blank=True, default="")
