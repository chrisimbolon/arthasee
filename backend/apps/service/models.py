# =============================================================================
# === backend/apps/service/models.py ===
# =============================================================================
"""
Arthasee — Service (Phase 1 + Sprint 1 additions)

Sprint 1 adds two things, both traced directly to source documents:
  1. Vehicle fields confirmed against Made's actual STNK paperwork
     (chassis/engine/BPKB numbers, color, registration expiry).
  2. A real inventory subsystem — Part, PartUsage, StockAdjustment —
     replacing the free-text `parts_replaced` field's implicit
     assumption that stock tracking doesn't exist.

Deliberate scope note: `parts_replaced` (TextField) stays on
ServiceRecord unchanged — some jobs use parts that were never
formally stocked (a one-off part bought same-day for a specific
repair), and forcing every part through the Part catalog would make
those jobs harder to log, not easier. PartUsage is additive, not a
replacement — a mechanic can use either or both per service record.
"""
import uuid

from apps.core.models import TenantScopedModel
from django.db import models

# Same 5,000 km interval named on the handwritten page — a real,
# standard Indonesian service-reminder interval, not an arbitrary
# number.
SERVICE_DUE_INTERVAL_KM = 5000


class Customer(TenantScopedModel):
    """
    A bengkel's customer — the person who brings the vehicle in,
    which may or may not be the same as the registered owner on the
    STNK. That distinction was explicit on the handwritten spec, not
    an assumption made here.
    """
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name      = models.CharField(max_length=200, verbose_name="Nama Pelanggan")
    phone     = models.CharField(max_length=20, blank=True, verbose_name="Nomor Telepon")
    stnk_name = models.CharField(
        max_length=200, blank=True, verbose_name="Nama di STNK",
        help_text="Nama pemilik terdaftar di STNK, jika berbeda dari nama pelanggan.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Customer"
        verbose_name_plural  = "Customers"
        ordering             = ["name"]

    def __str__(self):
        return self.name


class Vehicle(TenantScopedModel):
    """
    One vehicle, belonging to one Customer — a customer can have
    multiple vehicles (family car, work vehicle, etc). Plate number
    is unique per shop, not globally unique — two unrelated bengkels
    can each have a record for the same real-world plate.

    Sprint 1 fields below are all `blank=True` / `null=True` on
    purpose: every existing Vehicle row in production has none of
    this data, and a migration that suddenly required it would break
    on the very first `migrate` run against real data. These fields
    fill in over time as STNK documents get transcribed, not all at
    once.
    """
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        # PROTECT, not CASCADE — Principle 2 ("no service history
        # should ever be lost"). A customer with zero vehicles can
        # still be deleted freely (fixing a genuine data-entry
        # mistake) — but the moment a real Vehicle exists, deletion
        # is blocked outright. See views.py's delete() handlers for
        # the friendly error this produces instead of a raw 500.
        Customer, on_delete=models.PROTECT, related_name="vehicles",
        verbose_name="Pelanggan",
    )
    plate_number      = models.CharField(max_length=20, verbose_name="Nomor Plat")
    manufacture_year  = models.PositiveIntegerField(verbose_name="Tahun Pembuatan")
    vehicle_type      = models.CharField(max_length=100, verbose_name="Jenis Kendaraan")
    model              = models.CharField(max_length=100, verbose_name="Type/Model")
    current_odometer_km = models.PositiveIntegerField(default=0, verbose_name="KM Saat Ini")

    # ── Sprint 1: STNK-sourced fields ─────────────────────────────
    # Deliberately NOT named `jenis` — see the models.py module
    # docstring's sibling note in the roadmap doc: `vehicle_type`
    # above already means "Jenis Kendaraan" (Mobil/Motor) in this
    # codebase. `body_style` covers the separate Sedan/SUV/MPV
    # categorization from Made's notes without overloading a field
    # that already means something else to existing code and data.
    body_style = models.CharField(
        max_length=100, blank=True, verbose_name="Jenis Bodi",
        help_text="Sedan, SUV, MPV, dll — kategori bentuk bodi, terpisah dari Jenis Kendaraan.",
    )
    chassis_number = models.CharField(
        max_length=50, blank=True, verbose_name="No. Rangka",
        help_text="Nomor rangka/NIK sesuai STNK.",
    )
    engine_number = models.CharField(
        max_length=50, blank=True, verbose_name="No. Mesin",
    )
    bpkb_number = models.CharField(
        max_length=50, blank=True, verbose_name="No. BPKB",
    )
    color = models.CharField(max_length=50, blank=True, verbose_name="Warna")
    registration_expiry = models.DateField(
        null=True, blank=True, verbose_name="STNK Berlaku Sampai",
        help_text="Tanggal jatuh tempo STNK — dasar untuk pengingat perpanjangan di masa depan.",
    )

    # Denormalized on purpose — kept in sync by ServiceRecord.save()
    # below, so "when was this vehicle last serviced" is always a
    # direct read, not a query across every historical record.
    last_service_date        = models.DateField(null=True, blank=True, verbose_name="Tanggal Service Terakhir")
    last_service_odometer_km = models.PositiveIntegerField(null=True, blank=True, verbose_name="KM Saat Service Terakhir")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Vehicle"
        verbose_name_plural  = "Vehicles"
        ordering             = ["plate_number"]
        unique_together      = [("organization", "plate_number")]

    def __str__(self):
        return f"{self.plate_number} — {self.model}"

    def _resolve_organization(self):
        return self.customer.organization

    @property
    def is_due_for_service(self):
        """
        The computed flag from the handwritten spec — deliberately
        just a flag, not automated delivery. See ServiceRecord's own
        docstring and the roadmap doc for why: automated SMS/WhatsApp
        sending is a real, separate subsystem, not assumed here.
        """
        if self.last_service_odometer_km is None:
            return False
        return (self.current_odometer_km - self.last_service_odometer_km) >= SERVICE_DUE_INTERVAL_KM

    @property
    def is_registration_expiring_soon(self):
        """
        Same "flag, not delivery" philosophy as is_due_for_service
        above — a 30-day window, computed on read, no notification
        subsystem assumed. Kept as a property rather than a stored
        field so it's always accurate against today's date without
        needing a scheduled job to keep it in sync.
        """
        if self.registration_expiry is None:
            return False
        from datetime import date, timedelta
        return date.today() <= self.registration_expiry <= (date.today() + timedelta(days=30))


