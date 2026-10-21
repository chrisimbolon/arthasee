# =============================================================================
# === backend/apps/service/models.py ===
# =============================================================================
"""
Arthasee — Service

Part, PartUsage, and StockAdjustment moved out to apps.inventory —
see that app's models.py docstring and its migrations/0001_initial.py
for why and how (existing production data preserved via a migration-
state move + table rename, not a drop-and-recreate). ServiceRecord
still gets a `part_usages` related accessor from PartUsage's
cross-app FK — nothing about that changes from this app's side.
"""
import uuid
from decimal import Decimal, InvalidOperation

from apps.core.models import TenantScopedModel
from django.db import models, transaction

# Same 5,000 km interval named on the handwritten page — a real,
# standard Indonesian service-reminder interval, not an arbitrary
# number.
SERVICE_DUE_INTERVAL_KM = 5000
SERVICE_REMINDER_THRESHOLD_MONTHS = 3

def _add_months(d, months):
    """
    Real calendar-month arithmetic, no dateutil dependency — same
    "pure Python month arithmetic" discipline already established in
    apps.analytics.growth._last_n_month_starts(). Clamps an invalid
    result (e.g. Jan 31 + 3 months landing on a non-existent "April
    31") down to the real last day of that month, rather than
    raising. A naive "just compare month numbers" version was tried
    first and found genuinely wrong by hand — it counted a date only
    2 months and 29 days later as a full 3 months elapsed, since it
    ignored day-of-month entirely. Verified against that exact case,
    a year boundary, and the invalid-date clamp before being written
    here.
    """
    import calendar
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    from datetime import date
    return date(year, month, day)

