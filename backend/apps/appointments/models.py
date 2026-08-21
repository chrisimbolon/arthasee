# =============================================================================
# === backend/apps/appointments/models.py ===
# =============================================================================
"""
Arthasee — Appointments

A brand-new domain, its own isolated app — a booking is a real
promise about the future, genuinely distinct from both a WorkOrder
(work actually happening, a car physically present) and a Customer
login concern. Same reasoning that moved Supplier Reliability into
its own correctly-owned app rather than living somewhere convenient.

v1 state machine, confirmed directly: CONFIRMED -> CONVERTED or
CANCELLED. REQUESTED was deliberately dropped — Made wants
automation, not another approval step (he's already rejected every
kind of approval workflow elsewhere in this project); a booking
either clears the capacity check and becomes real immediately, or
it's rejected outright. NO_SHOW is deferred to v2.
"""
import uuid

from apps.core.models import TenantScopedModel
from apps.workorders.models import WorkOrder
from django.db import models, transaction


class AppointmentDayLock(TenantScopedModel):
    """
    Exists purely to give Appointment.create_if_available() something
    guaranteed to lock via select_for_update(), even on the very
    first booking ever made for a given day. A real, known limitation
    of row-level locking: SELECT ... FOR UPDATE against a query that
    returns ZERO rows locks nothing at all — on an empty day, two
    simultaneous "book the first slot" requests would have nothing
    to serialize against, reopening exactly the boundary race this
    whole mechanism exists to close. One row per (organization,
    date), get_or_create'd on first use — mirrors the exact same
    proven-correct pattern already in this codebase,
    WorkOrderSequence.next_number()'s own
    select_for_update().get_or_create().

    Never queried or read for its own sake — its entire purpose is
    to exist and be lockable, nothing else.
    """
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField()

    class Meta:
        verbose_name        = "Appointment Day Lock"
        verbose_name_plural  = "Appointment Day Locks"
        unique_together      = [("organization", "date")]

    def __str__(self):
        return f"{self.organization} — {self.date}"

    def _resolve_organization(self):
        # No related object to derive this from — organization is
        # set explicitly at creation (see create_if_available()
        # below). Returning the already-set field here is always
        # correct, whether or not this is ever invoked as a
        # fallback.
        return self.organization


class Appointment(TenantScopedModel):
    """
    One customer-initiated booking request. Light by design, per
    Chris's own confirmed scope: date + vehicle + free-text notes —
    no service-item selection, no approval step.
    """
    STATUS_CHOICES = [
        ("CONFIRMED", "Terkonfirmasi"),
        ("CONVERTED", "Sudah Datang"),
        ("CANCELLED", "Dibatalkan"),
    ]

    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "service.Customer", on_delete=models.PROTECT, related_name="appointments",
        verbose_name="Pelanggan",
    )
    vehicle = models.ForeignKey(
        "service.Vehicle", on_delete=models.PROTECT, related_name="appointments",
        verbose_name="Kendaraan",
    )
    requested_date = models.DateField(verbose_name="Tanggal Diminta")
    notes = models.TextField(
        blank=True, verbose_name="Keluhan / Jenis Servis",
        help_text="Bebas, misal 'Ganti oli & cek rem' — bukan pilihan paket layanan (belum ada di v1).",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="CONFIRMED", verbose_name="Status")

    # Set only once, at conversion time — a direct, queryable answer
    # to "which real visit did this booking become," matching the
    # same real pattern already established by
    # WorkOrder.service_record.
    work_order = models.OneToOneField(
        WorkOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="appointment", verbose_name="Work Order",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Appointment"
        verbose_name_plural  = "Appointments"
        ordering             = ["requested_date", "created_at"]

    def __str__(self):
        return f"{self.vehicle.plate_number} — {self.requested_date} ({self.status})"

    def _resolve_organization(self):
        return self.vehicle.organization

    @classmethod
    def create_if_available(cls, *, customer, vehicle, requested_date, notes=""):
        """
        The real capacity check and the creation happen inside ONE
        transaction, deliberately — a plain "count, then create"
        without real locking has a genuine race at the exact
        capacity boundary: two customers booking the same nearly-full
        day in the same instant could both read the same count, both
        pass the check, and both create, silently exceeding capacity.
        Verified by hand (the counting logic itself, not the DB-level
        locking guarantee, which reuses an already-proven mechanism)
        before this was written.

        Only CONFIRMED and CONVERTED appointments count against
        capacity — Chris's own confirmed rule: a CANCELLED booking
        frees its slot immediately, nothing further needs to happen
        beyond the status change itself (see cancel() below).

        Returns the new Appointment on success, or None if the day
        is genuinely full — the caller (the view) turns None into
        the real customer-facing "day is full" response.
        """
        organization = vehicle.organization
        with transaction.atomic():
            AppointmentDayLock.objects.select_for_update().get_or_create(
                organization=organization, date=requested_date,
            )
            existing_count = cls.objects.filter(
                organization=organization, requested_date=requested_date,
                status__in=["CONFIRMED", "CONVERTED"],
            ).count()
            if existing_count >= organization.daily_appointment_capacity:
                return None
            return cls.objects.create(
                organization=organization, customer=customer, vehicle=vehicle,
                requested_date=requested_date, notes=notes, status="CONFIRMED",
            )

    def cancel(self):
        """
        Immediately frees the slot for someone else — the capacity
        check above only ever counts CONFIRMED/CONVERTED, so nothing
        further needs to happen here beyond the status change.
        """
        if self.status != "CONFIRMED":
            raise ValueError("Hanya janji temu yang masih terkonfirmasi yang bisa dibatalkan.")
        self.status = "CANCELLED"
        self.save(update_fields=["status", "updated_at"])

    def convert_to_work_order(self, *, received_by=""):
        """
        The real moment a booking becomes a real, physical visit.
        Deliberately does NOT fill in the Vehicle's placeholder
        fields (manufacture_year, vehicle_type, model — see
        CustomerSelfRegistrationView's own docstring for why they
        exist) — that's a real, separate staff action at intake, not
        this method's job.

        Wrapped in transaction.atomic() — a real bug caught live:
        WorkOrder.save() calls WorkOrderSequence.next_number(),
        which needs select_for_update(), which Django refuses to run
        outside an active transaction. create_if_available() above
        already knew this and wrapped its own body; this method
        didn't, and crashed the first time it was actually invoked
        outside a test. The atomic block also closes a second, real
        risk beyond the crash: without it, a WorkOrder could be
        created successfully and then the Appointment's own save()
        could fail, leaving a real orphaned WorkOrder with no
        Appointment pointing to it as converted. Now either both
        succeed or neither does.
        """
        if self.status != "CONFIRMED":
            raise ValueError("Hanya janji temu yang masih terkonfirmasi yang bisa dikonversi.")
        with transaction.atomic():
            work_order = WorkOrder.objects.create(
                vehicle=self.vehicle, received_by=received_by, notes=self.notes,
            )
            self.status = "CONVERTED"
            self.work_order = work_order
            self.save(update_fields=["status", "work_order", "updated_at"])
        return work_order
