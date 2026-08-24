# =============================================================================
# === backend/apps/inventory/models.py ===
# =============================================================================
"""
Arthasee — Inventory

Split out of apps.service (where it originated in Sprint 1) into its
own app ahead of Sprint 2 — invoicing needs to reference Part
directly for line items, and keeping it inside apps.service would
mean invoicing importing from an unrelated domain's models, exactly
the cross-app coupling the organizations/service split otherwise
avoids.

Real production data already exists in these tables (Part rows,
stock counts, PartUsage history) — see this app's migrations/0001_
initial.py and apps/service/migrations/0004_... for how the move
happens without losing or recreating any of it: a migration-state
relabel plus a table rename, not a drop-and-recreate.

--- Sprint 7, Task 7.1: taxonomy + reorder cadence (Part, below) ---
Real requirements from Made's own handwritten meeting notes, 20 Aug
2026 — parts are genuinely different depending on type: a spare part
is vehicle-brand-specific (a Toyota spark plug won't fit a Honda), a
fluid is fluid-brand-specific but universal across vehicle brands
(Castrol works in any engine). reorder_cadence reflects real,
different restocking behavior per part class — an expensive,
low-turnover sensor is deliberately kept at zero stock and bought
same-day (HARIAN), while oli/kain/lampu get checked monthly.

--- Sprint 7, guided Stock Opname (bottom of this file) ---
StockOpnameSequence / StockOpnameSession / StockOpnameLineItem — a
real, guided physical stock count. See StockOpnameSession's own
docstring for the scoped-session design and the complete() method's
own docstring for how a variance becomes both a real stock correction
AND a real, netted GL posting.

--- cost_price (added here): real ledger-consistency fix ---
Real bug found live, 24 Aug 2026: GoodsReceived debits Account 1301
at real cost (GRN's own unit_cost), but PartConsumed was crediting
the SAME account using Part.unit_price — the SELLING price. 1301's
own real GL balance was silently internally inconsistent the whole
time this system has been live. cost_price is the fix's foundation:
one real, system-maintained "last cost" field on Part itself,
updated automatically by GoodsReceivedNoteLineItem.save() every time
stock is received (see that file's own updated docstring), and
consumed by WorkOrderMaterialLine.save() instead of unit_price (see
that file's own updated docstring) — closing the loop so both the
debit AND the credit side of 1301 finally use the same real basis.

Made's own confirmed call: "Last Cost," not a full Weighted Average
Cost engine — simple, predictable, no WAC math running on every
partial GRN. Read-only from the API's own PartSerializer — same
"system-derived, never manually entered" treatment already given to
current_stock, since a hand-typed cost_price would immediately
diverge from the real GRN history this whole fix depends on.
"""
import uuid
from decimal import Decimal

