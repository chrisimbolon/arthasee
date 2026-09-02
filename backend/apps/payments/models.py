# =============================================================================
# === backend/apps/payments/models.py ===
# =============================================================================
"""
Arthasee — Payments

Three real write paths: Payment.record() (money in from customers),
Refund.record() (money back to customers), and SupplierPayment.record()
(money out to suppliers — Sprint 3, Task 3.3). All three mirror
JournalEntry.post() / WorkOrder.close()'s own shape: each owns its
own transaction.atomic(), validates before writing anything, and each
is the ONLY place its respective status transition happens anywhere
in the system.

SupplierPayment lives here, not in apps.purchasing, per the Roadmap's
own posting matrix — it lists SupplierPaymentMade under the payments
domain, not purchasing. Reuses Payment.METHOD_CHOICES directly, same
as Refund already does.

1 Sep 2026 — OperatingExpenseSequence/OperatingExpense (27 Aug) is
joined by InternalCashMutationSequence/InternalCashMutation: a real
internal cash movement (till -> bank, or bank -> till), Made's own
confirmed request while designing the Kas Harian dashboard. Mirrors
OperatingExpense's own skeleton exactly — same numbered-document
pattern, same "one classmethod is the only real entry point"
discipline.

2 Sep 2026 — Payment.record()/SupplierPayment.record()/
OperatingExpense.record() now thread a real display name
(customer_name/supplier_name/account_name) into their own published
event — real UX gap found on the Kas Harian dashboard: every memo
across the whole posting matrix was built from a raw ID, meaningless
in a friendly, owner-facing view. No new queries — each name was
already reachable off data already in hand at the point of
publishing.
"""
import uuid
from decimal import Decimal

from apps.core.models import TenantScopedModel
from django.db import models, transaction
from django.utils import timezone


class Payment(TenantScopedModel):
    """
    One real payment received against one Invoice. Multiple rows per
    Invoice are expected and normal, not an edge case — a deposit at
    intake followed by a balance payment at pickup is a genuinely
    common two-payment pattern in a real workshop.
    """
    METHOD_CHOICES = [
        ("cash",          "Tunai"),
        ("bank_transfer", "Transfer Bank"),
        ("qris",           "QRIS"),
        ("card",            "Kartu Debit/Kredit"),
        ("other",           "Lainnya"),
    ]

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(
        "invoicing.Invoice", on_delete=models.PROTECT, related_name="payments",
        verbose_name="Invoice",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah")
    method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default="cash", verbose_name="Metode",
    )
    received_at = models.DateTimeField(verbose_name="Waktu Diterima")
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Referensi",
        help_text="Nomor transfer, ID transaksi QRIS, dll — opsional.",
    )
    notes = models.TextField(blank=True, verbose_name="Catatan")
    received_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Diterima Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Payment"
        verbose_name_plural  = "Payments"
        ordering             = ["received_at"]

    def __str__(self):
        return f"{self.invoice.number} — {self.amount} ({self.get_method_display()})"

    def _resolve_organization(self):
        return self.invoice.organization

    @classmethod
    def record(
        cls, *, invoice, amount, method="cash", received_at=None,
        reference="", notes="", received_by=None,
    ):
        """
        The one real entry point for recording a payment — never
        construct Payment directly.

        Auto-transitions Invoice.status to "PAID" the moment
        balance_due actually reaches zero after this payment is
        recorded — re-derived from the DB-backed aggregate, not by
        trusting arithmetic on the in-memory `amount` argument alone.
        """
        if invoice.status != "ISSUED":
            raise ValueError(
                f"Tidak bisa mencatat pembayaran untuk invoice berstatus "
                f"'{invoice.get_status_display()}' — invoice harus berstatus "
                f"'Diterbitkan' terlebih dahulu."
            )
        if amount is None or amount <= Decimal("0"):
            raise ValueError("Jumlah pembayaran harus lebih dari nol.")
        if amount > invoice.balance_due:
            raise ValueError(
                f"Jumlah pembayaran ({amount}) melebihi sisa tagihan "
                f"({invoice.balance_due}) — kelebihan bayar belum didukung."
            )

        with transaction.atomic():
            payment = cls.objects.create(
                organization=invoice.organization,
                invoice=invoice,
                amount=amount,
                method=method,
                received_at=received_at or timezone.now(),
                reference=reference,
                notes=notes,
                received_by=received_by,
            )

            from apps.core.events.bus import default_bus
            from apps.payments.events import PaymentReceived
            default_bus.publish(PaymentReceived(
                organization_id=invoice.organization_id,
                invoice_id=invoice.id,
                payment_id=payment.id,
                amount=amount,
                method=method,
                # 2 Sep 2026 — real UX fix: an already-frozen snapshot
                # field on Invoice, threaded one hop further into the
                # event payload — no new query, no new source of
                # truth. See PaymentReceived's own docstring.
                customer_name=invoice.customer_name_snapshot,
            ))

            if invoice.balance_due <= Decimal("0"):
                invoice.status = "PAID"
                invoice.save(update_fields=["status"])

        return payment


