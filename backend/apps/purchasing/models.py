# =============================================================================
# === backend/apps/purchasing/models.py ===
# =============================================================================
"""
Arthasee — Purchasing (Sprint 3)

Lean scope, deliberately — no PurchaseRequisition or PurchaseOrder
model. Chris's own explicit call: build what the accounting actually
needs (Supplier, GoodsReceivedNote, SupplierInvoice), defer the
requisition/approval workflow until a real shop asks for it.

Stage 2 — the domain-event publish() calls that were stubbed as
comments in Stage 1 are now real, wired to apps.purchasing.events and
the accounting posting engine.
"""
import uuid
from decimal import Decimal

from apps.core.models import TenantScopedModel
from django.db import models, transaction
from django.utils import timezone


class Supplier(TenantScopedModel):
    """
    One row per vendor a shop buys parts from. Simple master data,
    same shape as apps.service.Customer — no credit-limit, payment-
    terms, or approval-workflow fields. Matches the same "lean, add
    it when a real shop needs it" philosophy this whole app was
    scoped around.
    """
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name           = models.CharField(max_length=200, verbose_name="Nama Supplier")
    contact_person = models.CharField(max_length=200, blank=True, verbose_name="Kontak")
    phone          = models.CharField(max_length=20, blank=True, verbose_name="Telepon")
    email          = models.EmailField(blank=True, verbose_name="Email")
    address        = models.TextField(blank=True, verbose_name="Alamat")
    notes          = models.TextField(blank=True, verbose_name="Catatan")
    is_active      = models.BooleanField(default=True, verbose_name="Aktif")
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Supplier"
        verbose_name_plural  = "Suppliers"
        ordering             = ["name"]

    def __str__(self):
        return self.name


