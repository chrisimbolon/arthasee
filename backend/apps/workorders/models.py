# =============================================================================
# === backend/apps/workorders/models.py ===
# =============================================================================
"""
Arthasee — Work Orders

The "live working state" that precedes ServiceRecord — directly
modeled on Made's real paper Work Order (WO NO: 1451): a numbered
job-description checklist filled in progressively, a separate
material/item table, captured at intake before pricing exists.

Design locked in with Chris/Made:
  - WorkOrder is genuinely mutable while open — job lines get ticked
    off, material lines get added — unlike ServiceRecord, which stays
    strictly append-only. This app owns the "in progress" reality;
    apps.service still owns the frozen historical record.
  - Closing a WorkOrder freezes it into a real ServiceRecord, the
    same "mutable working state -> frozen historical record" shape
    already proven by PartUsage -> Invoice. Nothing about
    ServiceRecord or Invoice changes to support this.
  - Stock deducts in REAL TIME the moment a WorkOrderMaterialLine is
    created — this app is the sole executor of that deduction.
    Closing a WorkOrder creates matching PartUsage rows via
    bulk_create() specifically because bulk_create() skips each
    instance's save() method, and therefore skips PartUsage's own
    stock-deducting side effect. The deduction already happened;
    closing only needs to leave a historical record behind, not
    deduct a second time. See WorkOrder.close() below.
  - Numbering is plain sequential (matching the paper's bare "1451",
    no prefix, no visible year) — WorkOrderSequence is one row per
    organization, not scoped by year the way InvoiceSequence is.
"""
import uuid
from datetime import date

from django.db import models, transaction

from apps.core.models import TenantScopedModel
from apps.inventory.models import Part, PartUsage, StockAdjustment