from apps.core.models import TenantScopedModel
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class Part(TenantScopedModel):
    """
    One catalog entry in a shop's parts inventory. Organization is
    set explicitly by the view at creation time — same pattern as
    Customer, since a Part doesn't derive its org from any other
    relation the way ServiceRecord derives its org from Vehicle.

    `current_stock` is denormalized, same philosophy as Vehicle's
    last_service_* fields: the true source of truth is the sum of
    every PartUsage (negative) and StockAdjustment (positive/
    negative) ever recorded against this Part, but reading that sum
    on every request would be needlessly expensive. Both PartUsage
    and StockAdjustment update this field atomically via
    `F("current_stock") ± quantity` on save — see below — so it's
    always correct without a recompute step.
    """

    class ItemType(models.TextChoices):
        SPARE_PART = "SPARE_PART", "Spare Part"
        FLUID      = "FLUID",      "Fluida"

    class VehicleBrand(models.TextChoices):
        TOYOTA     = "TOYOTA",     "Toyota"
        HONDA      = "HONDA",      "Honda"
        DAIHATSU   = "DAIHATSU",   "Daihatsu"
        SUZUKI     = "SUZUKI",     "Suzuki"
        MITSUBISHI = "MITSUBISHI", "Mitsubishi"

    class FluidBrand(models.TextChoices):
        SHELL               = "SHELL",               "Shell"
        CASTROL             = "CASTROL",              "Castrol"
        REPSOL              = "REPSOL",                "Repsol"
        FASTRON             = "FASTRON",               "Fastron"
        PERTAMINA_MEDITRAN  = "PERTAMINA_MEDITRAN",    "Pertamina Meditran"

    class ViscosityGrade(models.TextChoices):
        ENGINE_10W40 = "10W-40",  "10W-40"
        ENGINE_5W30  = "5W-30",   "5W-30"
        GEAR_SAE90   = "SAE_90",  "Oli 90 (SAE 90)"
        GEAR_SAE140  = "SAE_140", "Oli 140 (SAE 140)"

    class ReorderCadence(models.TextChoices):
        HARIAN        = "HARIAN",        "Harian"
        MINGGUAN      = "MINGGUAN",      "Mingguan"
        BULANAN       = "BULANAN",       "Bulanan"
        TIGA_BULANAN  = "TIGA_BULANAN",  "3 Bulanan"

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Nama Part")
    sku  = models.CharField(
        max_length=50, blank=True, verbose_name="Kode/SKU",
        help_text="Opsional — kode internal bengkel untuk part ini, jika ada.",
    )
    # Decimal, not integer — oli (oil) is sold/consumed by the liter,
    # a genuinely fractional unit.
    unit = models.CharField(
        max_length=20, default="pcs", verbose_name="Satuan",
        help_text="pcs, liter, set, botol, dll.",
    )
    current_stock = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Stok Saat Ini",
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Harga Satuan",
        help_text="Harga jual per satuan saat ini — perubahan di sini tidak mengubah riwayat pemakaian yang sudah tercatat.",
    )
    # Real ledger-consistency fix — see module docstring above for
    # the full incident this closes. "Last cost," Made's own
    # confirmed call: overwritten with the most recent
    # GoodsReceivedNoteLineItem.unit_cost every time this part is
    # actually received (see that model's own save()) — never a
    # running Weighted Average Cost. default=0 means "no real GRN
    # history yet for this part" — WorkOrderMaterialLine.save() treats
    # 0 the same as null and falls back to unit_price in that case
    # (Made's own confirmed "soft fallback," so a brand-new part can
    # still be consumed on a job before its first official GRN,
    # rather than blocking a mechanic mid-job). Read-only via the API
    # — see PartSerializer — same "system-derived, never hand-typed"
    # treatment as current_stock, since a manually-entered value here
    # would immediately drift from the real GRN history this field
    # exists to reflect.
    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Harga Beli (HPP)",
        help_text="Harga pokok (cost) terakhir dari GRN — diperbarui otomatis, tidak bisa diisi manual. 0 berarti part ini belum pernah menerima GRN.",
    )
    # Real per-part reorder threshold. Replaces what used to be a
    # single hardcoded global rule (PartListView.LOW_STOCK_THRESHOLD
    # = 5, applied identically to every part in every organization)
    # — a part used constantly (oli mesin) and a part rarely touched
    # (a specific sensor) genuinely need different thresholds, not
    # one shared magic number.
    #
    # default=0 means "no threshold configured — never flag this
    # part as low stock purely from its own threshold." A part
    # completely out of stock (current_stock <= 0) still surfaces
    # regardless of this setting — see PartListView's own low_stock
    # filter — since "zero" needs no configuration to be meaningful,
    # UNLESS reorder_cadence is HARIAN (see below) — zero stock is
    # the deliberately correct state for a HARIAN part, not a gap.
    #
    # Every part that existed before this field shipped was
    # backfilled to 5 by this migration's own data step, preserving
    # today's exact alerting behavior for real, existing parts. Only
    # NEW parts created after this ships start at the quiet default
    # of 0 — see migrations/00XX_add_minimum_stock.py for exactly
    # how that split is achieved.
    minimum_stock = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Stok Minimum",
        help_text="Ambang batas peringatan stok menipis untuk part ini — 0 berarti tidak ada peringatan dari threshold ini (part yang benar-benar habis tetap muncul, kecuali untuk part dengan Frekuensi Pengecekan Harian).",
    )
    # ── Sprint 7, Task 7.1: taxonomy ─────────────────────────────
    item_type = models.CharField(
        max_length=20, choices=ItemType.choices, default=ItemType.SPARE_PART,
        verbose_name="Jenis Item",
        help_text="Spare Part (spesifik per merk kendaraan) atau Fluida (universal lintas merk kendaraan).",
    )
    vehicle_brand = models.CharField(
        max_length=30, choices=VehicleBrand.choices, blank=True, default="",
        verbose_name="Merk Kendaraan",
        help_text="Hanya berlaku untuk Spare Part — kosong berarti belum dikategorikan.",
    )
    fluid_brand = models.CharField(
        max_length=30, choices=FluidBrand.choices, blank=True, default="",
        verbose_name="Merk Fluida",
        help_text="Hanya berlaku untuk Fluida — kosong berarti belum dikategorikan.",
    )
    viscosity_grade = models.CharField(
        max_length=20, choices=ViscosityGrade.choices, blank=True, default="",
        verbose_name="Tingkat Kekentalan",
        help_text="Hanya berlaku untuk Fluida — kosong berarti belum dikategorikan.",
    )
    reorder_cadence = models.CharField(
        max_length=20, choices=ReorderCadence.choices, blank=True, default="",
        verbose_name="Frekuensi Pengecekan",
        help_text="Seberapa sering part ini ditinjau untuk pemesanan ulang. Kosong berarti belum dikategorikan.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Part"
        verbose_name_plural  = "Parts"
        ordering             = ["name"]

    def __str__(self):
        return f"{self.name} ({self.current_stock} {self.unit})"

    def clean(self):
        """
        The one real place the SPARE_PART/FLUID mutual-exclusivity
        invariant is enforced — Chris's own confirmed call. Only
        checks for the WRONG-type field being set; does not require
        the correct-type field to already be filled in (a part mid-
        creation, not yet fully categorized, is not itself invalid —
        matches the same "honest blank, not a guessed default" spirit
        as the Sprint 7 migration backfill for existing parts).
        """
        super().clean()
        errors = {}
        if self.item_type == self.ItemType.SPARE_PART:
            if self.fluid_brand:
                errors["fluid_brand"] = "Part bertipe Spare Part tidak boleh memiliki Merk Fluida."
            if self.viscosity_grade:
                errors["viscosity_grade"] = "Part bertipe Spare Part tidak boleh memiliki Tingkat Kekentalan."
        elif self.item_type == self.ItemType.FLUID:
            if self.vehicle_brand:
                errors["vehicle_brand"] = "Part bertipe Fluida tidak boleh memiliki Merk Kendaraan."
        if errors:
            raise ValidationError(errors)


class PartUsage(TenantScopedModel):
    """
    One line of "this Part was used on this ServiceRecord." Creating
    one atomically decrements Part.current_stock — the mechanism
    behind Made's own "G inventory 20−4=16" note.

    `service_record` is a cross-app FK (to apps.service.ServiceRecord)
    — referenced by string ("service.ServiceRecord") rather than a
    direct class import, standard Django practice for cross-app FKs
    that avoids any import-ordering questions between the two apps.

    `unit_price_at_time` is a deliberate snapshot, not a live
    reference to Part.unit_price — a price change next month must
    never silently rewrite the effective cost of a past service
    record. Same instinct as ServiceRecord being append-only: history
    should not move once written.
    """
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_record = models.ForeignKey(
        "service.ServiceRecord", on_delete=models.CASCADE, related_name="part_usages",
        verbose_name="Catatan Servis",
        # CASCADE (not PROTECT) is safe specifically because
        # ServiceRecord has no delete endpoint at all — there is
        # currently no code path that could ever cascade-delete a
        # PartUsage as a side effect. If a delete endpoint is ever
        # added to ServiceRecord, this decision needs revisiting.
    )
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="usages",
        verbose_name="Part",
        # PROTECT — same Principle 2 reasoning as everywhere else. A
        # Part that's never been used can be deleted freely; one with
        # real usage history cannot.
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah")
    unit_price_at_time = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Harga Saat Digunakan",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Part Usage"
        verbose_name_plural  = "Part Usages"
        ordering             = ["-created_at"]

    def __str__(self):
        return f"{self.part.name} × {self.quantity} — {self.service_record}"

    def _resolve_organization(self):
        return self.service_record.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.unit_price_at_time:
            self.unit_price_at_time = self.part.unit_price
        super().save(*args, **kwargs)
        if creating:
            # F() expression, not read-modify-write — avoids a race
            # condition if two mechanics log usage of the same part
            # at the same moment. Deliberately allowed to go negative
            # (see PartUsageSerializer.validate for why) rather than
            # hard-blocking here at the model layer.
            Part.objects.filter(pk=self.part_id).update(
                current_stock=models.F("current_stock") - self.quantity
            )


class StockAdjustment(TenantScopedModel):
    """
    Every non-usage change to a Part's stock — restocking after a
    purchase, correcting a miscount, writing off damaged/lost stock.
    Without this, current_stock could only ever go down after a
    Part's initial creation value.

    "correction" (reason, below) is also now the exact mechanism
    Sprint 7's Stock Opname uses to apply a physical count back onto
    Part.current_stock — see StockOpnameSession.complete(), which
    creates one of these per part with a nonzero variance, reusing
    this same proven F()-based update rather than a second, parallel
    stock-mutation path.
    """
    REASON_CHOICES = [
        ("restock",    "Restock / Pembelian"),
        ("correction", "Koreksi Stok"),
        ("damage",     "Rusak / Hilang"),
        ("work_order_cancelled", "Pembatalan Work Order"),
        ("customer_cancelled_part", "Part Dibatalkan Pelanggan"),
        ("purchase_return", "Retur Pembelian"),
    ]

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="adjustments",
        verbose_name="Part",
    )
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Perubahan Jumlah")
    reason = models.CharField(max_length=30, choices=REASON_CHOICES, default="restock", verbose_name="Alasan")
    notes  = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Stock Adjustment"
        verbose_name_plural  = "Stock Adjustments"
        ordering             = ["-created_at"]

    def __str__(self):
        sign = "+" if self.quantity_change >= 0 else ""
        return f"{self.part.name} {sign}{self.quantity_change} ({self.get_reason_display()})"

    def _resolve_organization(self):
        return self.part.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            Part.objects.filter(pk=self.part_id).update(
                current_stock=models.F("current_stock") + self.quantity_change
            )


