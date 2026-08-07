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
InvoiceStatusUpdateView, apps.invoicing.views — now fixed alongside
this app, see that file's own updated docstring). This app is the
real fix for that gap, independent of Sprint 2's own need for a
PaymentReceived domain event — this model is what that event will
eventually be built from (see Payment.record()'s own docstring for
exactly where that hook lands).

Payment.record() is the one real write path — mirrors
JournalEntry.post() and WorkOrder.close()'s own shape: owns its own
transaction.atomic(), validates before writing anything, and is the
ONLY place Invoice.status transitions to "PAID" anywhere in the
system, per Chris's own explicit call: PAID must only ever be
system-derived from balance_due actually reaching zero, never a
human's typed claim.
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
        # PROTECT, same Principle 2 reasoning as everywhere else — a
        # real payment record must never be able to vanish just
        # because something happened to its Invoice (moot today,
        # same as ServiceRecord/Invoice themselves — neither has a
        # delete endpoint — but the constraint should hold
        # regardless of that changing later).
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
        construct Payment directly. Validates before writing
        anything, same "guarantee your own atomicity, don't trust the
        caller" discipline as JournalEntry.post() / WorkOrder.close().

        Auto-transitions Invoice.status to "PAID" the moment
        balance_due actually reaches zero after this payment is
        recorded — re-derived from the DB-backed aggregate
        (invoice.payments.all(), via balance_due), not by trusting
        arithmetic on the in-memory `amount` argument alone.

        Sprint 2, Task 2.1 hook point: `default_bus.publish(...)` for
        a future PaymentReceived event belongs right after the
        Payment row is created, inside this same transaction —
        deliberately not wired yet, since no PaymentReceived event
        class or accounting handler exists in this codebase until
        Sprint 2 formally starts. Marked below with a comment, not
        left undocumented.
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

            # Sprint 2, Task 2.1 — fires on every recorded payment,
            # partial or full (Chris's own explicit call) — see
            # apps.payments.events.PaymentReceived's own docstring.
            # Placed unconditionally, BEFORE the balance_due check
            # below, so it fires the same way regardless of whether
            # this particular payment happens to complete the
            # invoice — a partial payment is just as real a cash
            # movement as one that zeroes the balance.
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