class Customer(TenantScopedModel):
    """
    A bengkel's customer — the person who brings the vehicle in,
    which may or may not be the same as the registered owner on the
    STNK. That distinction was explicit on the handwritten spec, not
    an assumption made here.

    customer_type added once apps.contracts made the gap real and
    visible: institutional/tender clients (government bodies, police,
    large companies — see apps.contracts' own docstring) are stored
    as regular Customer rows, same as any walk-in customer, per the
    deliberate decision not to build a separate model for them. But
    with zero way to tell them apart, a UI picker meant to surface
    only institutional clients (Contract creation) would have no
    honest way to filter — every customer would show up in that list
    forever, regardless of how large the regular-customer list grows.
    Defaults to INDIVIDUAL so every existing Customer row, created
    before this field existed, stays correctly classified without
    requiring a backfill or a guess.
    """
    CUSTOMER_TYPE_CHOICES = [
        ("INDIVIDUAL",    "Perorangan"),
        ("INSTITUTIONAL", "Institusi/Tender"),
    ]

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name      = models.CharField(max_length=200, verbose_name="Nama Pelanggan")
    phone     = models.CharField(max_length=20, blank=True, verbose_name="Nomor Telepon")
    # Chris's own explicit call, 2 Aug — Fase 2 (customer tracking
    # links): not used by the token-link flow itself (a TrackingLink
    # is tied to a WorkOrder, not a Customer), but Made needs
    # somewhere real to record a client's email during intake for
    # Fase 2.5 (real accounts, magic-link verification — deliberately
    # parked, not built now). blank=True, same as phone above — never
    # required at intake, a real walk-in customer may not have one.
    email     = models.EmailField(blank=True, verbose_name="Email")
    stnk_name = models.CharField(
        max_length=200, blank=True, verbose_name="Nama di STNK",
        help_text="Nama pemilik terdaftar di STNK, jika berbeda dari nama pelanggan.",
    )
    customer_type = models.CharField(
        max_length=20, choices=CUSTOMER_TYPE_CHOICES, default="INDIVIDUAL",
        verbose_name="Jenis Pelanggan",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Customer"
        verbose_name_plural  = "Customers"
        ordering             = ["name"]

    def __str__(self):
        return self.name

    # 13 Sep 2026 — real, dedicated field-change history. Deliberately
    # scoped to Customer only for v1, not a generic contenttypes
    # mechanism spanning every model — the same "build concretely for
    # the one real consumer, generalize only once a second one
    # genuinely needs it" call already made for bulk import (Phase 18,
    # Open Decision #30). Only real, writable fields are eligible —
    # id/created_at/updated_at/customer_type's own derived count etc.
    # are never tracked, same as they're never accepted as direct
    # edit input via CustomerSerializer today.
    FIELD_LABELS = {
        "name":          "Nama Pelanggan",
        "phone":         "Nomor Telepon",
        "email":         "Email",
        "stnk_name":     "Nama di STNK",
        "customer_type": "Jenis Pelanggan",
    }

    def _display_value(self, field_name, value):
        """
        Real, deliberate choice: for customer_type specifically, the
        history log stores the human-readable label ("Perorangan"),
        not the raw stored code ("INDIVIDUAL") — a history entry is a
        read-only record meant for a person to actually read later,
        never queried by raw code the way the live Customer row
        itself might be. Every other tracked field is already plain
        text, so this is the only field that needs translating.
        """
        if field_name == "customer_type":
            return dict(self.CUSTOMER_TYPE_CHOICES).get(value, value)
        return value

    def apply_edit(self, *, changed_by=None, **fields):
        """
        The one real edit path for Customer — CustomerDetailView.put()
        is the only real caller. Every field passed in `fields` is
        compared against the CURRENT real value BEFORE anything is
        written; only a genuine difference produces a
        CustomerFieldChange row, with its own human-readable label
        frozen at write time (so a future relabeling of this field
        never silently rewrites what an old history entry says it
        was). Fields never mentioned in `fields` at all are left
        completely untouched — a plain PATCH-style partial update,
        no _UNSET-sentinel complexity needed here the way Account.
        parent required, since Customer has no field where None/blank
        is itself a meaningful "clear this" state distinct from
        "don't touch this."

        Raises ValueError for any field name outside FIELD_LABELS —
        same "fail loud on an unknown key" discipline as every other
        real write path in this codebase, never a silent no-op for a
        typo'd field name.
        """
        changes = []
        for field_name, new_value in fields.items():
            if field_name not in self.FIELD_LABELS:
                raise ValueError(f"Field tidak dikenal: {field_name!r}.")
            old_value = getattr(self, field_name)
            if old_value != new_value:
                changes.append(CustomerFieldChange(
                    organization=self.organization, customer=self,
                    field_name=field_name, field_label=self.FIELD_LABELS[field_name],
                    old_value=self._display_value(field_name, old_value) or "",
                    new_value=self._display_value(field_name, new_value) or "",
                    changed_by=changed_by,
                ))
                setattr(self, field_name, new_value)

        if changes:
            self.save()
            # bulk_create, not one .save() per change — same real
            # precedent JournalLine.objects.bulk_create() already
            # establishes for a TenantScopedModel written in a real
            # batch (JournalEntry.post()) rather than one row at a
            # time.
            CustomerFieldChange.objects.bulk_create(changes)
        return self


class CustomerFieldChange(TenantScopedModel):
    """
    13 Sep 2026 — real, per-field audit trail for Customer edits.
    Deliberately dedicated to Customer, not a generic contenttypes-
    based mechanism — see Customer.apply_edit()'s own docstring for
    the real reasoning. Never itself editable after creation — see
    the Admin lockdown (admin.py) for the same "an editable audit
    trail is not a trustworthy audit trail" discipline every other
    real audit-adjacent model in this codebase already gets
    (JournalEntry, AccountingPeriod).

    Honest, real limitation: this only ever tracks changes made
    THROUGH apply_edit() from the moment this ships — there is no
    retroactive backfill, since no record of what a Customer row
    looked like before this existed anywhere to reconstruct from.
    """
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="field_changes",
        verbose_name="Pelanggan",
    )
    field_name  = models.CharField(max_length=50, verbose_name="Nama Field")
    field_label = models.CharField(max_length=100, verbose_name="Label Field")
    old_value   = models.TextField(blank=True, verbose_name="Nilai Lama")
    new_value   = models.TextField(blank=True, verbose_name="Nilai Baru")
    changed_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Diubah Oleh",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Customer Field Change"
        verbose_name_plural  = "Customer Field Changes"
        ordering             = ["-changed_at"]

    def __str__(self):
        return f"{self.customer.name} — {self.field_label}: {self.old_value!r} -> {self.new_value!r}"

    def _resolve_organization(self):
        return self.customer.organization


