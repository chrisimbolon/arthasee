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
            ))

        return payment