class GoodsReceivedNoteSequence(TenantScopedModel):
    """
    One row per organization — mirrors WorkOrderSequence /
    InvoiceSequence / JournalEntrySequence exactly, same
    select_for_update()-based gap-free numbering.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Goods Received Note Sequence"
        verbose_name_plural  = "Goods Received Note Sequences"
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


class GoodsReceivedNote(TenantScopedModel):
    """
    One real delivery of parts arriving at the shop — the actual
    physical/economic event GoodsReceived describes. Frozen once
    created, same "never delete, always audit" discipline as
    everywhere else — no update/delete endpoint is planned; a wrong
    GRN gets corrected via a real StockAdjustment
    (reason="correction"), not by editing history.

    supplier_invoice is null until a real SupplierInvoice actually
    arrives and gets linked (see SupplierInvoice.record()) — that gap
    IS what Accrued Inventory (2010) means: goods physically
    received, but not yet billed.
    """
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor GRN")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="goods_received_notes",
        verbose_name="Supplier",
    )
    supplier_invoice = models.ForeignKey(
        "SupplierInvoice", on_delete=models.PROTECT, null=True, blank=True,
        related_name="goods_received_notes", verbose_name="Invoice Supplier",
        # PROTECT, not CASCADE/SET_NULL — a SupplierInvoice with real
        # GRNs already clearing against it must never disappear out
        # from under that history.
    )
    received_at = models.DateTimeField(verbose_name="Waktu Diterima")
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Referensi",
        help_text="Nomor surat jalan supplier, dll — opsional.",
    )
    notes = models.TextField(blank=True, verbose_name="Catatan")
    received_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Diterima Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Goods Received Note"
        verbose_name_plural  = "Goods Received Notes"
        ordering             = ["-received_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    @property
    def total_cost(self):
        # Computed on read from line items, never stored — same
        # "never trust a second source of truth" discipline as
        # Invoice.subtotal.
        return sum((li.subtotal for li in self.line_items.all()), Decimal("0"))

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = GoodsReceivedNoteSequence.next_number(self.organization)
            self.number = f"GRN/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def receive(
        cls, *, organization, supplier, lines,
        received_at=None, reference="", notes="", received_by=None,
    ):
        """
        The one real entry point for recording a goods receipt —
        never construct GoodsReceivedNote + line items separately.
        Mirrors WorkOrder.close()'s own shape: owns its own
        transaction.atomic(), creates the document AND every line
        item together, and publishes exactly ONE GoodsReceived event
        for the whole document — aggregating every line's cost into
        one total, same "one document, one accounting fact" pattern
        as WorkOrderCompleted, not PartConsumed's per-line shape.

        `lines` is a plain list of dicts:
            [{"part": <Part>, "quantity": Decimal, "unit_cost": Decimal}, ...]

        Uses .create() in a loop, not bulk_create() — each line item
        needs its own save()-time side effect (the real
        StockAdjustment it creates), which bulk_create() would skip
        entirely.
        """
        if not lines:
            raise ValueError("Goods Received Note harus memiliki minimal satu item.")

        with transaction.atomic():
            grn = cls.objects.create(
                organization=organization, supplier=supplier,
                received_at=received_at or timezone.now(),
                reference=reference, notes=notes, received_by=received_by,
            )
            line_items = [
                GoodsReceivedNoteLineItem.objects.create(
                    organization=organization, goods_received_note=grn,
                    part=line["part"], quantity=line["quantity"], unit_cost=line["unit_cost"],
                )
                for line in lines
            ]
            # Each GoodsReceivedNoteLineItem.save() above already
            # created its own StockAdjustment(reason="restock") —
            # no separate stock-update step needed here.

            total_cost = sum((li.subtotal for li in line_items), Decimal("0"))

            from apps.core.events.bus import default_bus
            from apps.purchasing.events import GoodsReceived
            default_bus.publish(GoodsReceived(
                organization_id=organization.id,
                goods_received_note_id=grn.id,
                supplier_id=supplier.id,
                amount=total_cost,
                line_item_count=len(line_items),
            ))

        return grn


class GoodsReceivedNoteLineItem(TenantScopedModel):
    """
    One part received, in one quantity, at one cost, on one
    GoodsReceivedNote. Creating one atomically increases
    Part.current_stock via a real StockAdjustment(reason="restock")
    row — reusing the EXACT mechanism already built for this in
    apps.inventory, not a fourth independent copy of stock math.

    unit_cost is a deliberate, separate field from Part.unit_price —
    that field is explicitly documented as the SELLING price;
    conflating it with what was actually PAID to the supplier would
    be a real, silent accounting error.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    goods_received_note = models.ForeignKey(
        GoodsReceivedNote, on_delete=models.CASCADE, related_name="line_items",
        verbose_name="GRN",
    )
    part = models.ForeignKey(
        "inventory.Part", on_delete=models.PROTECT, related_name="goods_received_line_items",
        verbose_name="Part",
    )
    quantity   = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah")
    unit_cost  = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Beli Satuan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Goods Received Line Item"
        verbose_name_plural  = "Goods Received Line Items"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.part.name} × {self.quantity} @ {self.unit_cost}"

    def _resolve_organization(self):
        return self.goods_received_note.organization

    @property
    def subtotal(self):
        return self.quantity * self.unit_cost

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            from apps.inventory.models import StockAdjustment
            StockAdjustment.objects.create(
                organization=self.organization,
                part=self.part,
                quantity_change=self.quantity,
                reason="restock",
                notes=f"GRN {self.goods_received_note.number}",
            )


