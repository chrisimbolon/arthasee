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


class OnboardingCompleteSerializer(serializers.ModelSerializer):
    """
    29 Aug 2026 — the real, single-purpose entry point behind the
    mandatory first-login welcome gate (Chris's own confirmed
    design). Deliberately separate from OrganizationSettingsUpdateSerializer
    above — that endpoint keeps every field genuinely optional for
    ongoing edits later; this one enforces phone/address/invoice_code
    as real, required inputs at the SERVER layer too, not just
    trusted from the frontend form's own required-field validation
    ("strictly required inputs on the frontend onboarding form" was
    Chris's own confirmed call — a real business rule deserves a real
    server-side guarantee, not just a client-side one). Also the one
    real place onboarding_completed ever flips to True.
    """
    phone        = serializers.CharField(max_length=30, required=True, allow_blank=False)
    address      = serializers.CharField(required=True, allow_blank=False)
    invoice_code = serializers.CharField(max_length=10, required=True, allow_blank=False)

    class Meta:
        model  = Organization
        fields = ["phone", "address", "invoice_code"]

    def validate_invoice_code(self, value):
        # Same real validation as OrganizationSettingsUpdateSerializer
        # above, minus the "blank is allowed" exception — a blank
        # code is never a valid choice during onboarding itself,
        # unlike a later, deliberate clear-out in Settings.
        value = value.strip().upper()
        if not re.match(r"^[A-Z0-9]{1,10}$", value):
            raise serializers.ValidationError(
                "Kode invoice hanya boleh berisi huruf dan angka, maksimal 10 karakter."
            )
        return value

    def update(self, instance, validated_data):
        # Reuses ModelSerializer's own real update() for the three
        # genuine fields, then does one additional, explicit save for
        # the flag — not folded into the same call, so it's clear at
        # a glance this is the one real place onboarding_completed
        # gets set, not an incidental side effect buried in a bulk
        # field assignment.
        instance = super().update(instance, validated_data)
        instance.onboarding_completed = True
        instance.save(update_fields=["onboarding_completed"])
        return instance
