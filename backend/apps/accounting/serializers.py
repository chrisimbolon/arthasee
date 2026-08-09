# =============================================================================
# === backend/apps/accounting/serializers.py ===
# =============================================================================
"""
Arthasee — Accounting Serializers (Task 4.4)

Task 4.1's reporting views never needed this file — every report is
read-only, built straight from plain dicts in reports.py. Manual
journals are the first WRITE path apps.accounting has ever exposed
over HTTP, hence the first real input validation this app needs.
"""
from decimal import Decimal

from rest_framework import serializers

from .models import JournalEntry, JournalLine


class ManualJournalLineInputSerializer(serializers.Serializer):
    """
    account_code, not an Account UUID — same reasoning as
    apps.accounting.cancellations' own generic reversal logic and
    everything else touching the Chart of Accounts by hand: account
    codes are the one identifier in this whole system specifically
    designed to be typed directly by a human ("5003", "1301"), unlike
    Part/Supplier UUIDs elsewhere, which are opaque references nobody
    would type. Resolved against the acting organization in the view
    via Account.resolve() — never trusted as a bare lookup.
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
    rejects both a truly empty string and a whitespace-only one) —
    Task 4.4's own explicit requirement, unlike every domain-event-
    sourced JournalEntry, where memo is auto-generated and never
    required from a caller.
    """
    posting_date = serializers.DateField()
    reason       = serializers.CharField(max_length=500)
    lines        = ManualJournalLineInputSerializer(many=True)

    def validate_lines(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("Jurnal manual harus memiliki minimal dua baris.")
        return value


class ManualJournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model  = JournalLine
        fields = ["id", "account_code", "account_name", "debit_amount", "credit_amount", "description"]
        read_only_fields = fields


class ManualJournalEntrySerializer(serializers.ModelSerializer):
    lines           = ManualJournalLineSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = JournalEntry
        fields = [
            "id", "entry_number", "posting_date", "memo", "status",
            "created_by", "created_by_name", "created_at", "lines",
        ]
        read_only_fields = fields
