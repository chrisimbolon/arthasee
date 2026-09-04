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
        # phone/address/onboarding_completed added 29 Aug 2026 — the
        # real onboarding gate needs onboarding_completed to decide
        # whether to intercept at all, and Settings needs phone/
        # address surfaced the same way invoice_code already is.
        fields = ["id", "name", "invoice_code", "phone", "address", "onboarding_completed", "plan", "is_active", "created_at"]
        read_only_fields = ["id", "onboarding_completed", "created_at"]


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
        # phone/address added 29 Aug 2026 — same "everything gathered
        # at onboarding stays editable in Settings afterward"
        # philosophy Chris's own confirmed design already applies to
        # invoice_code. onboarding_completed deliberately NOT here —
        # that flag only ever moves via OnboardingCompleteSerializer
        # below, never a generic settings edit.
        fields = ["name", "invoice_code", "phone", "address"]

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