class Refund(TenantScopedModel):
    """
    One real refund issued against one fully-PAID Invoice — the
    inverse of Payment. Reuses Payment.METHOD_CHOICES directly; a
    refund's own method is genuinely independent of how the original
    payment(s) came in.

    Deliberately full-invoice-only — Refund.record() requires status
    == "PAID" and always refunds the invoice's full total_paid, never
    a partial amount.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(
        "invoicing.Invoice", on_delete=models.PROTECT, related_name="refunds",
        verbose_name="Invoice",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah")
    method = models.CharField(
        max_length=20, choices=Payment.METHOD_CHOICES, default="cash", verbose_name="Metode",
    )
    refunded_at = models.DateTimeField(verbose_name="Waktu Refund")
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Referensi",
        help_text="Nomor transfer, ID transaksi refund, dll — opsional.",
    )
    notes = models.TextField(blank=True, verbose_name="Catatan")
    refunded_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Diproses Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Refund"
        verbose_name_plural  = "Refunds"
        ordering             = ["refunded_at"]

    def __str__(self):
        return f"{self.invoice.number} — refund {self.amount} ({self.get_method_display()})"

    def _resolve_organization(self):
        return self.invoice.organization

    @classmethod
    def record(cls, *, invoice, method="cash", refunded_at=None, reference="", notes="", refunded_by=None):
        """
        The one real entry point for recording a refund — never
        construct Refund directly. Deliberately no `amount` argument:
        the refund always covers the invoice's full total_paid.

        Sets Invoice.status to "CANCELLED" the moment the refund is
        recorded — same "one action does both the money and the
        status" symmetry as Payment.record()'s own transition to
        PAID, just inverted.
        """
        if invoice.status != "PAID":
            raise ValueError(
                f"Tidak bisa memproses refund untuk invoice berstatus "
                f"'{invoice.get_status_display()}' — invoice harus berstatus "
                f"'Lunas' terlebih dahulu."
            )

        amount = invoice.total_paid
        if amount <= Decimal("0"):
            raise ValueError("Invoice ini tidak memiliki riwayat pembayaran untuk di-refund.")

        with transaction.atomic():
            refund = cls.objects.create(
                organization=invoice.organization,
                invoice=invoice,
                amount=amount,
                method=method,
                refunded_at=refunded_at or timezone.now(),
                reference=reference,
                notes=notes,
                refunded_by=refunded_by,
            )

            invoice.status = "CANCELLED"
            invoice.save(update_fields=["status"])

            from apps.core.events.bus import default_bus
            from apps.invoicing.events import InvoiceRefunded
            default_bus.publish(InvoiceRefunded(
                organization_id=invoice.organization_id,
                invoice_id=invoice.id,
                refund_id=refund.id,
                issued_event_id=invoice.issued_event_id,
                amount=amount,
                method=method,
            ))

        return refund


class SupplierPayment(TenantScopedModel):
    """
    One real payment made TO a supplier against one SupplierInvoice
    (Sprint 3, Task 3.3) — mirrors Refund's own shape exactly
    (full-amount-only), not Payment's partial-amount support. Reuses
    Payment.METHOD_CHOICES directly, same as Refund does.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier_invoice = models.ForeignKey(
        "purchasing.SupplierInvoice", on_delete=models.PROTECT, related_name="supplier_payments",
        verbose_name="Invoice Supplier",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah")
    method = models.CharField(
        max_length=20, choices=Payment.METHOD_CHOICES, default="bank_transfer", verbose_name="Metode",
    )
    paid_at = models.DateTimeField(verbose_name="Waktu Dibayar")
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Referensi",
        help_text="Nomor transfer, referensi pembayaran, dll — opsional.",
    )
    notes = models.TextField(blank=True, verbose_name="Catatan")
    paid_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Dibayar Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Supplier Payment"
        verbose_name_plural  = "Supplier Payments"
        ordering             = ["paid_at"]

    def __str__(self):
        return f"{self.supplier_invoice.number} — {self.amount} ({self.get_method_display()})"

    def _resolve_organization(self):
        return self.supplier_invoice.organization

    @classmethod
    def record(cls, *, supplier_invoice, method="bank_transfer", paid_at=None, reference="", notes="", paid_by=None):
        """
        The one real entry point — never construct SupplierPayment
        directly. Full-invoice-only: amount is always
        supplier_invoice.amount, not an argument.

        Sets SupplierInvoice.status to "PAID" the moment payment is
        recorded — same "one action does both the money and the
        status" symmetry as Payment.record()/Refund.record().
        """
        if supplier_invoice.status != "UNPAID":
            raise ValueError(
                f"Invoice supplier ini berstatus '{supplier_invoice.get_status_display()}' — "
                f"tidak bisa dibayar lagi."
            )

        amount = supplier_invoice.amount

        with transaction.atomic():
            from apps.accounting.models import AccountingPeriod
            AccountingPeriod.assert_open_for_posting(
                supplier_invoice.organization, (paid_at or timezone.now()).date()
            )
            payment = cls.objects.create(
                organization=supplier_invoice.organization,
                supplier_invoice=supplier_invoice,
                amount=amount,
                method=method,
                paid_at=paid_at or timezone.now(),
                reference=reference,
                notes=notes,
                paid_by=paid_by,
            )

            supplier_invoice.status = "PAID"
            supplier_invoice.save(update_fields=["status"])

            from apps.core.events.bus import default_bus
            from apps.payments.events import SupplierPaymentMade
            default_bus.publish(SupplierPaymentMade(
                organization_id=supplier_invoice.organization_id,
                supplier_invoice_id=supplier_invoice.id,
                supplier_payment_id=payment.id,
                amount=amount,
                method=method,
                # 2 Sep 2026 — real UX fix: no existing snapshot field
                # for this one (unlike Invoice's own
                # customer_name_snapshot), so a live read at the
                # moment of payment, captured once. See
                # SupplierPaymentMade's own docstring.
                supplier_name=supplier_invoice.supplier.name,
            ))

        return payment