class StockOpnameSequence(TenantScopedModel):
    """Mirrors PurchaseOrderSequence / PurchaseReturnSequence exactly."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Stock Opname Sequence"
        verbose_name_plural  = "Stock Opname Sequences"
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


class StockOpnameSession(TenantScopedModel):
    """
    Sprint 7, Task 7.3 — a real, guided physical stock count.

    Deliberately SCOPED, not organization-wide by default — Chris and
    Made's own confirmed call: start_session(part_ids=[...]) counts
    only a caller-chosen subset (e.g. "today's Bulanan parts"),
    matching the whole point of the Task 7.1 reorder-cadence tiers —
    forcing a full-catalog recount every time would defeat them.

    system_stock_at_time (on StockOpnameLineItem, below) is frozen
    per-line at session START, not at completion — an unrelated stock
    movement mid-session (a work order consuming a part while the
    count is still in progress) must never corrupt the variance this
    session is measuring. Same "capture once, don't recompute from a
    shifting database" discipline as GoodsReceived's own amount and
    PurchaseReturned's own debit_account_code.
    """
    class Status(models.TextChoices):
        DRAFT     = "DRAFT", "Draft"
        COMPLETED = "COMPLETED", "Selesai"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor Opname")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name="Status",
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Waktu Selesai")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # real, evolving status — like PurchaseOrder, unlike a frozen document

    class Meta:
        verbose_name        = "Stock Opname Session"
        verbose_name_plural  = "Stock Opname Sessions"
        ordering             = ["-created_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = StockOpnameSequence.next_number(self.organization)
            self.number = f"SO/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def start_session(cls, *, organization, part_ids, created_by=None):
        """
        The one real entry point. part_ids must be non-empty — an
        opname covering zero parts isn't a real session.

        system_stock_at_time is captured from each Part's CURRENT
        current_stock, right now, inside this same transaction — the
        point-in-time snapshot the whole variance calculation is
        measured against.
        """
        if not part_ids:
            raise ValueError("Stock Opname harus mencakup minimal satu part.")

        with transaction.atomic():
            session = cls.objects.create(organization=organization, created_by=created_by)
            parts = list(Part.objects.filter(organization=organization, id__in=part_ids))
            found_ids = {str(p.id) for p in parts}
            missing = {str(pid) for pid in part_ids} - found_ids
            if missing:
                raise ValueError(f"Part tidak ditemukan: {', '.join(sorted(missing))}")

            StockOpnameLineItem.objects.bulk_create([
                StockOpnameLineItem(
                    organization=organization, session=session, part=part,
                    system_stock_at_time=part.current_stock,
                )
                for part in parts
            ])
        return session

    def complete(self):
        """
        Computes variance per line, corrects Part.current_stock via a
        real StockAdjustment per part with a nonzero variance (same
        proven F()-based mechanism PurchaseReturnLineItem already
        uses), and — ONLY if the netted totals aren't both zero —
        publishes StockOpnameCompleted. A session where every counted
        part matched exactly is a real, valid outcome:
        Part.current_stock needed no correction, and nothing gets
        posted to the ledger — not an empty balanced entry, no entry
        at all.

        Requires every line in THIS session to have a real
        physical_count already recorded — a partially-counted session
        cannot be completed, since an uncounted line has no honest
        variance to measure (genuinely unknown, not "zero").

        Valuation basis for the event's Rupiah totals is
        Part.unit_price — the same basis
        apps.inventory.reports.stock_summary() already uses for every
        other Inventory-adjacent figure in this system (Roadmap Open
        Decision #5's known, accepted gap against the ledger's true
        cost basis — not a new, third valuation basis introduced here).
        """
        if self.status == self.Status.COMPLETED:
            raise ValueError("Sesi Stock Opname ini sudah diselesaikan.")

        lines = list(self.line_items.select_related("part"))
        uncounted = [line for line in lines if line.physical_count is None]
        if uncounted:
            raise ValueError(
                f"{len(uncounted)} part dalam sesi ini belum dihitung — "
                f"semua part harus dihitung sebelum sesi diselesaikan."
            )

        with transaction.atomic():
            shortage_amount = Decimal("0")
            surplus_amount  = Decimal("0")

            for line in lines:
                variance_qty = line.physical_count - line.system_stock_at_time
                if variance_qty == 0:
                    continue

                variance_value = abs(variance_qty) * line.part.unit_price
                if variance_qty < 0:
                    shortage_amount += variance_value
                else:
                    surplus_amount += variance_value

                StockAdjustment.objects.create(
                    organization=self.organization, part=line.part,
                    quantity_change=variance_qty, reason="correction",
                    notes=(
                        f"Stock Opname {self.number} — sistem: "
                        f"{line.system_stock_at_time}, fisik: {line.physical_count}"
                    ),
                    created_by=self.created_by,
                )

            self.status = self.Status.COMPLETED
            self.completed_at = timezone.now()
            self.save(update_fields=["status", "completed_at", "updated_at"])

            if shortage_amount > 0 or surplus_amount > 0:
                from apps.core.events.bus import default_bus
                from apps.inventory.events import StockOpnameCompleted
                default_bus.publish(StockOpnameCompleted(
                    organization_id=self.organization.id,
                    stock_opname_session_id=self.id,
                    shortage_amount=shortage_amount,
                    surplus_amount=surplus_amount,
                    line_item_count=len(lines),
                ))

        return self


class StockOpnameLineItem(TenantScopedModel):
    """
    One part being counted in one StockOpnameSession.
    system_stock_at_time is a frozen snapshot (see StockOpnameSession
    docstring); physical_count starts null — genuinely uncounted, not
    defaulted to 0, since 0 would be indistinguishable from "we
    counted it and found nothing."
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        StockOpnameSession, on_delete=models.CASCADE, related_name="line_items",
        verbose_name="Sesi Stock Opname",
    )
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="stock_opname_lines",
        verbose_name="Part",
    )
    system_stock_at_time = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Stok Sistem Saat Mulai",
    )
    physical_count = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Hasil Hitung Fisik",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Stock Opname Line Item"
        verbose_name_plural  = "Stock Opname Line Items"
        ordering             = ["created_at"]
        unique_together      = [("session", "part")]

    def __str__(self):
        return f"{self.part.name} — {self.session.number}"

    def _resolve_organization(self):
        return self.session.organization

    @property
    def variance(self):
        if self.physical_count is None:
            return None
        return self.physical_count - self.system_stock_at_time

    def record_count(self, physical_count):
        """
        The one real mutation point for entering a count — used by
        the PATCH endpoint. Blocked once the parent session is
        already COMPLETED, same "frozen once real" discipline as
        every other finalized document in this codebase.
        """
        if self.session.status == StockOpnameSession.Status.COMPLETED:
            raise ValueError("Sesi Stock Opname ini sudah diselesaikan — hasil hitung tidak bisa diubah.")
        self.physical_count = physical_count
        self.save(update_fields=["physical_count", "updated_at"])