class Vehicle(TenantScopedModel):
    """
    One vehicle, belonging to one Customer — a customer can have
    multiple vehicles (family car, work vehicle, etc). Plate number
    is unique per shop, not globally unique — two unrelated bengkels
    can each have a record for the same real-world plate.
    """
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="vehicles",
        verbose_name="Pelanggan",
    )
    plate_number      = models.CharField(max_length=20, verbose_name="Nomor Plat")
    manufacture_year  = models.PositiveIntegerField(verbose_name="Tahun Pembuatan")
    vehicle_type      = models.CharField(max_length=100, verbose_name="Jenis Kendaraan")
    model              = models.CharField(max_length=100, verbose_name="Type/Model")
    current_odometer_km = models.PositiveIntegerField(default=0, verbose_name="KM Saat Ini")

    # ── STNK-sourced fields ────────────────────────────────────────
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
        if self.last_service_odometer_km is None:
            return False
        return (self.current_odometer_km - self.last_service_odometer_km) >= SERVICE_DUE_INTERVAL_KM

    @property
    def is_registration_expiring_soon(self):
        """
        Deliberately has no lower bound — an ALREADY-expired
        registration must still evaluate True here. Caught via
        test_expiring_soon_true_when_already_expired in tests.py.
        """
        if self.registration_expiry is None:
            return False
        from datetime import date, timedelta
        return self.registration_expiry <= (date.today() + timedelta(days=30))

    @property
    def is_due_for_service_reminder(self):
        """
        Made's own calendar-based nudge — deliberately kept SEPARATE
        from is_due_for_service above, which is purely mileage-based
        and drives the already-live "Harus Servis" dashboard badge.
        A customer who drives less than average could sit under
        5,000 km for well past 4 months and never trip that one —
        this is exactly the signal meant to catch them anyway.

        No upper bound, same pattern as is_registration_expiring_soon
        — once due, it stays due until a real new ServiceRecord
        resets last_service_date, nothing to reset by hand. The
        actual send-once guard lives in ServiceReminderLog, not
        here — this property only answers "is this vehicle
        currently in the reminder window," not "have we already
        reminded them about it."
        """
        if self.last_service_date is None:
            return False
        from datetime import date
        return date.today() >= _add_months(self.last_service_date, SERVICE_REMINDER_THRESHOLD_MONTHS)

    # 14 Sep 2026 — real, dedicated field-change history, same shape
    # as Customer.apply_edit()/CustomerFieldChange already established.
    #
    # Real, deliberate scope, confirmed directly before writing this:
    #   - `customer` is EXCLUDED — reassigning a vehicle's owner is a
    #     structural transfer, not a simple field correction; that
    #     gets its own dedicated flow in a future phase, not folded
    #     into a plain text-diff log. VehicleDetailView.put() (views.py)
    #     enforces this at the API layer too — a payload containing
    #     `customer` is rejected outright with a real, explicit
    #     message, not a confusing generic "unknown field" error from
    #     this method's own guard below.
    #   - `last_service_date`/`last_service_odometer_km` are EXCLUDED
    #     — both are strictly system-derived from a real, completed
    #     ServiceRecord (see ServiceRecord.save() below, which writes
    #     them directly, never through this method) and must never be
    #     hand-editable at all.
    #   - `current_odometer_km` IS included — a real, legitimate
    #     "staff mis-typed the KM" correction case, distinct from the
    #     two fields above which are meant to be purely automatic.
    FIELD_LABELS = {
        "plate_number":         "Nomor Plat",
        "vehicle_type":         "Jenis Kendaraan",
        "model":                "Type/Model",
        "manufacture_year":     "Tahun Pembuatan",
        "body_style":           "Jenis Bodi",
        "color":                "Warna",
        "chassis_number":       "No. Rangka",
        "engine_number":        "No. Mesin",
        "bpkb_number":          "No. BPKB",
        "registration_expiry":  "STNK Berlaku Sampai",
        "current_odometer_km":  "KM Saat Ini",
    }

    def apply_edit(self, *, changed_by=None, **fields):
        """
        The one real edit path for Vehicle — VehicleDetailView.put()
        is the only real caller. Same real diff logic as Customer.
        apply_edit(): every field in `fields` is compared against the
        CURRENT real value before anything is written, only a genuine
        difference produces a VehicleFieldChange row, and a field
        never mentioned at all is left completely untouched.

        Unlike Customer, several tracked fields here are non-string
        (manufacture_year/current_odometer_km are int,
        registration_expiry is a real date or None) — old_value/
        new_value are stored as plain text either way, via a uniform
        str()-or-empty conversion, not a per-field type branch.

        Raises ValueError for any field name outside FIELD_LABELS —
        same fail-loud discipline as Customer.apply_edit(). `customer`
        specifically is blocked one layer up, in VehicleDetailView.
        put() itself, with a real, explicit message — this method
        would otherwise only ever produce a generic "Field tidak
        dikenal" for it, which is correct but not the clearest thing
        to show a real caller.
        """
        changes = []
        for field_name, new_value in fields.items():
            if field_name not in self.FIELD_LABELS:
                raise ValueError(f"Field tidak dikenal: {field_name!r}.")
            old_value = getattr(self, field_name)
            if old_value != new_value:
                changes.append(VehicleFieldChange(
                    organization=self.organization, vehicle=self,
                    field_name=field_name, field_label=self.FIELD_LABELS[field_name],
                    old_value=str(old_value) if old_value not in (None, "") else "",
                    new_value=str(new_value) if new_value not in (None, "") else "",
                    changed_by=changed_by,
                ))
                setattr(self, field_name, new_value)

        if changes:
            self.save()
            VehicleFieldChange.objects.bulk_create(changes)
        return self


