# =============================================================================
# === backend/apps/payments/models.py ===
# =============================================================================
"""
Arthasee — Payments

New domain, not an extraction — apps.invoicing never had a real
Payment model. It had one overwritable Invoice.deposit_amount field
that nothing in invoicing/views.py or serializers.py ever actually
writes to, and a status field any authenticated user could PATCH
straight to "PAID" with zero connection to real money received (see
InvoiceStatusUpdateView, apps.invoicing.views — fixed alongside this
app). This app is the real fix for that gap, independent of Sprint
2's own need for a PaymentReceived domain event.

Payment.record() and Refund.record() are the two real write paths —
mirror JournalEntry.post() and WorkOrder.close()'s own shape: each
owns its own transaction.atomic(), validates before writing anything,
and each is the ONLY place its respective Invoice.status transition
happens anywhere in the system.
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
            ))

            if invoice.balance_due <= Decimal("0"):
                invoice.status = "PAID"
                invoice.save(update_fields=["status"])

        return payment


class Refund(TenantScopedModel):
    """
    One real refund issued against one fully-PAID Invoice — the
    inverse of Payment. Reuses Payment.METHOD_CHOICES directly rather
    than duplicating the list; a refund's own method is genuinely
    independent of how the original payment(s) came in (paid by
    card, refunded via bank transfer is completely normal — see
    Refund.record()'s own docstring).

    Deliberately full-invoice-only for now (Task 2.3, Half B's own
    scope) — Refund.record() requires status == "PAID" and always
    refunds the invoice's full total_paid, never a partial amount.
    Cancelling a PARTIALLY paid invoice is deliberately still blocked
    (see InvoiceStatusUpdateView's own guard) until that's explicitly
    scoped as its own piece of work.
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
        the refund always covers the invoice's full total_paid,
        computed here, never a caller-supplied partial figure — see
        class docstring for why.

        Sets Invoice.status to "CANCELLED" the moment the refund is
        recorded — same "one action does both the money and the
        status" symmetry as Payment.record()'s own transition to
        PAID, just inverted. This is the ONLY place a PAID invoice
        can ever become CANCELLED — InvoiceStatusUpdateView's own
        guard blocks that transition through the generic status PATCH
        entirely, redirecting here instead.
        """
        if invoice.status != "PAID":
            raise ValueError(
                f"Tidak bisa memproses refund untuk invoice berstatus "
                f"'{invoice.get_status_display()}' — invoice harus berstatus "
                f"'Lunas' terlebih dahulu."
            )

        amount = invoice.total_paid
        if amount <= Decimal("0"):
            # Should be structurally impossible — status == "PAID"
            # implies total_paid fully covers total, which is > 0 by
            # JournalEntry.post()'s own zero-total guard on the
            # original InvoiceIssued posting. Checked anyway, fail
            # loudly rather than silently create a $0 refund.
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
