# =============================================================================
# === backend/apps/organizations/serializers.py ===
# =============================================================================
import re

from rest_framework import serializers

from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Organization
        # invoice_code added 5 Aug — Organization Settings needed
        # somewhere to actually display/confirm the current (possibly
        # auto-generated) code, and MyOrganizationView's own GET
        # response was silently omitting it entirely before this.
        fields = ["id", "name", "invoice_code", "plan", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class OrganizationSettingsUpdateSerializer(serializers.ModelSerializer):
    """
    Deliberately narrower than OrganizationSerializer above — an
    owner can self-edit their shop's own display name and invoice
    prefix through Organization Settings, but NEVER plan or
    is_active via this endpoint. Those are genuinely different
    concerns (billing tier, account suspension) that must never be
    self-service through a "customize my invoice code" settings
    screen — a real security boundary, not an oversight. See
    MyOrganizationView.patch() for the accompanying owner-only role
    check.
    """
    class Meta:
        model  = Organization
        fields = ["name", "invoice_code"]

    def validate_invoice_code(self, value):
        # Blank is explicitly allowed here — an owner clearing the
        # field is a real, valid choice (falls back to the same
        # hard-block Invoice.save() already enforces for a genuinely
        # unset code, not a new failure mode this introduces).
        value = value.strip().upper()
        if value and not re.match(r"^[A-Z0-9]{1,10}$", value):
            raise serializers.ValidationError(
                "Kode invoice hanya boleh berisi huruf dan angka, maksimal 10 karakter."
            )
        return value