class OperatingExpenseSequence(TenantScopedModel):
    """Mirrors QuickPurchaseSequence exactly — same real numbering pattern."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Operating Expense Sequence"
        verbose_name_plural  = "Operating Expense Sequences"
        unique_together      = [("organization",)]

    def __str__(self):
        return f"{self.organization}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization):
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class OperatingExpense(TenantScopedModel):
    """
    A real, immediate cash outflow for a recurring operating cost —
    salary, rent, utilities, and so on. Made's own confirmed real
    request, 27 Aug meeting: a guided "Catat Beban Operasional" form,
    a real alternative to the generic Manual Adjusting Journal for
    exactly this recurring, routine kind of entry — no account codes,
    no debit/credit thinking required from Made himself.

    Lives here, not apps.purchasing — same Roadmap precedent already
    established for SupplierPayment: this is a real money-OUT event,
    not a purchasing concept.

    Deliberately single-line, unlike QuickPurchase's own multi-line
    design — one real expense payment is one category, one amount,
    one real transaction. No need to reinvent QuickPurchase's own
    multi-item complexity for a fundamentally simpler real-world fact.

    `account` is restricted to real, active EXPENSE-type accounts,
    EXCLUDING 6004 (Beban Penyusutan) — enforced in record() below,
    not just the frontend dropdown. 6004 is reserved for the real,
    separate depreciation engine (non-cash, credits a contra-asset
    account, not Cash/Bank) — posting a depreciation entry through
    this Cash/Bank-only form would produce a real, wrong journal
    entry, not just a cosmetic mismatch.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="operating_expenses",
        verbose_name="Akun Beban",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah")
    method = models.CharField(
        max_length=10, choices=[("cash", "Tunai"), ("bank", "Transfer Bank")],
        default="cash", verbose_name="Metode Pembayaran",
        # Deliberately only cash/bank, not Payment's own full
        # METHOD_CHOICES (qris/card/other) — matches QuickPurchase's
        # own real, confirmed 2-option payment_method exactly, since
        # this is the same "paid on the spot, cash or bank" real-
        # world event, not a customer-facing payment method choice.
    )
    paid_at = models.DateTimeField(verbose_name="Waktu Dibayar")
    # Made's own confirmed call, 27 Aug: optional attribution to a
    # specific mechanic, ONLY meaningful for Gaji Karyawan (6001) —
    # helps track labor efficiency against Made's own real
    # Rp15.000.000/bulan target per mechanic (see apps.workorders'
    # own Mechanic model). Nullable even for 6001 — "All / Lump Sum"
    # is a real, valid choice too; not every payout is attributable
    # to one specific person.
    mechanic = models.ForeignKey(
        "workorders.Mechanic", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="operating_expenses", verbose_name="Mekanik",
    )
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Referensi",
        help_text="Nomor kwitansi/struk, jika ada.",
    )
    notes = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Operating Expense"
        verbose_name_plural  = "Operating Expenses"
        ordering             = ["-paid_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return f"{self.number} — {self.account.name} ({self.amount})"

    def _resolve_organization(self):
        return self.account.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = OperatingExpenseSequence.next_number(self.organization)
            self.number = f"EXP/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def record(
        cls, *, organization, account, amount, method="cash",
        paid_at=None, mechanic=None, reference="", notes="", created_by=None,
    ):
        """
        The one real entry point — never construct OperatingExpense
        directly. Real validation, not just a UI suggestion:
          - account must be a real, active EXPENSE-type account,
            excluding 6004 (see class docstring for why).
          - mechanic can only be set when account.code == "6001" —
            stops nonsensical data ("mechanic X got paid for rent")
            at the source, not just discouraged by the form.
        """
        if account.account_type != account.AccountType.EXPENSE:
            raise ValueError(f"Akun {account.code} bukan akun Beban (Expense).")
        if account.code == "6004":
            raise ValueError(
                "Akun 6004 (Beban Penyusutan) tidak bisa dicatat di sini — "
                "penyusutan aset memiliki alur pencatatan tersendiri."
            )
        if mechanic is not None and account.code != "6001":
            raise ValueError("Mekanik hanya bisa dipilih untuk akun 6001 (Beban Gaji Karyawan).")
        if amount is None or amount <= Decimal("0"):
            raise ValueError("Jumlah beban harus lebih dari nol.")

        with transaction.atomic():
            from apps.accounting.models import AccountingPeriod
            resolved_paid_at = paid_at or timezone.now()
            AccountingPeriod.assert_open_for_posting(organization, resolved_paid_at.date())

            expense = cls.objects.create(
                organization=organization, account=account, amount=amount,
                method=method, paid_at=resolved_paid_at, mechanic=mechanic,
                reference=reference, notes=notes, created_by=created_by,
            )

            from apps.core.events.bus import default_bus
            from apps.payments.events import OperatingExpenseRecorded
            default_bus.publish(OperatingExpenseRecorded(
                organization_id=organization.id,
                operating_expense_id=expense.id,
                account_code=account.code,
                # 2 Sep 2026 — real UX fix: already resolved above to
                # validate account_type/6004-exclusion — no extra
                # query, just threading a value already in hand. See
                # OperatingExpenseRecorded's own docstring.
                account_name=account.name,
                method=method,
                amount=amount,
                # 28 Aug 2026 — real bug fix: the real, user-chosen
                # paid_at date, not "whenever this event happens to
                # get published" — see OperatingExpenseRecorded's own
                # docstring for the full story.
                transaction_date=resolved_paid_at.date(),
            ))

        return expense