class VehicleFieldChange(TenantScopedModel):
    """
    14 Sep 2026 — real, per-field audit trail for Vehicle edits, same
    shape and same real reasoning as CustomerFieldChange. Never
    itself editable after creation — see the Admin lockdown
    (admin.py), same "an editable audit trail is not a trustworthy
    audit trail" discipline as every other real audit-adjacent model
    in this codebase.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="field_changes",
        verbose_name="Kendaraan",
    )
    field_name  = models.CharField(max_length=50, verbose_name="Nama Field")
    field_label = models.CharField(max_length=100, verbose_name="Label Field")
    old_value   = models.TextField(blank=True, verbose_name="Nilai Lama")
    new_value   = models.TextField(blank=True, verbose_name="Nilai Baru")
    changed_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Diubah Oleh",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Vehicle Field Change"
        verbose_name_plural  = "Vehicle Field Changes"
        ordering             = ["-changed_at"]

    def __str__(self):
        return f"{self.vehicle.plate_number} — {self.field_label}: {self.old_value!r} -> {self.new_value!r}"

    def _resolve_organization(self):
        return self.vehicle.organization


class ServiceRecord(TenantScopedModel):
    """
    One work order / service visit — the "histori pekerjaan" from the
    handwritten spec. Append-only: a service record never gets
    edited after the fact, only created.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
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
        self.vehicle.last_service_date        = self.service_date
        self.vehicle.last_service_odometer_km = self.odometer_km
        self.vehicle.current_odometer_km      = max(self.vehicle.current_odometer_km, self.odometer_km)
        self.vehicle.save(update_fields=[
            "last_service_date", "last_service_odometer_km", "current_odometer_km", "updated_at",
        ])