class ServiceRecord(TenantScopedModel):
    """
    One work order / service visit — the "histori pekerjaan" from the
    handwritten spec. Append-only, same audit-trail instinct as every
    other model in this codebase's lineage: a service record never
    gets edited after the fact, only created.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        # Same PROTECT reasoning as Vehicle.customer above — a vehicle
        # with zero service records can still be deleted (fixing a
        # mistake), but once even one real ServiceRecord exists,
        # deletion is blocked. This is the actual enforcement
        # mechanism for Principle 2, not just a stated intention.
        Vehicle, on_delete=models.PROTECT, related_name="service_records",
        verbose_name="Kendaraan",
    )
    service_date       = models.DateField(verbose_name="Tanggal Service")
    odometer_km         = models.PositiveIntegerField(verbose_name="KM Saat Service")
    issue_description   = models.TextField(verbose_name="Kerusakan")
    parts_replaced      = models.TextField(blank=True, verbose_name="Part yang Diganti")
    notes                = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Service Record"
        verbose_name_plural  = "Service Records"
        ordering             = ["-service_date", "-created_at"]

    def __str__(self):
        return f"{self.vehicle.plate_number} — {self.service_date}"

    def _resolve_organization(self):
        return self.vehicle.organization

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep Vehicle's denormalized "last service" fields in sync
        # the moment a real ServiceRecord is created — same
        # "creation triggers an update elsewhere" shape as every
        # small hook already proven across DevelopIndo's own sprints.
        self.vehicle.last_service_date        = self.service_date
        self.vehicle.last_service_odometer_km = self.odometer_km
        self.vehicle.current_odometer_km      = max(self.vehicle.current_odometer_km, self.odometer_km)
        self.vehicle.save(update_fields=[
            "last_service_date", "last_service_odometer_km", "current_odometer_km", "updated_at",
        ])


# =============================================================================
# === Sprint 1: Inventory ===
# =============================================================================

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
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Nama Part")
    sku  = models.CharField(
        max_length=50, blank=True, verbose_name="Kode/SKU",
        help_text="Opsional — kode internal bengkel untuk part ini, jika ada.",
    )
    # Decimal, not integer — oli (oil) is sold/consumed by the liter,
    # a genuinely fractional unit. Matching that against Made's own
    # invoice (Image 1: "Oli Mesin, 8" — whole units there, but a
    # smaller job could reasonably use 1.5L) means integer would be
    # a real future limitation, not a hypothetical one.
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Part"
        verbose_name_plural  = "Parts"
        ordering             = ["name"]

    def __str__(self):
        return f"{self.name} ({self.current_stock} {self.unit})"


class PartUsage(TenantScopedModel):
    """
    One line of "this Part was used on this ServiceRecord." Creating
    one atomically decrements Part.current_stock — the actual
    mechanism behind Made's own "G inventory 20−4=16" note.

    `unit_price_at_time` is a deliberate snapshot, not a live
    reference to Part.unit_price. Without it, a price change next
    month would silently rewrite the effective cost of every past
    service record that used this part — a real historical-accuracy
    bug, not a stylistic choice. Same instinct as ServiceRecord being
    append-only: history should not move once written.
    """
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_record = models.ForeignKey(
        ServiceRecord, on_delete=models.CASCADE, related_name="part_usages",
        verbose_name="Catatan Servis",
        # CASCADE (not PROTECT) is safe here specifically because
        # ServiceRecord has no delete endpoint at all (see urls.py) —
        # there is currently no code path that could ever cascade-
        # delete a PartUsage as a side effect. If a delete endpoint
        # is ever added to ServiceRecord, this decision needs
        # revisiting alongside it.
    )
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="usages",
        verbose_name="Part",
        # PROTECT — same Principle 2 reasoning as everywhere else. A
        # Part that's never been used can be deleted freely (fixing a
        # catalog mistake); one with real usage history cannot.
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
            # (see PartUsageSerializer.validate below for why) rather
            # than hard-blocking here at the model layer.
            Part.objects.filter(pk=self.part_id).update(
                current_stock=models.F("current_stock") - self.quantity
            )


class StockAdjustment(TenantScopedModel):
    """
    Every non-usage change to a Part's stock — restocking after a
    purchase, correcting a miscount, writing off damaged/lost stock.
    Without this, current_stock could only ever go down after a
    Part's initial creation value, which isn't a real inventory
    system — someone has to be able to record "20 more arrived."

    Positive quantity_change = stock increase, negative = decrease.
    Both directions go through this one model rather than a separate
    "restock" vs "write-off" model, since the underlying mechanism
    (adjust current_stock, keep an audit trail of why) is identical
    either way.
    """
    REASON_CHOICES = [
        ("restock",    "Restock / Pembelian"),
        ("correction", "Koreksi Stok"),
        ("damage",     "Rusak / Hilang"),
    ]

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="adjustments",
        verbose_name="Part",
    )
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Perubahan Jumlah")
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="restock", verbose_name="Alasan")
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
