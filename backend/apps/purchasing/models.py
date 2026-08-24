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


class PurchaseOrderSequence(TenantScopedModel):
    """Mirrors GoodsReceivedNoteSequence exactly."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Purchase Order Sequence"
        verbose_name_plural  = "Purchase Order Sequences"
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


class PurchaseOrder(TenantScopedModel):
    """
    A real, formal commitment to a supplier — the FIRST mutable
    document in this whole purchasing domain. Every other one
    (GoodsReceivedNote, SupplierInvoice, PurchaseReturn) is frozen the
    instant it's created; a PO can't work that way, since it has a
    real lifecycle that unfolds as deliveries actually arrive.

    No PurchaseRequisition, no approval routing — Made is the
    owner/operator, confirmed directly: creating a PO is a single
    action, defaulting straight to ORDERED. DRAFT exists as a real,
    separate state anyway — a PO still being built (items not yet
    finalized, not yet sent to the supplier) shouldn't count toward
    outstanding-inventory tracking the way a genuinely placed order
    does.

    No accounting event fires on creation or on any status change —
    a PO is a commitment, not yet an economic transaction. Matches
    the canonical purchasing diagram's own "NO JOURNAL" treatment for
    this stage.
    """
    class Status(models.TextChoices):
        DRAFT               = "DRAFT", "Draft"
        ORDERED             = "ORDERED", "Dipesan"
        PARTIALLY_RECEIVED  = "PARTIALLY_RECEIVED", "Sebagian Diterima"
        FULLY_RECEIVED      = "FULLY_RECEIVED", "Diterima Penuh"
        CANCELLED           = "CANCELLED", "Dibatalkan"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor PO")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_orders", verbose_name="Supplier",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name="Status",
    )
    order_date    = models.DateField(verbose_name="Tanggal Pesan")
    expected_date = models.DateField(null=True, blank=True, verbose_name="Perkiraan Tiba")
    notes         = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # real, evolving status — unlike every frozen sibling document

    class Meta:
        verbose_name        = "Purchase Order"
        verbose_name_plural  = "Purchase Orders"
        ordering             = ["-order_date"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    @property
    def total_ordered_value(self):
        return sum((li.quantity_ordered * li.unit_cost for li in self.line_items.all()), Decimal("0"))

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = PurchaseOrderSequence.next_number(self.organization)
            self.number = f"PO/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def create_order(
        cls, *, organization, supplier, lines,
        order_date=None, expected_date=None, notes="", status=None, created_by=None,
    ):
        """
        The one real entry point. `lines`:
            [{"part": <Part>, "quantity_ordered": Decimal, "unit_cost": Decimal}, ...]

        status defaults to ORDERED, not DRAFT — Made creates and
        sends a PO in one action; DRAFT is available for the "still
        building this, haven't committed yet" case, but callers must
        pass it explicitly rather than land there by default.
        """
        if not lines:
            raise ValueError("Purchase Order harus memiliki minimal satu item.")

        with transaction.atomic():
            po = cls.objects.create(
                organization=organization, supplier=supplier,
                status=status or cls.Status.ORDERED,
                order_date=order_date or timezone.now().date(),
                expected_date=expected_date, notes=notes, created_by=created_by,
            )
            for line in lines:
                PurchaseOrderLineItem.objects.create(
                    organization=organization, purchase_order=po,
                    part=line["part"], quantity_ordered=line["quantity_ordered"],
                    unit_cost=line["unit_cost"],
                )
        return po

    def cancel(self):
        """
        Only DRAFT or ORDERED (zero real receipts) can be cancelled
        cleanly. The moment any GRN has been received against this
        PO, cancelling would leave real stock/accounting facts
        orphaned from their own authorization — same "can't touch
        history once real facts exist" instinct as every hard-block
        guard elsewhere in this domain.
        """
        if self.status not in (self.Status.DRAFT, self.Status.ORDERED):
            raise ValueError(
                f"PO {self.number} berstatus '{self.get_status_display()}' — tidak bisa "
                f"dibatalkan (sudah ada barang yang diterima untuk PO ini)."
            )
        self.status = self.Status.CANCELLED
        self.save(update_fields=["status"])


class PurchaseOrderLineItem(TenantScopedModel):
    """
    One part, one ordered quantity, one expected cost, on one PO.
    quantity_received/quantity_outstanding are computed live from
    every real GoodsReceivedNoteLineItem that traces back to this
    line — never stored, same "never trust a second source of truth"
    discipline as GoodsReceivedNote.total_cost.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="line_items", verbose_name="Purchase Order",
    )
    part = models.ForeignKey(
        "inventory.Part", on_delete=models.PROTECT, related_name="purchase_order_line_items",
        verbose_name="Part",
    )
    quantity_ordered = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah Dipesan")
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Harga Beli Satuan (Perkiraan)",
        help_text="Harga yang disepakati/diperkirakan saat pemesanan — bisa berbeda dari harga aktual saat GRN dicatat.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Purchase Order Line Item"
        verbose_name_plural  = "Purchase Order Line Items"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.part.name} × {self.quantity_ordered}"

    def _resolve_organization(self):
        return self.purchase_order.organization

    @property
    def quantity_received(self):
        return self.grn_line_items.aggregate(total=models.Sum("quantity"))["total"] or Decimal("0")

    @property
    def quantity_outstanding(self):
        return self.quantity_ordered - self.quantity_received

    def amend_quantity(self, new_quantity):
        """
        The one real way to raise an ordered quantity after the
        fact — e.g. resolving an over-receipt attempt by raising the
        PO's own ceiling first, deliberately, before re-attempting
        the GRN. Can never drop below what's already been physically
        received — history that already happened doesn't move.
        """
        if new_quantity < self.quantity_received:
            raise ValueError(
                f"Tidak bisa mengubah jumlah pesanan '{self.part.name}' menjadi {new_quantity} "
                f"— sudah diterima {self.quantity_received}."
            )
        self.quantity_ordered = new_quantity
        self.save(update_fields=["quantity_ordered"])

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
    purchase_order = models.ForeignKey(
        "PurchaseOrder", on_delete=models.PROTECT,  
        related_name="goods_received_notes", verbose_name="Purchase Order",
        # PROTECT — a PO with real GRNs against it must never
        # disappear out from under that history. Required for every
        # GRN going forward; existing GRNs (created before this
        # feature shipped) get a real, explicitly-labeled synthetic
        # "legacy" PO via this migration's own data-migration step.
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
        cls, *, organization, purchase_order, lines,
        received_at=None, reference="", notes="", received_by=None,
    ):
        """
        purchase_order is now REQUIRED — every real delivery must
        trace back to an authorized commitment. `lines`:
            [{"purchase_order_line_item": <POLineItem>, "quantity": Decimal, "unit_cost": Decimal}, ...]

        Two real, explicitly confirmed hard-block guardrails:
        receiving MORE than a PO line's own remaining quantity is
        blocked outright (a PO is a spend ceiling, not a suggestion —
        the user must amend the PO first, deliberately, if more
        really did arrive); receiving something that isn't on the
        referenced PO at all is blocked outright (every GRN line must
        trace to an authorized PO line — an unlisted item needs its
        own PO, not to be folded silently into an unrelated delivery).
        Receiving LESS than what's outstanding is always allowed, no
        warning — that's the normal partial-delivery case this whole
        feature exists to track, and is what drives the PO's own
        status recompute below.

        Price variance — deliberately a WARNING, not a third hard
        block: if the entered unit_cost differs from the PO line's
        own unit_cost (the price agreed/expected at order time),
        that's surfaced back to the caller via a transient
        `price_variance_warnings` list attribute set on the returned
        GRN instance — never persisted, no new DB column. Made is
        both the one who creates the PO and the one who records the
        receipt in this shop; a hard block or approval-token system
        would be real friction solving a multi-employee fraud
        scenario that doesn't exist here yet. Same "flag it, don't
        block it" instinct already proven elsewhere in this codebase
        — PartUsageSerializer's own negative-stock warning,
        ManualJournalListCreateView's own control-account warning.
        """
        if purchase_order.status not in (PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIALLY_RECEIVED):
            raise ValueError(
                f"PO {purchase_order.number} berstatus '{purchase_order.get_status_display()}' "
                f"— tidak bisa menerima barang untuk PO ini."
            )
        if not lines:
            raise ValueError("Goods Received Note harus memiliki minimal satu item.")

        with transaction.atomic():
            grn = cls.objects.create(
                organization=organization, supplier=purchase_order.supplier,
                purchase_order=purchase_order,
                received_at=received_at or timezone.now(),
                reference=reference, notes=notes, received_by=received_by,
            )
            line_items = []
            price_variance_warnings = []
            for line in lines:
                po_line = line["purchase_order_line_item"]
                quantity = line["quantity"]
                entered_unit_cost = line["unit_cost"]

                if po_line.purchase_order_id != purchase_order.id:
                    raise ValueError(
                        f"Item '{po_line.part.name}' bukan bagian dari PO {purchase_order.number}."
                    )
                if quantity > po_line.quantity_outstanding:
                    raise ValueError(
                        f"Jumlah diterima untuk '{po_line.part.name}' melebihi sisa PO "
                        f"(dipesan: {po_line.quantity_ordered}, sudah diterima: "
                        f"{po_line.quantity_received}, sisa: {po_line.quantity_outstanding}, "
                        f"diminta: {quantity}). Ubah jumlah PO terlebih dahulu jika memang "
                        f"perlu menerima lebih banyak."
                    )
                if entered_unit_cost != po_line.unit_cost:
                    entered_fmt = f"{entered_unit_cost:,.0f}".replace(",", ".")
                    po_fmt = f"{po_line.unit_cost:,.0f}".replace(",", ".")
                    price_variance_warnings.append(
                        f"Harga Beli '{po_line.part.name}' (Rp{entered_fmt}) berbeda "
                        f"dari PO {purchase_order.number} (Rp{po_fmt})."
                    )

                line_items.append(GoodsReceivedNoteLineItem.objects.create(
                    organization=organization, goods_received_note=grn,
                    purchase_order_line_item=po_line, part=po_line.part,
                    quantity=quantity, unit_cost=entered_unit_cost,
                ))
                # Each GoodsReceivedNoteLineItem.save() above already
                # created its own StockAdjustment(reason="restock").

            total_cost = sum((li.subtotal for li in line_items), Decimal("0"))

            # Recompute the PO's own status from REAL, current totals
            # across ALL its line items — not just the ones THIS GRN
            # touched, since earlier partial deliveries matter too.
            # Verified by hand across a real partial-then-complete
            # scenario before being written here.
            purchase_order.refresh_from_db()
            all_fully_received = all(
                li.quantity_outstanding <= Decimal("0") for li in purchase_order.line_items.all()
            )
            purchase_order.status = (
                PurchaseOrder.Status.FULLY_RECEIVED if all_fully_received
                else PurchaseOrder.Status.PARTIALLY_RECEIVED
            )
            purchase_order.save(update_fields=["status"])

            from apps.core.events.bus import default_bus
            from apps.purchasing.events import GoodsReceived
            default_bus.publish(GoodsReceived(
                organization_id=organization.id,
                goods_received_note_id=grn.id,
                supplier_id=purchase_order.supplier_id,
                amount=total_cost,
                line_item_count=len(line_items),
            ))

        grn.price_variance_warnings = price_variance_warnings
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

    Also updates Part.cost_price on every creation — Made's own
    confirmed "Last Cost" call: the most recent real GRN unit_cost
    simply overwrites whatever was there before, no running Weighted
    Average Cost math. This is the real fix for a genuine ledger
    inconsistency found live, 24 Aug 2026: GoodsReceived debits
    Account 1301 at real cost, but PartConsumed was crediting the
    SAME account at Part.unit_price (selling price) — see
    apps.workorders.models.WorkOrderMaterialLine's own updated
    docstring for the other half of this fix.
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
    purchase_order_line_item = models.ForeignKey(
        "PurchaseOrderLineItem", on_delete=models.PROTECT,
        related_name="grn_line_items", verbose_name="Item PO",
        # Deliberately kept ALONGSIDE `part`, not replacing it — a
        # derived property reading through this relation was
        # considered, but `part` is a real column with real
        # production data already in it; removing it would be a
        # genuinely destructive schema change for something the
        # "unlisted item" guard in receive() already guarantees can
        # never drift from this relation's own part anyway.
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
            # Real ledger-consistency fix — "Last Cost," Made's own
            # confirmed call. A plain overwrite, not F()-based — this
            # isn't an increment, it's "the most recent real cost IS
            # now this value," full stop. See this class's own
            # docstring for the full incident this closes.
            from apps.inventory.models import Part
            Part.objects.filter(pk=self.part_id).update(cost_price=self.unit_cost)


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
    class ReturnClassification(models.TextChoices):
        BEFORE_INVOICE        = "BEFORE_INVOICE", "Sebelum Invoice (Retur ke Accrued Inventory)"
        AFTER_INVOICE_UNPAID  = "AFTER_INVOICE_UNPAID", "Setelah Invoice, Belum Dibayar (Retur ke Utang)"
        # AFTER_INVOICE_PAID (Case C) deliberately does not exist yet
        # — real refund mechanics (cash vs. vendor credit) vary by
        # supplier and need Made's own direct input before this can
        # be scoped safely. See create_return()'s own guard below.

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor Retur")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    goods_received_note = models.ForeignKey(
        GoodsReceivedNote, on_delete=models.PROTECT, related_name="purchase_returns",
        verbose_name="GRN Asal",
    )
    # System-determined at creation, never user-editable — same
    # treatment as `number`/`sequence_number` above. Real audit
    # visibility: a shop owner reviewing this return months later can
    # see immediately whether it reduced Accrued Inventory (GR/IR) or
    # reduced a real vendor bill (AP), without inferring it from the
    # linked GRN's own current state (which may have moved on since).
    return_classification = models.CharField(
        max_length=30, choices=ReturnClassification.choices, editable=False,
        default=ReturnClassification.BEFORE_INVOICE,
        verbose_name="Klasifikasi Retur",
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
        Determines WHICH real classification applies — before any
        supplier invoice exists (Case A), or an invoice exists but is
        still unpaid (Case B) — once, here, inside this same
        transaction, and freezes it BOTH on the record itself
        (return_classification, real audit visibility — see the
        field's own docstring) AND inside the PurchaseReturned
        event's own payload (debit_account_code).

        posting_engine.py never re-derives this from live GRN/
        SupplierInvoice state later — by the time an event is
        actually processed (after commit, asynchronously via the
        real event bus), that state could theoretically have moved
        on. Same "capture once, don't recompute from a shifting
        database" discipline already used for GoodsReceived's own
        amount — verified by hand before being written here.

        Case C (return after the supplier invoice has been PAID)
        remains explicitly deferred — real refund mechanics (cash vs.
        vendor credit) vary by supplier and need Made's own direct
        input before this can be scoped safely, not guessed at.
        """
        invoice = goods_received_note.supplier_invoice
        if invoice is None:
            classification = cls.ReturnClassification.BEFORE_INVOICE
            debit_account_code = "2010"
        elif invoice.status == "UNPAID":
            classification = cls.ReturnClassification.AFTER_INVOICE_UNPAID
            debit_account_code = "2001"
        else:
            raise ValueError(
                f"Invoice untuk GRN {goods_received_note.number} sudah dibayar ke supplier — "
                f"retur untuk invoice yang sudah lunas belum didukung di versi ini."
            )

        if not lines:
            raise ValueError("Retur Pembelian harus memiliki minimal satu item.")

        with transaction.atomic():
            ret = cls.objects.create(
                organization=organization, goods_received_note=goods_received_note,
                return_classification=classification,
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
                debit_account_code=debit_account_code,
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
    just moving stock the other direction.
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


class SupplierPartCode(TenantScopedModel):
    """
    One supplier's own SKU/code for one Part — real multi-supplier
    reality, confirmed directly by Made and by Chris's own visit to
    Arya Motor, not assumed. A single Part.supplier_sku field would
    have silently discarded which supplier a code belonged to the
    moment a second supplier's code was ever entered.

    organization is set explicitly wherever this is created (the
    Part edit modal's own supplier-code section, or the GRN screen's
    inline capture) — same pattern as every other TenantScopedModel
    here that doesn't derive org from a single obvious parent
    relation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    part = models.ForeignKey(
        "inventory.Part", on_delete=models.CASCADE, related_name="supplier_codes",
        verbose_name="Part",
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name="part_codes",
        verbose_name="Supplier",
    )
    supplier_sku = models.CharField(max_length=100, verbose_name="Kode Part Supplier")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Supplier Part Code"
        verbose_name_plural  = "Supplier Part Codes"
        unique_together      = [("part", "supplier")]
        ordering             = ["supplier__name"]

    def __str__(self):
        return f"{self.part.name} @ {self.supplier.name}: {self.supplier_sku}"

    @classmethod
    def set_code(cls, *, organization, part, supplier, supplier_sku):
        """
        The one real entry point — used by both the Part edit modal's
        own supplier-code section and the GRN screen's inline
        capture, so there's one real place this upsert logic lives,
        not two independent copies that could drift. Idempotent by
        the real unique_together constraint — a second call for the
        same (part, supplier) updates the existing code rather than
        erroring or creating a duplicate.
        """
        obj, _ = cls.objects.update_or_create(
            organization=organization, part=part, supplier=supplier,
            defaults={"supplier_sku": supplier_sku},
        )
        return obj