class ServiceReminderLog(TenantScopedModel):
    """
    One row per reminder actually ATTEMPTED for a vehicle (sent or
    failed), tied to the specific last_service_date it was sent
    about — the real mechanism stopping this from becoming a daily
    email every single day forever. A failed attempt still creates a
    row here, same "fails soft, don't retry-storm" philosophy as
    apps.customers.email.send_magic_link_email — a transient Resend
    outage is treated the same as a permanent bad address; both wait
    for the vehicle's own next real service visit before trying
    again, rather than hammering an unreliable address daily.

    Tied to for_last_service_date, not just the vehicle — a genuine
    new ServiceRecord updates last_service_date (see
    ServiceRecord.save() above), which naturally makes the vehicle
    eligible for a fresh reminder next time 3 months pass. Nothing
    to reset by hand.
    """
    STATUS_CHOICES = [
        ("SENT",   "Terkirim"),
        ("FAILED", "Gagal"),
    ]

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="reminder_logs",
        verbose_name="Kendaraan",
    )
    for_last_service_date = models.DateField(verbose_name="Untuk Service Terakhir Tanggal")
    status  = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="Status")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Service Reminder Log"
        verbose_name_plural  = "Service Reminder Logs"
        unique_together      = [("vehicle", "for_last_service_date")]
        ordering             = ["-sent_at"]

    def __str__(self):
        return f"{self.vehicle.plate_number} — {self.for_last_service_date} — {self.status}"

    def _resolve_organization(self):
        return self.vehicle.organization


# =============================================================================
# Daftar Jasa — Phase 21, Task 21.3 (20 Oct 2026)
# =============================================================================
# Made's handwritten note, 12 Sep 2026 (signed by Chris and I Made Sudarta):
# "Jasa: misalnya tune-up: muncul klasifikasi harga tune-up — Sedan / SUV /
# Ertiga ... ini harus bisa di-update!" Each jasa has one price per vehicle
# class, plus a default price used when the vehicle has no class or the jasa
# has no price for that class. Agreed 16-20 Oct 2026:
#   - the class is the vehicle's existing body_style field (no new field);
#   - the class list is Sedan / Hatchback / MPV / SUV / Pick-up / Truck
#     ("Ertiga" in Made's note = MPV);
#   - only the shop OWNER may change the list or its prices;
#   - a price is always COPIED onto an estimate/invoice line, never read live,
#     so changing this list never changes a past document (Principle #15).
# Every change is logged in ServiceItemChange (who, when, old -> new).

# Must match VEHICLE_CLASSES in frontend/lib/api/service.ts —
# ServiceItemVehicleClassSyncTests checks the two stay identical.
VEHICLE_CLASSES = ["Sedan", "Hatchback", "MPV", "SUV", "Pick-up", "Truck"]


def _class_key(value):
    return "".join(str(value).lower().split()).replace("-", "")


_CLASS_BY_KEY = {_class_key(c): c for c in VEHICLE_CLASSES}


def normalise_vehicle_class(value):
    """
    "suv", " SUV ", "Pick up", "pickup" -> the canonical class name.
    Blank or anything not in VEHICLE_CLASSES -> "" (no class). Used for
    every price lookup and every vehicle write, so spelling never
    decides which price a customer pays.
    """
    if not value:
        return ""
    return _CLASS_BY_KEY.get(_class_key(value), "")


_UNSET = object()  # Cheat Sheet section 10 — "not sent" vs "sent as null"


def _rp(value):
    if value is None:
        return ""
    return "Rp " + f"{Decimal(value):,.0f}".replace(",", ".")


def _clean_price(value, label):
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} harus berupa angka.")
    if not price.is_finite():
        raise ValueError(f"{label} harus berupa angka.")
    if price < 0:
        raise ValueError(f"{label} tidak boleh negatif.")
    return price.quantize(Decimal("0.01"))


