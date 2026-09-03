# =============================================================================
# === backend/apps/accounting/serializers.py ===
# =============================================================================
from decimal import Decimal

from apps.core.models import Outbox
from rest_framework import serializers

from .models import (Account, AccountingPeriod, Asset, AssetDepreciationEntry,
                     DepreciationRun, JournalEntry, JournalLine,
                     OpeningBalanceAssetLine, OpeningBalanceCashLine,
                     OpeningBalanceOtherLine, OpeningBalancePartLine,
                     OpeningBalancePayable, OpeningBalanceReceivable,
                     OpeningBalanceSession)


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


class AssetSerializer(serializers.ModelSerializer):
    """
    29 Aug 2026 — real fixed asset register, Made's own confirmed
    request. monthly_depreciation/accumulated_depreciation/book_value
    are real Python properties on the model, computed on read from
    AssetDepreciationEntry rows — same "never trust a second source
    of truth" discipline as every other computed property in this
    codebase (Invoice.subtotal, Account.balance(), etc.), never
    cached fields that could drift.

    Entirely read-only — an Asset is only ever created via the real
    Asset.record() (which also posts its own acquisition journal
    entry in the same transaction), never through a generic
    serializer.save().
    """
    monthly_depreciation     = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    accumulated_depreciation = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    book_value               = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    created_by_name          = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = Asset
        fields = [
            "id", "number", "sequence_number", "name", "acquisition_date",
            "cost", "useful_life_months", "method", "is_active",
            "monthly_depreciation", "accumulated_depreciation", "book_value",
            "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = fields


class AssetRecordSerializer(serializers.Serializer):
    """
    Write-only input for POST /api/accounting/assets/. No salvage
    value field — Chris's own confirmed call, v1 always assumes 0
    (see Asset's own docstring in models.py) — asking for one on
    every asset would slow down exactly the kind of fast,
    low-ceremony entry this system optimizes for elsewhere
    (QuickPurchase, OperatingExpense).
    """
    name               = serializers.CharField(max_length=200)
    acquisition_date   = serializers.DateField()
    cost               = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    useful_life_months = serializers.IntegerField(min_value=1)
    method             = serializers.ChoiceField(choices=[("cash", "Tunai"), ("bank", "Transfer Bank")], default="cash")


class AssetDepreciationEntrySerializer(serializers.ModelSerializer):
    """One real, granular line in a DepreciationRun's own itemized
    breakdown — see that serializer's own docstring below."""
    asset_id     = serializers.UUIDField(source="asset.id", read_only=True)
    asset_number = serializers.CharField(source="asset.number", read_only=True)
    asset_name   = serializers.CharField(source="asset.name", read_only=True)

    class Meta:
        model  = AssetDepreciationEntry
        fields = ["id", "asset_id", "asset_number", "asset_name", "amount", "created_at"]
        read_only_fields = fields


class DepreciationRunSerializer(serializers.ModelSerializer):
    """
    29 Aug 2026 — Chris's own confirmed granularity call: one
    consolidated Dr 6004 / Cr 1402 journal entry per period on the
    Jurnal page, with the real, itemized per-asset breakdown
    retrievable underneath via `entries` here.
    """
    entries          = AssetDepreciationEntrySerializer(many=True, read_only=True)
    journal_entry_id = serializers.UUIDField(source="journal_entry.id", read_only=True, default=None)

    class Meta:
        model  = DepreciationRun
        fields = ["id", "accounting_period", "journal_entry_id", "total_amount", "run_at", "entries"]
        read_only_fields = fields


# =============================================================================
# Opening Balance — new-workshop onboarding (3 Sep 2026)
# =============================================================================
"""
Same real split every other write path in this file already
establishes: a plain ModelSerializer for the READ representation
(entirely read-only — every OpeningBalance* row is only ever created
through its own real model logic, never a generic serializer.save()),
and a separate, dedicated `...RecordSerializer` for the WRITE input,
matching AssetRecordSerializer/ManualJournalRecordSerializer's own
exact naming and shape.
"""

class OpeningBalanceCashLineSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OpeningBalanceCashLine
        fields = ["id", "account_code", "amount", "created_at"]
        read_only_fields = fields


class OpeningBalanceCashLineRecordSerializer(serializers.Serializer):
    """
    Write-only input for the cash/bank upsert endpoint.
    account_code is a real ChoiceField mirroring the model's own
    ACCOUNT_CHOICES exactly (1001/1101 only) — Cash and Bank are the
    only two accounts this whole onboarding step ever touches
    directly, per Chris's own signed-off subledger strategy.
    """
    account_code = serializers.ChoiceField(choices=OpeningBalanceCashLine.ACCOUNT_CHOICES)
    amount       = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))