class SupplierInvoiceSequence(TenantScopedModel):
    """Mirrors GoodsReceivedNoteSequence exactly."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Supplier Invoice Sequence"
        verbose_name_plural  = "Supplier Invoice Sequences"
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


class SupplierInvoice(TenantScopedModel):
    """
    The supplier's own bill — may correspond to one or several
    GoodsReceivedNotes (a real one-to-many — see
    GoodsReceivedNote.supplier_invoice, the reverse FK that makes
    this relationship real).

    amount is entered directly from what the supplier's bill actually
    states — NOT derived from the linked GRNs' own total costs.
    Deliberate consequence of "no 3-way matching" (this app's own
    lean scope): if the supplier's stated total differs from what was
    accrued via GoodsReceived, that shows up as a real, visible
    variance on Accrued Inventory (2010) for a future manual
    adjusting journal (Phase 4) to resolve — not something this lean
    version silently force-balances.
    """
    STATUS_CHOICES = [
        ("UNPAID", "Belum Dibayar"),
        ("PAID",   "Lunas"),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor Internal")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="supplier_invoices",
        verbose_name="Supplier",
    )
    supplier_invoice_number = models.CharField(
        max_length=100, blank=True, verbose_name="Nomor Invoice Supplier",
        help_text="Nomor invoice asli dari supplier, jika ada.",
    )
    amount       = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah")
    invoice_date = models.DateField(verbose_name="Tanggal Invoice")
    due_date     = models.DateField(null=True, blank=True, verbose_name="Jatuh Tempo")
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default="UNPAID", verbose_name="Status")
    notes        = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Supplier Invoice"
        verbose_name_plural  = "Supplier Invoices"
        ordering             = ["-invoice_date"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = SupplierInvoiceSequence.next_number(self.organization)
            self.number = f"SINV/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def record(
        cls, *, organization, supplier, amount, invoice_date, goods_received_notes=None,
        supplier_invoice_number="", due_date=None, notes="", created_by=None,
    ):
        """
        The one real entry point — never construct SupplierInvoice
        directly. Links any given GoodsReceivedNotes to this invoice
        (clearing their Accrued Inventory) — each GRN passed in must
        not already be linked to a different invoice.
        """
        if amount is None or amount <= Decimal("0"):
            raise ValueError("Jumlah invoice harus lebih dari nol.")

        with transaction.atomic():
            invoice = cls.objects.create(
                organization=organization, supplier=supplier, amount=amount,
                invoice_date=invoice_date, supplier_invoice_number=supplier_invoice_number,
                due_date=due_date, notes=notes, created_by=created_by,
            )
            for grn in (goods_received_notes or []):
                if grn.supplier_invoice_id is not None:
                    raise ValueError(
                        f"GRN {grn.number} sudah terhubung dengan invoice lain."
                    )
                grn.supplier_invoice = invoice
                grn.save(update_fields=["supplier_invoice"])

            from apps.core.events.bus import default_bus
            from apps.purchasing.events import SupplierInvoiceReceived
            default_bus.publish(SupplierInvoiceReceived(
                organization_id=organization.id,
                supplier_invoice_id=invoice.id,
                supplier_id=supplier.id,
                amount=amount,
            ))

        return invoice

class PurchaseReturnSequence(TenantScopedModel):
    """Mirrors GoodsReceivedNoteSequence / SupplierInvoiceSequence exactly."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Purchase Return Sequence"
        verbose_name_plural  = "Purchase Return Sequences"
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


