# =============================================================================
# === backend/apps/letters/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import IncomingLetter, OutgoingLetter


class OutgoingLetterSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OutgoingLetter
        fields = ["id", "number", "recipient", "subject", "source", "created_at"]
        read_only_fields = ["id", "number", "source", "created_at"]


class OutgoingLetterCreateSerializer(serializers.ModelSerializer):
    """
    Deliberately only recipient/subject — the standalone "Buat Surat"
    path, Chris's own confirmed shape: "custom recipient/subject for
    general business needs outside a Work Order." number/source/
    estimate/contract_import are never client-settable — number is
    always generated in save() itself, and source is hard-set to
    STANDALONE in the view for anything created through this path
    (see OutgoingLetterListView.post()).
    """
    class Meta:
        model  = OutgoingLetter
        fields = ["recipient", "subject"]


class IncomingLetterSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    vehicle_plate = serializers.CharField(source="vehicle.plate_number", read_only=True, default=None)

    class Meta:
        model  = IncomingLetter
        fields = [
            "id", "sender", "subject", "letter_date", "received_date", "file",
            "customer", "customer_name", "vehicle", "vehicle_plate", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        # Real, cheap sanity check — a vehicle genuinely belongs to a
        # customer in this app's data model, so a letter linked to a
        # vehicle but a DIFFERENT customer than that vehicle's own
        # owner would be a real, silent inconsistency the moment it
        # showed up on the wrong customer's history timeline.
        customer = attrs.get("customer")
        vehicle = attrs.get("vehicle")
        if customer and vehicle and vehicle.customer_id != customer.id:
            raise serializers.ValidationError(
                "Kendaraan yang dipilih bukan milik pelanggan yang dipilih."
            )
        return attrs
