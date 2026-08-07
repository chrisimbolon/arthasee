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
  - work_started_at: Made's own request — "jam mulai dikerjakan,"
    the exact clock time a car actually enters work, captured
    automatically the moment SA marks a Work Order "Dikerjakan"
    (IN_PROGRESS). Confirmed with Chris: only meaningful for Work
    Orders that trace back to an approved Estimate — per Made's own
    phrasing ("...jika estimasi disetujui customer") — so a
    direct-entry Work Order with no Estimate origin never gets this
    field populated at all, by design, not by omission.
  - Mechanic / WorkOrderStage.assigned_to / is_overdue: the concrete
    backend for Made's 28 Jul Owner Dashboard requirements. Mechanic
    is deliberately NOT a login-capable user — mechanics still never
    log into the system at all (confirmed fact, unchanged) — it's a
    lightweight roster SA/Made maintains, existing purely so a
    dashboard can answer "how many mechanics are actually working
    right now" with a real, honest denominator instead of a
    fabricated stat (the exact gap Made independently flagged in
    Sansan's mockup: "kenapa mechanic hanya 3 yg kerja? 3 dari 6").
    is_overdue on both WorkOrder and WorkOrderStage is Made's own
    literal example — "ganti oli + kampas rem lebih dari 2 jam" —
    computed on read from real timestamps already captured
    elsewhere, never stored, same discipline as
    Vehicle.is_due_for_service.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from apps.core.models import TenantScopedModel
from apps.inventory.models import Part, PartUsage, StockAdjustment
from django.db import models, transaction
from django.utils import timezone

# Made's own literal example from the 28 Jul meeting — an oil change
# + brake pads taking more than 2 hours. The one, shared default
# threshold for a plain WorkOrder; WorkOrderStage gets its own
# per-stage override below, since a genuinely heavy stage (body
# repair, painting) legitimately takes far longer than routine work
# and shouldn't false-alarm against the same generic number.
DEFAULT_DURATION_ALERT_HOURS = 2


class Mechanic(TenantScopedModel):
    """
    A real, lightweight roster entry — deliberately NOT a login-
    capable user. Mechanics never log into the system (confirmed,
    unchanged) — this exists purely so a dashboard can honestly
    count "how many mechanics are currently working" against a real
    total, rather than the fabricated "3/6" stat Made himself called
    out as unsourced in Sansan's mockup.

    No hard-delete path is exposed via the API on purpose (see
    views.py) — a Mechanic who leaves the shop gets deactivated
    (is_active=False), not deleted, specifically because
    WorkOrderStage.assigned_to would otherwise SET_NULL every
    historical stage they ever worked, silently erasing real "who
    did this" history — the same Principle 2 reasoning already
    applied to Customer/Vehicle deletion, just enforced by omission
    here rather than a ProtectedError guard, since there's no FK
    constraint to violate in the first place.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=200, verbose_name="Nama Mekanik")
    is_active  = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Mechanic"
        verbose_name_plural  = "Mechanics"
        ordering             = ["name"]

    def __str__(self):
        return self.name


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

    # Made's own explicit reason, confirmed 31 Jul: a specific
    # mechanic must be identifiable on every job, even a routine one
    # (his own real example — draining and refilling engine oil) —
    # so he can go back and question that person directly if the
    # same car has a problem again. Deliberately distinct from
    # WorkOrderStage.assigned_to below — that one only exists for
    # heavy, multi-phase jobs and supports several different
    # mechanics across different stages; this one is the single
    # mechanic responsible for the job as a whole, the common case
    # for the overwhelming majority of real work. The two coexist
    # without conflict: a routine job only ever uses this field, a
    # staged job can use both (this field for overall accountability,
    # stages for who did which phase). Nullable at the DB level —
    # the real hard requirement Made asked for ("no invoice creation
    # without mechanic assigned") is enforced at invoice-creation
    # time (see apps.invoicing.models.Invoice.save()), not here, so
    # a WorkOrder can still legitimately exist and even close without
    # one assigned yet.
    assigned_to = models.ForeignKey(
        Mechanic, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="work_orders", verbose_name="Mekanik Penanggung Jawab",
    )

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

    @property
    def is_overdue(self):
        """
        Made's own literal example: a job taking longer than expected
        (his case — oil change + brake pads over 2 hours). Only
        meaningful while genuinely IN_PROGRESS with a real
        work_started_at on record — a WorkOrder still OPEN hasn't
        started yet (nothing to be "overdue" against), and one that's
        DONE/CANCELLED is finished, not overdue. Computed on read,
        never stored — same discipline as Vehicle.is_due_for_service.
        """
        if self.status != "IN_PROGRESS" or self.work_started_at is None:
            return False
        elapsed_hours = (timezone.now() - self.work_started_at).total_seconds() / 3600
        return elapsed_hours >= DEFAULT_DURATION_ALERT_HOURS

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
        # Chris's own catch, 2 Aug — caught live in production: a
        # WorkOrder could jump straight from OPEN to DONE, skipping
        # "Mulai Dikerjakan" entirely. Nothing here previously
        # required a job to have actually started before being
        # closed — a real workflow-integrity gap, not a cosmetic one:
        # "Selesaikan Work Order" and its own Tanggal Servis field
        # both rendered fully enabled the moment a WorkOrder existed,
        # regardless of status. Blocking OPEN here is the real fix;
        # the frontend also stops rendering "Selesaikan Work Order"
        # at all while OPEN, but that's the proactive layer, not the
        # enforcement — this check is what actually stops it.
        if self.status == "OPEN":
            raise ValueError('Work order harus "Mulai Dikerjakan" terlebih dahulu sebelum bisa diselesaikan.')
        # Made's own confirmed real-world rule, 2 Aug — Chris
        # witnessed it directly at Arya Motor: EVERY job goes through
        # QC before being marked done, even a routine oil change or
        # spark plug replacement. Made himself personally does QC on
        # simple jobs — there's no "too small to inspect" exception in
        # the real shop, so there isn't one here either. Closing
        # directly from IN_PROGRESS, skipping "Ajukan Pemeriksaan"
        # entirely, is exactly as wrong as closing directly from OPEN
        # was — just one step further down the same pipeline.
        if self.status == "IN_PROGRESS":
            raise ValueError('Work order harus melalui "Ajukan Pemeriksaan" terlebih dahulu sebelum bisa diselesaikan.')
        # Made's own explicit rule, 4 Aug meeting: "Harus dicegat
        # penerbitan WO selesai tanpa mekanik!" — no orphan
        # completions. Item 22 (31 Jul) already blocked this at
        # INVOICE-creation time (Invoice.save() itself), but that
        # only caught the problem downstream, after a mechanic-less
        # WorkOrder had already reached DONE — confirmed live: a real
        # WorkOrder closed with no assigned_to, and the block only
        # ever fired later, at the "Buat Invoice" step. This is the
        # real fix, catching it at the source. Invoice.save()'s own
        # check stays — deliberately not redundant, since a bare
        # ServiceRecord with no WorkOrder origin at all (see its own
        # getattr/RelatedObjectDoesNotExist handling) can still exist
        # completely outside this method and needs its own guard.
        if self.assigned_to is None:
            raise ValueError("Work order belum memiliki mekanik penanggung jawab — tidak bisa diselesaikan.")

        with transaction.atomic():
            job_lines = list(self.job_lines.all())
            material_lines = list(self.material_lines.select_related("part").all())

            # Chris's own catch, 2 Aug — caught live via a real
            # customer-facing tracking link: a WorkOrder could reach
            # DONE while one of its own stages still sat at "Menunggu"
            # (never explicitly started/completed via "Mulai Tahap"/
            # "Selesaikan Tahap") — stage lifecycle and job-line
            # completion are two entirely separate, unlinked concepts
            # in this codebase, and nothing wired them together.
            # Internally this was mostly invisible (SA/Made see the
            # real checked job lines regardless of a stage's own
            # formal status), but the public tracking page only shows
            # stage-level status — a customer would see "Selesai" on
            # the overall job sitting right next to a stage that says
            # "Menunggu," a real, visible contradiction.
            #
            # Deliberately NOT calling stage.start()/stage.complete()
            # here — both require self.status == "IN_PROGRESS" (see
            # WorkOrderStage.start()'s own docstring), but by this
            # point in close() the WorkOrder is already at QC (that
            # transition is itself required before close() can even
            # run — see the IN_PROGRESS check above). Setting the
            # timestamps directly instead, same first-time-wins spirit
            # as start()/complete() themselves: a stage genuinely
            # already completed keeps its real, earlier timestamp;
            # only a stage still open gets backfilled, and it gets
            # both started_at and completed_at together since there's
            # no real way to know when it actually began — same
            # reasoning complete()'s own auto-start fallback already
            # uses. bulk_update(), not a loop of .save() calls — same
            # "no per-instance side effects to preserve" reasoning
            # already established for PartUsage.bulk_create() below.
            now = timezone.now()
            stages_to_backfill = []
            for stage in self.stages.all():
                changed = False
                if stage.started_at is None:
                    stage.started_at = now
                    changed = True
                if stage.completed_at is None:
                    stage.completed_at = now
                    changed = True
                if changed:
                    stages_to_backfill.append(stage)
            if stages_to_backfill:
                WorkOrderStage.objects.bulk_update(stages_to_backfill, ["started_at", "completed_at"])

            # Same real risk, now for job lines too — Chris's own
            # extension of the fix above, 4 Aug: once job-line timing
            # became customer-visible (Made's own confirmed request
            # for per-step "jam mulai – jam selesai"), a WorkOrder
            # reaching DONE with an item still stuck at "Menunggu"
            # became exactly the same visible contradiction the stage
            # fix already solved, one level down. In the normal API-
            # driven flow every job line is already completed by the
            # time close() runs (the QC gate itself requires it), but
            # close() is also reachable directly via the ORM (tests,
            # scripts) bypassing that gate — this is real defense in
            # depth, not redundant with the QC check.
            job_lines_to_backfill = []
            for line in job_lines:
                changed = False
                if line.started_at is None:
                    line.started_at = now
                    changed = True
                if line.completed_at is None:
                    line.completed_at = now
                    changed = True
                if changed:
                    job_lines_to_backfill.append(line)
            if job_lines_to_backfill:
                WorkOrderJobLine.objects.bulk_update(job_lines_to_backfill, ["started_at", "completed_at"])

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

            # Sprint 2, Task 2.1 — total is exactly what apps.accounting's
            # future posting rule needs for Dr COGS Sparepart (5001) /
            # Cr WIP (1302). Computed from the same material_lines list
            # already collected earlier in this method — not a second
            # query. Summed here, not inside WorkOrderCompleted itself,
            # so the event class stays a plain data container with no
            # business logic of its own. Published even when material_
            # lines is empty (a labor-only job) — see
            # apps.workorders.events.WorkOrderCompleted's own docstring
            # for why that's a deliberate call, not an oversight.
            # Local imports, same established convention as the
            # cross-app ServiceRecord import at the top of this method,
            # and PartConsumed's own publish call in
            # WorkOrderMaterialLine.save().
            from apps.core.events.bus import default_bus
            from apps.workorders.events import WorkOrderCompleted
            total_amount = sum(
                (line.quantity * line.unit_price_at_time for line in material_lines),
                Decimal("0"),
            )
            default_bus.publish(WorkOrderCompleted(
                organization_id=self.organization_id,
                work_order_id=self.id,
                service_record_id=record.id,
                amount=total_amount,
                material_line_count=len(material_lines),
            ))

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
    # SET_NULL, not PROTECT/CASCADE — a Mechanic leaving the roster
    # (deactivated, never hard-deleted — see Mechanic's own docstring)
    # should never block or cascade-delete a real historical stage
    # record. Optional: Made's own diagram showed real assignment,
    # but nothing about starting/completing a stage requires one —
    # same "trust human judgment, don't force data entry" philosophy
    # as completing a stage never requiring all its job lines done.
    assigned_to = models.ForeignKey(
        Mechanic, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stages", verbose_name="Dikerjakan Oleh",
    )
    # Nullable override of the module-level DEFAULT_DURATION_ALERT_HOURS
    # — a genuinely heavy stage (body repair, painting) legitimately
    # takes far longer than routine work and shouldn't false-alarm
    # against the same generic 2-hour default a plain WorkOrder uses.
    expected_duration_hours = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
        verbose_name="Estimasi Durasi (Jam)",
    )
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

        Also cascades: starting a stage auto-starts its first
        sequential job line too (Made's own confirmed distinction,
        5 Aug — see _cascade_start_first_job_line() below).
        """
        if self.work_order.status != "IN_PROGRESS":
            raise ValueError('Work order harus berstatus "Dikerjakan" sebelum tahap bisa dimulai.')
        if self.started_at is not None:
            return
        self.started_at = timezone.now()
        self._cascade_start_first_job_line()

    def _cascade_start_first_job_line(self):
        """
        Made's own confirmed distinction, 5 Aug: a sequential staged
        job (bongkar -> pasang -> uji, one at a time) is a genuinely
        different shape of work than parallel, independently-
        clickable items — clicking "Mulai Tahap" already means "I'm
        starting the first real task," not two separate clicks for
        the same real moment. Auto-starts the first not-yet-started
        job line under this stage, by creation order (Chris's own
        confirmed call for v1 — no explicit sequence field needed
        yet).

        Explicitly saves the cascaded job line here, not left to the
        caller — WorkOrderStage.start() itself only ever saves the
        stage's own fields, and this method reaches into a genuinely
        different model instance the caller has no reason to know
        changed.
        """
        first_line = self.job_lines.filter(started_at__isnull=True).order_by("created_at").first()
        if first_line:
            first_line.start()
            first_line.save(update_fields=["started_at"])

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

    @property
    def is_overdue(self):
        """
        Uses this stage's own expected_duration_hours if set,
        otherwise falls back to the same DEFAULT_DURATION_ALERT_HOURS
        a plain WorkOrder uses. Only meaningful while genuinely
        in-progress (started, not yet completed) — a stage that
        never started can't be overdue, and a completed one is done,
        not overdue, regardless of how long it actually took.
        """
        if self.started_at is None or self.completed_at is not None:
            return False
        threshold = (
            self.expected_duration_hours
            if self.expected_duration_hours is not None
            else DEFAULT_DURATION_ALERT_HOURS
        )
        elapsed_hours = (timezone.now() - self.started_at).total_seconds() / 3600
        return elapsed_hours >= float(threshold)


class WorkOrderJobLine(TenantScopedModel):
    """
    One numbered row from the paper's "Job Description" table —
    genuinely checkable off as work happens, unlike ServiceRecord's
    single free-text issue_description field it eventually collapses
    into.

    Made's own confirmed handwritten note, 4 Aug: "Pekerjaan bertahap:
    jam mulai – jam selesai" — multi-step work needs a real start
    time AND end time per step, not just a done/not-done flag. Real
    started_at/completed_at now, mirroring WorkOrderStage's own exact
    shape and semantics (start()/complete(), same IN_PROGRESS
    precondition, same first-time-wins). Chris's own explicit call,
    same day: this now shows on the CUSTOMER-facing tracking page too
    (a badly-damaged car's owner genuinely wants to see "bongkar
    done, parts on order now" — a real, separate scope decision from
    Made's note itself, not something to quietly infer from one line
    about timestamps) — see apps.customers.payload's own comment for
    where that's wired in.

    is_done deliberately removed as a stored field, not just renamed
    — Option B, Chris's own explicit call: a payload served to a
    customer needs ONE honest number, not a boolean and a timestamp
    that could theoretically drift apart. completed_at is now the
    only real stored fact; is_done below is a read-only property
    derived from it, purely so code that only ever READS the concept
    ("is this done?") doesn't need rewriting — anything that used to
    WRITE is_done=True must now call complete() instead.
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
    started_at   = models.DateTimeField(null=True, blank=True, verbose_name="Mulai")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Selesai")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Work Order Job Line"
        verbose_name_plural  = "Work Order Job Lines"
        ordering             = ["created_at"]

    def __str__(self):
        return self.description

    def _resolve_organization(self):
        return self.work_order.organization

    @property
    def is_done(self):
        # Read-only, derived — never assign to this. See the class
        # docstring's own Option B reasoning for why completed_at is
        # the only real stored fact now.
        return self.completed_at is not None

    def start(self):
        """
        Mirrors WorkOrderStage.start() exactly — same precondition,
        same first-time-wins, same in-memory-only (caller saves).
        Real reason for the IN_PROGRESS requirement here too: a job
        line's own start time landing before the WorkOrder's overall
        work_started_at would be the same incoherent-timeline problem
        stages already guard against.
        """
        if self.work_order.status != "IN_PROGRESS":
            raise ValueError('Work order harus berstatus "Dikerjakan" sebelum item bisa dimulai.')
        if self.started_at is not None:
            return
        self.started_at = timezone.now()

    def complete(self):
        """
        Mirrors WorkOrderStage.complete() exactly — auto-starts
        first if never explicitly started, first-time-wins on
        completed_at itself. Also cascades: finishing one sequential
        job line auto-starts the next one in the same stage (Made's
        own confirmed distinction, 5 Aug — see
        _cascade_start_next_sibling() below).
        """
        if self.started_at is None:
            self.start()
        if self.completed_at is not None:
            return
        self.completed_at = timezone.now()
        self._cascade_start_next_sibling()

    def _cascade_start_next_sibling(self):
        """
        Made's own confirmed distinction, 5 Aug: sequential staged
        work (bongkar -> pasang -> uji) should flow automatically —
        checking off one step is the same real moment as starting the
        next, not two separate clicks. Deliberately a SOFT cascade
        only, Chris's own explicit call: finding the next not-yet-
        started sibling and starting it is a convenience, not a hard
        sequence lock. Nothing stops a mechanic starting a later item
        directly (a part arrives early, work genuinely happens out of
        order) — that's real shop-floor fluidity, not a bug to guard
        against.

        Unstaged job lines (stage_id is None) are untouched — Made's
        own explicit distinction: only genuinely sequential, staged
        work cascades. Independent, parallel items keep behaving
        exactly as they already do.

        Explicitly saves the cascaded sibling here, not left to the
        caller — same reasoning as WorkOrderStage's own
        _cascade_start_first_job_line(): the caller only knows to
        save `self`, not a different model instance this method
        reaches into.
        """
        if not self.stage_id:
            return
        next_line = (
            WorkOrderJobLine.objects
            .filter(stage_id=self.stage_id, started_at__isnull=True)
            .exclude(pk=self.pk)
            .order_by("created_at")
            .first()
        )
        if next_line:
            next_line.start()
            next_line.save(update_fields=["started_at"])

    def reset(self):
        """
        NOT mirrored from WorkOrderStage — stages have no equivalent.
        Added specifically for the job-line 3-state click cycle
        (Menunggu -> Sedang Berjalan -> Selesai -> back to Menunggu):
        a mechanic correcting a mistake needs a real way back to the
        start, not a dead end at "Selesai." Clears both timestamps
        together — an item can't be "half reset," genuinely back to
        not-yet-started or nothing.
        """
        self.started_at = None
        self.completed_at = None

    @property
    def is_locked(self):
        """
        Chris's own explicit ask, 2 Aug: a job line had no way to fix
        a typo or remove a wrongly-added item at all — only toggle()
        and stage-reassignment existed. Editable/deletable while
        genuinely in flight, frozen once the work it describes is
        actually done — same "frozen record" discipline already
        applied to Invoice snapshots and a closed WorkOrder elsewhere
        in this codebase.

        Two separate lock conditions, not one: the whole WorkOrder
        being DONE/CANCELLED locks everything (matches the existing
        OPEN_STATUSES check already used by toggle()/assign-stage()),
        but a line grouped under its own already-COMPLETED stage
        locks too, even while the WorkOrder overall still has other,
        genuinely open stages left — a finished stage's own checklist
        shouldn't stay editable just because a sibling stage is still
        in progress.
        """
        if self.work_order.status in ("DONE", "CANCELLED"):
            return True
        if self.stage_id and self.stage.completed_at is not None:
            return True
        return False


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
            # Sprint 2, Task 2.1 — the F() deduction directly above IS
            # the real-world event PartConsumed describes. Published
            # here, not from apps.inventory, because this is the one
            # place that deduction actually happens — see
            # apps.inventory.events.PartConsumed's own module
            # docstring for the full reasoning. Local imports, same
            # established convention as WorkOrder.close()'s own
            # cross-app import of ServiceRecord — kept local to the
            # one method that needs them, not module-level, so the
            # dependency direction stays obvious without hunting
            # through the whole file.
            from apps.core.events.bus import default_bus
            from apps.inventory.events import PartConsumed
            default_bus.publish(PartConsumed(
                organization_id=self.organization_id,
                part_id=self.part_id,
                work_order_id=self.work_order_id,
                material_line_id=self.id,
                quantity=self.quantity,
                unit_price_at_time=self.unit_price_at_time,
                amount=self.quantity * self.unit_price_at_time,
            ))