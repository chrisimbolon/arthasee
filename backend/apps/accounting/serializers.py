# =============================================================================
# === backend/apps/accounting/serializers.py ===
# =============================================================================
from decimal import Decimal

from apps.core.models import Outbox
from rest_framework import serializers

from .models import AccountingPeriod, JournalEntry, JournalLine


class ManualJournalLineInputSerializer(serializers.Serializer):
    """
    account_code, not an Account UUID — account codes are the one
    identifier in this whole system specifically designed to be
    typed directly by a human ("5003", "1301"), unlike Part/Supplier
    UUIDs elsewhere, which are opaque references nobody would type.
    Resolved against the acting organization in the view via
    Account.resolve() — never trusted as a bare lookup.
    """
    account_code = serializers.CharField(max_length=10)
    debit        = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0"))
    credit       = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0"))

    def validate(self, data):
        debit  = data.get("debit") or Decimal("0")
        credit = data.get("credit") or Decimal("0")
        if (debit > 0) == (credit > 0):
            raise serializers.ValidationError(
                "Setiap baris harus memiliki TEPAT SATU dari debit atau kredit — tidak keduanya, tidak tidak sama sekali."
            )
        return data


class ManualJournalRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/accounting/manual-journals/.
    `reason` is required (CharField's own default allow_blank=False,
    combined with DRF's default trim_whitespace=True, correctly
    rejects both a truly empty string and a whitespace-only one).
    """
    posting_date = serializers.DateField()
    reason       = serializers.CharField(max_length=500)
    lines        = ManualJournalLineInputSerializer(many=True)

    def validate_lines(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("Jurnal manual harus memiliki minimal dua baris.")
        return value


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model  = JournalLine
        fields = ["id", "account_code", "account_name", "debit_amount", "credit_amount", "description"]
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):
    """
    Task 5.2 — renamed from ManualJournalEntrySerializer (Task 4.4).
    Shared by the manual-journal endpoints AND the general journal-
    entries list — one real shape for "what a posted JournalEntry
    looks like over the API," not two near-identical copies that
    could quietly drift. source/event_type are what actually
    distinguish entries in the general list view; they were always
    on the model, just never surfaced when every caller of the old
    manual-only serializer already knew the answer (source is always
    MANUAL there).
    """
    lines           = JournalLineSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = JournalEntry
        fields = [
            "id", "entry_number", "posting_date", "source", "event_type",
            "memo", "status", "created_by", "created_by_name", "created_at", "lines",
        ]
        read_only_fields = fields


class FailedPostingSerializer(serializers.ModelSerializer):
    """
    Task 5.2 — the real point of this whole task. A failed domain-
    event posting never produces a JournalEntry at all (that's what
    "failed" means); the only trace of it is this Outbox row. This
    is the shape that gives a shop owner a real way to SEE that,
    instead of discovering it because a report looked wrong — exactly
    what happened in production on Aug 10 2026 before this existed.
    """
    class Meta:
        model  = Outbox
        fields = [
            "id", "event_id", "event_type", "payload", "occurred_at",
            "attempts", "last_error", "processed_at", "created_at",
        ]
        read_only_fields = fields


class AccountingPeriodSerializer(serializers.ModelSerializer):
    """
    28 Aug 2026 — real month-end closing, Made's own confirmed
    requirement via his tax & accounting consultant. Entirely read-
    only — a period is only ever created via
    periods.ensure_period_for_org() and only ever transitions via the
    real period.close()/period.reopen() model methods, never through
    a generic serializer.save().
    """
    is_open_for_posting = serializers.BooleanField(read_only=True)
    closed_by_name = serializers.CharField(source="closed_by.full_name", read_only=True, default=None)
    reopened_by_name = serializers.CharField(source="reopened_by.full_name", read_only=True, default=None)

    class Meta:
        model  = AccountingPeriod
        fields = [
            "id", "year", "month", "start_date", "end_date",
            "is_closed", "is_locked", "is_open_for_posting",
            "closed_at", "closed_by", "closed_by_name",
            "reopened_at", "reopened_by", "reopened_by_name",
            "created_at",
        ]
        read_only_fields = fields