class WorkOrderSequence(TenantScopedModel):
    """
    One row per organization — no year scoping, unlike
    InvoiceSequence. Not exposed via any API; purely internal
    plumbing behind WorkOrder.save()'s number generation.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Work Order Sequence"
        verbose_name_plural  = "Work Order Sequences"
        unique_together      = [("organization",)]

    def __str__(self):
        return f"{self.organization}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization):
        """
        Atomically claims the next sequence number. select_for_update()
        locks this row for the rest of the caller's transaction — two
        work orders opened in the same instant can't both claim the
        same number. Must be called from inside an atomic block
        (WorkOrder.save() runs inside one — see below).
        """
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class WorkOrder(TenantScopedModel):
    """
    One vehicle's live, in-progress job — the digital form of the
    paper WO. Genuinely mutable while OPEN/IN_PROGRESS/QC; frozen
    into a ServiceRecord the moment it reaches DONE.
    """
    STATUS_CHOICES = [
        ("OPEN",        "Terbuka"),
        ("IN_PROGRESS", "Dikerjakan"),
        ("QC",          "Pemeriksaan Kualitas"),
        ("DONE",        "Selesai"),
        ("CANCELLED",   "Dibatalkan"),
    ]

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        "service.Vehicle", on_delete=models.PROTECT, related_name="work_orders",
        verbose_name="Kendaraan",
    )
    number          = models.CharField(max_length=20, editable=False, verbose_name="Nomor WO")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN", verbose_name="Status")

    odometer_km_intake = models.PositiveIntegerField(null=True, blank=True, verbose_name="KM Saat Masuk")
    received_by         = models.CharField(max_length=200, blank=True, verbose_name="Diterima Oleh")
    notes                = models.TextField(blank=True, verbose_name="Catatan")

    # Set only once, at close time — a direct, queryable answer to
    # "which WorkOrder became this ServiceRecord," rather than making
    # anyone infer it. Nullable because most of a WorkOrder's life it
    # has no ServiceRecord yet.
    service_record = models.OneToOneField(
        "service.ServiceRecord", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="work_order", verbose_name="Catatan Servis",
    )

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Work Order"
        verbose_name_plural  = "Work Orders"
        ordering             = ["-created_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return f"WO {self.number} — {self.vehicle.plate_number}"

    def _resolve_organization(self):
        return self.vehicle.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            org = self._resolve_organization()
            self.sequence_number = WorkOrderSequence.next_number(org)
            self.number = str(self.sequence_number)
        super().save(*args, **kwargs)

    def close(self, service_date=None, closed_by=None):
        """
        Freezes this WorkOrder into a real ServiceRecord. The entire
        operation runs in its own transaction (not relying on the
        caller to wrap one) — this is business logic complex enough
        (multiple creates, a status change) that it should guarantee
        its own atomicity regardless of what calls it: a view, an
        admin action, a management command, a test.
        """
        # Imported here, not at module level — apps.service already
        # imports nothing from apps.workorders, so there's no real
        # circular-import risk, but keeping this import local to the
        # one method that needs it makes the dependency direction
        # obvious without hunting through the whole file.
        from apps.service.models import ServiceRecord

        if self.status == "DONE":
            raise ValueError("Work order ini sudah selesai.")
        if self.status == "CANCELLED":
            raise ValueError("Work order yang sudah dibatalkan tidak bisa diselesaikan.")

        with transaction.atomic():
            job_lines = list(self.job_lines.all())
            material_lines = list(self.material_lines.select_related("part").all())

            issue_description = "\n".join(line.description for line in job_lines)
            parts_replaced = ", ".join(line.part.name for line in material_lines)

            record = ServiceRecord.objects.create(
                organization=self.organization,
                vehicle=self.vehicle,
                service_date=service_date or date.today(),
                odometer_km=self.odometer_km_intake or self.vehicle.current_odometer_km,
                issue_description=issue_description or "(tidak ada deskripsi pekerjaan)",
                parts_replaced=parts_replaced,
                created_by=closed_by,
            )

            # bulk_create(), not a loop of individual .save() calls —
            # this is the actual mechanism that avoids double-
            # deducting stock. bulk_create() skips each instance's
            # save() method entirely, so PartUsage.save()'s own
            # F("current_stock") - quantity update never runs here.
            # The deduction already happened, in real time, when each
            # WorkOrderMaterialLine was created (see that model's own
            # save() below) — this only needs to leave the historical
            # PartUsage record behind for Invoice to later snapshot
            # from, not move any stock a second time.
            PartUsage.objects.bulk_create([
                PartUsage(
                    organization=self.organization,
                    service_record=record,
                    part=line.part,
                    quantity=line.quantity,
                    unit_price_at_time=line.unit_price_at_time,
                )
                for line in material_lines
            ])

            self.status = "DONE"
            self.service_record = record
            self.save(update_fields=["status", "service_record", "updated_at"])

        return record

    def cancel(self):
        """
        Reverses every real-time deduction this WorkOrder caused, via
        genuine StockAdjustment rows — reusing the exact same
        reversal mechanism that already exists for restocking or
        correcting a miscount, not inventing a parallel one. Labeled
        with its own reason ("work_order_cancelled") so the audit
        trail honestly shows why stock moved back, rather than
        looking like an unexplained manual correction.
        """
        if self.status in ("DONE", "CANCELLED"):
            raise ValueError("Work order ini tidak bisa dibatalkan.")

        with transaction.atomic():
            for line in self.material_lines.select_related("part").all():
                StockAdjustment.objects.create(
                    organization=self.organization,
                    part=line.part,
                    quantity_change=line.quantity,
                    reason="work_order_cancelled",
                    notes=f"Pembatalan Work Order {self.number}",
                )
            self.status = "CANCELLED"
            self.save(update_fields=["status", "updated_at"])


class WorkOrderJobLine(TenantScopedModel):
    """
    One numbered row from the paper's "Job Description" table —
    genuinely checkable off as work happens, unlike ServiceRecord's
    single free-text issue_description field it eventually collapses
    into.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order  = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="job_lines", verbose_name="Work Order")
    description = models.CharField(max_length=255, verbose_name="Deskripsi Pekerjaan")
    is_done      = models.BooleanField(default=False, verbose_name="Selesai")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Work Order Job Line"
        verbose_name_plural  = "Work Order Job Lines"
        ordering             = ["created_at"]

    def __str__(self):
        return self.description

    def _resolve_organization(self):
        return self.work_order.organization


class WorkOrderMaterialLine(TenantScopedModel):
    """
    One row from the paper's separate "Material/Item" table. This is
    the sole executor of real-time stock deduction for the whole
    WorkOrder lifecycle — see the module docstring and WorkOrder.close()
    for why nothing else deducts a second time.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order  = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="material_lines", verbose_name="Work Order")
    part        = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="work_order_material_lines", verbose_name="Part")
    quantity    = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah")
    unit_price_at_time = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Saat Digunakan")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Work Order Material Line"
        verbose_name_plural  = "Work Order Material Lines"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.part.name} × {self.quantity} — WO {self.work_order.number}"

    def _resolve_organization(self):
        return self.work_order.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.unit_price_at_time:
            self.unit_price_at_time = self.part.unit_price
        super().save(*args, **kwargs)
        if creating:
            Part.objects.filter(pk=self.part_id).update(
                current_stock=models.F("current_stock") - self.quantity
            )
