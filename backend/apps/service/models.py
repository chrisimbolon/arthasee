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

from apps.core.models import TenantScopedModel
from django.db import models

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