class OpeningBalancePartLineSerializer(serializers.ModelSerializer):
    part_id = serializers.UUIDField(source="part.id", read_only=True, default=None)

    class Meta:
        model  = OpeningBalancePartLine
        fields = ["id", "part_name", "sku", "unit", "quantity", "cost_price", "part_id", "created_at"]
        read_only_fields = fields


class OpeningBalancePartLineRecordSerializer(serializers.Serializer):
    """
    part_name is freeform text here, deliberately NOT a Part UUID —
    unlike every other real Part reference in this system, this line
    describes a part that may not exist as a real Part row yet at
    all (that's the whole point — see OpeningBalanceSession.post()'s
    own logic in models.py, which creates the real Part the moment
    the session posts, never before).
    """
    part_name  = serializers.CharField(max_length=200)
    sku        = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    unit       = serializers.CharField(max_length=20, default="pcs")
    quantity   = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    cost_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class OpeningBalanceAssetLineSerializer(serializers.ModelSerializer):
    asset_id = serializers.UUIDField(source="asset.id", read_only=True, default=None)

    class Meta:
        model  = OpeningBalanceAssetLine
        fields = ["id", "name", "current_book_value", "remaining_useful_life_months", "asset_id", "created_at"]
        read_only_fields = fields


class OpeningBalanceAssetLineRecordSerializer(serializers.Serializer):
    """
    current_book_value/remaining_useful_life_months, deliberately NOT
    the asset's real original cost/acquisition_date/useful_life — see
    this app's own module docstring on models.py and Asset.record()'s
    own post_acquisition_entry parameter for the full reasoning this
    reframing exists to prevent (a legacy asset silently depreciating
    from zero, as if bought today).
    """
    name = serializers.CharField(max_length=200)
    current_book_value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    remaining_useful_life_months = serializers.IntegerField(min_value=1)


class OpeningBalanceReceivableSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model  = OpeningBalanceReceivable
        fields = ["id", "customer", "customer_name", "balance_due", "due_date", "reference", "created_at"]
        read_only_fields = fields


class OpeningBalanceReceivableRecordSerializer(serializers.Serializer):
    """
    customer is a real UUID here, not a name — unlike part_name
    above (deliberately freeform, since no real Part exists yet), a
    Customer is always a real, existing row the wizard resolves via
    a picker or the established inline-add pattern (Cheat Sheet §7),
    same "opaque reference, never typed directly" treatment every
    other real FK in this system already gets.
    """
    customer    = serializers.UUIDField()
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    due_date    = serializers.DateField(required=False, allow_null=True)
    reference   = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class OpeningBalancePayableSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model  = OpeningBalancePayable
        fields = ["id", "supplier", "supplier_name", "balance_due", "due_date", "reference", "created_at"]
        read_only_fields = fields


class OpeningBalancePayableRecordSerializer(serializers.Serializer):
    """Mirrors OpeningBalanceReceivableRecordSerializer exactly, inverted."""
    supplier    = serializers.UUIDField()
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    due_date    = serializers.DateField(required=False, allow_null=True)
    reference   = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class OpeningBalanceOtherLineSerializer(serializers.ModelSerializer):
    account_name = serializers.SerializerMethodField()

    class Meta:
        model  = OpeningBalanceOtherLine
        fields = ["id", "account_code", "account_name", "side", "amount", "description", "created_at"]
        read_only_fields = fields

    def get_account_name(self, obj):
        """
        Best-effort, not a hard requirement — account_code is only
        ever validated as a REAL account at post() time
        (Account.resolve() inside OpeningBalanceSession.post()), not
        at line-creation time, matching every other line category's
        own "collect first, validate everything together at post()"
        shape. A not-yet-resolvable code here just shows no name
        rather than failing the whole read.
        """
        account = Account.objects.filter(organization=obj.organization, code=obj.account_code).first()
        return account.name if account else None


