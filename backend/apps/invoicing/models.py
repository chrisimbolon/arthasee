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

UPDATED — real Payment tracking: balance_due now nets out real
Payment rows (apps.payments.models.Payment), not just deposit_amount.
deposit_amount itself is left in place and still subtracted — it
predates this change and nothing currently writes to it anywhere in
invoicing/views.py or serializers.py as of this update, so it's
effectively dormant today. Left alone rather than removed, since it's
unclear whether it's meant to represent a pre-invoice down payment
collected at a different stage (Estimate/WorkOrder) — worth a
deliberate decision later, not something to silently delete here.
status="PAID" is no longer settable via InvoiceStatusUpdateView's
manual PATCH — see that view's own updated docstring — it is now
ONLY ever set by apps.payments.models.Payment.record() the moment
balance_due actually reaches zero.
"""
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.core.models import TenantScopedModel
from django.db import models, transaction
from django.utils import timezone


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
        ("PARTIALLY_PAID",  "Dibayar Sebagian"),        
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
    # Made's own explicit reason, confirmed 31 Jul: a specific
    # mechanic must be identifiable on every invoice, even for
    # routine work, so he can go back and question that person
    # directly if the same car has an issue again — same class of
    # real accountability need as knowing which SA received a car at
    # intake. Frozen at invoice-creation time, same discipline as
    # customer_name_snapshot/license_plate_snapshot above: the
    # Mechanic roster can change (someone leaves, gets renamed) and
    # that must never silently alter what an already-issued invoice
    # says. See save() below for where this is both populated AND
    # hard-required — a plain field default can't enforce "this must
    # exist," only an explicit check can.
    mechanic_name_snapshot = models.CharField(max_length=200, verbose_name="Nama Mekanik")

    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT", verbose_name="Status")
    deposit_amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Deposit")
    # 15 Sep 2026 — real, deliberately nullable due date. None (the
    # default, and the real state of every invoice created before
    # this field existed) means "no due date set" — such an invoice
    # can never be overdue, an honest default rather than a forced
    # requirement on every invoice.
    due_date        = models.DateField(null=True, blank=True, verbose_name="Jatuh Tempo")
    issued_event_id = models.UUIDField(null=True, blank=True, editable=False, verbose_name="ID Event Penerbitan")

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
    def total_paid(self):
        """
        Sum of every real Payment recorded against this invoice
        (apps.payments.models.Payment, related_name="payments").
        Computed on read, same discipline as subtotal/total above —
        no denormalized running total to let drift from the real
        Payment rows that are the actual source of truth.
        """
        return sum((p.amount for p in self.payments.all()), Decimal("0"))

    @property
    def total_pph23_withheld(self):
        """
        10 Oct 2026 — PPh 23 + PPh Final UMKM patch, follow-up. Sum of
        pph23_withheld_amount across every real Payment recorded
        against this invoice — mirrors total_paid's own
        computed-on-read discipline exactly, same reasoning (no
        denormalized running total to let drift from the real Payment
        rows). Deliberately NOT subtracted from balance_due above —
        the withheld portion is still part of the full settled value
        (see Payment.record()'s own docstring); this is purely a
        reporting figure for the printed receipt/invoice PDF, never
        used in any balance calculation.
        """
        return sum((p.pph23_withheld_amount for p in self.payments.all()), Decimal("0"))

    @property
    def balance_due(self):
        return self.total - self.deposit_amount - self.total_paid

    @property
    def is_overdue(self):
        """
        Real, deliberate DERIVED flag, not a 5th status value — an
        invoice can genuinely be BOTH partially paid AND overdue at
        once, a real combination a single status field can't
        represent. Only ISSUED/PARTIALLY_PAID invoices can ever be
        overdue: a PAID invoice is fully settled regardless of how
        late that settlement was, a CANCELLED one was never really
        owed, and a DRAFT one was never even issued yet — "late"
        doesn't honestly apply to any of those three.
        """
        if self.due_date is None:
            return False
        if self.status not in ("ISSUED", "PARTIALLY_PAID"):
            return False
        return self.due_date < date.today()

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating:
            if not self.customer_name_snapshot:
                self.customer_name_snapshot = self.service_record.vehicle.customer.name
            if not self.license_plate_snapshot:
                self.license_plate_snapshot = self.service_record.vehicle.plate_number
            if not self.mechanic_name_snapshot:
                # getattr(..., None) — the same reverse-OneToOneField
                # probe already used throughout this project (e.g.
                # WorkOrder.mark_started()'s own estimate lookup):
                # ServiceRecord.work_order is a reverse accessor, and
                # Django raises RelatedObjectDoesNotExist (a subclass
                # of AttributeError) rather than returning None when
                # nothing points back to it — getattr's default
                # argument absorbs exactly that case.
                work_order = getattr(self.service_record, "work_order", None)
                if work_order is None or work_order.assigned_to is None:
                    # Fail loudly, not silently — Made's own explicit
                    # requirement: no invoice without an identifiable
                    # mechanic. Same "no safe generic fallback to
                    # guess at" discipline as the invoice_code check
                    # just below — there is no reasonable default
                    # name to invent here.
                    raise ValueError(
                        "Work order untuk catatan servis ini belum memiliki "
                        "mekanik penanggung jawab — tidak bisa membuat invoice."
                    )
                self.mechanic_name_snapshot = work_order.assigned_to.name
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

    # ── 22 Oct 2026 (Phase 21, Task C1) — editing JASA on a DRAFT invoice ──
    # Made's note, 12 Sep 2026: "Waktu invoice di posisi draft, masih bisa
    # tambah & kurang barang / jasa." This covers jasa only: a jasa line has
    # no stock or ledger effect until the invoice is issued, and
    # InvoiceIssued reads the line items at that moment, so whatever is
    # here when "Terbitkan" is clicked is exactly what gets posted. Parts
    # are Task C2 (they need their own stock + COGS posting).
    #
    # Every change locks this invoice's row first and re-checks DRAFT under
    # the lock — InvoiceStatusUpdateView takes the same lock before issuing
    # — so a jasa can never be added in the instant between "total
    # computed" and "status = ISSUED".
    _MAX_LABOR_QTY   = Decimal("99999999")
    _MAX_LABOR_PRICE = Decimal("9999999999")

    def _lock_draft(self):
        locked = Invoice.objects.select_for_update().get(pk=self.pk)
        if locked.status != "DRAFT":
            # 22 Oct 2026 (Task C2): message made generic — jasa and parts share this lock.
            raise ValueError("Invoice sudah diterbitkan atau dibatalkan — tidak bisa diubah lagi.")
        return locked

    @classmethod
    def _clean_labor(cls, description, quantity, unit_price):
        description = (description or "").strip()
        if not description:
            raise ValueError("Deskripsi jasa wajib diisi.")
        try:
            qty = Decimal(str(quantity))
            price = Decimal(str(unit_price))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Jumlah dan harga harus berupa angka.")
        if not qty.is_finite() or qty <= 0 or qty > cls._MAX_LABOR_QTY:
            raise ValueError("Jumlah harus lebih dari 0.")
        if not price.is_finite() or price < 0 or price > cls._MAX_LABOR_PRICE:
            raise ValueError("Harga tidak boleh negatif.")
        return description[:255], qty.quantize(Decimal("0.01")), price.quantize(Decimal("0.01"))

    def _own_labor_line(self, line):
        if line.invoice_id != self.pk:
            raise ValueError("Baris ini bukan milik invoice ini.")
        if line.kind != "labor":
            raise ValueError("Hanya baris jasa yang bisa diubah di sini.")

    def add_labor_line(self, *, description, quantity=1, unit_price):
        description, qty, price = self._clean_labor(description, quantity, unit_price)
        with transaction.atomic():
            self._lock_draft()
            return InvoiceLineItem.objects.create(
                invoice=self, kind="labor", description=description, quantity=qty, unit_price=price,
            )

    def update_labor_line(self, line, *, description, quantity, unit_price):
        self._own_labor_line(line)
        description, qty, price = self._clean_labor(description, quantity, unit_price)
        with transaction.atomic():
            self._lock_draft()
            line.description, line.quantity, line.unit_price = description, qty, price
            line.save(update_fields=["description", "quantity", "unit_price"])
        return line

    def remove_labor_line(self, line):
        self._own_labor_line(line)
        with transaction.atomic():
            self._lock_draft()
            line.delete()

    # ── 22 Oct 2026 (Phase 21, Task C2) — PARTS on a DRAFT invoice ─────────
    # Made's note, 12 Sep 2026: "Waktu invoice di posisi draft, masih bisa
    # tambah & kurang barang." Unlike jasa (C1), a part moves stock and cost:
    # the WorkOrder is already closed and its parts' cost already sits in
    # COGS, so changes here go straight between Inventory and COGS through
    # InvoicePartAdjusted (see its docstring). Agreed 22 Oct with Chris:
    #   - removing is whole-line only (no partial returns);
    #   - "Dikembalikan ke stok" = stock back + Dr 1301 / Cr 5001 at the
    #     line's own frozen cost; the line leaves the invoice;
    #   - "Tidak ditagih" = no stock or ledger movement; the line STAYS at
    #     Rp 0 marked "(tidak ditagih)" so the customer sees it was free.
    # Same row lock + DRAFT re-check as the jasa methods, plus the period
    # lock (readiness is checked in the views, Cheat Sheet section 13).
    NOT_CHARGED_SUFFIX = " (tidak ditagih)"

    def _work_order_unit_cost(self, part_id):
        """The cost this part left stock at on this invoice's WorkOrder —
        quantity-weighted across its material lines — or None."""
        work_order = getattr(self.service_record, "work_order", None)
        if work_order is None:
            return None
        lines = [ml for ml in work_order.material_lines.all() if ml.part_id == part_id]
        quantity = sum((ml.quantity for ml in lines), Decimal("0"))
        if not quantity:
            return None
        total = sum((ml.quantity * ml.unit_price_at_time for ml in lines), Decimal("0"))
        return (total / quantity).quantize(Decimal("0.01"))

    @staticmethod
    def _current_unit_cost(part):
        # The same rule WorkOrderMaterialLine.save() uses: last real cost,
        # falling back to the selling price for a part never received via GRN.
        return (part.cost_price or part.unit_price).quantize(Decimal("0.01"))

    def _own_part_line(self, line):
        if line.invoice_id != self.pk:
            raise ValueError("Baris ini bukan milik invoice ini.")
        if line.kind != "part" or line.part_id is None:
            raise ValueError("Hanya baris part yang bisa diubah di sini.")

    @staticmethod
    def _today():
        from apps.accounting.periods import safe_local_date
        return safe_local_date(timezone.now())

    def add_part_line(self, *, part, quantity, unit_price=None):
        """Adds a part used on this job: stock goes down now (through a real
        PartUsage, so the vehicle's service history shows it), the line is
        billed at the selling price, and its cost moves Inventory -> COGS."""
        from apps.accounting.models import AccountingPeriod
        from apps.core.events.bus import default_bus
        from apps.inventory.models import PartUsage
        from .events import InvoicePartAdjusted

        if part.organization_id != self.organization_id:
            raise ValueError("Part tidak ditemukan.")
        price = part.unit_price if unit_price in (None, "") else unit_price
        _, qty, price = self._clean_labor(part.name, quantity, price)
        unit_cost = self._current_unit_cost(part)
        today = self._today()

        with transaction.atomic():
            self._lock_draft()
            AccountingPeriod.assert_open_for_posting(self.organization, today)
            PartUsage.objects.create(
                organization=self.organization, service_record=self.service_record,
                part=part, quantity=qty, unit_price_at_time=price,
            )
            line = InvoiceLineItem.objects.create(
                invoice=self, kind="part", description=part.name, quantity=qty,
                unit_price=price, part=part, unit_cost=unit_cost,
            )
            default_bus.publish(InvoicePartAdjusted(
                organization_id=self.organization_id, invoice_id=self.id, part_id=part.id,
                direction="added", quantity=qty, unit_cost=unit_cost,
                amount=(qty * unit_cost).quantize(Decimal("0.01")), transaction_date=today,
            ))
        return line

    def return_part_line(self, line):
        """"Dikembalikan ke stok": the whole line goes back to stock, its
        cost back from COGS to Inventory at the cost it was booked at, and
        the line leaves the invoice (and the vehicle's service history)."""
        from apps.accounting.models import AccountingPeriod
        from apps.core.events.bus import default_bus
        from apps.inventory.models import PartUsage, StockAdjustment
        from .events import InvoicePartAdjusted

        self._own_part_line(line)
        unit_cost = (
            line.unit_cost
            or self._work_order_unit_cost(line.part_id)
            or self._current_unit_cost(line.part)
        )
        today = self._today()

        with transaction.atomic():
            self._lock_draft()
            AccountingPeriod.assert_open_for_posting(self.organization, today)
            StockAdjustment.objects.create(
                organization=self.organization, part=line.part, quantity_change=line.quantity,
                reason="invoice_part_returned", notes=f"Dikembalikan dari invoice {self.number}",
            )
            usage = (PartUsage.objects
                     .filter(service_record=self.service_record, part=line.part, quantity=line.quantity)
                     .order_by("-created_at").first())
            if usage is not None:
                usage.delete()  # history only — the StockAdjustment above already moved the stock
            default_bus.publish(InvoicePartAdjusted(
                organization_id=self.organization_id, invoice_id=self.id, part_id=line.part_id,
                direction="returned", quantity=line.quantity, unit_cost=unit_cost,
                amount=(line.quantity * unit_cost).quantize(Decimal("0.01")), transaction_date=today,
            ))
            line.delete()

    def mark_part_not_charged(self, line):
        """"Tidak ditagih": the part was used and stays on the invoice at
        Rp 0, marked so the customer can see it was given free. No stock or
        ledger movement — its cost correctly stays in COGS."""
        self._own_part_line(line)
        with transaction.atomic():
            self._lock_draft()
            if not line.description.endswith(self.NOT_CHARGED_SUFFIX):
                line.description = line.description[: 255 - len(self.NOT_CHARGED_SUFFIX)] + self.NOT_CHARGED_SUFFIX
            line.unit_price = Decimal("0.00")
            line.save(update_fields=["description", "unit_price"])
        return line


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
    # 22 Oct 2026 (Phase 21, Task C2) — the COST of one unit of this part
    # line (never shown to the customer). Copied when the line is created:
    # from the WorkOrder's material lines at "Buat Invoice", or the part's
    # cost price when added on a draft. "Dikembalikan ke stok" reverses at
    # exactly this cost. Null for jasa lines and for part lines created
    # before this field existed (those fall back to the WO cost).
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, editable=False,
        verbose_name="Harga Pokok (HPP)",
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

    def save(self, *args, **kwargs):
        # 6 Sep 2026 — real, deliberate policy guard, found via a
        # design-review trace (Sansan's own "negative transaction"
        # question), not a live incident: a negative quantity or
        # unit_price here would flow straight into Invoice.total (a
        # plain sum of these subtotals) and from there into
        # InvoiceIssued's own posting — posting_engine.py's own
        # _lines() now fails loudly if a negative amount ever reaches
        # it (see that function's own updated docstring), but the
        # REAL fix belongs here, at the source: a standard Invoice
        # must never represent a negative transaction at all. Chris's
        # own confirmed policy: a genuine negative transaction (a
        # refund, a return) belongs in a dedicated Credit Note/Return
        # flow with its own journal treatment, never passed through
        # as a raw negative Invoice line.
        # 6 Sep 2026 — real bug found live, hours after this guard
        # first shipped: quantity/unit_price aren't guaranteed to be
        # real Decimal instances yet at this point — Django only
        # coerces a DecimalField's raw assigned value at the DB
        # layer, AFTER save() runs, not before. The real invoice-
        # creation view passes unit_price as a plain string in at
        # least one real call site, and a bare `str < Decimal`
        # comparison raises TypeError, not the intended ValueError —
        # a real regression this exact guard introduced, caught by
        # 9 real existing tests failing loudly rather than silently.
        # Decimal(str(x)) round-trips correctly regardless of
        # whether x is already a Decimal, a string, an int, or a
        # float — safe, defensive coercion before the comparison
        # that actually matters.
        if self.quantity is not None and Decimal(str(self.quantity)) < Decimal("0"):
            raise ValueError(
                "Jumlah pada baris invoice tidak boleh negatif — gunakan alur "
                "Nota Kredit/Retur yang terpisah untuk transaksi negatif, "
                "bukan invoice standar."
            )
        if self.unit_price is not None and Decimal(str(self.unit_price)) < Decimal("0"):
            raise ValueError(
                "Harga satuan pada baris invoice tidak boleh negatif — "
                "gunakan alur Nota Kredit/Retur yang terpisah untuk "
                "transaksi negatif, bukan invoice standar."
            )
        super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price
