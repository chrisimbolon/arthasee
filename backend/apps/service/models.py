# =============================================================================
# === backend/apps/service/models.py ===
# =============================================================================
"""
Arthasee — Service (Phase 1)

Three models, directly off the handwritten spec Chris and Made
signed. Nothing added beyond it — see BENGKEL_CRM_PHASE_1_ROADMAP.md
for what's deliberately parked (inventory, invoicing, multi-branch,
appointment scheduling, automated notification delivery).
"""
import uuid

from django.db import models

from apps.core.models import TenantScopedModel

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