class OpeningBalanceOtherLineRecordSerializer(serializers.Serializer):
    """
    The deliberate, honest escape hatch — a real account_code and an
    explicit side, resolved through the exact same Account.resolve()
    every other real posting in this system uses. Not validated
    against a real Account at THIS layer (same "collect first,
    validate together at post() time" reasoning as every sibling
    RecordSerializer above) — a genuinely invalid code only surfaces
    as a real, clear ValueError from OpeningBalanceSession.post()
    itself, same failure shape every other bad account_code in this
    codebase already produces via Account.resolve().
    """
    account_code = serializers.CharField(max_length=10)
    side         = serializers.ChoiceField(choices=OpeningBalanceOtherLine.Side.choices)
    amount       = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    description  = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class OpeningBalanceSessionSerializer(serializers.ModelSerializer):
    """
    The real, nested representation of one org's entire opening
    balance session — every line item across all six categories,
    plus a live-computed total_debit/total_credit/is_balanced/
    difference, mirroring the exact "✓ BALANCED & SUBLEDGERS MATCHED"
    badge the wizard's own Step 3 needs to render in real time.

    Deliberately NOT the same code path as OpeningBalanceSession.
    post()'s own balance check — that one runs inside
    JournalEntry.post(), against the real, final assembled lines, and
    is the one true source of "does this actually balance." This
    serializer's own totals are a client-facing PREVIEW, computed the
    same way (every cash/part/asset/receivable line is a debit;
    every payable line is a credit; every other line follows its own
    explicit side) so the wizard can show real-time feedback without
    attempting a real post() on every keystroke — both are proven
    equivalent by construction against post()'s own real line-
    assembly logic in models.py, not independently reinvented.

    Queryset optimization is the VIEW's responsibility, not this
    serializer's — the six nested relations below should be
    prefetch_related() at the view layer before this ever renders, or
    every one of the four get_*() methods below re-walks its own
    querysets from scratch (they deliberately call obj.cash_lines.
    all() etc. multiple times each, trading a little duplicate
    Python-side work for keeping four separate, individually
    readable total functions instead of one dense combined one).
    """
    cash_lines       = OpeningBalanceCashLineSerializer(many=True, read_only=True)
    part_lines       = OpeningBalancePartLineSerializer(many=True, read_only=True)
    asset_lines      = OpeningBalanceAssetLineSerializer(many=True, read_only=True)
    receivable_lines = OpeningBalanceReceivableSerializer(many=True, read_only=True)
    payable_lines    = OpeningBalancePayableSerializer(many=True, read_only=True)
    other_lines      = OpeningBalanceOtherLineSerializer(many=True, read_only=True)

    total_debit  = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()
    is_balanced  = serializers.SerializerMethodField()
    difference   = serializers.SerializerMethodField()

    posted_by_name   = serializers.CharField(source="posted_by.full_name", read_only=True, default=None)
    journal_entry_id = serializers.UUIDField(source="journal_entry.id", read_only=True, default=None)

    class Meta:
        model  = OpeningBalanceSession
        fields = [
            "id", "start_date", "status",
            "cash_lines", "part_lines", "asset_lines",
            "receivable_lines", "payable_lines", "other_lines",
            "total_debit", "total_credit", "is_balanced", "difference",
            "journal_entry_id", "posted_at", "posted_by", "posted_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_total_debit(self, obj):
        total = sum((c.amount for c in obj.cash_lines.all()), Decimal("0"))
        total += sum((p.quantity * p.cost_price for p in obj.part_lines.all()), Decimal("0"))
        total += sum((a.current_book_value for a in obj.asset_lines.all()), Decimal("0"))
        total += sum((r.balance_due for r in obj.receivable_lines.all()), Decimal("0"))
        total += sum(
            (o.amount for o in obj.other_lines.all() if o.side == OpeningBalanceOtherLine.Side.DEBIT),
            Decimal("0"),
        )
        return total

    def get_total_credit(self, obj):
        total = sum((p.balance_due for p in obj.payable_lines.all()), Decimal("0"))
        total += sum(
            (o.amount for o in obj.other_lines.all() if o.side == OpeningBalanceOtherLine.Side.CREDIT),
            Decimal("0"),
        )
        return total

    def get_is_balanced(self, obj):
        return self.get_total_debit(obj) == self.get_total_credit(obj)

    def get_difference(self, obj):
        # Signed, deliberately — a positive number means debits are
        # ahead (more Assets than Liabilities+Equity so far, the
        # normal mid-entry state before Owner Capital/Other lines
        # close the gap); negative means credits are ahead. The
        # wizard's own real-time badge can show this raw, or take
        # abs() itself for display — this serializer doesn't decide
        # that presentation choice.
        return self.get_total_debit(obj) - self.get_total_credit(obj)


class OpeningBalanceSessionRecordSerializer(serializers.Serializer):
    """
    Write-only input for creating the one real session an
    organization will ever have. Nothing else about the session is
    settable at creation — every line item is added afterward via its
    own dedicated endpoint, matching the real wizard flow (Step 1
    just establishes the accounting start date; everything else comes
    in Steps 2 onward).
    """
    start_date = serializers.DateField()