def _clean_class_prices(class_prices):
    """{"SUV": "400000", "MPV": None} -> {"SUV": Decimal, "MPV": None}.
    None (or "") means "no own price for this class — use the default"."""
    if not isinstance(class_prices, dict):
        raise ValueError("Format harga per kelas tidak valid.")
    cleaned = {}
    for raw_class, raw_price in class_prices.items():
        vehicle_class = normalise_vehicle_class(raw_class)
        if not vehicle_class:
            raise ValueError(f"Kelas kendaraan tidak dikenal: {raw_class!r}.")
        if raw_price is None or raw_price == "":
            cleaned[vehicle_class] = None
        else:
            cleaned[vehicle_class] = _clean_price(raw_price, f"Harga {vehicle_class}")
    return cleaned


class ServiceItem(TenantScopedModel):
    """
    One jasa in the shop's price list ("Daftar Jasa"), e.g. "Tune-up".
    Never hard-deleted (estimate/invoice lines will point at it from Task
    21.4) — retired with is_active=False instead.

    Never constructed or edited directly: record() creates, apply_edit()
    changes, and both write the ServiceItemChange history. Django Admin is
    read-only for the same reason (Cheat Sheet section 11).
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name          = models.CharField(max_length=200, verbose_name="Nama Jasa")
    default_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Default")
    is_active     = models.BooleanField(default=True, verbose_name="Aktif")
    created_by    = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Dibuat Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Service Item"
        verbose_name_plural  = "Service Items"
        ordering             = ["name"]
        unique_together      = [("organization", "name")]

    def __str__(self):
        return self.name

    def _resolve_organization(self):
        return self.organization

    @classmethod
    def record(cls, *, organization, name, default_price, class_prices=None, created_by=None):
        """The one real create path. Validates everything first; writes
        nothing unless it all passes."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Nama jasa wajib diisi.")
        price = _clean_price(default_price, "Harga default")
        prices = _clean_class_prices(class_prices or {})
        if cls.objects.filter(organization=organization, name__iexact=name).exists():
            raise ValueError(f"Jasa \"{name}\" sudah ada di Daftar Jasa.")

        with transaction.atomic():
            item = cls.objects.create(
                organization=organization, name=name, default_price=price, created_by=created_by,
            )
            for vehicle_class, class_price in prices.items():
                if class_price is not None:
                    ServiceItemPrice.objects.create(
                        organization=organization, service_item=item,
                        body_style=vehicle_class, price=class_price,
                    )
            ServiceItemChange.objects.create(
                organization=organization, service_item=item, field_label="Dibuat",
                old_value="", new_value=f"Harga default {_rp(price)}", changed_by=created_by,
            )
        return item

    def apply_edit(self, *, changed_by=None, name=_UNSET, default_price=_UNSET,
                   is_active=_UNSET, class_prices=_UNSET):
        """
        The one real edit path. Only what was actually sent is touched
        (_UNSET = not sent). In class_prices, a class set to None removes
        that class's own price (it falls back to the default). Every real
        difference becomes one ServiceItemChange row; no difference, no row.
        """
        changes = []
        updates = {}

        if name is not _UNSET:
            name = (name or "").strip()
            if not name:
                raise ValueError("Nama jasa wajib diisi.")
            if name != self.name:
                clash = (ServiceItem.objects.filter(organization=self.organization, name__iexact=name)
                         .exclude(pk=self.pk).exists())
                if clash:
                    raise ValueError(f"Jasa \"{name}\" sudah ada di Daftar Jasa.")
                changes.append(("Nama Jasa", self.name, name))
                updates["name"] = name

        if default_price is not _UNSET:
            price = _clean_price(default_price, "Harga default")
            if price != self.default_price:
                changes.append(("Harga Default", _rp(self.default_price), _rp(price)))
                updates["default_price"] = price

        if is_active is not _UNSET:
            is_active = bool(is_active)
            if is_active != self.is_active:
                changes.append(("Status", "Aktif" if self.is_active else "Nonaktif",
                                "Aktif" if is_active else "Nonaktif"))
                updates["is_active"] = is_active

        price_writes = []
        if class_prices is not _UNSET:
            current = {p.body_style: p for p in self.class_prices.all()}
            for vehicle_class, new_price in _clean_class_prices(class_prices).items():
                row = current.get(vehicle_class)
                old_price = row.price if row else None
                if old_price == new_price:
                    continue
                label = f"Harga {vehicle_class}"
                old_text = _rp(old_price) if old_price is not None else "(pakai default)"
                new_text = _rp(new_price) if new_price is not None else "(pakai default)"
                changes.append((label, old_text, new_text))
                price_writes.append((vehicle_class, row, new_price))

        if not changes:
            return self

        with transaction.atomic():
            for field, value in updates.items():
                setattr(self, field, value)
            if updates:
                self.save()
            for vehicle_class, row, new_price in price_writes:
                if new_price is None:
                    row.delete()
                elif row is None:
                    ServiceItemPrice.objects.create(
                        organization=self.organization, service_item=self,
                        body_style=vehicle_class, price=new_price,
                    )
                else:
                    row.price = new_price
                    row.save(update_fields=["price"])
            ServiceItemChange.objects.bulk_create([
                ServiceItemChange(
                    organization=self.organization, service_item=self, field_label=label,
                    old_value=old, new_value=new, changed_by=changed_by,
                )
                for label, old, new in changes
            ])
        return self

    def price_for(self, vehicle_class):
        """
        (price, source) for a vehicle class — or a Vehicle, whose
        body_style is used. source is "class" when this jasa has its own
        price for that class, otherwise "default" (no class on the
        vehicle, an old free-text value, or no price set for that class).
        """
        raw = getattr(vehicle_class, "body_style", vehicle_class)
        key = normalise_vehicle_class(raw)
        if key:
            for row in self.class_prices.all():
                if row.body_style == key:
                    return row.price, "class"
        return self.default_price, "default"


