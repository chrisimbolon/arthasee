# =============================================================================
# === backend/apps/invoicing/models.py ===
# =============================================================================
"""
Arthasee — Invoicing (Sprint 2)

Own app, not folded into apps.service — invoicing references both
service.ServiceRecord and inventory.Part, and after the caddy-net-
grade effort of extracting inventory out of apps.service specifically
so it wouldn't force cross-domain imports, doing the same thing again
here would undo that reasoning on day one.

Design decisions locked in with Made/Chris before writing this:
  - Invoice <-> ServiceRecord is OneToOneField, not ForeignKey — the
    database itself refuses to let a visit be invoiced twice.
  - Line items are a single InvoiceLineItem model with a `kind`
    field ("part" or "labor"), not two separate tables — matches how
    a real invoice actually reads: one ordered list of charges.
  - Everything financial on Invoice/InvoiceLineItem is a SNAPSHOT,
    copied at creation time, never a live read through relations.
    A part's price changing next month, a customer's name being
    corrected, a vehicle changing hands — none of that may ever
    silently alter a printed invoice's numbers after the fact.
  - Sequence numbers reset every year (confirmed), scoped per
    organization — InvoiceSequence exists specifically to make that
    increment atomic under concurrent invoice creation.
"""
import uuid
from datetime import date
from decimal import Decimal

from apps.core.models import TenantScopedModel
from django.db import models


class InvoiceSequence(TenantScopedModel):
    """
    Tracks the last invoice sequence number used per (organization,
    year). Not exposed via any API — purely internal plumbing behind
    Invoice.save()'s number generation.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    year          = models.PositiveIntegerField(verbose_name="Tahun")
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Invoice Sequence"
        verbose_name_plural  = "Invoice Sequences"
        unique_together      = [("organization", "year")]

    def __str__(self):
        return f"{self.organization} — {self.year}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization, year):
        """
        Atomically claims the next sequence number, creating the
        tracking row on first use of a given year. select_for_update()
        locks this row for the rest of the caller's transaction — two
        invoices created in the same instant can't both read
        last_sequence=11 and both compute "I'm number 12." Must be
        called from inside an atomic block (Invoice.save() is always
        invoked from within one — see InvoiceCreateView).
        """
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, year=year, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class Invoice(TenantScopedModel):
    """
    A frozen financial document for exactly one ServiceRecord.

    customer_name_snapshot / license_plate_snapshot exist because
    vehicle ownership and plate transfers are a real thing in
    Indonesia — reading these live through
    service_record.vehicle.customer risks a printed invoice's
    displayed name silently changing after the fact. Same class of
    problem PartUsage.unit_price_at_time already solves for prices,
    just applied to identity fields instead of money.
    """
    STATUS_CHOICES = [
        ("DRAFT",     "Draf"),
        ("ISSUED",    "Diterbitkan"),
        ("PAID",      "Lunas"),
        ("CANCELLED", "Dibatalkan"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_record = models.OneToOneField(
        "service.ServiceRecord", on_delete=models.PROTECT, related_name="invoice",
        verbose_name="Catatan Servis",
        # PROTECT, same Principle 2 reasoning as everywhere else — a
        # ServiceRecord with a real invoice attached must never be
        # deletable (moot today since ServiceRecord has no delete
        # endpoint at all, but the constraint should hold regardless
        # of that changing later).
    )
    number          = models.CharField(max_length=50, editable=False, verbose_name="Nomor Invoice")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    year            = models.PositiveIntegerField(editable=False, verbose_name="Tahun")

    customer_name_snapshot = models.CharField(max_length=200, verbose_name="Nama Pelanggan")
    license_plate_snapshot = models.CharField(max_length=20, verbose_name="Nomor Plat")

    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT", verbose_name="Status")
    deposit_amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Deposit")

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Invoice"
        verbose_name_plural  = "Invoices"
        ordering             = ["-created_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    def _resolve_organization(self):
        return self.service_record.organization

    @property
    def subtotal(self):
        # Computed on read from line items, never stored — same
        # "never trust a second source of truth for one fact"
        # discipline as everywhere else. A subtotal field that could
        # drift from its own line items would be worse than no field.
        return sum((li.subtotal for li in self.line_items.all()), Decimal("0"))

    @property
    def total(self):
        return self.subtotal

    @property
    def balance_due(self):
        return self.total - self.deposit_amount

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating:
            if not self.customer_name_snapshot:
                self.customer_name_snapshot = self.service_record.vehicle.customer.name
            if not self.license_plate_snapshot:
                self.license_plate_snapshot = self.service_record.vehicle.plate_number
            if not self.number:
                org = self._resolve_organization()
                if not org.invoice_code:
                    # Fail loudly, not silently — an earlier version
                    # of this method hardcoded "AM" (Arya Motor's own
                    # code) directly here, which meant every other
                    # shop's first invoice of the year collided with
                    # Arya Motor's under the same literal number.
                    # There is no safe generic fallback to guess at
                    # here (deriving one from org.name risks a code
                    # that doesn't match what a shop actually wants
                    # printed on real paperwork) — this must be
                    # configured deliberately, once, via admin.
                    raise ValueError(
                        f"'{org.name}' has no invoice_code configured — "
                        "set Organization.invoice_code (e.g. 'AM') before "
                        "creating invoices for this shop."
                    )
                self.year = self.year or date.today().year
                self.sequence_number = InvoiceSequence.next_number(org, self.year)
                self.number = f"INV/REG/{org.invoice_code}/{self.sequence_number:04d}/{self.year}"
        # organization itself is resolved by TenantScopedModel.save()
        # below, via the same _resolve_organization() called above —
        # no need to duplicate that assignment here.
        super().save(*args, **kwargs)


class InvoiceLineItem(TenantScopedModel):
    """
    One charge on an invoice — either a `part` (snapshotted from a
    PartUsage at invoice-creation time) or `labor` (typed directly,
    supporting Arya Motor's multi-line labor billing — e.g. separate
    "Jasa Servis Rem" and "Jasa Balancing" charges on one invoice).

    Deliberately ONE model for both kinds rather than two separate
    tables — an invoice reads as a single ordered list of charges,
    and rendering the PDF/UI shouldn't need to interleave two
    separate queries in the right order.
    """
    KIND_CHOICES = [
        ("part",  "Part"),
        ("labor", "Jasa"),
    ]

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="line_items", verbose_name="Invoice",
        # CASCADE is safe here the same way PartUsage->ServiceRecord's
        # is: Invoice has no delete endpoint at all, so there is no
        # code path that could ever trigger this cascade as a side
        # effect today.
    )
    kind        = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name="Jenis")
    description = models.CharField(max_length=255, verbose_name="Deskripsi")
    quantity    = models.DecimalField(max_digits=10, decimal_places=2, default=1, verbose_name="Jumlah")
    unit_price  = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Satuan")
    part = models.ForeignKey(
        "inventory.Part", on_delete=models.PROTECT, null=True, blank=True,
        related_name="invoice_line_items", verbose_name="Part",
        # Null for labor lines. PROTECT, not that it's expected to
        # matter much in practice — a Part referenced by a real
        # invoice line item is exactly the kind of history Principle
        # 2 says must not silently vanish.
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Invoice Line Item"
        verbose_name_plural  = "Invoice Line Items"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.description} × {self.quantity}"

    def _resolve_organization(self):
        return self.invoice.organization

    @property
    def subtotal(self):
        return self.quantity * self.unit_price