class InternalCashMutationSequence(TenantScopedModel):
    """Mirrors OperatingExpenseSequence exactly — same real numbering pattern."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Internal Cash Mutation Sequence"
        verbose_name_plural  = "Internal Cash Mutation Sequences"
        unique_together      = [("organization",)]

    def __str__(self):
        return f"{self.organization}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization):
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class InternalCashMutation(TenantScopedModel):
    """
    A real internal movement of cash between the till and the bank —
    NOT a customer or supplier transaction, and NEVER touches any
    Revenue/COGS/Expense account. 1 Sep 2026 — Made's own confirmed
    real request, arrived at while designing the Kas Harian
    dashboard: real workshops move physical cash to the bank
    regularly (theft-risk management), and this system had no way to
    record that real fact.

    Deliberately restricted to Cash (1001) <-> Bank (1101) only in
    v1 — Chris's own confirmed scope call, same "don't build real
    multi-bank-account tracking speculatively" discipline already
    applied to Open Decision #10 (per-supplier cost tracking) and
    Asset's own no-salvage-value call. A specific bank channel name
    (BCA, Mandiri, QRIS) is cosmetic-only, carried in `note` for
    display — never a real ledger distinction; see Roadmap COA
    Blueprint, 1101 (Bank), for why there's only one real bank
    account in the COA today.

    Single real write path, mirrors OperatingExpense's own skeleton
    exactly — same numbered-document pattern (`MUT/00001`), same
    "one classmethod is the only real entry point" discipline.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    from_account_code = models.CharField(max_length=10, verbose_name="Dari Akun")
    to_account_code   = models.CharField(max_length=10, verbose_name="Ke Akun")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah")
    transaction_date = models.DateField(verbose_name="Tanggal Transaksi")
    note = models.CharField(
        max_length=255, blank=True, verbose_name="Catatan",
        help_text="Cosmetic only — e.g. 'Transfer BCA'. No real per-bank "
                  "ledger account exists yet; see Roadmap Open Decisions.",
    )
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Same restriction InternalCashMutationRecorded's own docstring
    # states as a hard architectural fact — enforced here too, not
    # just described, since record() is the one real place that can
    # actually stop bad data from ever being created.
    ALLOWED_ACCOUNT_CODES = {"1001", "1101"}

    class Meta:
        verbose_name        = "Internal Cash Mutation"
        verbose_name_plural  = "Internal Cash Mutations"
        ordering             = ["-transaction_date", "-sequence_number"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return f"{self.number} — {self.from_account_code} → {self.to_account_code} ({self.amount})"

    def _resolve_organization(self):
        # Set directly at creation (see record() below) — no FK to
        # derive it from, same as OperatingExpense derives it via
        # account.organization; this model has no such FK, so
        # organization is passed explicitly instead.
        return self.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = InternalCashMutationSequence.next_number(self.organization)
            self.number = f"MUT/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def record(
        cls, *, organization, from_account_code, to_account_code, amount,
        transaction_date=None, note="", created_by=None,
    ):
        """
        The one real entry point — never construct
        InternalCashMutation directly. Real validation, not just a
        UI suggestion:
          - both account codes must be real Cash/Bank codes (1001 or
            1101), and must differ from each other.
          - amount must be positive.
        """
        if from_account_code not in cls.ALLOWED_ACCOUNT_CODES or to_account_code not in cls.ALLOWED_ACCOUNT_CODES:
            raise ValueError(
                "Mutasi kas internal hanya didukung antara Kas (1001) dan "
                "Bank (1101) pada v1."
            )
        if from_account_code == to_account_code:
            raise ValueError("Akun asal dan akun tujuan tidak boleh sama.")
        if amount is None or amount <= Decimal("0"):
            raise ValueError("Jumlah mutasi harus lebih dari nol.")

        with transaction.atomic():
            from apps.accounting.models import AccountingPeriod
            resolved_date = transaction_date or timezone.now().date()
            AccountingPeriod.assert_open_for_posting(organization, resolved_date)

            mutation = cls(
                organization=organization,
                from_account_code=from_account_code,
                to_account_code=to_account_code,
                amount=amount,
                transaction_date=resolved_date,
                note=note,
                created_by=created_by,
            )
            mutation.save()

            from apps.core.events.bus import default_bus
            from apps.payments.events import InternalCashMutationRecorded
            default_bus.publish(InternalCashMutationRecorded(
                organization_id=organization.id,
                internal_cash_mutation_id=mutation.id,
                from_account_code=from_account_code,
                to_account_code=to_account_code,
                amount=amount,
                transaction_date=resolved_date,
            ))

        return mutation