class ServiceItemPrice(TenantScopedModel):
    """One class price for one jasa — e.g. Tune-up / SUV / Rp 400.000.
    Written only by ServiceItem.record()/apply_edit()."""
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_item = models.ForeignKey(
        ServiceItem, on_delete=models.CASCADE, related_name="class_prices", verbose_name="Jasa",
    )
    body_style = models.CharField(
        max_length=20, choices=[(c, c) for c in VEHICLE_CLASSES], verbose_name="Kelas Kendaraan",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga")

    class Meta:
        verbose_name        = "Service Item Price"
        verbose_name_plural  = "Service Item Prices"
        unique_together      = [("service_item", "body_style")]

    def __str__(self):
        return f"{self.service_item.name} — {self.body_style}: {self.price}"

    def _resolve_organization(self):
        return self.service_item.organization


class ServiceItemChange(TenantScopedModel):
    """
    Audit trail for Daftar Jasa — same shape and same reasoning as
    VehicleFieldChange: an editable audit trail is not a trustworthy one,
    so Django Admin is read-only and the only writer is ServiceItem itself.
    """
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_item = models.ForeignKey(
        ServiceItem, on_delete=models.CASCADE, related_name="changes", verbose_name="Jasa",
    )
    field_label = models.CharField(max_length=100, verbose_name="Yang Diubah")
    old_value   = models.TextField(blank=True, verbose_name="Nilai Lama")
    new_value   = models.TextField(blank=True, verbose_name="Nilai Baru")
    changed_by  = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Diubah Oleh",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Service Item Change"
        verbose_name_plural  = "Service Item Changes"
        ordering             = ["-changed_at"]

    def __str__(self):
        return f"{self.service_item.name} — {self.field_label}: {self.old_value!r} -> {self.new_value!r}"

    def _resolve_organization(self):
        return self.service_item.organization
