# =============================================================================
# === backend/apps/leads/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import RejectedQuote


class RejectedQuoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = RejectedQuote
        fields = [
            "id", "name", "phone", "vehicle_description",
            "quoted_description", "quoted_amount",
            "reason", "notes", "follow_up_status",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        # Deliberately no read_only_fields beyond the identity/audit
        # ones — unlike ServiceRecord/Invoice, this record is meant
        # to be edited freely (correcting a phone number, updating
        # follow_up_status as Made works through his call list, etc.)
        read_only_fields = ["id", "created_by", "created_by_name", "created_at", "updated_at"]
