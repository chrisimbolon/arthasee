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
  - work_started_at: Made's own request — "jam mulai dikerjakan,"
    the exact clock time a car actually enters work, captured
    automatically the moment SA marks a Work Order "Dikerjakan"
    (IN_PROGRESS). Confirmed with Chris: only meaningful for Work
    Orders that trace back to an approved Estimate — per Made's own
    phrasing ("...jika estimasi disetujui customer") — so a
    direct-entry Work Order with no Estimate origin never gets this
    field populated at all, by design, not by omission.
"""
import uuid
from datetime import date

from apps.core.models import TenantScopedModel
from apps.inventory.models import Part, PartUsage, StockAdjustment
from django.db import models, transaction
from django.utils import timezone


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

    # Made's own request: the exact clock time work actually began —
    # not just the date. Nullable and set at most once — see
    # mark_started() below for exactly when and why. Deliberately a
    # plain DateTimeField on WorkOrder itself, not a new model: this
    # is one fact about one WorkOrder, not a repeating event needing
    # its own history.
    work_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Jam Mulai Dikerjakan")

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

    def mark_started(self):
        """
        Sets work_started_at on the in-memory instance — deliberately
        does NOT call save() itself. The one caller (the status-
        transition view) is already about to save() the status change
        in the same request; doing so here too would mean two writes
        for one real event instead of one. The caller is responsible
        for including "work_started_at" in its own update_fields.

        First-time-wins: silently does nothing if already set, so a
        WorkOrder that somehow cycles IN_PROGRESS -> OPEN ->
        IN_PROGRESS again never has its original start time overwritten
        by a later re-entry into the same status.

        Deliberately a no-op for a WorkOrder with no Estimate origin —
        per Made's own words, this concept only applies to a Work
        Order born from an approved Estimate. getattr(self, "estimate",
        None) is the same reverse-OneToOneField probe already used
        throughout this project (ServiceRecordSerializer's own
        get_original_estimate_total, most directly) — Django's
        RelatedObjectDoesNotExist is deliberately a subclass of
        AttributeError specifically so this works without a
        try/except.
        """
        if self.work_started_at is not None:
            return
        if getattr(self, "estimate", None) is None:
            return
        self.work_started_at = timezone.now()

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


class WorkOrderStage(TenantScopedModel):
    """
    A custom, optional, higher-level grouping of job lines — Made's
    own request, confirmed with Chris: for a heavy-damage repair
    (collision, overhaul) that genuinely happens in distinct phases
    (e.g. body work, painting, reassembly), each phase gets tracked
    as its own named stage with its own start/complete timestamps.

    Deliberately additive, not a replacement for anything already
    proven: a routine, single-visit repair (the overwhelming
    majority of jobs) never touches this table at all — its
    WorkOrder.job_lines stay exactly as flat and simple as they
    already are. Stages only exist when someone actually creates
    one for a specific job that needs the finer granularity.

    Also deliberately NOT the same concept as WorkOrder.status
    (OPEN/IN_PROGRESS/QC/DONE/CANCELLED) — status is the generic
    pipeline position every WorkOrder has; stages are a custom,
    per-repair breakdown of what's actually happening inside
    IN_PROGRESS for THIS specific job. A WorkOrder can have zero
    stages (routine jobs) or several custom ones (a collision job),
    completely independent of its status.

    name/sequence are free text/plain ordering, not a fixed
    taxonomy — confirmed with Chris this is defined fresh per
    repair, not a standard list every job must follow.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order  = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="stages", verbose_name="Work Order")
    name        = models.CharField(max_length=255, verbose_name="Nama Tahap")
    sequence    = models.PositiveIntegerField(verbose_name="Urutan")
    # First-time-wins, same pattern as WorkOrder.work_started_at —
    # see start()/complete() below.
    started_at   = models.DateTimeField(null=True, blank=True, verbose_name="Mulai")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Selesai")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Work Order Stage"
        verbose_name_plural  = "Work Order Stages"
        ordering             = ["sequence", "created_at"]

    def __str__(self):
        return f"{self.name} — WO {self.work_order.number}"

    def _resolve_organization(self):
        return self.work_order.organization

    def start(self):
        """
        Sets started_at in memory — does not save(). Same reasoning
        as WorkOrder.mark_started(): the caller is already about to
        save() in the same request, avoiding two writes for one
        event. First-time-wins: a stage re-entered later (unlikely,
        but not prevented) never has its original start silently
        overwritten.

        Raises ValueError if the parent WorkOrder hasn't actually
        reached IN_PROGRESS yet — confirmed with Chris after a real
        ordering inconsistency showed up in testing: nothing
        previously stopped a stage from starting while the WO itself
        was still just OPEN, producing a stage's own start time
        landing BEFORE WorkOrder.work_started_at, which undermines
        the entire point of a coherent, trustworthy timeline. Keeps
        the ordering guaranteed by construction: work overall always
        starts before any of its sub-phases can.
        """
        if self.work_order.status != "IN_PROGRESS":
            raise ValueError('Work order harus berstatus "Dikerjakan" sebelum tahap bisa dimulai.')
        if self.started_at is not None:
            return
        self.started_at = timezone.now()

    def complete(self):
        """
        Sets completed_at in memory — does not save(). Auto-starts
        first if somehow marked complete without ever being
        explicitly started: a stage that's clearly finished deserves
        a real (if slightly late) start time on record rather than
        none at all, matching the spirit of never leaving a genuinely
        real event untracked. First-time-wins on completed_at itself,
        same as start().

        Deliberately routes through self.start() for that auto-start,
        rather than setting started_at directly — this is what makes
        the IN_PROGRESS requirement above apply here too, with no
        separate check to keep in sync. Without this, calling
        complete() directly on a never-started stage would be a
        silent loophole around the exact rule start() just enforced.
        """
        if self.started_at is None:
            self.start()
        if self.completed_at is not None:
            return
        self.completed_at = timezone.now()


class WorkOrderJobLine(TenantScopedModel):
    """
    One numbered row from the paper's "Job Description" table —
    genuinely checkable off as work happens, unlike ServiceRecord's
    single free-text issue_description field it eventually collapses
    into.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order  = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="job_lines", verbose_name="Work Order")
    # Nullable, optional — most job lines never belong to a stage at
    # all (see WorkOrderStage's own docstring). SET_NULL rather than
    # CASCADE: deleting a stage removes the grouping, never the real
    # checklist items underneath it — a job line that already
    # happened doesn't stop being real history just because its
    # organizational label went away.
    stage       = models.ForeignKey(
        WorkOrderStage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="job_lines", verbose_name="Tahap",
    )
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