class PurchaseReturn(TenantScopedModel):
    """
    Retur Pembelian — Case A only, a deliberate v1 scope call: returning
    goods received via a GRN that has NOT yet been linked to a
    SupplierInvoice. The moment goods_received_note.supplier_invoice_id
    is set, Accrued Inventory (2010) has already been cleared by that
    invoice and Accounts Payable (2001) holds the real balance
    instead — a genuinely different reversal (a real debit memo
    against AP), deliberately deferred rather than guessed at. See
    Roadmap's own Open Decisions for the full reasoning behind this
    split.

    Frozen once created — same "never delete, always audit" discipline
    as GoodsReceivedNote itself. A wrong return needs its own
    correcting StockAdjustment, not an edit to history.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor Retur")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    goods_received_note = models.ForeignKey(
        GoodsReceivedNote, on_delete=models.PROTECT, related_name="purchase_returns",
        verbose_name="GRN Asal",
    )
    return_date = models.DateTimeField(verbose_name="Tanggal Retur")
    reason      = models.TextField(verbose_name="Alasan Retur")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Purchase Return"
        verbose_name_plural  = "Purchase Returns"
        ordering             = ["-return_date"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    @property
    def total_value(self):
        # Computed on read from line items, never stored — same
        # discipline as GoodsReceivedNote.total_cost.
        return sum((li.subtotal for li in self.line_items.all()), Decimal("0"))

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = PurchaseReturnSequence.next_number(self.organization)
            self.number = f"RTR/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def create_return(
        cls, *, organization, goods_received_note, lines,
        return_date=None, reason="", created_by=None,
    ):
        """
        The one real entry point — mirrors GoodsReceivedNote.receive()
        exactly: validates the Case-A precondition BEFORE creating
        anything, owns its own transaction.atomic(), creates the
        document and every line item together, and publishes exactly
        ONE PurchaseReturned event for the whole document — aggregating
        every line's value into one total, same "one document, one
        accounting fact" pattern as GoodsReceived.

        `lines` is a plain list of dicts:
            [{"grn_line_item": <GoodsReceivedNoteLineItem>, "quantity": Decimal}, ...]

        Each line's quantity is validated against how much of that
        SPECIFIC GRN line has already been returned across any prior
        PurchaseReturn — supports multiple partial returns against the
        same line over time, capped honestly at what was actually
        received. Verified by hand before being written here.
        """
        if goods_received_note.supplier_invoice_id is not None:
            raise ValueError(
                f"GRN {goods_received_note.number} sudah memiliki invoice supplier — "
                f"retur untuk GRN yang sudah ditagih belum didukung di versi ini."
            )
        if not lines:
            raise ValueError("Retur Pembelian harus memiliki minimal satu item.")

        with transaction.atomic():
            ret = cls.objects.create(
                organization=organization, goods_received_note=goods_received_note,
                return_date=return_date or timezone.now(), reason=reason, created_by=created_by,
            )
            line_items = []
            for line in lines:
                grn_line = line["grn_line_item"]
                quantity = line["quantity"]

                if grn_line.goods_received_note_id != goods_received_note.id:
                    raise ValueError(
                        f"Line item ini bukan bagian dari GRN {goods_received_note.number}."
                    )

                already_returned = PurchaseReturnLineItem.objects.filter(
                    goods_received_note_line_item=grn_line,
                ).aggregate(total=models.Sum("quantity"))["total"] or Decimal("0")

                if already_returned + quantity > grn_line.quantity:
                    raise ValueError(
                        f"Jumlah retur untuk '{grn_line.part.name}' melebihi jumlah yang "
                        f"diterima (diterima: {grn_line.quantity}, sudah diretur sebelumnya: "
                        f"{already_returned}, diminta sekarang: {quantity})."
                    )

                line_items.append(PurchaseReturnLineItem.objects.create(
                    organization=organization, purchase_return=ret,
                    goods_received_note_line_item=grn_line, quantity=quantity,
                ))
                # Each PurchaseReturnLineItem.save() above already
                # created its own StockAdjustment(reason="purchase_return")
                # — no separate stock-update step needed here, same
                # discipline as GoodsReceivedNote.receive().

            total_value = sum((li.subtotal for li in line_items), Decimal("0"))

            from apps.core.events.bus import default_bus
            from apps.purchasing.events import PurchaseReturned
            default_bus.publish(PurchaseReturned(
                organization_id=organization.id,
                purchase_return_id=ret.id,
                goods_received_note_id=goods_received_note.id,
                amount=total_value,
                line_item_count=len(line_items),
            ))

        return ret


class PurchaseReturnLineItem(TenantScopedModel):
    """
    One part being returned, in one quantity, valued at the ORIGINAL
    GRN line's own unit_cost via a real FK snapshot — never a live
    reference to Part.unit_price (the SELLING price, a completely
    different number) and never the part's CURRENT cost either, which
    may have changed since the original receipt. Same "history should
    not move once written" instinct as PartUsage.unit_price_at_time.

    Creating one atomically DECREASES Part.current_stock via a real
    StockAdjustment(reason="purchase_return") — reusing the exact
    stock-math mechanism already proven for GoodsReceivedNoteLineItem,
    just moving stock the other direction. Needs a new REASON_CHOICES
    entry on StockAdjustment — see the companion patch for
    apps/inventory/models.py.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_return = models.ForeignKey(
        PurchaseReturn, on_delete=models.CASCADE, related_name="line_items",
        verbose_name="Retur Pembelian",
    )
    goods_received_note_line_item = models.ForeignKey(
        GoodsReceivedNoteLineItem, on_delete=models.PROTECT, related_name="purchase_return_line_items",
        verbose_name="Item GRN Asal",
    )
    quantity   = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah Diretur")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Purchase Return Line Item"
        verbose_name_plural  = "Purchase Return Line Items"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.goods_received_note_line_item.part.name} × {self.quantity}"

    def _resolve_organization(self):
        return self.purchase_return.organization

    @property
    def part(self):
        return self.goods_received_note_line_item.part

    @property
    def unit_cost(self):
        return self.goods_received_note_line_item.unit_cost

    @property
    def subtotal(self):
        return self.quantity * self.unit_cost

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            from apps.inventory.models import StockAdjustment
            StockAdjustment.objects.create(
                organization=self.organization,
                part=self.part,
                quantity_change=-self.quantity,
                reason="purchase_return",
                notes=(
                    f"Retur {self.purchase_return.number} — "
                    f"GRN {self.goods_received_note_line_item.goods_received_note.number}"
                ),
            )